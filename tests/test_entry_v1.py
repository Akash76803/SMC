from datetime import datetime, timedelta, timezone

import pytest

from smc.entry_v1 import State, evaluate_entry
from smc.liquidity import LiquidityEvent, LiquidityLevel
from smc.models import Candle, Pivot, Zone
from smc.structure_v2 import StructuralBreak

T = datetime(2026, 11, 12, tzinfo=timezone.utc)


def bars(highs, lows, closes, *, incomplete_last=False):
    out = [Candle(T + timedelta(minutes=i), cl, hi, lo, cl)
           for i, (hi, lo, cl) in enumerate(zip(highs, lows, closes))]
    if incomplete_last:
        x = out[-1]
        out[-1] = Candle(x.timestamp, x.open, x.high, x.low, x.close,
                         complete=False)
    return out


def fixture():
    # Sweep high at index 1; bearish CHoCH at 2; FVG at 3; retest at 5.
    c = bars([110, 114, 106, 104, 102, 105],
             [102, 101, 98, 94, 91, 97],
             [105, 105, 99, 96, 93, 96])
    level = LiquidityLevel("BSL", 111, 0, (0,), 1)
    sweep = LiquidityEvent("SWEEP", level, 1, "BULLISH", 3)
    choch = StructuralBreak("CHoCH", "BEARISH", "INTERNAL",
                            Pivot("LOW", 0, 100, 0), 2, None)
    fvg = Zone("BEARISH_FVG", 100, 103, 3)
    # last candle high=105 intersects gap, close=96 below gap
    return c, sweep, choch, fvg


def test_wait_choch_without_confirmation():
    c,s,_,g=fixture()
    result=evaluate_entry(c[:2],[s],[],symbol="SENSEX",target=0,fvgs=[g])
    assert result[0].state == State.WAITING_CHOCH


def test_wait_fvg_after_choch():
    c,s,co,_=fixture()
    result=evaluate_entry(c[:3],[s],[co],symbol="SENSEX")
    assert result[0].state == State.WAITING_FVG


def test_wait_retest_after_fvg():
    c,s,co,g=fixture()
    result=evaluate_entry(c[:4],[s],[co],symbol="SENSEX",fvgs=[g])
    assert result[0].state == State.WAITING_RETEST


def test_reject_when_target_not_provided():
    c,s,co,g=fixture()
    result=evaluate_entry(c,[s],[co],symbol="SENSEX",fvgs=[g])
    assert result[0].state == State.REJECTED
    assert "MISSING_VERIFIED" in result[0].reason


def test_candidate_only_after_valid_target():
    c,s,co,g=fixture()
    # entry 96, stop 114, target 50 => reward 46, invalid for SENSEX.
    result=evaluate_entry(c,[s],[co],symbol="SENSEX",target=50,fvgs=[g])
    assert result[0].state == State.REJECTED
    # 120+ point reward and >2 RR
    result=evaluate_entry(c,[s],[co],symbol="SENSEX",target=-20,fvgs=[g])
    assert result[0].state == State.REJECTED  # non-positive target
    # Use plausible SENSEX levels by translating entire fixture upwards.
    shifted=bars([x.high+85000 for x in c],
                 [x.low+85000 for x in c],
                 [x.close+85000 for x in c])
    result=evaluate_entry(shifted,[s],[co],symbol="SENSEX",
                          target=84980,fvgs=[g])
    assert result[0].state == State.REJECTED  # levels not aligned, no artificial pass
    from dataclasses import replace
    shifted_s=replace(s,level=replace(s.level,price=85111))
    shifted_g=replace(g,lower=85100,upper=85103)
    passed=evaluate_entry(shifted,[shifted_s],[co],symbol="SENSEX",
                          target=84980,fvgs=[shifted_g])
    assert passed[0].state == State.CANDIDATE
    assert passed[0].index_rr >= 2


def test_sweep_extreme_break_invalidates():
    c,s,co,g=fixture()
    # Stop=114; future bar 115 invalidates before any entry.
    broken = c[:5]+bars([115],[97],[96])[-1:]
    x=broken[-1]
    broken[-1]=Candle(c[5].timestamp,x.open,x.high,x.low,x.close)
    result=evaluate_entry(broken,[s],[co],symbol="SENSEX",
                          target=84800,fvgs=[g])
    assert result[0].state == State.INVALIDATED


def test_no_retest_on_incomplete_bar():
    c,s,co,g=fixture()
    x=c[-1]
    c[-1]=Candle(x.timestamp,x.open,x.high,x.low,x.close,complete=False)
    result=evaluate_entry(c,[s],[co],symbol="SENSEX",fvgs=[g])
    assert result[0].state == State.WAITING_RETEST


def test_out_of_order_events_cannot_confirm():
    c,s,co,g=fixture()
    early=StructuralBreak("CHoCH","BEARISH","INTERNAL",co.broken_pivot,1,None)
    result=evaluate_entry(c,[s],[early],symbol="SENSEX",fvgs=[g])
    assert result[0].state == State.WAITING_CHOCH


def test_timeout_and_invalid_config():
    c,s,co,g=fixture()
    assert evaluate_entry(c,[s],[],symbol="SENSEX",
                          max_choch_bars=2,fvgs=[g])[0].state == State.EXPIRED
    with pytest.raises(ValueError):
        evaluate_entry(c,[s],[co],symbol="SENSEX",max_fvg_bars=0,fvgs=[g])
