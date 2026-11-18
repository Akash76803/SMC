"""Completed-candle price action research engine."""
from __future__ import annotations
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


def _body(bar):
    return bar['close'] - bar['open']


def _new_pattern(window, scale):
    first, prev, curr = window[-3:]
    prior = window[:-2]
    o, h, l, close = (curr[key] for key in ('open', 'high', 'low', 'close'))
    po, ph, pl, pc = (prev[key] for key in ('open', 'high', 'low', 'close'))
    span = h - l
    body, prior_body, first_body = map(_body, (curr, prev, first))
    tolerance = 3 * scale
    volume = sum(row['volume'] for row in prior)
    vwap = (sum((row['high'] + row['low'] + row['close']) / 3 * row['volume']
                for row in prior) / volume if volume else None)
    ema = window[0]['close']
    for row in window[1:-1]:
        ema += 2 / 21 * (row['close'] - ema)
    lower, upper = min(o, close) - l, h - max(o, close)
    for sign in (1, -1):
        bullish = sign == 1
        extreme = l if bullish else h
        prior_extreme = pl if bullish else ph
        key = 'low' if bullish else 'high'
        reference = min(sign * row[key] for row in prior)
        support = (min(sign * extreme, sign * prior_extreme) <= reference + tolerance
                   or vwap is not None and sign * (extreme - vwap) <= 0 < sign * (close - vwap))
        if support:
            stop = sign * min(sign * extreme, sign * prior_extreme) - sign * 2 * scale
            first_mid = (first['close'] + first['open']) / 2
            if (sign * first_body < 0 and abs(prior_body) <= abs(first_body) / 2
                    and sign * body >= span / 2 and sign * (close - first_mid) > 0
                    and sign * (pc - first_mid) < 0):
                stop = sign * min(sign * stop, sign * first[key] - 2 * scale)
                return ('MORNING_STAR' if bullish else 'EVENING_STAR'), sign, stop
            if (sign * prior_body < 0 < sign * body and sign * (o - pc) <= 0
                    and sign * ((po + pc) / 2) < sign * close < sign * po):
                return ('PIERCING_LINE' if bullish else 'DARK_CLOUD_COVER'), sign, stop
            if (sign * prior_body < 0 < sign * body and abs(extreme - prior_extreme) <= tolerance
                    and sign * (close - (po + pc) / 2) <= 0):
                return ('TWEEZER_BOTTOM' if bullish else 'TWEEZER_TOP'), sign, stop
            wick, other = (lower, upper) if bullish else (upper, lower)
            if abs(body) <= 0.05 * span and wick >= 0.7 * span and other <= 0.2 * span:
                return ('DRAGONFLY_DOJI' if bullish else 'GRAVESTONE_DOJI'), sign, extreme - sign * 2 * scale
            if bullish and upper >= 0.65 * span and lower <= 0.15 * span and body > 0:
                return 'INVERTED_HAMMER', sign, l - 2 * scale

        trend = sign * (close - ema) > 0 and (vwap is None or sign * (close - vwap) > 0)
        if trend and sign * body >= 0.9 * span:
            return ('BULLISH_MARUBOZU' if bullish else 'BEARISH_MARUBOZU'), sign, extreme - sign * 2 * scale
        if (trend and all(sign * _body(bar) > 0 for bar in (first, prev, curr))
                and sign * first['close'] < sign * pc < sign * close
                and all(abs(_body(bar)) >= 0.6 * (bar['high'] - bar['low']) for bar in (first, prev, curr))
                and all(min(a['open'], a['close']) <= b['open'] <= max(a['open'], a['close'])
                        for a, b in ((first, prev), (prev, curr)))):
            stop = sign * min(sign * row[key] for row in (first, prev, curr)) - sign * 2 * scale
            return ('THREE_WHITE_SOLDIERS' if bullish else 'THREE_BLACK_CROWS'), sign, stop
    return None


