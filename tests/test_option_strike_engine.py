from datetime import datetime, timedelta, timezone

import pytest

from smc.option_strike_engine import read_quote_tape, select_strikes


NOW = datetime(2026, 11, 17, 5, tzinfo=timezone.utc)


def row(strike=25400, **changes):
    return dict(dict(market='NIFTY', side='CE', strike=strike,
                     expiry='2026-11-17', quote_at=NOW.isoformat(),
                     bid=99.95, ask=100, trading_symbol=f'OPTION{strike}',
                     research_only=True, orders_enabled=False), **changes)


def select(**changes):
    args = dict(spot=25400, direction='BULLISH', index_sl_pts=15,
                index_target_pts=30, now=NOW)
    args.update(changes)
    return select_strikes(**args)


@pytest.mark.parametrize('direction,strikes,side', [
    ('BULLISH', [25400, 25350, 25450], 'CE'),
    ('BEARISH', [25400, 25450, 25350], 'PE'),
])
def test_strikes_and_option_side(direction, strikes, side):
    cards = select(direction=direction)
    assert [c['strike'] for c in cards.values()] == strikes
    assert all(c['side'] == side for c in cards.values())
    assert all(c['premium_entry'] is None for c in cards.values())


@pytest.mark.parametrize('kind,strike,delta,sl,target', [
    ('ATM', 25400, .50, 92.5, 115),
    ('ITM', 25350, .65, 90.25, 119.5),
    ('OTM', 25450, .35, 94.75, 110.5),
])
def test_delta_distances_and_absolute_prices(kind, strike, delta, sl, target):
    card = select(quotes=[row(strike)])[kind]
    assert card['delta'] == delta
    assert card['premium_sl_pts'] == 100 - sl
    assert card['premium_target_pts'] == target - 100
    assert card['premium_entry'] == 100
    assert card['premium_sl'] == sl
    assert card['premium_target'] == target
    assert card['orders_enabled'] is False
    assert card['research_only'] is True
    assert card['premium_exit_prices_verified'] is False


def test_sensex_spacing_and_half_up_tie():
    cards = select(symbol='SENSEX', spot=80050, direction='BEARISH')
    assert [c['strike'] for c in cards.values()] == [80100, 80200, 80000]
    assert select(spot=25425)['ATM']['strike'] == 25450


def test_price_floor_and_tick_rounding():
    card = select(quotes=[row(bid=1, ask=1.025)])['ATM']
    assert card['premium_entry'] == 1.05
    assert card['premium_sl'] == 0
    assert card['premium_target'] == 16.05


@pytest.mark.parametrize('changes', [
    {'market': 'SENSEX'}, {'side': 'PE'}, {'expiry': '2026-11-16'},
    {'quote_at': (NOW - timedelta(seconds=21)).isoformat()},
    {'quote_at': (NOW + timedelta(seconds=1)).isoformat()},
    {'quote_at': '2026-11-17T05:00:00'}, {'quote_at': 'bad'},
    {'bid': 101}, {'bid': 0}, {'ask': float('nan')},
    {'ask': float('inf')}, {'orders_enabled': True}, {'research_only': False},
])
def test_invalid_quotes_never_generate_prices(changes):
    assert select(quotes=[row(**changes)])['ATM']['premium_entry'] is None


def test_latest_quote_and_single_expiry():
    rows = [row(ask=101, quote_at=(NOW - timedelta(seconds=5)).isoformat()),
            row(), row(25350, expiry='2026-11-24')]
    cards = select(quotes=rows)
    assert cards['ATM']['premium_entry'] == 100
    assert cards['ITM']['premium_entry'] is None
    assert cards['ITM']['expiry'] == '2026-11-17'
    assert select(quotes=rows, expiry='2026-11-24')['ITM']['premium_entry'] == 100


@pytest.mark.parametrize('changes', [
    {'spot': 0}, {'spot': float('nan')}, {'spot': float('inf')},
    {'spot': 'bad'}, {'index_sl_pts': -1}, {'index_target_pts': 0},
    {'direction': 'LONG'}, {'symbol': 'OTHER'}, {'max_quote_age': -1},
    {'now': NOW.replace(tzinfo=None)},
])
def test_invalid_inputs(changes):
    with pytest.raises(ValueError):
        select(**changes)


def test_jsonl_tape_and_truncated_line(tmp_path):
    import json
    path = tmp_path / 'quotes.jsonl'
    path.write_text(json.dumps(row()) + '\nnull\n{unfinished', encoding='utf-8')
    assert len(read_quote_tape(path)) == 1
    assert select(quote_path=path)['ATM']['premium_entry'] == 100
    assert read_quote_tape(tmp_path / 'missing') == []


def test_freshness_boundary_and_no_mutation():
    quote = row(quote_at=(NOW - timedelta(seconds=20)).isoformat())
    original = quote.copy()
    assert select(quotes=[quote])['ATM']['status'] == 'ESTIMATED'
    assert quote == original
