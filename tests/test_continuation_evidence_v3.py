"""V3.9C evidence checks: protection, POI and target ladder stay provisional."""
from datetime import datetime, timedelta, timezone

import pytest

from smc.continuation_evidence_v3 import enrich_continuation
from smc.continuation_v3 import ContinuationObservation
from smc.models import Candle

T = datetime(2026, 11, 2, 9, 16,
             tzinfo=timezone(timedelta(hours=5, minutes=30)))


def candles():
    prices = [
        (100, 104, 98, 102),
        (102, 106, 101, 105),
        (105, 107, 102, 104),
        (104, 105, 99, 100),
        (100, 107, 100, 106),
        (106, 108, 102, 103),
        (103, 110, 103, 109),
        (109, 111, 107, 110),
    ]
    return [Candle(T + timedelta(minutes=i), *values)
            for i, values in enumerate(prices)]


def obs():
    return ContinuationObservation("BULLISH", 4, 5, 6, 106, 108, 109)


def test_enrichment_is_non_executable_and_json_serializable():
    import json
    result = enrich_continuation(symbol="NIFTY", candles=candles(),
                                 observation=obs())
    assert result["status"] == "RESEARCH_ONLY"
    assert result["no_trade_authorization"] is True
    assert result["protected_structure"]["is_verified_protected_structure"] is False
    assert result["poi"]["is_verified_htf_poi"] is False
    assert result["index_targets"]["research_only"] is True
    assert json.loads(json.dumps(result)) == result


def test_protected_proxy_is_prior_to_bos():
    result = enrich_continuation(symbol="NIFTY", candles=candles(),
                                 observation=obs())
    protected = result["protected_structure"]
    if protected["confirmed_at"] is not None:
        assert protected["confirmed_at"] < candles()[obs().bos_index].timestamp.isoformat()
    assert protected["status"] in ("PROVISIONAL", "UNAVAILABLE")


def test_future_candles_do_not_change_prior_event_research():
    c = candles()
    before = enrich_continuation(symbol="NIFTY", candles=c[:7],
                                 observation=obs())
    after = enrich_continuation(symbol="NIFTY", candles=c,
                                observation=obs())
    assert before == after


def test_no_cross_session_evidence():
    c = candles()
    c[-1] = Candle(T + timedelta(days=1), 109, 111, 107, 110)
    with pytest.raises(ValueError, match="CROSS_SESSION"):
        enrich_continuation(symbol="NIFTY", candles=c, observation=obs())


def test_incomplete_candles_rejected():
    c = candles()
    x = c[3]
    c[3] = Candle(x.timestamp, x.open, x.high, x.low, x.close,
                  complete=False)
    with pytest.raises(ValueError, match="INCOMPLETE"):
        enrich_continuation(symbol="NIFTY", candles=c, observation=obs())


def test_invalid_event_index_rejected():
    bad = ContinuationObservation("BEARISH", 5, 4, 6, 100, 98, 97)
    with pytest.raises(ValueError, match="INVALID_RESEARCH_EVENT_INDICES"):
        enrich_continuation(symbol="NIFTY", candles=candles(), observation=bad)


def test_unknown_symbol_rejected():
    with pytest.raises(ValueError, match="INVALID_RESEARCH_SYMBOL"):
        enrich_continuation(symbol="ABC", candles=candles(), observation=obs())
