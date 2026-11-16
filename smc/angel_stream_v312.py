"""Angel SmartWebSocketV2 decoded tick adapter. Research only.

SDK binary parser publishes 'last_traded_price' scaled by 100, epoch
'exchange_timestamp' in milliseconds, exchange_type 1 NSE / 3 BSE CM.
Never guess timestamps or turn receipt time into exchange time.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from math import isfinite

EXCHANGE_TYPE = {"NIFTY": 1, "SENSEX": 3}


class StreamDataError(RuntimeError):
    """Safe constant messages only; raw broker packets are never logged."""


@dataclass(frozen=True)
class ValidatedTick:
    symbol: str
    token: str
    price: float
    exchange_at: datetime
    received_at: datetime
    sequence: int

    def as_dict(self) -> dict:
        return {
            "symbol": self.symbol, "price": self.price,
            "exchange_at": self.exchange_at.isoformat(),
            "received_at": self.received_at.isoformat(),
            "sequence": self.sequence, "source": "ANGEL_WEBSOCKET_V2",
            "research_only": True,
        }


def parse_tick(packet: object, *, symbol: str, token: str,
               received_at: datetime, max_age_seconds: float = 15.0,
               future_tolerance_seconds: float = 2.0) -> ValidatedTick:
    if symbol not in EXCHANGE_TYPE or not str(token).strip():
        raise ValueError("INVALID_STREAM_SYMBOL")
    if received_at.tzinfo is None or received_at.utcoffset() is None:
        raise ValueError("RECEIPT_TIMESTAMP_REQUIRES_OFFSET")
    if not isinstance(packet, dict):
        raise StreamDataError("INVALID_WS_PACKET")
    if packet.get("subscription_mode") not in (1, 2, 3):
        raise StreamDataError("UNSUPPORTED_WS_MODE")
    if packet.get("exchange_type") != EXCHANGE_TYPE[symbol]:
        raise StreamDataError("WS_WRONG_EXCHANGE")
    if str(packet.get("token", "")).strip() != str(token).strip():
        raise StreamDataError("WS_WRONG_TOKEN")
    try:
        raw_price = int(packet["last_traded_price"])
        raw_at = int(packet["exchange_timestamp"])
        sequence = int(packet["sequence_number"])
        if raw_price <= 0 or raw_at <= 0 or sequence < 0:
            raise ValueError()
        # Angel price is transmitted in paise (1/100 INR); timestamp in ms.
        price = raw_price / 100
        exchange_at = datetime.fromtimestamp(raw_at / 1000, tz=timezone.utc)
        age = (received_at - exchange_at).total_seconds()
    except (ValueError, TypeError, KeyError, OverflowError, OSError):
        raise StreamDataError("INVALID_WS_TICK_FIELDS") from None
    if not isfinite(price) or price <= 0:
        raise StreamDataError("INVALID_WS_PRICE")
    if not (0 <= max_age_seconds <= 600 and 0 <= future_tolerance_seconds <= 60):
        raise ValueError("INVALID_STREAM_FRESHNESS_CONFIG")
    if age > max_age_seconds:
        raise StreamDataError("STALE_WS_TICK")
    if age < -future_tolerance_seconds:
        raise StreamDataError("FUTURE_WS_TICK")
    return ValidatedTick(symbol, str(token), price, exchange_at, received_at,
                         sequence)
