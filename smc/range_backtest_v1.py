"""Chronological walk-forward evaluation engine for Range Predictor V2.

Evaluates deterministic baseline forecasts across historical sessions without leakage.
Computes MAE, Median Absolute Error, Pinball Loss (q10/q50/q90), empirical coverage,
causal rolling base-rate reference, Brier skill score, and independent snapshot cohorts.
"""
from __future__ import annotations

import csv
import json
import statistics
from dataclasses import asdict, dataclass, field
from datetime import datetime, time as dtime
from pathlib import Path
from typing import Any, Sequence
from zoneinfo import ZoneInfo

from .models import Candle
from .range_dataset_v1 import DatasetRow, build_daily_bars, generate_range_dataset
from .range_features_v1 import DailyBar, compute_atr, compute_nr7
from .range_predictor_v1 import TARGET_NAME, RangeSnapshot, generate_daily_range_forecast

IST = ZoneInfo("Asia/Kolkata")


def pinball_loss(y: float, y_hat: float, q: float) -> float:
    """Quantile pinball loss: max(q * (y - y_hat), (q - 1) * (y - y_hat))."""
    diff = y - y_hat
    return q * diff if diff >= 0 else (q - 1.0) * diff


@dataclass
class BacktestPredictionRecord:
    """Individual prediction and realized outcome row."""
    trading_date: str
    as_of: str
    symbol: str
    target_name: str
    spot_at_asof: float
    atr14: float
    is_nr7: bool
    predicted_q10: float
    predicted_q50: float
    predicted_q90: float
    predicted_p_expansion: float
    rolling_base_rate_reference: float
    actual_range: float
    actual_expansion: int
    covered_in_interval: bool
    absolute_error_q50: float
    pinball_q10: float
    pinball_q50: float
    pinball_q90: float
    brier_error: float
    brier_reference_error: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class SnapshotMetrics:
    """Evaluated performance for a single snapshot cohort (e.g. 09:16 or 09:30)."""
    snapshot_time: str
    sample_sessions_count: int
    mae_q50: float
    median_absolute_error: float
    pinball_loss_q10: float
    pinball_loss_q50: float
    pinball_loss_q90: float
    empirical_coverage_80pct: float
    expansion_brier_score: float
    expansion_reference_brier: float
    brier_skill_score: float
    expansion_base_rate: float


@dataclass
class BacktestSummary:
    """Comprehensive evaluation metrics for a backtest run."""
    symbol: str
    target_name: str
    total_audited_sessions: int
    evaluated_sessions: int
    warmup_sessions: int
    sample_records_count: int
    overall_mae_q50: float
    overall_median_absolute_error: float
    overall_coverage_80pct: float
    overall_brier_score: float
    overall_reference_brier: float
    overall_brier_skill_score: float
    snapshot_0916: dict[str, Any] = field(default_factory=dict)
    snapshot_0930: dict[str, Any] = field(default_factory=dict)
    delta_0930_vs_0916: dict[str, float] = field(default_factory=dict)
    volatility_regimes: dict[str, Any] = field(default_factory=dict)
    run_timestamp: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _eval_cohort(records: list[BacktestPredictionRecord], snap_name: str) -> SnapshotMetrics:
    sub = [r for r in records if r.as_of == snap_name]
    sn = len(sub)
    if sn == 0:
        return SnapshotMetrics(snap_name, 0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0)
    
    mae = sum(r.absolute_error_q50 for r in sub) / sn
    med_ae = statistics.median(r.absolute_error_q50 for r in sub)
    pb10 = sum(r.pinball_q10 for r in sub) / sn
    pb50 = sum(r.pinball_q50 for r in sub) / sn
    pb90 = sum(r.pinball_q90 for r in sub) / sn
    cov80 = sum(1 for r in sub if r.covered_in_interval) / sn
    brier = sum(r.brier_error for r in sub) / sn
    brier_ref = sum(r.brier_reference_error for r in sub) / sn
    bss = (1.0 - (brier / brier_ref)) if brier_ref > 0 else 0.0
    base_rate = sum(r.actual_expansion for r in sub) / sn
    
    return SnapshotMetrics(
        snapshot_time=snap_name,
        sample_sessions_count=sn,
        mae_q50=round(mae, 2),
        median_absolute_error=round(med_ae, 2),
        pinball_loss_q10=round(pb10, 3),
        pinball_loss_q50=round(pb50, 3),
        pinball_loss_q90=round(pb90, 3),
        empirical_coverage_80pct=round(cov80, 4),
        expansion_brier_score=round(brier, 4),
        expansion_reference_brier=round(brier_ref, 4),
        brier_skill_score=round(bss, 4),
        expansion_base_rate=round(base_rate, 4),
    )


