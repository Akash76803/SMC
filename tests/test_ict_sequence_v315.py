"""V3.15 closed-bar ICT sequence research, future leakage and safety tests."""
from datetime import datetime, timedelta, timezone

import pytest

from smc.models import Candle
from smc.ict_sequence_v315 import analyze_ict_sequence
from smc.angel_historical_research_cli_v313 import analyze_downloaded

IST = timezone(timedelta(hours=5, minutes=30))
START = datetime(2026, 11, 2, 9, 16, tzinfo=IST)


def bars(n=60):
    out = []
    for i in range(n):
        base = 100 + ((i * 7) % 19) * .5
        out.append(Candle(START+timedelta(minutes=i),
                          base, base+2.5, base-2.5, base+.5))
    return out


def test_every_stage_reported_even_when_unverified():
    result = analyze_ict_sequence(bars(), direction="BULLISH")
    assert set(result["stages"]) == {
        "IDM", "LIQUIDITY_SWEEP", "STRUCTURE_SHIFT", "DISPLACEMENT",
        "ORDER_BLOCK", "FVG", "MITIGATION_RETEST"}
    assert result["order_execution_allowed"] is False
    assert result["stop_is_verified_protected"] is False
    assert result["research_only"] is True


def test_no_future_leakage_with_as_of_prefix():
    candles = bars(80)
    early = analyze_ict_sequence(candles, direction="BEARISH", as_of=30)
    prefix = analyze_ict_sequence(candles[:31], direction="BEARISH")
    assert early == prefix
    assert early["as_of"] == candles[30].timestamp.isoformat()


def test_simple_smooth_candles_no_fabricated_full_sequence():
    candles = [
        Candle(START + timedelta(minutes=i), 100+i,
               102+i, 99+i, 101+i)
        for i in range(40)]
    result = analyze_ict_sequence(candles, direction="BULLISH")
    assert result["ict_sequence_observed"] is False
    assert result["stop_candidate"] is None
    assert result["status"] == "WAIT"


@pytest.mark.parametrize("wrong", ["LONG", "SHORT", "CE", ""])
def test_invalid_direction_rejected(wrong):
    with pytest.raises(ValueError, match="INVALID_ICT_DIRECTION"):
        analyze_ict_sequence(bars(), direction=wrong)


def test_incomplete_candle_rejected():
    data = bars()
    data[5] = Candle(data[5].timestamp, 100, 102, 99, 100, complete=False)
    with pytest.raises(ValueError, match="INCOMPLETE"):
        analyze_ict_sequence(data, direction="BULLISH")


def test_unordered_candle_rejected():
    data = bars()
    data[5], data[6] = data[6], data[5]
    with pytest.raises(ValueError, match="UNORDERED"):
        analyze_ict_sequence(data, direction="BULLISH")


def test_bad_configuration_rejected():
    with pytest.raises(ValueError, match="INVALID_ICT_PARAMETERS"):
        analyze_ict_sequence(bars(), direction="BULLISH", max_sweep_lookback=0)


def test_historical_replay_includes_ict_without_promoting_to_orders():
    data = bars(360)
    result = analyze_downloaded(symbol="NIFTY", candles=data)
    assert result["usable_sessions"] == 1
    for candidate in result["days"][0]["brackets"]["observations"]:
        assert "ict_sequence" in candidate
        assert candidate["broker_order_eligible"] is False
        assert candidate["ict_sequence"]["as_of"] == candidate["confirmed_at"]

def test_offline_ict_csv_reports_missing_stages(tmp_path):
    from smc.historical_replay_v314_cli import export_ict_csv
    payload = analyze_downloaded(symbol="NIFTY", candles=bars(360))
    output = tmp_path / "ict.csv"
    export_ict_csv(payload, output)
    text = output.read_text(encoding="utf-8")
    assert "LIQUIDITY_SWEEP" in text
    assert "MITIGATION_RETEST" in text
    assert "missing_stages" in text
