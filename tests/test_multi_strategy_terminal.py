"""Read-only HTTP and recorded-data integration acceptance checks."""
import json
from datetime import datetime, timedelta
from http.server import ThreadingHTTPServer
from threading import Thread
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from smc import app_terminal_v316 as terminal
from smc.multi_strategy_terminal import multi_strategy_payload

NOW = datetime.fromisoformat('2026-11-17T09:40:00+05:30')


def write_rows(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(''.join(json.dumps(row)+'\n' for row in rows), encoding='utf-8')


def bars():
    return [dict(timestamp=(NOW-timedelta(minutes=20-i*5)).isoformat(),
                 open=25410, high=25420, low=25400, close=25415, volume=100)
            for i in range(3)] + [
                dict(timestamp=(NOW-timedelta(minutes=5)).isoformat(), open=25410,
                     high=25420, low=25400, close=25415, volume=100),
                dict(timestamp=NOW.isoformat(), open=25418, high=25427,
                     low=25412, close=25425, volume=200)]


def quotes():
    return [dict(strike=strike, side=side, oi=oi, expiry='2026-11-17',
                 bid=99.95, ask=100, market='NIFTY', quote_at=NOW.isoformat(),
                 research_only=True, orders_enabled=False)
            for strike, side, oi in [(25400, 'CE', 1000), (25350, 'PE', 1200),
                                      (25450, 'CE', 100), (25500, 'CE', 50)]]


@pytest.fixture
def server(tmp_path):
    http = ThreadingHTTPServer(('127.0.0.1', 0), terminal.make_handler(
        'unused', 'unused', None, multi_root=tmp_path))
    worker = Thread(target=http.serve_forever, daemon=True)
    worker.start()
    try:
        yield f'http://127.0.0.1:{http.server_port}'
    finally:
        http.shutdown()
        http.server_close()
        worker.join(timeout=4)


@pytest.mark.parametrize('market', ['NIFTY', 'SENSEX'])
def test_get_endpoint_missing_files_returns_safe_json(server, market):
    with urlopen(server+'/api/multi_strategy_status?market='+market) as response:
        assert response.status == 200
        assert response.headers['Content-Type'] == 'application/json'
        assert response.headers['Cache-Control'] == 'no-store'
        data = json.load(response)
    assert data['market'] == market
    assert data['timestamp']
    assert data['research_only'] is True
    assert data['orders_enabled'] is False
    assert set(data['strategies']) == {
        'snr_vwap', 'orb', 'candlestick', 'oi_trap', 'smc_sweep', 'smc_mss',
        'smc_fvg', 'smc_ob', 'smc_fib', 'pdh_pdl', 'trap_detector',
    }
    for state in data['strategies'].values():
        assert state['signal'] is None
        assert state['strikes'] == {}


def test_endpoint_reads_results_under_multi_root(server, tmp_path):
    write_rows(tmp_path/'results/live_nifty.jsonl', bars())
    with urlopen(server+'/api/multi_strategy_status?market=NIFTY') as response:
        data = json.load(response)
    assert data['strategies']['orb']['range']['orb_high'] == 25420


def test_bad_market_and_no_write_route(server):
    with pytest.raises(HTTPError) as error:
        urlopen(server+'/api/multi_strategy_status?market=INVALID')
    assert error.value.code == 400
    with pytest.raises(HTTPError) as error:
        urlopen(Request(server+'/api/multi_strategy_status', data=b'{}', method='POST'))
    assert error.value.code == 501
    with pytest.raises(HTTPError) as error:
        urlopen(server+'/api/place-order')
    assert error.value.code == 404


def test_orb_fresh_signal_cards_and_market_isolation(tmp_path):
    write_rows(tmp_path/'live_nifty.jsonl', bars())
    write_rows(tmp_path/'live_nifty_option_quotes.jsonl', quotes())
    data = multi_strategy_payload(tmp_path, 'NIFTY', now=NOW)
    orb = data['strategies']['orb']
    assert orb['status'] == 'BREAKOUT_OBSERVED'
    assert orb['direction'] == 'BULLISH'
    assert orb['strikes']['ATM']['premium_entry'] == 100
    assert orb['strikes']['ATM']['premium_sl'] == 93.5
    assert orb['strikes']['ATM']['premium_target'] == 113
    sensex = multi_strategy_payload(tmp_path, 'SENSEX', now=NOW)
    assert sensex['strategies']['orb']['signal'] is None


def test_snr_fresh_rejection(tmp_path):
    b = [dict(timestamp=NOW.isoformat(), open=25406, high=25409,
              low=25400, close=25408, volume=100)]
    write_rows(tmp_path/'live_nifty.jsonl', b)
    data = multi_strategy_payload(tmp_path, 'NIFTY', now=NOW)
    assert data['strategies']['snr_vwap']['status'] == 'ACTIVE_SIGNAL'
    assert set(data['strategies']['snr_vwap']['strikes']) == {'ATM', 'ITM', 'OTM'}


def test_oi_confirmation_and_quote_tape_deduplication(tmp_path):
    b = []
    for i in range(5):
        b.append(dict(timestamp=(NOW-timedelta(minutes=20-i*5)).isoformat(),
                      open=25398 if i == 0 else 25403, high=25408,
                      low=25396 if i == 0 else 25401,
                      close=25399 if i == 0 else 25405, volume=100))
    write_rows(tmp_path/'live_nifty.jsonl', b)
    q = quotes()
    write_rows(tmp_path/'live_nifty_option_quotes.jsonl', q+q)
    oi = multi_strategy_payload(tmp_path, 'NIFTY', now=NOW)['strategies']['oi_trap']
    assert oi['status'] == 'SHORT_COVERING'
    assert oi['walls']['max_call_oi_strike'] == 25400
    assert oi['pcr'] == pytest.approx(1200/1150)
    assert oi['signal']['oi_unwinding_verified'] is False


def test_old_signal_not_promoted_and_stale_candles_block(tmp_path):
    b = bars()
    write_rows(tmp_path/'live_nifty.jsonl', b)
    data = multi_strategy_payload(tmp_path, 'NIFTY', now=NOW+timedelta(minutes=6))
    assert data['strategies']['orb']['status'] == 'WAITING'
    assert data['strategies']['orb']['strikes'] == {}
    b.append(dict(b[-1], timestamp=(NOW+timedelta(minutes=5)).isoformat(), low=25424, open=25424))
    write_rows(tmp_path/'live_nifty.jsonl', b)
    data = multi_strategy_payload(tmp_path, 'NIFTY', now=NOW+timedelta(minutes=5))
    assert data['strategies']['orb']['signal'] is None


def test_real_snapshot_missing_volume_oi_and_blocked_quality(tmp_path):
    b = [{k: v for k, v in row.items() if k != 'volume'} for row in bars()]
    write_rows(tmp_path/'live_nifty.jsonl', [dict(symbol='NIFTY', sampled_live_candles=b,
                                                stream_quality={'volume_verified': False})])
    write_rows(tmp_path/'live_nifty_option_quotes.jsonl', [{k: v for k, v in q.items() if k != 'oi'} for q in quotes()])
    data = multi_strategy_payload(tmp_path, 'NIFTY', now=NOW)
    assert data['strategies']['orb']['range']['orb_high'] == 25420
    assert data['strategies']['orb']['status'] == 'BREAKOUT_OBSERVED'
    assert set(data['strategies']['orb']['strikes']) == {'ATM', 'ITM', 'OTM'}
    assert data['strategies']['oi_trap']['reason'] == 'OI_UNAVAILABLE'
    write_rows(tmp_path/'live_nifty.jsonl', [dict(symbol='NIFTY', sampled_live_candles=bars(),
                                                stream_quality={'quality_blocked': True})])
    assert multi_strategy_payload(tmp_path, 'NIFTY', now=NOW)['strategies']['orb']['signal'] is None


@pytest.mark.parametrize('market', ['NIFTY', 'SENSEX'])
def test_cash_index_orb_evening_review_uses_setup_time_quotes(tmp_path, market):
    scale = 1 if market == 'NIFTY' else 3
    data = bars()
    for b in data:
        b.pop('volume')
        for key in ('open', 'high', 'low', 'close'):
            b[key] *= scale
    # For SENSEX the selected ATM at 76275 is 76300.
    atm = 25450 if market == 'NIFTY' else 76300
    q = [dict(quotes()[0], market=market, strike=atm)]
    q.append(dict(q[0], ask=999, bid=998, quote_at=(NOW+timedelta(minutes=5)).isoformat()))
    write_rows(tmp_path/f'live_{market.lower()}.jsonl', data)
    write_rows(tmp_path/f'live_{market.lower()}_option_quotes.jsonl', q)
    live = multi_strategy_payload(tmp_path, market, now=NOW)['strategies']['orb']
    assert live['status'] == 'BREAKOUT_OBSERVED'
    evening = multi_strategy_payload(tmp_path, market, now=NOW.replace(hour=19))['strategies']['orb']
    assert evening['status'] == 'SESSION_CLOSED_OBSERVATION'
    assert evening['observed_at'] == NOW.isoformat()
    assert evening['strikes']['ATM']['premium_entry'] == 100
    assert evening['strikes']['ATM']['premium_sl'] == pytest.approx(100-13*scale*.5)
    tomorrow = multi_strategy_payload(tmp_path, market, now=NOW.replace(hour=19)+timedelta(days=1))
    assert tomorrow['strategies']['orb']['strikes'] == {}


def test_live_twenty_second_boundary_and_evening_no_quotes(tmp_path):
    write_rows(tmp_path/'live_nifty.jsonl', [dict(b, volume=0) for b in bars()])
    assert multi_strategy_payload(tmp_path, 'NIFTY', now=NOW+timedelta(seconds=20))['strategies']['orb']['status'] == 'BREAKOUT_OBSERVED'
    assert multi_strategy_payload(tmp_path, 'NIFTY', now=NOW+timedelta(seconds=21))['strategies']['orb']['signal'] is None
    state = multi_strategy_payload(tmp_path, 'NIFTY', now=NOW.replace(hour=18))['strategies']['orb']
    assert state['status'] == 'SESSION_CLOSED_OBSERVATION'
    assert state['strikes']['ATM']['premium_entry'] is None


def test_cash_snr_evening_latest_observation(tmp_path):
    b = dict(timestamp=NOW.isoformat(), open=25406, high=25409, low=25400, close=25408)
    write_rows(tmp_path/'live_nifty.jsonl', [b])
    write_rows(tmp_path/'live_nifty_option_quotes.jsonl', quotes())
    state = multi_strategy_payload(tmp_path, 'NIFTY', now=NOW.replace(hour=18))['strategies']['snr_vwap']
    assert state['status'] == 'SESSION_CLOSED_OBSERVATION'
    assert state['strikes']['ATM']['premium_entry'] == 100
    assert state['signal']['levels']['vwap_source'] == 'TYPICAL_PRICE_MEAN'


def test_option_volume_walls_and_evening_oi_replay(tmp_path):
    b = []
    for i in range(5):
        b.append(dict(timestamp=(NOW-timedelta(minutes=20-i*5)).isoformat(),
                      open=25398 if i == 0 else 25403, high=25408,
                      low=25396 if i == 0 else 25401,
                      close=25399 if i == 0 else 25405))
    # End the day back inside the walls: retain the earlier confirmed setup.
    b.append(dict(timestamp=(NOW+timedelta(minutes=5)).isoformat(),
                  open=25399, high=25400, low=25395, close=25398))
    q = [{**{k: v for k, v in row.items() if k != 'oi'}, 'volume': row['oi']} for row in quotes()]
    write_rows(tmp_path/'live_nifty.jsonl', b)
    write_rows(tmp_path/'live_nifty_option_quotes.jsonl', q+q)
    state = multi_strategy_payload(tmp_path, 'NIFTY', now=NOW.replace(hour=18))['strategies']['oi_trap']
    assert state['status'] == 'SESSION_CLOSED_OBSERVATION'
    assert state['activity_basis'] == 'OPTION_VOLUME'
    assert 'OPTION_VOLUME' in state['reason']
    assert state['signal']['timestamp'] == NOW.isoformat()
    assert state['strikes']['ATM']['premium_entry'] == 100


@pytest.mark.parametrize('content', ['', '{unfinished', 'null\n[]\n{"sampled_live_candles":[null,1]}\n'])
def test_empty_or_malformed_tapes(tmp_path, content):
    (tmp_path/'live_nifty.jsonl').write_text(content, encoding='utf-8')
    data = multi_strategy_payload(tmp_path, 'NIFTY', now=NOW)
    assert data['strategies']['orb']['signal'] is None
    json.dumps(data, allow_nan=False)


def test_invalid_ohlc_fails_closed(tmp_path):
    b = bars()
    b[-1]['high'] = 1
    write_rows(tmp_path/'live_nifty.jsonl', b)
    data = multi_strategy_payload(tmp_path, 'NIFTY', now=NOW)
    assert all(s['reason'] == 'INVALID_OR_INCOMPLETE_DATA' for key, s in data['strategies'].items()
               if key in ('snr_vwap', 'orb', 'candlestick', 'oi_trap'))


def test_ui_and_existing_routes_still_present(server):
    with urlopen(server+'/') as response:
        html = response.read().decode()
    assert 'MULTI-STRATEGY SIGNALS' in html
    assert 'Object.entries(data.strategies)' in html
    assert "badge.textContent='High confluence'" in html
    assert 'isCached' not in html
    assert 'setInterval(pollMultiStrategies,2500)' in html
    assert 'navigator.clipboard.writeText(text)' in html
    assert 'SMC / MARKET RESEARCH TERMINAL' in html
    for route in ['/api/live', '/api/snapshot']:
        with urlopen(server+route+'?symbol=NIFTY') as response:
            assert response.status == 200
            assert json.load(response).get('orders_enabled', False) is False


@pytest.mark.parametrize('market', ['NIFTY', 'SENSEX'])
def test_http_timing_available_even_without_signals(server, market):
    with urlopen(server+'/api/multi_strategy_status?market='+market) as response:
        states = json.load(response)['strategies']
    for key, expected in {'snr_vwap': (10, 20, 25), 'orb': (15, 30, 40), 'candlestick': (5, 15, 20), 'oi_trap': (10, 25, 30)}.items():
        minimum, maximum, hold = expected
        state = states[key]
        assert state['expected_duration_min'] == minimum
        assert state['expected_duration_max'] == maximum
        assert state['max_safe_holding_minutes'] == hold
        assert state['timing']['expected_duration'] == f'{minimum} - {maximum} mins'
        assert state['timing']['max_hold'] == f'{hold} mins'
        assert state['timing']['advice'] == state['time_stop_note']
        assert state['timing']['basis'] == 'CONFIGURED_RESEARCH_HEURISTIC'
        assert state['signal'] is None
        assert state['strikes'] == {}


@pytest.mark.parametrize('closed', [False, True])
@pytest.mark.parametrize('strategy', ['snr_vwap', 'orb', 'candlestick', 'oi_trap'])
def test_timing_propagates_to_live_and_historical_signals_and_strikes(tmp_path, strategy, closed):
    if strategy == 'snr_vwap':
        data = [dict(timestamp=NOW.isoformat(), open=25406, high=25409, low=25400, close=25408, volume=0)]
        note = 'If no momentum after 25m, exit near cost to avoid theta decay.'
    elif strategy == 'orb':
        data = [dict(b, volume=0) for b in bars()]
        note = 'Trend continuation expected; exit if price re-enters range after 40m.'
    elif strategy == 'candlestick':
        data = [
            dict(timestamp=(NOW-timedelta(minutes=4)).isoformat(), open=25415, high=25418, low=25410, close=25412, volume=0),
            dict(timestamp=(NOW-timedelta(minutes=3)).isoformat(), open=25412, high=25415, low=25405, close=25406, volume=0),
            dict(timestamp=(NOW-timedelta(minutes=2)).isoformat(), open=25406, high=25408, low=25398, close=25400, volume=0),
            dict(timestamp=(NOW-timedelta(minutes=1)).isoformat(), open=25400, high=25402, low=25392, close=25394, volume=0),
            dict(timestamp=NOW.isoformat(), open=25393, high=25395, low=25382, close=25394, volume=0),
        ]
        note = 'Price action momentum scalp; exit if no expansion within 20m.'
    else:
        data = [dict(timestamp=(NOW-timedelta(minutes=20-i*5)).isoformat(),
                     open=25398 if i == 0 else 25403, high=25408,
                     low=25396 if i == 0 else 25401,
                     close=25399 if i == 0 else 25405, volume=0) for i in range(5)]
        note = 'Fast short-covering spike; exit if momentum halts after 30m.'
    write_rows(tmp_path/'live_nifty.jsonl', data)
    write_rows(tmp_path/'live_nifty_option_quotes.jsonl', quotes())
    at = NOW.replace(hour=19) if closed else NOW
    state = multi_strategy_payload(tmp_path, 'NIFTY', now=at)['strategies'][strategy]
    assert state['signal'] is not None
    assert state['timing']['advice'] == note
    assert state['signal']['timing'] == state['timing']
    assert state['signal']['max_safe_holding_minutes'] == state['max_safe_holding_minutes']
    if closed:
        assert state['status'] == 'SESSION_CLOSED_OBSERVATION'
    for kind in ('ATM', 'ITM', 'OTM'):
        assert state['strikes'][kind]['timing'] == state['timing']
    # A consumer editing one card must not overwrite another card's timing.
    state['strikes']['ITM']['timing']['max_hold'] = 'changed'
    assert state['strikes']['ATM']['timing']['max_hold'] == state['timing']['max_hold']
    assert state['signal']['timing'] == state['timing']


def test_dashboard_renders_and_copies_timing(server):
    with urlopen(server+'/') as response:
        html = response.read().decode()
    assert 'appendStrategyTiming(card,state.timing)' in html
    assert 'appendStrategyTiming(box,timing)' in html
    assert '⏱️ Target Expected: ' in html
    assert '⚠️ Time-SL: ' in html
    assert "timing.expected_duration+' | Max Safe Hold: '+timing.max_hold+' | Time-SL: '+timing.advice" in html
    assert 'Timing windows are configured research heuristics' in html
    assert 'Minutes are measured from manual entry.' in html


def test_dispatcher_publishes_single_engine_and_optional_confluence(tmp_path, monkeypatch):
    from smc import multi_strategy_terminal as dispatcher
    from smc.independent_signals import build_signal

    def sweep(*args, **kwargs):
        return [build_signal('SMC_SWEEP', 'TURTLE_SOUP_PDL', NOW, 'NIFTY', 1,
                             25425, 25415, 25445, 5)]

    def failed_scanner(*args, **kwargs):
        raise RuntimeError('isolated scanner failure')

    write_rows(tmp_path/'live_nifty.jsonl', bars())
    monkeypatch.setattr(dispatcher, 'scan_smc_mss', failed_scanner)
    standalone = multi_strategy_payload(tmp_path, 'NIFTY', now=NOW)
    assert standalone['signals']['orb']
    assert standalone['confluences'] == []
    assert standalone['strategies']['smc_mss']['reason'] == 'INVALID_OR_INCOMPLETE_DATA'

    monkeypatch.setattr(dispatcher, 'scan_smc_sweep', sweep)
    aligned = multi_strategy_payload(tmp_path, 'NIFTY', now=NOW)
    assert aligned['signals']['orb'] == standalone['signals']['orb']
    assert aligned['signals']['smc_sweep'][0]['strikes'][0]['option_type'] == 'CE'
    badge, = aligned['confluences']
    assert badge['confluence_score'] == 'HIGH'
    assert set(badge['engines']) == {'orb', 'smc_sweep'}


def test_hero_setup_entry_bracket_and_sl_stay_frozen_when_ltp_changes():
    from smc.multi_strategy_terminal import build_confirmed_hero_setup, clear_hero_locks
    clear_hero_locks()

    bars = [
        {'open': 25000, 'high': 25050, 'low': 24980, 'close': 25020,
         'timestamp': '2026-11-20T09:30:00+05:30'}
    ]
    card = {
        'setup_id': 'NIFTY:ORB:BREAKOUT:2026-11-20T09:30:00',
        'signal': {
            'setup_id': 'NIFTY:ORB:BREAKOUT:2026-11-20T09:30:00',
            'timestamp': '2026-11-20T09:30:00+05:30',
            'direction': 'BULLISH',
            'entry': 25020.0,
            'stop_loss': 24990.0,
            'target': 25080.0,
        },
        'strikes': {
            'ATM': {
                'strike': 25000,
                'side': 'CE',
                'premium_entry': 120.0,
                'premium_sl': 105.0,
                'premium_target': 150.0,
                'trading_symbol': 'NIFTY26NOV25000CE',
                'expiry': '2026-11-26',
            }
        },
        'outcome': {'status': 'ACTIVE'},
    }
    strategies = {'orb': {'cards': [card]}}
    mtf_trend = {'master_bias': 'BULLISH'}

    # 1. At signal confirmation time, quote LTP is 120.0
    quotes_t0 = [{'strike': 25000, 'side': 'CE', 'ltp': 120.0, 'bid': 119.5, 'ask': 120.5}]
    hero_t0 = build_confirmed_hero_setup('NIFTY', bars, quotes_t0, mtf_trend, strategies, now=NOW)

    assert hero_t0 is not None
    assert hero_t0['ltp'] == 120.0
    initial_bracket = hero_t0['entry_bracket']
    initial_sl = hero_t0['stop_loss']
    initial_t1 = hero_t0['target_1']
    initial_do_not_chase = hero_t0['do_not_chase']

    # 2. Next tick: Option premium surges to 125.0
    quotes_t1 = [{'strike': 25000, 'side': 'CE', 'ltp': 125.0, 'bid': 124.5, 'ask': 125.5}]
    hero_t1 = build_confirmed_hero_setup('NIFTY', bars, quotes_t1, mtf_trend, strategies, now=NOW)

    # LTP updates dynamically
    assert hero_t1['ltp'] == 125.0
    # BUT Entry Bracket, Stop Loss, Target, and Do Not Chase MUST REMAIN 100% FROZEN!
    assert hero_t1['entry_bracket'] == initial_bracket
    assert hero_t1['stop_loss'] == initial_sl
    assert hero_t1['target_1'] == initial_t1
    assert hero_t1['do_not_chase'] == initial_do_not_chase

    # 3. Next tick: Option premium surges to 132.0 (near Target)
    quotes_t2 = [{'strike': 25000, 'side': 'CE', 'ltp': 132.0, 'bid': 131.5, 'ask': 132.5}]
    hero_t2 = build_confirmed_hero_setup('NIFTY', bars, quotes_t2, mtf_trend, strategies, now=NOW)

    assert hero_t2['ltp'] == 132.0
    assert hero_t2['entry_bracket'] == initial_bracket
    assert hero_t2['stop_loss'] == initial_sl
    assert hero_t2['target_1'] == initial_t1
    assert hero_t2['do_not_chase'] == initial_do_not_chase
