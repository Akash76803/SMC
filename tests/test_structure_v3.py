from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from smc.models import Candle
from smc.structure_v3 import (three_candle_points, structure_hierarchy,
                              detect_hierarchical_structure, detect_idm_touches)


START = datetime(2026, 11, 12, 9, 16, tzinfo=ZoneInfo("Asia/Kolkata"))


def bars(highs, lows=None, closes=None):
    if lows is None:
        lows = [h-10 for h in highs]
    if closes is None:
        closes = [(h+l)/2 for h, l in zip(highs, lows)]
    return [Candle(START+timedelta(minutes=i), c, h, l, c)
            for i, (h, l, c) in enumerate(zip(highs, lows, closes))]


def test_three_candle_pivot_confirmed_only_on_next_closed_bar():
    c = bars([100, 110, 101, 103])
    assert three_candle_points(c[:2]) == ()
    points = three_candle_points(c[:3])
    assert len([p for p in points if p.kind == "STH"]) == 1
    assert [p.confirmed_at for p in points if p.kind == "STH"] == [2]


def test_incomplete_right_candle_never_confirms_pivot():
    c = bars([100, 110, 101])
    last = c[-1]
    c[-1] = Candle(last.timestamp, last.open, last.high, last.low, last.close,
                   complete=False)
    assert three_candle_points(c) == ()


def test_intermediate_high_confirmed_after_right_sth():
    c = bars([100, 115, 104, 120, 105, 130, 110, 125, 111, 116, 100])
    p = [x for x in structure_hierarchy(c) if x.kind == "ITH"]
    assert len(p) == 1
    assert p[0].pivot.index == 5
    assert p[0].left_pivot_index == 3
    assert p[0].right_pivot_index == 7
    assert p[0].confirmed_at == 8


def test_intermediate_low_confirmed_after_right_stl():
    c = bars([130, 110, 130, 105, 130, 90, 130, 100, 130, 110, 130],
             [120, 100, 120, 95, 120, 80, 120, 90, 120, 100, 120])
    pts = [p for p in structure_hierarchy(c) if p.kind == "ITL"]
    assert len(pts) == 1
    assert pts[0].pivot.index == 5 and pts[0].confirmed_at == 8


def test_wick_sweep_requires_close_beyond_wick_for_bos():
    c = bars([100, 110, 100, 120, 121, 123],
             [90, 100, 90, 105, 110, 111],
             [95, 105, 95, 108, 119, 122])
    e = [x for x in detect_hierarchical_structure(c) if x.tier == "SHORT"
         and x.origin_index == 1 and x.direction == "BULLISH"]
    assert [(x.kind, x.confirmed_at) for x in e] == [
        ("SWEEP", 3), ("SWEEP", 4), ("BOS", 5)]
    assert e[-1].level == 121


def test_no_events_before_origin_confirmation():
    c = bars([100, 110, 100, 111, 100])
    for e in detect_hierarchical_structure(c):
        assert e.confirmed_at > e.origin_index + 1


def test_equal_highs_do_not_form_sth():
    c = bars([100, 110, 110, 100])
    assert not [p for p in three_candle_points(c) if p.kind == "STH"]


def test_idm_touch_needs_mature_left_pivot():
    c = bars([110, 100, 115, 108, 130, 105, 120],
             [100, 90, 105, 98, 120, 95, 110])
    idms = detect_idm_touches(c)
    assert all(x.swept_at >= x.eligible_from for x in idms)
    assert all(x.swept_at > x.extreme_index + 1 for x in idms)


def test_no_lookahead_on_prefix():
    c = bars([100,115,104,120,105,130,110,125,111,116,100])
    for n in range(3, len(c)+1):
        pts = structure_hierarchy(c[:n])
        assert all(p.confirmed_at < n for p in pts)
        events = detect_hierarchical_structure(c[:n])
        assert all(e.confirmed_at < n for e in events)
        assert all(e.confirmed_at > e.origin_index for e in events)


def test_invalid_inputs():
    with pytest.raises(ValueError):
        detect_hierarchical_structure(bars([100, 110, 100]), buffer=-1)
    c = bars([100, 110, 100])
    with pytest.raises(ValueError):
        structure_hierarchy([c[1], c[0], c[2]])
