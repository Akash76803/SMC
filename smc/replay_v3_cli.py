"""Command-line V3.7 index-only diagnostics from verified 1m historical CSV.

Examples:
python -m smc.replay_v3_cli --ltf data/nifty_1m.csv --symbol NIFTY --out results/v37.json

M/W/D files are optional. Without *correctly aggregated, close-stamped*
HTF inputs the analysis stays unverified; never aggregate from 1m by guess.
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path

from .csv_data import read_candles_csv
from .data_quality import audit_1m
from .replay_v3 import replay_unified_reversal


def main() -> None:
    p=argparse.ArgumentParser(description="Research-only V3.7 closed-bar diagnostic replay")
    p.add_argument("--ltf",required=True,help="Historical CLOSED-timestamp one-minute CSV")
    p.add_argument("--monthly",help="Optional verified month CLOSE-timestamp candles")
    p.add_argument("--weekly",help="Optional verified week CLOSE-timestamp candles")
    p.add_argument("--daily",help="Optional verified daily CLOSE-timestamp candles")
    p.add_argument("--symbol",required=True,choices=("NIFTY","SENSEX"))
    p.add_argument("--out",required=True)
    p.add_argument("--max-holding-bars",type=int,default=24)
    p.add_argument("--warmup-bars",type=int,default=16)
    a=p.parse_args()
    ltf=list(read_candles_csv(a.ltf))
    if not ltf:
        p.error("NO_LTF_CANDLES")
    q=audit_1m(ltf)
    if not q.safe_for_replay:
        p.error("LTF_DATA_QUALITY_FAILED: "+",".join(sorted({x.code for x in q.issues})))
    htf={
        k:list(read_candles_csv(v)) if v else []
        for k,v in (("monthly",a.monthly),("weekly",a.weekly),("daily",a.daily))
    }
    result=replay_unified_reversal(
        symbol=a.symbol,ltf=ltf,data_healthy=True,
        max_holding_bars=a.max_holding_bars,min_warmup_bars=a.warmup_bars,
        **htf)
    dest=Path(a.out)
    dest.parent.mkdir(parents=True,exist_ok=True)
    dest.write_text(json.dumps(result.as_dict(),indent=2)+"\n",encoding="utf-8")
    print(f"RESEARCH_ONLY: {result.evaluated_prefixes} closed-bar prefixes; "
          f"{len(result.observations)} distinct terminal observations; "
          f"{result.diagnostic_brackets} hypothetical brackets")
    print(f"Output: {dest}")


if __name__=="__main__":
    main()
