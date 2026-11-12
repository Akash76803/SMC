"""Phase 5-only diagnosis runner: no legacy reversal replay overhead.

Progress is written immediately to stderr, result JSON to stdout.
Optional --date isolates one session when testing terminal responsiveness.
"""
from __future__ import annotations
import argparse
import csv
import json
import sys
from pathlib import Path
from zoneinfo import ZoneInfo

from .backtest import BacktestConfig
from .csv_data import read_candles_csv
from .data_quality import audit_1m
from .historical_replay import ReplayConfig
from .multiday_replay import validate_hourly
from .phase5_report import replay_archetype
from .phase5_setups import STRATEGIES
from .research_sessions import regular_november_2026,regular_htf_without_special

IST=ZoneInfo("Asia/Kolkata")

def progress(message):
    print("[phase5] "+message,file=sys.stderr,flush=True)

def main():
    parser=argparse.ArgumentParser(description="Standalone Phase 5 index-only research runner")
    parser.add_argument("--ltf",required=True)
    parser.add_argument("--htf",required=True)
    parser.add_argument("--symbol",required=True,choices=("NIFTY","SENSEX"))
    parser.add_argument("--date",help="Optional YYYY-MM-DD for one trading day")
    parser.add_argument("--strategy",choices=STRATEGIES+("ALL",),default="ALL")
    parser.add_argument("--nov-2026-regular-only",action="store_true")
    parser.add_argument("--trades-out",help="Output CSV for any backtested trades")
    parser.add_argument("--result-out",help="Optional JSON output file")
    args=parser.parse_args()
    progress("Loading historical CSVs")
    ltf=list(read_candles_csv(args.ltf))
    htf=list(read_candles_csv(args.htf))
    if args.nov_2026_regular_only:
        ltf=list(regular_november_2026(ltf).candles)
        htf=list(regular_htf_without_special(htf))
    if args.date:
        ltf=[c for c in ltf if c.timestamp.astimezone(IST).date().isoformat()==args.date]
        if not ltf:
            parser.error("NO_LTF_CANDLES_FOR_DATE")
    quality=audit_1m(ltf)
    if not quality.safe_for_replay:
        parser.error("LTF_DATA_QUALITY_GATE_FAILED: "+",".join(sorted({x.code for x in quality.issues})))
    try:
        verified,excluded=validate_hourly(htf,ltf,60)
    except ValueError as error:
        parser.error(str(error))
    progress(f"Validated {len(ltf)} LTF candles, {len(verified)} full hourly HTF candles; {quality.days} session(s)")
    config=ReplayConfig(args.symbol,htf_duration_minutes=60)
    strategies=STRATEGIES if args.strategy=="ALL" else (args.strategy,)
    results={}
    rows=[]
    for strategy in strategies:
        progress(f"Starting {strategy}")
        report=replay_archetype(ltf,verified,config,strategy,BacktestConfig(),
                                progress=lambda day,n:progress(f"{strategy}: {day} completed ({n} candles)"))
        results[strategy]={
            "sessions":report.sessions,"signals_emitted":report.signals_emitted,
            "trades":len(report.trades),
            "diagnostics":report.diagnostics,
            "rejected_candidate_details":list(report.risk_rejections),
            "signals_rejected":report.signals_rejected,
            "signals_skipped":report.signals_skipped,
            "net_index_points":report.net_index_points,
            "win_rate":report.win_rate,
            "profit_factor":report.profit_factor,
            "max_drawdown_points":report.max_drawdown_points
        }
        for trade in report.trades:
            rows.append((strategy,trade.symbol,trade.side.value,
                         trade.signal_index,trade.entry_index,trade.exit_index,
                         trade.entry_price,trade.exit_price,trade.stop,trade.target,
                         trade.exit_reason.value,trade.net_index_points))
        progress(f"Finished {strategy}: {len(report.trades)} index-only trades")
    if args.trades_out:
        path=Path(args.trades_out)
        path.parent.mkdir(parents=True,exist_ok=True)
        with path.open("w",newline="",encoding="utf-8") as handle:
            writer=csv.writer(handle)
            writer.writerow(["strategy","symbol","side","signal_index","entry_index",
                             "exit_index","entry_price","exit_price","stop",
                             "target","exit_reason","net_index_points"])
            writer.writerows(rows)
    output={
       "mode":"INDEX_POINTS_ONLY_NOT_OPTION_PNL",
       "ltf_bars":len(ltf),
       "sessions":quality.days,
       "htf_terminal_partial_bars_excluded":excluded,
       "strategies":results,
       "warning":"Preliminary independent index research. Not option P&L, portfolio statistics or trade advice."
    }
    body=json.dumps(output,indent=2)
    if args.result_out:
        path=Path(args.result_out)
        path.parent.mkdir(parents=True,exist_ok=True)
        path.write_text(body+"\n",encoding="utf-8")
        progress("Saved JSON to "+str(path))
    else:
        print(body)

if __name__=="__main__":
    main()
