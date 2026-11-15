import pytest
from smc.premium_feasibility_v3 import evaluate_premium_bracket as check

def test_minimum_15_target_and_net_3r():
    p=check(target_points=15,stop_points=3,round_trip_cost_per_unit=1)
    assert p.accepted and p.net_rr == 3.5

def test_10_or_14_premium_points_rejected():
    assert check(target_points=10,stop_points=2).reason=="PREMIUM_TARGET_BELOW_15"
    assert check(target_points=14.99,stop_points=2).reason=="PREMIUM_TARGET_BELOW_15"

def test_costs_can_invalidate_gross_3r():
    p=check(target_points=15,stop_points=5,round_trip_cost_per_unit=1)
    assert not p.accepted and p.reason=="NET_PREMIUM_RR_BELOW_3"
    assert p.net_rr < 3

def test_boundary_net_3r():
    p=check(target_points=16,stop_points=4,round_trip_cost_per_unit=1)
    assert p.accepted and p.net_rr == 3

def test_bad_inputs_fail_closed():
    with pytest.raises(ValueError):
        check(target_points=float("nan"),stop_points=3)
    with pytest.raises(ValueError):
        check(target_points=15,stop_points=0)
