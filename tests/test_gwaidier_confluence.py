"""Gwaidier research upgrade: causal evidence, targeting and legacy isolation."""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace as Obj

import pytest

from smc import ict_lifecycle_v316 as lifecycle
from smc import live_research_v312 as live
from smc.live_setup_screen_v317 import build_setup_screen, CONFLUENCES
from smc.models import Candle, Pivot, Zone
from smc.app_terminal_v316 import HTML, live_screen_payload

START = datetime(2026, 11, 17, 9, 16, tzinfo=timezone(timedelta(hours=5, minutes=30)))


def bars(n=24):
    data = [Candle(START+timedelta(minutes=i), 100, 103, 98, 101) for i in range(n)]
    data[15] = Candle(data[15].timestamp, 100, 109, 99, 108)
    for i in range(16, n):
        data[i] = Candle(data[i].timestamp, 104, 106, 100, 104)
    return data


@pytest.fixture
def evidence(monkeypatch):
    """Explicit upstream structural evidence; lifecycle transitions remain real."""
    shift = Obj(candle_index=15, direction='BULLISH', kind='BOS', tier='EXTERNAL')
    block = Obj(structure_index=15, direction='BULLISH', lower=99, upper=101, source_index=13)
    sweep = Obj(kind='SWEEP', candle_index=13, level=Obj(kind='SSL', price=98))
    pivot = Pivot('LOW', 12, 99, 12)
    monkeypatch.setattr(lifecycle, 'confirmed_pivots', lambda *args, **kwargs: [pivot])
    monkeypatch.setattr(lifecycle, 'structure_hierarchy', lambda *args: ())
    monkeypatch.setattr(lifecycle, 'detect_structure', lambda data, **kwargs: [shift] if len(data)>15 else [])
    monkeypatch.setattr(lifecycle, 'liquidity_map', lambda *args: ([], [sweep]))
    monkeypatch.setattr(lifecycle, 'find_order_blocks', lambda *args: [block])
    monkeypatch.setattr(lifecycle, 'fair_value_gaps', lambda data: [Zone('BULLISH_FVG', 100, 102, 15)] if len(data)>15 else [])
    monkeypatch.setattr(lifecycle, 'atr', lambda *args: 2)
    return shift, block, sweep, pivot


def dr(eq=110):
    return dict(high=150, low=70, equilibrium=eq, timeframe='15m', position='DISCOUNT')


def test_default_zone_rejection_and_opt_in_counter(evidence):
    legacy, = lifecycle.scan_ict_lifecycles(bars(), dealing_range=dr(90))
    counter, = lifecycle.scan_ict_lifecycles(bars(), dealing_range=dr(90), allow_counter=True)
    assert legacy['state'] == 'REJECTED_WRONG_ZONE'
    assert counter['state'] == 'RETEST_CONFIRMED_RESEARCH'
    assert counter['setup_type'] == 'COUNTER_PULLBACK'
    assert counter['target_reference'] == 90
    assert counter['target_kind'] == 'HTF_EQUILIBRIUM'
    # Classification never turns a target behind a bullish entry into a trade.
    assert counter['target_is_directional'] is False
    assert counter['order_allowed'] is False


def test_pro_trend_external_target_and_prefix_equivalence(evidence):
    a = lifecycle.scan_ict_lifecycles(bars(), as_of=16, dealing_range=dr(), allow_counter=True)
    b = lifecycle.scan_ict_lifecycles(bars()[:17], dealing_range=dr(), allow_counter=True)
    assert a == b
    row, = a
    assert row['setup_type'] == 'PRO_TREND'
    assert row['poi_category'] == 'BOS_SWEEP'
    assert row['target_reference'] == 150
    assert row['target_rr_min'] == 3
    assert row['target_is_directional'] is True


def test_causal_htf_history_never_uses_future_context(evidence):
    future = {**dr(), 'available_at': bars()[20].timestamp.isoformat()}
    row, = lifecycle.scan_ict_lifecycles(bars(), dealing_range={**dr(), 'history': [future]}, allow_counter=True)
    assert row['htf_context'] is None
    assert row['setup_type'] is None
    known = {**dr(), 'available_at': bars()[14].timestamp.isoformat()}
    row, = lifecycle.scan_ict_lifecycles(bars(), dealing_range={**dr(), 'history': [known, future]}, allow_counter=True)
    assert row['htf_context'] == known


