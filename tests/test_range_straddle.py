"""Unit tests for range_straddle_v1."""
from smc.range_straddle_v1 import StraddleQuote, evaluate_straddle_pair


def test_straddle_pair_valid_pricing():
    ce = {
        "trading_symbol": "NIFTY20NOV2625000CE",
        "symbol": "NIFTY",
        "expiry": "2026-11-20",
        "side": "CE",
        "strike": 25000.0,
        "bid": 120.0,
        "ask": 122.0,
        "quote_at": "2026-11-20T09:15:50+05:30",
    }
    pe = {
        "trading_symbol": "NIFTY20NOV2625000PE",
        "symbol": "NIFTY",
        "expiry": "2026-11-20",
        "side": "PE",
        "strike": 25000.0,
        "bid": 98.0,
        "ask": 100.0,
        "quote_at": "2026-11-20T09:15:52+05:30",
    }
    as_of = "2026-11-20T09:16:00+05:30"
    
    res = evaluate_straddle_pair(ce, pe, as_of)
    assert res.is_available is True
    assert res.rejection_reason is None
    assert res.source == "OBSERVED_BROKER_DEPTH"
    assert res.strike == 25000.0
    assert res.straddle_mid == 220.0  # (121 + 99)
    assert res.straddle_ask == 222.0  # (122 + 100)
    assert res.expiry_be_low == 24778.0  # 25000 - 222
    assert res.expiry_be_high == 25222.0  # 25000 + 222


def test_straddle_strike_mismatch():
    ce = {"symbol": "NIFTY", "expiry": "2026-11-20", "strike": 25000.0, "bid": 100, "ask": 102, "quote_at": "2026-11-20T09:15:50+05:30"}
    pe = {"symbol": "NIFTY", "expiry": "2026-11-20", "strike": 25100.0, "bid": 100, "ask": 102, "quote_at": "2026-11-20T09:15:50+05:30"}
    res = evaluate_straddle_pair(ce, pe, "2026-11-20T09:16:00+05:30")
    assert res.is_available is False
    assert res.rejection_reason == "ATM_STRIKE_MISMATCH"


def test_straddle_expiry_mismatch():
    ce = {"symbol": "NIFTY", "expiry": "2026-11-20", "strike": 25000.0, "bid": 100, "ask": 102, "quote_at": "2026-11-20T09:15:50+05:30"}
    pe = {"symbol": "NIFTY", "expiry": "2026-11-27", "strike": 25000.0, "bid": 100, "ask": 102, "quote_at": "2026-11-20T09:15:50+05:30"}
    res = evaluate_straddle_pair(ce, pe, "2026-11-20T09:16:00+05:30")
    assert res.is_available is False
    assert res.rejection_reason == "EXPIRY_MISMATCH"


def test_straddle_stale_and_future_quotes():
    ce = {"symbol": "NIFTY", "expiry": "2026-11-20", "strike": 25000.0, "bid": 100, "ask": 102, "quote_at": "2026-11-20T09:14:00+05:30"}
    pe = {"symbol": "NIFTY", "expiry": "2026-11-20", "strike": 25000.0, "bid": 100, "ask": 102, "quote_at": "2026-11-20T09:14:00+05:30"}
    # 2 minutes old -> exceeds 60s
    res_stale = evaluate_straddle_pair(ce, pe, "2026-11-20T09:16:00+05:30", max_age_seconds=60)
    assert res_stale.is_available is False
    assert res_stale.rejection_reason == "STALE_QUOTE"
    
    # Future quote: quote_at is 09:17:00 when as_of is 09:16:00
    ce_future = {"symbol": "NIFTY", "expiry": "2026-11-20", "strike": 25000.0, "bid": 100, "ask": 102, "quote_at": "2026-11-20T09:17:00+05:30"}
    res_fut = evaluate_straddle_pair(ce_future, pe, "2026-11-20T09:16:00+05:30")
    assert res_fut.is_available is False
    assert res_fut.rejection_reason == "QUOTE_AFTER_AS_OF"


def test_straddle_wide_spread_rejection():
    # 20% spread on CE (bid 80, ask 100 -> (100-80)/100 = 0.20 > 0.08)
    ce = {"symbol": "NIFTY", "expiry": "2026-11-20", "strike": 25000.0, "bid": 80.0, "ask": 100.0, "quote_at": "2026-11-20T09:15:55+05:30"}
    pe = {"symbol": "NIFTY", "expiry": "2026-11-20", "strike": 25000.0, "bid": 98.0, "ask": 100.0, "quote_at": "2026-11-20T09:15:55+05:30"}
    res = evaluate_straddle_pair(ce, pe, "2026-11-20T09:16:00+05:30", max_spread_pct=0.08)
    assert res.is_available is False
    assert res.rejection_reason == "WIDE_SPREAD"
