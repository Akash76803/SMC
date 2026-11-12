"""Retrospective diagnostics for missing sweep -> internal CHoCH matches.

Uses only closed candles, but the entire supplied sample is scanned once.
This is an explanatory audit, NOT a trading signal or a causal backtest output.
"""
from __future__ import annotations
from collections import Counter
from typing import Sequence
from .models import Candle
from .phase2 import scan

def audit_choch_link(candles: Sequence[Candle], *, internal_k:int=2,
                     external_k:int=5, max_choch_bars:int=8)->dict:
    if max_choch_bars<1:raise ValueError("max_choch_bars must be positive")
    result=scan(list(candles),internal_k=internal_k,external_k=external_k)
    sweeps=[s for s in result.liquidity_events
            if s.kind=="SWEEP" and s.level.kind in
            ("BSL","SSL","EQH","EQL","PDH","PDL")]
    internal=[e for e in result.structure_events if e.tier=="INTERNAL"]
    chochs=[e for e in internal if e.kind=="CHoCH"]
    matched=0
    same_direction_late=0
    any_direction_in_window=0
    nearest_lags=[]
    for s in sweeps:
        wanted=("BEARISH" if s.level.kind in ("BSL","EQH","PDH")
                else "BULLISH")
        subsequent=[e for e in chochs
                    if e.candle_index>s.candle_index
                    and e.direction==wanted]
        in_window=[e for e in subsequent
                   if e.candle_index<=s.candle_index+max_choch_bars]
        if in_window:
            matched+=1
            nearest_lags.append(min(e.candle_index-s.candle_index for e in in_window))
        elif subsequent:
            same_direction_late+=1
        if any(s.candle_index<e.candle_index<=s.candle_index+max_choch_bars
               for e in chochs):
            any_direction_in_window+=1
    return {
        "unique_sweep_events":len(sweeps),
        "internal_structure_events":len(internal),
        "internal_bos_events":sum(e.kind=="BOS" for e in internal),
        "internal_choch_events":len(chochs),
        "internal_choch_by_direction":dict(sorted(Counter(e.direction for e in chochs).items())),
        "sweeps_with_matching_choch_within_window":matched,
        "sweeps_with_matching_choch_only_after_window":same_direction_late,
        "sweeps_with_any_choch_within_window":any_direction_in_window,
        "min_matching_lag_bars":min(nearest_lags) if nearest_lags else None,
        "max_choch_bars":max_choch_bars,
        "note":"Retrospective event-link audit of closed sample; not independent opportunities or trade confirmations."
    }
