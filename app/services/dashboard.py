from datetime import timedelta
from typing import Any

from sqlalchemy import and_, desc, func, select
from sqlalchemy.orm import Session

from app.config import settings
from app.models import Community, EnergyReading, Unit
from app.schemas import AIStatusResponse, CommunityUnitSummaryItem, DashboardCommunitySummary, DashboardResponse, PeakRiskResponse
from app.services.ai_integration import ai_orchestrator
from app.services.ai_recommendations import get_latest_ai_result, parse_recommendations, recommendations_map_by_unit
from app.utils.time import utc_now
from app.utils.time import assume_utc


def _freshness(last_timestamp) -> bool:
    if not last_timestamp:
        return False
    return assume_utc(last_timestamp) >= (utc_now() - timedelta(minutes=10))


def _emission(kwh: float) -> float:
    return kwh * settings.emission_factor_kg_co2e_per_kwh


def _risk_label(peak_kwh: float) -> str:
    if peak_kwh >= 3.0:
        return "critical"
    if peak_kwh >= 1.5:
        return "high"
    return "normal"


def build_units_summary(db: Session, community_id: str, include_simulation: bool = False) -> list[CommunityUnitSummaryItem]:
    units = db.execute(select(Unit).where(Unit.community_id == community_id).order_by(Unit.unit_id)).scalars().all()
    summaries: list[CommunityUnitSummaryItem] = []

    for unit in units:
        conditions = [EnergyReading.unit_id == unit.unit_id, EnergyReading.community_id == community_id]
        if not include_simulation:
            conditions.append(EnergyReading.is_simulation.is_(False))
        total_kwh, estimated_cost, last_timestamp = db.execute(
            select(
                func.coalesce(func.sum(EnergyReading.kwh), 0.0),
                func.coalesce(func.sum(EnergyReading.estimated_cost), 0.0),
                func.max(EnergyReading.timestamp),
            ).where(and_(*conditions))
        ).one()

        summaries.append(
            CommunityUnitSummaryItem(
                community_id=community_id,
                unit_id=unit.unit_id,
                va=unit.va,
                total_kwh=float(total_kwh),
                estimated_cost=float(estimated_cost),
                estimated_emission_kg_co2e=_emission(float(total_kwh)),
                last_timestamp=last_timestamp,
                is_fresh=_freshness(last_timestamp),
            )
        )
    return summaries


def build_load_curve(db: Session, community_id: str, include_simulation: bool = False) -> list[dict[str, Any]]:
    bucket_expr = func.to_char(func.date_trunc("hour", EnergyReading.timestamp), "YYYY-MM-DD\"T\"HH24:00:00")
    conditions = [EnergyReading.community_id == community_id]
    if not include_simulation:
        conditions.append(EnergyReading.is_simulation.is_(False))
    rows = db.execute(
        select(
            bucket_expr.label("bucket"),
            func.coalesce(func.sum(EnergyReading.kwh), 0.0).label("total_kwh"),
        )
        .where(and_(*conditions))
        .group_by(bucket_expr)
        .order_by(bucket_expr)
    ).all()
    return [{"bucket": r.bucket, "total_kwh": float(r.total_kwh)} for r in rows]


def build_peak_risk(db: Session, community_id: str, include_simulation: bool = False) -> PeakRiskResponse:
    bucket_expr = func.to_char(func.date_trunc("hour", EnergyReading.timestamp), "YYYY-MM-DD\"T\"HH24:00:00")
    conditions = [EnergyReading.community_id == community_id]
    if not include_simulation:
        conditions.append(EnergyReading.is_simulation.is_(False))
    row = db.execute(
        select(
            bucket_expr.label("bucket"),
            func.coalesce(func.sum(EnergyReading.kwh), 0.0).label("total_kwh"),
        )
        .where(and_(*conditions))
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
        risk_level=_risk_label(peak_kwh),
    )


def build_dashboard_snapshot(db: Session, community_id: str, include_simulation: bool = False) -> DashboardResponse | None:
    community = db.execute(select(Community).where(Community.community_id == community_id)).scalar_one_or_none()
    if not community:
        return None

    units_summary = build_units_summary(db, community_id, include_simulation=include_simulation)
    load_curve = build_load_curve(db, community_id, include_simulation=include_simulation)
    peak_risk = build_peak_risk(db, community_id, include_simulation=include_simulation)
    ai_status = AIStatusResponse(**ai_orchestrator.get_status(community_id=community_id))
    ai_result_row = get_latest_ai_result(db, community_id)
    unit_ai_recommendations = {
        unit_id: [item.model_dump() for item in items]
        for unit_id, items in recommendations_map_by_unit(parse_recommendations(ai_result_row)).items()
    }

    total_kwh = float(sum(item.total_kwh for item in units_summary))
    total_cost = float(sum(item.estimated_cost for item in units_summary))
    last_timestamps = [item.last_timestamp for item in units_summary if item.last_timestamp]
    last_timestamp = max(last_timestamps) if last_timestamps else None

    community_section = DashboardCommunitySummary(
        community_id=community.community_id,
        name=community.name,
        total_units=len(units_summary),
        total_kwh=total_kwh,
        estimated_cost=total_cost,
        estimated_emission_kg_co2e=_emission(total_kwh),
        last_timestamp=last_timestamp,
        is_fresh=_freshness(last_timestamp),
    )

    return DashboardResponse(
        community=community_section,
        units_summary=units_summary,
        load_curve=load_curve,
        peak_risk=peak_risk,
        ai_status=ai_status,
        unit_ai_recommendations=unit_ai_recommendations,
        include_simulation_used=include_simulation,
        generated_at=utc_now(),
    )
