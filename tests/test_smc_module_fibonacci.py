from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo
from smc.smc_module_fibonacci import scan_smc_fibonacci

IST = ZoneInfo('Asia/Kolkata')


def make_candle(dt, o, h, l, c, vol=1000):
    return {
        'symbol': 'NIFTY',
        'timestamp': dt.isoformat(),
        'open': o,
        'high': h,
        'low': l,
        'close': c,
        'volume': vol
    }


def test_fibonacci_ote_bullish_discount_setup():
    start = datetime(2026, 11, 18, 9, 16, tzinfo=IST)
    candles = [
        # Establish swing low at 25000
        make_candle(start, 25020, 25025, 25010, 25015),
        make_candle(start + timedelta(minutes=1), 25015, 25015, 25000, 25005), # low pivot
        make_candle(start + timedelta(minutes=2), 25005, 25030, 25005, 25025),
        make_candle(start + timedelta(minutes=3), 25025, 25050, 25020, 25045),
        # Establish swing high at 25100
        make_candle(start + timedelta(minutes=4), 25045, 25100, 25040, 25095), # high pivot
        make_candle(start + timedelta(minutes=5), 25095, 25095, 25070, 25075),
        make_candle(start + timedelta(minutes=6), 25075, 25075, 25050, 25055),
        # Retracement into 61.8% - 78.6% (Range = 100, Fib 61.8% = 25038.2, Fib 78.6% = 25021.4)
        make_candle(start + timedelta(minutes=7), 25040, 25045, 25025, 25030), # In OTE zone!
    ]
    signals = scan_smc_fibonacci(candles, symbol='NIFTY')
    assert len(signals) == 1
    sig = signals[0]
    assert sig['direction'] == 'BULLISH'
    assert sig['strategy'] == 'SMC_FIB'
    assert 'OTE' in sig['pattern_or_trigger']
    assert sig['stop_loss'] == 24998.0  # 25000 - 2
    assert sig['target'] >= 25100.0     # Swing high or ICT expansion target
    assert sig['risk_reward'] >= 2.0


def test_fibonacci_ote_bearish_premium_setup():
    start = datetime(2026, 11, 18, 9, 16, tzinfo=IST)
    candles = [
        # Establish swing high at 25100
        make_candle(start, 25080, 25090, 25075, 25085),
        make_candle(start + timedelta(minutes=1), 25085, 25100, 25080, 25095), # high pivot
        make_candle(start + timedelta(minutes=2), 25095, 25095, 25070, 25075),
        make_candle(start + timedelta(minutes=3), 25075, 25080, 25050, 25055),
        # Establish swing low at 25000
        make_candle(start + timedelta(minutes=4), 25055, 25060, 25000, 25005), # low pivot
        make_candle(start + timedelta(minutes=5), 25005, 25030, 25005, 25025),
        make_candle(start + timedelta(minutes=6), 25025, 25050, 25020, 25045),
        # Retracement into 61.8% - 78.6% Premium zone (25061.8 - 25078.6)
        make_candle(start + timedelta(minutes=7), 25060, 25075, 25058, 25070), # In OTE zone!
    ]
    signals = scan_smc_fibonacci(candles, symbol='NIFTY')
    assert len(signals) == 1
    sig = signals[0]
    assert sig['direction'] == 'BEARISH'
    assert sig['strategy'] == 'SMC_FIB'
    assert 'OTE' in sig['pattern_or_trigger']
    assert sig['stop_loss'] == 25102.0  # 25100 + 2
    assert sig['target'] <= 25000.0
    assert sig['risk_reward'] >= 2.0

