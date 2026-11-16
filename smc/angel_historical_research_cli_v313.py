"""One-command Angel historical 1m API -> data audit -> SMC -> paper brackets.

Read-only index research. No order methods, live option premium assumptions,
future-data target selection or invented liquidity. Credentials remain local.
"""
from __future__ import annotations

import argparse
import csv
import json
import logging
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from .angel_history import (HistoryError, HistoryResult, download_history,
                            export_csv, load_master, resolve_token)
from .angel_local_auth import (CredentialError, current_totp,
                               load_local_env, resolve_login_fields)
from .continuation_validation_cli import build_report
from .data_quality import drop_terminal_1530, audit_1m
from .historical_brackets_v313 import analyze_trade_references
from .market_context_v310 import _check
from .session_reconciliation_v314 import reconcile_sessions

def _ist():
    return ZoneInfo("Asia/Kolkata")


def _day(value):
    try:
        return datetime.strptime(value, "%Y-%m-%d").replace(tzinfo=_ist())
    except ValueError:
        raise argparse.ArgumentTypeError("DATE_MUST_BE_YYYY_MM_DD")


def analyze_downloaded(*, symbol: str, candles: list, source_requests: int = 0) -> dict:
    """Reject bad sessions rather than interpolate; no future HTF data at setups."""
    if symbol not in ("NIFTY", "SENSEX") or not candles:
        raise ValueError("INVALID_HISTORICAL_RESEARCH_INPUT")
    by_day, session_audit = reconcile_sessions(candles)
    verified = [c for session in by_day.values() for c in session]
    excluded = [
        {"date": row["date"], "reason": row["reason"],
         "bars": row["raw_bars"]}
        for row in session_audit if row["status"] == "EXCLUDED"
    ]
    if verified:
        _check(verified)
    report_days = []
    counts = Counter()
    for day, session in by_day.items():
        # Strictly historical context: no later day may contribute to entry.
        history = [c for c in verified if c.timestamp.date() <= session[0].timestamp.date()]
        research = build_report(symbol=symbol, candles=session,
                                context_candles=history)
        bracket = analyze_trade_references(symbol=symbol, session=session, report=research)
        report_days.append({"date": day, "research": research, "brackets": bracket})
        counts.update(bracket["outcome_counts"])
    return {
        "schema_version": "angel-historical-research-1",
        "symbol": symbol, "api_requests": source_requests,
        "downloaded_candles": len(candles), "usable_candles": len(verified),
        "usable_sessions": len(report_days), "excluded_sessions": excluded,
        "session_reconciliation": session_audit,
        "recovered_sessions": sum(x["status"] == "RECOVERED_ISOLATED_POST_SESSION"
                                  for x in session_audit),
        "outcome_counts": dict(counts), "days": report_days,
        "executed_trades": 0, "orders_enabled": False,
        "options_quotes_available": False,
        "not_a_live_entry_recommendation": True, "research_only": True,
    }


def export_brackets_csv(payload: dict, path: str | Path) -> None:
    """Compact user-facing research CSV; no credentials or order information."""
    names = ("date", "confirmed_at", "direction", "index_entry_close_reference",
             "index_stop_reference", "t1", "t2", "t3", "index_bracket_qualified",
             "validation_status", "validation_reason", "paper_entry_open",
             "paper_exit", "paper_exit_reason", "paper_index_points_gross")
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", encoding="utf-8", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=names)
        writer.writeheader()
        for day in payload["days"]:
            for obs in day["brackets"]["observations"]:
                tiers = obs["index_t1_t2_t3_references"]
                outcome = obs["paper_outcome"] or {}
                vals = [tier["price"] for tier in tiers[:3]]
                vals += [None] * (3 - len(vals))
                writer.writerow({
                    "date": day["date"], "confirmed_at": obs["confirmed_at"],
                    "direction": obs["direction"],
                    "index_entry_close_reference": obs["index_entry_close_reference"],
                    "index_stop_reference": obs["index_stop_reference"],
                    "t1": vals[0], "t2": vals[1], "t3": vals[2],
                    "index_bracket_qualified": obs["index_bracket_qualified"],
                    "validation_status": obs["validation_status"],
                    "validation_reason": obs["validation_reason"],
                    "paper_entry_open": outcome.get("entry_open"),
                    "paper_exit": outcome.get("exit_reference"),
                    "paper_exit_reason": outcome.get("exit_reason"),
                    "paper_index_points_gross": outcome.get("index_points_gross"),
                })


