from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import and_, desc, func, select
from sqlalchemy.orm import Session

from app.config import settings
from app.models import Community, EnergyReading, Unit
from app.schemas import AIStatusResponse, CommunityUnitSummaryItem, DashboardCommunitySummary, DashboardResponse, PeakRiskResponse, PeriodComparison, UnitDashboardResponse, UnitDashboardSummary
from app.services.ai_integration import ai_orchestrator
from app.services.ai_recommendations import get_latest_ai_result, parse_recommendations, recommendations_map_by_unit
from app.services.recommendation_compliance import compute_recommendation_compliance
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


def _previous_window(period_start: datetime, period_end: datetime) -> tuple[datetime, datetime]:
    delta = period_end - period_start
    return period_start - delta, period_start


def _pct_change(current: float, previous: float) -> float | None:
    if previous == 0:
        return None
    return ((current - previous) / previous) * 100.0


def _build_comparison(
    period_used: str,
    current_kwh: float,
    current_cost: float,
    current_emission: float,
    previous_kwh: float,
    previous_cost: float,
    previous_emission: float,
    previous_period_start: datetime | None,
    previous_period_end: datetime | None,
) -> PeriodComparison | None:
    if period_used == "all":
        return None
    return PeriodComparison(
        previous_period_start=previous_period_start,
        previous_period_end=previous_period_end,
        consumption_pct=_pct_change(current_kwh, previous_kwh),
        cost_pct=_pct_change(current_cost, previous_cost),
        emission_pct=_pct_change(current_emission, previous_emission),
        compliance_pct_point_delta=None,
    )


def resolve_period(period: str | None) -> tuple[str, datetime | None, datetime | None]:
    value = (period or "all").lower()
    if value not in {"all", "month", "week"}:
        raise ValueError("period must be one of: all, month, week")
    now = utc_now()
    if value == "month":
        return value, now.replace(day=1, hour=0, minute=0, second=0, microsecond=0), now
    if value == "week":
        now = utc_now()
        start = (now - timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
        return value, start, now
    return value, None, None


def resolve_load_curve_start(period_start: datetime | None, days: int = 7) -> datetime:
    lower_bound = utc_now() - timedelta(days=max(1, days))
    if period_start is None:
        return lower_bound
    return period_start if period_start > lower_bound else lower_bound


def resolve_load_curve_end(period_end: datetime | None) -> datetime:
    now = utc_now()
    if period_end is None:
        return now
    return period_end if period_end < now else now


def build_units_summary(
    db: Session,
    community_id: str,
    include_simulation: bool = False,
    period_start: datetime | None = None,
    period_end: datetime | None = None,
    period_used: str = "all",
) -> list[CommunityUnitSummaryItem]:
    units = db.execute(select(Unit).where(Unit.community_id == community_id).order_by(Unit.unit_id)).scalars().all()
    summaries: list[CommunityUnitSummaryItem] = []

    for unit in units:
        conditions = [EnergyReading.unit_id == unit.unit_id, EnergyReading.community_id == community_id]
        if period_start:
            conditions.append(EnergyReading.timestamp >= period_start.replace(tzinfo=None))
        if period_end:
            conditions.append(EnergyReading.timestamp <= period_end.replace(tzinfo=None))
        if not include_simulation:
            conditions.append(EnergyReading.is_simulation.is_(False))
        total_kwh, estimated_cost, last_timestamp = db.execute(
            select(
                func.coalesce(func.sum(EnergyReading.kwh), 0.0),
                func.coalesce(func.sum(EnergyReading.estimated_cost), 0.0),
                func.max(EnergyReading.timestamp),
            ).where(and_(*conditions))
        ).one()

        current_compliance = compute_recommendation_compliance(
            db=db,
            community_id=community_id,
            period_start=period_start,
            period_end=period_end,
            unit_id=unit.unit_id,
            window_hours=24,
        )
        comparison = None
        if period_start and period_end and period_used in {"week", "month"}:
            prev_start, prev_end = _previous_window(period_start, period_end)
            prev_conditions = [EnergyReading.unit_id == unit.unit_id, EnergyReading.community_id == community_id]
            prev_conditions.append(EnergyReading.timestamp >= prev_start.replace(tzinfo=None))
            prev_conditions.append(EnergyReading.timestamp < prev_end.replace(tzinfo=None))
            if not include_simulation:
                prev_conditions.append(EnergyReading.is_simulation.is_(False))
            prev_kwh, prev_cost = db.execute(
                select(
                    func.coalesce(func.sum(EnergyReading.kwh), 0.0),
                    func.coalesce(func.sum(EnergyReading.estimated_cost), 0.0),
                ).where(and_(*prev_conditions))
            ).one()
            current_emission = _emission(float(total_kwh))
            previous_emission = _emission(float(prev_kwh))
            comparison = _build_comparison(
                period_used=period_used,
                current_kwh=float(total_kwh),
                current_cost=float(estimated_cost),
                current_emission=current_emission,
                previous_kwh=float(prev_kwh),
                previous_cost=float(prev_cost),
                previous_emission=previous_emission,
                previous_period_start=prev_start,
                previous_period_end=prev_end,
            )
            previous_compliance = compute_recommendation_compliance(
                db=db,
                community_id=community_id,
                period_start=prev_start,
                period_end=prev_end,
                unit_id=unit.unit_id,
                window_hours=24,
            )
            if current_compliance.compliance_pct is not None and previous_compliance.compliance_pct is not None:
                comparison.compliance_pct_point_delta = current_compliance.compliance_pct - previous_compliance.compliance_pct
            else:
                comparison.compliance_pct_point_delta = None

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
                period_used=period_used,
                period_start=period_start,
                comparison=comparison,
                recommendation_compliance=current_compliance.to_schema(window_hours=24),
            )
        )
    return summaries


