"""Unit tests for SMC Gwaidier 1-Minute (1M) Entry Confirmation & HTF <-> LTF Bridge."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from smc.entry_confirmation_1m import (
    PullbackPattern,
    ValidPullback1M,
    detect_bullish_pullback_1m,
    detect_bearish_pullback_1m,
    evaluate_htf_ltf_bridge,
    find_mother_candle,
    is_inside_bar,
)
from smc.models import Candle

IST = ZoneInfo("Asia/Kolkata")
BASE_TIME = datetime(2026, 11, 23, 10, 0, tzinfo=IST)


def _candle(idx: int, o: float, h: float, l: float, c: float) -> Candle:
    t = BASE_TIME + timedelta(minutes=idx)
    return Candle(timestamp=t, open=float(o), high=float(h), low=float(l), close=float(c), complete=True)


# ═══════════════════════════════════════════════════════════════════════════
# Test Inside Bar & Mother Candle Resolution
# ═══════════════════════════════════════════════════════════════════════════

class TestMotherCandleResolution:
    def test_is_inside_bar(self):
        mother = _candle(0, 100, 110, 90, 105)
        inside = _candle(1, 102, 108, 92, 104)
        outside = _candle(2, 95, 112, 88, 100)
        assert is_inside_bar(inside, mother) is True
        assert is_inside_bar(outside, mother) is False

    def test_find_mother_candle_single_inside(self):
        c0 = _candle(0, 100, 120, 80, 110)  # Mother
        c1 = _candle(1, 105, 115, 85, 108)  # Inside
        candles = [c0, c1]
        res = find_mother_candle(candles, 1)
        assert res is not None
        idx, mother = res
        assert idx == 0
        assert mother.high == 120 and mother.low == 80

    def test_find_mother_candle_nested_inside(self):
        c0 = _candle(0, 100, 130, 70, 115)  # True Mother
        c1 = _candle(1, 105, 120, 75, 110)  # Inside
        c2 = _candle(2, 108, 115, 80, 109)  # Inside of Inside
        candles = [c0, c1, c2]
        res = find_mother_candle(candles, 2)
        assert res is not None
        idx, mother = res
        assert idx == 0
        assert mother.high == 130


# ═══════════════════════════════════════════════════════════════════════════
# Test 6 Bullish Pullback Patterns
# ═══════════════════════════════════════════════════════════════════════════

class TestBullishPullbackPatterns:
    def test_pattern_1_classic_1_candle(self):
        # c0 makes Peak (H:110, L:95)
        # c1 sweeps peak low (H:105, L:90 < 95)
        # c2 closes above peak high (H:115, L:98, C:112 > 110)
        c0 = _candle(0, 100, 110, 95, 108)
        c1 = _candle(1, 102, 105, 90, 98)
        c2 = _candle(2, 98, 115, 96, 112)
        res = detect_bullish_pullback_1m([c0, c1, c2])
        assert res.is_valid is True
        assert res.pattern == PullbackPattern.CLASSIC_1_CANDLE
        assert res.sweep_price == 90.0
        assert res.trigger_close == 112.0
        assert res.provisional_stop == 90.0

    def test_pattern_2_outside_candle_grab(self):
        # c0 prior (H:105, L:95)
        # c1 outside bar breaks H:108 > 105 AND sweeps L:92 < 95
        # c2 closes above outside bar high (C:110 > 108)
        c0 = _candle(0, 100, 105, 95, 102)
        c1 = _candle(1, 100, 108, 92, 104)
        c2 = _candle(2, 104, 112, 101, 110)
        res = detect_bullish_pullback_1m([c0, c1, c2])
        assert res.is_valid is True
        assert res.pattern == PullbackPattern.OUTSIDE_CANDLE_GRAB
        assert res.sweep_price == 92.0

    def test_pattern_3_inside_bar_mother_sweep(self):
        # c0 Mother (H:120, L:100)
        # c1 Inside Bar (H:115, L:105)
        # c2 Sweep candle sweeps Mother's Low (L:96 < 100)
        # c3 Trigger closes above Mother's High (C:122 > 120)
        c0 = _candle(0, 105, 120, 100, 118)
        c1 = _candle(1, 110, 115, 105, 112)
        c2 = _candle(2, 108, 114, 96, 105)
        c3 = _candle(3, 106, 125, 102, 122)
        res = detect_bullish_pullback_1m([c0, c1, c2, c3])
        assert res.is_valid is True
        assert res.pattern == PullbackPattern.INSIDE_BAR_MOTHER_SWEEP
        assert res.sweep_price == 96.0
        assert res.trigger_close == 122.0

    def test_pattern_4_scob_single_candle(self):
        # c0 prior peak (H:100, L:90)
        # c1 single candle sweeps L:88 < 90 AND closes C:102 > 100 in same candle!
        c0 = _candle(0, 95, 100, 90, 98)
        c1 = _candle(1, 92, 104, 88, 102)
        res = detect_bullish_pullback_1m([c0, c1])
        assert res.is_valid is True
        assert res.pattern == PullbackPattern.SINGLE_CANDLE_OB
        assert res.sweep_price == 88.0
        assert res.trigger_close == 102.0

    def test_pattern_5_inside_bar_rejection_expansion(self):
        # c0 Mother (H:110, L:90)
        # c1 Inside bar (H:105, L:95)
        # c2 sweeps Mother L:88 < 90 AND closes C:112 > 110 in same candle!
        c0 = _candle(0, 100, 110, 90, 108)
        c1 = _candle(1, 102, 105, 95, 101)
        c2 = _candle(2, 96, 115, 88, 112)
        res = detect_bullish_pullback_1m([c0, c1, c2])
        assert res.is_valid is True
        assert res.pattern == PullbackPattern.INSIDE_BAR_REJECTION
        assert res.sweep_price == 88.0

    def test_pattern_6_multi_candle_step(self):
        # c0 Peak (H:100, L:92)
        # c1 pulls back (L:90 < 92)
        # c2 pulls back deeper (L:86 < 90)
        # c3 trigger closes above Peak (C:104 > 100)
        c0 = _candle(0, 95, 100, 92, 98)
        c1 = _candle(1, 95, 97, 90, 91)
        c2 = _candle(2, 89, 92, 86, 88)
        c3 = _candle(3, 89, 106, 88, 104)
        res = detect_bullish_pullback_1m([c0, c1, c2, c3])
        assert res.is_valid is True
        assert res.pattern == PullbackPattern.MULTI_CANDLE_STEP
        assert res.sweep_price == 86.0
        assert res.trigger_close == 104.0


# ═══════════════════════════════════════════════════════════════════════════
# Test 6 Bearish Pullback Patterns
# ═══════════════════════════════════════════════════════════════════════════

class TestBearishPullbackPatterns:
    def test_pattern_1_classic_bearish(self):
        # c0 valley (L:90, H:105)
        # c1 sweeps high (H:110 > 105)
        # c2 closes below valley low (C:88 < 90)
        c0 = _candle(0, 100, 105, 90, 92)
        c1 = _candle(1, 98, 110, 95, 102)
        c2 = _candle(2, 101, 102, 86, 88)
        res = detect_bearish_pullback_1m([c0, c1, c2])
        assert res.is_valid is True
        assert res.pattern == PullbackPattern.CLASSIC_1_CANDLE
        assert res.sweep_price == 110.0
        assert res.trigger_close == 88.0

    def test_pattern_2_outside_candle_grab_bearish(self):
        # c0 prior (L:95, H:105)
        # c1 outside bar breaks H:108 > 105 AND sweeps L:92 < 95
        # c2 closes below outside bar low (C:90 < 92)
        c0 = _candle(0, 100, 105, 95, 98)
        c1 = _candle(1, 100, 108, 92, 96)
        c2 = _candle(2, 96, 97, 88, 90)
        res = detect_bearish_pullback_1m([c0, c1, c2])
        assert res.is_valid is True
        assert res.pattern == PullbackPattern.OUTSIDE_CANDLE_GRAB
        assert res.sweep_price == 108.0

    def test_pattern_3_inside_bar_mother_sweep_bearish(self):
        # c0 Mother (H:110, L:90)
        # c1 Inside Bar (H:105, L:95)
        # c2 Sweep candle sweeps Mother High (H:112 > 110)
        # c3 Trigger closes below Mother Low (C:88 < 90)
        c0 = _candle(0, 95, 110, 90, 92)
        c1 = _candle(1, 95, 105, 95, 96)
        c2 = _candle(2, 98, 112, 96, 100)
        c3 = _candle(3, 98, 99, 86, 88)
        res = detect_bearish_pullback_1m([c0, c1, c2, c3])
        assert res.is_valid is True
        assert res.pattern == PullbackPattern.INSIDE_BAR_MOTHER_SWEEP
        assert res.sweep_price == 112.0
        assert res.trigger_close == 88.0

    def test_pattern_5_inside_bar_rejection_bearish(self):
        # c0 Mother (H:110, L:90)
        # c1 Inside bar (H:105, L:95)
        # c2 sweeps Mother H:112 > 110 AND closes C:88 < 90 in same candle!
        c0 = _candle(0, 95, 110, 90, 94)
        c1 = _candle(1, 96, 105, 95, 98)
        c2 = _candle(2, 102, 112, 86, 88)
        res = detect_bearish_pullback_1m([c0, c1, c2])
        assert res.is_valid is True
        assert res.pattern == PullbackPattern.INSIDE_BAR_REJECTION
        assert res.sweep_price == 112.0

    def test_pattern_6_multi_candle_step_bearish(self):
        # c0 Valley (L:90, H:98)
        # c1 step 1 higher high (H:102 > 98)
        # c2 step 2 higher high (H:106 > 102)
        # c3 trigger closes below Valley Low (C:86 < 90)
        c0 = _candle(0, 96, 98, 90, 92)
        c1 = _candle(1, 92, 102, 91, 100)
        c2 = _candle(2, 100, 106, 98, 104)
        c3 = _candle(3, 102, 103, 84, 86)
        res = detect_bearish_pullback_1m([c0, c1, c2, c3])
        assert res.is_valid is True
        assert res.pattern == PullbackPattern.MULTI_CANDLE_STEP
        assert res.sweep_price == 106.0
        assert res.trigger_close == 86.0

    def test_bearish_sniper_entry_bridge(self):
        # Prior: L:25000, H:25050
        # Trigger: sweeps H:25060, closes C:24990
        c0 = _candle(0, 25020, 25050, 25000, 25030)
        c1 = _candle(1, 25040, 25060, 24980, 24990)
        # HTF Bias: BEARISH, Eq: 24900 (Price 24990 is in PREMIUM!)
        # POI: 15M OB 25040-25070 (tapped by c1 high 25060)
        # Target: 15M Opposing SSL at 24800 (190 pts reward)
        res = evaluate_htf_ltf_bridge(
            symbol="NIFTY",
            direction="BEARISH",
            ltf_candles=[c0, c1],
            htf_bias="BEARISH",
            htf_equilibrium=24900.0,
            htf_poi_zone=(25040.0, 25070.0),
            htf_target_pool=24800.0,
            min_points=50.0,
            min_rr=2.0,
        )
        assert res.is_qualified is True
        assert res.status == "CONFIRMED_SNIPER_ENTRY"
        assert res.entry_price == 24990.0
        # Stop loss = 25060 + 1.0 = 25061.0
        assert res.stop_loss == 25061.0
        assert res.risk_points == pytest.approx(71.0)
        assert res.reward_points == pytest.approx(190.0)
        assert res.index_rr >= 2.0
        assert res.target_1 == 24800.0

    def test_as_dict_serialization(self):
        c0 = _candle(0, 100, 110, 95, 108)
        c1 = _candle(1, 102, 105, 90, 98)
        c2 = _candle(2, 98, 115, 96, 112)
        pb = detect_bullish_pullback_1m([c0, c1, c2])
        d = pb.as_dict()
        assert d["pattern"] == "CLASSIC_1_CANDLE"
        assert d["is_valid"] is True
        assert d["sweep_price"] == 90.0


# ═══════════════════════════════════════════════════════════════════════════
# Test HTF <-> LTF Institutional Bridge
# ═══════════════════════════════════════════════════════════════════════════

class TestHTFLTFBridge:
    def _bullish_candles(self):
        # 1M sequence producing a clean SCOB:
        # Prior candle: H:25000, L:24950
        # Trigger candle: sweeps L:24940, closes C:25010
        c0 = _candle(0, 24980, 25000, 24950, 24970)
        c1 = _candle(1, 24960, 25020, 24940, 25010)
        return [c0, c1]

    def test_successful_bullish_sniper_entry(self):
        candles = self._bullish_candles()
        # HTF: Bias = BULLISH, Equilibrium = 25100 (price 25010 is DISCOUNT!)
        # POI: 15M OB between 24930 and 24960 (tapped by c1 low 24940)
        # Target: 15M Opposing Liquidity at 25200 (190 pts away)
        res = evaluate_htf_ltf_bridge(
            symbol="NIFTY",
            direction="BULLISH",
            ltf_candles=candles,
            htf_bias="BULLISH",
            htf_equilibrium=25100.0,
            htf_poi_zone=(24930.0, 24960.0),
            htf_target_pool=25200.0,
            min_points=50.0,
            min_rr=2.0,
        )
        assert res.is_qualified is True
        assert res.status == "CONFIRMED_SNIPER_ENTRY"
        assert res.entry_price == 25010.0
        # Stop loss = 24940 - 1.0 = 24939.0
        assert res.stop_loss == 24939.0
        assert res.risk_points == pytest.approx(71.0)
        assert res.reward_points == pytest.approx(190.0)
        assert res.index_rr >= 2.0
        assert res.target_1 == 25200.0

    def test_blocked_by_htf_bias_conflict(self):
        candles = self._bullish_candles()
        # Direction is BULLISH, but HTF Bias is BEARISH
        res = evaluate_htf_ltf_bridge(
            symbol="NIFTY",
            direction="BULLISH",
            ltf_candles=candles,
            htf_bias="BEARISH",
            htf_equilibrium=25100.0,
            htf_poi_zone=(24930.0, 24960.0),
            htf_target_pool=25200.0,
        )
        assert res.is_qualified is False
        assert res.status == "WAIT_HTF_BIAS"

    def test_blocked_by_premium_zone_for_bullish(self):
        candles = self._bullish_candles()
        # Price is 25010, but HTF Equilibrium is 24900 (Price is in PREMIUM, not Discount!)
        res = evaluate_htf_ltf_bridge(
            symbol="NIFTY",
            direction="BULLISH",
            ltf_candles=candles,
            htf_bias="BULLISH",
            htf_equilibrium=24900.0,
            htf_poi_zone=(24930.0, 24960.0),
            htf_target_pool=25200.0,
        )
        assert res.is_qualified is False
        assert res.status == "WAIT_DISCOUNT_ZONE"

    def test_blocked_by_htf_poi_not_tapped(self):
        candles = self._bullish_candles()
        # POI is 24800-24850, which price never reached
        res = evaluate_htf_ltf_bridge(
            symbol="NIFTY",
            direction="BULLISH",
            ltf_candles=candles,
            htf_bias="BULLISH",
            htf_equilibrium=25100.0,
            htf_poi_zone=(24800.0, 24850.0),
            htf_target_pool=25200.0,
        )
        assert res.is_qualified is False
        assert res.status == "WAIT_HTF_POI"

    def test_blocked_by_small_target_room(self):
        candles = self._bullish_candles()
        # Target pool is only 25030 (20 pts away < min_points=50)
        res = evaluate_htf_ltf_bridge(
            symbol="NIFTY",
            direction="BULLISH",
            ltf_candles=candles,
            htf_bias="BULLISH",
            htf_equilibrium=25100.0,
            htf_poi_zone=(24930.0, 24960.0),
            htf_target_pool=25030.0,
            min_points=50.0,
        )
        assert res.is_qualified is False
        assert res.status == "TARGET_ROOM_TOO_SMALL"

    def test_blocked_by_low_rr(self):
        candles = self._bullish_candles()
        # Risk = 71 pts. Target = 25085 -> Reward = 75 pts -> RR ~ 1.05 < 2.0
        res = evaluate_htf_ltf_bridge(
            symbol="NIFTY",
            direction="BULLISH",
            ltf_candles=candles,
            htf_bias="BULLISH",
            htf_equilibrium=25100.0,
            htf_poi_zone=(24930.0, 24960.0),
            htf_target_pool=25085.0,
            min_points=50.0,
            min_rr=2.0,
        )
        assert res.is_qualified is False
        assert res.status == "RR_BELOW_MINIMUM"
