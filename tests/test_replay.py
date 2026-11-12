import io
from datetime import datetime,timedelta,timezone

import pytest

from smc.csv_data import read_candles_csv
from smc.historical_replay import ReplayConfig, SMCReplay
from smc.backtest import walk_forward_backtest
from smc.models import Candle

T=datetime(2026,11,12,9,15,tzinfo=timezone.utc)


def candle(i,offset=0,step=1):
    price=100+offset
    return Candle(T+timedelta(minutes=i*step),price,price+2,price-2,price)


def test_csv_aware_timestamps_and_volume():
    text="timestamp,open,high,low,close,volume\n2026-11-12T09:16:00+05:30,100,103,99,101,1000\n2026-11-12T09:17:00+05:30,101,104,100,103,1200\n"
    cs=read_candles_csv(io.StringIO(text))
    assert len(cs)==2 and cs[0].volume==1000
    assert cs[0].timestamp.utcoffset()==timedelta(hours=5,minutes=30)


def test_csv_rejects_naive_and_malformed_data():
    bad=[
        "timestamp,open,high,low,close\n2026-01-01T09:15:00,100,102,98,101\n",
        "timestamp,open,high,low,close\n2026-01-01T09:15:00+00:00,100,90,98,101\n",
        "timestamp,open,high,low,close\n2026-01-01T09:15:00+00:00,100,102,98,101\n2026-01-01T09:15:00+00:00,100,102,98,101\n",
    ]
    for value in bad:
        with pytest.raises(ValueError):
            read_candles_csv(io.StringIO(value))


def test_csv_requires_columns_and_nonempty_rows():
    for value in ("timestamp,close\n", "timestamp,open,high,low,close\n"):
        with pytest.raises(ValueError):
            read_candles_csv(io.StringIO(value))


def test_htf_future_bars_excluded_and_prefix_is_stable():
    ltf=[candle(i) for i in range(20)]
    htf=[candle(i,step=60) for i in range(25)]
    r=SMCReplay(ReplayConfig("NIFTY"),htf)
    snap=r.snapshot(tuple(ltf))
    assert snap.htf_bars_available==0
    assert snap.reason=="HTF_WARMUP"
    future=[candle(i+25,step=60) for i in range(5)]
    r2=SMCReplay(ReplayConfig("NIFTY"),htf+future)
    assert r2.snapshot(tuple(ltf))==snap


def test_htf_only_available_on_full_close():
    ltf=[candle(i) for i in range(61)]
    htf=[candle(i,step=60) for i in range(13)]
    r=SMCReplay(ReplayConfig("NIFTY"),htf)
    assert r.snapshot(tuple(ltf[:60])).htf_bars_available==0
    assert r.snapshot(tuple(ltf[:61])).htf_bars_available==1


def test_signal_fn_causal_and_no_invented_signals():
    ltf=[candle(i) for i in range(30)]
    htf=[candle(i,step=60) for i in range(20)]
    engine=SMCReplay(ReplayConfig("NIFTY"),htf)
    report=walk_forward_backtest(ltf,engine)
    assert len(engine.snapshots)==len(ltf)-1
    assert not report.trades
    assert all(x.signal is None for x in engine.snapshots)


def test_replay_config_rejects_invalid_parameters():
    with pytest.raises(ValueError):
        ReplayConfig("BANKNIFTY")
    with pytest.raises(ValueError):
        ReplayConfig("NIFTY",htf_duration_minutes=0)
    with pytest.raises(ValueError):
        ReplayConfig("NIFTY",internal_k=5,external_k=2)


def test_replay_rejects_unsorted_htf_data():
    with pytest.raises(ValueError):
        SMCReplay(ReplayConfig("NIFTY"),[candle(2),candle(1)])


def test_warmup_produces_no_fake_index_trade():
    ltf=[candle(i) for i in range(50)]
    htf=[candle(i,step=60) for i in range(15)]
    engine=SMCReplay(ReplayConfig("SENSEX"),htf)
    report=walk_forward_backtest(ltf,engine)
    assert report.total_net_index_points==0
    assert report.win_rate is None
