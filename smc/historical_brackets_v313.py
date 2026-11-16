"""Causal historical trade-bracket research and conservative next-bar replay.

No fills or orders. The only target is an opposing historical liquidity
candidate that passed the existing 50/100-point and 1:2 index rules at setup.
We additionally recheck feasibility at the *next bar open* to avoid acting
on a previous close price. Intrabar SL/target conflict is counted as STOP.
"""
from __future__ import annotations

from collections import Counter
from math import isfinite

from .models import Candle
from .sl_postmortem_v314 import review_stopped_setup


def paper_outcome(*, session: list[Candle], confirm_index: int,
                  direction: str, stop: float, target: float,
                  min_points: float, min_rr: float = 2.0) -> dict:
    if (not 0 <= confirm_index < len(session)-1 or direction not in
            ("BULLISH", "BEARISH")):
        return {"status": "UNTESTABLE", "reason": "NO_NEXT_BAR_OR_DIRECTION"}
    entry_bar = session[confirm_index + 1]
    entry = entry_bar.open
    sign = 1 if direction == "BULLISH" else -1
    risk = sign * (entry - stop)
    reward = sign * (target - entry)
    if not all(isfinite(x) for x in (entry, stop, target, risk, reward)):
        return {"status": "UNTESTABLE", "reason": "INVALID_REFERENCE_PRICE"}
    if risk <= 0 or reward < min_points or reward / risk < min_rr:
        return {
            "status": "NO_TRADE", "reason": "NEXT_BAR_OPEN_RISK_OR_ROOM_FAILED",
            "entry_open": entry, "stop": stop, "target": target,
            "risk_points": risk if risk > 0 else None,
            "reward_points": reward if reward > 0 else None,
        }
    # A gap beyond the stop at the next candle open invalidates the
    # hypothetical fill; entry and stop were not simultaneously executable.
    if (direction == "BULLISH" and entry <= stop) or (
            direction == "BEARISH" and entry >= stop):
        return {"status": "NO_TRADE", "reason": "OPEN_BEYOND_STOP"}
    result = {
        "status": "HYPOTHETICAL", "entry_at": entry_bar.timestamp.isoformat(),
        "entry_open": entry, "stop": stop, "target": target,
        "risk_points": risk, "reward_points": reward, "index_rr": reward / risk,
        "exit_at": None, "exit_reference": None,
        "exit_reason": None, "index_points_gross": None,
        "index_not_option_pnl": True,
        "execution_assumed_not_verified": True,
    }
    # Conservative: if both stop & target crossed in the same 1m candle,
    # assume stop first, because order is unknowable from OHLC.
    for bar in session[confirm_index + 1:]:
        hit_stop = bar.low <= stop if sign == 1 else bar.high >= stop
        hit_target = bar.high >= target if sign == 1 else bar.low <= target
        if hit_stop:
            result.update(exit_at=bar.timestamp.isoformat(), exit_reference=stop,
                          exit_reason="SL_FIRST_OR_SAME_BAR_AMBIGUOUS")
            break
        if hit_target:
            result.update(exit_at=bar.timestamp.isoformat(), exit_reference=target,
                          exit_reason="TARGET_HIT")
            break
    if result["exit_reference"] is None:
        result.update(exit_at=session[-1].timestamp.isoformat(),
                      exit_reference=session[-1].close, exit_reason="EOD_EXIT")
    result["index_points_gross"] = sign * (result["exit_reference"] - entry)
    return result


def analyze_trade_references(*, symbol: str, session: list[Candle],
                             report: dict) -> dict:
    """All historical candidates remain hypotheses, never live trade signals."""
    if symbol not in ("NIFTY", "SENSEX") or len(session) != 360:
        raise ValueError("EXPECTED_AUDITED_COMPLETE_SESSION")
    minimum = 50.0 if symbol == "NIFTY" else 100.0
    rows = []
    outcomes = Counter()
    for item in report["observations"]:
        at = item["confirmed_at"]
        indices = {c.timestamp.isoformat(): i for i, c in enumerate(session)}
        index = indices.get(at)
        entry = item["entry_reference"]
        stop = item["stop_reference"]
        targets = item["evidence_review"]["index_targets"]
        first = targets["targets"][0] if targets["targets"] else None
        available = bool(
            index is not None and stop is not None and first is not None
            and first["feasible"] and targets["status"] == "CANDIDATE"
            and first["index_points"] >= minimum
            and first["index_rr"] is not None and first["index_rr"] >= 2.0)
        # Protected structure, HTF POI and monthly/weekly/daily remain
        # unverified; even a passing index bracket is a RESEARCH candidate.
        row = {
            "confirmed_at": at,
            "direction": item["direction"],
            "index_entry_close_reference": entry,
            "index_stop_reference": stop,
            "index_t1_t2_t3_references": targets["targets"],
            "minimum_index_target_points": minimum,
            "minimum_index_rr": 2.0,
            "mtf_alignment": item["intraday_mtf"]["alignment"],
            "protected_status": item["evidence_review"]["protected_structure"]["status"],
            "poi_status": item["evidence_review"]["poi"]["status"],
            "validation_status": item["status"],
            "validation_reason": item["reason"],
            "index_bracket_qualified": available,
            "paper_outcome": None,
            "sl_postmortem": None,
            "broker_order_eligible": False,
            "option_premium_pnl": None,
        }
        if available:
            outcome = paper_outcome(
                session=session, confirm_index=index,
                direction=item["direction"], stop=stop,
                target=first["price"], min_points=minimum)
            row["paper_outcome"] = outcome
            if outcome.get("exit_reason") == "SL_FIRST_OR_SAME_BAR_AMBIGUOUS":
                row["sl_postmortem"] = review_stopped_setup(
                    session=session, direction=item["direction"],
                    entry=outcome["entry_open"], stop=stop,
                    target=first["price"], exit_at=outcome["exit_at"])
            outcomes[outcome["status"]] += 1
        else:
            outcomes["NO_VERIFIED_INDEX_BRACKET"] += 1
        rows.append(row)
    return {
        "schema_version": "historical-bracket-1",
        "symbol": symbol,
        "session": session[0].timestamp.date().isoformat(),
        "observations": rows,
        "outcome_counts": dict(outcomes),
        "qualified_index_brackets": sum(r["index_bracket_qualified"] for r in rows),
        "executed_trades": 0, "auto_orders_enabled": False,
        "research_only": True,
        "no_verified_options_pnl": True,
    }