def build_load_curve(
    db: Session,
    community_id: str,
    include_simulation: bool = False,
    period_start: datetime | None = None,
    period_end: datetime | None = None,
) -> list[dict[str, Any]]:
    bucket_expr = func.to_char(func.date_trunc("hour", EnergyReading.timestamp), "YYYY-MM-DD\"T\"HH24:00:00")
    conditions = [EnergyReading.community_id == community_id]
    effective_start = resolve_load_curve_start(period_start)
    effective_end = resolve_load_curve_end(period_end)
    conditions.append(EnergyReading.timestamp >= effective_start.replace(tzinfo=None))
    conditions.append(EnergyReading.timestamp <= effective_end.replace(tzinfo=None))
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


def build_peak_risk(
    db: Session,
    community_id: str,
    include_simulation: bool = False,
    period_start: datetime | None = None,
    period_end: datetime | None = None,
    period_used: str = "all",
) -> PeakRiskResponse:
    bucket_expr = func.to_char(func.date_trunc("hour", EnergyReading.timestamp), "YYYY-MM-DD\"T\"HH24:00:00")
    conditions = [EnergyReading.community_id == community_id]
    if period_start:
        conditions.append(EnergyReading.timestamp >= period_start.replace(tzinfo=None))
    if period_end:
        conditions.append(EnergyReading.timestamp <= period_end.replace(tzinfo=None))
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
        return PeakRiskResponse(
            community_id=community_id,
            peak_hour=None,
            peak_kwh=0.0,
            risk_level="normal",
            period_used=period_used,
            period_start=period_start,
        )

    peak_kwh = float(row.total_kwh)
    return PeakRiskResponse(
        community_id=community_id,
        peak_hour=row.bucket,
        peak_kwh=peak_kwh,
        risk_level=_risk_label(peak_kwh),
        period_used=period_used,
        period_start=period_start,
    )


