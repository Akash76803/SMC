from datetime import datetime,timedelta,timezone
from smc.models import Candle
from smc.historical_replay import ReplayConfig
from smc.phase5_report import replay_archetype
from smc.phase5_setups import BREAKOUT,CONTINUATION
def bars():
    begin=datetime(2026,11,11,9,16,tzinfo=timezone.utc)
    return [Candle(begin+timedelta(minutes=i),100,101,99,100)
            for i in range(20)]
def test_two_strategies_report_independently_and_never_invent_trades():
    for name in (BREAKOUT,CONTINUATION):
        result=replay_archetype(bars(),[],ReplayConfig("NIFTY"),name)
        assert result.strategy==name
        assert result.trades==()
        assert result.net_index_points==0
        assert result.win_rate is None
        assert result.sessions==1
        assert result.signals_emitted==0
def test_trade_count_is_not_count_of_rejected_candidates():
    report=replay_archetype(bars(),[],ReplayConfig("NIFTY"),BREAKOUT)
    assert report.signals_rejected==0
    assert report.risk_rejections==()
