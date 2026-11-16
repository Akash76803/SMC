"""Causal, research-only BOS -> pullback -> reclaim continuation checks."""
from datetime import datetime, timedelta, timezone

import pytest

from smc.continuation_v3 import detect_continuation_observations
from smc.models import Candle, Pivot
from smc.structure_v2 import StructuralBreak


T = datetime(2026, 11, 2, 9, 16, tzinfo=timezone(timedelta(hours=5, minutes=30)))


def candles(values):
    return [Candle(T + timedelta(minutes=i), o, h, l, c)
            for i, (o, h, l, c) in enumerate(values)]


def fixture():
    return candles([
        (100, 101, 99, 100), (100, 102, 99, 101),
        (101, 104, 100, 103), (103, 106, 102, 105),
        (105, 106, 101, 102), (102, 107, 101, 106.5),
        (106.5, 108, 105, 107),
    ])


def bos(direction="BULLISH"):
    return StructuralBreak("BOS", direction, "INTERNAL",
                           Pivot("HIGH" if direction == "BULLISH" else "LOW",
                                 1, 102 if direction == "BULLISH" else 99, 2),
                           3, None)


def test_bullish_bos_pullback_reclaim_is_wait_not_buy(monkeypatch):
    monkeypatch.setattr("smc.continuation_v3.detect_structure", lambda c: [bos()])
    c = fixture()
    output = detect_continuation_observations(c)
    assert len(output) == 1
    item = output[0]
    assert (item.bos_index, item.pullback_index, item.confirm_index) == (3, 4, 5)
    data = item.as_dict(c)
    assert data["status"] == "WAIT"
    assert data["index_bracket"] is None
    assert data["research_only"] is True
    assert data["source"] == "CONTINUATION_RESEARCH"
    assert "VERIFIED_HTF_BIAS" in data["diagnostics"]["pending_stages"]


def test_not_reported_before_confirmation_close(monkeypatch):
    monkeypatch.setattr("smc.continuation_v3.detect_structure", lambda c: [bos()])
    c = fixture()
    assert detect_continuation_observations(c[:5]) == ()
    assert len(detect_continuation_observations(c[:6])) == 1


def test_wrong_direction_reclaim_is_not_candidate(monkeypatch):
    monkeypatch.setattr("smc.continuation_v3.detect_structure", lambda c: [bos()])
    c = fixture()[:5] + [Candle(T + timedelta(minutes=5), 102, 105, 99, 100)]
    assert detect_continuation_observations(c) == ()


def test_no_bos_means_no_continuation(monkeypatch):
    monkeypatch.setattr("smc.continuation_v3.detect_structure", lambda c: [])
    assert detect_continuation_observations(fixture()) == ()


def test_reversal_choch_cancels_continuation(monkeypatch):
    reversal = StructuralBreak("CHoCH", "BEARISH", "INTERNAL",
                               Pivot("LOW", 2, 100, 3), 5, None)
    monkeypatch.setattr("smc.continuation_v3.detect_structure",
                        lambda c: [bos(), reversal])
    assert detect_continuation_observations(fixture()) == ()


def test_fails_closed_on_incomplete_or_multiday():
    c = fixture()
    c[1] = Candle(c[1].timestamp, c[1].open, c[1].high, c[1].low,
                  c[1].close, complete=False)
    with pytest.raises(ValueError, match="INCOMPLETE"):
        detect_continuation_observations(c)
    d = fixture()
    d[-1] = Candle(T + timedelta(days=1), 106, 108, 105, 107)
    with pytest.raises(ValueError, match="SINGLE_SESSION"):
        detect_continuation_observations(d)


def test_invalid_timeout_parameters():
    with pytest.raises(ValueError, match="INVALID_CONTINUATION_WINDOWS"):
        detect_continuation_observations(fixture(), max_pullback_bars=0)
