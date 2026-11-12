"""Phase 3.5 causal historical SMC research signal adapter.

Rebuilds structures and liquidity from only the supplied LTF candle prefix.
HTF data uses candle START timestamps; HTF bar is available only after its
full duration ends at or before the current LTF candle CLOSE timestamp.

No options, Delta, IV or execution claims are made. This is an index-level
research signal callback for smc.backtest.walk_forward_backtest.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import Sequence

from .advanced import find_idm, find_order_blocks, qualify_atr, select_liquidity_target
from .backtest import Signal
from .engine import confirmed_pivots, fair_value_gaps
from .entry_v1 import State, evaluate_entry
from .models import Candle, IndexSetup, Side
from .phase2 import scan
from .risk import validate_index_setup
from .structure_v2 import detect_structure


@dataclass(frozen=True)
class ReplayConfig:
    symbol: str
    htf_duration_minutes: int = 60
    internal_k: int = 2
    external_k: int = 5
    equal_tolerance: float = 2.0
    max_target_atr: float = 4.0

    def __post_init__(self):
        if self.symbol not in ("SENSEX", "NIFTY"):
            raise ValueError("unsupported symbol")
        if self.htf_duration_minutes < 1 or not (1 <= self.internal_k < self.external_k):
            raise ValueError("invalid timeframe or pivot widths")
        if self.equal_tolerance < 0 or self.max_target_atr <= 0:
            raise ValueError("invalid tolerance or ATR bound")


@dataclass(frozen=True)
class ReplaySnapshot:
    signal: Signal | None
    state: str
    reason: str
    ltf_bars: int
    htf_bars_available: int
    entry_state_counts: tuple[tuple[str,int], ...] = ()
    entry_reason_counts: tuple[tuple[str,int], ...] = ()


class SMCReplay:
    def __init__(self, config: ReplayConfig, htf_candles: Sequence[Candle]):
        self.config = config
        self.htf_candles = tuple(htf_candles)
        if any(not c.complete for c in self.htf_candles):
            raise ValueError("HTF history must consist of completed bars")
        if any(self.htf_candles[i].timestamp >= self.htf_candles[i+1].timestamp
               for i in range(len(self.htf_candles)-1)):
            raise ValueError("HTF candles must be sorted")
        self.snapshots: list[ReplaySnapshot] = []

    def snapshot(self, prefix: Sequence[Candle]) -> ReplaySnapshot:
        if not prefix or any(not c.complete for c in prefix):
            return ReplaySnapshot(None, "NO_TRADE", "NO_COMPLETE_LTF_HISTORY", len(prefix), 0)
        if any(prefix[i].timestamp >= prefix[i+1].timestamp
               for i in range(len(prefix)-1)):
            raise ValueError("LTF candles must be sorted")
        candles = list(prefix)
        now = candles[-1].timestamp  # CLOSE time, never a future candle
        duration = timedelta(minutes=self.config.htf_duration_minutes)
        # For HTF timestamps, complete means historically fully formed; filter
        # by close time so even a preloaded full dataset cannot leak.
        htf = [c for c in self.htf_candles if c.timestamp + duration <= now]
        if len(htf) < 2*self.config.external_k+2:
            return ReplaySnapshot(None, "WAIT", "HTF_WARMUP", len(candles), len(htf))
        if len(candles) < 16:
            return ReplaySnapshot(None, "WAIT", "LTF_ATR_WARMUP", len(candles),len(htf))

        ltf_scan=scan(candles,internal_k=self.config.internal_k,
                      external_k=self.config.external_k,
                      equal_tolerance=self.config.equal_tolerance)
        htf_breaks=detect_structure(htf,internal_k=self.config.internal_k,
                                    external_k=self.config.external_k)
        htf_external=[e for e in htf_breaks if e.tier=="EXTERNAL"]
        if not htf_external:
            return ReplaySnapshot(None,"WAIT","HTF_BIAS_NOT_ESTABLISHED",len(candles),len(htf))
        bias=htf_external[-1].direction
        ltf_breaks=list(ltf_scan.structure_events)
        pivots=confirmed_pivots(candles,self.config.internal_k)
        obs=find_order_blocks(candles,ltf_breaks)
        idms=find_idm(pivots,ltf_breaks)
        detected=evaluate_entry(candles,list(ltf_scan.liquidity_events),
                                ltf_breaks,symbol=self.config.symbol,
                                target=None,fvgs=fair_value_gaps(candles))
        if not detected:
            return ReplaySnapshot(None,"WAIT","NO_SWEEP_SETUP",len(candles),len(htf))
        latest=len(candles)-1
        # Only entry confirmation at this exact bar; no stale signal replay.
        current=[e for e in detected if e.transition_index==latest and
                 e.entry is not None and e.choch_index is not None]
        if not current:
            # Sweeps in the list can include previously expired events.
            # Counts summarize per-prefix observations, not distinct trades.
            from collections import Counter
            states=Counter(x.state.value for x in detected)
            reasons=Counter(x.reason for x in detected)
            return ReplaySnapshot(None,"WAIT","NO_CURRENT_RETEST",len(candles),len(htf),
                                  tuple(sorted(states.items())),
                                  tuple(sorted(reasons.items())))
        candidate=max(current,key=lambda x:x.sweep_index)
        direction="BULLISH" if candidate.side==Side.CE else "BEARISH"
        if direction!=bias:
            return ReplaySnapshot(None,"NO_TRADE","HTF_BIAS_MISMATCH",len(candles),len(htf))
        # Only research proxies; never claim actual stop pools are known.
        if not any(o.direction==direction and o.source_index<candidate.choch_index
                   and o.confirmed_at<=latest and o.structure_index>=candidate.choch_index
                   for o in obs):
            return ReplaySnapshot(None,"NO_TRADE","OB_PROXY_MISSING",len(candles),len(htf))
        if not any(d.direction==direction and d.source_index<candidate.choch_index
                   and d.confirmed_at<=latest for d in idms):
            return ReplaySnapshot(None,"NO_TRADE","IDM_PROXY_MISSING",len(candles),len(htf))
        consumed={(event.level.kind,event.level.price)
                  for event in ltf_scan.liquidity_events if event.candle_index<=latest}
        target=select_liquidity_target(candidate.entry,direction,
                                       list(ltf_scan.levels),latest,
                                       invalidated=consumed)
        if target is None:
            return ReplaySnapshot(None,"NO_TRADE","NO_VALID_LIQUIDITY_TARGET",len(candles),len(htf))
        volatility=qualify_atr(ltf_scan.atr14,abs(target-candidate.entry),
                               max_target_atr=self.config.max_target_atr)
        if not volatility.accepted:
            return ReplaySnapshot(None,"NO_TRADE",volatility.reason,len(candles),len(htf))
        setup=IndexSetup(self.config.symbol,candidate.side,candidate.entry,
                         candidate.stop,target,True,"REPLAY_RESEARCH_V1")
        validation=validate_index_setup(setup)
        if not validation.accepted:
            return ReplaySnapshot(None,"NO_TRADE",",".join(validation.reasons),
                                  len(candles),len(htf))
        # Option Greeks unavailable: signal is INDEX research only.
        return ReplaySnapshot(Signal(setup,latest),"INDEX_RESEARCH_CANDIDATE",
                              "OPTION_DATA_NOT_VALIDATED",len(candles),len(htf))

    def __call__(self, prefix: tuple[Candle,...]) -> Signal | None:
        result=self.snapshot(prefix)
        self.snapshots.append(result)
        return result.signal
