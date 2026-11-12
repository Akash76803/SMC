from datetime import datetime,timedelta,timezone
from dataclasses import replace

from smc.advanced import OrderBlock, IDM
from smc.liquidity import LiquidityEvent, LiquidityLevel
from smc.models import Candle, Pivot, OptionQuote, Side, Zone
from smc.pipeline import Decision, scan_setup
from smc.structure_v2 import StructuralBreak

T=datetime(2026,11,12,9,15,tzinfo=timezone.utc)

def fixture():
    # Close-timestamp convention for local LTF candles.
    base=[(85110,85102,85105),(85114,85101,85105),
          (85106,85098,85099),(85104,85094,85096),
          (85099,85091,85093),(85105,85095,85096)]
    # 15 earlier candles for ATR(14), with no new active sweep events.
    rows=[(85100,85090,85095)]*15+base
    candles=[Candle(T+timedelta(minutes=i),cl,hi,lo,cl)
             for i,(hi,lo,cl) in enumerate(rows)]
    si=16
    level=LiquidityLevel("BSL",85111,15,(14,),si)
    sweep=LiquidityEvent("SWEEP",level,si,"BULLISH",3)
    choch=StructuralBreak("CHoCH","BEARISH","INTERNAL",
                          Pivot("LOW",14,85100,15),17,None)
    gap=Zone("BEARISH_FVG",85100,85103,18)
    ob=OrderBlock("BEARISH",85100,85109,15,17,17)
    idm=IDM("BEARISH",85112,14,17,17)
    target=LiquidityLevel("SSL",84970,0,(0,),1)
    htf=[Candle(T-timedelta(hours=3),85120,85150,85060,85100),
         Candle(T-timedelta(hours=2),85100,85110,85010,85050)]
    htf_event=StructuralBreak("BOS","BEARISH","EXTERNAL",
                              Pivot("LOW",0,85100,0),0,None)
    now=candles[-1].timestamp+timedelta(seconds=1)
    q=OptionQuote("SENSEX",Side.PE,85100,now+timedelta(days=7),20,
                  99,100,-0.60,155,84,now,500)
    return dict(symbol="SENSEX",ltf_candles=candles,htf_candles=htf,
                htf_events=[htf_event],ltf_events=[choch],
                liquidity_events=[sweep],liquidity_levels=[level,target],
                order_blocks=[ob],idm_candidates=[idm],
                option_quotes=[q],spot=85096,now=now,
                htf_duration_minutes=60,fvg_zones=[gap],max_target_atr=15.0)


def test_full_pipeline_research_candidate():
    data=fixture()
    out=scan_setup(**data)
    assert out.decision==Decision.RESEARCH_CANDIDATE
    assert out.option is not None and out.option.net_rr>=2
    assert out.target==84970
    assert out.entry.index_rr>=2


def test_no_future_htf_confirmation():
    data=fixture()
    future=replace(data["htf_candles"][0],
                   timestamp=data["ltf_candles"][-1].timestamp)
    data["htf_candles"]=[future]
    out=scan_setup(**data)
    assert out.decision==Decision.NO_TRADE
    assert "HTF_BIAS_MISMATCH_OR_MISSING" in out.reasons


def test_no_idm_proxy_blocks():
    data=fixture()
    data["idm_candidates"]=[]
    assert scan_setup(**data).reasons==("MISSING_IDM_PROXY",)


def test_no_implied_option_scenario():
    data=fixture()
    data["option_quotes"]=[replace(data["option_quotes"][0],delta=None)]
    out=scan_setup(**data)
    assert out.decision==Decision.NO_TRADE
    assert out.option is None


def test_consumed_target_not_reused():
    data=fixture()
    target=data["liquidity_levels"][1]
    data["liquidity_events"].append(LiquidityEvent("RUN",target,15,"BEARISH",1))
    out=scan_setup(**data)
    assert out.reasons==("NO_UNCONSUMED_LIQUIDITY_TARGET",)


def test_stale_or_unclosed_ltf_no_trade():
    data=fixture()
    data["now"]+=timedelta(hours=2)
    assert scan_setup(**data).reasons==("STALE_OR_OPEN_LTF_CANDLE",)
    data=fixture()
    last=data["ltf_candles"][-1]
    data["ltf_candles"][-1]=replace(last,complete=False)
    assert scan_setup(**data).decision==Decision.NO_TRADE


def test_historical_replay_not_current():
    data=fixture()
    last=data["ltf_candles"][-1]
    data["ltf_candles"].append(
        Candle(last.timestamp+timedelta(minutes=1),last.close,85102,85090,85095))
    data["now"]=data["ltf_candles"][-1].timestamp+timedelta(seconds=1)
    assert scan_setup(**data).reasons==("HISTORICAL_SIGNAL_NOT_CURRENT",)


def test_volatility_gate_rejects_unrealistic_large_target():
    data=fixture()
    data["liquidity_levels"][1]=replace(data["liquidity_levels"][1],price=84000)
    assert scan_setup(**data).reasons==("TARGET_TOO_LARGE_VS_ATR",)


def test_index_rr_gate_rejects_close_target():
    data=fixture()
    data["liquidity_levels"][1]=replace(data["liquidity_levels"][1],price=85050)
    out=scan_setup(**data)
    assert out.decision==Decision.NO_TRADE
    assert "INDEX_TARGET_TOO_SMALL" in out.reasons[0]


def test_missing_data_fail_closed():
    data=fixture()
    data["ltf_candles"]=[]
    assert scan_setup(**data).reasons==("MISSING_CANDLES",)
