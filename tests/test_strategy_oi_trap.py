from datetime import datetime, timedelta

import pytest

from smc.strategy_oi_trap import analyze_oi_chain, evaluate_oi_trap

NOW = datetime.fromisoformat('2026-11-17T09:40:00+05:30')


def quote(strike, side, oi, **changes):
    return dict(dict(strike=strike, side=side, oi=oi, expiry='2026-11-17',
                     bid=99.95, ask=100, market='NIFTY', quote_at=NOW.isoformat(),
                     research_only=True, orders_enabled=False), **changes)


def chain():
    return [quote(25400, 'CE', 1000), quote(25350, 'PE', 1200),
            quote(25450, 'CE', 100), quote(25350, 'CE', 50),
            quote(25400, 'PE', 100), quote(25450, 'PE', 50)]


def candles(bullish=True):
    result = []
    for i in range(5):
        at = NOW-timedelta(minutes=20-5*i)
        if bullish:
            o, h, l, c = (25398, 25401, 25396, 25399) if i == 0 else (25403, 25408, 25401, 25405)
        else:
            o, h, l, c = (25352, 25354, 25349, 25351) if i == 0 else (25347, 25349, 25342, 25345)
        result.append(dict(timestamp=at.isoformat(), open=o, high=h, low=l, close=c, volume=100))
    return result


def evaluate(bullish=True, **kwargs):
    args = dict(spot=25405 if bullish else 25345, candles=candles(bullish), option_chain=chain(), now=NOW)
    args.update(kwargs)
    return evaluate_oi_trap(**args)


def test_oi_walls_pcr_and_additive_strikes():
    rows = chain()+[quote(25450, 'CE', 2000)]
    analysis = analyze_oi_chain(rows, now=NOW)
    assert analysis['max_call_oi_strike'] == 25450
    assert analysis['max_put_oi_strike'] == 25350
    assert analysis['strike_oi']['CE'][25450] == 2100
    assert analysis['pcr_oi'] == pytest.approx(1350/3150)


def test_nearest_active_expiry_and_market_isolation():
    rows = chain()+[quote(26000, 'CE', 99999, expiry='2026-11-10'),
                    quote(26000, 'CE', 99999, expiry='2026-11-24'),
                    quote(26000, 'CE', 99999, market='SENSEX')]
    analysis = analyze_oi_chain(rows, now=NOW)
    assert analysis['expiry'] == '2026-11-17'
    assert analysis['max_call_oi_strike'] == 25400
    after_close = NOW.replace(hour=16)
    assert analyze_oi_chain(rows, now=after_close)['expiry'] == '2026-11-24'


@pytest.mark.parametrize('bullish,side,stop,target', [
    (True, 'CE', 25388, 25439), (False, 'PE', 25362, 25311)])
def test_confirmed_signals(bullish, side, stop, target):
    result = evaluate(bullish)
    signal, = result['signals']
    assert result['status'] == 'SIGNAL'
    assert signal['side'] == side
    assert signal['stop_loss'] == stop
    assert signal['target'] == target
    assert signal['index_sl_pts'] == 17
    assert signal['risk_reward'] == 2
    assert signal['orders_enabled'] is False
    assert signal['oi_unwinding_verified'] is False


def test_strike_cards_and_delta_prices():
    signal, = evaluate()['signals']
    assert set(signal['strikes']) == {'ATM', 'ITM', 'OTM'}
    for kind, delta in [('ATM', .5), ('ITM', .65), ('OTM', .35)]:
        card = signal['strikes'][kind]
        assert card['premium_entry'] == 100
        assert card['premium_sl'] == pytest.approx(100-17*delta)
        assert card['premium_target'] == pytest.approx(100+34*delta)


@pytest.mark.parametrize('spot', [25350, 25375, 25400])
def test_inside_walls_or_boundary_no_signal(spot):
    result = evaluate(spot=spot)
    assert result['status'] == 'NO_BREAKOUT'
    assert result['signals'] == []


def test_full_fifteen_minutes_and_observed_crossing_required():
    assert evaluate(candles=candles()[:-1], now=NOW-timedelta(minutes=5))['status'] == 'AWAITING_CONFIRMATION'
    assert evaluate(candles=candles()[1:])['status'] == 'AWAITING_CONFIRMATION'


def test_gap_or_wick_back_inside_blocks_confirmation():
    bars = candles()
    assert evaluate(candles=bars[:2]+bars[3:])['status'] == 'AWAITING_CONFIRMATION'
    bars[2]['low'] = 25399
    assert evaluate(candles=bars)['status'] == 'AWAITING_CONFIRMATION'


def test_spot_break_without_closed_bar_confirmation():
    bars = candles()
    bars[-1].update(open=25398, high=25401, low=25396, close=25399)
    assert evaluate(candles=bars)['status'] == 'AWAITING_CONFIRMATION'


def test_stale_and_previous_day_candles():
    assert evaluate(now=NOW+timedelta(minutes=6))['status'] == 'STALE_OR_MISSING_CANDLES'
    old = [dict(b, timestamp=b['timestamp'].replace('11-17', '11-16')) for b in candles()]
    assert evaluate(candles=old)['status'] == 'STALE_OR_MISSING_CANDLES'


