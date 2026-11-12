from datetime import datetime, timedelta, timezone
import pytest
from smc.models import Candle
from smc.engine import confirmed_pivots, analyze, fair_value_gaps, atr


def candles(closes):
    t = datetime(2026, 1, 1, tzinfo=timezone.utc)
    return [Candle(t+timedelta(minutes=i), x, x+1, x-1, x)
            for i,x in enumerate(closes)]


def test_pivot_confirmed_only_after_right_bars():
    series = candles([10, 11, 15, 11, 10, 12])
    p = confirmed_pivots(series, k=2)
    assert [(x.kind, x.index, x.confirmed_at) for x in p] == [("HIGH", 2, 4)]
    assert not confirmed_pivots(series[:4], k=2)


def test_atr_requires_enough_complete_candles():
    assert atr(candles([10]*14)) is None
    assert atr(candles([10]*15)) == pytest.approx(2)


def test_reject_out_of_order_candles():
    series = candles([10, 11])
    with pytest.raises(ValueError):
        analyze(series[::-1])


def test_fvg_has_three_candle_condition():
    t = datetime(2026,1,1,tzinfo=timezone.utc)
    cs = [
        Candle(t, 100, 102, 99, 101),
        Candle(t+timedelta(minutes=1), 103, 111, 102, 110),
        Candle(t+timedelta(minutes=2), 114, 116, 113, 115)
    ]
    assert any(z.kind == "BULLISH_FVG" and z.lower == 102 and z.upper == 113
               for z in fair_value_gaps(cs))
