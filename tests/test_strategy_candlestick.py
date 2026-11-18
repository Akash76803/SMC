from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import pytest

from smc.strategy_candlestick import scan_candlestick_signals

IST = ZoneInfo('Asia/Kolkata')
BASE_TIME = datetime(2026, 11, 18, 10, 0, tzinfo=IST)


def _bar(minute_offset, o, h, l, c, v=100):
    ts = (BASE_TIME + timedelta(minutes=minute_offset)).isoformat()
    return dict(timestamp=ts, open=float(o), high=float(h), low=float(l), close=float(c), volume=v)


def test_bullish_hammer_signal():
    # Downward progression followed by a hammer sweeping local low
    bars = [
        _bar(0, 25200, 25205, 25195, 25198),
        _bar(1, 25198, 25200, 25188, 25190),
        _bar(2, 25190, 25192, 25180, 25182),
        _bar(3, 25182, 25185, 25175, 25176),
        # Hammer: sweeps to 25165, closes at 25175 with long lower wick
        _bar(4, 25174, 25176, 25165, 25175),
    ]
    signals = scan_candlestick_signals(bars, symbol='NIFTY')
    assert len(signals) == 1
    sig = signals[0]
    assert sig['direction'] == 'BULLISH'
    assert sig['pattern'] == 'HAMMER'
    assert sig['entry'] == 25175.0
    assert sig['stop_loss'] == 25163.0  # low 25165 - 2
    assert sig['target'] == 25175.0 + 2.0 * sig['index_sl_pts']
    assert sig['risk_reward'] == 2.0
    assert 'ATM' in sig['strikes']


def test_bearish_shooting_star_signal():
    # Upward progression followed by a shooting star rejecting local high
    bars = [
        _bar(0, 25150, 25160, 25148, 25158),
        _bar(1, 25158, 25170, 25155, 25168),
        _bar(2, 25168, 25180, 25165, 25178),
        _bar(3, 25178, 25190, 25175, 25188),
        # Shooting star: spikes to 25205, closes at 25189 with long upper wick
        _bar(4, 25190, 25205, 25188, 25189),
    ]
    signals = scan_candlestick_signals(bars, symbol='NIFTY')
    assert len(signals) == 1
    sig = signals[0]
    assert sig['direction'] == 'BEARISH'
    assert sig['pattern'] == 'SHOOTING_STAR'
    assert sig['entry'] == 25189.0
    assert sig['stop_loss'] == 25207.0  # high 25205 + 2
    assert sig['target'] == 25189.0 - 2.0 * sig['index_sl_pts']


def test_bullish_engulfing_signal():
    bars = [
        _bar(0, 25200, 25205, 25195, 25198),
        _bar(1, 25198, 25200, 25188, 25190),
        _bar(2, 25190, 25192, 25180, 25182),
        # Red bar
        _bar(3, 25182, 25185, 25174, 25175),
        # Big green engulfing bar
        _bar(4, 25174, 25188, 25173, 25187),
    ]
    signals = scan_candlestick_signals(bars, symbol='NIFTY')
    assert len(signals) == 1
    sig = signals[0]
    assert sig['direction'] == 'BULLISH'
    assert sig['pattern'] == 'BULLISH_ENGULFING'
    assert sig['entry'] == 25187.0
    assert sig['stop_loss'] == 25171.0


def test_bearish_engulfing_signal():
    bars = [
        _bar(0, 25150, 25160, 25148, 25158),
        _bar(1, 25158, 25170, 25155, 25168),
        _bar(2, 25168, 25180, 25165, 25178),
        # Green bar
        _bar(3, 25178, 25188, 25176, 25187),
        # Big red engulfing bar
        _bar(4, 25187, 25189, 25172, 25173),
    ]
    signals = scan_candlestick_signals(bars, symbol='NIFTY')
    assert len(signals) == 1
    sig = signals[0]
    assert sig['direction'] == 'BEARISH'
    assert sig['pattern'] == 'BEARISH_ENGULFING'
    assert sig['entry'] == 25173.0
    assert sig['stop_loss'] == 25191.0

