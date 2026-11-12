from datetime import datetime, timedelta, timezone
from smc.models import IndexSetup, OptionQuote, Side
from smc.risk import validate_index_setup
from smc.options import rank_options


def test_target_and_index_rr_mandatory():
    assert validate_index_setup(IndexSetup("NIFTY", Side.CE, 26000,25975,26060,True,"ES-01")).accepted
    assert not validate_index_setup(IndexSetup("SENSEX",Side.PE,85000,85060,84910,True,"ES-01")).accepted
    assert not validate_index_setup(IndexSetup("NIFTY",Side.CE,26000,25975,26060,False,"ES-01")).accepted


def test_only_delta_qualified_liquid_atm_itm_with_net_rr():
    now=datetime(2026,11,12,tzinfo=timezone.utc)
    setup=IndexSetup("NIFTY",Side.CE,26000,25975,26060,True,"ES-01")
    def quote(strike,delta,volume=100,ask=100,bid=99,target=150,stop=85):
        return OptionQuote("NIFTY",Side.CE,strike,now+timedelta(days=7),
                           65,bid,ask,delta,target,stop,now,volume)
    ranked=rank_options(setup,26001,[
        quote(26000,.56),quote(25950,.65),quote(26050,.55),
        quote(25900,.61),quote(26000,.20)
    ],now)
    assert {r.quote.strike for r in ranked} == {26000,25950}
    assert all(r.net_rr>=2 for r in ranked)


def test_missing_greeks_or_pricing_blocks_signal():
    now=datetime(2026,11,12,tzinfo=timezone.utc)
    setup=IndexSetup("SENSEX",Side.PE,85000,85050,84900,True,"ES-01")
    q=OptionQuote("SENSEX",Side.PE,85000,now+timedelta(days=7),
                  20,100,101,None,None,None,now,300)
    assert rank_options(setup,85000,[q],now)==[]
