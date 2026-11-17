"""Causal, research-only 15-minute opening-range breakout evaluation.

Input mappings contain OHLCV and aware timestamps for completed 1m or 5m
bars. Default timestamps denote bar close; use timestamp_kind='open' for
bar-open feeds. No data is fetched and no orders are submitted.
"""
from datetime import datetime, time, timedelta
from math import isfinite
from zoneinfo import ZoneInfo

from .option_strike_engine import select_strikes

IST = ZoneInfo('Asia/Kolkata')


def _number(value, name, zero=False):
    value = float(value)
    if not isfinite(value) or value < 0 or (not zero and value == 0):
        raise ValueError(f'Invalid {name}')
    return value


def evaluate_orb_15m(candles, *, symbol='NIFTY', interval_minutes=5,
                       timestamp_kind='close', retest_tolerance=3,
                       volume_multiplier=1, quotes=None, quote_path=None,
                       expiry=None, now=None):
    """Return latest session range/status and causal signals across input days.

    NIFTY valid range: 10..150 points; stops: 10..30. SENSEX uses 3x
    these distances (an explicit research heuristic). Stops use the nearest
    eligible midpoint or breakout wick, widened to the minimum when needed;
    candidates above the maximum are rejected. Targets are exactly 2R.
    Zero/missing volume uses cash-index price action only. When positive
    volume is supplied, retain the optional preceding-volume confirmation.
    Emit at most one initial breakout and one later retest per side/session.
    Retests must touch the broken boundary and close outside it. Missing
    opening bars block the session. Explicitly incomplete bars are rejected.
    """
    symbol = str(symbol).upper()
    if symbol not in ('NIFTY', 'SENSEX') or interval_minutes not in (1, 5):
        raise ValueError('Invalid symbol or interval')
    if timestamp_kind not in ('open', 'close'):
        raise ValueError('Invalid timestamp_kind')
    tolerance = _number(retest_tolerance, 'retest_tolerance', zero=True)
    multiplier = _number(volume_multiplier, 'volume_multiplier', zero=True)
    quotes = list(quotes or [])
    scale = 1 if symbol == 'NIFTY' else 3
    duration = timedelta(minutes=interval_minutes)
    signals, last, day = [], None, None
    summary = dict(status='NO_DATA', orb_high=None, orb_low=None,
                   orb_midpoint=None, range_span=None, breakout_status='NONE')
    for source in candles:
        if source.get('completed', True) is not True or source.get('closed', True) is not True:
            raise ValueError('Completed candles required')
        at = source['timestamp']
        at = datetime.fromisoformat(at) if isinstance(at, str) else at
        if not isinstance(at, datetime) or at.tzinfo is None or at.utcoffset() is None:
            raise ValueError('Timezone-aware timestamp required')
        if last is not None and at <= last:
            raise ValueError('Timestamps must strictly increase')
        last = at
        close_at = at.astimezone(IST) + (duration if timestamp_kind == 'open' else timedelta())
        start = close_at-duration
        o, h, l, c = (_number(source[k], k) for k in ('open', 'high', 'low', 'close'))
        volume = _number(source.get('volume', 0), 'volume', zero=True)
        if not l <= min(o, c) <= max(o, c) <= h:
            raise ValueError('Invalid OHLC')
        if start.date() != close_at.date() or start.time() < time(9, 15) or close_at.time() > time(15, 30):
            continue
        if day != close_at.date():
            day = close_at.date()
            opening, volumes, broken, retested = [], [], {}, set()
            summary = dict(session_date=day.isoformat(), status='BUILDING_RANGE',
                           orb_high=None, orb_low=None, orb_midpoint=None,
                           range_span=None, breakout_status='NONE')
        session_open = datetime.combine(day, time(9, 15), IST)
        lock_at = datetime.combine(day, time(9, 30), IST)
        if close_at <= lock_at:
            opening.append((start, close_at, h, l))
            volumes.append(volume)
            if close_at < lock_at:
                continue
        if summary['status'] == 'BUILDING_RANGE':
            expected = [session_open + i*duration for i in range(15//interval_minutes)]
            if [b[0] for b in opening] != expected:
                summary['status'] = 'INCOMPLETE_RANGE'
            else:
                high, low = max(b[2] for b in opening), min(b[3] for b in opening)
                span = high-low
                summary.update(orb_high=high, orb_low=low, orb_midpoint=(high+low)/2,
                               range_span=span, status='LOCKED' if 10*scale <= span <= 150*scale else 'ANOMALOUS_RANGE')
        if close_at <= lock_at:
            continue
        average = sum(volumes)/len(volumes) if volumes else 0
        volumes.append(volume)
        if summary['status'] != 'LOCKED' or (volume > 0 and volume < average*multiplier):
            continue
        high, low, midpoint = (summary[k] for k in ('orb_high', 'orb_low', 'orb_midpoint'))
        direction = 'BULLISH' if c > high else 'BEARISH' if c < low else None
        if direction is None:
            continue
        bullish = direction == 'BULLISH'
        boundary = high if bullish else low
        kind = 'BREAKOUT'
        if direction in broken:
            if direction in retested or not (abs((l if bullish else h)-boundary) <= tolerance):
                continue
            kind = 'RETEST'
        wick = broken.get(direction, l if bullish else h)
        distances = [c-level if bullish else level-c for level in (midpoint, wick)]
        risks = [max(10*scale, distance) for distance in distances if 0 < distance <= 30*scale]
        if not risks:
            continue
        risk = min(risks)
        signal = dict(strategy='ORB_15M', timestamp=close_at.isoformat(), symbol=symbol,
                      direction=direction, side='CE' if bullish else 'PE', signal_type=kind,
                      entry=c, stop_loss=c-risk if bullish else c+risk,
                      target=c+2*risk if bullish else c-2*risk,
                      index_sl_pts=risk, index_target_pts=2*risk, risk_reward=2.,
                      confirmation_source='PRICE_ONLY' if volume == 0 else 'PRICE_AND_VOLUME',
                      orb_high=high, orb_low=low, orb_midpoint=midpoint, range_span=high-low,
                      strikes=select_strikes(c, direction, risk, 2*risk, symbol=symbol,
                                            quotes=quotes, quote_path=quote_path, expiry=expiry, now=now),
                      research_only=True, orders_enabled=False)
        signals.append(signal)
        if kind == 'BREAKOUT':
            broken[direction] = l if bullish else h
        else:
            retested.add(direction)
        summary['breakout_status'] = direction
    return {**summary, 'signals': signals, 'research_only': True, 'orders_enabled': False}