@pytest.mark.parametrize('kind,tier,block_index,origin,expected', [
    ('CHoCH', 'INTERNAL', 9, None, 'CHOCH_SWEEP'),
    ('BOS', 'EXTERNAL', 9, None, 'BOS_SWEEP'),
    ('BOS', 'INTERNAL', 5, 5, 'EXTREME_OB'),
    ('BOS', 'INTERNAL', 9, 2, 'DECISIONAL_OB'),
    ('BOS', 'INTERNAL', 5, 2, 'TRAP_MIDDLE_OB'),
])
def test_poi_taxonomy(kind, tier, block_index, origin, expected):
    assert lifecycle.classify_poi(block=Obj(source_index=block_index),
        idm=Obj(index=10), sweep=Obj(), shift=Obj(kind=kind,tier=tier),
        origin=Obj(index=origin) if origin is not None else None) == expected


def test_idm_wick_sweep_and_missing_poi():
    assert lifecycle.classify_poi(idm=Obj(), sweep=Obj()) == 'IDM_SWEEP'
    assert lifecycle.classify_poi() == 'UNVERIFIED'


@pytest.mark.parametrize('tier', ['INTERNAL', 'EXTERNAL'])
def test_middle_ob_cannot_trigger_entry(evidence, tier):
    shift, block, _, _ = evidence
    shift.tier = tier
    block.source_index = 5
    row, = lifecycle.scan_ict_lifecycles(bars(), dealing_range=dr(), allow_counter=True)
    assert row['poi_category'] == 'TRAP_MIDDLE_OB'
    assert row['state'] == 'TRAP_IGNORED'
    assert row['retest_at'] is None
    assert row['poi_valid'] is False


def test_volume_imbalance_wick_overlap_body_gap_and_direction():
    a = Candle(START, 100, 105, 99, 101)
    b = Candle(START+timedelta(minutes=1), 103, 106, 102, 104)
    vi, = lifecycle.find_volume_imbalances([a,b])
    assert (vi.kind, vi.lower, vi.upper, vi.created_at) == ('BULLISH_VOLUME_IMBALANCE',101,103,1)
    reverse = [Candle(START,103,106,102,104), Candle(START+timedelta(minutes=1),100,105,99,101)]
    assert lifecycle.find_volume_imbalances(reverse)[0].kind == 'BEARISH_VOLUME_IMBALANCE'
    assert lifecycle.find_volume_imbalances([a,Candle(b.timestamp,101,106,100,104)]) == []
    assert lifecycle.find_volume_imbalances([a,Candle(b.timestamp,106,109,106,108)]) == []
    assert lifecycle.find_volume_imbalances([a,Candle(b.timestamp,103,106,102,104,complete=False)]) == []


def test_volume_imbalance_substitutes_for_fvg(evidence, monkeypatch):
    monkeypatch.setattr(lifecycle, 'fair_value_gaps', lambda data: [])
    monkeypatch.setattr(lifecycle, 'find_volume_imbalances', lambda data: [Zone('BULLISH_VOLUME_IMBALANCE',100,102,15)])
    row, = lifecycle.scan_ict_lifecycles(bars(), dealing_range=dr(), allow_counter=True)
    assert row['state'] == 'RETEST_CONFIRMED_RESEARCH'
    assert row['fvg_zone'] is None
    assert row['volume_imbalance_zone'] == [100,102]
    monkeypatch.setattr(lifecycle, 'find_volume_imbalances', lambda data: [])
    row, = lifecycle.scan_ict_lifecycles(bars(), dealing_range=dr(), allow_counter=True)
    assert row['state'] == 'WAITING_FOR_IMBALANCE'


def test_htf_preference_and_fallback():
    snapshots = {'timeframes': {'1h': {'confirmed_high': 150, 'confirmed_low': 80},
                               '15m': {'confirmed_high': 130, 'confirmed_low': 90}}}
    assert live._select_htf_context(snapshots,100)['timeframe'] == '1h'
    snapshots['timeframes']['1h']['confirmed_low'] = None
    context = live._select_htf_context(snapshots,100)
    assert context['timeframe'] == '15m'
    assert context['source'] == '15M_CONFIRMED_PIVOTS'
    assert context['equilibrium'] == 110
    assert context['position'] == 'DISCOUNT'
    snapshots['timeframes']['15m']['confirmed_high'] = float('nan')
    assert live._select_htf_context(snapshots,100) is None


