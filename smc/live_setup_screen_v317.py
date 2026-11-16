"""Live SMC setup screen view-model. No broker order recommendations.

Only visible evidence is displayed; absent verified liquidity targets or
option contract bid/ask MUST render WAIT / UNAVAILABLE, never fake prices.
"""
from __future__ import annotations
from math import isfinite


def build_setup_screen(event: dict | None, *, live_status: str = "NOT_CONNECTED") -> dict:
    if not isinstance(event, dict):
        return _waiting("NO_LIVE_CLOSED_CANDLE", live_status)
    if not event.get("research_only") or event.get("orders_enabled") is not False:
        return _waiting("UNTRUSTED_LIVE_EVENT", live_status)
    quality = event.get("stream_quality") or {}
    if live_status != "RECENT_BAR" or quality.get("quality_blocked", True):
        return _waiting("FEED_NOT_FRESH_OR_COMPLETE", live_status)
    if event.get("status") != "RESEARCH_ONLY":
        return _waiting(event.get("reason", "STRUCTURE_NOT_READY"), live_status)
    latest = event.get("ict_last_lifecycle")
    active = event.get("ict_active_lifecycles") or []
    candidate = active[-1] if active else latest
    if not isinstance(candidate, dict):
        return _waiting("NO_ICT_STRUCTURE_SETUP", live_status)
    direction = candidate.get("direction")
    if direction not in ("BULLISH", "BEARISH"):
        return _waiting("UNKNOWN_STRUCTURE_DIRECTION", live_status)
    step = candidate.get("state", "UNVERIFIED")
    stop_ref = None
    # No claim of *protected* stop: the provisional sweep/OB envelope is
    # shown separately and NEVER promoted to an actionable price.
    if candidate.get("sweep_level") is not None and candidate.get("ob_zone"):
        ob = candidate["ob_zone"]
        if isinstance(ob, list) and len(ob) == 2 and all(
            isinstance(x, (float,int)) and isfinite(x) for x in ob
        ):
            stop_ref = min(candidate["sweep_level"], ob[0]) if direction == "BULLISH" else max(candidate["sweep_level"], ob[1])
    # No market target is invented; no live option quote adapter is currently
    # validated. Returning None is a feature, not an absence of UI.
    missing = []
    if candidate.get("sweep_at") is None:
        missing.append("LIQUIDITY_SWEEP")
    if candidate.get("idm_at") is None:
        missing.append("IDM_CORROBORATION")
    if not candidate.get("displacement_confirmed"):
        missing.append("DISPLACEMENT")
    if candidate.get("ob_zone") is None:
        missing.append("ORDER_BLOCK")
    if candidate.get("fvg_zone") is None:
        missing.append("FVG")
    if candidate.get("retest_at") is None:
        missing.append("MITIGATION_RETEST")
    missing.extend(("VERIFIED_PROTECTED_SWING", "VERIFIED_LIQUIDITY_TARGET",
                    "INDEX_RR_AT_LEAST_2", "LIVE_OPTION_BID_ASK_GREEKS"))
    return {
        "market": event.get("symbol"), "status": "WAIT",
        "bias": direction, "instrument_side": "CE" if direction == "BULLISH" else "PE",
        "structure_kind": candidate.get("structure_kind"),
        "setup_state": step,
        "candle_at": event.get("last_candle_close_at"),
        "observed_index_close": event.get("last_candle_close"),
        "sweep_level": candidate.get("sweep_level"),
        "idm_level": candidate.get("idm_level"),
        "order_block": candidate.get("ob_zone"),
        "fvg": candidate.get("fvg_zone"),
        "entry": None, "structural_stop": None,
        "provisional_stop_reference": stop_ref,
        "t1": None, "t2": None, "t3": None,
        "index_rr": None,
        "option_strike": None, "option_bid": None, "option_ask": None,
        "option_delta": None, "option_iv": None,
        "option_premium_stop": None, "option_premium_target": None,
        "missing_evidence": missing, "live_status": live_status,
        "no_trade_reason": "SETUP_AND_OPTION_QUOTES_UNVERIFIED",
        "order_eligible": False, "research_only": True,
    }


def _waiting(reason: str, live_status: str) -> dict:
    return {
        "status": "WAIT", "bias": None, "instrument_side": None,
        "market": None, "structure_kind": None, "setup_state": "UNVERIFIED",
        "candle_at": None, "observed_index_close": None,
        "sweep_level": None, "idm_level": None, "order_block": None,
        "fvg": None, "entry": None, "structural_stop": None,
        "provisional_stop_reference": None, "t1": None, "t2": None,
        "t3": None, "index_rr": None, "option_strike": None,
        "option_bid": None, "option_ask": None, "option_delta": None,
        "option_iv": None, "option_premium_stop": None,
        "option_premium_target": None, "missing_evidence": [reason],
        "live_status": live_status, "no_trade_reason": reason,
        "order_eligible": False, "research_only": True,
    }