def build_dashboard_snapshot(
    db: Session,
    community_id: str,
    include_simulation: bool = False,
    period_start: datetime | None = None,
    period_end: datetime | None = None,
    period_used: str = "all",
) -> DashboardResponse | None:
    community = db.execute(select(Community).where(Community.community_id == community_id)).scalar_one_or_none()
    if not community:
        return None

    units_summary = build_units_summary(
        db,
        community_id,
        include_simulation=include_simulation,
        period_start=period_start,
        period_end=period_end,
        period_used=period_used,
    )
    load_curve = build_load_curve(
        db,
        community_id,
        include_simulation=include_simulation,
        period_start=period_start,
        period_end=period_end,
    )
    peak_risk = build_peak_risk(
        db,
        community_id,
        include_simulation=include_simulation,
        period_start=period_start,
        period_end=period_end,
        period_used=period_used,
    )
    ai_status = AIStatusResponse(**ai_orchestrator.get_status(community_id=community_id))
    ai_result_row = get_latest_ai_result(db, community_id)
    unit_ai_recommendations = {
        unit_id: [item.model_dump() for item in items]
        for unit_id, items in recommendations_map_by_unit(parse_recommendations(ai_result_row)).items()
    }

    total_kwh = float(sum(item.total_kwh for item in units_summary))
    total_cost = float(sum(item.estimated_cost for item in units_summary))
    total_emission = _emission(total_kwh)
    last_timestamps = [item.last_timestamp for item in units_summary if item.last_timestamp]
    last_timestamp = max(last_timestamps) if last_timestamps else None

    comparison = None
    current_compliance = compute_recommendation_compliance(
        db=db,
        community_id=community_id,
        period_start=period_start,
        period_end=period_end,
        unit_id=None,
        window_hours=24,
    )
    if period_start and period_end and period_used in {"week", "month"}:
        prev_start, prev_end = _previous_window(period_start, period_end)
        prev_conditions = [EnergyReading.community_id == community_id]
        prev_conditions.append(EnergyReading.timestamp >= prev_start.replace(tzinfo=None))
        prev_conditions.append(EnergyReading.timestamp < prev_end.replace(tzinfo=None))
        if not include_simulation:
            prev_conditions.append(EnergyReading.is_simulation.is_(False))
        prev_kwh, prev_cost = db.execute(
            select(
                func.coalesce(func.sum(EnergyReading.kwh), 0.0),
                func.coalesce(func.sum(EnergyReading.estimated_cost), 0.0),
            ).where(and_(*prev_conditions))
        ).one()
        comparison = _build_comparison(
            period_used=period_used,
            current_kwh=total_kwh,
            current_cost=total_cost,
            current_emission=total_emission,
            previous_kwh=float(prev_kwh),
            previous_cost=float(prev_cost),
            previous_emission=_emission(float(prev_kwh)),
            previous_period_start=prev_start,
            previous_period_end=prev_end,
        )
        previous_compliance = compute_recommendation_compliance(
            db=db,
            community_id=community_id,
            period_start=prev_start,
            period_end=prev_end,
            unit_id=None,
            window_hours=24,
        )
        if current_compliance.compliance_pct is not None and previous_compliance.compliance_pct is not None:
            comparison.compliance_pct_point_delta = current_compliance.compliance_pct - previous_compliance.compliance_pct
        else:
            comparison.compliance_pct_point_delta = None

    community_section = DashboardCommunitySummary(
        community_id=community.community_id,
        name=community.name,
        total_units=len(units_summary),
        total_kwh=total_kwh,
        estimated_cost=total_cost,
        estimated_emission_kg_co2e=total_emission,
        last_timestamp=last_timestamp,
        is_fresh=_freshness(last_timestamp),
        period_used=period_used,
        period_start=period_start,
        comparison=comparison,
        recommendation_compliance=current_compliance.to_schema(window_hours=24),
    )

    return DashboardResponse(
        community=community_section,
        units_summary=units_summary,
        load_curve=load_curve,
        peak_risk=peak_risk,
        ai_status=ai_status,
        unit_ai_recommendations=unit_ai_recommendations,
        include_simulation_used=include_simulation,
        period_used=period_used,
        period_start=period_start,
        comparison=comparison,
        recommendation_compliance=current_compliance.to_schema(window_hours=24),
        generated_at=utc_now(),
    )


