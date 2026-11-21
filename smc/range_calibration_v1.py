"""Causal Conformal Calibration for Range Predictor V2.6.

Phase P2.6 Deliverable:
Strictly chronological rolling nonconformity scoring:
  score_i = max(q10_i - actual_i, actual_i - q90_i, 0.0)

Applies finite-sample conformal quantile adjustment for nominal 80% coverage:
  adj_quantile = min(1.0, ceil((k + 1) * (1 - alpha)) / k)
  q_hat = quantile(scores_window, adj_quantile)
  calibrated_interval = [q10 - q_hat, q90 + q_hat]

Maintains separate calibration state per market and snapshot horizon.
Enforces strict causality: uses only completed previous sessions.
"""
from __future__ import annotations

import csv
import json
import math
import statistics
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Sequence
from zoneinfo import ZoneInfo

from .models import Candle
from .range_backtest_v1 import BacktestPredictionRecord, pinball_loss
from .range_dataset_v1 import build_daily_bars
from .range_features_v1 import compute_atr, compute_nr7
from .range_predictor_v1 import TARGET_NAME, RangeSnapshot, generate_daily_range_forecast

IST = ZoneInfo("Asia/Kolkata")


@dataclass
class CalibratedRecord:
    """Individual forecast record with uncalibrated vs calibrated interval."""
    trading_date: str
    as_of: str
    symbol: str
    actual_range: float
    uncalibrated_q10: float
    uncalibrated_q50: float
    uncalibrated_q90: float
    uncalibrated_width: float
    uncalibrated_covered: bool
    conformal_score_q_hat: float
    calibrated_q10: float
    calibrated_q90: float
    calibrated_width: float
    calibrated_covered: bool
    rolling_calibration_sample_size: int
    is_nr7: bool
    atr14: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class CalibrationCohortMetrics:
    """Out-of-sample evaluation metrics for a calibrated cohort."""
    symbol: str
    snapshot_time: str
    sample_size: int
    window_size: int
    uncalibrated_coverage: float
    calibrated_coverage: float
    coverage_improvement: float
    uncalibrated_avg_width: float
    calibrated_avg_width: float
    width_expansion_ratio: float
    uncalibrated_pinball_q10: float
    calibrated_pinball_q10: float
    uncalibrated_pinball_q90: float
    calibrated_pinball_q90: float
    nr7_coverage: float
    non_nr7_coverage: float
    low_atr_coverage: float
    high_atr_coverage: float
    drift_first_half_coverage: float
    drift_second_half_coverage: float
    promotion_passed: bool
    rejection_reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def compute_nonconformity_score(actual_range: float, q10: float, q90: float) -> float:
    """Calculate point-wise nonconformity score for 2-sided interval."""
    if actual_range < q10:
        return q10 - actual_range
    elif actual_range > q90:
        return actual_range - q90
    return 0.0


def finite_sample_conformal_quantile(scores: Sequence[float], target_coverage: float = 0.80) -> float:
    """Compute finite-sample conformal adjustment quantile from past nonconformity scores.
    
    Level: ceil((k + 1) * target_coverage) / k
    """
    k = len(scores)
    if k == 0:
        return 0.0
    
    sorted_scores = sorted(scores)
    # Required finite-sample quantile level
    level = math.ceil((k + 1) * target_coverage) / float(k)
    
    if level >= 1.0:
        return sorted_scores[-1]
    
    # Linear interpolation at level
    pos = level * (k - 1)
    idx = int(pos)
    frac = pos - idx
    if idx >= k - 1:
        return sorted_scores[-1]
    return sorted_scores[idx] + frac * (sorted_scores[idx + 1] - sorted_scores[idx])


