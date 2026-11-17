"""ICT lifecycle state acceptance tests (research only)."""
from datetime import datetime, timedelta, timezone

import pytest

from smc.models import Candle
from smc.ict_lifecycle_v316 import scan_ict_lifecycles, _ob_zone_label, _zone_aligned
from smc.angel_historical_research_cli_v313 import analyze_downloaded

IST=timezone(timedelta(hours=5,minutes=30))
START=datetime(2026,11,2,9,16,tzinfo=IST)


def candles(n=80):
    return [Candle(START+timedelta(minutes=i),
                   100+(i*7%23)*.7, 103+(i*7%23)*.7,
                   98+(i*7%23)*.7, 101+(i*7%23)*.7)
            for i in range(n)]


def test_lifecycle_is_research_only_for_all_states():
    entries=scan_ict_lifecycles(candles())
    assert isinstance(entries,list)
    assert all(not row["order_allowed"] and row["research_only"] for row in entries)
    assert all(not row["stop_protected_verified"] for row in entries)


def test_lifecycle_prefix_equivalence_no_future_candles():
    dataset=candles()
    a=scan_ict_lifecycles(dataset,as_of=39)
    b=scan_ict_lifecycles(dataset[:40])
    assert a==b


def test_lifecycle_rejects_unsorted_or_incomplete():
    data=candles()
    data[9],data[10]=data[10],data[9]
    with pytest.raises(ValueError,match="UNORDERED"):
        scan_ict_lifecycles(data)
    with pytest.raises(ValueError,match="INVALID_LIFECYCLE_AS_OF"):
        scan_ict_lifecycles(candles(),as_of=81)


def test_lifecycle_export_in_replay_and_no_orders():
    result=analyze_downloaded(symbol="NIFTY",candles=candles(360))
    session=result["days"][0]
    assert "ict_lifecycles" in session
    assert all(x["order_allowed"] is False for x in session["ict_lifecycles"])
    assert result["executed_trades"]==0


# --- Premium / Discount zone filter tests (Gwaidier Lecture 11) ---

def test_ob_zone_label_premium():
    # OB midpoint 110 > equilibrium 100 → PREMIUM
    assert _ob_zone_label(105.0, 115.0, 100.0) == "PREMIUM"


def test_ob_zone_label_discount():
    # OB midpoint 90 < equilibrium 100 → DISCOUNT
    assert _ob_zone_label(85.0, 95.0, 100.0) == "DISCOUNT"


def test_ob_zone_label_equilibrium():
    # OB midpoint exactly at equilibrium → EQUILIBRIUM
    assert _ob_zone_label(95.0, 105.0, 100.0) == "EQUILIBRIUM"


def test_zone_aligned_bullish_in_discount():
    # BULLISH OB in DISCOUNT → aligned ✓
    assert _zone_aligned("BULLISH", "DISCOUNT") is True


def test_zone_aligned_bullish_in_premium_rejected():
    # BULLISH OB in PREMIUM → wrong side ✗
    assert _zone_aligned("BULLISH", "PREMIUM") is False


def test_zone_aligned_bearish_in_premium():
    # BEARISH OB in PREMIUM → aligned ✓
    assert _zone_aligned("BEARISH", "PREMIUM") is True


def test_zone_aligned_bearish_in_discount_rejected():
    # BEARISH OB in DISCOUNT → wrong side ✗
    assert _zone_aligned("BEARISH", "DISCOUNT") is False


def test_lifecycle_no_dealing_range_has_zone_fields_as_none():
    """Without dealing_range, zone fields are None / False — backward compat."""
    rows = scan_ict_lifecycles(candles())
    for row in rows:
        assert "zone_filter_applied" in row
        assert "ob_zone_label" in row
        assert "zone_aligned" in row
        assert row["zone_filter_applied"] is False
        assert row["ob_zone_label"] is None
        assert row["zone_aligned"] is None


