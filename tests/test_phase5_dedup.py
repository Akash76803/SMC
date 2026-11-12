from datetime import datetime,timedelta,timezone
from types import SimpleNamespace
from smc.models import Candle,Pivot
from smc.structure_v2 import StructuralBreak
from smc.historical_replay import ReplayConfig
from smc.phase5_setups import StrategyReplay,BREAKOUT,SetupDecision
from smc.backtest import Signal
from smc.models import IndexSetup,Side
import smc.phase5_setups as mod
T=datetime(2026,11,11,9,16,tzinfo=timezone.utc)
def bars():
    prices=[90]*16+[102,104,103,101,101]
    return [Candle(T+timedelta(minutes=i),v,v+2,v-2,v)
            for i,v in enumerate(prices)]
def test_duplicate_confirmations_from_same_bos_suppressed(monkeypatch):
    b=bars()
    def fake_evaluate(prefix,htf,config,strategy):
        index=len(prefix)-1
        setup=IndexSetup("NIFTY",Side.CE,101,88,180,True,BREAKOUT)
        return SetupDecision(BREAKOUT,Signal(setup,index),"APPROVED_INDEX_RESEARCH",
                             16,Side.CE,101,88,180,79/13)
    monkeypatch.setattr(mod,"evaluate_setup",fake_evaluate)
    engine=StrategyReplay(ReplayConfig("NIFTY"),[],BREAKOUT)
    assert engine(tuple(b[:20])) is not None
    assert engine(tuple(b[:21])) is None
    assert engine.decisions[-1].reason=="DUPLICATE_TRIGGER_SUPPRESSED"
