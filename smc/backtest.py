"""Phase 3.4 walk-forward *index-level* research backtester.

No future candles are passed to signal_fn; an approved signal at a bar close
can fill only on the NEXT completed bar's open. OHLC cannot reveal intrabar
execution ordering: simultaneous target+stop conservatively resolves to STOP.

Important: index-point PnL is NOT option-premium PnL. There is no live data,
broker execution, historical option quote replay, or proven profitability.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Callable, Sequence

from .models import Candle, IndexSetup, Side
from .risk import validate_index_setup


class ExitReason(str, Enum):
    STOP = "STOP"
    TARGET = "TARGET"
    TIME_EXIT = "TIME_EXIT"
    END_OF_DATA = "END_OF_DATA"


@dataclass(frozen=True)
class BacktestConfig:
    max_holding_bars: int = 24
    # Round trip index-point equivalent for illustrative index-only stats.
    # Actual option fees, theta, IV and execution slippage are NOT modeled.
    entry_slippage_points: float = 0.0
    exit_slippage_points: float = 0.0
    round_trip_cost_points: float = 0.0

    def __post_init__(self):
        if self.max_holding_bars < 1 or min(
            self.entry_slippage_points, self.exit_slippage_points,
            self.round_trip_cost_points
        ) < 0:
            raise ValueError("invalid backtest configuration")


@dataclass(frozen=True)
class Signal:
    """Closed-bar research event. All levels must be known on signal_index."""
    setup: IndexSetup
    signal_index: int


@dataclass(frozen=True)
class BacktestTrade:
    symbol: str
    side: Side
    signal_index: int
    entry_index: int
    exit_index: int
    entry_price: float
    exit_price: float
    stop: float
    target: float
    exit_reason: ExitReason
    net_index_points: float


@dataclass(frozen=True)
class BacktestReport:
    trades: tuple[BacktestTrade, ...]
    signals_rejected: int
    signals_skipped: int
    total_net_index_points: float
    win_rate: float | None
    profit_factor: float | None
    max_drawdown_points: float
    mode: str = "INDEX_POINTS_ONLY_NOT_OPTION_PNL"


SignalFn = Callable[[tuple[Candle, ...]], Signal | None]


def _exit_bar(side: Side, bar: Candle, stop: float,
              target: float, time_exit: bool
              ) -> tuple[float, ExitReason] | None:
    if side == Side.CE:
        # Gap through stop/target fills at opening price, not stale threshold.
        if bar.open <= stop:
            return bar.open, ExitReason.STOP
        if bar.open >= target:
            return bar.open, ExitReason.TARGET
        if bar.low <= stop:  # STOP wins if both touched
            return stop, ExitReason.STOP
        if bar.high >= target:
            return target, ExitReason.TARGET
    else:
        if bar.open >= stop:
            return bar.open, ExitReason.STOP
        if bar.open <= target:
            return bar.open, ExitReason.TARGET
        if bar.high >= stop:
            return stop, ExitReason.STOP
        if bar.low <= target:
            return target, ExitReason.TARGET
    if time_exit:
        return bar.close, ExitReason.TIME_EXIT
    return None


def walk_forward_backtest(
    candles: Sequence[Candle],
    signal_fn: SignalFn,
    config: BacktestConfig = BacktestConfig(),
) -> BacktestReport:
    """Replay completed OHLC candles without any future input to signal_fn.

    Timestamp is treated as a bar CLOSE time for this backtest API.
    A signal is evaluated after candle[i] closes. If approved, entry can
    occur at candle[i+1].open; otherwise no fill. Only one position at a time.
    A signal on the last candle is skipped (no next-bar fill).
    """
    if any(not c.complete for c in candles):
        raise ValueError("backtest requires fully completed bars")
    if any(candles[i].timestamp >= candles[i+1].timestamp
           for i in range(len(candles)-1)):
        raise ValueError("candles must be strictly ordered")
    trades: list[BacktestTrade] = []
    rejected = skipped = 0
    position: dict | None = None
    pending: Signal | None = None

    for i, candle in enumerate(candles):
        if pending is not None:
            # No entries can be retrospectively filled on the signal candle.
            setup = pending.setup
            raw_entry = candle.open
            # If next bar gaps beyond stop or target, the old bracket is stale.
            # Skip rather than quietly manufacture the desired entry price.
            valid = (setup.stop < raw_entry < setup.target if setup.side == Side.CE
                     else setup.target < raw_entry < setup.stop)
            if not valid:
                skipped += 1
            else:
                direction = 1 if setup.side == Side.CE else -1
                execution = raw_entry + direction * config.entry_slippage_points
                if (setup.stop < execution < setup.target if setup.side == Side.CE
                        else setup.target < execution < setup.stop):
                    position = dict(
                        signal=pending, entry_index=i,
                        entry=execution
                    )
                else:
                    skipped += 1
            pending = None

        if position is not None:
            setup = position["signal"].setup
            age = i - position["entry_index"] + 1
            outcome = _exit_bar(
                setup.side, candle, setup.stop, setup.target,
                age >= config.max_holding_bars
            )
            if outcome is not None or i == len(candles)-1:
                raw_exit, reason = (outcome if outcome is not None
                                    else (candle.close, ExitReason.END_OF_DATA))
                direction = 1 if setup.side == Side.CE else -1
                executed_exit = raw_exit - direction * config.exit_slippage_points
                pnl = (executed_exit-position["entry"]) * direction
                pnl -= config.round_trip_cost_points
                trades.append(BacktestTrade(
                    setup.symbol, setup.side, position["signal"].signal_index,
                    position["entry_index"], i, position["entry"],
                    executed_exit, setup.stop, setup.target, reason, pnl
                ))
                position = None
            continue

        # Evaluate after bar close; the callback sees only the prefix.
        # Signal on the very last bar cannot enter and is not executed.
        if i == len(candles)-1:
            break
        signal = signal_fn(tuple(candles[:i+1]))
        if signal is None:
            continue
        if not isinstance(signal, Signal) or signal.signal_index != i:
            rejected += 1
            continue
        if not validate_index_setup(signal.setup).accepted:
            rejected += 1
            continue
        pending = signal

    total = sum(t.net_index_points for t in trades)
    wins = sum(1 for t in trades if t.net_index_points > 0)
    gains = sum(t.net_index_points for t in trades if t.net_index_points > 0)
    losses = -sum(t.net_index_points for t in trades if t.net_index_points < 0)
    equity, peak, max_dd = 0.0, 0.0, 0.0
    for trade in trades:
        equity += trade.net_index_points
        peak = max(peak,equity)
        max_dd = max(max_dd,peak-equity)
    return BacktestReport(
        tuple(trades), rejected, skipped, total,
        wins/len(trades) if trades else None,
        gains/losses if losses else None,
        max_dd
    )
