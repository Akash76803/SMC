"""Completed-candle and signal helpers for independent research engines."""
from datetime import datetime, time, timedelta
from math import isfinite
from zoneinfo import ZoneInfo

from .option_strike_engine import select_strikes

IST = ZoneInfo('Asia/Kolkata')


def session_bars(candles, symbol, now=None):
    bars = {}
    for raw in candles:
        if raw.get('symbol', raw.get('market', symbol)) != symbol:
            continue
        at = raw['timestamp']
        at = datetime.fromisoformat(at) if isinstance(at, str) else at
        if at.tzinfo is None or (now is not None and at > now):
            continue
        at = at.astimezone(IST)
        if not time(9, 15) < at.time() <= time(15, 30):
            continue
        o, h, l, c = (float(raw[key]) for key in ('open', 'high', 'low', 'close'))
        if all(isfinite(v) for v in (o, h, l, c)) and 0 < l <= min(o, c) <= max(o, c) <= h:
            bars[at] = dict(timestamp=at, open=o, high=h, low=l, close=c)
    return [bars[at] for at in sorted(bars)]


def resample(bars, source, target):
    if source > target or target % source:
        return []
    groups = {}
    for bar in bars:
        at = bar['timestamp']
        opened = at.replace(hour=9, minute=15, second=0, microsecond=0)
        seconds = (at - opened).total_seconds()
        if seconds % (60 * source):
            continue
        bucket = (int(seconds) - 1) // (60 * target) + 1
        end = opened + timedelta(minutes=bucket * target)
        groups.setdefault(end, []).append(bar)
    return [
        dict(timestamp=end, open=group[0]['open'], close=group[-1]['close'],
             high=max(row['high'] for row in group), low=min(row['low'] for row in group))
        for end, group in groups.items()
        if len(group) == target // source and group[-1]['timestamp'] == end
    ]


def build_signal(strategy, pattern, at, symbol, sign, entry, stop, target,
                 timeframe, quotes=None):
    risk, reward = sign * (entry - stop), sign * (target - entry)
    if risk <= 0 or reward + 1e-9 < 2 * risk or min(entry, stop, target) <= 0:
        return None
    direction, side = ('BULLISH', 'CE') if sign > 0 else ('BEARISH', 'PE')
    strikes = select_strikes(entry, direction, risk, reward, symbol=symbol, quotes=quotes, now=at)
    return dict(
        strategy=strategy, setup_id=f'{symbol}:{strategy}:{pattern}:{at.isoformat()}',
        pattern_or_trigger=pattern, timestamp=at.isoformat(), symbol=symbol,
        direction=direction, side=side, entry=entry, stop_loss=stop, target=target,
        index_sl_pts=risk, index_target_pts=reward, risk_reward=max(2.0, reward / risk),
        timeframe=f'{timeframe}m', confirmation_source=strategy,
        strikes=[dict(strike=row['strike'], option_type=side, premium_entry=row['premium_entry'],
                      premium_sl=row['premium_sl'], premium_target=row['premium_target'])
                 for row in strikes.values()],
        research_only=True, orders_enabled=False,
    )


def candle_sessions(candles, symbol, now=None):
    from itertools import groupby

    return [list(rows) for _, rows in groupby(
        session_bars(candles, symbol, now), key=lambda bar: bar['timestamp'].date()
    )]


def swing_context(bars):
    """Yield candles with the latest swing high and low confirmed before each close."""
    high = low = None
    for index, bar in enumerate(bars):
        if index >= 3:
            left, pivot, right = bars[index - 3:index]
            if pivot['high'] > max(left['high'], right['high']):
                high = pivot['high']
            if pivot['low'] < min(left['low'], right['low']):
                low = pivot['low']
        yield index, bar, high, low


def displacement(bar, previous, high, low):
    span = bar['high'] - bar['low']
    body = bar['close'] - bar['open']
    if not span or abs(body) < 0.6 * span:
        return 0
    if body > 0 and high is not None and previous['close'] <= high < bar['close']:
        return 1
    if body < 0 and low is not None and previous['close'] >= low > bar['close']:
        return -1
    return 0
