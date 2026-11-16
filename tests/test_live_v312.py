"""V3.12 offline WebSocket/candle/SMC safety contract tests."""
from datetime import datetime, timedelta, timezone
from io import StringIO
import json

import pytest

from smc.angel_stream_v312 import parse_tick, StreamDataError, ValidatedTick
from smc.live_candles_v312 import LiveCandleBuilder
from smc.live_research_v312 import LiveResearchEngine
from smc.angel_stream_cli_v312 import run_live

IST = timezone(timedelta(hours=5, minutes=30))
T = datetime(2026, 11, 16, 9, 15, tzinfo=IST)


def tick(at=T, price=25200, seq=1, symbol="NIFTY"):
    return ValidatedTick(symbol, "99926000", price, at, at, seq)


def packet(at=T, price=25200, seq=1, exchange=1, token="99926000"):
    return {"subscription_mode": 1, "exchange_type": exchange, "token": token,
            "sequence_number": seq, "exchange_timestamp": int(at.timestamp()*1000),
            "last_traded_price": int(price*100)}


def test_smartapi_price_scale_epoch_and_token():
    x = parse_tick(packet(), symbol="NIFTY", token="99926000",
                   received_at=T + timedelta(seconds=1))
    assert x.price == 25200
    assert x.exchange_at == T
    assert x.sequence == 1


@pytest.mark.parametrize("mod,reason", [
    ({"exchange_type": 3}, "WS_WRONG_EXCHANGE"),
    ({"token": "X"}, "WS_WRONG_TOKEN"),
    ({"subscription_mode": 0}, "UNSUPPORTED_WS_MODE"),
    ({"last_traded_price": 0}, "INVALID_WS_TICK_FIELDS"),
    ({"exchange_timestamp": 0}, "INVALID_WS_TICK_FIELDS"),
])
def test_invalid_stream_fields_fail_closed(mod, reason):
    x = packet()
    x.update(mod)
    with pytest.raises(StreamDataError, match=reason):
        parse_tick(x, symbol="NIFTY", token="99926000", received_at=T)


def test_stale_and_future_ticks_are_rejected():
    with pytest.raises(StreamDataError, match="STALE"):
        parse_tick(packet(), symbol="NIFTY", token="99926000",
                   received_at=T + timedelta(seconds=20))
    with pytest.raises(StreamDataError, match="FUTURE"):
        parse_tick(packet(), symbol="NIFTY", token="99926000",
                   received_at=T - timedelta(seconds=5))


def test_candle_uses_exchange_minute_and_later_tick_to_finalize():
    b = LiveCandleBuilder("NIFTY")
    assert b.ingest(tick()) is None
    assert b.ingest(tick(T + timedelta(seconds=30), 25210, 2)) is None
    c = b.ingest(tick(T + timedelta(minutes=1), 25205, 3))
    assert c.timestamp == T + timedelta(minutes=1)
    assert (c.open, c.high, c.low, c.close) == (25200, 25210, 25200, 25210)
    assert c.volume == 0
    assert b.state()["volume_verified"] is False
    assert b.state()["orders_enabled"] is False


def test_gap_disables_analysis_and_does_not_synthesize_candle():
    b = LiveCandleBuilder("NIFTY")
    b.ingest(tick())
    assert b.ingest(tick(T + timedelta(minutes=3), seq=2)) is None
    assert b.quality_blocked
    assert b.gaps == 2
    assert b.completed == []


def test_out_of_order_tick_is_rejected():
    b = LiveCandleBuilder("NIFTY")
    b.ingest(tick())
    with pytest.raises(StreamDataError, match="NONMONOTONIC"):
        b.ingest(tick(T, seq=2))


def test_outside_regular_session_is_rejected():
    b = LiveCandleBuilder("NIFTY")
    with pytest.raises(StreamDataError, match="OUTSIDE_REGULAR_SESSION"):
        b.ingest(tick(T - timedelta(minutes=1)))


def test_coordinator_only_reports_on_closed_candle():
    engine = LiveResearchEngine("NIFTY")
    assert engine.on_tick(tick()) is None
    event = engine.on_tick(tick(T + timedelta(minutes=1), 25205, 2))
    assert event["status"] == "WAIT"
    assert event["reason"] == "STRUCTURE_WARMUP"
    assert event["orders_enabled"] is False
    assert event["entry"] is None


def test_disconnect_blocks_followup_trading_claims():
    engine = LiveResearchEngine("NIFTY")
    engine.on_tick(tick())
    engine.on_disconnect()
    x = engine.on_tick(tick(T + timedelta(minutes=1), seq=2))
    assert x["status"] == "WAIT"
    assert x["reason"] == "UNVERIFIED_STREAM_CONTINUITY"


def test_12_candles_research_only_no_orders():
    engine = LiveResearchEngine("NIFTY")
    result = None
    for i in range(13):
        result = engine.on_tick(tick(T + timedelta(minutes=i),
                                     25200 + i, seq=i+1))
    assert result["status"] == "RESEARCH_ONLY"
    assert "intraday_mtf" in result
    assert result["orders_enabled"] is False
    assert result["entry"] is None


def test_sensex_websocket_exchange_type():
    x = packet(exchange=3, token="99919000")
    y = parse_tick(x, symbol="SENSEX", token="99919000",
                   received_at=T + timedelta(seconds=1))
    assert y.symbol == "SENSEX"


class FakeSocket:
    def __init__(self):
        self.on_open = None
        self.on_data = None
        self.on_error = None
        self.on_close = None
        self.subscriptions = []
        self.closed = False

    def subscribe(self, correlation, mode, token_list):
        self.subscriptions.append((mode, token_list))

    def close_connection(self):
        self.closed = True

    def connect(self):
        self.on_open(self)
        self.on_data(self, packet(at=datetime.now(IST)))
        self.on_close(self)


def test_websocket_cli_boundary_is_read_only():
    ws = FakeSocket()
    output = StringIO()
    result = run_live(symbol="NIFTY", token="99926000", ws=ws,
                      output=output, max_seconds=5)
    assert ws.subscriptions == [(1, [{"exchangeType": 1, "tokens": ["99926000"]}])]
    assert ws.closed
    assert result["orders_enabled"] is False
    assert result["ticks"] == 1
    assert output.getvalue() == ""

def test_secure_websocket_requires_tls_certificates():
    import ssl
    from smc.angel_secure_ws_v312 import make_secure_websocket

    connections = []
    class FakeApp:
        def __init__(self, uri, **kwargs):
            connections.append((uri, kwargs))
        def run_forever(self, **kwargs):
            connections.append(kwargs)
    class FakeSDK:
        ROOT_URI = "wss://test.invalid"
        HEART_BEAT_INTERVAL = 10
        def __init__(self, auth_token, api_key, client_code, feed_token, **kwargs):
            self.auth_token = auth_token
            self.api_key = api_key
            self.client_code = client_code
            self.feed_token = feed_token
            self.on_open = self.on_error = self.on_close = None
            self.on_data = self.on_ping = self.on_pong = None
        def _on_open(self, *args): pass
        def _on_error(self, *args): pass
        def _on_close(self, *args): pass
        def _on_data(self, *args): pass
        def _on_ping(self, *args): pass
        def _on_pong(self, *args): pass
    socket = make_secure_websocket("test-jwt", "test-key", "test-client", "test-feed",
                                   ws_class=FakeSDK,
                                   websocket_module=type("W", (), {"WebSocketApp": FakeApp}))
    socket.connect()
    options = connections[1]["sslopt"]
    assert options["cert_reqs"] == ssl.CERT_REQUIRED
    assert options["check_hostname"] is True
