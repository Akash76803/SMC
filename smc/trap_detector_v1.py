"""Causal 5-minute trap and breakout observations from completed candles."""

from datetime import time, timedelta
from math import ulp

from .independent_signals import build_signal, candle_sessions, displacement, resample, swing_context


TICK_SIZE = 0.05
NO_TRADE = {'candidate_type': 'NO_TRADE', 'label': 0}
LABELS = {'TRUE_UP': 1, 'TRUE_DOWN': 2, 'BULL_TRAP': 3, 'BEAR_TRAP': 4}


def compute_atr_5m(candles, period=14):
    if period < 1:
        raise ValueError('ATR period must be positive')
    window = candles[-(period + 1):]
    if len(window) <= period:
        return None
    return sum(max(bar['high'] - bar['low'], abs(bar['high'] - prev['close']),
                   abs(bar['low'] - prev['close']))
               for prev, bar in zip(window, window[1:])) / period


def detect_candidate_events(candles, levels, atr_buffer):
    """Find fresh penetrations of named support and resistance levels."""
    events = []
    for index, bar in enumerate(candles):
        for name, level in levels.items():
            upside = name.endswith(('_H', 'DH'))
            sign = 1 if upside else -1
            edge = 'high' if upside else 'low'
            threshold = sign * level + atr_buffer
            if sign * bar[edge] > threshold and (index == 0 or
                    sign * candles[index - 1][edge] <= threshold):
                events.append(dict(name=name, level=level, sign=sign, index=index,
                                   extreme=bar[edge]))
    return events


def evaluate_reclaim(event, bars, k_bars=3):
    """Return the first close back inside, counting the sweep bar as bar one."""
    if k_bars not in (1, 2, 3):
        raise ValueError('Reclaim window must be 1, 2 or 3 bars')
    start = event['index']
    for index in range(start, min(start + k_bars, len(bars))):
        if event['sign'] * (bars[index]['close'] - event['level']) < 0:
            return index
    return None


def evaluate_choch(bars, swing_pivots):
    """Return the displaced break direction against frozen pre-sweep pivots."""
    if len(bars) < 2:
        return 0
    high, low = swing_pivots
    return displacement(bars[-1], bars[-2], high, low)


def _rejection(bar, sign, level):
    return (bar['low'] <= level if sign > 0 else bar['high'] >= level) and (
        sign * (bar['close'] - level) > 0 and sign * (bar['close'] - bar['open']) > 0)


def _signal(event, bar, levels, symbol, buffer, quotes):
    sign = -event['sign']
    entry = bar['close']
    stop = event['extreme'] - sign * buffer
    required = 2 * sign * (entry - stop)
    targets = sorted((price for name, price in levels.items()
                      if name.endswith(('_H', 'DH')) == (sign > 0)
                      and sign * (price - entry) > 0), key=lambda price: sign * price)
    if not targets or sign * (targets[0] - entry) + ulp(entry) < required:
        return None
    pattern = 'BEAR_TRAP' if sign > 0 else 'BULL_TRAP'
    signal = build_signal('TRAP_DETECTOR', pattern, bar['timestamp'], symbol, sign,
                          entry, stop, targets[0], 5, quotes)
    if signal is not None:
        signal.update(_observation(pattern, bar, event, symbol, 'CONFIRMED_RETEST'),
                      spot_entry=entry, spot_stop=stop, spot_target=targets[0],
                      planned_rr=signal['risk_reward'], status='ACTIVE',
                      counter_trend_exhaustion=event['immediate_reclaim'])
    return signal


def _observation(pattern, bar, event, symbol, stage):
    return dict(symbol=symbol, timeframe='5m', signal_stage=stage,
                candidate_type=pattern, label=LABELS[pattern],
                decision_time_ist=bar['timestamp'].isoformat(), level=event['level'],
                level_name=event['name'], model_version='trap-v1.0', probability=None)


