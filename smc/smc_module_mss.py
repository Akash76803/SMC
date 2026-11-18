"""Five-minute market structure breaks confirmed by displacement."""
from .independent_signals import build_signal, candle_sessions, displacement, resample, swing_context


def scan_smc_mss(candles, *, symbol='NIFTY', quotes=None, now=None, interval_minutes=5):
    signals = []
    for session in candle_sessions(candles, symbol, now):
        bars = resample(session, interval_minutes, 5)
        for index, bar, high, low in swing_context(bars):
            if index < 3:
                continue
            sign = displacement(bar, bars[index - 1], high, low)
            if sign:
                entry = bar['close']
                stop = bar['low'] if sign > 0 else bar['high']
                signal = build_signal('SMC_MSS', 'DISPLACEMENT_BREAK', bar['timestamp'],
                                      symbol, sign, entry, stop, entry + 2 * (entry - stop), 5, quotes)
                if signal:
                    signals.append(signal)
    return signals