def fetch_and_analyze(*, client, symbol: str, token: str,
                      start: datetime, end: datetime, raw_csv: str | Path,
                      report_json: str | Path,
                      candidates_csv: str | Path | None = None) -> dict:
    if start > end:
        raise ValueError("INVALID_DATE_RANGE")
    # One-minute timestamp from the broker is candle START;
    # existing adapter normalizes to 1m CLOSE in Asia/Kolkata.
    history = download_history(
        client, symbol=symbol, token=token, interval="ONE_MINUTE",
        start=start.replace(hour=9, minute=15),
        end=end.replace(hour=15, minute=30))
    payload = analyze_downloaded(
        symbol=symbol, candles=list(history.candles),
        source_requests=history.requests)
    export_csv(history, raw_csv)
    if candidates_csv is not None:
        export_brackets_csv(payload, candidates_csv)
    path = Path(report_json)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, allow_nan=False)+"\n",
                    encoding="utf-8")
    return payload


def main() -> int:
    p = argparse.ArgumentParser(
        description="Read-only authenticated Angel historical SMC and index bracket research")
    p.add_argument("--symbol", choices=("NIFTY", "SENSEX"), required=True)
    p.add_argument("--from-date", type=_day, required=True)
    p.add_argument("--to-date", type=_day, required=True)
    p.add_argument("--token", help="Explicit verified exchange index token")
    p.add_argument("--master-file", help="Official Angel instrument master JSON")
    p.add_argument("--env-file", help="Local ignored .env")
    p.add_argument("--raw-csv", required=True)
    p.add_argument("--candidates-csv", help="Compact entries/SL/T1-T3 research table")
    p.add_argument("--out", required=True)
    args = p.parse_args()
    if args.to_date < args.from_date:
        p.error("INVALID_DATE_RANGE")
    try:
        token = args.token or resolve_token(load_master(args.master_file), args.symbol)
    except (HistoryError, ValueError):
        p.error("INDEX_TOKEN_MISSING_OR_AMBIGUOUS")
    logging.disable(logging.CRITICAL)
    try:
        from logzero import logger
        logger.disabled = True
        from SmartApi import SmartConnect
    except ImportError:
        p.error('SDK_MISSING: python -m pip install -e ".[angel]"')
    logged_in = False
    client_id = ""
    try:
        key, client_id, pin = resolve_login_fields(load_local_env(args.env_file))
        otp = current_totp()
        api = SmartConnect(api_key=key)
        try:
            response = api.generateSession(clientCode=client_id,
                                           password=pin, totp=otp)
        except Exception:
            raise CredentialError("BROKER_LOGIN_FAILED") from None
        if not isinstance(response, dict) or response.get("status") is not True:
            raise CredentialError("BROKER_LOGIN_REJECTED")
        logged_in = True
        payload = fetch_and_analyze(
            client=api, symbol=args.symbol, token=token,
            start=args.from_date, end=args.to_date,
            raw_csv=args.raw_csv, report_json=args.out,
            candidates_csv=args.candidates_csv)
        print("HISTORICAL_RESEARCH_COMPLETE: "
              f"downloaded={payload['downloaded_candles']} "
              f"usable_sessions={payload['usable_sessions']} "
              f"excluded_sessions={len(payload['excluded_sessions'])}")
        print("OUTCOMES: "+json.dumps(payload["outcome_counts"], sort_keys=True))
        print(f"Report: {args.out}")
        print("INDEX_REFERENCES_ONLY | OPTIONS_PNL_UNVERIFIED | NO_ORDERS")
        return 0 if payload["usable_sessions"] else 2
    except (CredentialError, HistoryError, ValueError) as exc:
        print(f"FAILED: {exc}")
        return 1
    except Exception:
        print("FAILED: HISTORICAL_SDK_OR_ANALYSIS_ERROR")
        return 1
    finally:
        if logged_in:
            try:
                api.terminateSession(client_id)
            except Exception:
                print("LOGOUT_NOT_CONFIRMED")


if __name__ == "__main__":
    raise SystemExit(main())
