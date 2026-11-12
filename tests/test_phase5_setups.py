"""Research setup invariants, including causal prefix and genuine retest."""
from datetime import datetime,timedelta,timezone
from types import SimpleNamespace
import pytest
from smc.models import Candle,Pivot
from smc.historical_replay import ReplayConfig
from smc.structure_v2 import StructuralBreak
from smc.phase5_setups import (evaluate_setup,StrategyReplay,CONTINUATION,
                                BREAKOUT,summarize_decisions)
import smc.phase5_setups as mod
BASE=datetime(2026,11,11,9,16,tzinfo=timezone.utc)
def cs(closes):
    return [Candle(BASE+timedelta(minutes=i),c,c+2,c-2,c) for i,c in enumerate(closes)]
def fake_bos(index=16):
    return StructuralBreak("BOS","BULLISH","INTERNAL",
                           Pivot("HIGH",10,100,12),index,None)
def test_unknown_strategy_rejected():
    with pytest.raises(ValueError,match="UNKNOWN"):
        evaluate_setup(cs([100]*18),[],ReplayConfig("NIFTY"),"INVALID")
def test_empty_retest_never_emits():
    bars=cs([100]*21)
    replay=StrategyReplay(ReplayConfig("NIFTY"),[],BREAKOUT)
    assert replay(tuple(bars)) is None
    assert replay.decisions[-1].reason=="HTF_BIAS_UNAVAILABLE"
def test_breakout_signal_not_on_bos_candle(monkeypatch):
    bars=cs([90]*16+[102,104,103,103])
    monkeypatch.setattr(mod,"_active_htf_bias",lambda *args:"BULLISH")
    monkeypatch.setattr(mod,"scan",lambda *args,**kwargs:SimpleNamespace(
        structure_events=[fake_bos()],
        liquidity_events=[],levels=[]))
    assert evaluate_setup(bars[:17],[],ReplayConfig("NIFTY"),BREAKOUT).signal is None
def test_risk_gate_rejects_insufficient_target(monkeypatch):
    bars=cs([90]*16+[102,104,103,101])
    monkeypatch.setattr(mod,"_active_htf_bias",lambda *args:"BULLISH")
    monkeypatch.setattr(mod,"scan",lambda *args,**kwargs:SimpleNamespace(
        structure_events=[fake_bos()],liquidity_events=[],levels=[]))
    monkeypatch.setattr(mod,"select_liquidity_target",lambda *args,**kwargs:102)
    result=evaluate_setup(bars,[],ReplayConfig("NIFTY"),BREAKOUT)
    assert result.signal is None
    assert "INDEX_RR_BELOW_2" in result.reason
def test_approved_breakout_requires_actual_far_target(monkeypatch):
    bars=cs([90]*16+[102,104,103,101])
    monkeypatch.setattr(mod,"_active_htf_bias",lambda *args:"BULLISH")
    monkeypatch.setattr(mod,"scan",lambda *args,**kwargs:SimpleNamespace(
        structure_events=[fake_bos()],liquidity_events=[],levels=[]))
    monkeypatch.setattr(mod,"select_liquidity_target",lambda *args,**kwargs:180)
    result=evaluate_setup(bars,[],ReplayConfig("NIFTY"),BREAKOUT)
    assert result.signal is not None
    assert result.signal.signal_index==len(bars)-1
    assert result.signal.setup.target==180
    assert result.signal.setup.stop<result.entry<180
def test_cannot_signal_on_partial_prefix(monkeypatch):
    bars=cs([90]*16+[102,104,103,101])
    monkeypatch.setattr(mod,"_active_htf_bias",lambda *args:"BULLISH")
    monkeypatch.setattr(mod,"scan",lambda *args,**kwargs:SimpleNamespace(
        structure_events=[fake_bos()],liquidity_events=[],levels=[]))
    monkeypatch.setattr(mod,"select_liquidity_target",lambda *args,**kwargs:180)
    for n in (16,17,18):
        result=evaluate_setup(bars[:n],[],ReplayConfig("NIFTY"),BREAKOUT)
        assert result.signal is None
def test_decision_summary():
    assert summarize_decisions([])=={}
