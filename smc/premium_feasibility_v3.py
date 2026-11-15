"""V3 premium-target feasibility: per-unit option premium, never index points.

A plan is only a *research candidate* after independent evidence verifies
liquidity, realistic exit quotes, timestamps and option chain availability.
"""
from __future__ import annotations
from dataclasses import dataclass
from math import isfinite

@dataclass(frozen=True)
class PremiumFeasibility:
    accepted: bool
    reason: str
    gross_target_points: float
    gross_stop_points: float
    net_reward_points: float
    net_risk_points: float
    net_rr: float | None

def evaluate_premium_bracket(*, target_points: float, stop_points: float,
                             round_trip_cost_per_unit: float = 1.0,
                             minimum_target_points: float = 15.0,
                             minimum_net_rr: float = 3.0) -> PremiumFeasibility:
    values = (target_points, stop_points, round_trip_cost_per_unit,
              minimum_target_points, minimum_net_rr)
    if not all(isfinite(v) for v in values):
        raise ValueError("PREMIUM_CONFIG_NOT_FINITE")
    if not (target_points > 0 and stop_points > 0
            and round_trip_cost_per_unit >= 0 and minimum_target_points > 0
            and minimum_net_rr > 0):
        raise ValueError("INVALID_PREMIUM_FEASIBILITY_CONFIG")
    net_reward = target_points - round_trip_cost_per_unit
    net_risk = stop_points + round_trip_cost_per_unit
    net_rr = net_reward / net_risk
    reason = ("PREMIUM_TARGET_BELOW_15" if target_points < minimum_target_points
              else "NET_PREMIUM_REWARD_NON_POSITIVE" if net_reward <= 0
              else "NET_PREMIUM_RR_BELOW_3" if net_rr < minimum_net_rr
              else "RESEARCH_BRACKET_PASSES_POLICY")
    return PremiumFeasibility(
        reason == "RESEARCH_BRACKET_PASSES_POLICY", reason,
        target_points, stop_points, net_reward, net_risk, net_rr)