def test_real_htf_history_prefix_no_lookahead():
    wave = [0,1,5,1,0,-3,0,1,6,1,0,-4]
    data = [Candle(START+timedelta(minutes=i),100+wave[i//15],102+wave[i//15],98+wave[i//15],101+wave[i//15]) for i in range(180)]
    history = live._htf_context_history(data)
    assert history
    prefix = live._htf_context_history(data[:135])
    assert prefix == [c for c in history if c['available_at'] <= data[134].timestamp.isoformat()]
    assert all(c['timeframe'] == '15m' for c in history)


def screen_event():
    candidate = dict(setup_id='test', confluence_model='GWAIDIER_V1', direction='BULLISH',
        state='RETEST_CONFIRMED_RESEARCH', structure_kind='CHoCH',
        sweep_at=START.isoformat(), idm_at=START.isoformat(), sweep_level=90, idm_level=92,
        displacement_confirmed=True, ob_zone=[95,99], fvg_zone=[98,100], retest_at=START.isoformat(),
        setup_type='PRO_TREND', poi_category='EXTREME_OB', poi_valid=True, htf_context=dr())
    bracket = dict(setup_id='test', research_only=True, status='RESEARCH_INDEX_BRACKET_PASSES',
                   entry_close_reference=100, stop_reference=90, targets=[{'price':150}])
    return dict(research_only=True, orders_enabled=False, status='RESEARCH_ONLY', symbol='NIFTY',
                stream_quality={'quality_blocked':False}, ict_last_lifecycle=candidate,
                index_bracket_research=bracket)


def test_three_confluences_pass_without_option_greeks():
    result = build_setup_screen(screen_event(),live_status='RECENT_BAR')
    assert result['status'] == 'RESEARCH_SEQUENCE_OBSERVED'
    assert result['index_setup_status'] == 'PASS'
    assert result['missing_evidence'] == []
    assert set(result['confluences']) == set(CONFLUENCES)
    assert all(result['confluences'].values())
    assert result['option_pricing_status'] == 'UNAVAILABLE'
    assert result['entry'] is None and result['option_strike'] is None
    assert result['order_eligible'] is False


@pytest.mark.parametrize('change,missing', [
    ({'poi_category':'TRAP_MIDDLE_OB'},'HTF_POI_VALIDATED'),
    ({'htf_context':None},'HTF_POI_VALIDATED'),
    ({'displacement_confirmed':False},'DISPLACEMENT_CONFIRMED'),
    ({'fvg_zone':None},'DISPLACEMENT_CONFIRMED'),
    ({'retest_at':None},'MITIGATION_RETEST'),
    ({'state':'INVALIDATED'},'MITIGATION_RETEST'),
])
def test_each_confluence_blocks_independently(change, missing):
    event = screen_event()
    event['ict_last_lifecycle'].update(change)
    result = build_setup_screen(event,live_status='RECENT_BAR')
    assert result['status'] == 'WAIT'
    assert missing in result['missing_evidence']
    assert 'LIVE_OPTION_BID_ASK_GREEKS' not in result['missing_evidence']


def test_screen_vi_and_mismatched_bracket_and_stale_feed():
    event = screen_event()
    event['ict_last_lifecycle'].update(fvg_zone=None,volume_imbalance_zone=[98,100])
    assert build_setup_screen(event,live_status='RECENT_BAR')['status'] == 'RESEARCH_SEQUENCE_OBSERVED'
    event['index_bracket_research']['setup_id'] = 'other'
    assert build_setup_screen(event,live_status='RECENT_BAR')['confluences']['MITIGATION_RETEST'] is False
    assert not any(build_setup_screen(event,live_status='STALE')['confluences'].values())


def test_classified_bracket_keeps_risk_limits_and_rejects_wrong_target(monkeypatch):
    bracket = dict(status='RESEARCH_INDEX_BRACKET_PASSES', entry_close_reference=100,
                   stop_reference=90, min_target_required=30, reason='OK', research_only=True)
    monkeypatch.setattr(live,'research_bracket',lambda **kwargs:dict(bracket))
    row = dict(confluence_model='GWAIDIER_V1', poi_valid=True, setup_type='PRO_TREND',
               setup_id='test', direction='BULLISH', target_reference=150,
               target_kind='HTF_EXTERNAL_LIQUIDITY', target_rr_min=3)
    result = live._classified_bracket('NIFTY',bars(),row)
    assert result['status'] == 'RESEARCH_INDEX_BRACKET_PASSES'
    assert result['target_t1'] == 150
    row.update(setup_type='COUNTER_PULLBACK',target_reference=90,target_kind='HTF_EQUILIBRIUM')
    assert live._classified_bracket('NIFTY',bars(),row)['reason'] == 'CLASSIFIED_TARGET_WRONG_DIRECTION'
    row['target_reference'] = 115
    assert live._classified_bracket('NIFTY',bars(),row)['status'] == 'NO_VERIFIED_INDEX_BRACKET'


def test_dashboard_exposes_classification_and_three_confluences():
    for text in ('Gwaidier 3-Confluence Matrix','PRO-TREND (BOS TARGET)',
                 'COUNTER-PULLBACK (50% EQ TARGET)','htfDealingRange','HTF_POI_VALIDATED',
                 'DISPLACEMENT_CONFIRMED','Mitigation Retest & Bracket'):
        assert text in HTML


def test_retest_at_imbalance_and_nearest_internal_ob_cap(evidence, monkeypatch):
    _, block, _, _ = evidence
    block.upper = 205  # OB midpoint in premium, but a lower FVG can be retested.
    internal = Obj(structure_index=10, direction='BEARISH', lower=120, upper=123, source_index=9)
    monkeypatch.setattr(lifecycle, 'find_order_blocks', lambda *args: [block, internal])
    row, = lifecycle.scan_ict_lifecycles(bars(), dealing_range={**dr(150), 'high':230}, allow_counter=True)
    assert row['state'] == 'RETEST_CONFIRMED_RESEARCH'
    assert row['setup_type'] == 'COUNTER_PULLBACK'
    assert row['target_reference'] == 120
    assert row['target_is_directional'] is True


@pytest.mark.parametrize('range_value', [dict(low=100,high=90,equilibrium=95),
    dict(low=70,high=150,equilibrium=float('nan')),dict(low=70,high=150,equilibrium=160)])
def test_invalid_htf_ranges_fail_closed(evidence, range_value):
    with pytest.raises(ValueError,match='INVALID_DEALING_RANGE'):
        lifecycle.scan_ict_lifecycles(bars(),dealing_range=range_value,allow_counter=True)


def test_live_coordinator_passes_fallback_context_and_counter_opt_in(monkeypatch):
    wave = [0,1,5,1,0,-3,0,1,6,1,0,-4]
    data = [Candle(START+timedelta(minutes=i),100+wave[i//15],102+wave[i//15],
                   98+wave[i//15],101+wave[i//15]) for i in range(180)]
    captured = {}
    def capture(candles, **kwargs):
        captured.update(kwargs)
        return []
    monkeypatch.setattr(live, 'scan_ict_lifecycles', capture)
    engine = live.LiveResearchEngine('NIFTY')
    engine.builder = Obj(completed=data, symbol='NIFTY', quality_blocked=False,
                         gaps=0, ingest=lambda tick:data[-1], state=lambda:{'quality_blocked':False})
    report = engine.on_tick(None)
    assert captured['allow_counter'] is True
    assert captured['dealing_range']['timeframe'] == '15m'
    assert captured['dealing_range']['history']
    assert report['htf_context']['timeframe'] == '15m'
    assert 'history' not in report['htf_context']
    assert 'setup_type' in report
    assert report['orders_enabled'] is False
    assert report['ict_order_eligible'] is False


@pytest.mark.parametrize('bad_zone', [[],[100,98],[98,float('nan')]])
def test_malformed_imbalance_cannot_pass_confluence(bad_zone):
    event = screen_event()
    event['ict_last_lifecycle']['fvg_zone'] = bad_zone
    result = build_setup_screen(event,live_status='RECENT_BAR')
    assert result['confluences']['DISPLACEMENT_CONFIRMED'] is False


def test_classified_bracket_cannot_revive_stopped_setup(monkeypatch):
    monkeypatch.setattr(live,'research_bracket',lambda **kwargs:dict(
        status='NO_VERIFIED_INDEX_BRACKET',entry_close_reference=100,stop_reference=90,
        min_target_required=30,reason='STRUCTURAL_STOP_BREACHED',research_only=True))
    row = dict(confluence_model='GWAIDIER_V1',poi_valid=True,setup_type='PRO_TREND',
               direction='BULLISH',target_reference=150)
    assert live._classified_bracket('NIFTY',bars(),row)['status'] == 'NO_VERIFIED_INDEX_BRACKET'


def test_upgraded_stop_invalidation_and_retest_expiry(evidence):
    data = bars()
    data[16] = Candle(data[16].timestamp,100,102,97,98)
    row, = lifecycle.scan_ict_lifecycles(data,dealing_range=dr(),allow_counter=True)
    assert row['state'] == 'INVALIDATED'
    assert row['invalidated_at'] == data[16].timestamp.isoformat()
    data = bars()
    for i in range(16,len(data)):
        data[i] = Candle(data[i].timestamp,107,110,105,108)
    row, = lifecycle.scan_ict_lifecycles(data,dealing_range=dr(),allow_counter=True,max_retest_bars=2)
    assert row['state'] == 'EXPIRED'
    assert row['retest_at'] is None


def test_imbalance_must_exist_before_retest(evidence, monkeypatch):
    monkeypatch.setattr(lifecycle,'fair_value_gaps',lambda data:[Zone('BULLISH_FVG',100,102,18)])
    early, = lifecycle.scan_ict_lifecycles(bars(),as_of=17,dealing_range=dr(),allow_counter=True)
    assert early['state'] == 'WAITING_FOR_IMBALANCE'
    later, = lifecycle.scan_ict_lifecycles(bars(),dealing_range=dr(),allow_counter=True)
    assert later['retest_at'] == bars()[19].timestamp.isoformat()