def build_unit_dashboard_snapshot(
    db: Session,
    community_id: str,
    unit_id: str,
    include_simulation: bool = False,
    period_start: datetime | None = None,
    period_end: datetime | None = None,
    period_used: str = "all",
) -> UnitDashboardResponse | None:
    community = db.execute(select(Community).where(Community.community_id == community_id)).scalar_one_or_none()
    if not community:
        return None
    unit = db.execute(select(Unit).where(and_(Unit.community_id == community_id, Unit.unit_id == unit_id))).scalar_one_or_none()
    if not unit:
        return None

    conditions = [EnergyReading.community_id == community_id, EnergyReading.unit_id == unit_id]
    if period_start:
        conditions.append(EnergyReading.timestamp >= period_start.replace(tzinfo=None))
    if period_end:
        conditions.append(EnergyReading.timestamp <= period_end.replace(tzinfo=None))
    if not include_simulation:
        conditions.append(EnergyReading.is_simulation.is_(False))

    total_kwh, estimated_cost, last_timestamp = db.execute(
        select(
            func.coalesce(func.sum(EnergyReading.kwh), 0.0),
            func.coalesce(func.sum(EnergyReading.estimated_cost), 0.0),
            func.max(EnergyReading.timestamp),
        ).where(and_(*conditions))
    ).one()

    current_compliance = compute_recommendation_compliance(
        db=db,
        community_id=community_id,
        period_start=period_start,
        period_end=period_end,
        unit_id=unit_id,
        window_hours=24,
    )
    comparison = None
    if period_start and period_end and period_used in {"week", "month"}:
        prev_start, prev_end = _previous_window(period_start, period_end)
        prev_conditions = [EnergyReading.community_id == community_id, EnergyReading.unit_id == unit_id]
        prev_conditions.append(EnergyReading.timestamp >= prev_start.replace(tzinfo=None))
        prev_conditions.append(EnergyReading.timestamp < prev_end.replace(tzinfo=None))
        if not include_simulation:
            prev_conditions.append(EnergyReading.is_simulation.is_(False))
        prev_kwh, prev_cost = db.execute(
            select(
                func.coalesce(func.sum(EnergyReading.kwh), 0.0),
                func.coalesce(func.sum(EnergyReading.estimated_cost), 0.0),
            ).where(and_(*prev_conditions))
        ).one()
        comparison = _build_comparison(
            period_used=period_used,
            current_kwh=float(total_kwh),
            current_cost=float(estimated_cost),
            current_emission=_emission(float(total_kwh)),
            previous_kwh=float(prev_kwh),
            previous_cost=float(prev_cost),
            previous_emission=_emission(float(prev_kwh)),
            previous_period_start=prev_start,
            previous_period_end=prev_end,
        )
        previous_compliance = compute_recommendation_compliance(
            db=db,
            community_id=community_id,
            period_start=prev_start,
            period_end=prev_end,
            unit_id=unit_id,
            window_hours=24,
        )
        if current_compliance.compliance_pct is not None and previous_compliance.compliance_pct is not None:
            comparison.compliance_pct_point_delta = current_compliance.compliance_pct - previous_compliance.compliance_pct
        else:
            comparison.compliance_pct_point_delta = None

    unit_summary = UnitDashboardSummary(
        community_id=community_id,
        unit_id=unit_id,
        va=unit.va,
        total_kwh=float(total_kwh),
        estimated_cost=float(estimated_cost),
        estimated_emission_kg_co2e=_emission(float(total_kwh)),
        last_timestamp=last_timestamp,
        is_fresh=_freshness(last_timestamp),
        period_used=period_used,
        period_start=period_start,
        comparison=comparison,
        recommendation_compliance=current_compliance.to_schema(window_hours=24),
    )

    bucket_expr = func.to_char(func.date_trunc("hour", EnergyReading.timestamp), "YYYY-MM-DD\"T\"HH24:00:00")
    load_curve_conditions = [EnergyReading.community_id == community_id, EnergyReading.unit_id == unit_id]
    effective_load_start = resolve_load_curve_start(period_start)
    effective_load_end = resolve_load_curve_end(period_end)
    load_curve_conditions.append(EnergyReading.timestamp >= effective_load_start.replace(tzinfo=None))
    load_curve_conditions.append(EnergyReading.timestamp <= effective_load_end.replace(tzinfo=None))
    if not include_simulation:
        load_curve_conditions.append(EnergyReading.is_simulation.is_(False))
    rows = db.execute(
        select(
            bucket_expr.label("bucket"),
            func.coalesce(func.sum(EnergyReading.kwh), 0.0).label("total_kwh"),
        )
        .where(and_(*load_curve_conditions))
        .group_by(bucket_expr)
        .order_by(bucket_expr)
    ).all()
    load_curve = [{"bucket": r.bucket, "total_kwh": float(r.total_kwh)} for r in rows]

    peak_row = db.execute(
        select(
            bucket_expr.label("bucket"),
            func.coalesce(func.sum(EnergyReading.kwh), 0.0).label("total_kwh"),
        )
        .where(and_(*conditions))
        .group_by(bucket_expr)
        .order_by(desc("total_kwh"))
    ).first()
    if peak_row:
        peak_risk = PeakRiskResponse(
            community_id=community_id,
            peak_hour=peak_row.bucket,
            peak_kwh=float(peak_row.total_kwh),
            risk_level=_risk_label(float(peak_row.total_kwh)),
            period_used=period_used,
            period_start=period_start,
        )
    else:
        peak_risk = PeakRiskResponse(
            community_id=community_id,
            peak_hour=None,
            peak_kwh=0.0,
            risk_level="normal",
            period_used=period_used,
            period_start=period_start,
        )

    ai_row = get_latest_ai_result(db, community_id)
    unit_recs = [rec.model_dump() for rec in parse_recommendations(ai_row) if rec.unit_id == unit_id]

    return UnitDashboardResponse(
        community_id=community_id,
        unit_id=unit_id,
        unit_summary=unit_summary,
        load_curve=load_curve,
        peak_risk=peak_risk,
        ai_recommendations=unit_recs,
        period_used=period_used,
        period_start=period_start,
        comparison=comparison,
        recommendation_compliance=current_compliance.to_schema(window_hours=24),
        generated_at=utc_now(),
    )
