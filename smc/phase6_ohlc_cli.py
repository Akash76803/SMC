"""Phase 6.3 offline index-signal to OPTION OHLC scenario comparison.

NOT historical bid/ask execution and NOT a combined option portfolio.
"""
from __future__ import annotations
import argparse,csv,json
from collections import defaultdict
from pathlib import Path
from dataclasses import asdict
from .phase6_ohlc import read_events,read_series,simulate

def main():
    p=argparse.ArgumentParser(description="Research-only option OHLC comparison; no orders")
    p.add_argument("--signals",required=True,help="Phase5 --signals-out CSV")
    p.add_argument("--option-ohlc",nargs="+",required=True,help="One or more exact contract CSVs from angel_option_history_cli")
    p.add_argument("--target",type=float,default=25.0)
    p.add_argument("--stop",type=float,default=10.0)
    p.add_argument("--holding-bars",type=int,default=24)
    p.add_argument("--out",default="phase6_ohlc_trades.csv")
    p.add_argument("--result-out",default="phase6_ohlc_result.json")
    args=p.parse_args()
    try:
        signals=read_events(args.signals)
        if not signals:p.error("NO_INDEX_SIGNALS")
        result=[]
        detail=[]
        for name in args.option_ohlc:
            series=read_series(name)
            trades,skips=simulate(signals,series,target_points=args.target,
                                   stop_points=args.stop,hold_bars=args.holding_bars)
            for trade in trades:
                row=asdict(trade)
                row.update({key:row[key].isoformat() for key in ("signal_time","entry_time","exit_time")})
                detail.append(row)
            result.append({"contract":series.trading_symbol,
                           "source":str(name),"candles":len(series.candles),
                           "signals_total":len(signals),
                           "research_scenarios":len(trades),
                           "target_hit":sum(t.exit_reason.startswith("TARGET") for t in trades),
                           "stop_hit":sum(t.exit_reason.startswith("STOP") for t in trades),
                           "time_exit":sum(t.exit_reason.startswith("TIME_EXIT") for t in trades),
                           "skips":skips,
                           "gross_premium_points_sum_independent":sum(t.gross_premium_points for t in trades)})
    except (ValueError,OSError) as exc:
        p.error(str(exc))
    fieldnames=["strategy","trading_symbol","signal_time","entry_time","exit_time",
               "entry_open","exit_assumed","target","stop","exit_reason",
               "gross_premium_points","max_favorable_envelope","max_adverse_envelope"]
    out=Path(args.out);out.parent.mkdir(parents=True,exist_ok=True)
    with out.open("w",encoding="utf-8",newline="") as f:
        writer=csv.DictWriter(f,fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(detail)
    payload={"mode":"OPTION_OHLC_SCENARIO_ONLY_NOT_EXECUTABLE_BID_ASK_PNL",
             "target_premium_points":args.target,"stop_premium_points":args.stop,
             "contracts":result,
             "warning":"Comparison is independent by contract and signal. OHLC open/threshold fills are hypothetical and omit spread, fees and slippage. In the same candle STOP wins over TARGET; missing continuous candles generate no completed scenario. NOT a portfolio, not verified realized profit."}
    path=Path(args.result_out);path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(payload,indent=2)+"\n",encoding="utf-8")
    print(json.dumps(payload,indent=2))

if __name__=="__main__":
    main()
