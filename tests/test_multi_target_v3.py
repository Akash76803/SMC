from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from smc.models import Candle
from smc.liquidity import LiquidityLevel
from smc.multi_target_v3 import (
    rank_liquidity_targets, PremiumScenario, evaluate_premium_scenarios,
)

T = datetime(2026,11,16,9,16,tzinfo=ZoneInfo("Asia/Kolkata"))

def candles(price=100, n=8):
    return [Candle(T+timedelta(minutes=i),price,price+1,price-1,price)
            for i in range(n)]

def lev(price, kind="BSL", created=1, eligible=2, strength=1):
    return LiquidityLevel(kind,price,created,(0,),eligible,strength)

def review(cs=None, levels=None, **overrides):
    cs = candles() if cs is None else cs
    args=dict(candles=cs,levels=[lev(160),lev(180),lev(210)] if levels is None else levels,
              events=[],direction="BULLISH",entry=100,stop=80,
              symbol="NIFTY",as_of=cs[-1].timestamp)
    args.update(overrides)
    return rank_liquidity_targets(**args)

def test_three_tiers_and_expected_maximum_observed_rr():
    x=review()
    assert [t.name for t in x.levels]==["T1","T2","T3"]
    assert [t.candidate.price for t in x.levels]==[160,180,210]
    assert x.expected_index_rr==3
    assert x.maximum_observed_index_rr==5.5
    assert x.status=="CANDIDATE"

def test_nearest_unfeasible_does_not_skip_to_further_target():
    x=review(levels=[lev(130),lev(200)])
    assert x.status=="NO_TRADE"
    assert x.reason=="INDEX_TARGET_TOO_SMALL"
    assert x.maximum_observed_index_rr==5
    assert x.levels[0].feasible is False

def test_one_price_multiple_labels_deduplicated():
    x=review(levels=[lev(160),lev(160,"EQH",strength=2),lev(180)])
    assert x.eligible_count==2
    assert x.levels[0].candidate.level_kind=="EQH"

def test_consumed_t1_is_excluded_and_t2_becomes_expected():
    cs=candles()
    cs[4]=Candle(cs[4].timestamp,100,165,99,100)
    x=review(cs=cs,levels=[lev(160),lev(180)])
    assert x.levels[0].candidate.price==180

def test_no_target_is_wait():
    x=review(levels=[])
    assert x.status=="WAIT" and x.expected_index_rr is None

def test_bearish_targets_sorted_nearest_first():
    cs=candles(price=250)
    x=review(cs=cs,levels=[lev(120,"SSL"),lev(190,"EQL")],
             direction="BEARISH",entry=250,stop=275)
    assert [t.candidate.price for t in x.levels]==[190,120]
    assert x.maximum_observed_index_rr==5.2

def test_visible_limit_does_not_change_true_farthest_observed():
    x=review(max_visible_targets=1)
    assert len(x.levels)==1
    assert x.furthest_observed.candidate.price==210

def test_future_data_raises():
    cs=candles()
    with pytest.raises(ValueError,match="FUTURE_CANDLE"):
        review(cs=cs,as_of=cs[2].timestamp)

def test_invalid_stop_direction_rejected():
    with pytest.raises(ValueError,match="STOP_DIRECTION_MISMATCH"):
        review(stop=120)

def test_not_yet_eligible_not_displayed():
    x=review(levels=[lev(180,created=7,eligible=8)])
    assert x.status=="WAIT"

def test_premium_minimum_15_with_cost_adjusted_3r():
    x=evaluate_premium_scenarios(
        stop_points=3,round_trip_cost_per_unit=1,
        scenarios=(PremiumScenario("T1",15),PremiumScenario("T2",20)))
    assert x.expected_net_rr==3.5
    assert x.maximum_supplied_net_rr==4.75
    assert all(s.feasibility.accepted for s in x.scenarios)
    assert x.status=="SCENARIOS_ONLY_NOT_VERIFIED"

def test_premium_scenarios_not_derived_from_index():
    x=evaluate_premium_scenarios(
        stop_points=3,round_trip_cost_per_unit=1)
    assert x.expected_net_rr is None
    assert x.maximum_supplied_net_rr is None
    assert x.status=="PREMIUM_TARGETS_UNVERIFIED"

def test_premium_bad_gross_target_or_rr_flagged():
    x=evaluate_premium_scenarios(
        stop_points=5,round_trip_cost_per_unit=1,
        scenarios=(PremiumScenario("T1",10),PremiumScenario("T2",15)))
    assert [t.feasibility.accepted for t in x.scenarios]==[False,False]

def test_duplicate_scenario_rejected():
    with pytest.raises(ValueError,match="DUPLICATE_OR_UNNAMED"):
        evaluate_premium_scenarios(
            stop_points=3,round_trip_cost_per_unit=1,
            scenarios=(PremiumScenario("T1",15),PremiumScenario("T1",16)))

def test_invalid_cost_rejected_without_targets():
    with pytest.raises(ValueError,match="INVALID_PREMIUM_SCENARIO_CONFIG"):
        evaluate_premium_scenarios(stop_points=3,round_trip_cost_per_unit=-1)

def test_no_opposite_liquidity():
    assert review(levels=[lev(170,"SSL")]).status=="WAIT"

def test_zero_or_negative_count_rejected():
    with pytest.raises(ValueError,match="INVALID_TARGET_COUNT"):
        review(max_visible_targets=0)
