from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect
from sqlalchemy import and_, asc, desc, func, or_, select
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.models import AIAnalysisResult, Community, DeadLetter, Device, EnergyReading, Unit
from app.schemas import (
    BulkDeleteUnitsRequest,
    BulkDeleteUnitsResponse,
    AIRecommendationItem,
    AIRecommendationsResponse,
    AIStatusResponse,
    CommunityCreateRequest,
    DashboardCommunitySummary,
    DashboardResponse,
    CommunityResponse,
    CommunitiesListResponse,
    CommunityUnitSummaryItem,
    CommunityUpdateRequest,
    DeadLetterItem,
    DeadLettersListResponse,
    DeviceMetadataResponse,
    IngestionPerCommunityItem,
    IngestionStatusResponse,
    PeakRiskResponse,
    UnitCreateRequest,
    UnitCrudResponse,
    UnitsListResponse,
    UnitSummaryResponse,
    UnitUpdateRequest,
    UnitVaUpdateRequest,
)
from app.services.ai_integration import ai_orchestrator
from app.services.dashboard import build_dashboard_snapshot, build_load_curve, build_peak_risk, build_units_summary
from app.services.ingestion import QueryService
from app.services.realtime_ws import dashboard_ws_manager
from app.utils.time import utc_now

router = APIRouter()


@router.get("/communities", response_model=CommunitiesListResponse)
def list_communities(
    offset: int = 0,
    limit: int = 20,
    q: str | None = None,
    sort_by: str = "community_id",
    sort_order: str = "asc",
    db: Session = Depends(get_db),
):
    limit = min(limit, 200)
    stmt = select(Community)
    count_stmt = select(func.count(Community.id))

    if q:
        pattern = f"%{q}%"
        condition = or_(Community.community_id.ilike(pattern), Community.name.ilike(pattern))
        stmt = stmt.where(condition)
        count_stmt = count_stmt.where(condition)

    sort_map = {"community_id": Community.community_id, "name": Community.name}
    sort_col = sort_map.get(sort_by, Community.community_id)
    order_expr = desc(sort_col) if sort_order == "desc" else asc(sort_col)

    rows = db.execute(stmt.order_by(order_expr).offset(offset).limit(limit)).scalars().all()
    total = int(db.execute(count_stmt).scalar_one())
    items = [CommunityResponse(community_id=row.community_id, name=row.name) for row in rows]
    return {
        "items": items,
        "meta": {
            "total": total,
            "offset": offset,
            "limit": limit,
            "has_next": (offset + limit) < total,
        },
    }


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


@router.get("/communities/{community_id}/units", response_model=UnitsListResponse)
def list_units(
    community_id: str,
    offset: int = 0,
    limit: int = 20,
    q: str | None = None,
    va_min: int | None = None,
    va_max: int | None = None,
    sort_by: str = "unit_id",
    sort_order: str = "asc",
    db: Session = Depends(get_db),
):
    limit = min(limit, 200)
    stmt = select(Unit).where(Unit.community_id == community_id)
    count_stmt = select(func.count(Unit.id)).where(Unit.community_id == community_id)

    if q:
        pattern = f"%{q}%"
        stmt = stmt.where(Unit.unit_id.ilike(pattern))
        count_stmt = count_stmt.where(Unit.unit_id.ilike(pattern))
    if va_min is not None:
        stmt = stmt.where(Unit.va >= va_min)
        count_stmt = count_stmt.where(Unit.va >= va_min)
    if va_max is not None:
        stmt = stmt.where(Unit.va <= va_max)
        count_stmt = count_stmt.where(Unit.va <= va_max)

    sort_map = {"unit_id": Unit.unit_id, "va": Unit.va}
    sort_col = sort_map.get(sort_by, Unit.unit_id)
    order_expr = desc(sort_col) if sort_order == "desc" else asc(sort_col)

    rows = db.execute(stmt.order_by(order_expr).offset(offset).limit(limit)).scalars().all()
    total = int(db.execute(count_stmt).scalar_one())
    items = [UnitCrudResponse(community_id=r.community_id, unit_id=r.unit_id, va=r.va) for r in rows]
    return {
        "items": items,
        "meta": {
            "total": total,
            "offset": offset,
            "limit": limit,
            "has_next": (offset + limit) < total,
        },
    }


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


