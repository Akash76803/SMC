"""Date-scoped SMC research replay; never carries fills overnight."""
from __future__ import annotations
import argparse
import csv
import json
from collections import Counter
from pathlib import Path

from .backtest import BacktestConfig
from .csv_data import read_candles_csv
from .data_quality import audit_1m,drop_terminal_1530
from .historical_replay import ReplayConfig
from .multiday_replay import replay_by_session,validate_hourly
from .structure_diagnostics import audit_choch_link


def summarize_snapshots(snapshots):
    states=Counter(s.state for s in snapshots)
    reasons=Counter(s.reason for s in snapshots)
    entry_states=Counter()
    entry_reasons=Counter()
    for s in snapshots:
        entry_states.update(dict(getattr(s,"entry_state_counts",())))
        entry_reasons.update(dict(getattr(s,"entry_reason_counts",())))
    last=next((s for s in reversed(snapshots) if getattr(s,"entry_state_counts",())),None)
    return {
        "states":dict(sorted(states.items())),
        "reasons":dict(sorted(reasons.items())),
        "entry_state_observations":dict(sorted(entry_states.items())),
        "entry_reason_observations":dict(sorted(entry_reasons.items())),
        "last_evaluated_entry_states":dict(getattr(last,"entry_state_counts",())) if last else {},
        "note":"Observations repeat historical sweeps across prefixes; NOT independent signals/trades."
    }


def main():
    parser=argparse.ArgumentParser(description="Session-safe experimental INDEX replay")
    parser.add_argument("--ltf",required=True)
    parser.add_argument("--htf",required=True)
    parser.add_argument("--symbol",required=True,choices=("NIFTY","SENSEX"))
    parser.add_argument("--htf-minutes",type=int,default=60)
    parser.add_argument("--max-target-atr",type=float,default=4.0)
    parser.add_argument("--out",help="Trades CSV")
    parser.add_argument("--setups-out",help="One row per unique sweep (diagnostic CSV)")
    parser.add_argument("--drop-terminal-1530",action="store_true",
                        help="Exclude isolated closing record after 15:15; never interpolate")
    args=parser.parse_args()
    ltf=read_candles_csv(args.ltf)
    htf=read_candles_csv(args.htf)
    if args.drop_terminal_1530:
        ltf=list(drop_terminal_1530(ltf))
    audit=audit_1m(ltf)
    if not audit.safe_for_replay:
        parser.error("LTF_DATA_QUALITY_GATE_FAILED: "+",".join(sorted({x.code for x in audit.issues})))
    config=ReplayConfig(args.symbol,htf_duration_minutes=args.htf_minutes,
                        max_target_atr=args.max_target_atr)
    try:
        verified,excluded=validate_hourly(htf,ltf,args.htf_minutes)
        result=replay_by_session(ltf,htf,config,BacktestConfig())
    except ValueError as exc:
        parser.error(str(exc))
    if args.out:
        path=Path(args.out)
        path.parent.mkdir(parents=True,exist_ok=True)
        with path.open("w",newline="",encoding="utf-8") as f:
            writer=csv.writer(f)
            writer.writerow(["symbol","side","signal_index","entry_index","exit_index",
                             "entry_price","exit_price","stop","target","exit_reason","net_index_points"])
            for t in result.trades:
                writer.writerow([t.symbol,t.side.value,t.signal_index,t.entry_index,t.exit_index,
                                 t.entry_price,t.exit_price,t.stop,t.target,t.exit_reason.value,
                                 t.net_index_points])
    if args.setups_out:
        path=Path(args.setups_out)
        path.parent.mkdir(parents=True,exist_ok=True)
        with path.open("w",newline="",encoding="utf-8") as f:
            writer=csv.DictWriter(f,fieldnames=["date","sweep_time","liquidity_kind",
                 "liquidity_price","side","state","reason","choch_time","fvg_time",
                 "entry","stop","target","index_rr"])
            writer.writeheader()
            for session in result.sessions:
                for item in session.unique_setups:
                    writer.writerow({"date":session.date,**item})
    counts=Counter()
    for session in result.sessions:
        counts.update(session.unique_sweep_outcomes)
    print(json.dumps({
        "mode":"INDEX_POINTS_ONLY_NOT_OPTION_PNL",
        "ltf_bars":len(ltf),"htf_bars":len(htf),
        "htf_full_hour_bars":len(verified),
        "htf_terminal_partial_bars_excluded":excluded,
        "sessions":len(result.sessions),
        "session_breakdown":[{"date":s.date,"ltf_bars":s.candles,
             "unique_sweeps":len(s.unique_setups),
             "trades":len(s.trades)} for s in result.sessions],
        "snapshots":len(result.snapshots),
        "signals_emitted":sum(s.signal is not None for s in result.snapshots),
        "signal_diagnostics":summarize_snapshots(result.snapshots),
        "unique_sweep_outcomes":dict(sorted(counts.items())),
        "risk_rejection_details":[{"date":session.date,**snapshot.rejection_detail}
             for session in result.sessions for snapshot in session.snapshots
             if snapshot.rejection_detail is not None],
        "unique_sweeps_total":sum(counts.values()),
        "structure_link_diagnostics_by_day":{
             s.date:audit_choch_link([c for c in ltf
              if c.timestamp.astimezone(__import__("zoneinfo").ZoneInfo("Asia/Kolkata")).date().isoformat()==s.date])
             for s in result.sessions},
        "trades":len(result.trades),"signals_rejected":result.rejected,
        "signals_skipped":result.skipped,
        "total_net_index_points":result.total_net_index_points,
        "win_rate":result.win_rate,
        "profit_factor":result.profit_factor,
        "max_drawdown_points":result.max_drawdown_points,
        "warning":"SESSION-SCOPED INDEX ONLY; NO OPTION PREMIUM OR VERIFIED PERFORMANCE"
    },indent=2))

if __name__=="__main__":
    main()