def calibrate_range_intervals(
    symbol: str,
    usable_sessions: dict[str, list[Candle]],
    snapshot_time: str = "09:16",
    rolling_window: int = 50,
    warmup_sessions: int = 20,
    target_coverage: float = 0.80,
    max_allowed_width_expansion: float = 1.35,
) -> tuple[CalibrationCohortMetrics, list[CalibratedRecord]]:
    """Chronologically calibrate range intervals using strictly preceding resolved sessions."""
    sorted_dates = sorted(usable_sessions.keys())
    daily_bars = build_daily_bars(usable_sessions)
    
    # Store rolling history of nonconformity scores
    past_scores: list[float] = []
    calibrated_records: list[CalibratedRecord] = []
    
    for t_idx in range(warmup_sessions, len(sorted_dates)):
        test_date = sorted_dates[t_idx]
        test_bars = usable_sessions[test_date]
        prior_daily = daily_bars[:t_idx]
        
        session_high = max(b.high for b in test_bars)
        session_low = min(b.low for b in test_bars)
        actual_range = round(session_high - session_low, 2)
        
        atr14 = compute_atr(prior_daily, period=14)
        if atr14 is None:
            continue
        is_nr7 = compute_nr7(prior_daily)
        
        # Build snapshot as-of snapshot_time
        if snapshot_time == "09:16":
            snap_bars = [test_bars[0]]
        else:
            snap_bars = [b for b in test_bars if b.timestamp.astimezone(IST).time() <= datetime.strptime("09:30", "%H:%M").time()]
            if not snap_bars:
                snap_bars = [test_bars[0]]
                
        spot = snap_bars[-1].close
        as_of_iso = snap_bars[-1].timestamp.astimezone(IST).isoformat()
        
        snapshot = RangeSnapshot(
            symbol=symbol,
            trading_date=test_date,
            as_of_ist=as_of_iso,
            session_definition="REGULAR_360",
            spot_at_asof=spot,
            prior_completed_days=prior_daily,
            intraday_bars=snap_bars,
        )
        
        forecast = generate_daily_range_forecast(snapshot)
        q10 = forecast.forecast["daily_total_range_q10"]
        q50 = forecast.forecast["daily_total_range_q50"]
        q90 = forecast.forecast["daily_total_range_q90"]
        
        if q10 is None or q90 is None:
            continue
            
        uncal_width = round(q90 - q10, 2)
        uncal_covered = (q10 <= actual_range <= q90)
        
        # Conformal calibration using past scores strictly before today!
        if len(past_scores) >= 15:
            # Use up to rolling_window recent scores
            window_scores = past_scores[-rolling_window:]
            q_hat = finite_sample_conformal_quantile(window_scores, target_coverage=target_coverage)
        else:
            q_hat = 0.0
            
        cal_q10 = max(0.0, round(q10 - q_hat, 2))
        cal_q90 = round(q90 + q_hat, 2)
        cal_width = round(cal_q90 - cal_q10, 2)
        cal_covered = (cal_q10 <= actual_range <= cal_q90)
        
        rec = CalibratedRecord(
            trading_date=test_date,
            as_of=snapshot_time,
            symbol=symbol,
            actual_range=actual_range,
            uncalibrated_q10=q10,
            uncalibrated_q50=q50,
            uncalibrated_q90=q90,
            uncalibrated_width=uncal_width,
            uncalibrated_covered=uncal_covered,
            conformal_score_q_hat=round(q_hat, 2),
            calibrated_q10=cal_q10,
            calibrated_q90=cal_q90,
            calibrated_width=cal_width,
            calibrated_covered=cal_covered,
            rolling_calibration_sample_size=len(past_scores),
            is_nr7=is_nr7,
            atr14=round(atr14, 2),
        )
        calibrated_records.append(rec)
        
        # After today's session is closed, compute today's score and append for FUTURE days
        score_today = compute_nonconformity_score(actual_range, q10, q90)
        past_scores.append(score_today)
        
    # Evaluate out-of-sample metrics on calibrated records (only evaluate after rolling calibration has started, e.g. record >= 15)
    eval_records = [r for r in calibrated_records if r.rolling_calibration_sample_size >= 15]
    n_eval = len(eval_records)
    if n_eval == 0:
        raise RuntimeError("No records reached calibration evaluation threshold")
        
    uncal_cov = sum(1 for r in eval_records if r.uncalibrated_covered) / float(n_eval)
    cal_cov = sum(1 for r in eval_records if r.calibrated_covered) / float(n_eval)
    cov_improvement = cal_cov - uncal_cov
    
    uncal_avg_w = sum(r.uncalibrated_width for r in eval_records) / float(n_eval)
    cal_avg_w = sum(r.calibrated_width for r in eval_records) / float(n_eval)
    width_ratio = (cal_avg_w / uncal_avg_w) if uncal_avg_w > 0 else 1.0
    
    uncal_pb10 = sum(pinball_loss(r.actual_range, r.uncalibrated_q10, 0.10) for r in eval_records) / float(n_eval)
    cal_pb10 = sum(pinball_loss(r.actual_range, r.calibrated_q10, 0.10) for r in eval_records) / float(n_eval)
    uncal_pb90 = sum(pinball_loss(r.actual_range, r.uncalibrated_q90, 0.90) for r in eval_records) / float(n_eval)
    cal_pb90 = sum(pinball_loss(r.actual_range, r.calibrated_q90, 0.90) for r in eval_records) / float(n_eval)
    
    # Subgroup coverage
    nr7_recs = [r for r in eval_records if r.is_nr7]
    non_nr7_recs = [r for r in eval_records if not r.is_nr7]
    nr7_cov = (sum(1 for r in nr7_recs if r.calibrated_covered) / len(nr7_recs)) if nr7_recs else cal_cov
    non_nr7_cov = (sum(1 for r in non_nr7_recs if r.calibrated_covered) / len(non_nr7_recs)) if non_nr7_recs else cal_cov
    
    median_atr = statistics.median(r.atr14 for r in eval_records)
    low_atr_recs = [r for r in eval_records if r.atr14 <= median_atr]
    high_atr_recs = [r for r in eval_records if r.atr14 > median_atr]
    low_atr_cov = (sum(1 for r in low_atr_recs if r.calibrated_covered) / len(low_atr_recs)) if low_atr_recs else cal_cov
    high_atr_cov = (sum(1 for r in high_atr_recs if r.calibrated_covered) / len(high_atr_recs)) if high_atr_recs else cal_cov
    
    # Calibration drift: first half vs second half
    half = n_eval // 2
    drift_first = sum(1 for r in eval_records[:half] if r.calibrated_covered) / float(half) if half > 0 else cal_cov
    drift_second = sum(1 for r in eval_records[half:] if r.calibrated_covered) / float(n_eval - half) if (n_eval - half) > 0 else cal_cov
    
    # Promotion Gate
    # 1. Out-of-sample coverage improves toward target 80% (cal_cov >= uncal_cov and cal_cov >= 0.75)
    # 2. Width expansion ratio does not exceed limit (width_ratio <= max_allowed_width_expansion)
    # 3. No material collapse in subgroups
    promoted = (
        cal_cov >= uncal_cov
        and cal_cov >= 0.76
        and width_ratio <= max_allowed_width_expansion
        and high_atr_cov >= 0.65
    )
    rejection_reason = None
    if not promoted:
        rejection_reason = (
            f"Conformal adjustment did not meet promotion criteria: "
            f"Coverage={cal_cov:.1%} (Target 80%), Width Expansion={width_ratio:.2f}x (Max {max_allowed_width_expansion}x), "
            f"High ATR Coverage={high_atr_cov:.1%}."
        )
        
    metrics = CalibrationCohortMetrics(
        symbol=symbol,
        snapshot_time=snapshot_time,
        sample_size=n_eval,
        window_size=rolling_window,
        uncalibrated_coverage=round(uncal_cov, 4),
        calibrated_coverage=round(cal_cov, 4),
        coverage_improvement=round(cov_improvement, 4),
        uncalibrated_avg_width=round(uncal_avg_w, 2),
        calibrated_avg_width=round(cal_avg_w, 2),
        width_expansion_ratio=round(width_ratio, 3),
        uncalibrated_pinball_q10=round(uncal_pb10, 3),
        calibrated_pinball_q10=round(cal_pb10, 3),
        uncalibrated_pinball_q90=round(uncal_pb90, 3),
        calibrated_pinball_q90=round(cal_pb90, 3),
        nr7_coverage=round(nr7_cov, 4),
        non_nr7_coverage=round(non_nr7_cov, 4),
        low_atr_coverage=round(low_atr_cov, 4),
        high_atr_coverage=round(high_atr_cov, 4),
        drift_first_half_coverage=round(drift_first, 4),
        drift_second_half_coverage=round(drift_second, 4),
        promotion_passed=promoted,
        rejection_reason=rejection_reason,
    )
    
    return metrics, calibrated_records