@router.post("/communities/{community_id}/units/bulk-delete", response_model=BulkDeleteUnitsResponse)
def bulk_delete_units(community_id: str, payload: BulkDeleteUnitsRequest, db: Session = Depends(get_db)):
    requested_ids = list(dict.fromkeys(payload.unit_ids))
    rows = db.execute(
        select(Unit).where(and_(Unit.community_id == community_id, Unit.unit_id.in_(requested_ids)))
    ).scalars().all()
    found_map = {u.unit_id: u for u in rows}
    not_found = [u for u in requested_ids if u not in found_map]

    deleted_count = 0
    for unit_id in requested_ids:
        unit = found_map.get(unit_id)
        if not unit:
            continue
        db.execute(Device.__table__.delete().where(Device.unit_id == unit.id))
        db.delete(unit)
        deleted_count += 1

    db.commit()
    return BulkDeleteUnitsResponse(
        community_id=community_id,
        requested_count=len(requested_ids),
        deleted_count=deleted_count,
        not_found_unit_ids=not_found,
    )


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
    return build_units_summary(db, community_id)


@router.get("/communities/{community_id}/dashboard", response_model=DashboardResponse)
def community_dashboard(community_id: str, db: Session = Depends(get_db)):
    snapshot = build_dashboard_snapshot(db, community_id)
    if snapshot is None:
        raise HTTPException(status_code=404, detail="Not found")
    return snapshot


@router.get("/communities/{community_id}/load-curve")
def load_curve(community_id: str, db: Session = Depends(get_db)):
    return build_load_curve(db, community_id)


@router.get("/communities/{community_id}/peak-risk", response_model=PeakRiskResponse)
def peak_risk(community_id: str, db: Session = Depends(get_db)):
    return build_peak_risk(db, community_id)


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


@router.get("/communities/{community_id}/ai-recommendations", response_model=AIRecommendationsResponse)
def ai_recommendations(community_id: str, db: Session = Depends(get_db)):
    row = db.execute(
        select(AIAnalysisResult)
        .where(AIAnalysisResult.community_id == community_id)
        .order_by(desc(AIAnalysisResult.analyzed_at))
    ).scalars().first()

    if not row:
        return AIRecommendationsResponse(
            community_id=community_id,
            exists=False,
            analyzed_at=None,
            status=None,
            stale=True,
            source="unknown",
            recommendations=[],
        )

    recs_raw = []
    if isinstance(row.result, dict):
        result_payload = row.result.get("result", row.result)
        if isinstance(result_payload, dict):
            recs_raw = result_payload.get("recommendations", []) or []

    recommendations: list[AIRecommendationItem] = []
    for rec in recs_raw:
        if not isinstance(rec, dict):
            continue
        reasons = rec.get("reasons")
        normalized_reasons = [str(x) for x in reasons if isinstance(x, str)] if isinstance(reasons, list) else []
        recommendations.append(
            AIRecommendationItem(
                unit_id=rec.get("unit_id"),
                device=rec.get("device"),
                action=rec.get("action"),
                saving=float(rec["saving"]) if isinstance(rec.get("saving"), (int, float)) else None,
                co2_reduction=float(rec["co2_reduction"]) if isinstance(rec.get("co2_reduction"), (int, float)) else None,
                estimated_reduction_kwh=float(rec["estimated_reduction_kwh"])
                if isinstance(rec.get("estimated_reduction_kwh"), (int, float))
                else None,
                reasons=normalized_reasons,
            )
        )

    return AIRecommendationsResponse(
        community_id=community_id,
        exists=True,
        analyzed_at=row.analyzed_at.isoformat(),
        status=row.status,
        stale=bool(row.stale),
        source=row.source or "unknown",
        recommendations=recommendations,
    )


@router.get("/ai/status", response_model=AIStatusResponse)
def ai_status(community_id: str):
    return AIStatusResponse(**ai_orchestrator.get_status(community_id=community_id))


