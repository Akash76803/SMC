from datetime import datetime, timedelta
import json

import pytest

from smc.independent_signals import IST
from smc.multi_strategy_terminal import (
    _curate_recommendations, build_confirmed_hero_setup, multi_strategy_payload,
)
from smc.trap_detector_v1 import (
    compute_atr_5m, detect_candidate_events, evaluate_choch, evaluate_reclaim,
    scan_traps_and_breakouts,
)


def candles(rows, day=20):
    start = datetime(2026, 11, day, 9, 15, tzinfo=IST)
    return [dict(timestamp=start + timedelta(minutes=5 * index), open=o, high=h, low=l, close=c)
            for index, (o, h, l, c) in enumerate(rows, 1)]


PRIOR = candles([(1000, 1050, 850, 1000)] + [(1000, 1010, 990, 1000)] * 18, day=19)
OPENING = [(1000, 1040, 885, 1020), (1020, 1035, 1012, 1025),
           (1025, 1040, 1010, 1030), (1030, 1039, 1015, 1032)]
SWEEP = (1032, 1058, 1020, 1030)
CHOCH = (1032, 1033, 1000, 1002)
RETEST = (1014, 1016, 1003, 1005)


@pytest.mark.parametrize('mirror,pattern,label,direction', [
    (False, 'BULL_TRAP', 3, 'BEARISH'), (True, 'BEAR_TRAP', 4, 'BULLISH'),
])
def test_confirmed_trap_only_emits_after_retest(mirror, pattern, label, direction):
    bars = PRIOR + candles(OPENING + [SWEEP, CHOCH, RETEST])
    if mirror:
        bars = [dict(timestamp=b['timestamp'], open=2000-b['open'], high=2000-b['low'],
                     low=2000-b['high'], close=2000-b['close']) for b in bars]
    radar = {}
    assert not scan_traps_and_breakouts(bars, 'NIFTY', now=bars[-2]['timestamp'], radar=radar)
    assert radar['candidate_type'] == 'NO_TRADE'
    signals = scan_traps_and_breakouts(bars, 'NIFTY', radar=radar)
    assert len(signals) == 1
    signal = signals[0]
    assert signal['candidate_type'] == radar['candidate_type'] == pattern
    assert signal['label'] == label
    assert signal['direction'] == direction
    assert signal['signal_stage'] == 'CONFIRMED_RETEST'
    assert signal['decision_time_ist'] == bars[-1]['timestamp'].isoformat()
    assert signal['planned_rr'] >= 2
    assert signal['spot_stop'] < 942 if mirror else signal['spot_stop'] > 1058
    assert signal['spot_target'] == (1115 if mirror else 885)
    assert signal['research_only'] and not signal['orders_enabled']
    assert signal['probability'] is None


@pytest.mark.parametrize('mirror', [False, True])
def test_genuine_breakout_requires_consecutive_closes_and_hold(mirror):
    bars = PRIOR + candles(OPENING + [(1035, 1065, 1035, 1060), (1060, 1070, 1056, 1065),
                                    (1065, 1075, 1053, 1069), (1069, 1071, 1049, 1056)])
    if mirror:
        bars = [dict(timestamp=b['timestamp'], open=2000-b['open'], high=2000-b['low'],
                     low=2000-b['high'], close=2000-b['close']) for b in bars]
    radar = {}
    assert not scan_traps_and_breakouts(bars[:-1], 'NIFTY', radar=radar)
    assert radar['candidate_type'] == 'NO_TRADE'
    assert not scan_traps_and_breakouts(bars, 'NIFTY', radar=radar)
    assert radar['candidate_type'] == ('TRUE_DOWN' if mirror else 'TRUE_UP')
    assert radar['signal_stage'] == 'CONFIRMED_HOLD'


@pytest.mark.parametrize('tail', [
    [SWEEP, CHOCH, (1014, 1064, 1003, 1005), RETEST],  # Sweep extreme breached
    [SWEEP, (1020, 1033, 997, 1008), RETEST],  # Low crossed without displacement
    [SWEEP, CHOCH, (1007, 1009, 994, 1000)],  # No retest
    [(1035, 1065, 1035, 1060)] * 3 + [SWEEP, CHOCH, RETEST],  # Reclaim after K
])
def test_invalidation_and_incomplete_confirmation(tail):
    radar = {}
    assert not scan_traps_and_breakouts(PRIOR + candles(OPENING + tail), 'NIFTY', radar=radar)
    assert radar['candidate_type'] == 'NO_TRADE'