def test_risk_cap_and_buffer():
    assert evaluate(spot=25430)['status'] == 'RISK_TOO_LARGE'
    assert evaluate(stop_buffer=15)['signals'][0]['stop_loss'] == 25385
    with pytest.raises(ValueError):
        evaluate(stop_buffer=16)


def test_missing_invalid_oi_and_zero_call_pcr():
    rows = [quote(25400, 'CE', 0), quote(25350, 'PE', 100),
            quote(25500, 'CE', -1), quote(25500, 'CE', float('nan'))]
    analysis = analyze_oi_chain(rows, now=NOW)
    assert analysis['pcr_oi'] is None
    assert analysis['max_call_oi_strike'] is None
    assert evaluate(option_chain=rows)['status'] == 'OI_UNAVAILABLE'
    assert evaluate(option_chain=[])['signals'] == []


def test_ties_and_ambiguous_walls():
    rows = [quote(25400, 'CE', 100), quote(25350, 'CE', 100), quote(25400, 'PE', 100)]
    assert analyze_oi_chain(rows, now=NOW)['max_call_oi_strike'] == 25350
    assert evaluate(option_chain=rows)['status'] == 'AMBIGUOUS_WALLS'


def test_minimum_chain_schema_without_premium_provenance():
    rows = [{k: r[k] for k in ('strike', 'side', 'oi', 'expiry', 'bid', 'ask')} for r in chain()]
    result = evaluate(option_chain=rows)
    assert result['status'] == 'SIGNAL'
    assert result['signals'][0]['strikes']['ATM']['premium_entry'] is None


@pytest.mark.parametrize('changes', [dict(completed=False), dict(volume=-1),
    dict(close=float('inf')), dict(low=25500), dict(timestamp='2026-11-17T09:40:00')])
def test_invalid_candles(changes):
    bars = candles()
    bars[-1].update(changes)
    with pytest.raises(ValueError):
        evaluate(candles=bars)


def test_invalid_parameters_and_future_or_unordered_candles():
    for kwargs in [dict(spot=0), dict(symbol='OTHER'), dict(interval_minutes=3),
                   dict(sustain_minutes=10), dict(now=NOW.replace(tzinfo=None))]:
        with pytest.raises(ValueError):
            evaluate(**kwargs)
    for bars in [candles()+[candles()[-1]], candles()[::-1]]:
        with pytest.raises(ValueError):
            evaluate(candles=bars)
    with pytest.raises(ValueError):
        evaluate(now=NOW-timedelta(minutes=1))


def test_sensex_scaled_risk_and_input_unchanged():
    bars = [{k: v*3 if k in ('open', 'high', 'low', 'close') else v for k, v in b.items()} for b in candles()]
    rows = [dict(r, strike=r['strike']*3, market='SENSEX') for r in chain()]
    original = [b.copy() for b in bars]
    signal, = evaluate(spot=25405*3, candles=bars, option_chain=rows, symbol='SENSEX')['signals']
    assert signal['index_sl_pts'] == 51
    assert bars == original


def test_one_minute_confirmation():
    bars = []
    for i in range(17):
        template = candles()[0 if i == 0 else 1]
        bars.append(dict(template, timestamp=(NOW-timedelta(minutes=16-i)).isoformat()))
    assert evaluate(candles=bars, interval_minutes=1)['status'] == 'SIGNAL'


@pytest.mark.parametrize('zero_oi', [False, True])
def test_option_volume_fallback_walls_pcr_and_signals(zero_oi):
    rows = []
    for row in chain():
        row['volume'] = row.pop('oi')
        if zero_oi:
            row['oi'] = 0
        rows.append(row)
    analysis = analyze_oi_chain(rows, now=NOW)
    assert analysis['max_call_oi_strike'] == 25400
    assert analysis['max_put_oi_strike'] == 25350
    assert analysis['activity_basis'] == 'OPTION_VOLUME'
    assert analysis['pcr_oi'] == pytest.approx(1350/1150)
    bars = [{k: v for k, v in bar.items() if k != 'volume'} for bar in candles()]
    result = evaluate(option_chain=rows, candles=bars)
    assert result['status'] == 'SIGNAL'
    assert result['signals'][0]['activity_basis'] == 'OPTION_VOLUME'
    assert result['signals'][0]['oi_unwinding_verified'] is False


def test_positive_oi_wins_and_mixed_basis_is_explicit():
    rows = [quote(25400, 'CE', 100, volume=99999), quote(25350, 'PE', 0, volume=200)]
    analysis = analyze_oi_chain(rows, now=NOW)
    assert analysis['total_call_oi'] == 100
    assert analysis['pcr_oi'] == 2
    assert analysis['activity_basis'] == 'MIXED_OI_OPTION_VOLUME'


@pytest.mark.parametrize('volume', [-1, float('nan'), float('inf')])
def test_bad_fallback_volume_not_used(volume):
    rows = [quote(25400, 'CE', 0, volume=volume), quote(25350, 'PE', 100)]
    assert analyze_oi_chain(rows, now=NOW)['max_call_oi_strike'] is None
