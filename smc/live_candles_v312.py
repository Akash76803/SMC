"""Conservative exchange-time 1m tick candle builder for Indian index streaming.

A candle closes only when a later fresh exchange-timestamped tick arrives.
The broker can skip trades or drop packets; missing minutes fail closed. An
observed tick cannot prove a fully sampled OHLC or actual volume.
"""
from __future__ import annotations

from datetime import datetime, timedelta, time
from zoneinfo import ZoneInfo

from .angel_stream_v312 import ValidatedTick, StreamDataError
from .models import Candle

IST = ZoneInfo("Asia/Kolkata")
SESSION_OPEN = time(9, 15)
SESSION_END = time(15, 15)


class LiveCandleBuilder:
    def __init__(self, symbol: str):
        if symbol not in ("NIFTY", "SENSEX"):
            raise ValueError("INVALID_STREAM_SYMBOL")
        self.symbol = symbol
        self._minute: datetime | None = None
        self._ohlc: list[float] = []
        self._last_sequence: int | None = None
        self._last_tick_at: datetime | None = None
        self._last_session = None
        self.gaps = 0
        self.quality_blocked = False
        self.completed: list[Candle] = []

    @staticmethod
    def _session_minute(at: datetime) -> datetime:
        return at.astimezone(IST).replace(second=0, microsecond=0)

    def ingest(self, tick: ValidatedTick) -> Candle | None:
        if tick.symbol != self.symbol:
            raise StreamDataError("CANDLE_SYMBOL_MISMATCH")
        t = self._session_minute(tick.exchange_at)
        if not SESSION_OPEN <= t.time() < SESSION_END:
            raise StreamDataError("TICK_OUTSIDE_REGULAR_SESSION")
        if self._last_tick_at is not None and tick.exchange_at <= self._last_tick_at:
            raise StreamDataError("NONMONOTONIC_STREAM_TIME")
        if self._last_sequence is not None and tick.sequence <= self._last_sequence:
            raise StreamDataError("NONMONOTONIC_STREAM_SEQUENCE")
        self._last_sequence = tick.sequence
        self._last_tick_at = tick.exchange_at

        if self._last_session is not None and self._last_session != t.date():
            # A new session does not seal prior session's last candle.
            self._minute, self._ohlc = None, []
            self.quality_blocked = True
            self.gaps += 1
        self._last_session = t.date()

        if self._minute is None:
            if t.time() != SESSION_OPEN:
                self.quality_blocked = True  # no complete open-to-current coverage
            self._minute = t
            self._ohlc = [tick.price] * 4
            return None
        if t == self._minute:
            self._ohlc[1] = max(self._ohlc[1], tick.price)
            self._ohlc[2] = min(self._ohlc[2], tick.price)
            self._ohlc[3] = tick.price
            return None
        if t < self._minute:
            raise StreamDataError("OUT_OF_ORDER_MINUTE")

        diff = int((t - self._minute).total_seconds() / 60)
        prior = self._minute
        vals = self._ohlc
        self._minute = t
        self._ohlc = [tick.price] * 4
        if diff != 1:
            self.quality_blocked = True
            self.gaps += max(1, diff - 1)
            return None

        candle = Candle(prior + timedelta(minutes=1), vals[0], vals[1],
                        vals[2], vals[3], volume=0.0)
        self.completed.append(candle)
        return candle

    def state(self) -> dict:
        return {
            "symbol": self.symbol,
            "completed_candles": len(self.completed),
            "gaps": self.gaps,
            "quality_blocked": self.quality_blocked,
            "active_minute": self._minute.isoformat() if self._minute else None,
            "volume_verified": False,
            "full_tick_coverage_verified": False,
            "orders_enabled": False,
            "research_only": True,
        }
