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
from .data_quality import audit_1m, drop_terminal_1530
from .replay_v3 import replay_unified_reversal
from .htf_aggregation_v3 import aggregate_regular_1m


def prepare_ltf_for_replay(candles, *, drop_isolated_terminal_1530: bool = False):
    """Exclude only explicit isolated 15:30 terminal bars; re-audit all remaining bars."""
    retained = (list(drop_terminal_1530(candles))
                if drop_isolated_terminal_1530 else list(candles))
    quality = audit_1m(retained)
    if not quality.safe_for_replay:
        codes = ",".join(sorted({issue.code for issue in quality.issues}))
        raise ValueError("LTF_DATA_QUALITY_FAILED: " + codes)
    return retained, len(candles) - len(retained)


def write_replay_json(path: Path, payload: dict) -> None:
    """Write standards-compliant JSON followed by exactly one real newline."""
    path.write_text(json.dumps(payload, indent=2) + chr(10), encoding="utf-8")


def main() -> None:
    p=argparse.ArgumentParser(description="Research-only V3.7 closed-bar diagnostic replay")
    p.add_argument("--ltf",required=True,help="Historical CLOSED-timestamp one-minute CSV")
    p.add_argument("--monthly",help="Optional verified month CLOSE-timestamp candles")
    p.add_argument("--weekly",help="Optional verified week CLOSE-timestamp candles")
    p.add_argument("--daily",help="Optional verified daily CLOSE-timestamp candles")
    p.add_argument("--symbol",required=True,choices=("NIFTY","SENSEX"))
    p.add_argument("--out",required=True)
    p.add_argument("--drop-terminal-1530", action="store_true",
                   help="Omit only isolated 15:30 bars after same-day 15:15; all other gaps still fail")
    p.add_argument("--max-holding-bars",type=int,default=24)
    p.add_argument("--warmup-bars",type=int,default=16)
    p.add_argument("--aggregate-regular-htf",action="store_true",
                   help="Derive only full-session 5m/15m/1h/daily; never infer weekly/monthly completion")
    a=p.parse_args()
    ltf=list(read_candles_csv(a.ltf))
    if not ltf:
        p.error("NO_LTF_CANDLES")
    try:
        ltf, removed_terminal = prepare_ltf_for_replay(
            ltf, drop_isolated_terminal_1530=a.drop_terminal_1530)
    except ValueError as error:
        p.error(str(error))
    htf={
        k:list(read_candles_csv(v)) if v else []
        for k,v in (("monthly",a.monthly),("weekly",a.weekly),("daily",a.daily))
    }
    aggregation = None
    if a.aggregate_regular_htf:
        try:
            aggregation = aggregate_regular_1m(ltf)
        except ValueError as error:
            p.error("HTF_AGGREGATION_FAILED: "+str(error))
        if a.daily is not None:
            p.error("CANNOT_COMBINE_DAILY_CSV_WITH_AUTO_DAILY")
        htf["daily"] = list(aggregation.daily)
    result=replay_unified_reversal(
        symbol=a.symbol,ltf=ltf,data_healthy=True,
        max_holding_bars=a.max_holding_bars,min_warmup_bars=a.warmup_bars,
        **htf)
    dest=Path(a.out)
    dest.parent.mkdir(parents=True,exist_ok=True)
    payload = result.as_dict()
    if aggregation is not None:
        payload["htf_aggregation"] = aggregation.as_dict()
    write_replay_json(dest, payload)
    print(f"Quality gate passed; excluded {removed_terminal} isolated 15:30 record(s)")
    print(f"RESEARCH_ONLY: {result.evaluated_prefixes} closed-bar prefixes; "
          f"{len(result.observations)} distinct terminal observations; "
          f"{result.diagnostic_brackets} hypothetical brackets")
    print(f"Output: {dest}")


if __name__=="__main__":
    main()
