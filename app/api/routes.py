from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import and_, desc, func, select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Community, Device, EnergyReading, Unit
from app.schemas import (
    CommunityCreateRequest,
    CommunityResponse,
    CommunityUnitSummaryItem,
    CommunityUpdateRequest,
    DeviceMetadataResponse,
    PeakRiskResponse,
    UnitCreateRequest,
    UnitCrudResponse,
    UnitSummaryResponse,
    UnitUpdateRequest,
    UnitVaUpdateRequest,
)
from app.services.ai_integration import ai_orchestrator
from app.services.ingestion import QueryService

router = APIRouter()


@router.get("/communities", response_model=list[CommunityResponse])
def list_communities(db: Session = Depends(get_db)):
    rows = db.execute(select(Community).order_by(Community.community_id)).scalars().all()
    return [CommunityResponse(community_id=row.community_id, name=row.name) for row in rows]


@router.post("/communities", response_model=CommunityResponse)
def create_community(payload: CommunityCreateRequest, db: Session = Depends(get_db)):
    exists = db.execute(select(Community).where(Community.community_id == payload.community_id)).scalar_one_or_none()
    if exists:
        raise HTTPException(status_code=400, detail="Community already exists")

    community = Community(community_id=payload.community_id, name=payload.name)
    db.add(community)
    db.commit()
    db.refresh(community)
    return CommunityResponse(community_id=community.community_id, name=community.name)


@router.get("/communities/{community_id}", response_model=CommunityResponse)
def get_community(community_id: str, db: Session = Depends(get_db)):
    row = db.execute(select(Community).where(Community.community_id == community_id)).scalar_one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail="Not found")
    return CommunityResponse(community_id=row.community_id, name=row.name)


@router.put("/communities/{community_id}", response_model=CommunityResponse)
def update_community(community_id: str, payload: CommunityUpdateRequest, db: Session = Depends(get_db)):
    row = db.execute(select(Community).where(Community.community_id == community_id)).scalar_one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail="Not found")

    row.name = payload.name
    db.commit()
    db.refresh(row)
    return CommunityResponse(community_id=row.community_id, name=row.name)


@router.delete("/communities/{community_id}")
def delete_community(community_id: str, db: Session = Depends(get_db)):
    row = db.execute(select(Community).where(Community.community_id == community_id)).scalar_one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail="Not found")

    unit_count = db.execute(select(func.count(Unit.id)).where(Unit.community_id == community_id)).scalar_one()
    if unit_count > 0:
        raise HTTPException(status_code=400, detail="Community has units; delete units first")

    db.delete(row)
    db.commit()
    return {"status": "deleted", "community_id": community_id}


@router.get("/communities/{community_id}/units", response_model=list[UnitCrudResponse])
def list_units(community_id: str, db: Session = Depends(get_db)):
    rows = db.execute(select(Unit).where(Unit.community_id == community_id).order_by(Unit.unit_id)).scalars().all()
    return [UnitCrudResponse(community_id=r.community_id, unit_id=r.unit_id, va=r.va) for r in rows]


@router.post("/communities/{community_id}/units", response_model=UnitCrudResponse)
def create_unit(community_id: str, payload: UnitCreateRequest, db: Session = Depends(get_db)):
    community = db.execute(select(Community).where(Community.community_id == community_id)).scalar_one_or_none()
    if not community:
        raise HTTPException(status_code=404, detail="Not found")

    exists = db.execute(
        select(Unit).where(and_(Unit.community_id == community_id, Unit.unit_id == payload.unit_id))
    ).scalar_one_or_none()
    if exists:
        raise HTTPException(status_code=400, detail="Unit already exists")

    unit = Unit(community_id=community_id, unit_id=payload.unit_id, va=payload.va)
    db.add(unit)
    db.commit()
    db.refresh(unit)
    return UnitCrudResponse(community_id=unit.community_id, unit_id=unit.unit_id, va=unit.va)


