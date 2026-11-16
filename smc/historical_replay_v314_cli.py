"""Offline V3.14 rerun of locally downloaded Angel 1m close-time CSV.

No broker auth, orders, inferred historical ticks or network calls.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from .angel_historical_research_cli_v313 import (analyze_downloaded,
                                                 export_brackets_csv)
from .csv_data import read_candles_csv


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Offline 9-session 1m historical SMC research with reconciliation")
    parser.add_argument("--symbol", choices=("NIFTY", "SENSEX"), required=True)
    parser.add_argument("--input-csv", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--candidates-csv", required=True)
    args = parser.parse_args()
    try:
        candles = read_candles_csv(args.input_csv)
        payload = analyze_downloaded(symbol=args.symbol, candles=candles)
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(payload, indent=2, allow_nan=False)+"\n",
                       encoding="utf-8")
        export_brackets_csv(payload, args.candidates_csv)
        print(f"V314_REPLAY_COMPLETE: sessions={payload['usable_sessions']} "
              f"recovered={payload['recovered_sessions']} "
              f"excluded={len(payload['excluded_sessions'])}")
        print("OUTCOMES: " + json.dumps(payload["outcome_counts"], sort_keys=True))
        print("NO_ORDERS | INDEX_POINTS_ONLY | NOT_VALIDATED_OPTIONS_STRATEGY")
        return 0 if payload["usable_sessions"] else 2
    except Exception:
        print("FAILED: REPLAY_INPUT_OR_ANALYSIS_ERROR")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
