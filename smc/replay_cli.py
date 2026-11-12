"""CSV-to-index-replay command. No live quotes and no option premium PnL."""
from __future__ import annotations
import argparse
import csv
import json
from pathlib import Path

from .backtest import BacktestConfig, walk_forward_backtest
from .csv_data import read_candles_csv
from .historical_replay import ReplayConfig, SMCReplay


def main() -> None:
    parser=argparse.ArgumentParser(description="SMC historical INDEX research replay")
    parser.add_argument("--ltf",required=True,help="LTF CSV with CLOSE timestamps")
    parser.add_argument("--htf",required=True,help="HTF CSV with START timestamps")
    parser.add_argument("--symbol",required=True,choices=["SENSEX","NIFTY"])
    parser.add_argument("--htf-minutes",type=int,default=60)
    parser.add_argument("--max-target-atr",type=float,default=4.0)
    parser.add_argument("--out",help="Write per-trade CSV report")
    args=parser.parse_args()
    ltf=read_candles_csv(args.ltf)
    htf=read_candles_csv(args.htf)
    engine=SMCReplay(ReplayConfig(args.symbol,
                         htf_duration_minutes=args.htf_minutes,
                         max_target_atr=args.max_target_atr),htf)
    report=walk_forward_backtest(ltf,engine,BacktestConfig())
    if args.out:
        path=Path(args.out)
        with path.open("w",newline="",encoding="utf-8") as f:
            writer=csv.writer(f)
            writer.writerow(["symbol","side","signal_index","entry_index",
                             "exit_index","entry_price","exit_price","stop",
                             "target","exit_reason","net_index_points"])
            for t in report.trades:
                writer.writerow([t.symbol,t.side.value,t.signal_index,
                                 t.entry_index,t.exit_index,t.entry_price,
                                 t.exit_price,t.stop,t.target,t.exit_reason.value,
                                 t.net_index_points])
    print(json.dumps({
        "mode":report.mode,
        "ltf_bars":len(ltf),
        "htf_bars":len(htf),
        "snapshots":len(engine.snapshots),
        "signals_emitted":sum(x.signal is not None for x in engine.snapshots),
        "trades":len(report.trades),
        "signals_rejected":report.signals_rejected,
        "signals_skipped":report.signals_skipped,
        "total_net_index_points":report.total_net_index_points,
        "win_rate":report.win_rate,
        "profit_factor":report.profit_factor,
        "max_drawdown_points":report.max_drawdown_points,
        "warning":"NOT OPTION PREMIUM PNL / NOT VERIFIED STRATEGY PERFORMANCE"
    },indent=2))


if __name__=="__main__":
    main()
