"""Per-archetype independent session-safe research backtests.

Reports are NOT a simultaneous three-strategy portfolio. Decisions after
a position is opened may not be evaluated by the one-position backtester.
MFE/MAE are full-bar OHLC ENVELOPES, not proven pre-exit intrabar excursions.
"""
from __future__ import annotations
from collections import Counter
from dataclasses import dataclass,replace
from typing import Sequence

from .backtest import BacktestConfig,BacktestTrade,walk_forward_backtest
from .historical_replay import ReplayConfig
from .models import Candle,Side
from .multiday_replay import group_days
from .phase5_setups import STRATEGIES,StrategyReplay,summarize_decisions

@dataclass(frozen=True)
class ArchetypeResult:
    strategy:str
    sessions:int
    signals_emitted:int
    trades:tuple[BacktestTrade,...]
    signals_rejected:int
    signals_skipped:int
    diagnostics:dict[str,int]
    risk_rejections:tuple[dict,...]
    net_index_points:float
    win_rate:float|None
    profit_factor:float|None
    max_drawdown_points:float
    bar_envelope_mfe:tuple[float,...]
    bar_envelope_mae:tuple[float,...]

def replay_archetype(ltf:Sequence[Candle],htf:Sequence[Candle],
                     config:ReplayConfig,strategy:str,
                     backtest_config:BacktestConfig=BacktestConfig())->ArchetypeResult:
    if strategy not in STRATEGIES:
        raise ValueError("UNKNOWN_STRATEGY")
    trades=[]
    diagnostics=Counter()
    rejects=[]
    emitted=rejected=skipped=0
    mfe=[]
    mae=[]
    groups=group_days(ltf)
    for day,bars,offset in groups:
        adapter=StrategyReplay(config,htf,strategy)
        result=walk_forward_backtest(bars,adapter,backtest_config)
        emitted+=sum(d.signal is not None for d in adapter.decisions)
        diagnostics.update(summarize_decisions(adapter.decisions))
        rejected+=result.signals_rejected
        skipped+=result.signals_skipped
        for d in adapter.decisions:
            if d.entry is not None and d.signal is None:
                rejects.append({"date":day,"strategy":strategy,"reason":d.reason,
                                "entry":d.entry,"stop":d.stop,"target":d.target,
                                "index_rr":d.rr,
                                "trigger_local_index":d.trigger_index})
        for trade in result.trades:
            direction=1 if trade.side==Side.CE else -1
            involved=bars[trade.entry_index:trade.exit_index+1]
            if direction==1:
                favorable=max(c.high for c in involved)-trade.entry_price
                adverse=trade.entry_price-min(c.low for c in involved)
            else:
                favorable=trade.entry_price-min(c.low for c in involved)
                adverse=max(c.high for c in involved)-trade.entry_price
            mfe.append(max(0.0,favorable))
            mae.append(max(0.0,adverse))
            trades.append(replace(trade,signal_index=trade.signal_index+offset,
                                  entry_index=trade.entry_index+offset,
                                  exit_index=trade.exit_index+offset))
    net=sum(t.net_index_points for t in trades)
    gains=sum(t.net_index_points for t in trades if t.net_index_points>0)
    losses=-sum(t.net_index_points for t in trades if t.net_index_points<0)
    equity=peak=drawdown=0.0
    for t in trades:
        equity+=t.net_index_points
        peak=max(peak,equity)
        drawdown=max(drawdown,peak-equity)
    return ArchetypeResult(strategy,len(groups),emitted,tuple(trades),
                           rejected,skipped,dict(sorted(diagnostics.items())),
                           tuple(rejects),net,
                           sum(t.net_index_points>0 for t in trades)/len(trades)
                           if trades else None,
                           gains/losses if losses else None,drawdown,
                           tuple(mfe),tuple(mae))
