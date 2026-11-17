"""Snapshot OI walls and sustained price breaks for research only.

OI snapshots identify potential trapping, not verified changes in OI or
actual short covering. The nearest supplied unexpired contract is used;
weekly/monthly classification is not inferred from weekday calendars.
"""
from datetime import datetime, time, timedelta, date, timezone
from math import isfinite
from zoneinfo import ZoneInfo

from .option_strike_engine import select_strikes

IST = ZoneInfo('Asia/Kolkata')


def _number(value, name, zero=False):
    value = float(value)
    if not isfinite(value) or value < 0 or (not zero and value == 0):
        raise ValueError(f'Invalid {name}')
    return value


def _time(value):
    value = datetime.fromisoformat(value) if isinstance(value, str) else value
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError('Timezone-aware timestamp required')
    return value


def analyze_oi_chain(option_chain, *, symbol='NIFTY', now=None):
    """Sum supplied strike/side OI rows for one nearest active expiry.

    Rows without market metadata belong to the caller-selected symbol.
    Missing/zero OI falls back to option trade volume, labelled OPTION_VOLUME.
    Mixed snapshots are labelled MIXED_OI_OPTION_VOLUME; ratios and legacy
    *_oi fields then describe activity, not a pure open-interest measure.
    Explicit other-market rows and invalid OI rows are excluded. Duplicate
    rows are additive; callers must supply a single snapshot, not a tape.
    Ties choose the lower strike deterministically. PCR is None at zero CE OI.
    Bid/ask do not affect OI analysis; premium validity belongs to strike engine.
    """
    if symbol not in ('NIFTY', 'SENSEX'):
        raise ValueError('Invalid symbol')
    at = _time(now or datetime.now(timezone.utc)).astimezone(IST)
    rows = []
    for row in option_chain:
        try:
            if row.get('market', row.get('index', symbol)) != symbol or row['side'] not in ('CE', 'PE'):
                continue
            expiry = date.fromisoformat(row['expiry'])
            if expiry < at.date() or (expiry == at.date() and at.time() > time(15, 30)):
                continue
            strike = _number(row['strike'], 'strike')
            oi = _number(row.get('oi', 0), 'oi', zero=True)
            basis = 'OI'
            if oi == 0:
                oi = _number(row.get('volume', 0), 'option volume', zero=True)
                basis = 'OPTION_VOLUME'
            rows.append((expiry, row['side'], strike, oi, basis))
        except (AttributeError, KeyError, TypeError, ValueError, OverflowError):
            continue
    expiry = min((r[0] for r in rows), default=None)
    totals = {'CE': {}, 'PE': {}}
    sources = set()
    for exp, side, strike, oi, basis in rows:
        if exp == expiry:
            totals[side][strike] = totals[side].get(strike, 0.)+oi
            if oi > 0:
                sources.add(basis)
    calls, puts = sum(totals['CE'].values()), sum(totals['PE'].values())
    def wall(side):
        positive = [s for s, oi in totals[side].items() if oi > 0]
        return min(positive, key=lambda s: (-totals[side][s], s)) if positive else None
    return dict(expiry=expiry.isoformat() if expiry else None,
                activity_basis=(next(iter(sources)) if len(sources) == 1 else
                                'MIXED_OI_OPTION_VOLUME' if sources else 'UNAVAILABLE'),
                max_call_oi_strike=wall('CE'), max_put_oi_strike=wall('PE'),
                total_call_oi=calls, total_put_oi=puts, pcr_oi=puts/calls if calls else None,
                strike_oi=totals, research_only=True, orders_enabled=False)


