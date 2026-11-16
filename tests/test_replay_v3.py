from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from smc.decision_v3 import ResearchBracket
from smc.models import Candle
from smc.replay_v3 import evaluate_level_outcomes, replay_unified_reversal

T=datetime(2026,11,16,9,16,tzinfo=ZoneInfo("Asia/Kolkata"))

def bars(vals):
    return [Candle(T+timedelta(minutes=i),*v) for i,v in enumerate(vals)]

def base():
    return bars([(100,101,99,100)]*5)

def outcomes(vals, **kwargs):
    cs=bars(vals)
    args=dict(candles=cs,confirmation_index=0,
              bracket=ResearchBracket(100,90,120,"BULLISH"),
              levels=(("T1",120),))
    args.update(kwargs)
    return evaluate_level_outcomes(**args)[0]

def test_t1_hit_on_next_candle():
    r=outcomes([(100,101,99,100),(100,122,98,120)])
    assert (r.result,r.resolved_index)==("HIT",1)

def test_stop_first():
    r=outcomes([(100,101,99,100),(100,102,89,90)])
    assert r.result=="STOP_FIRST"

def test_same_bar_target_and_stop_ambiguous():
    r=outcomes([(100,101,99,100),(100,125,85,105)])
    assert r.result=="AMBIGUOUS_SAME_BAR"

def test_confirmation_candle_never_used_for_outcome():
    r=outcomes([(100,130,80,100),(100,105,95,100)])
    assert r.result=="TIME_EXIT"

def test_missing_future_bars_is_not_a_winner():
    r=outcomes([(100,101,99,100)])
    assert r.result=="NO_FUTURE_BARS"

def test_bearish_target_uses_low_and_stop_high():
    r=outcomes([(100,101,99,100),(100,102,79,80)],
        bracket=ResearchBracket(100,110,80,"BEARISH"),levels=(("T1",80),))
    assert r.result=="HIT"

def test_time_exit_not_called_profit():
    r=outcomes([(100,101,99,100),(100,105,95,100),(100,107,94,101)],
               max_holding_bars=2)
    assert r.result=="TIME_EXIT" and r.resolved_index==2

def test_gap_fail_closed():
    cs=base()
    cs[1]=Candle(T+timedelta(minutes=2),100,101,99,100)
    cs[2]=Candle(T+timedelta(minutes=3),100,101,99,100)
    cs[3]=Candle(T+timedelta(minutes=4),100,101,99,100)
    cs[4]=Candle(T+timedelta(minutes=5),100,101,99,100)
    r=evaluate_level_outcomes(
        candles=cs,confirmation_index=0,
        bracket=ResearchBracket(100,90,120,"BULLISH"),
        levels=(("T1",120),))[0]
    assert r.result=="DATA_GAP"

def test_tiers_resolve_independently():
    cs=bars([(100,101,99,100),(100,123,99,120),(120,143,110,140)])
    r=evaluate_level_outcomes(
        candles=cs,confirmation_index=0,
        bracket=ResearchBracket(100,90,120,"BULLISH"),
        levels=(("T1",120),("T2",140)))
    assert [x.result for x in r]==["HIT","HIT"]

def test_unordered_rejected():
    cs=base()
    with pytest.raises(ValueError,match="UNORDERED_REPLAY_BARS"):
        evaluate_level_outcomes(
            candles=[cs[1],cs[0]],confirmation_index=0,
            bracket=ResearchBracket(100,90,120,"BULLISH"),
            levels=(("T1",120),))

def test_empty_replay_summary_no_option_pnl():
    r=replay_unified_reversal(symbol="NIFTY",ltf=[],
        monthly=[],weekly=[],daily=[])
    assert r.as_dict()["option_pnl"] is None
    assert r.evaluated_prefixes==0

def test_no_unverified_ltf_data_generates_trades():
    c=bars([(100,101,99,100)]*18)
    r=replay_unified_reversal(symbol="NIFTY",ltf=c,
        monthly=[],weekly=[],daily=[],data_healthy=False)
    assert r.status_counts=={"DATA_BLOCKED":3}
    assert r.diagnostic_brackets==0
    assert r.as_dict()["live_orders_enabled"] is False

def test_future_htf_bars_not_used_to_backfill():
    c=bars([(100,101,99,100)]*17)
    future=Candle(T+timedelta(days=1),100,101,99,100)
    r=replay_unified_reversal(symbol="NIFTY",ltf=c,
        monthly=[future],weekly=[future],daily=[future],
        data_healthy=True)
    assert r.evaluated_prefixes==2
    assert r.diagnostic_brackets==0

def test_incomplete_replay_rejected():
    c=base()
    c[2]=Candle(c[2].timestamp,100,101,99,100,complete=False)
    with pytest.raises(ValueError,match="INCOMPLETE_LTF_REPLAY"):
        replay_unified_reversal(symbol="NIFTY",ltf=c,
            monthly=[],weekly=[],daily=[])

def test_no_shortcut_trade_wins_or_option_pnl():
    c=bars([(100,101,99,100)]*18)
    r=replay_unified_reversal(symbol="NIFTY",ltf=c,
        monthly=[],weekly=[],daily=[],data_healthy=True)
    assert r.as_dict()["option_pnl"] is None
    assert r.diagnostic_brackets==0

def test_v38_observation_diagnostics_are_json_safe():
    from smc.replay_v3 import ReplayObservation
    o=ReplayObservation(
        3,"2026-11-16T09:19:00+05:30","NO_TRADE","MSS_CONFIRMED",
        "BULLISH",None,(),diagnostics={
            "pending_stages":["MSS_CONFIRMED"],
            "nearest_target_level":None,
            "index_entry":None})
    value=o.as_dict()
    assert value["diagnostics"]["pending_stages"]==["MSS_CONFIRMED"]
    assert value["level_outcomes"]==[]

def test_v38_no_observations_still_has_safe_serialization():
    c=bars([(100,101,99,100)]*18)
    result=replay_unified_reversal(
        symbol="NIFTY",ltf=c,monthly=[],weekly=[],daily=[],data_healthy=False)
    assert result.as_dict()["observations"]==[]
