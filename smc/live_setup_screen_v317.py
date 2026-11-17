"""Live SMC setup screen view-model. No broker order recommendations.

Only visible evidence is displayed; absent verified liquidity targets or
option contract bid/ask MUST render WAIT / UNAVAILABLE, never fake prices.
"""
from __future__ import annotations
from math import isfinite

CONFLUENCES = ('HTF_POI_VALIDATED', 'DISPLACEMENT_CONFIRMED', 'MITIGATION_RETEST')
VALID_POIS = {'IDM_SWEEP', 'DECISIONAL_OB', 'EXTREME_OB', 'BOS_SWEEP', 'CHOCH_SWEEP'}


def _valid_zone(zone):
    return (isinstance(zone, (list, tuple)) and len(zone) == 2
            and all(isinstance(v, (int, float)) and isfinite(v) for v in zone)
            and 0 < zone[0] < zone[1])


def _confluence_matrix(candidate, bracket):
    context = candidate.get('htf_context') or {}
    high, low, eq = (context.get(key) for key in ('high', 'low', 'equilibrium'))
    context_valid = (all(isinstance(v, (int, float)) and isfinite(v) for v in (high, low, eq))
                     and 0 < low < eq < high)
    poi = (context_valid and candidate.get('poi_category') in VALID_POIS
           and candidate.get('poi_valid') is True
           and candidate.get('setup_type') in ('PRO_TREND', 'COUNTER_PULLBACK'))
    displacement = bool(candidate.get('sweep_at') and candidate.get('idm_at')
                        and candidate.get('structure_kind') in ('BOS', 'CHoCH')
                        and candidate.get('displacement_confirmed')
                        and (_valid_zone(candidate.get('fvg_zone')) or
                             _valid_zone(candidate.get('volume_imbalance_zone'))))
    retest = bool(candidate.get('state') == 'RETEST_CONFIRMED_RESEARCH' and candidate.get('retest_at')
                  and bracket and bracket.get('research_only') is True
                  and bracket.get('status') == 'RESEARCH_INDEX_BRACKET_PASSES'
                  and bracket.get('setup_id') == candidate.get('setup_id')
                  and candidate.get('setup_id'))
    return dict(zip(CONFLUENCES, (bool(poi), displacement, retest)))


def build_setup_screen(event: dict | None, *, live_status: str = "NOT_CONNECTED") -> dict:
    if not isinstance(event, dict):
        return _waiting("NO_LIVE_CLOSED_CANDLE", live_status)
    if not event.get("research_only") or event.get("orders_enabled") is not False:
        return _waiting("UNTRUSTED_LIVE_EVENT", live_status)
    quality = event.get("stream_quality") or {}
    if live_status not in ("RECENT_BAR", "SUBSCRIBING") or quality.get("quality_blocked", True):
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
    bracket = event.get("index_bracket_research")
    if not isinstance(bracket,dict) or bracket.get("research_only") is not True:
        bracket = None
    bracket_passed = bool(bracket and
        bracket.get("status") == "RESEARCH_INDEX_BRACKET_PASSES")
    if bracket_passed:
        missing.extend(("VERIFIED_PROTECTED_SWING", "EXECUTABLE_ENTRY_PRICE",
                        "LIVE_OPTION_BID_ASK_GREEKS",
                        "OPTION_STOP_AND_TARGET_EXIT_QUOTES"))
    else:
        missing.extend(("VERIFIED_PROTECTED_SWING", "VERIFIED_LIQUIDITY_TARGET",
                        "INDEX_RR_AT_LEAST_2", "LIVE_OPTION_BID_ASK_GREEKS"))
    upgraded = candidate.get('confluence_model') == 'GWAIDIER_V1'
    matrix = _confluence_matrix(candidate, bracket) if upgraded else dict.fromkeys(CONFLUENCES, False)
    if upgraded:
        # Legacy event readers retain their historical keys; new engine events
        # use index evidence alone and never require option Greeks for research.
        missing = [key for key, passed in matrix.items() if not passed]
    index_ready = all(matrix.values()) if upgraded else bracket_passed
    return {
        "market": event.get("symbol"),
        "status": "RESEARCH_SEQUENCE_OBSERVED" if index_ready else "WAIT",
        "index_setup_status": "PASS" if index_ready else "WAIT",
        "option_pricing_status": "UNAVAILABLE",
        "confluence_model": candidate.get('confluence_model', 'LEGACY'),
        "confluences": matrix,
        "setup_type": candidate.get('setup_type'),
        "poi_category": candidate.get('poi_category'),
        "htf_context": candidate.get('htf_context'),
        "target_reference": candidate.get('target_reference'),
        "target_kind": candidate.get('target_kind'),
        "volume_imbalance": candidate.get('volume_imbalance_zone'),
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
        "index_research_entry": bracket.get("entry_close_reference") if bracket else None,
        "index_research_stop": bracket.get("stop_reference") if bracket else None,
        "index_research_targets": [
            x.get("price") for x in (bracket.get("targets") or [])[:3]
        ] if bracket else [],
        "index_research_bracket_status": bracket.get("status") if bracket else "UNAVAILABLE",
        "min_target_required": bracket.get("min_target_required") if bracket else None,
        "atr14": bracket.get("atr14") if bracket else None,
        "provisional_stop_reference": stop_ref,
        "t1": None, "t2": None, "t3": None,
        "index_rr": bracket.get("index_rr_reference") if bracket else None,
        "option_strike": None, "option_bid": None, "option_ask": None,
        "option_delta": None, "option_iv": None,
        "option_premium_stop": None, "option_premium_target": None,
        "missing_evidence": missing, "live_status": live_status,
        "no_trade_reason": ("INDEX_RESEARCH_ONLY_OPTIONS_SEPARATE" if index_ready else
                            '|'.join(missing)) if upgraded else "SETUP_AND_OPTION_QUOTES_UNVERIFIED",
        "order_eligible": False, "research_only": True,
    }


def _waiting(reason: str, live_status: str) -> dict:
    return {
        "status": "WAIT", "bias": None, "instrument_side": None,
        "index_setup_status": "WAIT", "option_pricing_status": "UNAVAILABLE",
        "confluence_model": "GWAIDIER_V1", "confluences": dict.fromkeys(CONFLUENCES, False),
        "setup_type": None, "poi_category": None, "htf_context": None,
        "target_reference": None, "target_kind": None, "volume_imbalance": None,
        "market": None, "structure_kind": None, "setup_state": "UNVERIFIED",
        "candle_at": None, "observed_index_close": None,
        "sweep_level": None, "idm_level": None, "order_block": None,
        "fvg": None, "entry": None, "structural_stop": None,
        "index_research_entry": None, "index_research_stop": None,
        "index_research_targets": [], "index_research_bracket_status": "UNAVAILABLE",
        "min_target_required": None, "atr14": None,
        "provisional_stop_reference": None, "t1": None, "t2": None,
        "t3": None, "index_rr": None, "option_strike": None,
        "option_bid": None, "option_ask": None, "option_delta": None,
        "option_iv": None, "option_premium_stop": None,
        "option_premium_target": None, "missing_evidence": [reason],
        "live_status": live_status, "no_trade_reason": reason,
        "order_eligible": False, "research_only": True,
    }
