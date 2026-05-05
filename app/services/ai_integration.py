import threading
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

import httpx
from sqlalchemy import and_, desc, func, select
from sqlalchemy.orm import Session

from app.config import settings
from app.database import SessionLocal
from app.models import AIAnalysisResult, Device, DeviceCatalog, EnergyReading, TariffLookupByVA, Unit
from app.utils.time import utc_now


class ExternalAIClient:
    def __init__(self):
        self.base_url = settings.ai_base_url.rstrip("/")
        self.timeout = settings.ai_timeout_seconds
        self.retry_count = max(0, settings.ai_retry_count)

    def health(self) -> Dict[str, Any]:
        if not settings.ai_enabled:
            return {"status": "disabled"}
        with httpx.Client(timeout=self.timeout) as client:
            r = client.get(f"{self.base_url}/health")
            r.raise_for_status()
            return r.json()

    def analyze(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        last_err = None
        for _ in range(self.retry_count + 1):
            try:
                with httpx.Client(timeout=self.timeout) as client:
                    r = client.post(f"{self.base_url}/analyze", json=payload)
                    r.raise_for_status()
                    return r.json()
            except Exception as exc:
                last_err = exc
        raise last_err


class AIOrchestrator:
    _DEFAULT_DEVICE_POWER_WATT = {
        "ac": 900.0,
        "ac-main": 900.0,
        "lamp": 20.0,
        "tv": 120.0,
        "charger": 65.0,
        "washing_machine": 800.0,
        "water_heater": 1500.0,
        "smart_fan": 60.0,
    }

    def __init__(self):
        self.client = ExternalAIClient()
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()

    def _tariff_for_unit(self, db: Session, unit: Unit) -> float:
        row = db.execute(select(TariffLookupByVA).where(TariffLookupByVA.va == unit.va)).scalar_one_or_none()
        if row:
            return float(row.tariff_per_kwh)
        fallback = db.execute(select(TariffLookupByVA).order_by(desc(TariffLookupByVA.va))).scalars().first()
        return float(fallback.tariff_per_kwh) if fallback else 1444.0

    def _build_device_map(
        self,
        devices: list[Device],
        catalog_power_watt: Dict[str, float],
        live_power_kw: Dict[str, float],
    ) -> Dict[str, Any]:
        device_map: Dict[str, Any] = {}
        for d in devices:
            hours = None
            if d.schedules and isinstance(d.schedules, list):
                hours = []
                for entry in d.schedules:
                    if isinstance(entry, dict):
                        if "hours" in entry and isinstance(entry["hours"], list):
                            hours.extend([int(x) for x in entry["hours"] if isinstance(x, int)])
                        else:
                            start = entry.get("start_hour")
                            end = entry.get("end_hour")
                            if isinstance(start, int) and isinstance(end, int):
                                if end >= start:
                                    hours.extend(list(range(start, end + 1)))
                                else:
                                    hours.extend(list(range(start, 24)) + list(range(0, end + 1)))
                hours = sorted(list(set(hours))) if hours else None

            power_kw = float(live_power_kw.get(d.device_id, 0.0))
            if power_kw <= 0:
                # Catalog stores watt, AI contract expects kW for device power.
                catalog_watt = float(catalog_power_watt.get(d.device_id, 0.0))
                if catalog_watt <= 0 and "-" in d.device_id:
                    catalog_watt = float(catalog_power_watt.get(d.device_id.split("-")[0], 0.0))
                if catalog_watt <= 0:
                    catalog_watt = float(self._DEFAULT_DEVICE_POWER_WATT.get(d.device_id, 0.0))
                power_kw = catalog_watt / 1000.0

            device_map[d.device_id] = {
                "state": power_kw > 0,
                "power": round(power_kw, 4),
                "controllable": bool(d.controllable),
            }
            if hours is not None:
                device_map[d.device_id]["schedule"] = {"hours": hours}
        return device_map

    def _estimate_base_load_kwh(
        self,
        db: Session,
        community_id: str,
        unit_id: str,
        bucket_start: datetime,
    ) -> float:
        lookback_start = bucket_start - timedelta(hours=24)
        value = db.execute(
            select(func.coalesce(func.avg(EnergyReading.kwh), 0.0)).where(
                and_(
                    EnergyReading.community_id == community_id,
                    EnergyReading.unit_id == unit_id,
                    EnergyReading.timestamp >= lookback_start,
                    EnergyReading.timestamp < bucket_start,
                )
            )
        ).scalar_one()
        return round(float(value), 4)

    def _community_hour_buckets(self, db: Session, community_id: str, limit: int) -> list[datetime]:
        bucket_expr = func.date_trunc("hour", EnergyReading.timestamp)
        rows = db.execute(
            select(bucket_expr.label("bucket"))
            .where(EnergyReading.community_id == community_id)
            .group_by(bucket_expr)
            .order_by(desc("bucket"))
            .limit(limit)
        ).all()
        buckets = [r.bucket for r in rows if r.bucket]
        buckets.sort()
        return buckets

    def build_snapshot_payloads_for_community(
        self,
        db: Session,
        community_id: str,
        max_hours: int = 1,
    ) -> List[Dict[str, Any]]:
        units = db.execute(select(Unit).where(Unit.community_id == community_id)).scalars().all()
        if not units:
            return []
        devices_by_unit_id: Dict[int, list[Device]] = {}
        for unit in units:
            devices_by_unit_id[unit.id] = db.execute(select(Device).where(Device.unit_id == unit.id)).scalars().all()
        catalog_rows = db.execute(select(DeviceCatalog).where(DeviceCatalog.is_active.is_(True))).scalars().all()
        catalog_power_watt = {row.device_key: float(row.default_power_watt or 0.0) for row in catalog_rows}

        buckets = self._community_hour_buckets(db, community_id, max_hours)
        payloads: List[Dict[str, Any]] = []
        for bucket in buckets:
            bucket_end = bucket + timedelta(hours=1)
            unit_payloads = []
            for unit in units:
                consumption = db.execute(
                    select(func.coalesce(func.sum(EnergyReading.kwh), 0.0)).where(
                        and_(
                            EnergyReading.community_id == community_id,
                            EnergyReading.unit_id == unit.unit_id,
                            EnergyReading.timestamp >= bucket,
                            EnergyReading.timestamp < bucket_end,
                        )
                    )
                ).scalar_one()
                power_rows = db.execute(
                    select(
                        EnergyReading.device_id,
                        func.coalesce(func.avg(EnergyReading.power_watt), 0.0).label("avg_power_watt"),
                    )
                    .where(
                        and_(
                            EnergyReading.community_id == community_id,
                            EnergyReading.unit_id == unit.unit_id,
                            EnergyReading.timestamp >= bucket,
                            EnergyReading.timestamp < bucket_end,
                        )
                    )
                    .group_by(EnergyReading.device_id)
                ).all()
                live_power_kw = {str(r.device_id): float(r.avg_power_watt or 0.0) / 1000.0 for r in power_rows}
                unit_payloads.append(
                    {
                        "unit_id": unit.unit_id,
                        "tariff": self._tariff_for_unit(db, unit),
                        "base_load_kwh": self._estimate_base_load_kwh(db, community_id, unit.unit_id, bucket),
                        "consumption_kwh": float(consumption),
                        "devices": self._build_device_map(
                            devices_by_unit_id.get(unit.id, []),
                            catalog_power_watt=catalog_power_watt,
                            live_power_kw=live_power_kw,
                        ),
                    }
                )
            payloads.append(
                {
                    "community_id": community_id,
                    "timestamp": bucket.isoformat(),
                    "units": unit_payloads,
                }
            )
        return payloads

    def build_snapshot_payloads(self, db: Session, max_hours_per_community: int = 1) -> List[Dict[str, Any]]:
        community_rows = db.execute(select(EnergyReading.community_id).distinct()).all()
        payloads: List[Dict[str, Any]] = []
        for (community_id,) in community_rows:
            payloads.extend(
                self.build_snapshot_payloads_for_community(
                    db,
                    community_id,
                    max_hours=max_hours_per_community,
                )
            )
        return payloads

    def run_once_for_community(self, community_id: str, source: str = "manual") -> Dict[str, Any]:
        db = SessionLocal()
        try:
            max_hours = 24 if source == "manual" else 1
            payloads = self.build_snapshot_payloads_for_community(db, community_id, max_hours=max_hours)
            if not payloads:
                raise ValueError(f"No snapshot data for community {community_id}")
            success_count = 0
            last_success_result: Dict[str, Any] = {}
            last_error = ""
            for payload in payloads:
                try:
                    result = self.client.analyze(payload)
                    row = AIAnalysisResult(
                        community_id=community_id,
                        status="success",
                        stale=False,
                        source=source,
                        payload=payload,
                        result=result,
                        error="",
                    )
                    db.add(row)
                    db.commit()
                    success_count += 1
                    last_success_result = result
                except Exception as exc:
                    last_error = str(exc)
                    row = AIAnalysisResult(
                        community_id=community_id,
                        status="failed",
                        stale=True,
                        source=source,
                        payload=payload,
                        result=(last_success_result if last_success_result else {}),
                        error=last_error,
                    )
                    db.add(row)
                    db.commit()

            if success_count > 0:
                return {
                    "status": "success",
                    "community_id": community_id,
                    "result": last_success_result,
                    "stale": False,
                    "processed_samples": len(payloads),
                    "successful_samples": success_count,
                }
            return {
                "status": "failed",
                "community_id": community_id,
                "stale": True,
                "error": last_error or "AI analyze failed for all samples",
                "result": {},
                "processed_samples": len(payloads),
                "successful_samples": 0,
            }
        finally:
            db.close()

    def run_once_all(self, source: str = "manual") -> Dict[str, Any]:
        db = SessionLocal()
        try:
            max_hours = 24 if source == "manual" else 1
            payloads = self.build_snapshot_payloads(db, max_hours_per_community=max_hours)
            communities = [p["community_id"] for p in payloads]
        finally:
            db.close()

        results = [self.run_once_for_community(cid, source=source) for cid in sorted(set(communities))]
        return {"status": "ok", "communities": results, "count": len(results)}

    def get_last_result(self, community_id: str) -> Dict[str, Any]:
        db = SessionLocal()
        try:
            row = db.execute(
                select(AIAnalysisResult)
                .where(AIAnalysisResult.community_id == community_id)
                .order_by(desc(AIAnalysisResult.analyzed_at))
            ).scalars().first()
            if not row:
                return {"community_id": community_id, "exists": False}
            return {
                "community_id": community_id,
                "exists": True,
                "analyzed_at": row.analyzed_at.isoformat(),
                "status": row.status,
                "stale": row.stale,
                "error": row.error,
                "source": row.source,
                "result": row.result,
            }
        finally:
            db.close()

    def get_status(self, community_id: str) -> Dict[str, Any]:
        db = SessionLocal()
        try:
            last_row = db.execute(
                select(AIAnalysisResult)
                .where(AIAnalysisResult.community_id == community_id)
                .order_by(desc(AIAnalysisResult.analyzed_at))
            ).scalars().first()
            last_success = db.execute(
                select(AIAnalysisResult)
                .where(and_(AIAnalysisResult.community_id == community_id, AIAnalysisResult.status == "success"))
                .order_by(desc(AIAnalysisResult.analyzed_at))
            ).scalars().first()

            try:
                healthy = bool(self.client.health().get("status") == "ok")
            except Exception:
                healthy = False

            if not last_row:
                return {
                    "community_id": community_id,
                    "exists": False,
                    "healthy": healthy,
                    "last_run_at": None,
                    "last_success_at": None,
                    "stale": True,
                    "error": "",
                    "source": "unknown",
                }

            return {
                "community_id": community_id,
                "exists": True,
                "healthy": healthy,
                "last_run_at": last_row.analyzed_at.isoformat(),
                "last_success_at": last_success.analyzed_at.isoformat() if last_success else None,
                "stale": bool(last_row.stale),
                "error": last_row.error or "",
                "source": last_row.source or "unknown",
            }
        finally:
            db.close()

    def scheduler_start(self):
        if not settings.ai_enabled:
            return
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()

        def _loop():
            while not self._stop.is_set():
                try:
                    self.run_once_all(source="scheduler")
                except Exception as exc:
                    print(f"[AI-SCHEDULER][ERROR] {exc}")
                self._stop.wait(settings.ai_scheduler_interval_seconds)

        self._thread = threading.Thread(target=_loop, daemon=True)
        self._thread.start()

    def scheduler_stop(self):
        self._stop.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2)


ai_orchestrator = AIOrchestrator()