def scan_traps_and_breakouts(candles, symbol, quotes=None, now=None, *,
                            interval_minutes=5, radar=None):
    """Return confirmed reversals. Report held breakouts through the optional radar."""
    signals = []
    prior_levels = {}
    atr_history = []
    if radar is not None:
        radar.update(NO_TRADE)
    for session in candle_sessions(candles, symbol, now):
        bars = resample(session, interval_minutes, 5)
        bars_15m = resample(session, interval_minutes, 15)
        swings_15m = iter(swing_context(bars_15m))
        next_swing = next(swings_15m, None)
        levels = dict(prior_levels)
        candidates = {}
        latest = NO_TRADE
        for index, bar, high, low in swing_context(bars):
            if latest['candidate_type'] in ('TRUE_UP', 'TRUE_DOWN'):
                breakout_sign = 1 if latest['candidate_type'] == 'TRUE_UP' else -1
                if breakout_sign * (bar['close'] - latest['level']) <= 0:
                    latest = NO_TRADE
            elif 'setup_id' in latest:
                bullish = latest['direction'] == 'BULLISH'
                stopped = bar['low'] <= latest['stop_loss'] if bullish else bar['high'] >= latest['stop_loss']
                reached = bar['high'] >= latest['target'] if bullish else bar['low'] <= latest['target']
                if stopped or reached:
                    latest = NO_TRADE
            if index and bar['timestamp'] - bars[index - 1]['timestamp'] != timedelta(minutes=5):
                candidates.clear()
            if bars_15m and bars_15m[0]['timestamp'].time() == time(9, 30) and (
                    bars_15m[0]['timestamp'] < bar['timestamp']):
                levels.update(ORB_H=bars_15m[0]['high'], ORB_L=bars_15m[0]['low'])
            while next_swing is not None and next_swing[1]['timestamp'] <= bar['timestamp']:
                _, _, swing_high, swing_low = next_swing
                if swing_high is not None:
                    levels['SWING_H'] = swing_high
                if swing_low is not None:
                    levels['SWING_L'] = swing_low
                next_swing = next(swings_15m, None)

            atr = compute_atr_5m(atr_history)
            atr_history.append(bar)
            atr_history = atr_history[-15:]
            if atr is None:
                continue
            buffer = max(0.05 * atr, 2 * TICK_SIZE)
            for event in detect_candidate_events(bars[max(0, index - 1):index + 1], levels, buffer):
                if event['index'] != min(index, 1) or event['name'] in candidates:
                    continue
                event.update(index=index, pivots=(high, low), buffer=buffer,
                             reclaim=None, choch=None, fvg=None)
                candidates[event['name']] = event

            confirmed = set()
            for name, event in list(candidates.items()):
                sign = event['sign']
                edge = bar['high'] if sign > 0 else bar['low']
                if event['reclaim'] is None:
                    event['extreme'] = sign * max(sign * edge, sign * event['extreme'])
                    event['reclaim'] = evaluate_reclaim(event, bars[:index + 1])
                    age = index - event['index']
                    if event['reclaim'] is None:
                        if age == 3:
                            closes = bars[event['index']:index + 1]
                            if all(sign * (row['close'] - event['level']) > 0 for row in closes):
                                pattern = 'TRUE_UP' if sign > 0 else 'TRUE_DOWN'
                                latest = _observation(pattern, bar, event, symbol, 'CONFIRMED_HOLD')
                            del candidates[name]
                        continue
                    event['immediate_reclaim'] = age == 0
                elif (sign * edge >= sign * event['extreme'] + event['buffer']
                      or sign * (bar['close'] - event['level']) >= 0):
                    del candidates[name]
                    continue

                if event['choch'] is None:
                    if evaluate_choch(bars[max(0, index - 1):index + 1], event['pivots']) == -sign:
                        event['choch'] = index
                    continue

                if index == event['choch'] + 1 and index >= 2:
                    before = bars[index - 2]
                    lower, upper = ((bar['high'], before['low']) if sign > 0 else
                                    (before['high'], bar['low']))
                    if lower < upper:
                        event['fvg'] = (lower + upper) / 2
                swing_high, swing_low = event['pivots']
                broken_pivot = swing_low if sign > 0 else swing_high
                retest_levels = (event['level'], broken_pivot, event['fvg'])
                if not any(_rejection(bar, -sign, price) for price in retest_levels if price is not None):
                    continue
                signal = _signal(event, bar, levels, symbol, event['buffer'], quotes)
                if signal is not None and signal['setup_id'] not in confirmed:
                    signals.append(signal)
                    confirmed.add(signal['setup_id'])
                    latest = signal
                del candidates[name]

        if radar is not None:
            radar.clear()
            radar.update(latest if 'setup_id' not in latest else {
                key: latest[key] for key in ('candidate_type', 'label', 'level', 'level_name',
                                            'decision_time_ist', 'signal_stage', 'setup_id')})
        prior_levels = {'PDH': max(bar['high'] for bar in session),
                        'PDL': min(bar['low'] for bar in session)}
    return signals
