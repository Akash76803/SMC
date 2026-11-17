from datetime import datetime, timedelta

import pytest

from smc.strategy_orb import evaluate_orb_15m


def bar(clock='09:35', **changes):
    return dict(dict(timestamp=f'2026-11-17T{clock}:00+05:30', open=25418,
                     high=25427, low=25412, close=25425, volume=200), **changes)


def opening():
    return [bar('09:20', open=25410, high=25420, low=25400, close=25415, volume=100),
            bar('09:25', open=25415, high=25418, low=25405, close=25410, volume=100),
            bar('09:30', open=25410, high=25419, low=25404, close=25418, volume=100)]


def evaluate(extra=(), **kwargs):
    return evaluate_orb_15m(opening()+list(extra), **kwargs)


def test_range_exact_close_boundaries_and_lock():
    result = evaluate([bar(), bar('09:40', high=25490, close=25480)])
    assert result['status'] == 'LOCKED'
    assert result['orb_high'] == 25420
    assert result['orb_low'] == 25400
    assert result['orb_midpoint'] == 25410
    assert result['range_span'] == 20
    assert len(result['signals']) == 1


def test_open_timestamp_convention_equivalent():
    bars = opening()+[bar()]
    shifted = [dict(b, timestamp=(datetime.fromisoformat(b['timestamp'])-timedelta(minutes=5)).isoformat()) for b in bars]
    assert evaluate_orb_15m(shifted, timestamp_kind='open') == evaluate_orb_15m(bars)


def test_bullish_breakout_and_2r():
    signal, = evaluate([bar()])['signals']
    assert signal['direction'] == 'BULLISH'
    assert signal['signal_type'] == 'BREAKOUT'
    assert signal['stop_loss'] == 25412
    assert signal['index_sl_pts'] == 13
    assert signal['target'] == 25451
    assert signal['risk_reward'] == 2
    assert signal['orders_enabled'] is False
    assert signal['research_only'] is True


def test_bearish_breakout():
    signal, = evaluate([bar(open=25402, high=25408, low=25393, close=25395)])['signals']
    assert signal['side'] == 'PE'
    assert signal['stop_loss'] == 25408
    assert signal['target'] == 25369
    assert signal['strikes']['ITM']['strike'] == 25450


@pytest.mark.parametrize('close', [25400, 25410, 25420])
def test_inside_or_boundary_close_is_not_breakout(close):
    assert evaluate([bar(open=25410, high=25422, low=25398, close=close)])['signals'] == []


def test_retest_once_after_breakout():
    result = evaluate([bar(), bar('09:40', open=25422, low=25419), bar('09:45', open=25422, low=25420)])
    assert [s['signal_type'] for s in result['signals']] == ['BREAKOUT', 'RETEST']
    assert result['signals'][1]['stop_loss'] == 25412


def test_bearish_retest():
    result = evaluate([bar(open=25402, high=25408, low=25393, close=25395),
                       bar('09:40', open=25398, high=25401, low=25392, close=25395)])
    assert [s['signal_type'] for s in result['signals']] == ['BREAKOUT', 'RETEST']


def test_no_retest_without_touch():
    assert len(evaluate([bar(), bar('09:40', open=25424, low=25424)])['signals']) == 1


def test_strike_cards_delta_prices():
    at = datetime.fromisoformat('2026-11-17T09:35:00+05:30')
    quotes = [dict(market='NIFTY', side='CE', strike=strike, expiry='2026-11-17',
                   quote_at=at.isoformat(), bid=99.95, ask=100,
                   research_only=True, orders_enabled=False) for strike in (25400, 25450, 25500)]
    signal, = evaluate([bar()], quotes=quotes, now=at)['signals']
    assert set(signal['strikes']) == {'ATM', 'ITM', 'OTM'}
    for kind, delta in [('ATM', .5), ('ITM', .65), ('OTM', .35)]:
        card = signal['strikes'][kind]
        assert card['delta'] == delta
        assert card['premium_entry'] == 100
        assert card['premium_sl'] == pytest.approx(100-13*delta)
        assert card['premium_target'] == pytest.approx(100+26*delta)


def test_quotes_missing_never_invent_entry():
    signal, = evaluate([bar()])['signals']
    assert signal['strikes']['ATM']['premium_entry'] is None


