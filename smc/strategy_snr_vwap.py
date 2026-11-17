"""Standalone completed-candle S&R/VWAP research; no brokerage operations.

Timestamps must be timezone-aware and strictly increasing. Callers supply
completed, consistently spaced 1m or 5m candles (timestamp at bar close).
Session statistics reset on each Indian trading date. Reference levels apply
to the supplied session(s); multi-day callers should pass references per day.
"""
from datetime import datetime
from math import isfinite
from zoneinfo import ZoneInfo

from .option_strike_engine import select_strikes

IST = ZoneInfo('Asia/Kolkata')


def _positive(value, name, zero=False):
    value = float(value)
    if not isfinite(value) or value < 0 or (value == 0 and not zero):
        raise ValueError(f'Invalid {name}')
    return value


def calculate_levels(candles, previous_day=None):
    """Return one causal level snapshot per bar, including cumulative VWAP.

    With no cumulative volume, vwap is the cumulative typical-price mean
    (labelled TYPICAL_PRICE_MEAN, not exchange VWAP). Explicit incomplete bars,
    invalid OHLCV and unordered timestamps are rejected. Prior session
    extrema exclude the current bar; session_high/low include it.
    """
    refs = previous_day or {}
    refs = {key: _positive(refs[key], key) for key in ('PDH', 'PDL', 'PDC') if key in refs}
    if 'PDH' in refs and 'PDL' in refs and refs['PDH'] < refs['PDL']:
        raise ValueError('PDH below PDL')
    pivots = {}
    if len(refs) == 3:
        p = sum(refs.values()) / 3
        pivots = dict(P=p, R1=2*p-refs['PDL'], S1=2*p-refs['PDH'],
                      R2=p+refs['PDH']-refs['PDL'], S2=p-refs['PDH']+refs['PDL'])
    output, last, session = [], None, None
    for source in candles:
        if source.get('completed', True) is not True or source.get('closed', True) is not True:
            raise ValueError('Only completed candles accepted')
        at = source['timestamp']
        at = datetime.fromisoformat(at) if isinstance(at, str) else at
        if not isinstance(at, datetime) or at.tzinfo is None or at.utcoffset() is None:
            raise ValueError('Timezone-aware timestamp required')
        if last is not None and at <= last:
            raise ValueError('Timestamps must increase')
        last = at
        o, h, l, c = (_positive(source[k], k) for k in ('open', 'high', 'low', 'close'))
        v = _positive(source.get('volume', 0), 'volume', zero=True)
        if not l <= min(o, c) <= max(o, c) <= h:
            raise ValueError('Invalid OHLC range')
        day = at.astimezone(IST).date()
        if day != session:
            session, pv, volume, high, low, day_open = day, 0., 0., None, None, o
            typical_sum, count = 0., 0
        prior_high, prior_low = high, low
        high = max(high, h) if high is not None else h
        low = min(low, l) if low is not None else l
        pv += (h+l+c)/3*v
        volume += v
        typical_sum += (h+l+c)/3
        count += 1
        output.append(dict(timestamp=at.isoformat(), open=o, high=h, low=l, close=c,
                           volume=v, vwap=pv/volume if volume else typical_sum/count,
                           vwap_source='VOLUME_WEIGHTED' if volume else 'TYPICAL_PRICE_MEAN',
                           session_high=high, session_low=low, day_open=day_open,
                           prior_session_high=prior_high, prior_session_low=prior_low,
                           **refs, **pivots))
    return output


def scan_snr_signals(candles, previous_day=None, *, symbol='NIFTY', tolerance=6,
                     quotes=None, quote_path=None, expiry=None, now=None):
    """Return rejection setups with >=2R unobstructed by a known S&R level.

    Stops extend two points beyond the wick, widened to eight points when
    needed. Stops requiring more than twenty points are rejected rather than
    clipped inside the wick. Nearest opposing levels below 2R block entry;
    when none exists, use a 2R projected target. Zero-body dojis are excluded.
    Quote freshness uses wall clock unless an explicit replay ``now`` is given.
    """
    tolerance = _positive(tolerance, 'tolerance', zero=True)
    symbol = str(symbol).upper()
    if symbol not in ('NIFTY', 'SENSEX'):
        raise ValueError('Invalid symbol')
    quotes = list(quotes or [])
    signals = []
    for bar in calculate_levels(candles, previous_day):
        o, h, l, c = (bar[k] for k in ('open', 'high', 'low', 'close'))
        body, span = abs(c-o), h-l
        if not body or not span:
            continue
        support = {k: bar.get(k) for k in ('PDL', 'prior_session_low', 'vwap', 'S1', 'S2', 'P')}
        resistance = {k: bar.get(k) for k in ('PDH', 'prior_session_high', 'vwap', 'R1', 'R2', 'P')}
        bullish = c > o and min(o, c)-l >= 2*body and c >= l+.65*span
        bearish = c < o and h-max(o, c) >= 2*body and c <= l+.35*span
        if not bullish and not bearish:
            continue
        levels = support if bullish else resistance
        tested = [k for k, value in levels.items() if value is not None
                  and abs((l if bullish else h)-value) <= tolerance
                  and (c >= value if bullish else c <= value)]
        if not tested:
            continue
        risk = max(8., c-l+2 if bullish else h-c+2)
        if risk > 20:
            continue
        opposite = resistance if bullish else support
        distances = [value-c if bullish else c-value for value in opposite.values()
                     if value is not None and (value > c if bullish else value < c)]
        reward = min(distances) if distances else 2*risk
        if reward < 2*risk:
            continue
        direction = 'BULLISH' if bullish else 'BEARISH'
        signals.append(dict(strategy='SNR_VWAP', timestamp=bar['timestamp'], symbol=symbol,
                            direction=direction, side='CE' if bullish else 'PE',
                            entry=c, stop_loss=c-risk if bullish else c+risk,
                            target=c+reward if bullish else c-reward,
                            index_sl_pts=risk, index_target_pts=reward, risk_reward=reward/risk,
                            tested_levels=tested, levels=bar,
                            strikes=select_strikes(c, direction, risk, reward, symbol=symbol,
                                                  quotes=quotes, quote_path=quote_path,
                                                  expiry=expiry, now=now),
                            research_only=True, orders_enabled=False))
    return signals
