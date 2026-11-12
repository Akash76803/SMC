"""Protected swing is pinned across later pivot confirmations (no look-ahead)."""
from datetime import datetime,timedelta,timezone
import pytest
import smc.structure_v2 as structure
from smc.models import Candle,Pivot

def candles():
    start=datetime(2026,11,11,9,16,tzinfo=timezone.utc)
    closes=[100,100,100,100,100,100,112,110,108,105,102,97,94]
    return [Candle(start+timedelta(minutes=i),v,v+2,v-2,v)
            for i,v in enumerate(closes)]

def fake_confirmed(candles,k):
    if k!=2:return []
    return [p for p in (
        Pivot("HIGH",2,110,4),
        Pivot("LOW",3,95,5),
        Pivot("LOW",8,98,10),
    ) if p.confirmed_at<len(candles)]

def test_newer_unprotected_low_does_not_trigger_choch(monkeypatch):
    monkeypatch.setattr(structure,"confirmed_pivots",fake_confirmed)
    e=structure.detect_structure(candles()[:12])
    internal=[x for x in e if x.tier=="INTERNAL"]
    assert [(x.kind,x.direction,x.candle_index) for x in internal]==[
        ("BOS","BULLISH",6)]
    # Close 97 at index 11 breaks active low 98 but NOT protected low 95.
    assert all(x.kind!="CHoCH" for x in internal)

def test_break_of_pinned_protected_swing_confirmed_as_choch(monkeypatch):
    monkeypatch.setattr(structure,"confirmed_pivots",fake_confirmed)
    full=structure.detect_structure(candles())
    internal=[x for x in full if x.tier=="INTERNAL"]
    assert [(x.kind,x.direction,x.candle_index) for x in internal]==[
        ("BOS","BULLISH",6),("CHoCH","BEARISH",12)]
    assert internal[1].broken_pivot.index==3
    assert internal[1].protected_pivot.index==3
    for n in range(6,13):
        prefix=structure.detect_structure(candles()[:n])
        assert all(x.candle_index<n for x in prefix)
        assert [x for x in prefix if x.kind=="CHoCH"]==[]

def test_reversal_requires_confirmed_protected_pivot(monkeypatch):
    def pivots(candles,k):
        if k!=2:return []
        return [p for p in [
            Pivot("HIGH",2,110,4),
            Pivot("LOW",3,95,11)] if p.confirmed_at<len(candles)]
    monkeypatch.setattr(structure,"confirmed_pivots",pivots)
    result=structure.detect_structure(candles())
    assert all(x.kind!="CHoCH" for x in result)
