"""Retests of the last opposing candle before a displacement break."""
from .independent_signals import build_signal, candle_sessions, displacement, swing_context


def scan_smc_ob(candles, *, symbol='NIFTY', quotes=None, now=None, interval_minutes=1):
    signals = []
    for bars in candle_sessions(candles, symbol, now):
        opposing = {}
        blocks = {}
        for index, bar, high, low in swing_context(bars):
            for origin, (sign, entry, stop) in list(blocks.items()):
                if sign * (bar['low'] if sign > 0 else bar['high']) <= sign * stop:
                    del blocks[origin]
                elif bar['low'] <= entry <= bar['high']:
                    del blocks[origin]
                    signal = build_signal('SMC_OB', f'{origin:%H%M}_ORDER_BLOCK_RETEST', bar['timestamp'],
                                          symbol, sign, entry, stop, entry + 2.5 * (entry - stop),
                                          interval_minutes, quotes)
                    if signal:
                        signals.append(signal)
            sign = displacement(bar, bars[index - 1], high, low) if index >= 3 else 0
            block = opposing.pop(sign, None)
            if block is not None:
                entry, stop = ((block['high'], block['low'] - 2) if sign > 0
                               else (block['low'], block['high'] + 2))
                blocks[block['timestamp']] = (sign, entry, stop)
            if bar['close'] != bar['open']:
                opposing[1 if bar['close'] < bar['open'] else -1] = bar
    return signals