def run_walk_forward_backtest(
    symbol: str,
    usable_sessions: dict[str, list[Candle]],
    warmup_sessions: int = 20,
    atr_period: int = 14,
    expansion_factor: float = 1.25,
) -> tuple[BacktestSummary, list[BacktestPredictionRecord]]:
    """Execute strictly causal chronological rolling-origin walk-forward evaluation.
    
    Groups snapshots by date so 09:16 and 09:30 belong to the same fold.
    Never trains or calibrates on the test session or any future session.
    """
    sorted_dates = sorted(usable_sessions.keys())
    daily_bars = build_daily_bars(usable_sessions)
    
    if len(sorted_dates) <= warmup_sessions:
        raise ValueError(f"Total sessions ({len(sorted_dates)}) <= warmup sessions ({warmup_sessions})")
    
    records: list[BacktestPredictionRecord] = []
    
    for t_idx in range(warmup_sessions, len(sorted_dates)):
        test_date = sorted_dates[t_idx]
        test_bars = usable_sessions[test_date]
        
        # Prior completed daily history strictly prior to test session
        prior_daily = daily_bars[:t_idx]
        
        # Test session ground truth labels (strictly within REGULAR_360)
        session_high = max(b.high for b in test_bars)
        session_low = min(b.low for b in test_bars)
        actual_range = round(session_high - session_low, 2)
        
        # Calibrate baseline ATR
        test_atr14 = compute_atr(prior_daily, period=atr_period)
        if test_atr14 is None:
            continue
            
        test_is_nr7 = compute_nr7(prior_daily)
        exp_threshold = expansion_factor * test_atr14
        actual_expansion = 1 if actual_range >= exp_threshold else 0
        
        # Evaluate both 09:16 and 09:30 snapshots
        for as_of in ["09:16", "09:30"]:
            cutoff_dt = dtime(9, 16) if as_of == "09:16" else dtime(9, 30)
            intraday_snapshot_bars = [b for b in test_bars if b.timestamp.astimezone(IST).time() <= cutoff_dt]
            if not intraday_snapshot_bars:
                intraday_snapshot_bars = [test_bars[0]]
            
            spot = intraday_snapshot_bars[-1].close
            as_of_iso = intraday_snapshot_bars[-1].timestamp.astimezone(IST).isoformat()
            
            snapshot = RangeSnapshot(
                symbol=symbol,
                trading_date=test_date,
                as_of_ist=as_of_iso,
                session_definition="REGULAR_360",
                spot_at_asof=spot,
                prior_completed_days=prior_daily,
                intraday_bars=intraday_snapshot_bars,
            )
            
            forecast = generate_daily_range_forecast(
                snapshot=snapshot,
                atr_period=atr_period,
                expansion_atr_factor=expansion_factor,
            )
            
            q10 = forecast.forecast["daily_total_range_q10"]
            q50 = forecast.forecast["daily_total_range_q50"]
            q90 = forecast.forecast["daily_total_range_q90"]
            p_exp = forecast.forecast["p_expansion"] or 0.15
            p_base_ref = forecast.forecast.get("p_expansion_base_rate") or 0.15
            
            covered = (q10 <= actual_range <= q90)
            abs_err = abs(actual_range - q50)
            pb_10 = pinball_loss(actual_range, q10, 0.10)
            pb_50 = pinball_loss(actual_range, q50, 0.50)
            pb_90 = pinball_loss(actual_range, q90, 0.90)
            brier_err = (p_exp - actual_expansion) ** 2
            brier_ref_err = (p_base_ref - actual_expansion) ** 2
            
            record = BacktestPredictionRecord(
                trading_date=test_date,
                as_of=as_of,
                symbol=symbol,
                target_name=TARGET_NAME,
                spot_at_asof=spot,
                atr14=round(test_atr14, 2),
                is_nr7=test_is_nr7,
                predicted_q10=q10,
                predicted_q50=q50,
                predicted_q90=q90,
                predicted_p_expansion=round(p_exp, 4),
                rolling_base_rate_reference=round(p_base_ref, 4),
                actual_range=actual_range,
                actual_expansion=actual_expansion,
                covered_in_interval=covered,
                absolute_error_q50=round(abs_err, 2),
                pinball_q10=round(pb_10, 3),
                pinball_q50=round(pb_50, 3),
                pinball_q90=round(pb_90, 3),
                brier_error=round(brier_err, 4),
                brier_reference_error=round(brier_ref_err, 4),
            )
            records.append(record)
            
    # Calculate independent snapshot cohorts
    m_0916 = _eval_cohort(records, "09:16")
    m_0930 = _eval_cohort(records, "09:30")
    
    # Delta comparison: 09:30 vs 09:16
    delta = {
        "delta_mae_pts": round(m_0930.mae_q50 - m_0916.mae_q50, 2),
        "delta_median_ae_pts": round(m_0930.median_absolute_error - m_0916.median_absolute_error, 2),
        "delta_coverage_pct": round(m_0930.empirical_coverage_80pct - m_0916.empirical_coverage_80pct, 4),
        "delta_pinball_q50": round(m_0930.pinball_loss_q50 - m_0916.pinball_loss_q50, 3),
        "delta_brier_skill": round(m_0930.brier_skill_score - m_0916.brier_skill_score, 4),
    }
    
    # Volatility regime breakdown (using 09:16 cohort of independent sessions)
    rec_0916 = [r for r in records if r.as_of == "09:16"]
    nr7_records = [r for r in rec_0916 if r.is_nr7]
    non_nr7_records = [r for r in rec_0916 if not r.is_nr7]
    
    atrs = sorted(r.atr14 for r in rec_0916)
    t_33 = atrs[len(atrs) // 3]
    t_66 = atrs[(2 * len(atrs)) // 3]
    low_atr_records = [r for r in rec_0916 if r.atr14 <= t_33]
    high_atr_records = [r for r in rec_0916 if r.atr14 >= t_66]
    
    def _sub_stats(sub_recs: list[BacktestPredictionRecord]) -> dict[str, Any]:
        if not sub_recs:
            return {}
        n = len(sub_recs)
        return {
            "sessions_count": n,
            "mae_q50": round(sum(r.absolute_error_q50 for r in sub_recs) / n, 2),
            "median_ae": round(statistics.median(r.absolute_error_q50 for r in sub_recs), 2),
            "coverage_80pct": round(sum(1 for r in sub_recs if r.covered_in_interval) / n, 4),
            "expansion_rate": round(sum(r.actual_expansion for r in sub_recs) / n, 4),
        }
        
    vol_regimes = {
        "nr7_sessions": _sub_stats(nr7_records),
        "non_nr7_sessions": _sub_stats(non_nr7_records),
        "low_volatility_tercile": _sub_stats(low_atr_records),
        "high_volatility_tercile": _sub_stats(high_atr_records),
    }
    
    n_total = len(records)
    summary = BacktestSummary(
        symbol=symbol,
        target_name=TARGET_NAME,
        total_audited_sessions=len(sorted_dates),
        evaluated_sessions=len(sorted_dates) - warmup_sessions,
        warmup_sessions=warmup_sessions,
        sample_records_count=n_total,
        overall_mae_q50=round(sum(r.absolute_error_q50 for r in records) / n_total, 2),
        overall_median_absolute_error=round(statistics.median(r.absolute_error_q50 for r in records), 2),
        overall_coverage_80pct=round(sum(1 for r in records if r.covered_in_interval) / n_total, 4),
        overall_brier_score=round(sum(r.brier_error for r in records) / n_total, 4),
        overall_reference_brier=round(sum(r.brier_reference_error for r in records) / n_total, 4),
        overall_brier_skill_score=round(1.0 - ((sum(r.brier_error for r in records)) / (sum(r.brier_reference_error for r in records))), 4),
        snapshot_0916=asdict(m_0916),
        snapshot_0930=asdict(m_0930),
        delta_0930_vs_0916=delta,
        volatility_regimes=vol_regimes,
        run_timestamp=datetime.now(IST).isoformat(),
    )
    
    return summary, records


def save_backtest_artifacts(
    summary: BacktestSummary,
    records: list[BacktestPredictionRecord],
    out_dir: Path,
    run_id: str | None = None,
) -> Path:
    """Save backtest metrics.json and predictions.csv to portable output directory."""
    if run_id is None:
        run_id = f"{summary.symbol.lower()}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    target_dir = out_dir / "backtests" / run_id
    target_dir.mkdir(parents=True, exist_ok=True)
    
    # Save metrics JSON
    metrics_path = target_dir / "metrics.json"
    with open(metrics_path, "w", encoding="utf-8") as f:
        json.dump(summary.to_dict(), f, indent=2)
        
    # Save predictions CSV
    csv_path = target_dir / "predictions.csv"
    if records:
        fieldnames = list(records[0].to_dict().keys())
        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for r in records:
                writer.writerow(r.to_dict())
                
    return target_dir
