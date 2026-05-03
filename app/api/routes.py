from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import and_, desc, func, select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Device, EnergyReading, Unit
from app.schemas import DeviceMetadataResponse, PeakRiskResponse, UnitSummaryResponse, UnitVaUpdateRequest
from app.services.ai_integration import ai_orchestrator
from app.services.ingestion import QueryService

router = APIRouter()


@router.get("/units/{unit_id}/summary", response_model=UnitSummaryResponse)
def unit_summary(unit_id: str, community_id: str, db: Session = Depends(get_db)):
    total_kwh, estimated_cost, last_timestamp = db.execute(
        select(
            func.coalesce(func.sum(EnergyReading.kwh), 0.0),
            func.coalesce(func.sum(EnergyReading.estimated_cost), 0.0),
            func.max(EnergyReading.timestamp),
        ).where(and_(EnergyReading.unit_id == unit_id, EnergyReading.community_id == community_id))
    ).one()

    return UnitSummaryResponse(
        community_id=community_id,
        unit_id=unit_id,
        total_kwh=float(total_kwh),
        estimated_cost=float(estimated_cost),
        estimated_emission_kg_co2e=QueryService.emission(float(total_kwh)),
        last_timestamp=last_timestamp,
        is_fresh=QueryService.freshness(last_timestamp),
    )


@router.get("/communities/{community_id}/load-curve")
def load_curve(community_id: str, db: Session = Depends(get_db)):
    rows = db.execute(
        select(
            func.strftime("%Y-%m-%dT%H:00:00", EnergyReading.timestamp).label("bucket"),
            func.coalesce(func.sum(EnergyReading.kwh), 0.0).label("total_kwh"),
        )
        .where(EnergyReading.community_id == community_id)
        .group_by("bucket")
        .order_by("bucket")
    ).all()
    return [{"bucket": r.bucket, "total_kwh": float(r.total_kwh)} for r in rows]


@router.get("/communities/{community_id}/peak-risk", response_model=PeakRiskResponse)
def peak_risk(community_id: str, db: Session = Depends(get_db)):
    row = db.execute(
        select(
            func.strftime("%Y-%m-%dT%H:00:00", EnergyReading.timestamp).label("bucket"),
            func.coalesce(func.sum(EnergyReading.kwh), 0.0).label("total_kwh"),
        )
        .where(EnergyReading.community_id == community_id)
        .group_by("bucket")
        .order_by(desc("total_kwh"))
    ).first()

    if not row:
        return PeakRiskResponse(community_id=community_id, peak_hour=None, peak_kwh=0.0, risk_level="normal")

    peak_kwh = float(row.total_kwh)
    return PeakRiskResponse(
        community_id=community_id,
        peak_hour=row.bucket,
        peak_kwh=peak_kwh,
        risk_level=QueryService.risk_label(peak_kwh),
    )


@router.get("/units/{unit_id}/devices")
def unit_devices(unit_id: str, community_id: str, db: Session = Depends(get_db)):
    unit = db.execute(select(Unit).where(and_(Unit.unit_id == unit_id, Unit.community_id == community_id))).scalar_one_or_none()
    if not unit:
        raise HTTPException(status_code=404, detail="Not found")

    rows = db.execute(select(Device).where(Device.unit_id == unit.id)).scalars().all()
    return [DeviceMetadataResponse(device_id=r.device_id, controllable=r.controllable, schedules=r.schedules).model_dump() for r in rows]


@router.put("/units/{unit_id}/va")
def update_unit_va(unit_id: str, payload: UnitVaUpdateRequest, community_id: str, db: Session = Depends(get_db)):
    unit = db.execute(select(Unit).where(and_(Unit.unit_id == unit_id, Unit.community_id == community_id))).scalar_one_or_none()
    if not unit:
        raise HTTPException(status_code=404, detail="Not found")

    unit.va = payload.va
    db.commit()
    db.refresh(unit)
    return {"community_id": community_id, "unit_id": unit_id, "va": unit.va}


@router.get("/ai/health")
def ai_health():
    return ai_orchestrator.client.health()


@router.get("/ai/last-result")
def ai_last_result(community_id: str):
    return ai_orchestrator.get_last_result(community_id=community_id)


@router.post("/ai/run-now")
def ai_run_now(community_id: str | None = None):
    if community_id:
        return ai_orchestrator.run_once_for_community(community_id=community_id)
    return ai_orchestrator.run_once_all()