@router.get("/communities/{community_id}/units/{unit_id}", response_model=UnitCrudResponse)
def get_unit(community_id: str, unit_id: str, db: Session = Depends(get_db)):
    unit = db.execute(select(Unit).where(and_(Unit.community_id == community_id, Unit.unit_id == unit_id))).scalar_one_or_none()
    if not unit:
        raise HTTPException(status_code=404, detail="Not found")
    return UnitCrudResponse(community_id=unit.community_id, unit_id=unit.unit_id, va=unit.va)


@router.put("/communities/{community_id}/units/{unit_id}", response_model=UnitCrudResponse)
def update_unit(community_id: str, unit_id: str, payload: UnitUpdateRequest, db: Session = Depends(get_db)):
    unit = db.execute(select(Unit).where(and_(Unit.community_id == community_id, Unit.unit_id == unit_id))).scalar_one_or_none()
    if not unit:
        raise HTTPException(status_code=404, detail="Not found")

    unit.va = payload.va
    db.commit()
    db.refresh(unit)
    return UnitCrudResponse(community_id=unit.community_id, unit_id=unit.unit_id, va=unit.va)


@router.delete("/communities/{community_id}/units/{unit_id}")
def delete_unit(community_id: str, unit_id: str, db: Session = Depends(get_db)):
    unit = db.execute(select(Unit).where(and_(Unit.community_id == community_id, Unit.unit_id == unit_id))).scalar_one_or_none()
    if not unit:
        raise HTTPException(status_code=404, detail="Not found")

    db.execute(Device.__table__.delete().where(Device.unit_id == unit.id))
    db.delete(unit)
    db.commit()
    return {"status": "deleted", "community_id": community_id, "unit_id": unit_id}


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


@router.get("/communities/{community_id}/units-summary", response_model=list[CommunityUnitSummaryItem])
def community_units_summary(community_id: str, db: Session = Depends(get_db)):
    units = db.execute(select(Unit).where(Unit.community_id == community_id).order_by(Unit.unit_id)).scalars().all()
    summaries: list[CommunityUnitSummaryItem] = []

    for unit in units:
        total_kwh, estimated_cost, last_timestamp = db.execute(
            select(
                func.coalesce(func.sum(EnergyReading.kwh), 0.0),
                func.coalesce(func.sum(EnergyReading.estimated_cost), 0.0),
                func.max(EnergyReading.timestamp),
            ).where(and_(EnergyReading.unit_id == unit.unit_id, EnergyReading.community_id == community_id))
        ).one()

        summaries.append(
            CommunityUnitSummaryItem(
                community_id=community_id,
                unit_id=unit.unit_id,
                va=unit.va,
                total_kwh=float(total_kwh),
                estimated_cost=float(estimated_cost),
                estimated_emission_kg_co2e=QueryService.emission(float(total_kwh)),
                last_timestamp=last_timestamp,
                is_fresh=QueryService.freshness(last_timestamp),
            )
        )

    return summaries


@router.get("/communities/{community_id}/load-curve")
def load_curve(community_id: str, db: Session = Depends(get_db)):
    bucket_expr = func.to_char(func.date_trunc("hour", EnergyReading.timestamp), "YYYY-MM-DD\"T\"HH24:00:00")
    rows = db.execute(
        select(
            bucket_expr.label("bucket"),
            func.coalesce(func.sum(EnergyReading.kwh), 0.0).label("total_kwh"),
        )
        .where(EnergyReading.community_id == community_id)
        .group_by(bucket_expr)
        .order_by(bucket_expr)
    ).all()
    return [{"bucket": r.bucket, "total_kwh": float(r.total_kwh)} for r in rows]


@router.get("/communities/{community_id}/peak-risk", response_model=PeakRiskResponse)
def peak_risk(community_id: str, db: Session = Depends(get_db)):
    bucket_expr = func.to_char(func.date_trunc("hour", EnergyReading.timestamp), "YYYY-MM-DD\"T\"HH24:00:00")
    row = db.execute(
        select(
            bucket_expr.label("bucket"),
            func.coalesce(func.sum(EnergyReading.kwh), 0.0).label("total_kwh"),
        )
        .where(EnergyReading.community_id == community_id)
        .group_by(bucket_expr)
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
        try:
            return ai_orchestrator.run_once_for_community(community_id=community_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
    return ai_orchestrator.run_once_all()
