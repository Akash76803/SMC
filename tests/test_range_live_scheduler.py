"""Unit tests for Live Shadow Scheduler and State Machine (Phase P4.1)."""
from datetime import date, datetime, timedelta
from pathlib import Path
import tempfile
from zoneinfo import ZoneInfo
import json

from smc.range_live_v1 import (
    is_market_holiday_or_weekend,
    make_idempotency_key,
    atomic_write_json,
    append_jsonl,
    read_jsonl_safely,
    ShadowState,
    ShadowSessionContext,
    record_live_shadow_forecast,
    reconcile_shadow_outcomes,
)
from smc.models import Candle
from smc.range_features_v1 import DailyBar

IST = ZoneInfo("Asia/Kolkata")


def test_calendar_holiday_and_weekend_check():
    # Saturday
    is_holiday, reason = is_market_holiday_or_weekend(date(2026, 11, 21))
    assert is_holiday is True
    assert reason == "WEEKEND"

    # Sunday
    is_holiday, reason = is_market_holiday_or_weekend(date(2026, 11, 22))
    assert is_holiday is True
    assert reason == "WEEKEND"

    # Verified Exchange Holiday: Republic Day 2026-01-26
    is_holiday, reason = is_market_holiday_or_weekend(date(2026, 1, 26))
    assert is_holiday is True
    assert reason == "EXCHANGE_HOLIDAY"

    # Regular Trading Day: 2026-11-20 (Friday)
    is_holiday, reason = is_market_holiday_or_weekend(date(2026, 11, 20))
    assert is_holiday is False
    assert reason is None


def test_idempotency_key_generation():
    key1 = make_idempotency_key("NIFTY", "2026-11-20", "09:16")
    key2 = make_idempotency_key("nifty", "2026-11-20", "09:16")
    assert key1 == "NIFTY_2026-11-20_09:16_REGULAR_360_RANGE"
    assert key1 == key2


def test_atomic_write_and_corrupted_jsonl_recovery():
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        json_file = tmp_path / "test.json"
        jsonl_file = tmp_path / "test.jsonl"

        # Atomic write
        data = {"symbol": "NIFTY", "price": 25000.0}
        atomic_write_json(json_file, data)
        assert json_file.exists()
        with open(json_file, "r") as f:
            assert json.load(f)["price"] == 25000.0

        # Append JSONL
        append_jsonl(jsonl_file, {"id": 1, "val": "first"})
        append_jsonl(jsonl_file, {"id": 2, "val": "second"})

        # Inject corrupted line
        with open(jsonl_file, "a", encoding="utf-8") as f:
            f.write("{corrupted json line\n")

        append_jsonl(jsonl_file, {"id": 3, "val": "third"})

        # Safe read should recover and return the 3 valid records, skipping the corrupted one
        recs = read_jsonl_safely(jsonl_file)
        assert len(recs) == 3
        assert [r["id"] for r in recs] == [1, 2, 3]


def test_reconciliation_only_fires_post_eod():
    with tempfile.TemporaryDirectory() as tmpdir:
        out_dir = Path(tmpdir)
        prior = [
            DailyBar(date=f"2026-10-{i:02d}", open=25000, high=25150, low=24950, close=25050)
            for i in range(1, 26)
        ]
        base_dt = datetime(2026, 11, 20, 9, 16, tzinfo=IST)
        
        # Incomplete session: only 100 bars (e.g. at 11:00 IST)
        partial_candles = [
            Candle(
                timestamp=base_dt + timedelta(minutes=i),
                open=25000.0,
                high=25100.0,
                low=24980.0,
                close=25050.0,
                volume=100.0,
            )
            for i in range(100)
        ]

        # First record 09:16 forecast
        record_live_shadow_forecast(
            symbol="NIFTY",
            as_of_ist_iso="2026-11-20T09:16:00+05:30",
            trading_date="2026-11-20",
            spot_at_asof=25000.0,
            prior_completed_days=prior,
            intraday_bars=[partial_candles[0]],
            out_dir=out_dir,
        )

        # Attempt reconciliation prematurely with partial candles
        res = reconcile_shadow_outcomes(
            symbol="NIFTY",
            trading_date="2026-11-20",
            regular_bars=partial_candles,
            out_dir=out_dir,
        )
        assert res == []  # Should refuse to reconcile incomplete session!
