from smc.strategy_pdh_pdl import scan_pdh_pdl


def candle(day, minute, o, h, l, c):
    return dict(timestamp=f'2026-11-{day}T09:{minute}:00+05:30', open=o, high=h, low=l, close=c)


def test_acceptance_waits_for_break_and_uses_breakout_stop():
    bars = [candle(17, 30, 150, 200, 100, 150), candle(18, 30, 205, 215, 203, 213)]
    assert scan_pdh_pdl(bars) == []
    signal, = scan_pdh_pdl([*bars, candle(18, 45, 214, 220, 210, 219)])
    assert signal['pattern_or_trigger'] == 'PDH_ACCEPTANCE'
    assert (signal['entry'], signal['stop_loss'], signal['target']) == (215, 203, 239)
    assert signal['research_only'] and not signal['orders_enabled']


def test_rejection_targets_midpoint_and_enforces_reward_floor():
    previous = candle(17, 30, 150, 200, 100, 150)
    plans = {}
    signal, = scan_pdh_pdl([previous, candle(18, 30, 112, 115, 98, 108)], trade_plans=plans)
    assert signal['target'] == 150
    assert plans[signal['setup_id']]['target_2'] == 200
    assert scan_pdh_pdl([previous, candle(18, 30, 130, 131, 95, 130)]) == []


def test_five_minute_break_can_trigger_before_next_confirmation():
    from datetime import datetime, timedelta

    start = datetime.fromisoformat('2026-11-18T09:20:00+05:30')
    previous = [dict(candle(17, 30, 150, 200, 100, 150),
                     timestamp=(start - timedelta(days=1) + timedelta(minutes=5 * i)).isoformat())
                for i in range(3)]
    current = [dict(timestamp=(start + timedelta(minutes=5 * i)).isoformat(),
                    open=205, high=215, low=203, close=213) for i in range(3)]
    breaking = dict(timestamp=(start + timedelta(minutes=15)).isoformat(),
                    open=214, high=220, low=210, close=219)
    signal, = scan_pdh_pdl(previous + current + [breaking], interval_minutes=5)
    assert signal['timestamp'] == breaking['timestamp']
    assert signal['timeframe'] == '5m'