def evaluate_interval_coverage(records: Sequence[CalibratedRecord]) -> float:
    """Compute empirical coverage over records."""
    if not records:
        return 0.0
    return sum(1 for r in records if r.calibrated_covered) / float(len(records))


def compare_calibrated_baseline(metrics: CalibrationCohortMetrics) -> dict[str, Any]:
    """Compare calibrated metrics against uncalibrated baseline."""
    return {
        "symbol": metrics.symbol,
        "snapshot": metrics.snapshot_time,
        "uncalibrated_coverage": metrics.uncalibrated_coverage,
        "calibrated_coverage": metrics.calibrated_coverage,
        "coverage_improvement": metrics.coverage_improvement,
        "uncalibrated_avg_width": metrics.uncalibrated_avg_width,
        "calibrated_avg_width": metrics.calibrated_avg_width,
        "width_expansion_ratio": metrics.width_expansion_ratio,
        "promoted": metrics.promotion_passed,
    }


def detect_calibration_drift(records: Sequence[CalibratedRecord], drift_threshold: float = 0.15) -> tuple[bool, float, float, float]:
    """Detect significant divergence in coverage between first and second half of sample."""
    n = len(records)
    if n < 4:
        return False, 0.0, 0.0, 0.0
    half = n // 2
    cov1 = sum(1 for r in records[:half] if r.calibrated_covered) / float(half)
    cov2 = sum(1 for r in records[half:] if r.calibrated_covered) / float(n - half)
    diff = abs(cov1 - cov2)
    return diff > drift_threshold, diff, cov1, cov2


