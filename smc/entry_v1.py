"""Phase 3 experimental liquidity-sweep -> CHoCH -> FVG retest state machine.

Not the complete book's ES-01 (IDM/OB semantics remain to be verified).
Only produces research candidates; it cannot authorize real option trades.
Every transition is on a completed bar and strictly ordered in time.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Iterable

from .engine import fair_value_gaps
from .liquidity import LiquidityEvent
from .models import Candle, Zone
from .risk import validate_index_setup
from .models import IndexSetup, Side
from .structure_v2 import StructuralBreak


class State(str, Enum):
    WAITING_CHOCH = "WAITING_CHOCH"
    WAITING_FVG = "WAITING_FVG"
    WAITING_RETEST = "WAITING_RETEST"
    CANDIDATE = "CANDIDATE"
    INVALIDATED = "INVALIDATED"
    EXPIRED = "EXPIRED"
    REJECTED = "REJECTED"


@dataclass(frozen=True)
class EntryResult:
    state: State
    side: Side
    sweep_index: int
    transition_index: int
    reason: str
    choch_index: int | None = None
    fvg_index: int | None = None
    entry: float | None = None
    stop: float | None = None
    target: float | None = None
    index_rr: float | None = None


def evaluate_entry(
    candles: list[Candle],
    liquidity_events: Iterable[LiquidityEvent],
    structure_events: Iterable[StructuralBreak],
    *,
    symbol: str,
    target: float | None = None,
    max_choch_bars: int = 8,
    max_fvg_bars: int = 6,
    max_retest_bars: int = 12,
    sl_buffer: float = 0.0,
    fvgs: Iterable[Zone] | None = None,
) -> list[EntryResult]:
    """Scan all BSL/SSL sweep events, emitting their latest state at last closed bar.

    Trade candidate must have sweep -> directionally aligned INTERNAL CHoCH ->
    same-direction FVG created at/after CHoCH -> subsequent zone retest.
    Retest entry price is *closing price* of confirming candle (no assumed
    fill at a past zone price). Stop uses sweep extreme. Target is supplied
    independently by a validated opposing-liquidity target provider.
    """
    if min(max_choch_bars, max_fvg_bars, max_retest_bars) < 1 or sl_buffer < 0:
        raise ValueError("invalid phase 3 parameters")
    if any(candles[i].timestamp >= candles[i+1].timestamp for i in range(len(candles)-1)):
        raise ValueError("candles must be ordered")
    gaps = list(fvgs) if fvgs is not None else fair_value_gaps(candles)
    events = sorted(structure_events, key=lambda e: e.candle_index)
    closed_indices = [i for i, c in enumerate(candles) if c.complete]
    last = closed_indices[-1] if closed_indices else -1
    results: list[EntryResult] = []

    for sweep in liquidity_events:
        if sweep.kind != "SWEEP" or sweep.level.kind not in ("BSL", "SSL", "EQH", "EQL", "PDH", "PDL"):
            continue
        si = sweep.candle_index
        if si < 0 or si > last or not candles[si].complete:
            continue
        # Upper liquidity sweep suggests bearish reversal; lower suggests bullish.
        bearish = sweep.level.kind in ("BSL", "EQH", "PDH")
        direction = "BEARISH" if bearish else "BULLISH"
        side = Side.PE if bearish else Side.CE
        extreme = candles[si].high if bearish else candles[si].low
        stop = extreme + sl_buffer if bearish else extreme - sl_buffer

        def emit(state: State, idx: int, reason: str, *,
                 choch: int | None = None, gap: int | None = None,
                 entry: float | None = None, rr: float | None = None):
            results.append(EntryResult(state, side, si, idx, reason, choch,
                                       gap, entry, stop, target, rr))

        # First matching internal CHoCH after sweep, within expiry window.
        choch = next((e for e in events
                      if e.tier == "INTERNAL" and e.kind == "CHoCH"
                      and e.direction == direction
                      and si < e.candle_index <= min(last, si + max_choch_bars)
                      and candles[e.candle_index].complete), None)
        if choch is None:
            if last >= si + max_choch_bars:
                emit(State.EXPIRED, si + max_choch_bars, "CHOCH_TIMEOUT")
            else:
                emit(State.WAITING_CHOCH, last, "WAIT_FOR_CONFIRMED_CHOCH")
            continue

        ci = choch.candle_index
        wanted = "BEARISH_FVG" if bearish else "BULLISH_FVG"
        gap = next((z for z in sorted(gaps, key=lambda z: z.created_at)
                    if z.kind == wanted and ci <= z.created_at <= min(last, ci + max_fvg_bars)
                    and 0 <= z.created_at < len(candles)
                    and candles[z.created_at].complete and z.lower < z.upper), None)
        if gap is None:
            if last >= ci + max_fvg_bars:
                emit(State.EXPIRED, ci + max_fvg_bars, "FVG_TIMEOUT", choch=ci)
            else:
                emit(State.WAITING_FVG, last, "WAIT_FOR_DIRECTIONAL_FVG", choch=ci)
            continue

        gi = gap.created_at
        finished = False
        for i in range(gi + 1, min(last, gi + max_retest_bars) + 1):
            c = candles[i]
            if not c.complete:
                continue
            # Invalidation is checked BEFORE retest, including on the retest candle.
            if (bearish and c.high >= stop) or (not bearish and c.low <= stop):
                emit(State.INVALIDATED, i, "SWEEP_EXTREME_BREACHED", choch=ci, gap=gi)
                finished = True
                break
            touched = c.low <= gap.upper and c.high >= gap.lower
            rejection = c.close < gap.lower if bearish else c.close > gap.upper
            if not (touched and rejection):
                continue
            entry = c.close
            # The FVG candle is a completed retest, NOT a suggested fill.
            if target is None:
                emit(State.REJECTED, i, "MISSING_VERIFIED_LIQUIDITY_TARGET",
                     choch=ci, gap=gi, entry=entry)
            else:
                setup = IndexSetup(symbol, side, entry, stop, target,
                                   confirmed=True, scheme="RESEARCH_LIQUIDITY_V1")
                check = validate_index_setup(setup)
                if check.accepted:
                    emit(State.CANDIDATE, i, "RESEARCH_ONLY_OPTIONS_NOT_VALIDATED",
                         choch=ci, gap=gi, entry=entry, rr=check.index_rr)
                else:
                    emit(State.REJECTED, i, ",".join(check.reasons),
                         choch=ci, gap=gi, entry=entry, rr=check.index_rr)
            finished = True
            break
        if not finished:
            if last >= gi + max_retest_bars:
                emit(State.EXPIRED, gi + max_retest_bars, "RETEST_TIMEOUT",
                     choch=ci, gap=gi)
            else:
                emit(State.WAITING_RETEST, last, "WAIT_FOR_RETEST_REJECTION",
                     choch=ci, gap=gi)
    return results
