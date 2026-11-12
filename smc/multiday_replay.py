"""Safe date-partitioned index replay with independently audited sessions.

Each session owns its pending entries and open position; the existing
backtester closes the position on its final bar. Nothing is carried overnight.
HTF starts are validated and partial 15:15 bars deliberately excluded.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass,replace
from datetime import time
from typing import Sequence
from zoneinfo import ZoneInfo

from .backtest import BacktestConfig,BacktestTrade,walk_forward_backtest
from .data_quality import audit_1m
from .entry_v1 import evaluate_entry
from .engine import fair_value_gaps
from .historical_replay import ReplayConfig,SMCReplay,ReplaySnapshot
from .models import Candle
from .phase2 import scan

IST=ZoneInfo("Asia/Kolkata")

@dataclass(frozen=True)
class SessionResult:
    date:str
    candles:int
    snapshots:tuple[ReplaySnapshot,...]
    trades:tuple[BacktestTrade,...]
    rejected:int
    skipped:int
    unique_sweep_outcomes:dict[str,int]
    unique_setups:tuple[dict,...]

@dataclass(frozen=True)
class MultiDayResult:
    sessions:tuple[SessionResult,...]
    trades:tuple[BacktestTrade,...]
    snapshots:tuple[ReplaySnapshot,...]
    rejected:int
    skipped:int
    total_net_index_points:float
    win_rate:float|None
    profit_factor:float|None
    max_drawdown_points:float

def group_days(candles:Sequence[Candle])->list[tuple[str,list[Candle],int]]:
    groups=[]
    for index,c in enumerate(candles):
        day=c.timestamp.astimezone(IST).date().isoformat()
        if groups and groups[-1][0]==day:
            groups[-1][1].append(c)
        else:
            groups.append((day,[c],index))
    return groups

def validate_hourly(htf:Sequence[Candle],ltf:Sequence[Candle],duration_minutes:int
                    )->tuple[tuple[Candle,...],int]:
    if duration_minutes!=60:
        raise ValueError("HTF_QUALITY_REQUIRES_60_MINUTE_INTERVAL")
    if not htf or not ltf:
        raise ValueError("LTF_AND_HTF_REQUIRED")
    previous=None
    approved=[]
    dropped=0
    for c in htf:
        t=c.timestamp.astimezone(IST)
        if not c.complete or (previous is not None and c.timestamp<=previous):
            raise ValueError("HTF_NOT_COMPLETE_OR_NOT_SORTED")
        previous=c.timestamp
        if t.time() not in {time(9,15),time(10,15),time(11,15),
                            time(12,15),time(13,15),time(14,15),time(15,15)}:
            raise ValueError("HTF_START_NOT_HOURLY_SESSION_ALIGNED")
        if t.time()==time(15,15):
            # May represent a 15m residual bar; never present as a full hour.
            dropped+=1
            continue
        approved.append(c)
    if not approved:
        raise ValueError("NO_FULL_HOURLY_HTF_CANDLES")
    if approved[0].timestamp>=ltf[0].timestamp:
        raise ValueError("HTF_HISTORY_MUST_PRECEDE_LTF")
    return tuple(approved),dropped

def final_sweep_audit(candles:Sequence[Candle],symbol:str)->tuple[dict[str,int],tuple[dict,...]]:
    """One final diagnostic per actual sweep event; never sample repeated prefixes.

    REJECTED/MISSING_VERIFIED_LIQUIDITY_TARGET means preliminary evaluator has
    no target by design; it is not a final execution rejection.
    """
    phase=scan(list(candles))
    events=[e for e in phase.liquidity_events
            if e.kind=="SWEEP" and e.level.kind in ("BSL","SSL","EQH","EQL","PDH","PDL")]
    entries=evaluate_entry(list(candles),events,list(phase.structure_events),
                           symbol=symbol,target=None,fvgs=fair_value_gaps(list(candles)))
    if len(events)!=len(entries):
        raise ValueError("SWEEP_ENTRY_AUDIT_MISMATCH")
    records=[]
    for event,outcome in zip(events,entries):
        records.append({
            "sweep_time":candles[event.candle_index].timestamp.isoformat(),
            "liquidity_kind":event.level.kind,
            "liquidity_price":event.level.price,
            "side":outcome.side.value,
            "state":outcome.state.value,
            "reason":outcome.reason,
            "choch_time":candles[outcome.choch_index].timestamp.isoformat()
                         if outcome.choch_index is not None else None,
            "fvg_time":candles[outcome.fvg_index].timestamp.isoformat()
                        if outcome.fvg_index is not None else None,
            "entry":outcome.entry,
            "stop":outcome.stop,
            "target":outcome.target,
            "index_rr":outcome.index_rr,
        })
    return dict(sorted(Counter(r["reason"] for r in records).items())),tuple(records)

def replay_by_session(ltf:Sequence[Candle],htf:Sequence[Candle],
                      config:ReplayConfig,
                      backtest_config:BacktestConfig=BacktestConfig())->MultiDayResult:
    if not audit_1m(ltf).safe_for_replay:
        raise ValueError("LTF_DATA_QUALITY_GATE_FAILED")
    verified,dropped=validate_hourly(htf,ltf,config.htf_duration_minutes)
    sessions=[]
    all_trades=[]
    all_snaps=[]
    rejected=skipped=0
    for day,bars,offset in group_days(ltf):
        engine=SMCReplay(config,verified)
        report=walk_forward_backtest(bars,engine,backtest_config)
        trades=tuple(replace(t,signal_index=t.signal_index+offset,
                             entry_index=t.entry_index+offset,
                             exit_index=t.exit_index+offset) for t in report.trades)
        outcome_counts,setups=final_sweep_audit(bars,config.symbol)
        sessions.append(SessionResult(day,len(bars),tuple(engine.snapshots),
                       trades,report.signals_rejected,report.signals_skipped,
                       outcome_counts,setups))
        all_trades.extend(trades)
        all_snaps.extend(engine.snapshots)
        rejected+=report.signals_rejected
        skipped+=report.signals_skipped
    gains=sum(t.net_index_points for t in all_trades if t.net_index_points>0)
    losses=-sum(t.net_index_points for t in all_trades if t.net_index_points<0)
    equity=peak=drawdown=0.0
    for t in all_trades:
        equity+=t.net_index_points
        peak=max(peak,equity)
        drawdown=max(drawdown,peak-equity)
    return MultiDayResult(tuple(sessions),tuple(all_trades),tuple(all_snaps),
        rejected,skipped,sum(t.net_index_points for t in all_trades),
        sum(t.net_index_points>0 for t in all_trades)/len(all_trades) if all_trades else None,
        gains/losses if losses else None,drawdown)
