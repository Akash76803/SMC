from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum


class Side(str, Enum):
    CE = "CE"
    PE = "PE"


@dataclass(frozen=True)
class Candle:
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0
    complete: bool = True

    def __post_init__(self):
        if self.timestamp.tzinfo is None:
            raise ValueError("timestamps must be timezone-aware")
        if min(self.open, self.high, self.low, self.close) <= 0:
            raise ValueError("prices must be positive")
        if self.low > min(self.open, self.close) or self.high < max(self.open, self.close):
            raise ValueError("invalid OHLC")
        if self.volume < 0:
            raise ValueError("negative volume")


@dataclass(frozen=True)
class Pivot:
    kind: str
    index: int
    price: float
    confirmed_at: int


@dataclass(frozen=True)
class StructureEvent:
    kind: str
    direction: str
    level: float
    candle_index: int


@dataclass(frozen=True)
class Zone:
    kind: str
    lower: float
    upper: float
    created_at: int


@dataclass(frozen=True)
class IndexSetup:
    symbol: str
    side: Side
    entry: float
    stop: float
    target: float
    confirmed: bool
    scheme: str = "UNVERIFIED"


@dataclass(frozen=True)
class OptionQuote:
    symbol: str
    side: Side
    strike: float
    expiry: datetime
    lot_size: int
    bid: float
    ask: float
    delta: float | None
    # Price-adapter projections: conservative SELL bid at target and stop.
    target_exit_bid: float | None
    stop_exit_bid: float | None
    quote_time: datetime
    volume: int = 0

    def __post_init__(self):
        if self.expiry.tzinfo is None or self.quote_time.tzinfo is None:
            raise ValueError("option timestamps must be timezone-aware")
