"""Intraday Market Sentiment Classifier for SMC Strategy.

Matches the dashboard's intraday sentiment rule:
At setup confirmation (confirm_index), inspect the last 30 contiguous closed
1m candles from the same trading session (up to and including confirm_index).

Rule:
- Fewer than 30 closed 1m candles in the session: UNAVAILABLE
- Any intraday gap (delta != 1 minute) within the 30-candle window: UNAVAILABLE
- Compare the latest candle's close with the high and low of the older 15 bars:
  * latest_close > max(high of older 15 bars) -> BULLISH
  * latest_close < min(low of older 15 bars) -> BEARISH
  * min(low) <= latest_close <= max(high) (inside or at boundary) -> MIXED

Zero lookahead guarantee:
The calculation strictly depends on session_bars[:confirm_index + 1]. Any bars
occurring after confirm_index are completely inaccessible and cannot alter the result.
"""
from __future__ import annotations

from datetime import timedelta
from typing import NamedTuple, Sequence

from .models import Candle


class SentimentResult(NamedTuple):
    sentiment: str  # "BULLISH", "BEARISH", "MIXED", "UNAVAILABLE"
    reason: str
    latest_close: float | None
    older_high: float | None
    older_low: float | None
    bars_available: int


def classify_intraday_sentiment(
    session_bars: Sequence[Candle],
    confirm_index: int,
) -> SentimentResult:
    """Classify intraday market sentiment at confirm_index using strictly closed session bars."""
    if confirm_index < 0 or confirm_index >= len(session_bars):
        return SentimentResult(
            sentiment="UNAVAILABLE",
            reason=f"INDEX_OUT_OF_BOUNDS (index={confirm_index}, total_bars={len(session_bars)})",
            latest_close=None,
            older_high=None,
            older_low=None,
            bars_available=0,
        )

    # Strictly take only candles available up to confirm_index (causal, no lookahead)
    available_bars = session_bars[: confirm_index + 1]
    count = len(available_bars)

    if count < 30:
        return SentimentResult(
            sentiment="UNAVAILABLE",
            reason=f"FEWER_THAN_30_BARS (available={count}, required=30)",
            latest_close=available_bars[-1].close if available_bars else None,
            older_high=None,
            older_low=None,
            bars_available=count,
        )

    window = available_bars[-30:]

    # Check for intraday continuity / gap in the 30-bar window
    for i in range(1, 30):
        prev_t = window[i - 1].timestamp
        curr_t = window[i].timestamp
        delta = curr_t - prev_t
        if delta != timedelta(minutes=1):
            return SentimentResult(
                sentiment="UNAVAILABLE",
                reason=f"INTRADAY_GAP_IN_30_BARS ({prev_t.time()} to {curr_t.time()}, delta={delta})",
                latest_close=window[-1].close,
                older_high=None,
                older_low=None,
                bars_available=count,
            )

    # Older 15 bars: indices 0..14 of window
    older_15 = window[:15]
    high_older = max(c.high for c in older_15)
    low_older = min(c.low for c in older_15)

    latest_close = window[-1].close

    if latest_close > high_older:
        return SentimentResult(
            sentiment="BULLISH",
            reason=f"CLOSE_{latest_close:.2f}_ABOVE_OLDER_15_HIGH_{high_older:.2f}",
            latest_close=latest_close,
            older_high=high_older,
            older_low=low_older,
            bars_available=count,
        )
    elif latest_close < low_older:
        return SentimentResult(
            sentiment="BEARISH",
            reason=f"CLOSE_{latest_close:.2f}_BELOW_OLDER_15_LOW_{low_older:.2f}",
            latest_close=latest_close,
            older_high=high_older,
            older_low=low_older,
            bars_available=count,
        )
    else:
        return SentimentResult(
            sentiment="MIXED",
            reason=f"CLOSE_{latest_close:.2f}_INSIDE_OLDER_15_RANGE_[{low_older:.2f},_{high_older:.2f}]",
            latest_close=latest_close,
            older_high=high_older,
            older_low=low_older,
            bars_available=count,
        )

