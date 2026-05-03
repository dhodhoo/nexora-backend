from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple

from app.config import settings
from app.schemas import AnalyzeRequest, AnalyzeUnit


def _utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


@dataclass
class CommunityState:
    community_id: str
    history_window_days: int
    min_history_samples: int
    high_trigger_multiplier: float
    critical_trigger_multiplier: float
    baseline_short_window: int
    baseline_long_window: int
    baseline_short_weight: float
    baseline_long_weight: float
    max_recommendations: int
    community_history: List[Tuple[datetime, float]] = field(default_factory=list)
    unit_history: Dict[str, List[Tuple[datetime, float]]] = field(default_factory=dict)
    fairness: Dict[str, int] = field(default_factory=dict)


class NexoraAIStateManager:
    def __init__(self):
        self.communities: Dict[str, CommunityState] = {}

    def _create(self, community_id: str) -> CommunityState:
        state = CommunityState(
            community_id=community_id,
            history_window_days=settings.nexora_history_window_days,
            min_history_samples=settings.nexora_min_history_samples,
            high_trigger_multiplier=settings.nexora_high_trigger_multiplier,
            critical_trigger_multiplier=settings.nexora_critical_trigger_multiplier,
            baseline_short_window=settings.nexora_baseline_short_window,
            baseline_long_window=settings.nexora_baseline_long_window,
            baseline_short_weight=settings.nexora_baseline_short_weight,
            baseline_long_weight=settings.nexora_baseline_long_weight,
            max_recommendations=settings.nexora_max_recommendations,
        )
        self.communities[community_id] = state
        return state

    def _get(self, community_id: str) -> CommunityState:
        return self.communities.get(community_id) or self._create(community_id)

    def _prune(self, state: CommunityState, now: datetime) -> None:
        min_ts = now - timedelta(days=state.history_window_days)
        state.community_history = [(t, v) for t, v in state.community_history if t >= min_ts]
        for unit_id in list(state.unit_history.keys()):
            state.unit_history[unit_id] = [(t, v) for t, v in state.unit_history[unit_id] if t >= min_ts]

    @staticmethod
    def _avg(values: List[float]) -> float:
        return sum(values) / len(values) if values else 0.0

    def _baseline(self, state: CommunityState, samples: List[float]) -> float:
        short = self._avg(samples[-state.baseline_short_window :]) if samples else 0.0
        long = self._avg(samples[-state.baseline_long_window :]) if samples else 0.0
        base = (short * state.baseline_short_weight) + (long * state.baseline_long_weight)
        return base if base > 0 else (samples[-1] if samples else 0.0)

    def _unit_consumption(self, u: AnalyzeUnit) -> float:
        if u.consumption_kwh is not None:
            return float(u.consumption_kwh)
        return float(sum((d.power or 0.0) for d in u.devices.values()))

    def _state_dict(self, state: CommunityState, exists: Optional[bool] = None):
        payload = {
            "community_id": state.community_id,
            "history_window_days": state.history_window_days,
            "min_history_samples": state.min_history_samples,
            "high_trigger_multiplier": state.high_trigger_multiplier,
            "critical_trigger_multiplier": state.critical_trigger_multiplier,
            "baseline_short_window": state.baseline_short_window,
            "baseline_long_window": state.baseline_long_window,
            "baseline_short_weight": state.baseline_short_weight,
            "baseline_long_weight": state.baseline_long_weight,
            "community_history_count": len(state.community_history),
            "tracked_units": sorted(list(state.unit_history.keys())),
            "unit_history_count": {k: len(v) for k, v in state.unit_history.items()},
            "fairness": state.fairness,
            "max_recommendations": state.max_recommendations,
        }
        if exists is not None:
            payload = {"exists": exists, **payload}
        return payload

    def get_state(self, community_id: Optional[str] = None):
        if community_id:
            state = self.communities.get(community_id)
            if not state:
                return {"exists": False, "community_id": community_id}
            return self._state_dict(state, exists=True)
        return {
            "community_count": len(self.communities),
            "communities": {cid: self._state_dict(s) for cid, s in self.communities.items()},
        }

    def reset(self, community_id: Optional[str] = None):
        if community_id:
            self.communities.pop(community_id, None)
            return {"status": "reset", "community_id": community_id}
        self.communities.clear()
        return {"status": "reset_all"}

    def analyze(self, req: AnalyzeRequest):
        state = self._get(req.community_id)
        ts = _utc(req.timestamp)
        self._prune(state, ts)

        unit_values = {u.unit_id: self._unit_consumption(u) for u in req.units}
        current = float(sum(unit_values.values()))
        prev_samples = [v for _, v in state.community_history]
        baseline = self._baseline(state, prev_samples if prev_samples else [current])
        predicted = baseline
        high_trigger = baseline * state.high_trigger_multiplier
        critical_trigger = baseline * state.critical_trigger_multiplier

        history_samples = len(prev_samples)
        history_ready = history_samples >= state.min_history_samples
        warmup_remaining = max(0, state.min_history_samples - history_samples)
        if not history_ready:
            peak_status = "warming_up"
        elif current > critical_trigger:
            peak_status = "critical"
        elif current > high_trigger:
            peak_status = "high"
        else:
            peak_status = "normal"

        recs = []
        for unit in req.units:
            unit_kwh = unit_values[unit.unit_id]
            unit_hist = [v for _, v in state.unit_history.get(unit.unit_id, [])]
            unit_base = self._avg(unit_hist[-6:]) if unit_hist else unit_kwh
            contribution = (unit_kwh / current) if current > 0 else 0.0
            deviation = ((unit_kwh - unit_base) / unit_base) if unit_base > 0 else 0.0

            for device_name, dv in unit.devices.items():
                if not (dv.controllable or False):
                    continue
                power = float(dv.power or 0.0)
                if power <= 0:
                    continue

                action = None
                reasons = []
                sched = dv.schedule.hours if (dv.schedule and dv.schedule.hours) else None
                if (dv.state is True) and sched is not None and ts.hour not in sched:
                    action = "turn_off"
                    reasons.append("Device aktif di luar jadwal")
                elif peak_status in {"high", "critical"}:
                    if peak_status == "critical":
                        relevant = deviation >= 0.10 or contribution >= 0.30
                    else:
                        relevant = deviation >= 0.20 or contribution >= 0.35
                    if relevant:
                        action = "reduce"
                        reasons.append("Unit relevan terhadap lonjakan beban komunitas")

                if not action:
                    continue

                tariff = float(unit.tariff or 1444)
                saving = power * tariff
                co2_reduction = power * settings.emission_factor_kg_co2e_per_kwh
                fairness_count = state.fairness.get(unit.unit_id, 0)
                priority_score = (power * 1000) + saving - (fairness_count * 50)
                reasons.extend([
                    f"Unit ini menyumbang {round(contribution*100, 1)}% dari beban komunitas saat ini",
                    f"Estimasi hemat Rp {round(saving, 2)}",
                    f"Estimasi pengurangan CO2 {round(co2_reduction, 2)} kg",
                ])
                recs.append(
                    {
                        "unit_id": unit.unit_id,
                        "device": device_name,
                        "action": action,
                        "estimated_reduction_kwh": round(power, 4),
                        "saving": round(saving, 4),
                        "co2_reduction": round(co2_reduction, 4),
                        "priority_score": round(priority_score, 3),
                        "fairness_count": fairness_count,
                        "unit_baseline_kwh": round(unit_base, 4),
                        "reasons": reasons,
                    }
                )

        recs = sorted(recs, key=lambda x: x["priority_score"], reverse=True)[: state.max_recommendations]
        for r in recs:
            state.fairness[r["unit_id"]] = state.fairness.get(r["unit_id"], 0) + 1

        state.community_history.append((ts, current))
        for unit_id, val in unit_values.items():
            state.unit_history.setdefault(unit_id, []).append((ts, val))

        community_result = {
            "current": round(current, 4),
            "predicted": round(predicted, 4),
            "baseline": round(baseline, 4),
            "threshold": round(baseline, 4),
            "high_trigger": round(high_trigger, 4),
            "critical_trigger": round(critical_trigger, 4),
            "peak_status": peak_status,
            "history_ready": history_ready,
            "history_samples": history_samples,
            "min_history_samples": state.min_history_samples,
            "warmup_remaining_samples": warmup_remaining,
            "co2": round(current * settings.emission_factor_kg_co2e_per_kwh, 4),
        }

        return {
            "status": "success",
            "community_id": req.community_id,
            "result": {
                "community": community_result,
                "unit_predictions": {k: round(v, 4) for k, v in unit_values.items()},
                "recommendations": recs,
                "insights": [],
                "fairness": state.fairness,
            },
            "state": self._state_dict(state, exists=True),
        }


ai_state_manager = NexoraAIStateManager()