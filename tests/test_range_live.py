"""Unit tests for range_live_v1."""
import json
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from smc.models import Candle
from smc.range_features_v1 import DailyBar
from smc.range_live_v1 import record_live_shadow_forecast, reconcile_shadow_outcomes

IST = ZoneInfo("Asia/Kolkata")


def test_live_shadow_logging_and_reconciliation():
    with tempfile.TemporaryDirectory() as tmpdir:
        out_dir = Path(tmpdir)
        
        # 25 prior days
        prior = [
            DailyBar(date=f"2026-10-{i:02d}", open=25000, high=25150, low=24950, close=25050)
            for i in range(1, 26)
        ]
        
        # Build 360 regular candles for today
        base_dt = datetime(2026, 11, 20, 9, 16, tzinfo=IST)
        session_candles = [
            Candle(
                timestamp=base_dt + timedelta(minutes=i),
                open=25000.0,
                high=25120.0,
                low=24980.0,
                close=25050.0,
                volume=100.0,
            )
            for i in range(360)
        ]
        
        # Record 09:16 shadow forecast
        fc16 = record_live_shadow_forecast(
            symbol="NIFTY",
            as_of_ist_iso="2026-11-20T09:16:00+05:30",
            trading_date="2026-11-20",
            spot_at_asof=25000.0,
            prior_completed_days=prior,
            intraday_bars=[session_candles[0]],
            out_dir=out_dir,
        )
        assert fc16.status == "BASELINE_READY"
        
        # Record 09:30 shadow forecast
        fc30 = record_live_shadow_forecast(
            symbol="NIFTY",
            as_of_ist_iso="2026-11-20T09:30:00+05:30",
            trading_date="2026-11-20",
            spot_at_asof=25050.0,
            prior_completed_days=prior,
            intraday_bars=session_candles[:15],
            out_dir=out_dir,
        )
        assert fc30.status == "BASELINE_READY"
        
        # Verify JSONL log has 2 records
        history_file = out_dir / "nifty_shadow_forecasts.jsonl"
        assert history_file.is_file()
        lines = history_file.read_text(encoding="utf-8").strip().split("\n")
        assert len(lines) == 2
        
        # Verify latest JSON
        latest_file = out_dir / "nifty_latest.json"
        assert latest_file.is_file()
        latest_data = json.loads(latest_file.read_text(encoding="utf-8"))
        assert latest_data["as_of_ist"] == "2026-11-20T09:30:00+05:30"
        
        # Perform EOD post-15:15 reconciliation
        reconciled = reconcile_shadow_outcomes(
            symbol="NIFTY",
            trading_date="2026-11-20",
            regular_bars=session_candles,
            out_dir=out_dir,
        )
        assert len(reconciled) == 2
        assert reconciled[0]["actual_range"] == 140.0  # 25120 - 24980
        assert reconciled[0]["absolute_error_q50"] is not None
        assert isinstance(reconciled[0]["covered_in_interval"], bool)
        
        # Check reconciled file exists
        rec_file = out_dir / "nifty_reconciled.jsonl"
        assert rec_file.is_file()