def scan_candlestick_signals(candles, *, symbol='NIFTY', quotes=None,
                             quote_path=None, expiry=None, now=None,
                             min_risk=None, max_risk=None):
    """Scan completed candles for high-probability price action candlestick setups.

    Requires completed candles sorted chronologically. Minimum 2.0 R:R target.
    """
    symbol = str(symbol).upper()
    if symbol not in ('NIFTY', 'SENSEX'):
        raise ValueError('Invalid symbol: expected NIFTY or SENSEX')
    
    scale = 1.0 if symbol == 'NIFTY' else 3.0
    min_risk = _positive(min_risk if min_risk is not None else 8.0 * scale, 'min_risk')
    max_risk = _positive(max_risk if max_risk is not None else 25.0 * scale, 'max_risk')
    
    quotes = list(quotes or [])
    signals = []
    
    parsed = []
    for c in candles:
        at = c.get('timestamp')
        if not at:
            continue
        at = datetime.fromisoformat(at) if isinstance(at, str) else at
        if at.tzinfo is None or (now is not None and at > now):
            continue
        o, h, l, cl = (_positive(c[k], k) for k in ('open', 'high', 'low', 'close'))
        v = _positive(c.get('volume', 0), 'volume', zero=True)
        if not l <= min(o, cl) <= max(o, cl) <= h:
            raise ValueError('Invalid OHLC range')
        parsed.append(dict(timestamp=at, open=o, high=h, low=l, close=cl, volume=v, raw=c))

    if len(parsed) < 5:
        return signals

    for i in range(4, len(parsed)):
        curr = parsed[i]
        prev = parsed[i-1]
        if curr['timestamp'].astimezone(IST).date() != parsed[i-4]['timestamp'].astimezone(IST).date():
            continue
        
        o, h, l, cl = curr['open'], curr['high'], curr['low'], curr['close']
        po, ph, pl, pcl = prev['open'], prev['high'], prev['low'], prev['close']
        
        body = abs(cl - o)
        span = h - l
        if span <= 0:
            continue
            
        upper_w = h - max(o, cl)
        lower_w = min(o, cl) - l
        
        pattern = None
        direction = None
        raw_sl = None
        
        extra = _new_pattern(parsed[max(0, i-20):i+1], scale)
        if extra:
            pattern, sign, raw_sl = extra
            direction = 'BULLISH' if sign > 0 else 'BEARISH'

        # 1. Bullish Hammer (Long lower wick rejecting local low)
        elif (lower_w >= 1.5 * body and lower_w >= 0.45 * span and
            cl >= l + 0.45 * span and upper_w <= 0.35 * span):
            local_min = min(parsed[j]['low'] for j in range(max(0, i-10), i))
            if l <= local_min + 3.0 * scale:
                pattern = 'HAMMER'
                direction = 'BULLISH'
                raw_sl = l - 2.0 * scale

        # 2. Bearish Shooting Star (Long upper wick rejecting local high)
        elif (upper_w >= 1.5 * body and upper_w >= 0.45 * span and
              cl <= l + 0.55 * span and lower_w <= 0.35 * span):
            local_max = max(parsed[j]['high'] for j in range(max(0, i-10), i))
            if h >= local_max - 3.0 * scale:
                pattern = 'SHOOTING_STAR'
                direction = 'BEARISH'
                raw_sl = h + 2.0 * scale

        # 3. Bullish Engulfing
        elif (cl > o and body >= 0.50 * span and cl >= po and cl > pcl and o <= pl + 4.0 * scale):
            local_min = min(parsed[j]['low'] for j in range(max(0, i-8), i))
            if l <= local_min + 3.0 * scale:
                pattern = 'BULLISH_ENGULFING'
                direction = 'BULLISH'
                raw_sl = min(l, pl) - 2.0 * scale

        # 4. Bearish Engulfing
        elif (cl < o and body >= 0.50 * span and cl <= po and cl < pcl and o >= ph - 4.0 * scale):
            local_max = max(parsed[j]['high'] for j in range(max(0, i-8), i))
            if h >= local_max - 3.0 * scale:
                pattern = 'BEARISH_ENGULFING'
                direction = 'BEARISH'
                raw_sl = max(h, ph) + 2.0 * scale

        if not pattern or not direction or raw_sl is None:
            continue

        if direction == 'BULLISH':
            risk = max(min_risk, min(max_risk, cl - raw_sl))
            sl = cl - risk
            target = cl + 2.0 * risk
        else:
            risk = max(min_risk, min(max_risk, raw_sl - cl))
            sl = cl + risk
            target = cl - 2.0 * risk

        signals.append(dict(
            strategy='CANDLESTICK',
            pattern=pattern,
            timestamp=curr['timestamp'].isoformat(),
            symbol=symbol,
            direction=direction,
            side='CE' if direction == 'BULLISH' else 'PE',
            entry=cl,
            stop_loss=round(sl, 2),
            target=round(target, 2),
            index_sl_pts=round(risk, 2),
            index_target_pts=round(2.0 * risk, 2),
            risk_reward=2.0,
            confirmation_source='CANDLESTICK_PRICE_ACTION',
            strikes=select_strikes(cl, direction, risk, 2.0 * risk, symbol=symbol,
                                  quotes=quotes, quote_path=quote_path, expiry=expiry, now=now),
            research_only=True,
            orders_enabled=False
        ))

    return signals
