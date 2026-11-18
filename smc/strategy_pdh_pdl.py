"""Previous-session high/low acceptance and rejection research signals."""
from itertools import groupby

from .independent_signals import build_signal, resample, session_bars


def scan_pdh_pdl(candles, *, symbol='NIFTY', quotes=None, now=None,
                 interval_minutes=15, trade_plans=None):
    """Scan closed bars. Optionally collect secondary targets and ATR by setup ID."""
    bars = session_bars(candles, symbol, now)
    sessions = [(day, list(rows)) for day, rows in groupby(bars, lambda b: b['timestamp'].date())]
    signals = []
    for (_, previous), (_, current) in zip(sessions, sessions[1:]):
        pdh = max(bar['high'] for bar in previous)
        pdl = min(bar['low'] for bar in previous)
        midpoint = (pdh + pdl) / 2
        pending = None
        atr = None
        true_ranges = []
        trailing = []
        previous_close = previous[-1]['close']
        confirmations = {bar['timestamp']: bar for bar in resample(current, interval_minutes, 15)}
        for source in current:
            at, high, low, close = (source[key] for key in ('timestamp', 'high', 'low', 'close'))
            for sign, plan in trailing[:]:
                if sign * (low if sign > 0 else high) <= sign * plan['trailing_stop']:
                    plan['completed_at'] = at.isoformat()
                    plan['outcome'] = 'STOP_TOUCHED'
                    trailing.remove((sign, plan))
                elif sign * (high if sign > 0 else low) >= sign * plan['target_2']:
                    plan['completed_at'] = at.isoformat()
                    plan['outcome'] = 'TARGET_2_TOUCHED'
                    trailing.remove((sign, plan))

            if pending:
                sign, entry, stop, pattern = pending
                # With OHLC alone, a bar touching both levels has ambiguous ordering.
                broken = high > entry if sign > 0 else low < entry
                invalid = low <= stop if sign > 0 else high >= stop
                if broken and not invalid:
                    fill = max(entry, source['open']) if sign > 0 else min(entry, source['open'])
                    signal = build_signal('PDH_PDL', pattern, at, symbol, sign, fill, stop,
                                          fill + 2 * (fill - stop), interval_minutes, quotes)
                    if signal:
                        signals.append(signal)
                if broken or invalid:
                    pending = None

            bar = confirmations.get(at)
            if bar is None:
                continue
            high, low, close = (bar[key] for key in ('high', 'low', 'close'))
            tr = max(high - low, abs(high - previous_close), abs(low - previous_close))
            previous_close = close
            if atr is None:
                true_ranges.append(tr)
                if len(true_ranges) == 10:
                    atr = sum(true_ranges) / 10
            else:
                atr = (9 * atr + tr) / 10
            if atr is not None:
                for sign, plan in trailing:
                    plan['trailing_distance'] = 2 * atr
                    plan['trailing_stop'] = sign * max(sign * plan['trailing_stop'], sign * close - 2 * atr)

            if low > pdh and pending is None:
                pending = (1, high, low, 'PDH_ACCEPTANCE')
            elif high < pdl and pending is None:
                pending = (-1, low, high, 'PDL_ACCEPTANCE')
            elif pdl < close < pdh:
                for sign, swept, stop, other, pattern in (
                    (1, low < pdl, low, pdh, 'PDL_REJECTION'),
                    (-1, high > pdh, high, pdl, 'PDH_REJECTION'),
                ):
                    if not swept:
                        continue
                    signal = build_signal('PDH_PDL', pattern, at, symbol, sign, close, stop,
                                          midpoint, 15, quotes)
                    if signal:
                        signals.append(signal)
                        if trade_plans is not None:
                            trail = stop if atr is None else sign * max(sign * stop, sign * close - 2 * atr)
                            plan = dict(target_2=other, atr_period=10, atr_multiplier=2,
                                        trailing_distance=None if atr is None else 2 * atr,
                                        trailing_stop=trail)
                            trade_plans[signal['setup_id']] = plan
                            trailing.append((sign, plan))
    return signals
