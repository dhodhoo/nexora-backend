import threading
import time
from datetime import datetime
from typing import Any, Dict, List, Optional

import httpx
from sqlalchemy import and_, desc, func, select
from sqlalchemy.orm import Session

from app.config import settings
from app.database import SessionLocal
from app.models import AIAnalysisResult, Device, EnergyReading, TariffLookupByVA, Unit
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

    def build_snapshot_payloads(self, db: Session) -> List[Dict[str, Any]]:
        community_rows = db.execute(select(EnergyReading.community_id).distinct()).all()
        payloads: List[Dict[str, Any]] = []

        for (community_id,) in community_rows:
            latest_ts = db.execute(
                select(func.max(EnergyReading.timestamp)).where(EnergyReading.community_id == community_id)
            ).scalar_one_or_none()
            if not latest_ts:
                continue

            units = db.execute(select(Unit).where(Unit.community_id == community_id)).scalars().all()
            unit_payloads = []
            for unit in units:
                consumption = db.execute(
                    select(func.coalesce(func.sum(EnergyReading.kwh), 0.0)).where(
                        and_(
                            EnergyReading.community_id == community_id,
                            EnergyReading.unit_id == unit.unit_id,
                            EnergyReading.timestamp == latest_ts,
                        )
                    )
                ).scalar_one()

                devices = db.execute(select(Device).where(Device.unit_id == unit.id)).scalars().all()
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

                    device_map[d.device_id] = {
                        "state": True,
                        "power": 0.0,
                        "controllable": bool(d.controllable),
                    }
                    if hours is not None:
                        device_map[d.device_id]["schedule"] = {"hours": hours}

                unit_payloads.append(
                    {
                        "unit_id": unit.unit_id,
                        "tariff": self._tariff_for_unit(db, unit),
                        "consumption_kwh": float(consumption),
                        "devices": device_map,
                    }
                )

            payloads.append(
                {
                    "community_id": community_id,
                    "timestamp": latest_ts.isoformat(),
                    "units": unit_payloads,
                }
            )

        return payloads

    def run_once_for_community(self, community_id: str) -> Dict[str, Any]:
        db = SessionLocal()
        try:
            payloads = [p for p in self.build_snapshot_payloads(db) if p["community_id"] == community_id]
            if not payloads:
                raise ValueError(f"No snapshot data for community {community_id}")
            payload = payloads[0]

            try:
                result = self.client.analyze(payload)
                row = AIAnalysisResult(
                    community_id=community_id,
                    status="success",
                    stale=False,
                    payload=payload,
                    result=result,
                    error="",
                )
                db.add(row)
                db.commit()
                return {"status": "success", "community_id": community_id, "result": result, "stale": False}
            except Exception as exc:
                last_ok = db.execute(
                    select(AIAnalysisResult)
                    .where(and_(AIAnalysisResult.community_id == community_id, AIAnalysisResult.status == "success"))
                    .order_by(desc(AIAnalysisResult.analyzed_at))
                ).scalars().first()

                row = AIAnalysisResult(
                    community_id=community_id,
                    status="failed",
                    stale=True,
                    payload=payload,
                    result=(last_ok.result if last_ok else {}),
                    error=str(exc),
                )
                db.add(row)
                db.commit()
                return {
                    "status": "failed",
                    "community_id": community_id,
                    "stale": True,
                    "error": str(exc),
                    "result": last_ok.result if last_ok else {},
                }
        finally:
            db.close()

    def run_once_all(self) -> Dict[str, Any]:
        db = SessionLocal()
        try:
            payloads = self.build_snapshot_payloads(db)
            communities = [p["community_id"] for p in payloads]
        finally:
            db.close()

        results = [self.run_once_for_community(cid) for cid in communities]
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
                "result": row.result,
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
                    self.run_once_all()
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
