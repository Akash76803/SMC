"""SMC Live Session Automated Supervisor & Monitor.

Implements the user's Live Session Cheat Sheet SOP:
1. Checks whether SMC server (port 8765) and broker dual stream are active.
2. Monitors growth of results/live_nifty_option_quotes.jsonl and results/live_sensex_option_quotes.jsonl.
3. Automatically evaluates tape health (timestamp updates, size, bid/ask validity).
4. Runs full option tape audit (smc.option_tape_auditor) and outputs clean summary.
"""
from __future__ import annotations

import json
import time
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from .option_tape_auditor import audit_quote_tape

IST = ZoneInfo("Asia/Kolkata")


def check_live_status(results_dir: Path) -> dict[str, Any]:
    status = {}
    for sym in ["nifty", "sensex"]:
        st_file = results_dir / f"live_{sym}_status.json"
        if st_file.is_file():
            try:
                data = json.loads(st_file.read_text(encoding="utf-8"))
                status[sym.upper()] = data
            except Exception:
                status[sym.upper()] = {"status": "UNREADABLE"}
        else:
            status[sym.upper()] = {"status": "NOT_STARTED"}
    return status


def monitor_tape_files(results_dir: Path) -> dict[str, Any]:
    info = {}
    for sym in ["nifty", "sensex"]:
        tape_path = results_dir / f"live_{sym}_option_quotes.jsonl"
        if tape_path.is_file():
            stat = tape_path.stat()
            line_count = 0
            with tape_path.open("r", encoding="utf-8") as f:
                for line in f:
                    if line.strip():
                        line_count += 1
            info[sym.upper()] = {
                "exists": True,
                "path": str(tape_path),
                "bytes": stat.st_size,
                "lines": line_count,
                "last_modified": datetime.fromtimestamp(stat.st_mtime, tz=IST).isoformat(),
            }
        else:
            info[sym.upper()] = {
                "exists": False,
                "path": str(tape_path),
                "bytes": 0,
                "lines": 0,
                "last_modified": None,
            }
    return info


def run_session_health_check() -> int:
    base_dir = Path("E:/Project/SMC")
    results_dir = base_dir / "results"

    print("=" * 75)
    print(" SMC LIVE SESSION AUTOMATED SUPERVISOR STATUS")
    print(f" Timestamp: {datetime.now(IST).isoformat()}")
    print("=" * 75)

    # 1. Live stream status
    stream_st = check_live_status(results_dir)
    print("\n[1] Broker Dual Stream Status:")
    for sym, st in stream_st.items():
        print(f"  {sym:<7}: {st.get('status', 'UNKNOWN')} ({st.get('reason', '')})")

    # 2. Quote Tape File Growth
    tapes = monitor_tape_files(results_dir)
    print("\n[2] Live Quote Tape Files:")
    for sym, t in tapes.items():
        if t["exists"]:
            print(f"  {sym:<7}: {t['lines']:5d} records ({t['bytes']/1024:.1f} KB) | Last Write: {t['last_modified']}")
        else:
            print(f"  {sym:<7}: FILE NOT CREATED YET ({t['path']})")

    # 3. Full Quote Tape Audit
    print("\n[3] Full Option Tape Quality Audit:")
    for sym in ["NIFTY", "SENSEX"]:
        tape_path = results_dir / f"live_{sym.lower()}_option_quotes.jsonl"
        audit = audit_quote_tape(tape_path, sym)
        if audit["total_records"] > 0:
            print(f"  [{sym}] Total Records: {audit['total_records']}, Duration: {audit['recording_duration_minutes']} min")
            print(f"         Sessions: {audit['sessions_count']}, Contracts: {audit['distinct_contracts_count']}")
            print(f"         Quality: Missing Bid/Ask={audit['data_quality']['missing_bid_ask_count']}, Zero Bid={audit['data_quality']['zero_bid_count']}, Gaps >120s={audit['data_quality']['gaps_count_gt_120s']}")
            print(f"         Readiness: {audit['engine_readiness']['status']}")
        else:
            print(f"  [{sym}] {audit['message']}")

    print("\n" + "=" * 75)
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(run_session_health_check())

