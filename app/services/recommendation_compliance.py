from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import and_, select
from sqlalchemy.orm import Session

from app.models import AIAnalysisResult, DeviceCommand
from app.schemas import RecommendationCompliance


@dataclass
class ComplianceAggregate:
    total_recommendations: int = 0
    followed_recommendations: int = 0

    @property
    def compliance_pct(self) -> float | None:
        if self.total_recommendations == 0:
            return None
        return (self.followed_recommendations / self.total_recommendations) * 100.0

    def to_schema(self, window_hours: int) -> RecommendationCompliance:
        return RecommendationCompliance(
            total_recommendations=self.total_recommendations,
            followed_recommendations=self.followed_recommendations,
            compliance_pct=self.compliance_pct,
            window_hours=window_hours,
        )


def _normalize_action(action: str | None) -> str | None:
    if not action:
        return None
    value = str(action).strip().lower()
    if value in {"on", "turn_on"}:
        return "on"
    if value in {"off", "turn_off", "reduce"}:
        return "off"
    return None


def _iter_recommendations(row: AIAnalysisResult, unit_id: str | None):
    if not isinstance(row.result, dict):
        return
    result_payload = row.result.get("result", row.result)
    if not isinstance(result_payload, dict):
        return
    recs_raw = result_payload.get("recommendations", []) or []
    if not isinstance(recs_raw, list):
        return
    for rec in recs_raw:
        if not isinstance(rec, dict):
            continue
        rec_unit_id = rec.get("unit_id")
        rec_device = rec.get("device")
        rec_action = _normalize_action(rec.get("action"))
        if unit_id and rec_unit_id != unit_id:
            continue
        if not rec_unit_id or not rec_device or not rec_action:
            continue
        yield rec_unit_id, str(rec_device), rec_action


def _has_matching_command(
    db: Session,
    community_id: str,
    analyzed_at: datetime,
    unit_id: str,
    device_id: str,
    action: str,
    window_hours: int,
) -> bool:
    window_end = analyzed_at + timedelta(hours=window_hours)
    row = db.execute(
        select(DeviceCommand.id).where(
            and_(
                DeviceCommand.community_id == community_id,
                DeviceCommand.unit_id == unit_id,
                DeviceCommand.device_id == device_id,
                DeviceCommand.action == action,
                DeviceCommand.status.in_(["sent", "acked"]),
                DeviceCommand.created_at >= analyzed_at,
                DeviceCommand.created_at <= window_end,
            )
        )
    ).first()
    return row is not None


def compute_recommendation_compliance(
    db: Session,
    community_id: str,
    period_start: datetime | None,
    period_end: datetime | None,
    unit_id: str | None = None,
    window_hours: int = 24,
) -> ComplianceAggregate:
    stmt = select(AIAnalysisResult).where(AIAnalysisResult.community_id == community_id)
    if period_start:
        stmt = stmt.where(AIAnalysisResult.analyzed_at >= period_start.replace(tzinfo=None))
    if period_end:
        stmt = stmt.where(AIAnalysisResult.analyzed_at <= period_end.replace(tzinfo=None))
    rows = db.execute(stmt.order_by(AIAnalysisResult.analyzed_at.asc())).scalars().all()

    agg = ComplianceAggregate()
    for row in rows:
        for rec_unit_id, rec_device, rec_action in _iter_recommendations(row, unit_id):
            agg.total_recommendations += 1
            if _has_matching_command(
                db=db,
                community_id=community_id,
                analyzed_at=row.analyzed_at,
                unit_id=rec_unit_id,
                device_id=rec_device,
                action=rec_action,
                window_hours=window_hours,
            ):
                agg.followed_recommendations += 1
    return agg