def evaluate_oi_trap(spot, candles, option_chain, *, symbol='NIFTY',
                     interval_minutes=5, sustain_minutes=15, stop_buffer=12,
                     now=None, quotes=None, quote_path=None):
    """Evaluate current spot against a single OI snapshot and completed bars.

    Bar timestamps denote close. Require an observed crossing followed by
    >=15 minutes of consecutive closes outside the wall; all bars after the
    first crossing must keep their entire range outside. Only current IST
    session bars qualify; latest bar must be <=one interval old. A snapshot
    wall is held fixed throughout this retrospective confirmation window.
    Stop buffer is 10..15 points; SENSEX distances scale by 3. Reject total
    risk >30 scaled points instead of moving the stop inside the wall.
    Missing quote provenance leaves premium prices unavailable.
    """
    spot = _number(spot, 'spot')
    if interval_minutes not in (1, 5) or sustain_minutes < 15 or sustain_minutes % interval_minutes:
        raise ValueError('Invalid confirmation interval')
    buffer = _number(stop_buffer, 'stop_buffer')
    if not 10 <= buffer <= 15:
        raise ValueError('stop_buffer must be 10..15')
    at = _time(now or datetime.now(timezone.utc))
    chain = list(option_chain)
    analysis = analyze_oi_chain(chain, symbol=symbol, now=at)
    result = dict(**analysis, status='NO_BREAKOUT', signals=[])
    bars, last = [], None
    step = timedelta(minutes=interval_minutes)
    for row in candles:
        t = _time(row['timestamp'])
        if last is not None and t <= last:
            raise ValueError('Timestamps must strictly increase')
        last = t
        if row.get('completed', True) is not True or row.get('closed', True) is not True:
            raise ValueError('Completed candles required')
        o, h, l, c = (_number(row[k], k) for k in ('open', 'high', 'low', 'close'))
        _number(row.get('volume', 0), 'volume', zero=True)
        if not l <= min(o, c) <= max(o, c) <= h or t > at:
            raise ValueError('Invalid OHLC or future candle')
        local = t.astimezone(IST)
        if local.date() == at.astimezone(IST).date() and time(9, 15) < local.time() <= time(15, 30):
            bars.append((t, h, l, c))
    call, put = analysis['max_call_oi_strike'], analysis['max_put_oi_strike']
    if call is None or put is None:
        return {**result, 'status': 'OI_UNAVAILABLE'}
    if put >= call:
        return {**result, 'status': 'AMBIGUOUS_WALLS'}
    if not time(9, 15) < at.astimezone(IST).time() <= time(15, 30):
        return {**result, 'status': 'OUTSIDE_SESSION'}
    if not bars or at-bars[-1][0] > step:
        return {**result, 'status': 'STALE_OR_MISSING_CANDLES'}
    bullish = spot > call
    if not bullish and spot >= put:
        return result
    wall = call if bullish else put
    beyond = lambda price: price > wall if bullish else price < wall
    # Find the whole current run, retaining the preceding observation for crossing.
    start = len(bars)-1
    if not beyond(bars[start][3]):
        return {**result, 'status': 'AWAITING_CONFIRMATION'}
    while start > 0 and beyond(bars[start-1][3]):
        start -= 1
    run = bars[start:]
    if (start == 0 or run[-1][0]-run[0][0] < timedelta(minutes=sustain_minutes)
        or any(bars[i][0]-bars[i-1][0] != step for i in range(start, len(bars)))
        or any(not beyond(b[2] if bullish else b[1]) for b in run[1:])):
        return {**result, 'status': 'AWAITING_CONFIRMATION'}
    scale = 1 if symbol == 'NIFTY' else 3
    stop = wall-buffer*scale if bullish else wall+buffer*scale
    risk = spot-stop if bullish else stop-spot
    if risk > 30*scale:
        return {**result, 'status': 'RISK_TOO_LARGE'}
    reward = 2*risk
    signal = dict(strategy='OI_TRAP', direction='BULLISH' if bullish else 'BEARISH',
                  setup='POTENTIAL_SHORT_COVERING' if bullish else 'POTENTIAL_LONG_UNWINDING',
                  side='CE' if bullish else 'PE', symbol=symbol, timestamp=at.isoformat(),
                  confirmation_started_at=run[0][0].isoformat(), wall=wall,
                  entry=spot, stop_loss=stop, target=spot+reward if bullish else spot-reward,
                  index_sl_pts=risk, index_target_pts=reward, risk_reward=2.,
                  activity_basis=analysis['activity_basis'],
                  strikes=select_strikes(spot, 'BULLISH' if bullish else 'BEARISH', risk, reward,
                                        symbol=symbol, quotes=chain if quotes is None else quotes,
                                        quote_path=quote_path, expiry=analysis['expiry'], now=at),
                  research_only=True, orders_enabled=False, oi_unwinding_verified=False)
    return {**result, 'status': 'SIGNAL', 'signals': [signal]}
