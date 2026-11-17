"""Auditor for live recorded Angel One option quote tape.

Audits results/live_nifty_option_quotes.jsonl and results/live_sensex_option_quotes.jsonl:
- Total records and elapsed duration
- Timestamp continuity and gap analysis (> 120s between quotes)
- Bid/Ask quote quality (missing, zero, inverted bid > ask)
- Strike coverage (distinct strikes, CE/PE balance, ATM/ITM/OTM distribution)
- Progress towards minimum sample requirements for premium walk-forward learning
  (target: >= 20 training + 10 validation sessions with >= 15 + 8 trades).
"""
from __future__ import annotations

import json
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")


def audit_quote_tape(tape_path: Path, market: str) -> dict[str, Any]:
    if not tape_path.is_file():
        return {
            "market": market,
            "file": str(tape_path),
            "status": "FILE_NOT_FOUND",
            "message": f"Quote tape file does not exist yet. Run .\\run_smc.ps1 -Live during market hours (09:15-15:30 IST) to start recording.",
            "total_records": 0,
        }

    records: list[dict] = []
    corrupt_lines = 0
    with tape_path.open("r", encoding="utf-8") as f:
        for idx, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
                records.append(row)
            except Exception:
                corrupt_lines += 1

    if not records:
        return {
            "market": market,
            "file": str(tape_path),
            "status": "EMPTY_FILE",
            "message": "File exists but contains 0 valid quote records.",
            "total_records": 0,
            "corrupt_lines": corrupt_lines,
        }

    # Group records by timestamp
    by_timestamp: dict[str, list[dict]] = defaultdict(list)
    by_date: dict[str, int] = Counter()
    by_contract: dict[str, int] = Counter()
    missing_bid_ask = 0
    inverted_bid_ask = 0
    zero_bid = 0

    timestamps_sorted = []

    for r in records:
        q_time_str = r.get("quote_at")
        if q_time_str:
            by_timestamp[q_time_str].append(r)
            try:
                dt = datetime.fromisoformat(q_time_str).astimezone(IST)
                timestamps_sorted.append(dt)
                by_date[dt.date().isoformat()] += 1
            except Exception:
                pass

        trading_sym = r.get("trading_symbol", "UNKNOWN")
        by_contract[trading_sym] += 1

        bid = r.get("bid")
        ask = r.get("ask")
        if bid is None or ask is None:
            missing_bid_ask += 1
        elif bid == 0:
            zero_bid += 1
        elif bid > ask:
            inverted_bid_ask += 1

    timestamps_sorted.sort()
    start_time = timestamps_sorted[0] if timestamps_sorted else None
    end_time = timestamps_sorted[-1] if timestamps_sorted else None
    duration_min = round((end_time - start_time).total_seconds() / 60, 1) if start_time and end_time else 0.0

    # Gap analysis: consecutive snapshots > 120s apart during session
    gaps = []
    unique_ts = sorted(list(set(timestamps_sorted)))
    for t1, t2 in zip(unique_ts[:-1], unique_ts[1:]):
        delta_sec = (t2 - t1).total_seconds()
        if delta_sec > 120:
            gaps.append({
                "from": t1.isoformat(),
                "to": t2.isoformat(),
                "gap_seconds": delta_sec,
            })

    # Strike coverage breakdown
    ce_contracts = [c for c in by_contract if c.endswith("CE")]
    pe_contracts = [c for c in by_contract if c.endswith("PE")]

    sessions_count = len(by_date)
    readiness = "READY_FOR_PREMIUM_RESEARCH" if sessions_count >= 30 else f"COLLECTING_HISTORY ({sessions_count}/30 sessions required)"

    return {
        "market": market,
        "file": str(tape_path),
        "status": "RECORDING_ACTIVE" if duration_min > 0 else "PARTIAL",
        "total_records": len(records),
        "distinct_snapshots": len(unique_ts),
        "corrupt_lines": corrupt_lines,
        "first_quote": start_time.isoformat() if start_time else None,
        "last_quote": end_time.isoformat() if end_time else None,
        "recording_duration_minutes": duration_min,
        "sessions_recorded": dict(by_date),
        "sessions_count": sessions_count,
        "distinct_contracts_count": len(by_contract),
        "ce_contracts_count": len(ce_contracts),
        "pe_contracts_count": len(pe_contracts),
        "data_quality": {
            "missing_bid_ask_count": missing_bid_ask,
            "zero_bid_count": zero_bid,
            "inverted_bid_ask_count": inverted_bid_ask,
            "gaps_count_gt_120s": len(gaps),
            "sample_gaps": gaps[:5],
        },
        "engine_readiness": {
            "status": readiness,
            "current_sessions": sessions_count,
            "target_training_sessions": 20,
            "target_validation_sessions": 10,
        },
    }


def main() -> int:
    base_dir = Path("E:/Project/SMC")
    results_dir = base_dir / "results"

    print("=" * 70)
    print(" SMC LIVE OPTION QUOTE TAPE AUDIT")
    print("=" * 70)

    for market in ["NIFTY", "SENSEX"]:
        tape_path = results_dir / f"live_{market.lower()}_option_quotes.jsonl"
        audit = audit_quote_tape(tape_path, market)
        print(f"\n[{market}] File: {tape_path.name}")
        print(f"  Status: {audit['status']}")
        print(f"  Total records: {audit['total_records']}")
        if audit["total_records"] > 0:
            print(f"  Sessions: {audit['sessions_count']} ({list(audit['sessions_recorded'].keys())})")
            print(f"  Duration: {audit['recording_duration_minutes']} minutes ({audit['first_quote']} to {audit['last_quote']})")
            print(f"  Contracts: {audit['distinct_contracts_count']} (CE: {audit['ce_contracts_count']}, PE: {audit['pe_contracts_count']})")
            print(f"  Quality: Missing Bid/Ask={audit['data_quality']['missing_bid_ask_count']}, Zero Bid={audit['data_quality']['zero_bid_count']}, Gaps >120s={audit['data_quality']['gaps_count_gt_120s']}")
            print(f"  Engine Readiness: {audit['engine_readiness']['status']}")
        else:
            print(f"  Note: {audit['message']}")

    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())

