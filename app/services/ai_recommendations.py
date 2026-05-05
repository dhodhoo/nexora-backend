from __future__ import annotations

from collections import defaultdict

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.models import AIAnalysisResult
from app.schemas import AIRecommendationItem


def get_latest_ai_result(db: Session, community_id: str) -> AIAnalysisResult | None:
    return db.execute(
        select(AIAnalysisResult)
        .where(AIAnalysisResult.community_id == community_id)
        .order_by(desc(AIAnalysisResult.analyzed_at))
    ).scalars().first()


def parse_recommendations(row: AIAnalysisResult | None) -> list[AIRecommendationItem]:
    if not row or not isinstance(row.result, dict):
        return []
    result_payload = row.result.get("result", row.result)
    if not isinstance(result_payload, dict):
        return []
    recs_raw = result_payload.get("recommendations", []) or []
    items: list[AIRecommendationItem] = []
    for rec in recs_raw:
        if not isinstance(rec, dict):
            continue
        reasons = rec.get("reasons")
        items.append(
            AIRecommendationItem(
                unit_id=rec.get("unit_id"),
                device=rec.get("device"),
                action=rec.get("action"),
                saving=float(rec["saving"]) if isinstance(rec.get("saving"), (int, float)) else None,
                co2_reduction=float(rec["co2_reduction"]) if isinstance(rec.get("co2_reduction"), (int, float)) else None,
                estimated_reduction_kwh=float(rec["estimated_reduction_kwh"]) if isinstance(rec.get("estimated_reduction_kwh"), (int, float)) else None,
                reasons=[str(x) for x in reasons if isinstance(x, str)] if isinstance(reasons, list) else [],
            )
        )
    return items


def recommendations_map_by_unit(items: list[AIRecommendationItem]) -> dict[str, list[AIRecommendationItem]]:
    grouped: dict[str, list[AIRecommendationItem]] = defaultdict(list)
    for item in items:
        if item.unit_id:
            grouped[item.unit_id].append(item)
    return dict(grouped)
