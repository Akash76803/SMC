"""V3.6: rank known liquidity pools and separate option-premium scenarios.

'Maximum' means farthest *observed eligible* target in the supplied finite
snapshot, not the market's absolute maximum or a predicted price. Index
levels are NEVER converted into option premium targets without option data.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from math import isfinite

from .liquidity import LiquidityEvent, LiquidityLevel
from .models import Candle
from .poi_liquidity_v3 import TargetCandidate, review_liquidity_target
from .premium_feasibility_v3 import PremiumFeasibility, evaluate_premium_bracket


@dataclass(frozen=True)
class TargetTier:
    name: str
    candidate: TargetCandidate
    feasible: bool
    reason: str

    def as_dict(self) -> dict:
        return {
            "name": self.name,
            "price": self.candidate.price,
            "kind": self.candidate.level_kind,
            "index_points": self.candidate.index_points,
            "index_rr": self.candidate.index_rr,
            "feasible": self.feasible,
            "reason": self.reason,
            "evidence_id": self.candidate.evidence_id,
        }


@dataclass(frozen=True)
class MultiTargetReview:
    status: str
    reason: str
    levels: tuple[TargetTier, ...]
    expected_index_rr: float | None
    maximum_observed_index_rr: float | None
    minimum_required_index_rr: float
    eligible_count: int
    furthest_observed: TargetTier | None

    def as_dict(self) -> dict:
        return {
            "status": self.status, "reason": self.reason,
            "targets": [x.as_dict() for x in self.levels],
            "expected_index_rr": self.expected_index_rr,
            "maximum_observed_index_rr": self.maximum_observed_index_rr,
            "minimum_required_index_rr": self.minimum_required_index_rr,
            "eligible_count": self.eligible_count,
            "furthest_observed": (self.furthest_observed.as_dict()
                                  if self.furthest_observed else None),
            "maximum_is_observed_not_guaranteed": True,
            "research_only": True,
        }


@dataclass(frozen=True)
class PremiumScenario:
    """Externally provided hypothetical/quote-backed gross option target."""
    name: str
    target_points: float


@dataclass(frozen=True)
class PremiumTier:
    name: str
    feasibility: PremiumFeasibility

    def as_dict(self) -> dict:
        f = self.feasibility
        return {
            "name": self.name,
            "gross_target_points": f.gross_target_points,
            "net_reward_points": f.net_reward_points,
            "net_risk_points": f.net_risk_points,
            "net_rr": f.net_rr,
            "feasible": f.accepted,
            "reason": f.reason,
        }


@dataclass(frozen=True)
class PremiumLadder:
    status: str
    minimum_required_net_rr: float
    minimum_required_target_points: float
    expected_net_rr: float | None
    maximum_supplied_net_rr: float | None
    scenarios: tuple[PremiumTier, ...]

    def as_dict(self) -> dict:
        return {
            "status": self.status,
            "minimum_required_net_rr": self.minimum_required_net_rr,
            "minimum_required_target_points": self.minimum_required_target_points,
            "expected_net_rr": self.expected_net_rr,
            "maximum_supplied_net_rr": self.maximum_supplied_net_rr,
            "scenarios": [x.as_dict() for x in self.scenarios],
            "not_a_quote_or_fill_forecast": True,
            "research_only": True,
        }


def rank_liquidity_targets(*, candles: list[Candle],
                           levels: list[LiquidityLevel],
                           events: list[LiquidityEvent],
                           direction: str, entry: float, stop: float,
                           symbol: str, as_of: datetime,
                           at_index: int | None = None,
                           max_visible_targets: int = 3,
                           min_index_rr: float = 2.0) -> MultiTargetReview:
    """Rank T1..T3 and report farthest eligible *observed* index level.

    The closest target determines the conservative setup gate, even if T2/T3
    have a larger RR. All eligibility checks reuse the V3.4 causal reviewer.
    """
    if max_visible_targets < 1:
        raise ValueError("INVALID_TARGET_COUNT")
    # Validate the complete input (and timeframe boundaries) even if there are
    # no candidates; prevents empty-list results masking stale/future candles.
    base = review_liquidity_target(
        candles=candles, levels=[], events=events, direction=direction,
        entry=entry, stop=stop, symbol=symbol,
        at_index=at_index, as_of=as_of, min_index_rr=min_index_rr)
    if base.reason == "NO_DECISION_CANDLE":
        return MultiTargetReview(
            "WAIT", base.reason, (), None, None, min_index_rr, 0, None)

    ranked = []
    # Deduplicate equal prices: equal-high clusters and swing highs frequently
    # refer to the same pool. Keep the highest-strength source at that price.
    unique = {}
    for lev in levels:
        if not isfinite(lev.price):
            continue
        k = lev.price
        if k not in unique or lev.strength > unique[k].strength:
            unique[k] = lev
    for lev in unique.values():
        result = review_liquidity_target(
            candles=candles, levels=[lev], events=events,
            direction=direction, entry=entry, stop=stop, symbol=symbol,
            at_index=at_index, as_of=as_of, min_index_rr=min_index_rr)
        if result.target is not None:
            ranked.append(result)
    ranked.sort(key=lambda r: (r.target.index_points,
                               -r.target.available_at.timestamp(),
                               r.target.level_kind))
    if not ranked:
        return MultiTargetReview(
            "WAIT", "NO_UNCONSUMED_OPPOSING_LIQUIDITY", (),
            None, None, min_index_rr, 0, None)

    tiers = tuple(
        TargetTier(f"T{i+1}", r.target, r.status == "CANDIDATE", r.reason)
        for i, r in enumerate(ranked[:max_visible_targets]))
    furthest = ranked[-1]
    farthest_tier = TargetTier(
        f"T{len(ranked)}", furthest.target,
        furthest.status == "CANDIDATE", furthest.reason)
    nearest = ranked[0]
    status = ("CANDIDATE" if nearest.status == "CANDIDATE" else "NO_TRADE")
    return MultiTargetReview(
        status, nearest.reason, tiers, nearest.target.index_rr,
        furthest.target.index_rr, min_index_rr, len(ranked), farthest_tier)


def evaluate_premium_scenarios(*, stop_points: float,
                               round_trip_cost_per_unit: float,
                               scenarios: tuple[PremiumScenario, ...] = (),
                               minimum_target_points: float = 15.0,
                               minimum_net_rr: float = 3.0) -> PremiumLadder:
    """Calculate net premium RR from supplied scenarios, never index points.

    Without separately sourced option premium exit assumptions this remains
    UNVERIFIED, even if index liquidity targets are available.
    """
    if (not all(isfinite(v) for v in (
            stop_points, round_trip_cost_per_unit,
            minimum_target_points, minimum_net_rr))
            or stop_points <= 0 or round_trip_cost_per_unit < 0
            or minimum_target_points <= 0 or minimum_net_rr <= 0):
        raise ValueError("INVALID_PREMIUM_SCENARIO_CONFIG")
    if len({x.name for x in scenarios}) != len(scenarios) or any(
            not x.name for x in scenarios):
        raise ValueError("DUPLICATE_OR_UNNAMED_PREMIUM_SCENARIO")
    evaluated = tuple(
        PremiumTier(
            s.name, evaluate_premium_bracket(
                target_points=s.target_points, stop_points=stop_points,
                round_trip_cost_per_unit=round_trip_cost_per_unit,
                minimum_target_points=minimum_target_points,
                minimum_net_rr=minimum_net_rr))
        for s in scenarios)
    rrs = [t.feasibility.net_rr for t in evaluated]
    return PremiumLadder(
        "SCENARIOS_ONLY_NOT_VERIFIED" if evaluated else "PREMIUM_TARGETS_UNVERIFIED",
        minimum_net_rr, minimum_target_points,
        rrs[0] if rrs else None, max(rrs) if rrs else None, evaluated)
