from datetime import datetime, timedelta, timezone
import pytest

from smc.backtest import BacktestConfig, ExitReason, Signal, walk_forward_backtest
from smc.models import Candle, IndexSetup, Side

T=datetime(2026,1,1,tzinfo=timezone.utc)

def bars(prices):
    return [Candle(T+timedelta(minutes=i),*v) for i,v in enumerate(prices)]

def long_signal(prefix):
    if len(prefix)==2:
        return Signal(IndexSetup("NIFTY",Side.CE,100,90,160,True,"RESEARCH"),1)
    return None

def short_signal(prefix):
    if len(prefix)==2:
        return Signal(IndexSetup("NIFTY",Side.PE,100,110,40,True,"RESEARCH"),1)
    return None

def test_next_bar_open_entry_no_same_bar_fill():
    cs=bars([(100,102,98,100),(100,102,98,100),
             (101,108,100,106),(108,162,103,161)])
    r=walk_forward_backtest(cs,long_signal)
    assert len(r.trades)==1
    assert r.trades[0].signal_index==1
    assert r.trades[0].entry_index==2
    assert r.trades[0].entry_price==101
    assert r.trades[0].exit_reason==ExitReason.TARGET

def test_stop_wins_when_both_touch_same_bar():
    cs=bars([(100,101,99,100),(100,101,99,100),
             (101,165,89,110)])
    r=walk_forward_backtest(cs,long_signal)
    assert r.trades[0].exit_reason==ExitReason.STOP
    assert r.trades[0].exit_price==90

def test_short_trade_and_transaction_cost():
    cs=bars([(100,101,99,100),(100,101,99,100),
             (99,100,37,39)])
    r=walk_forward_backtest(cs,short_signal,
                            BacktestConfig(round_trip_cost_points=3))
    assert r.trades[0].exit_reason==ExitReason.TARGET
    assert r.trades[0].net_index_points==56

def test_gap_through_stop_uses_open():
    cs=bars([(100,101,99,100),(100,101,99,100),
             (95,97,84,92),(85,91,83,87)])
    r=walk_forward_backtest(cs,long_signal)
    # Stops not hit on initial candle because gap entry still valid.
    assert r.trades[0].entry_price==95
    assert r.trades[0].exit_reason==ExitReason.STOP

def test_gap_outside_bracket_skips_entry():
    cs=bars([(100,101,99,100),(100,101,99,100),
             (165,170,161,168)])
    r=walk_forward_backtest(cs,long_signal)
    assert len(r.trades)==0 and r.signals_skipped==1

def test_no_lookahead_prefix_lengths():
    lengths=[]
    cs=bars([(100,101,99,100)]*6)
    def watch(prefix):
        lengths.append(len(prefix))
        assert all(x.timestamp<=prefix[-1].timestamp for x in prefix)
        return None
    r=walk_forward_backtest(cs,watch)
    assert lengths==[1,2,3,4,5]
    assert not r.trades

def test_invalid_signals_rejected():
    cs=bars([(100,101,99,100)]*4)
    def bad(prefix):
        if len(prefix)==2:
            return Signal(IndexSetup("NIFTY",Side.CE,100,99,101,True,"RESEARCH"),1)
        return None
    r=walk_forward_backtest(cs,bad)
    assert r.signals_rejected==1 and r.trades==()

def test_last_bar_no_entry():
    cs=bars([(100,101,99,100)]*3)
    def last(prefix):
        if len(prefix)==3:
            return Signal(IndexSetup("NIFTY",Side.CE,100,90,120,True,"RESEARCH"),2)
    assert not walk_forward_backtest(cs,last).trades

def test_incomplete_and_unordered_rejected():
    cs=bars([(100,101,99,100)]*3)
    with pytest.raises(ValueError):
        walk_forward_backtest(cs[::-1],long_signal)
    incomplete=cs.copy()
    x=incomplete[2]
    incomplete[2]=Candle(x.timestamp,x.open,x.high,x.low,x.close,complete=False)
    with pytest.raises(ValueError):
        walk_forward_backtest(incomplete,long_signal)

def test_time_exit_and_max_drawdown():
    cs=bars([(100,101,99,100),(100,101,99,100),
             (100,105,95,102),(102,108,94,98),(98,105,95,97)])
    r=walk_forward_backtest(cs,long_signal,BacktestConfig(max_holding_bars=2))
    assert r.trades[0].exit_reason==ExitReason.TIME_EXIT
    assert r.trades[0].exit_index==3
    assert r.trades[0].net_index_points==-2
    assert r.max_drawdown_points==2

def test_no_option_pnl_claim_and_fee_slippage():
    cs=bars([(100,101,99,100),(100,101,99,100),
             (101,161,100,160)])
    r=walk_forward_backtest(cs,long_signal,BacktestConfig(
        entry_slippage_points=1,exit_slippage_points=1,
        round_trip_cost_points=2))
    assert r.mode=="INDEX_POINTS_ONLY_NOT_OPTION_PNL"
    assert r.trades[0].net_index_points==55
