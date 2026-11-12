from smc.option_contract_finder import find_nfo_options
import pytest
ROWS=[
 {"symbol":"NIFTY26NOV25000CE","token":"111","exch_seg":"NFO","instrumenttype":"OPTIDX",
  "expiry":"26NOV2026","strike":"2500000","lotsize":"65"},
 {"symbol":"NIFTY26NOV25000PE","token":"112","exch_seg":"NFO","instrumenttype":"OPTIDX",
  "expiry":"26NOV2026","strike":"2500000","lotsize":"65"},
 {"symbol":"NIFTY26NOV25000CE","token":"111","exch_seg":"NFO","instrumenttype":"OPTIDX",
  "expiry":"26NOV2026"},
 {"symbol":"NIFTY26NOV25000CE","token":"999","exch_seg":"NSE","instrumenttype":"OPTIDX"},
 {"symbol":"SENSEX26NOV25000CE","token":"777","exch_seg":"BFO","instrumenttype":"OPTIDX"},
 {"symbol":"NIFTY26NOV25000CE","token":"888","exch_seg":"NFO","instrumenttype":"FUTIDX"},
]
def test_exact_filter_and_no_guess():
    r=find_nfo_options(ROWS,underlying="NIFTY",side="CE",expiry="26NOV2026")
    assert len(r)==1 and r[0]["token"]=="111"
    assert r[0]["strike_master_raw"]=="2500000"
def test_missing_expired_contract_returns_empty_not_fake_token():
    assert find_nfo_options(ROWS,expiry="01JAN2020")==[]
def test_contains_strike_and_side():
    assert [r["token"] for r in find_nfo_options(ROWS,side="PE",contains="25000")]==["112"]
def test_no_cross_exchange_or_futures():
    assert len(find_nfo_options(ROWS,limit=100))==2
def test_invalid_filter():
    with pytest.raises(ValueError):find_nfo_options(ROWS,underlying="SENSEX")
