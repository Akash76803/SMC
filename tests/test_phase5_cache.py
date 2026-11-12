from datetime import datetime,timedelta,timezone
from smc.models import Candle
from smc.historical_replay import ReplayConfig
from smc.phase5_setups import _active_htf_bias,_bias_for_closed_htf
def test_hourly_bias_cache_reuses_same_closed_bar_prefix():
    _bias_for_closed_htf.cache_clear()
    start=datetime(2026,11,11,9,15,tzinfo=timezone.utc)
    hourly=tuple(Candle(start+timedelta(hours=i),100,101,99,100) for i in range(14))
    config=ReplayConfig("NIFTY")
    assert _active_htf_bias(hourly,start+timedelta(hours=14),config) is None
    first=_bias_for_closed_htf.cache_info()
    assert _active_htf_bias(hourly,start+timedelta(hours=14,minutes=1),config) is None
    second=_bias_for_closed_htf.cache_info()
    assert second.hits==first.hits+1
def test_incomplete_htf_is_never_cached_as_eligible():
    start=datetime(2026,11,11,9,15,tzinfo=timezone.utc)
    h=[Candle(start+timedelta(hours=i),100,101,99,100,complete=(i!=13))
       for i in range(14)]
    assert _active_htf_bias(h,start+timedelta(hours=14),ReplayConfig("NIFTY")) is None