def test_dispatcher_publishes_trap_and_clears_radar_after_invalidation(tmp_path, monkeypatch):
    # The sweep is also a shooting star. Isolate the trap's Hero path from that earlier wave.
    monkeypatch.setattr('smc.multi_strategy_terminal.scan_candlestick_signals', lambda *args, **kwargs: [])
    bars = PRIOR + candles(OPENING + [SWEEP, CHOCH, RETEST, (1005, 1070, 1005, 1065)])
    (tmp_path / 'live_nifty.jsonl').write_text('\n'.join(json.dumps({
        **bar, 'timestamp': bar['timestamp'].isoformat(), 'symbol': 'NIFTY',
    }) for bar in bars), encoding='utf-8')

    confirmed = multi_strategy_payload(tmp_path, 'NIFTY', now=bars[-2]['timestamp'])
    signal, = confirmed['signals']['trap_detector']
    assert confirmed['trap_radar']['candidate_type'] == 'BULL_TRAP'
    assert signal['setup_id'] in confirmed['recommendation_ids']
    assert confirmed['confirmed_hero']['strategy'] == 'Trap Radar'

    invalidated = multi_strategy_payload(tmp_path, 'NIFTY', now=bars[-1]['timestamp'])
    assert invalidated['trap_radar']['candidate_type'] == 'NO_TRADE'
    card, = invalidated['strategies']['trap_detector']['cards']
    assert card['outcome']['status'] == 'SL_HIT'
    assert signal['setup_id'] in invalidated['recommendation_ids']


def test_atr_gap_buffer_and_reclaim_boundary():
    bars = candles([(100, 102, 98, 101), (110, 112, 109, 110), (109, 111, 106, 108)])
    assert compute_atr_5m(bars) is None
    assert compute_atr_5m(bars, 2) == 8
    assert not detect_candidate_events(bars, {'PDH': 111}, 1)
    event, = detect_candidate_events(bars, {'PDH': 109}, 1)
    assert evaluate_reclaim(event, bars, 1) is None
    assert evaluate_reclaim(event, bars, 2) == 2
    assert evaluate_choch(bars, (111, 109)) == 0


def _card(index, *, direction='BEARISH', reward=40, risk=20):
    at = datetime(2026, 11, 20, 9, 35, tzinfo=IST) + timedelta(minutes=index)
    sign = -1 if direction == 'BEARISH' else 1
    return dict(setup_id=f'{index}:{direction}', outcome={'status': 'ACTIVE'},
                signal=dict(timestamp=at.isoformat(), direction=direction, index_target_pts=reward,
                            index_sl_pts=risk, entry=1000, stop_loss=1000-sign*risk,
                            target=1000+sign*reward))


def test_curated_wave_boundary_daily_cap_and_market_targets():
    cards = [_card(i) for i in range(0, 275, 25)] + [
        _card(24), _card(1, reward=39), _card(2, reward=40, risk=21),
        _card(3, direction='BULLISH'), _card(27, direction='BULLISH', reward=130),
    ]
    strategies = {'orb': {'cards': list(reversed(cards))}}
    accepted = _curate_recommendations('NIFTY', strategies)
    assert len(accepted) == 10
    assert accepted[:3] == ['0:BEARISH', '3:BULLISH', '25:BEARISH']
    assert _curate_recommendations('SENSEX', strategies) == ['27:BULLISH']


@pytest.mark.parametrize('master_bias,exhaustion,expected', [
    ('BEARISH', False, 'Trap Radar'), ('BULLISH', True, 'Trap Radar'),
    ('BULLISH', False, 'Opening Range Breakout'),
])
def test_hero_prioritizes_bias_aligned_or_exhaustion_confirmed_reversals(master_bias, exhaustion, expected):
    trap, orb = _card(0), _card(1, direction='BULLISH')
    trap['signal'].update(candidate_type='BULL_TRAP', counter_trend_exhaustion=exhaustion)
    strategies = {'trap_detector': {'cards': [trap]}, 'orb': {'cards': [orb]}}
    hero = build_confirmed_hero_setup('NIFTY', PRIOR, [], {'master_bias': master_bias}, strategies,
                                      now=datetime(2026, 11, 20, 10, tzinfo=IST))
    assert hero['strategy'] == expected
