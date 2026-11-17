from datetime import datetime, timezone

import pytest

from smc.strategy_snr_vwap import calculate_levels, scan_snr_signals


def candle(**changes):
    return dict(dict(timestamp='2026-11-17T09:20:00+05:30', open=25408,
                     high=25412, low=25400, close=25410, volume=100), **changes)


def test_cumulative_typical_price_vwap():
    bars = [candle(), candle(timestamp='2026-11-17T09:25:00+05:30',
                             high=25415, volume=300)]
    levels = calculate_levels(bars, {'PDH': 25500, 'PDL': 25300, 'PDC': 25400})
    expected = (((25412+25400+25410)/3)*100 + ((25415+25400+25410)/3)*300)/400
    assert levels[-1]['vwap'] == pytest.approx(expected)
    assert levels[-1]['P'] == 25400
    assert levels[-1]['S1'] == 25300
    assert levels[-1]['R1'] == 25500
    assert levels[-1]['S2'] == 25200
    assert levels[-1]['R2'] == 25600
    assert levels[-1]['session_high'] == 25415
    assert levels[-1]['session_low'] == 25400
    assert levels[-1]['day_open'] == 25408


def test_bullish_support_and_strikes_with_real_quote():
    quote = dict(market='NIFTY', side='CE', strike=25400, expiry='2026-11-17',
                 quote_at='2026-11-17T03:50:00+00:00', bid=99.95, ask=100,
                 research_only=True, orders_enabled=False)
    result = scan_snr_signals([candle()], {'PDL': 25400, 'PDH': 25450},
                              quotes=[quote], now=datetime(2026, 11, 17, 3, 50, tzinfo=timezone.utc))
    signal, = result
    assert signal['direction'] == 'BULLISH'
    assert signal['side'] == 'CE'
    assert 'PDL' in signal['tested_levels']
    assert signal['stop_loss'] == 25398
    assert signal['target'] == 25450
    assert set(signal['strikes']) == {'ATM', 'ITM', 'OTM'}
    assert signal['strikes']['ATM']['premium_entry'] == 100
    assert signal['strikes']['ATM']['premium_sl'] == 94
    assert signal['strikes']['ATM']['premium_target'] == 120
    assert signal['orders_enabled'] is False


def test_bearish_resistance():
    signal, = scan_snr_signals([candle(open=25402, close=25400, low=25398, high=25410)],
                               {'PDH': 25410, 'PDL': 25360})
    assert signal['side'] == 'PE'
    assert signal['stop_loss'] == 25412
    assert signal['target'] == 25360
    assert signal['strikes']['ITM']['strike'] == 25450


def test_vwap_rejection():
    # Prior bar fixes a nearby VWAP without introducing a close overhead level.
    bars = [candle(open=25400, close=25400, high=25450, low=25350, volume=10000),
            candle(timestamp='2026-11-17T09:25:00+05:30')]
    signal, = scan_snr_signals(bars)
    assert 'vwap' in signal['tested_levels']


@pytest.mark.parametrize('resistance', [25420, 25427, 25433])
def test_insufficient_reward_is_rejected(resistance):
    # Includes <1.5R and 1.5R..2R: do not project through nearby resistance.
    assert scan_snr_signals([candle()], {'PDL': 25400, 'PDH': resistance}) == []


def test_projected_target_when_no_opposing_level():
    signal, = scan_snr_signals([candle()], {'PDL': 25400})
    assert signal['risk_reward'] == 2
    assert signal['target'] == 25434
    assert signal['strikes']['ATM']['premium_entry'] is None


def test_stop_minimum_and_maximum():
    signal, = scan_snr_signals([candle(open=25402, close=25403, high=25404)], {'PDL': 25400})
    assert signal['index_sl_pts'] == 8
    assert signal['stop_loss'] == 25395
    assert scan_snr_signals([candle(open=25418, close=25420, high=25422)], {'PDL': 25400}) == []


def test_session_reset_and_zero_volume():
    bars = [candle(volume=0), candle(timestamp='2026-11-18T09:20:00+05:30',
                                    open=25500, low=25490, high=25510, close=25500)]
    levels = calculate_levels(bars)
    assert levels[0]['vwap'] == pytest.approx((25412+25400+25410)/3)
    assert levels[0]['vwap_source'] == 'TYPICAL_PRICE_MEAN'
    assert levels[1]['vwap'] == 25500
    assert levels[1]['day_open'] == 25500
    assert levels[1]['prior_session_low'] is None
    assert scan_snr_signals([bars[0]], {'PDL': 25400})[0]['side'] == 'CE'


@pytest.mark.parametrize('missing', [False, True])
@pytest.mark.parametrize('bearish', [False, True])
def test_cash_index_rejections_without_volume(missing, bearish):
    bar = (candle(open=25402, close=25400, low=25398, high=25410, volume=0)
           if bearish else candle(volume=0))
    if missing:
        bar.pop('volume')
    refs = {'PDH': 25410, 'PDL': 25360} if bearish else {'PDL': 25400}
    signal, = scan_snr_signals([bar], refs)
    assert signal['side'] == ('PE' if bearish else 'CE')
    assert set(signal['strikes']) == {'ATM', 'ITM', 'OTM'}


def test_cash_mean_accumulates_and_switches_to_weighted_volume():
    bars = [candle(volume=0), candle(timestamp='2026-11-17T09:25:00+05:30', high=25415, volume=0)]
    levels = calculate_levels(bars)
    assert levels[1]['vwap'] == pytest.approx(((25412+25400+25410)/3+(25415+25400+25410)/3)/2)
    bars.append(candle(timestamp='2026-11-17T09:30:00+05:30', volume=10))
    last = calculate_levels(bars)[-1]
    assert last['vwap'] == pytest.approx((25412+25400+25410)/3)
    assert last['vwap_source'] == 'VOLUME_WEIGHTED'


def test_causal_session_extrema_and_prefix_invariance():
    bars = [candle(), candle(timestamp='2026-11-17T09:25:00+05:30')]
    levels = calculate_levels(bars)
    assert levels[0]['prior_session_low'] is None
    assert levels[1]['prior_session_low'] == 25400
    assert calculate_levels(bars[:1])[0] == levels[0]


@pytest.mark.parametrize('changes', [
    {'high': 25300}, {'low': -1}, {'close': float('nan')},
    {'volume': -1}, {'volume': float('inf')}, {'completed': False},
    {'closed': False}, {'timestamp': '2026-11-17T09:20:00'},
])
def test_bad_data_rejected(changes):
    with pytest.raises(ValueError):
        calculate_levels([candle(**changes)])


def test_duplicate_timestamp_rejected():
    with pytest.raises(ValueError):
        calculate_levels([candle(), candle()])


@pytest.mark.parametrize('changes', [dict(open=25410), dict(open=25401, close=25410)])
def test_doji_or_poor_wick_rejected(changes):
    assert scan_snr_signals([candle(**changes)], {'PDL': 25400}) == []


def test_one_minute_candles_and_input_unchanged():
    bars = [candle(timestamp='2026-11-17T09:16:00+05:30'),
            candle(timestamp='2026-11-17T09:17:00+05:30')]
    original = [b.copy() for b in bars]
    assert scan_snr_signals(bars, {'PDL': 25400})
    assert bars == original


def test_empty_input_and_bad_configuration():
    assert scan_snr_signals([]) == []
    with pytest.raises(ValueError):
        scan_snr_signals([], tolerance=-1)
    with pytest.raises(ValueError):
        scan_snr_signals([], symbol='OTHER')
    with pytest.raises(ValueError):
        calculate_levels([], {'PDH': 10, 'PDL': 20})
