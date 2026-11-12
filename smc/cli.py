"""Run a deterministic demonstration; NOT a live market scanner."""
from __future__ import annotations
import argparse
import json
from datetime import datetime, timedelta, timezone
from .engine import analyze
from .models import Candle, IndexSetup, Side
from .risk import validate_index_setup


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--demo", action="store_true", help="Run fixed synthetic candles")
    args = p.parse_args()
    if not args.demo:
        p.print_help()
        return
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    closes = [100, 103, 106, 102, 98, 104, 109, 105, 101, 108,
              111, 107, 104, 110, 115, 112, 109, 116, 118, 114]
    candles = [
        Candle(start + timedelta(minutes=i), x-1, x+2, x-3, x, 1000)
        for i, x in enumerate(closes)
    ]
    result = analyze(candles)
    example = IndexSetup("NIFTY", Side.CE, 26000, 25975, 26060, False)
    validation = validate_index_setup(example)
    print(json.dumps({
        "mode": "SYNTHETIC_DEMO",
        "pivots": [p.__dict__ for p in result.pivots],
        "events": [e.__dict__ for e in result.events],
        "fvg_count": len(result.fvgs),
        "atr14": result.atr14,
        "trade_allowed": validation.accepted,
        "reasons": validation.reasons
    }, indent=2))


if __name__ == "__main__":
    main()
