"""Research-only V3.9B continuation validation CLI for one complete regular day.

No trade fills, no option price prediction, no cross-session carry, no auto
weekly/monthly inference. Do not turn provisional entry/stop into orders.
"""
from __future__ import annotations

import argparse
from collections import Counter
from pathlib import Path

from .continuation_v3 import detect_continuation_observations
from .continuation_validation_v3 import validate_continuation
from .csv_data import read_candles_csv
from .data_quality import audit_1m
from .htf_context_v3 import analyze_htf
from .phase2 import scan
from .replay_v3_cli import write_replay_json


def build_report(*, symbol, candles, monthly=(), weekly=(), daily=()):
    audit = audit_1m(candles)
    if not audit.safe_for_replay or len(candles) != 360 or audit.days != 1:
        raise ValueError("CONTINUATION_REQUIRES_AUDITED_COMPLETE_REGULAR_SESSION")
    events = detect_continuation_observations(list(candles))
    results = []
    for event in events:
        # Strict prefix at the actual closed-bar confirmation; never use later
        # levels or bars to improve historical target selection.
        prefix = list(candles[:event.confirm_index + 1])
        at = prefix[-1].timestamp
        context = analyze_htf(
            monthly=[c for c in monthly if c.timestamp <= at],
            weekly=[c for c in weekly if c.timestamp <= at],
            daily=[c for c in daily if c.timestamp <= at],
            as_of=at)
        evidence = scan(prefix)
        decision = validate_continuation(
            symbol=symbol, candles=prefix, observation=event,
            context=context, levels=list(evidence.levels),
            events=list(evidence.liquidity_events))
        item = decision.as_dict()
        item["bos_time"] = candles[event.bos_index].timestamp.isoformat()
        item["pullback_time"] = candles[event.pullback_index].timestamp.isoformat()
        results.append(item)
    return {
        "schema_version": "3.9b",
        "symbol": symbol,
        "session": candles[0].timestamp.date().isoformat(),
        "observed_bars": len(candles),
        "continuation_observations": len(events),
        "status_counts": dict(Counter(x["status"] for x in results)),
        "reason_counts": dict(Counter(x["reason"] for x in results)),
        "observations": results,
        "qualified_trades": 0,
        "option_pnl": None,
        "live_orders_enabled": False,
        "research_only": True,
    }


def main():
    p = argparse.ArgumentParser(description="V3.9B continuation validation; NO TRADE execution")
    p.add_argument("--ltf", required=True)
    p.add_argument("--symbol", choices=("NIFTY", "SENSEX"), required=True)
    p.add_argument("--monthly")
    p.add_argument("--weekly")
    p.add_argument("--daily")
    p.add_argument("--out", required=True)
    args = p.parse_args()
    candles = read_candles_csv(args.ltf)
    kwargs = {key: read_candles_csv(getattr(args, key)) if getattr(args, key) else ()
              for key in ("monthly", "weekly", "daily")}
    try:
        payload = build_report(symbol=args.symbol, candles=candles, **kwargs)
    except ValueError as exc:
        p.error(str(exc))
    path = Path(args.out)
    path.parent.mkdir(parents=True, exist_ok=True)
    write_replay_json(path, payload)
    print("RESEARCH_ONLY: " + str(payload["continuation_observations"])
          + " continuation observations; 0 executable trades")
    print("Output: " + str(path))


if __name__ == "__main__":
    main()
