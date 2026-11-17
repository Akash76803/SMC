from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from smc.liquidity import LiquidityLevel
from smc.models import Candle
from smc.poi_liquidity_v3 import review_liquidity_target

IST = ZoneInfo("Asia/Kolkata")


def test_custom_min_target_points_accepts_smaller_target_when_rr_valid():
    base = datetime(2026, 6, 1, 9, 16, tzinfo=IST)
    candles = [
        Candle(base + timedelta(minutes=i), 25000.0, 25010.0, 24990.0, 25000.0, 100.0)
        for i in range(30)
    ]
    # Opposing upper liquidity level at 25040 (40 points room from entry 25000)
    level = LiquidityLevel("BSL", 25040.0, 2, (1,), 3)

    # 1. Under default NIFTY rule (min 50 pts): 40 pts is REJECTED
    res_default = review_liquidity_target(
        candles=candles,
        levels=[level],
        events=[],
        direction="BULLISH",
        entry=25000.0,
        stop=24985.0,  # Risk = 15 pts -> RR = 40/15 = 2.67:1 (>= 2:1)
        symbol="NIFTY",
        as_of=candles[-1].timestamp,
    )
    assert res_default.status == "NO_TRADE"
    assert res_default.reason == "INDEX_TARGET_TOO_SMALL"

    # 2. Under dynamic ATR target rule (e.g. min 35 pts): 40 pts is ACCEPTED as CANDIDATE
    res_dynamic = review_liquidity_target(
        candles=candles,
        levels=[level],
        events=[],
        direction="BULLISH",
        entry=25000.0,
        stop=24985.0,  # Risk = 15 pts -> RR = 2.67:1
        symbol="NIFTY",
        as_of=candles[-1].timestamp,
        min_target_points=35.0,
    )
    assert res_dynamic.status == "CANDIDATE"
    assert res_dynamic.target is not None
    assert res_dynamic.target.index_points == 40.0
    assert res_dynamic.target.index_rr == 40.0 / 15.0


def test_dynamic_target_still_enforces_minimum_2_rr():
    base = datetime(2026, 6, 1, 9, 16, tzinfo=IST)
    candles = [
        Candle(base + timedelta(minutes=i), 25000.0, 25010.0, 24990.0, 25000.0, 100.0)
        for i in range(30)
    ]
    # Target room = 40 pts, but stop = 25 pts -> RR = 40/25 = 1.6:1 (< 2:1)
    level = LiquidityLevel("BSL", 25040.0, 2, (1,), 3)

    res = review_liquidity_target(
        candles=candles,
        levels=[level],
        events=[],
        direction="BULLISH",
        entry=25000.0,
        stop=24975.0,  # Risk = 25 pts
        symbol="NIFTY",
        as_of=candles[-1].timestamp,
        min_target_points=35.0,
        min_index_rr=2.0,
    )
    # Even if target points >= 35, if RR < 2.0 it must be rejected!
    assert res.status == "NO_TRADE"
    assert res.reason == "INDEX_RR_BELOW_MINIMUM"


def test_validate_index_setup_supports_dynamic_min_target():
    from smc.models import IndexSetup, Side
    from smc.risk import validate_index_setup

    # NIFTY setup with 35 pts target (Entry 25000, Stop 24985 -> Risk 15, Target 25035 -> Reward 35, RR 2.33)
    setup = IndexSetup("NIFTY", Side.CE, 25000.0, 24985.0, 25035.0, True, "ES-01")

    # Default (50 pts): Rejected
    assert not validate_index_setup(setup).accepted
    assert "INDEX_TARGET_TOO_SMALL" in validate_index_setup(setup).reasons

    # Dynamic target room (30 pts): Accepted
    valid_dyn = validate_index_setup(setup, min_target_points=30.0)
    assert valid_dyn.accepted
    assert valid_dyn.index_rr == 35.0 / 15.0


def test_live_bracket_computes_dynamic_atr_target():
    from smc.live_bracket_v318 import research_bracket

    base = datetime(2026, 6, 1, 9, 16, tzinfo=IST)
    # 20 candles with 15 pts range each -> ATR around 15
    candles = [
        Candle(base + timedelta(minutes=i), 25000.0, 25015.0, 25000.0, 25010.0, 100.0)
        for i in range(20)
    ]
    lifecycle = {
        "state": "RETEST_CONFIRMED_RESEARCH",
        "retest_at": candles[-1].timestamp.isoformat(),
        "direction": "BULLISH",
        "sweep_at": candles[5].timestamp.isoformat(),
        "ob_zone": [24995.0, 25005.0],
    }
    bracket = research_bracket(symbol="NIFTY", candles=candles, lifecycle=lifecycle)
    assert bracket["min_target_required"] is not None
    # Dynamic floor for NIFTY is 30.0
    assert bracket["min_target_required"] >= 30.0
    assert bracket["atr14"] is not None