def test_lifecycle_dealing_range_sets_zone_filter_applied():
    """With dealing_range supplied, zone_filter_applied is True for all rows."""
    dr = {"equilibrium": 100.0, "low": 90.0, "high": 110.0, "position": "DISCOUNT"}
    rows = scan_ict_lifecycles(candles(), dealing_range=dr)
    assert all(row["zone_filter_applied"] is True for row in rows)


def test_lifecycle_rejected_wrong_zone_state():
    """An OB on the wrong side of equilibrium gets REJECTED_WRONG_ZONE state."""
    rows_no_filter = scan_ict_lifecycles(candles())
    # Find any row that reached WAITING_FOR_RETEST or beyond (has an OB)
    with_ob = [r for r in rows_no_filter if r["ob_zone"] is not None]
    if not with_ob:
        pytest.skip("no OB found in synthetic candles — skip zone rejection test")

    # Push equilibrium so that the OB is on the wrong side for its direction
    sample = with_ob[0]
    ob_lower, ob_upper = sample["ob_zone"]
    ob_mid = (ob_lower + ob_upper) / 2.0
    direction = sample["direction"]
    # For BULLISH OB we want mid < equilibrium to be FALSE → put eq below mid
    # so OB is in PREMIUM (wrong for BULLISH)
    if direction == "BULLISH":
        eq = ob_mid - 0.5   # equilibrium below OB mid → OB in PREMIUM
    else:
        eq = ob_mid + 0.5   # equilibrium above OB mid → OB in DISCOUNT

    dr = {"equilibrium": eq}
    rows_filtered = scan_ict_lifecycles(candles(), dealing_range=dr)
    matching = [r for r in rows_filtered if r["setup_id"] == sample["setup_id"]]
    assert matching, "setup_id should still appear in filtered results"
    assert matching[0]["state"] == "REJECTED_WRONG_ZONE"
    assert matching[0]["zone_aligned"] is False


def test_lifecycle_correct_zone_not_rejected():
    """An OB on the correct side of equilibrium must NOT get REJECTED_WRONG_ZONE."""
    rows_no_filter = scan_ict_lifecycles(candles())
    with_ob = [r for r in rows_no_filter if r["ob_zone"] is not None]
    if not with_ob:
        pytest.skip("no OB found in synthetic candles")

    sample = with_ob[0]
    ob_lower, ob_upper = sample["ob_zone"]
    ob_mid = (ob_lower + ob_upper) / 2.0
    direction = sample["direction"]
    # Put equilibrium so that OB is on the CORRECT side
    if direction == "BULLISH":
        eq = ob_mid + 0.5   # equilibrium above OB mid → OB in DISCOUNT ✓
    else:
        eq = ob_mid - 0.5   # equilibrium below OB mid → OB in PREMIUM ✓

    dr = {"equilibrium": eq}
    rows_filtered = scan_ict_lifecycles(candles(), dealing_range=dr)
    matching = [r for r in rows_filtered if r["setup_id"] == sample["setup_id"]]
    assert matching
    assert matching[0]["state"] != "REJECTED_WRONG_ZONE"
    assert matching[0]["zone_aligned"] is True


def test_lifecycle_exposes_ith_itl_and_structural_swing_keys():
    """Each lifecycle setup exposes ith_itl_reference and structural_swing_reference."""
    rows = scan_ict_lifecycles(candles())
    for r in rows:
        assert "ith_itl_reference" in r
        assert "structural_swing_reference" in r
        # If an ith_itl_reference exists, check its structure
        if r["ith_itl_reference"] is not None:
            ref = r["ith_itl_reference"]
            assert ref["kind"] in ("ITH", "ITL")
            assert isinstance(ref["price"], float)
            assert isinstance(ref["index"], int)
            assert isinstance(ref["confirmed_at"], str)
        if r["structural_swing_reference"] is not None:
            ref = r["structural_swing_reference"]
            assert ref["kind"] in ("ITH", "ITL", "STH", "STL")
            assert isinstance(ref["price"], float)
