"""Liquidity sweep and close-back-inside signals."""
from .independent_signals import build_signal, candle_sessions, swing_context


def scan_smc_sweep(candles, *, symbol='NIFTY', quotes=None, now=None, interval_minutes=1):
    signals = []
    pdh = pdl = None
    for bars in candle_sessions(candles, symbol, now):
        for _, bar, swing_high, swing_low in swing_context(bars):
            at, o, h, l, c = (bar[key] for key in ('timestamp', 'open', 'high', 'low', 'close'))
            span = h - l
            if not span:
                continue
            for sign, wick, extreme, levels in (
                (1, min(o, c) - l, l, ((pdl, 'PDL'), (swing_low, 'SWING_LOW'))),
                (-1, h - max(o, c), h, ((pdh, 'PDH'), (swing_high, 'SWING_HIGH'))),
            ):
                if wick < span / 2:
                    continue
                for level, label in levels:
                    if level is None or not sign * extreme < sign * level < sign * c:
                        continue
                    stop = extreme - sign * 2
                    signal = build_signal('SMC_SWEEP', f'TURTLE_SOUP_{label}', at, symbol,
                                          sign, c, stop, c + 2 * (c - stop),
                                          interval_minutes, quotes)
                    if signal:
                        signals.append(signal)
                    break
        pdh = max(bar['high'] for bar in bars)
        pdl = min(bar['low'] for bar in bars)
    return signals