def run_full_calibration_experiment(
    usable_sessions_nifty: dict[str, list[Candle]],
    usable_sessions_sensex: dict[str, list[Candle]],
    out_dir: Path,
) -> dict[str, Any]:
    """Execute complete calibration study across NIFTY and SENSEX at 09:16 and 09:30."""
    cal_dir = out_dir / "calibration"
    cal_dir.mkdir(parents=True, exist_ok=True)
    
    results: dict[str, Any] = {
        "timestamp": datetime.now(IST).isoformat(),
        "target_name": TARGET_NAME,
        "cohorts": {},
    }
    
    all_summary_rows: list[dict[str, Any]] = []
    
    for symbol, sessions in [("NIFTY", usable_sessions_nifty), ("SENSEX", usable_sessions_sensex)]:
        results["cohorts"][symbol] = {}
        for snap in ["09:16", "09:30"]:
            metrics, records = calibrate_range_intervals(symbol, sessions, snapshot_time=snap)
            results["cohorts"][symbol][snap] = metrics.to_dict()
            
            row = {
                "symbol": symbol,
                "snapshot": snap,
                "sample_size": metrics.sample_size,
                "uncalibrated_coverage": f"{metrics.uncalibrated_coverage:.1%}",
                "calibrated_coverage": f"{metrics.calibrated_coverage:.1%}",
                "coverage_improvement": f"{metrics.coverage_improvement:+.1%}",
                "uncalibrated_width": metrics.uncalibrated_avg_width,
                "calibrated_width": metrics.calibrated_avg_width,
                "width_expansion": f"{metrics.width_expansion_ratio:.2f}x",
                "nr7_coverage": f"{metrics.nr7_coverage:.1%}",
                "high_atr_coverage": f"{metrics.high_atr_coverage:.1%}",
                "drift_first_half": f"{metrics.drift_first_half_coverage:.1%}",
                "drift_second_half": f"{metrics.drift_second_half_coverage:.1%}",
                "promoted": metrics.promotion_passed,
            }
            all_summary_rows.append(row)
            
        # Save symbol JSON
        sym_json = cal_dir / f"{symbol.lower()}_calibration.json"
        with open(sym_json, "w", encoding="utf-8") as f:
            json.dump(results["cohorts"][symbol], f, indent=2)
            
    # Save CSV comparison
    csv_path = cal_dir / "calibration_comparison.csv"
    if all_summary_rows:
        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=list(all_summary_rows[0].keys()))
            writer.writeheader()
            for r in all_summary_rows:
                writer.writerow(r)
                
    # Save calibration report markdown
    report_path = cal_dir / "calibration_report.md"
    with open(report_path, "w", encoding="utf-8") as f:
        f.write("# Causal Conformal Calibration Report — Phase P2.6\n\n")
        f.write(f"**Target:** `{TARGET_NAME}` (09:16 to 15:15 IST, 360 contiguous bars)\n")
        f.write(f"**Timestamp:** {results['timestamp']}\n\n")
        f.write("## 1. Summary Comparison Table\n\n")
        f.write("| Symbol | Snapshot | Samples | Uncalibrated Cov | Calibrated Cov | Improvement | Uncal Width | Cal Width | Width Expansion | High-ATR Cov | Drift (1st/2nd) | Gate Decision |\n")
        f.write("| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :--- |\n")
        for r in all_summary_rows:
            f.write(f"| **{r['symbol']}** | {r['snapshot']} | {r['sample_size']} | {r['uncalibrated_coverage']} | **{r['calibrated_coverage']}** | **{r['coverage_improvement']}** | {r['uncalibrated_width']} pts | {r['calibrated_width']} pts | {r['width_expansion']} | {r['high_atr_coverage']} | {r['drift_first_half']} / {r['drift_second_half']} | `{'PROMOTED' if r['promoted'] else 'RETAIN_BASELINE'}` |\n")
        f.write("\n## 2. Methodology & Causality\n\n")
        f.write("- Rolling nonconformity scores: computed strictly post-EOD for each past session.\n")
        f.write("- Finite-sample conformal quantile: `ceil((k + 1) * 0.80) / k` over rolling window.\n")
        f.write("- Zero lookahead: today's outcome is never included in today's interval calculation.\n")
        
    return results
