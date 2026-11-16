"""Momentum option premium paper-plan builder, never a brokerage instruction.

The paper entry is the latest observed ask, NOT an executable fill.
A paper plan exists only with current causal index SMC retest, observed
premium momentum, and out-of-sample *research* evidence. It is NOT a
claim the premium will hit target or that the strategy is profitable.
"""
from __future__ import annotations
from math import isfinite


def create_paper_plan(setup: dict, momentum: dict, learning: dict) -> dict:
    absent={"status":"WAIT","reason":"PREMIUM_MOMENTUM_OR_STRATEGY_UNVERIFIED",
            "contract":None,"side":None,"moneyness":None,
            "entry_ask_reference":None,"premium_stop_reference":None,
            "premium_target_reference":None,
            "net_rr_reference":None,"quote_at":None,
            "research_only":True,"orders_enabled":False,
            "notification_is_paper_only":True}
    if (setup.get("research_only") is not True
        or setup.get("index_research_bracket_status")!="RESEARCH_INDEX_BRACKET_PASSES"
        or setup.get("setup_state")!="RETEST_CONFIRMED_RESEARCH"):
        return {**absent,"reason":"NO_CURRENT_VERIFIED_SMC_INDEX_RESEARCH_BRACKET"}
    if (learning.get("status")!="PAPER_RESEARCH_CANDIDATE"
        or learning.get("promotion_allowed") is not False
        or learning.get("orders_enabled") is not False
        or learning.get("research_only") is not True):
        return {**absent,"reason":"NO_PASSED_OUT_OF_SAMPLE_PAPER_STRATEGY"}
    if momentum.get("orders_enabled") is not False:
        return absent
    side=setup.get("instrument_side")
    if side not in ("CE","PE"):
        return absent
    policy=learning.get("selected") or {}
    try:
        target=float(policy["target_premium_points"])
        stop=float(policy["stop_premium_points"])
        costs=float(policy["cost_per_unit"])
    except (KeyError,ValueError,TypeError):
        return absent
    if not all(isfinite(n) for n in (target,stop,costs)) or min(target,stop)<=0 or costs<0:
        return absent
    net_rr=(target-costs)/(stop+costs)
    if net_rr<2:
        return {**absent,"reason":"NET_PREMIUM_RR_BELOW_2"}
    available=[c for c in momentum.get("candidates",[]) if c.get("side")==side]
    if not available:
        return {**absent,"reason":"NO_SAME_SIDE_OBSERVED_PREMIUM_MOMENTUM"}
    # Score from observed bid, volume and spread. No fabricated cheap OTM.
    candidate=max(available,key=lambda row:row.get("score",float("-inf")))
    try: entry=float(candidate["entry_ask_reference"])
    except (KeyError,TypeError,ValueError):return absent
    if not isfinite(entry) or entry-stop<=0:
        return {**absent,"reason":"INVALID_PREMIUM_STOP_LEVEL"}
    return {
        "status":"READY_FOR_PAPER_OBSERVATION",
        "reason":"SMC_PLUS_MOMENTUM_PLUS_HOLDOUT_RESEARCH_NOT_LIVE_VALIDATED",
        "contract":candidate["trading_symbol"],"side":side,
        "moneyness":candidate.get("moneyness"),
        "entry_ask_reference":round(entry,2),
        "premium_stop_reference":round(entry-stop,2),
        "premium_target_reference":round(entry+target,2),
        "net_rr_reference":round(net_rr,3),
        "quote_at":candidate["quote_at"],
        "bid_change_pct":candidate.get("bid_change_pct"),
        "volume_growth":candidate.get("volume_growth"),
        "cost_per_unit_assumption":costs,
        "premium_stop_hit_observed":False,
        "premium_target_hit_observed":False,
        "research_only":True,"orders_enabled":False,
        "notification_is_paper_only":True,
    }
