"""CLI smoke and callback progression (run standalone from library API)."""
from datetime import datetime,timedelta,timezone
from smc.models import Candle
from smc.historical_replay import ReplayConfig
from smc.phase5_report import replay_archetype
from smc.phase5_setups import BREAKOUT
from smc.phase5_cli import progress

def test_day_callback_receives_completed_date():
    base=datetime(2026,11,11,9,16,tzinfo=timezone.utc)
    bars=[Candle(base+timedelta(minutes=i),100,101,99,100) for i in range(18)]
    done=[]
    result=replay_archetype(bars,[],ReplayConfig("NIFTY"),BREAKOUT,
                            progress=lambda day,n:done.append((day,n)))
    assert done==[("2026-11-11",18)]
    assert result.trades==()
def test_progress_flushed(capsys):
    progress("hello")
    assert "[phase5] hello" in capsys.readouterr().err
