from datetime import datetime,timedelta,timezone
import pytest
from smc.models import Candle
from smc.structure_diagnostics import audit_choch_link

def test_flat_bars_have_no_confirmed_sweep_choch_link():
    start=datetime(2026,11,11,9,16,tzinfo=timezone.utc)
    candles=[Candle(start+timedelta(minutes=i),100,101,99,100)
             for i in range(32)]
    report=audit_choch_link(candles)
    assert report["unique_sweep_events"]==0
    assert report["internal_choch_events"]==0
    assert report["sweeps_with_matching_choch_within_window"]==0
    assert report["min_matching_lag_bars"] is None

def test_config_rejects_bad_choch_window():
    with pytest.raises(ValueError):
        audit_choch_link([],max_choch_bars=0)

def test_report_keys_do_not_confuse_observations_with_trades():
    result=audit_choch_link([])
    assert result["max_choch_bars"]==8
    assert result["internal_choch_by_direction"]=={}
