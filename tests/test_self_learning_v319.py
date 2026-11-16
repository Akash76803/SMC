"""Momentum and option-learning safety: real quote history or NO SIGNAL."""
from datetime import datetime,timedelta,timezone
from zoneinfo import ZoneInfo

from smc.option_momentum_v319 import rank_momentum, MomentumPolicy
from smc.option_quote_tape_v319 import append_snapshot, read_recent, live_momentum
from smc.self_learning_research_v319 import evaluate_walk_forward, metrics
from smc.phase6_premium import Quote, Signal
from smc.models import Side

IST=ZoneInfo("Asia/Kolkata")
T=datetime(2026,11,16,10,0,tzinfo=IST)


def record(t,*,strike=25200,side="CE",bid=70,ask=71,vol=100):
    return {
        "market":"NIFTY","trading_symbol":f"NIFTY17NOV26{strike}{side}",
        "expiry":"2026-11-17","side":side,"strike":strike,"bid":bid,
        "ask":ask,"volume":vol,"bid_qty":50,"ask_qty":50,
        "quote_at":t.isoformat(),"delta":None,"iv":None,
        "lot_size":65,"research_only":True,"orders_enabled":False,
    }


def test_far_otm_is_allowed_only_with_observed_momentum():
    now=T+timedelta(seconds=45)
    # ATM is 25000; 25200 is 4 steps OTM. An ATM quote alone
    # without its own momentum history must never outrank it.
    rows=[record(T+timedelta(seconds=i),strike=25000,bid=100,ask=101,vol=100)
          for i in (0,20,40)]
    rows+= [
        record(T+timedelta(seconds=sec),strike=25200,bid=bid,ask=bid+1,vol=volume)
        for sec,bid,volume in ((0,70,100),(20,73,130),(40,77,180))]
    rows += [record(T+timedelta(seconds=sec),strike=strike,
                    bid=90,ask=91,vol=100) for strike in
             (25050,25100,25150) for sec in (0,20,40)]
    ranked=rank_momentum(rows,symbol="NIFTY",spot=25010,
                         now=now,side="CE")
    assert ranked
    assert ranked[0]["strike"]==25200
    assert ranked[0]["moneyness"]=="OTM"
    assert ranked[0]["otm_steps"]==4
    assert ranked[0]["entry_is_executable"] is False
    assert ranked[0]["premium_stop"] is None
    assert ranked[0]["premium_exit_target"] is None


def test_no_history_no_momentum_and_future_quotes_ignored():
    assert rank_momentum([],symbol="NIFTY",spot=25000,now=T,side="CE")==[]
    future=[record(T+timedelta(minutes=1+i),bid=70+5*i,vol=100+10*i)
            for i in range(3)]
    assert rank_momentum(future,symbol="NIFTY",spot=25000,now=T,side="CE")==[]


def test_wide_spread_or_flat_volume_does_not_promote_far_otm():
    rows=[record(T+timedelta(seconds=i*20),bid=70+i*5,
                 ask=100+i*5,vol=100) for i in range(3)]
    rows += [record(T+timedelta(seconds=i*20),strike=25000,bid=100,
                    ask=101,vol=100) for i in range(3)]
    assert rank_momentum(rows,symbol="NIFTY",spot=25000,
                         now=T+timedelta(seconds=41),side="CE")==[]


def test_quote_tape_requires_verified_broker_rows(tmp_path):
    path=tmp_path/"tape.jsonl"
    item=record(T)
    snapshot={"symbol":"NIFTY","research_only":True,"orders_enabled":False,
              "contracts":[item]}
    assert append_snapshot(path,snapshot)==1
    assert read_recent(path,symbol="NIFTY",now=T)==[item]
    assert read_recent(path,symbol="SENSEX",now=T)==[]
    assert live_momentum(path,symbol="NIFTY",spot=25000,now=T)["candidates"]==[]
    import pytest
    with pytest.raises(ValueError):
        append_snapshot(path,{**snapshot,"orders_enabled":True})


def quotes_for_days(days=40):
    signals=[];quotes=[]
    for d in range(days):
        stamp=datetime(2026,9,1,10,0,tzinfo=IST)+timedelta(days=d)
        signals.append(Signal(stamp,"NIFTY",Side.CE,"SMC_PAPER"))
        bid_out=130 if d%3 else 82
        quotes.extend((
            Quote(stamp+timedelta(seconds=60),"NIFTY",Side.CE,25000,
                  stamp+timedelta(days=60),99,100,65,100),
            Quote(stamp+timedelta(seconds=120),"NIFTY",Side.CE,25000,
                  stamp+timedelta(days=60),bid_out,bid_out+1,65,200),
        ))
    return signals,quotes


def test_walk_forward_can_never_auto_promote_even_with_positive_samples():
    signals,quotes=quotes_for_days()
    outcome=evaluate_walk_forward(signals,quotes,min_train_days=20,
                                   min_validation_days=10,
                                   min_train_trades=10,
                                   min_validation_trades=5)
    assert outcome["train_days"]==30
    assert outcome["validation_days"]==10
    assert outcome["selected"] is not None
    assert outcome["promotion_allowed"] is False
    assert outcome["production_settings_modified"] is False
    assert outcome["realized_broker_pnl"] is False


def test_walk_forward_fails_closed_with_too_few_days():
    signals,quotes=quotes_for_days(5)
    output=evaluate_walk_forward(signals,quotes)
    assert output["status"]=="INSUFFICIENT_EVIDENCE"
    assert output["selected"] is None
    assert output["promotion_allowed"] is False


def test_replay_metrics_drawdown_research_only():
    assert metrics([])["win_rate"] is None
    assert metrics([])["trades"]==0
