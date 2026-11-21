"""Unit tests for range_labels_v1 and range_backtest_v1."""
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from smc.models import Candle
from smc.range_backtest_v1 import pinball_loss, run_walk_forward_backtest
from smc.range_labels_v1 import compute_session_labels

IST = ZoneInfo("Asia/Kolkata")


def test_pinball_loss_exact_values():
    # When y > y_hat: loss = q * (y - y_hat)
    # y = 200, y_hat = 150, q = 0.90 -> 0.90 * 50 = 45.0
    assert pinball_loss(200.0, 150.0, 0.90) == 45.0
    
    # When y < y_hat: loss = (q - 1) * (y - y_hat)
    # y = 100, y_hat = 150, q = 0.10 -> (0.10 - 1.0) * (-50) = -0.9 * -50 = 45.0
    assert pinball_loss(100.0, 150.0, 0.10) == 45.0


def test_session_label_high_low_asymmetry():
    # Construct 360 bars for a session
    # 09:16 is bar 0.
    # Put extreme high at 09:20 (bar 4), and lower high for rest of day.
    base_dt = datetime(2026, 11, 20, 9, 16, tzinfo=IST)
    bars: list[Candle] = []
    for i in range(360):
        t = base_dt + timedelta(minutes=i)
        if i == 4:  # 09:20 IST
            h = 25500.0
            l = 24900.0
        else:
            h = 25100.0
            l = 24950.0
        bars.append(Candle(timestamp=t, open=25000.0, high=h, low=l, close=25000.0, volume=10.0))
    
    # Ground truth for entire day: max high is 25500, min low is 24900 -> range 600
    # From 09:16 snapshot: future bars include 09:20 peak (25500)
    labels_0916 = compute_session_labels(bars, as_of="09:16", spot_at_asof=25000.0)
    assert labels_0916.daily_total_range == 600.0
    assert labels_0916.future_upside == 500.0  # (25500 - 25000)
    
    # From 09:30 snapshot: future bars are > 09:30 (bar 14), so they MUST NOT include the 09:20 peak!
    labels_0930 = compute_session_labels(bars, as_of="09:30", spot_at_asof=25000.0)
    assert labels_0930.daily_total_range == 600.0
    assert labels_0930.future_upside == 100.0  # Max high after 09:30 is only 25100, NOT 25500!


def test_walk_forward_backtest_runner_synthetic():
    # 25 synthetic sessions, each with 360 bars
    sessions: dict[str, list[Candle]] = {}
    base_date = datetime(2026, 10, 1, 9, 16, tzinfo=IST)
    
    for day_i in range(25):
        day_date = (base_date + timedelta(days=day_i)).date().isoformat()
        day_bars: list[Candle] = []
        for m in range(360):
            t = datetime.combine((base_date + timedelta(days=day_i)).date(), datetime.min.time(), tzinfo=IST).replace(hour=9, minute=16) + timedelta(minutes=m)
            day_bars.append(Candle(
                timestamp=t,
                open=25000.0,
                high=25100.0 + (day_i % 5) * 10,
                low=24900.0 - (day_i % 5) * 10,
                close=25020.0,
                volume=100.0,
            ))
        sessions[day_date] = day_bars
        
    summary, records = run_walk_forward_backtest(
        symbol="NIFTY",
        usable_sessions=sessions,
        warmup_sessions=20,
    )
    
    assert summary.total_audited_sessions == 25
    assert summary.evaluated_sessions == 5
    assert summary.sample_records_count == 10  # 5 sessions * 2 snapshots (09:16 and 09:30)
    assert summary.overall_mae_q50 > 0.0
    assert summary.snapshot_0916["mae_q50"] > 0.0
    assert summary.snapshot_0930["mae_q50"] > 0.0
    assert 0.0 <= summary.overall_coverage_80pct <= 1.0
    assert 0.0 <= summary.overall_brier_score <= 1.0
    assert len(records) == 10
