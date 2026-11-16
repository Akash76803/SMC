"""Offline tests for Angel live market-data smoke test (no real credentials)."""
from datetime import datetime, timezone
import pytest
from smc.angel_live_smoke_cli import (
    LiveQuoteError, fetch_live_quote, validate_live_quote,
)

NOW = datetime(2026, 11, 16, 9, 0, tzinfo=timezone.utc)


class FakeClient:
    def __init__(self, response=None, error=None):
        self.response, self.error, self.calls = response, error, []
    def getMarketData(self, mode, tokens):
        self.calls.append((mode, tokens))
        if self.error:
            raise self.error
        return self.response


def response(ltp=25600.5, *, token="99926000", exchange="NSE", status=True):
    return {
        "status": status,
        "data": {
            "fetched": [{
                "exchange": exchange, "symbolToken": token,
                "tradingSymbol": "Nifty 50", "ltp": ltp,
            }],
            "unfetched": [],
        },
    }


def test_valid_response_stays_read_only_and_not_feed_verified():
    client = FakeClient(response())
    r = fetch_live_quote(
        client, symbol="NIFTY", token="99926000", received_at=NOW)
    assert client.calls == [("LTP", {"NSE": ["99926000"]})]
    assert r["ltp"] == 25600.5
    assert r["feed_freshness_verified"] is False
    assert r["orders_enabled"] is False
    assert r["smc_trade_ready"] is False
    assert r["options_quotes_verified"] is False
    assert r["research_only"] is True
    assert r["received_at_utc"] == NOW.isoformat()


def test_bse_index_exchange():
    client = FakeClient(response(83000, token="99919000", exchange="BSE"))
    fetch_live_quote(client, symbol="SENSEX", token="99919000",
                     received_at=NOW)
    assert client.calls == [("LTP", {"BSE": ["99919000"]})]


@pytest.mark.parametrize("value", [None, -1, 0, "nan", "inf", "bad"])
def test_invalid_ltp_fails_closed(value):
    with pytest.raises(LiveQuoteError, match="INVALID_LTP"):
        validate_live_quote(response(value), symbol="NIFTY",
                            token="99926000", received_at=NOW)


def test_wrong_exchange_and_token_fails_closed():
    for x in (response(exchange="BSE"), response(token="wrong")):
        with pytest.raises(LiveQuoteError, match="QUOTE_TOKEN"):
            validate_live_quote(x, symbol="NIFTY",
                                token="99926000", received_at=NOW)


def test_ambiguous_quote_rejected():
    x = response()
    x["data"]["fetched"].append(x["data"]["fetched"][0].copy())
    with pytest.raises(LiveQuoteError, match="AMBIGUOUS"):
        validate_live_quote(x, symbol="NIFTY",
                            token="99926000", received_at=NOW)


def test_error_response_rejected_without_leaking_response():
    x = {"status": False, "message": "SECRET DO NOT LOG", "data": None}
    with pytest.raises(LiveQuoteError) as error:
        validate_live_quote(x, symbol="NIFTY",
                            token="99926000", received_at=NOW)
    assert "SECRET" not in str(error.value)


def test_sdk_network_exception_hidden():
    client = FakeClient(error=RuntimeError("MY_SECRET_TOKEN"))
    with pytest.raises(LiveQuoteError) as error:
        fetch_live_quote(client, symbol="NIFTY",
                         token="99926000", received_at=NOW)
    assert "MY_SECRET_TOKEN" not in str(error.value)


def test_no_feed_timestamp_not_mistaken_for_live_tick():
    x = validate_live_quote(response(), symbol="NIFTY",
                            token="99926000", received_at=NOW)
    assert x["exchange_feed_time_raw"] is None
    assert x["feed_freshness_verified"] is False