@pytest.mark.parametrize('span', [9, 151])
def test_anomalous_range_blocks_signals(span):
    bars = [dict(b, high=25400+span, low=25400, open=25401, close=25402) for b in opening()]
    result = evaluate_orb_15m(bars+[bar()])
    assert result['status'] == 'ANOMALOUS_RANGE'
    assert result['signals'] == []


def test_incomplete_range_and_prelock_status():
    assert evaluate_orb_15m(opening()[:2])['status'] == 'BUILDING_RANGE'
    result = evaluate_orb_15m(opening()[1:]+[bar()])
    assert result['status'] == 'INCOMPLETE_RANGE'
    assert not result['signals']
    assert evaluate_orb_15m([bar()])['status'] == 'INCOMPLETE_RANGE'


def test_minimum_stop_and_excessive_stop():
    signal, = evaluate([bar(open=25424, low=25424)])['signals']
    assert signal['index_sl_pts'] == 10
    assert evaluate([bar(open=25420, high=25480, close=25475)])['signals'] == []


@pytest.mark.parametrize('volume', [99])
def test_volume_confirmation(volume):
    assert evaluate([bar(volume=volume)])['signals'] == []


@pytest.mark.parametrize('missing', [False, True])
@pytest.mark.parametrize('symbol', ['NIFTY', 'SENSEX'])
def test_cash_index_price_only_breakout_retest(missing, symbol):
    scale = 1 if symbol == 'NIFTY' else 3
    data = opening()+[bar(), bar('09:40', open=25422, low=25419)]
    for b in data:
        b['volume'] = 0
        if missing:
            b.pop('volume')
        for key in ('open', 'high', 'low', 'close'):
            b[key] *= scale
    signals = evaluate_orb_15m(data, symbol=symbol)['signals']
    assert [s['signal_type'] for s in signals] == ['BREAKOUT', 'RETEST']
    assert all(s['confirmation_source'] == 'PRICE_ONLY' for s in signals)
    assert set(signals[0]['strikes']) == {'ATM', 'ITM', 'OTM'}


def test_sensex_scaled_distances():
    bars = []
    for b in opening()+[bar()]:
        bars.append({k: v*3 if k in ('open', 'high', 'low', 'close') else v for k, v in b.items()})
    signal, = evaluate_orb_15m(bars, symbol='SENSEX')['signals']
    assert signal['index_sl_pts'] == 39
    assert signal['range_span'] == 60


def test_session_reset_and_no_lookahead():
    prefix = opening()+[bar()]
    tomorrow = [dict(b, timestamp=b['timestamp'].replace('11-17', '11-18')) for b in prefix]
    result = evaluate_orb_15m(prefix+tomorrow)
    assert result['signals'][:1] == evaluate_orb_15m(prefix)['signals']
    assert len(result['signals']) == 2
    assert result['session_date'] == '2026-11-18'


def test_utc_and_one_minute_inputs():
    start = datetime.fromisoformat('2026-11-17T03:46:00+00:00')
    bars = [dict(opening()[0], timestamp=(start+timedelta(minutes=i)).isoformat()) for i in range(15)]
    bars.append(bar('09:31'))
    result = evaluate_orb_15m(bars, interval_minutes=1)
    assert result['status'] == 'LOCKED'
    assert len(result['signals']) == 1


@pytest.mark.parametrize('changes', [dict(completed=False), dict(closed=False),
    dict(volume=-1), dict(close=float('nan')), dict(high=25300),
    dict(timestamp='2026-11-17T09:35:00')])
def test_invalid_candles(changes):
    with pytest.raises(ValueError):
        evaluate([bar(**changes)])


def test_invalid_configuration_and_duplicate_times():
    for kwargs in [dict(symbol='OTHER'), dict(interval_minutes=3), dict(timestamp_kind='other'),
                   dict(retest_tolerance=-1), dict(volume_multiplier=float('inf'))]:
        with pytest.raises(ValueError):
            evaluate_orb_15m([], **kwargs)
    with pytest.raises(ValueError):
        evaluate([bar(), bar()])


def test_outside_market_ignored_and_no_mutation():
    bars = [bar('09:15', high=26000), *opening(), bar(), bar('15:35')]
    original = [b.copy() for b in bars]
    result = evaluate_orb_15m(bars)
    assert result['orb_high'] == 25420
    assert bars == original
    assert evaluate_orb_15m([])['status'] == 'NO_DATA'
