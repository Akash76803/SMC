"""Evidence-only historical self-learning report from stored *observed* option bids.

Inputs: live SMC closed-candle decision reports and verified broker option
quote-tape JSONL. Output: frozen holdout evaluation, NEVER production trading
policy. Missing data causes INSUFFICIENT_EVIDENCE instead of synthetic trades.
"""
from __future__ import annotations
import argparse
import json
from datetime import datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo
from .models import Side
from .phase6_premium import Signal, Quote
from .self_learning_research_v319 import evaluate_walk_forward

IST=ZoneInfo("Asia/Kolkata")


def read_index_signals(path: str | Path, *, market: str) -> list[Signal]:
    output: list[Signal] = []
    seen=set()
    try:
        source=Path(path).read_text(encoding="utf-8")
    except OSError:
        return []
    for line in source.splitlines():
        try:
            event=json.loads(line)
            if (not isinstance(event,dict) or event.get("symbol")!=market or
                event.get("status")!="RESEARCH_ONLY" or
                event.get("research_only") is not True or
                event.get("orders_enabled") is not False or
                (event.get("stream_quality") or {}).get("quality_blocked") is not False):
                continue
            bracket=event.get("index_bracket_research") or {}
            if bracket.get("status")!="RESEARCH_INDEX_BRACKET_PASSES":
                continue
            at=datetime.fromisoformat(event["last_candle_close_at"])
            if at.tzinfo is None:
                continue
            for setup in event.get("ict_active_lifecycles",[]):
                if (setup.get("state")!="RETEST_CONFIRMED_RESEARCH" or
                    setup.get("retest_at")!=at.isoformat()):
                    continue
                side=Side.CE if setup.get("direction")=="BULLISH" else (
                    Side.PE if setup.get("direction")=="BEARISH" else None)
                if side is None:
                    continue
                key=(at,side)
                if key in seen:continue
                seen.add(key)
                output.append(Signal(at,market,side,"ICT_SWEEP_CHOCH_OB_RETEST"))
        except (ValueError,TypeError,KeyError,AttributeError):
            continue
    return sorted(output,key=lambda item:item.timestamp)


def read_observed_quotes(path: str | Path, *, market: str) -> list[Quote]:
    rows=[];seen=set()
    try:source=Path(path).read_text(encoding="utf-8")
    except OSError:return []
    for line in source.splitlines():
        try:
            item=json.loads(line)
            if (not isinstance(item,dict) or item.get("market")!=market or
                item.get("orders_enabled") is not False or
                item.get("research_only") is not True):
                continue
            stamp=datetime.fromisoformat(item["quote_at"])
            if stamp.tzinfo is None:continue
            expiry=datetime.combine(
                datetime.fromisoformat(item["expiry"]).date(),
                time(15,30),IST)
            if expiry<=stamp:continue
            side=Side(item["side"])
            # Actual contract identity must be preserved: no merging
            # two different expiry/strike option series.
            quote=Quote(stamp,market,side,float(item["strike"]),expiry,
                        float(item["bid"]),float(item["ask"]),
                        int(item["lot_size"]),int(item["volume"]),
                        float(item["delta"]) if item.get("delta") is not None else None)
            key=(quote.contract,quote.timestamp)
            if key in seen:continue
            seen.add(key)
            rows.append(quote)
        except (ValueError,TypeError,KeyError):
            continue
    return sorted(rows,key=lambda row:row.timestamp)


def run_learning(*, market: str, event_file: str | Path,
                 quote_file: str | Path) -> dict:
    if market not in ("NIFTY","SENSEX"):
        raise ValueError("INVALID_MARKET")
    signals=read_index_signals(event_file,market=market)
    quotes=read_observed_quotes(quote_file,market=market)
    result=evaluate_walk_forward(signals,quotes)
    return {
        "symbol":market,"recorded_signals":len(signals),
        "observed_quote_samples":len(quotes),
        **result,
    }


def main() -> int:
    p=argparse.ArgumentParser(description="Quote-observed offline self-learning audit; NO ORDERS")
    p.add_argument("--market",choices=("NIFTY","SENSEX"),required=True)
    p.add_argument("--events",required=True)
    p.add_argument("--option-tape",required=True)
    p.add_argument("--out",required=True)
    args=p.parse_args()
    result=run_learning(market=args.market,event_file=args.events,quote_file=args.option_tape)
    target=Path(args.out);target.parent.mkdir(parents=True,exist_ok=True)
    target.write_text(json.dumps(result,indent=2,allow_nan=False)+"\n",encoding="utf-8")
    print(f"SELF_LEARNING_RESEARCH: {args.market} {result['status']} "
          f"events={result['recorded_signals']} "
          f"quotes={result['observed_quote_samples']}")
    print("NO_AUTOMATIC_STRATEGY_PROMOTION | NO_LIVE_ORDERS")
    return 0


if __name__=="__main__":
    raise SystemExit(main())
