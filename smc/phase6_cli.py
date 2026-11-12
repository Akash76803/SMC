"""Phase 6 CLI: offline observed quote replay, never a broker order."""
from __future__ import annotations
import argparse,csv,json
from datetime import datetime
from pathlib import Path
from .models import Side
from .phase6_premium import Signal,Settings,read_quotes,replay

def main():
    p=argparse.ArgumentParser(description="Research only: observed CE/PE premium bid-ask replay")
    p.add_argument("--signals",required=True,help="Phase5 --signals-out CSV")
    p.add_argument("--quotes",required=True,help="Actual historical option quotes CSV")
    p.add_argument("--target",type=float,default=25)
    p.add_argument("--stop",type=float,default=10)
    p.add_argument("--cost-per-unit",type=float,default=1)
    p.add_argument("--out",default="phase6_trades.csv")
    p.add_argument("--result-out",default="phase6_result.json")
    args=p.parse_args()
    signals=[]
    with open(args.signals,newline="",encoding="utf-8-sig") as f:
        reader=csv.DictReader(f)
        if reader.fieldnames is None or not {'timestamp','symbol','side','strategy'}.issubset(reader.fieldnames):
            p.error("SIGNALS_CSV_COLUMNS_MISSING")
        for row in reader:
            signals.append(Signal(datetime.fromisoformat(row['timestamp']),
                                  row['symbol'].strip().upper(),
                                  Side(row['side'].strip().upper()),
                                  row['strategy'].strip()))
    if not signals:p.error("NO_APPROVED_SIGNALS")
    try:
        quotes=read_quotes(args.quotes)
        cfg=Settings(target_points=args.target,stop_points=args.stop,
                     cost_per_unit=args.cost_per_unit)
        trades,skipped=replay(signals,quotes,cfg)
    except ValueError as error:
        p.error(str(error))
    out=Path(args.out)
    out.parent.mkdir(parents=True,exist_ok=True)
    cols=['strategy','symbol','side','strike','expiry','signal_time','entry_time',
          'exit_time','entry_ask','exit_bid','target_bid','stop_bid',
          'exit_reason','net_per_unit','lot_size','net_one_lot']
    with out.open('w',encoding='utf-8',newline='') as f:
        w=csv.DictWriter(f,fieldnames=cols)
        w.writeheader()
        for t in trades:
            w.writerow({key:(getattr(t,key).value if key=='side' else getattr(t,key))
                        for key in cols})
    total=sum(t.net_one_lot for t in trades)
    data={"mode":"OBSERVED_OPTION_QUOTES_PAPER_REPLAY_NOT_LIVE",
          "signals":len(signals),"quotes":len(quotes),"trades":len(trades),
          "skipped":skipped,"target_premium_points":args.target,
          "stop_premium_points":args.stop,
          "cost_per_unit":args.cost_per_unit,
          "net_one_lot_rupees_sequential_sum":total,
          "warning":"No execution guarantee; sparse quotes and market impact remain unobserved. One lot per trade assumed; never aggregate independent strategies as proven live profits."}
    dst=Path(args.result_out)
    dst.parent.mkdir(parents=True,exist_ok=True)
    dst.write_text(json.dumps(data,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(data,indent=2))

if __name__=='__main__':
    main()
