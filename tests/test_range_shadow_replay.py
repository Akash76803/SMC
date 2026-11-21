"""Unit tests for Historical Shadow Replay Engine (Phase P4.2)."""
from datetime import datetime, timedelta
from pathlib import Path
import tempfile
from zoneinfo import ZoneInfo
import json

from smc.models import Candle
from smc.range_shadow_replay_cli import run_shadow_replay

IST = ZoneInfo("Asia/Kolkata")


def make_synthetic_dataset():
    sessions: dict[str, list[Candle]] = {}
    base_dt = datetime(2026, 7, 1, 9, 16, tzinfo=IST)
    for day in range(25):
        d_str = f"2026-07-{day+1:02d}"
        candles = []
        for m in range(360):
            candles.append(
                Candle(
                    timestamp=base_dt + timedelta(days=day, minutes=m),
                    open=25000.0,
                    high=25100.0,
                    low=24900.0,
                    close=25010.0,
                    volume=50.0,
                )
            )
        sessions[d_str] = candles
    return sessions


def test_shadow_replay_execution_and_idempotency():
    with tempfile.TemporaryDirectory() as tmpdir:
        out_dir = Path(tmpdir)
        sessions = make_synthetic_dataset()

        summary1, forecasts1, reconciliations1 = run_shadow_replay(
            symbol="NIFTY",
            usable_sessions=sessions,
            out_dir=out_dir,
            min_history_days=20,
        )

        assert summary1["idempotency_pass"] is True
        assert summary1["duplicate_count"] == 0
        assert summary1["evaluated_sessions"] == 5
        assert len(forecasts1) == 10  # 5 sessions * 2 snapshots (09:16 and 09:30)

        # Check provenance tag
        forecast_file = out_dir / "replay" / "nifty_shadow_forecasts.jsonl"
        assert forecast_file.exists()
        with open(forecast_file, "r", encoding="utf-8") as f:
            lines = [json.loads(l) for l in f if l.strip()]
        assert all(l.get("shadow_tag") == "HISTORICAL_SHADOW_REPLAY" for l in lines)

        # Second run on same directory: Idempotency should guarantee 0 duplicates
        summary2, forecasts2, reconciliations2 = run_shadow_replay(
            symbol="NIFTY",
            usable_sessions=sessions,
            out_dir=out_dir,
            min_history_days=20,
        )
        assert summary2["idempotency_pass"] is True
        assert summary2["duplicate_count"] == 0
        
        # Total lines in file should remain 10 (no double writing)
        with open(forecast_file, "r", encoding="utf-8") as f:
            lines2 = [json.loads(l) for l in f if l.strip()]
        assert len(lines2) == 10
