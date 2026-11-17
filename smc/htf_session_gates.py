"""Higher Timeframe (15m, 1H) and Session Timing Gates for SMC Strategy.

Reuses the repository's existing closed HTF aggregation and directional logic:
- Aggregates contiguous 1m bars from audited sessions (09:16 to 15:15 IST) into
  session-aligned 15m (24 bars/day) and 1H (60m, 6 bars/day) candles.
- At setup confirmation, uses ONLY HTF candles already closed (timestamp <= confirm_time).
- Determines HTF direction using causal external structure breaks via
  smc.market_context_v310.structure_snapshot (BULLISH, BEARISH, NEUTRAL, UNAVAILABLE).
- Evaluates session timing windows on simulated entry time:
  Allowed windows: [09:30, 11:00) IST and [13:15, 14:45) IST.
"""
from __future__ import annotations

from bisect import bisect_right
from datetime import datetime, time, timedelta
from typing import Any, NamedTuple, Sequence
from zoneinfo import ZoneInfo

from .market_context_v310 import _merge, structure_snapshot
from .models import Candle

IST = ZoneInfo("Asia/Kolkata")

# Session entry windows
WINDOW_1_START = time(9, 30)
WINDOW_1_END = time(11, 0)
WINDOW_2_START = time(13, 15)
WINDOW_2_END = time(14, 45)


class HTFGateResult(NamedTuple):
    allowed: bool
    htf_bias: str  # "BULLISH", "BEARISH", "NEUTRAL", "UNAVAILABLE"
    state: str     # "ALIGNED", "OPPOSITE", "NEUTRAL", "UNAVAILABLE"
    block_reason: str | None
    closed_htf_bars_count: int
    last_break: str | None
    last_break_at: str | None


class SessionWindowResult(NamedTuple):
    allowed: bool
    status: str  # "IN_WINDOW", "PRE_0930", "MIDDAY_1100_1315", "LATE_POST_1445"
    block_reason: str | None


def build_aggregated_htf_bars(
    usable_sessions: dict[str, list[Candle]],
) -> tuple[list[Candle], list[Candle]]:
    """Build continuous 15m and 1H bars across all usable sessions, aligned to session open."""
    all_15m: list[Candle] = []
    all_1h: list[Candle] = []

    sorted_dates = sorted(usable_sessions.keys())
    for d in sorted_dates:
        sess = usable_sessions[d]
        # 15m bars: 24 bars per 360-minute session
        for i in range(0, len(sess), 15):
            group = sess[i : i + 15]
            if len(group) == 15:
                all_15m.append(_merge(group))

        # 1H bars: 6 bars per 360-minute session (09:16..10:15, 10:16..11:15, ..., 14:16..15:15)
        for i in range(0, len(sess), 60):
            group = sess[i : i + 60]
            if len(group) == 60:
                all_1h.append(_merge(group))

    return all_15m, all_1h


def evaluate_htf_gate(
    setup_direction: str,
    all_htf_bars: list[Candle],
    htf_timestamps: list[datetime],
    confirm_time: datetime,
    timeframe: str,
) -> HTFGateResult:
    """Evaluate HTF directional alignment using only HTF candles closed before or at confirm_time."""
    # Find all HTF bars with timestamp <= confirm_time (candle close timestamp <= confirm_time)
    idx = bisect_right(htf_timestamps, confirm_time)
    closed_htf = all_htf_bars[:idx]
    count = len(closed_htf)

    if count < 6:
        return HTFGateResult(
            allowed=False,
            htf_bias="UNAVAILABLE",
            state="UNAVAILABLE",
            block_reason=f"BLOCKED_HTF_UNAVAILABLE (have {count} closed {timeframe} bars, need >= 6)",
            closed_htf_bars_count=count,
            last_break=None,
            last_break_at=None,
        )

    snap = structure_snapshot(closed_htf, timeframe=timeframe)
    bias = snap["bias"]
    last_break = snap.get("last_break")
    last_break_at = snap.get("last_break_at")

    if bias in ("UNVERIFIED", "NEUTRAL", None):
        return HTFGateResult(
            allowed=False,
            htf_bias="NEUTRAL",
            state="NEUTRAL",
            block_reason=f"BLOCKED_HTF_NEUTRAL (no confirmed external structure break on {timeframe})",
            closed_htf_bars_count=count,
            last_break=last_break,
            last_break_at=last_break_at,
        )

    if bias == setup_direction:
        return HTFGateResult(
            allowed=True,
            htf_bias=bias,
            state="ALIGNED",
            block_reason=None,
            closed_htf_bars_count=count,
            last_break=last_break,
            last_break_at=last_break_at,
        )
    else:
        opp_reason = f"BLOCKED_HTF_OPPOSITE_{bias}"
        return HTFGateResult(
            allowed=False,
            htf_bias=bias,
            state="OPPOSITE",
            block_reason=opp_reason,
            closed_htf_bars_count=count,
            last_break=last_break,
            last_break_at=last_break_at,
        )


def evaluate_session_timing_window(entry_time: datetime) -> SessionWindowResult:
    """Evaluate whether simulated entry time falls within [09:30, 11:00) or [13:15, 14:45) IST."""
    t = entry_time.astimezone(IST).time()

    if (WINDOW_1_START <= t < WINDOW_1_END) or (WINDOW_2_START <= t < WINDOW_2_END):
        return SessionWindowResult(allowed=True, status="IN_WINDOW", block_reason=None)

    if t < WINDOW_1_START:
        return SessionWindowResult(
            allowed=False,
            status="PRE_0930",
            block_reason="BLOCKED_SESSION_PRE_0930",
        )
    elif WINDOW_1_END <= t < WINDOW_2_START:
        return SessionWindowResult(
            allowed=False,
            status="MIDDAY_1100_1315",
            block_reason="BLOCKED_SESSION_MIDDAY_1100_1315",
        )
    else:
        return SessionWindowResult(
            allowed=False,
            status="LATE_POST_1445",
            block_reason="BLOCKED_SESSION_LATE_POST_1445",
        )

