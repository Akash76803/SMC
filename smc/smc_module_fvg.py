"""First midpoint retests of three-candle fair value gaps."""
from datetime import timedelta

from .independent_signals import build_signal, candle_sessions


def scan_smc_fvg(candles, *, symbol='NIFTY', quotes=None, now=None, interval_minutes=1):
    signals = []
    for bars in candle_sessions(candles, symbol, now):
        gaps = []
        for index, bar in enumerate(bars):
            resting = []
            for origin, sign, entry, stop in gaps:
                if sign * (bar['low'] if sign > 0 else bar['high']) <= sign * stop:
                    continue
                if bar['low'] <= entry <= bar['high']:
                    signal = build_signal('SMC_FVG', f'{origin:%H%M}_FVG_MIDPOINT', bar['timestamp'],
                                          symbol, sign, entry, stop, entry + 2 * (entry - stop),
                                          interval_minutes, quotes)
                    if signal:
                        signals.append(signal)
                else:
                    resting.append((origin, sign, entry, stop))
            gaps = resting
            if index < 2:
                continue
            first = bars[index - 2]
            if bar['timestamp'] - first['timestamp'] != timedelta(minutes=2 * interval_minutes):
                continue
            if first['high'] < bar['low']:
                gaps.append((bar['timestamp'], 1, (first['high'] + bar['low']) / 2, first['low'] - 2))
            elif first['low'] > bar['high']:
                gaps.append((bar['timestamp'], -1, (first['low'] + bar['high']) / 2, first['high'] + 2))
    return signals
