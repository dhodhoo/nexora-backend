from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import and_, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import settings
from app.models import Community, DeadLetter, Device, DeviceStateHistory, EnergyReading, Unit
from app.schemas import ConsumptionEvent
from app.services.tariff import TariffService
from app.services.realtime_ws import dashboard_ws_manager
from app.utils.time import assume_utc, utc_now


class IngestionService:
    @staticmethod
    def _to_utc(dt: datetime) -> datetime:
        return assume_utc(dt).replace(tzinfo=None)

    @staticmethod
    def ingest_event(db: Session, payload: dict, topic: str) -> None:
        try:
            event = ConsumptionEvent(**payload)
            if event.kwh is None and event.power_watt is None:
                raise ValueError("Either kwh or power_watt must be provided")
            kwh = event.kwh if event.kwh is not None else event.power_watt / 1000.0
            timestamp = IngestionService._to_utc(event.timestamp)

            community = db.execute(select(Community).where(Community.community_id == event.community_id)).scalar_one_or_none()
            if not community:
                community = Community(community_id=event.community_id, name=event.community_id)
                db.add(community)
                db.flush()

            unit = db.execute(
                select(Unit).where(and_(Unit.community_id == event.community_id, Unit.unit_id == event.unit_id))
            ).scalar_one_or_none()
            if not unit:
                unit = Unit(community_id=event.community_id, unit_id=event.unit_id, va=1300)
                db.add(unit)
                db.flush()

            tariff = TariffService.get_tariff_by_va(db, unit.va)

            device = db.execute(
                select(Device).where(and_(Device.unit_id == unit.id, Device.device_id == event.device_id))
            ).scalar_one_or_none()
            if not device:
                device = Device(
                    unit_id=unit.id,
                    device_id=event.device_id,
                    controllable=event.controllable,
                    schedules=[s.model_dump() for s in event.schedules] if event.schedules else None,
                )
                db.add(device)
                db.flush()
            else:
                new_schedules = [s.model_dump() for s in event.schedules] if event.schedules else None
                if device.controllable != event.controllable or device.schedules != new_schedules:
                    device.controllable = event.controllable
                    device.schedules = new_schedules
                    db.add(
                        DeviceStateHistory(
                            device_pk=device.id,
                            controllable=event.controllable,
                            schedules=new_schedules,
                        )
                    )

            reading = EnergyReading(
                community_id=event.community_id,
                unit_id=event.unit_id,
                device_id=event.device_id,
                timestamp=timestamp,
                kwh=float(kwh),
                power_watt=event.power_watt,
                tariff_per_kwh=tariff,
                estimated_cost=float(kwh) * tariff,
                raw_payload=payload,
            )
            db.add(reading)
            db.commit()
            print(f"[INGEST][RECEIVED] topic={topic} unit={event.unit_id} device={event.device_id}")
            try:
                dashboard_ws_manager.notify_community_update(event.community_id)
            except Exception as notify_exc:
                print(f"[WS][NOTIFY_FAILED] community={event.community_id} reason={notify_exc}")
        except IntegrityError:
            db.rollback()
            print(f"[INGEST][DUPLICATE] topic={topic}")
        except Exception as exc:
            db.rollback()
            db.add(DeadLetter(topic=topic, reason=str(exc), raw_payload=str(payload)))
            db.commit()
            print(f"[INGEST][REJECTED] topic={topic} reason={exc}")


class QueryService:
    @staticmethod
    def freshness(last_timestamp: Optional[datetime]) -> bool:
        if not last_timestamp:
            return False

        last_utc = assume_utc(last_timestamp)
        return last_utc >= (utc_now() - timedelta(minutes=10))

    @staticmethod
    def risk_label(peak_kwh: float) -> str:
        if peak_kwh >= 3.0:
            return "critical"
        if peak_kwh >= 1.5:
            return "high"
        return "normal"

    @staticmethod
    def emission(kwh: float) -> float:
        return kwh * settings.emission_factor_kg_co2e_per_kwh

    @staticmethod
    def last_hour_kwh(db: Session, community_id: str, unit_id: str) -> float:
        row = db.execute(
            select(func.coalesce(func.sum(EnergyReading.kwh), 0.0)).where(
                and_(EnergyReading.community_id == community_id, EnergyReading.unit_id == unit_id)
            )
        ).scalar_one()
        return float(row)
