"""Optimal Trade Entry (OTE) and Fibonacci 61.8%–78.6% Golden Pocket research engine.

Evaluates impulsive dealing ranges:
1. Bullish Leg: Swing Low -> Swing High impulse. Pullback into 61.8%–78.6% Discount zone.
   Entry at OTE with Stop-Loss below Swing Low, Target at Swing High (>= 1:2 R:R).
2. Bearish Leg: Swing High -> Swing Low impulse. Pullback into 61.8%–78.6% Premium zone.
   Entry at OTE with Stop-Loss above Swing High, Target at Swing Low (>= 1:2 R:R).

No real brokerage operations; decision and signal audit only.
"""
from __future__ import annotations
from .independent_signals import build_signal, candle_sessions, swing_context


def scan_smc_fibonacci(candles, *, symbol='NIFTY', quotes=None, now=None, interval_minutes=1):
    symbol = str(symbol).upper()
    scale = 1.0 if symbol == 'NIFTY' else 3.0
    signals = []
    
    for bars in candle_sessions(candles, symbol, now):
        # Track active impulse dealing ranges
        active_ranges = []
        confirmed_swings = []
        
        last_high = last_low = None
        for index, bar, high, low in swing_context(bars):
            # Record newly established swing levels
            if high is not None and high != last_high:
                last_high = high
                confirmed_swings.append(('HIGH', high, bar['timestamp']))
            if low is not None and low != last_low:
                last_low = low
                confirmed_swings.append(('LOW', low, bar['timestamp']))
            
            # Form impulsive dealing range when we have both recent low and high
            if len(confirmed_swings) >= 2:
                s1, s2 = confirmed_swings[-2], confirmed_swings[-1]
                # Bullish impulse leg: Low followed by High
                if s1[0] == 'LOW' and s2[0] == 'HIGH' and s2[1] > s1[1] + 15.0 * scale:
                    swing_l, swing_h = s1[1], s2[1]
                    rng = swing_h - swing_l
                    fib_618 = swing_h - 0.618 * rng
                    fib_786 = swing_h - 0.786 * rng
                    stop = swing_l - 2.0 * scale
                    target = swing_h
                    # Check if already in active ranges
                    key = (1, s1[2], s2[2])
                    if not any(r[0] == key for r in active_ranges):
                        active_ranges.append((key, 1, fib_786, fib_618, stop, target, s2[2]))
                
                # Bearish impulse leg: High followed by Low
                elif s1[0] == 'HIGH' and s2[0] == 'LOW' and s1[1] > s2[1] + 15.0 * scale:
                    swing_h, swing_l = s1[1], s2[1]
                    rng = swing_h - swing_l
                    fib_618 = swing_l + 0.618 * rng
                    fib_786 = swing_l + 0.786 * rng
                    stop = swing_h + 2.0 * scale
                    target = swing_l
                    key = (-1, s1[2], s2[2])
                    if not any(r[0] == key for r in active_ranges):
                        active_ranges.append((key, -1, fib_618, fib_786, stop, target, s2[2]))

            # Evaluate active ranges for price testing OTE Golden Zone
            for r in list(active_ranges):
                key, sign, zone_low, zone_high, stop, target, created_at = r
                if bar['timestamp'] <= created_at:
                    continue
                
                # Invalidation: price breaks stop level
                if (sign == 1 and bar['low'] <= stop) or (sign == -1 and bar['high'] >= stop):
                    active_ranges.remove(r)
                    continue
                
                # Trigger: price enters and reacts in 61.8%–78.6% Golden Pocket
                if zone_low <= bar['close'] <= zone_high or (bar['low'] <= zone_high and bar['high'] >= zone_low):
                    active_ranges.remove(r)
                    entry = bar['close']
                    risk = abs(entry - stop)
                    if risk <= 0:
                        continue
                    # Target at least swing high/low or ICT 2.0+ R:R extension
                    if sign == 1:
                        final_target = max(target, entry + 2.0 * risk)
                    else:
                        final_target = min(target, entry - 2.0 * risk)

                    pattern = 'BULLISH_FIB_OTE_DISCOUNT' if sign == 1 else 'BEARISH_FIB_OTE_PREMIUM'
                    sig = build_signal('SMC_FIB', pattern, bar['timestamp'], symbol,
                                       sign, entry, stop, final_target, interval_minutes, quotes)
                    if sig:
                        signals.append(sig)

    return signals