@router.get("/ops/ingestion-status", response_model=IngestionStatusResponse)
def ops_ingestion_status(db: Session = Depends(get_db)):
    total_readings = int(db.execute(select(func.count(EnergyReading.id))).scalar_one())
    total_dead_letters = int(db.execute(select(func.count(DeadLetter.id))).scalar_one())
    communities_with_data = int(db.execute(select(func.count(func.distinct(EnergyReading.community_id)))).scalar_one())

    last_ingestion = db.execute(select(func.max(EnergyReading.timestamp))).scalar_one_or_none()
    last_dead_letter = db.execute(select(func.max(DeadLetter.created_at))).scalar_one_or_none()

    rows = db.execute(
        select(
            EnergyReading.community_id,
            func.count(EnergyReading.id).label("readings_count"),
            func.max(EnergyReading.timestamp).label("last_ingestion_at"),
        )
        .group_by(EnergyReading.community_id)
        .order_by(EnergyReading.community_id)
    ).all()

    per_community = [
        IngestionPerCommunityItem(
            community_id=r.community_id,
            readings_count=int(r.readings_count),
            last_ingestion_at=r.last_ingestion_at.isoformat() if r.last_ingestion_at else None,
        )
        for r in rows
    ]

    return IngestionStatusResponse(
        mqtt={
            "enabled": settings.enable_mqtt,
            "host": settings.mqtt_host,
            "port": settings.mqtt_port,
        },
        totals={
            "energy_readings_count": total_readings,
            "dead_letters_count": total_dead_letters,
            "communities_with_data": communities_with_data,
        },
        latest={
            "last_ingestion_at": last_ingestion.isoformat() if last_ingestion else None,
            "last_dead_letter_at": last_dead_letter.isoformat() if last_dead_letter else None,
        },
        per_community=per_community,
    )


@router.get("/ops/dead-letters", response_model=DeadLettersListResponse)
def ops_dead_letters(
    offset: int = 0,
    limit: int = 20,
    topic: str | None = None,
    reason_q: str | None = None,
    sort_by: str = "created_at",
    sort_order: str = "desc",
    db: Session = Depends(get_db),
):
    limit = min(limit, 200)
    stmt = select(DeadLetter)
    count_stmt = select(func.count(DeadLetter.id))

    if topic:
        stmt = stmt.where(DeadLetter.topic == topic)
        count_stmt = count_stmt.where(DeadLetter.topic == topic)
    if reason_q:
        pattern = f"%{reason_q}%"
        stmt = stmt.where(DeadLetter.reason.ilike(pattern))
        count_stmt = count_stmt.where(DeadLetter.reason.ilike(pattern))

    sort_map = {"created_at": DeadLetter.created_at, "id": DeadLetter.id}
    sort_col = sort_map.get(sort_by, DeadLetter.created_at)
    order_expr = desc(sort_col) if sort_order == "desc" else asc(sort_col)

    total = int(db.execute(count_stmt).scalar_one())
    rows = db.execute(stmt.order_by(order_expr).offset(offset).limit(limit)).scalars().all()

    items = [
        DeadLetterItem(
            id=row.id,
            topic=row.topic,
            reason=row.reason,
            raw_payload=row.raw_payload,
            created_at=row.created_at.isoformat(),
        )
        for row in rows
    ]
    return {
        "items": items,
        "meta": {
            "total": total,
            "offset": offset,
            "limit": limit,
            "has_next": (offset + limit) < total,
        },
    }


@router.post("/ai/run-now")
def ai_run_now(community_id: str | None = None):
    if community_id:
        try:
            return ai_orchestrator.run_once_for_community(community_id=community_id, source="manual")
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
    return ai_orchestrator.run_once_all(source="manual")


@router.websocket("/ws/communities/{community_id}/dashboard")
async def ws_community_dashboard(websocket: WebSocket, community_id: str):
    await dashboard_ws_manager.connect(community_id, websocket)
    try:
        sent = await dashboard_ws_manager.send_snapshot(websocket, community_id)
        if not sent:
            await websocket.send_json({"error": "Not found"})
            await websocket.close(code=1008)
            return

        while True:
            # Keep connection alive and detect client disconnects.
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        await dashboard_ws_manager.disconnect(community_id, websocket)
