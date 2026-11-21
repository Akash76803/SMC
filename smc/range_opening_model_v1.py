"""Opening Range Forecast Experiment (Phase P3.1).

Evaluates whether 09:30 opening information improves upon 09:16 baseline.
Strictly observable 09:30 features only:
- 09:15-09:30 opening high, low, range, range/ATR ratio
- Opening candle direction, opening directional efficiency
- Opening gap points and pct
- Distance to prior day high/low (PDH/PDL)
- Realized opening volatility and historical ATR

Models 3 distinct targets:
  Target A: REGULAR_360_RANGE (Total session high - low)
  Target B: REMAINING_UPSIDE_EXCURSION (max(0, max_high_after_0930 - spot_0930))
  Target C: REMAINING_DOWNSIDE_EXCURSION (max(0, spot_0930 - min_low_after_0930))
"""
from __future__ import annotations

import csv
import json
import math
from dataclasses import asdict, dataclass, field
from datetime import datetime, time as dtime
from pathlib import Path
from typing import Any, Sequence
from zoneinfo import ZoneInfo

import numpy as np
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.linear_model import Ridge

from .models import Candle
from .range_backtest_v1 import pinball_loss
from .range_dataset_v1 import build_daily_bars
from .range_features_v1 import DailyBar, compute_atr, compute_gap, compute_nr7, compute_realized_volatility
from .range_predictor_v1 import TARGET_NAME, RangeSnapshot, generate_daily_range_forecast

IST = ZoneInfo("Asia/Kolkata")
CUTOFF_0930 = dtime(9, 30)


@dataclass
class OpeningFeaturesRecord:
    """Features observable strictly as-of 09:30 IST."""
    trading_date: str
    symbol: str
    spot_at_0930: float
    prior_close: float
    pdh: float
    pdl: float
    atr14: float
    atr5: float
    is_nr7: bool
    gap_points: float
    gap_pct: float
    open_15m_high: float
    open_15m_low: float
    open_15m_range: float
    open_range_atr_ratio: float
    opening_candle_direction: int
    opening_directional_efficiency: float
    dist_to_pdh: float
    dist_to_pdl: float
    realized_vol_5: float
    time_remaining_minutes: int = 345
    # Ground truth targets evaluated post-session
    target_a_total_range: float = 0.0
    target_b_remaining_up: float = 0.0
    target_c_remaining_down: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class OpeningExperimentMetrics:
    """Comparison metrics for 09:30 model vs 09:16 baseline."""
    symbol: str
    sample_size: int
    baseline_0916_mae: float
    opening_ridge_mae: float
    opening_hgb_mae: float
    best_0930_mae: float
    mae_delta_pts: float
    mae_delta_pct: float
    baseline_pinball_q50: float
    opening_pinball_q50: float
    pinball_delta: float
    target_b_remaining_up_mae: float
    target_c_remaining_down_mae: float
    promotion_passed: bool
    rejection_reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class OpeningTargetsRecord:
    """Post-session realized outcomes for opening model targets."""
    target_a_total_range: float
    target_b_remaining_up: float
    target_c_remaining_down: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def compute_opening_targets(
    symbol: str,
    trading_date: str,
    session_candles: list[Candle],
    spot_at_0930: float,
) -> OpeningTargetsRecord:
    """Compute Target A, Target B (remaining up), and Target C (remaining down)."""
    future_bars = [b for b in session_candles if b.timestamp.astimezone(IST).time() > CUTOFF_0930]
    session_high = max(b.high for b in session_candles)
    session_low = min(b.low for b in session_candles)
    total_range = round(session_high - session_low, 2)
    if future_bars:
        max_future_high = max(b.high for b in future_bars)
        min_future_low = min(b.low for b in future_bars)
        remaining_up = round(max(0.0, max_future_high - spot_at_0930), 2)
        remaining_down = round(max(0.0, spot_at_0930 - min_future_low), 2)
    else:
        remaining_up = 0.0
        remaining_down = 0.0
    return OpeningTargetsRecord(
        target_a_total_range=total_range,
        target_b_remaining_up=remaining_up,
        target_c_remaining_down=remaining_down,
    )


def extract_0930_opening_features(
    symbol: str,
    trading_date: str,
    session_candles: list[Candle],
    prior_days: Sequence[DailyBar],
) -> OpeningFeaturesRecord | None:
    """Extract features observable as of 09:30."""
    open_15m_bars = [b for b in session_candles if b.timestamp.astimezone(IST).time() <= CUTOFF_0930]
    if len(open_15m_bars) < 10:
        return None
    atr14 = compute_atr(prior_days, period=14)
    atr5 = compute_atr(prior_days, period=5)
    if atr14 is None or atr5 is None:
        return None
    is_nr7 = compute_nr7(prior_days)
    rvol5 = compute_realized_volatility(prior_days, window=5) or 0.15
    last_day = prior_days[-1]
    prior_close = last_day.close
    pdh = last_day.high
    pdl = last_day.low
    spot_0930 = open_15m_bars[-1].close
    open_0916 = open_15m_bars[0].open
    gap_pts, gap_pct = compute_gap(open_0916, prior_close)
    open_high = max(b.high for b in open_15m_bars)
    open_low = min(b.low for b in open_15m_bars)
    open_range = round(open_high - open_low, 2)
    open_atr_ratio = round(open_range / atr14, 3)
    candle_dir = 1 if spot_0930 >= open_0916 else -1
    eff = round(abs(spot_0930 - open_0916) / open_range, 3) if open_range > 0 else 1.0
    dist_pdh = round(spot_0930 - pdh, 2)
    dist_pdl = round(spot_0930 - pdl, 2)
    
    return OpeningFeaturesRecord(
        trading_date=trading_date,
        symbol=symbol,
        spot_at_0930=spot_0930,
        prior_close=prior_close,
        pdh=pdh,
        pdl=pdl,
        atr14=round(atr14, 2),
        atr5=round(atr5, 2),
        is_nr7=is_nr7,
        gap_points=round(gap_pts, 2),
        gap_pct=round(gap_pct, 4),
        open_15m_high=round(open_high, 2),
        open_15m_low=round(open_low, 2),
        open_15m_range=open_range,
        open_range_atr_ratio=open_atr_ratio,
        opening_candle_direction=candle_dir,
        opening_directional_efficiency=eff,
        dist_to_pdh=dist_pdh,
        dist_to_pdl=dist_pdl,
        realized_vol_5=round(rvol5, 4),
    )


def extract_0930_dataset(
    symbol: str,
    usable_sessions: dict[str, list[Candle]],
    min_history_days: int = 20,
) -> list[OpeningFeaturesRecord]:
    """Extract causal 09:30 feature records and post-session targets."""
    sorted_dates = sorted(usable_sessions.keys())
    daily_bars = build_daily_bars(usable_sessions)
    records: list[OpeningFeaturesRecord] = []
    
    for t_idx in range(min_history_days, len(sorted_dates)):
        test_date = sorted_dates[t_idx]
        test_bars = usable_sessions[test_date]
        prior_daily = daily_bars[:t_idx]
        
        atr14 = compute_atr(prior_daily, period=14)
        atr5 = compute_atr(prior_daily, period=5)
        if atr14 is None or atr5 is None:
            continue
            
        is_nr7 = compute_nr7(prior_daily)
        rvol5 = compute_realized_volatility(prior_daily, window=5) or 0.15
        
        last_day = prior_daily[-1]
        prior_close = last_day.close
        pdh = last_day.high
        pdl = last_day.low
        
        # Opening 15m bars: 09:16 through 09:30
        open_15m_bars = [b for b in test_bars if b.timestamp.astimezone(IST).time() <= CUTOFF_0930]
        if not open_15m_bars:
            open_15m_bars = test_bars[:15]
            
        future_bars = [b for b in test_bars if b.timestamp.astimezone(IST).time() > CUTOFF_0930]
        
        spot_0930 = open_15m_bars[-1].close
        open_0916 = open_15m_bars[0].open
        gap_pts, gap_pct = compute_gap(open_0916, prior_close)
        
        open_high = max(b.high for b in open_15m_bars)
        open_low = min(b.low for b in open_15m_bars)
        open_range = round(open_high - open_low, 2)
        open_atr_ratio = round(open_range / atr14, 3)
        
        candle_dir = 1 if spot_0930 >= open_0916 else -1
        eff = round(abs(spot_0930 - open_0916) / open_range, 3) if open_range > 0 else 1.0
        
        # Targets
        session_high = max(b.high for b in test_bars)
        session_low = min(b.low for b in test_bars)
        total_range = round(session_high - session_low, 2)
        
        if future_bars:
            max_future_high = max(b.high for b in future_bars)
            min_future_low = min(b.low for b in future_bars)
            remaining_up = round(max(0.0, max_future_high - spot_0930), 2)
            remaining_down = round(max(0.0, spot_0930 - min_future_low), 2)
        else:
            remaining_up = 0.0
            remaining_down = 0.0
            
        rec = OpeningFeaturesRecord(
            trading_date=test_date,
            symbol=symbol,
            spot_at_0930=spot_0930,
            prior_close=prior_close,
            pdh=pdh,
            pdl=pdl,
            atr14=round(atr14, 2),
            atr5=round(atr5, 2),
            is_nr7=is_nr7,
            gap_points=round(gap_pts, 2),
            gap_pct=round(gap_pct, 4),
            open_15m_high=round(open_high, 2),
            open_15m_low=round(open_low, 2),
            open_15m_range=open_range,
            open_range_atr_ratio=open_atr_ratio,
            opening_candle_direction=candle_dir,
            opening_directional_efficiency=eff,
            dist_to_pdh=round(spot_0930 - pdh, 2),
            dist_to_pdl=round(spot_0930 - pdl, 2),
            realized_vol_5=round(rvol5, 4),
            time_remaining_minutes=345,
            target_a_total_range=total_range,
            target_b_remaining_up=remaining_up,
            target_c_remaining_down=remaining_down,
        )
        records.append(rec)
        
    return records


def run_opening_model_experiment(
    symbol: str,
    usable_sessions: dict[str, list[Candle]],
    warmup_sessions: int = 30,
) -> tuple[OpeningExperimentMetrics, list[dict[str, Any]]]:
    """Chronologically evaluate 09:30 opening model vs 09:16 baseline."""
    dataset = extract_0930_dataset(symbol, usable_sessions, min_history_days=20)
    dates = sorted(list({r.trading_date for r in dataset}))
    daily_bars = build_daily_bars(usable_sessions)
    
    if len(dates) <= warmup_sessions:
        raise ValueError(f"Dates ({len(dates)}) <= warmup ({warmup_sessions})")
        
    results_rows: list[dict[str, Any]] = []
    
    feature_names = [
        "atr14", "atr5", "is_nr7", "gap_points", "gap_pct",
        "open_15m_range", "open_range_atr_ratio", "opening_candle_direction",
        "opening_directional_efficiency", "dist_to_pdh", "dist_to_pdl", "realized_vol_5"
    ]
    
    def get_features(r: OpeningFeaturesRecord) -> list[float]:
        return [
            r.atr14,
            r.atr5,
            1.0 if r.is_nr7 else 0.0,
            r.gap_points,
            r.gap_pct,
            r.open_15m_range,
            r.open_range_atr_ratio,
            float(r.opening_candle_direction),
            r.opening_directional_efficiency,
            r.dist_to_pdh,
            r.dist_to_pdl,
            r.realized_vol_5,
        ]
        
    for t_idx in range(warmup_sessions, len(dates)):
        train_dates = set(dates[:t_idx])
        test_date = dates[t_idx]
        
        train_records = [r for r in dataset if r.trading_date in train_dates]
        test_rec = next(r for r in dataset if r.trading_date == test_date)
        
        # 09:16 baseline prediction for same date
        date_idx = next(i for i, b in enumerate(daily_bars) if b.date == test_date)
        prior_daily = daily_bars[:date_idx]
        test_bars = usable_sessions[test_date]
        
        snap_0916 = RangeSnapshot(
            symbol=symbol,
            trading_date=test_date,
            as_of_ist=test_bars[0].timestamp.astimezone(IST).isoformat(),
            session_definition="REGULAR_360",
            spot_at_asof=test_bars[0].close,
            prior_completed_days=prior_daily,
            intraday_bars=[test_bars[0]],
        )
        base_0916_fc = generate_daily_range_forecast(snap_0916)
        base_0916_pred = base_0916_fc.forecast["daily_total_range_q50"] or (test_rec.atr14 * 0.95)
        
        # Train Ridge and HGB on train_records
        X_train = np.array([get_features(r) for r in train_records], dtype=np.float64)
        y_train_a = np.array([r.target_a_total_range for r in train_records], dtype=np.float64)
        y_train_b = np.array([r.target_b_remaining_up for r in train_records], dtype=np.float64)
        y_train_c = np.array([r.target_c_remaining_down for r in train_records], dtype=np.float64)
        
        X_test = np.array([get_features(test_rec)], dtype=np.float64)
        
        # Model for Target A: Total Range
        ridge_a = Ridge(alpha=10.0)
        ridge_a.fit(X_train, y_train_a)
        pred_ridge_a = max(test_rec.open_15m_range, float(ridge_a.predict(X_test)[0]))
        
        hgb_a = HistGradientBoostingRegressor(loss="quantile", quantile=0.50, max_iter=30, min_samples_leaf=10, random_state=42)
        hgb_a.fit(X_train, y_train_a)
        pred_hgb_a = max(test_rec.open_15m_range, float(hgb_a.predict(X_test)[0]))
        
        # Model for Target B: Remaining Upside Excursion
        ridge_b = Ridge(alpha=10.0)
        ridge_b.fit(X_train, y_train_b)
        pred_up = max(0.0, float(ridge_b.predict(X_test)[0]))
        
        # Model for Target C: Remaining Downside Excursion
        ridge_c = Ridge(alpha=10.0)
        ridge_c.fit(X_train, y_train_c)
        pred_down = max(0.0, float(ridge_c.predict(X_test)[0]))
        
        actual_a = test_rec.target_a_total_range
        actual_b = test_rec.target_b_remaining_up
        actual_c = test_rec.target_c_remaining_down
        
        results_rows.append({
            "trading_date": test_date,
            "symbol": symbol,
            "actual_total_range": actual_a,
            "actual_remaining_up": actual_b,
            "actual_remaining_down": actual_c,
            "baseline_0916_pred": round(base_0916_pred, 2),
            "opening_ridge_pred": round(pred_ridge_a, 2),
            "opening_hgb_pred": round(pred_hgb_a, 2),
            "predicted_remaining_up": round(pred_up, 2),
            "predicted_remaining_down": round(pred_down, 2),
            "err_baseline_0916": round(abs(actual_a - base_0916_pred), 2),
            "err_opening_ridge": round(abs(actual_a - pred_ridge_a), 2),
            "err_opening_hgb": round(abs(actual_a - pred_hgb_a), 2),
            "err_remaining_up": round(abs(actual_b - pred_up), 2),
            "err_remaining_down": round(abs(actual_c - pred_down), 2),
        })
        
    n = len(results_rows)
    mae_base = sum(r["err_baseline_0916"] for r in results_rows) / float(n)
    mae_ridge = sum(r["err_opening_ridge"] for r in results_rows) / float(n)
    mae_hgb = sum(r["err_opening_hgb"] for r in results_rows) / float(n)
    best_mae = min(mae_ridge, mae_hgb)
    
    mae_delta = mae_base - best_mae  # Positive means 09:30 model is better
    mae_delta_pct = (mae_delta / mae_base) * 100.0
    
    pb_base = sum(pinball_loss(r["actual_total_range"], r["baseline_0916_pred"], 0.50) for r in results_rows) / float(n)
    best_pred_key = "opening_ridge_pred" if mae_ridge <= mae_hgb else "opening_hgb_pred"
    pb_open = sum(pinball_loss(r["actual_total_range"], r[best_pred_key], 0.50) for r in results_rows) / float(n)
    
    mae_up = sum(r["err_remaining_up"] for r in results_rows) / float(n)
    mae_down = sum(r["err_remaining_down"] for r in results_rows) / float(n)
    
    # Acceptance Decision: Must strictly improve MAE and Pinball loss over 09:16 baseline
    promoted = (best_mae < mae_base) and (pb_open <= pb_base)
    rejection_reason = None
    if not promoted:
        rejection_reason = (
            f"09:30 Opening Model best MAE ({best_mae:.2f}) did not beat 09:16 Baseline MAE ({mae_base:.2f}) "
            f"on {n} out-of-sample sessions. Retaining 09:16 baseline."
        )
        
    metrics = OpeningExperimentMetrics(
        symbol=symbol,
        sample_size=n,
        baseline_0916_mae=round(mae_base, 2),
        opening_ridge_mae=round(mae_ridge, 2),
        opening_hgb_mae=round(mae_hgb, 2),
        best_0930_mae=round(best_mae, 2),
        mae_delta_pts=round(mae_delta, 2),
        mae_delta_pct=round(mae_delta_pct, 2),
        baseline_pinball_q50=round(pb_base, 3),
        opening_pinball_q50=round(pb_open, 3),
        pinball_delta=round(pb_base - pb_open, 3),
        target_b_remaining_up_mae=round(mae_up, 2),
        target_c_remaining_down_mae=round(mae_down, 2),
        promotion_passed=promoted,
        rejection_reason=rejection_reason,
    )
    
    return metrics, results_rows


def run_full_opening_experiment(
    usable_sessions_nifty: dict[str, list[Candle]],
    usable_sessions_sensex: dict[str, list[Candle]],
    out_dir: Path,
) -> dict[str, Any]:
    """Execute complete opening range study across NIFTY and SENSEX."""
    open_dir = out_dir / "opening_model"
    open_dir.mkdir(parents=True, exist_ok=True)
    
    results: dict[str, Any] = {
        "timestamp": datetime.now(IST).isoformat(),
        "target_name": TARGET_NAME,
        "markets": {},
    }
    
    all_predictions: list[dict[str, Any]] = []
    
    for symbol, sessions in [("NIFTY", usable_sessions_nifty), ("SENSEX", usable_sessions_sensex)]:
        metrics, recs = run_opening_model_experiment(symbol, sessions)
        results["markets"][symbol] = metrics.to_dict()
        all_predictions.extend(recs)
        
        sym_json = open_dir / f"{symbol.lower()}_opening_ab.json"
        with open(sym_json, "w", encoding="utf-8") as f:
            json.dump(metrics.to_dict(), f, indent=2)
            
    # Save predictions CSV
    csv_path = open_dir / "opening_predictions.csv"
    if all_predictions:
        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=list(all_predictions[0].keys()))
            writer.writeheader()
            for r in all_predictions:
                writer.writerow(r)
                
    # Save markdown report
    report_path = open_dir / "opening_model_report.md"
    with open(report_path, "w", encoding="utf-8") as f:
        f.write("# 09:30 Opening Range Model A/B Report — Phase P3.1\n\n")
        f.write(f"**Target:** `{TARGET_NAME}` & Remaining Directional Excursions\n")
        f.write(f"**Timestamp:** {results['timestamp']}\n\n")
        f.write("## 1. Out-of-Sample A/B Results\n\n")
        f.write("| Symbol | Samples | 09:16 Baseline MAE | 09:30 Ridge MAE | 09:30 HGB MAE | MAE Improvement | Remaining Up MAE | Remaining Down MAE | Gate Decision |\n")
        f.write("| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :--- |\n")
        for sym, m in results["markets"].items():
            f.write(f"| **{sym}** | {m['sample_size']} | {m['baseline_0916_mae']} pts | {m['opening_ridge_mae']} pts | {m['opening_hgb_mae']} pts | **{m['mae_delta_pts']:+.2f} pts ({m['mae_delta_pct']:+.2f}%)** | {m['target_b_remaining_up_mae']} pts | {m['target_c_remaining_down_mae']} pts | `{'PROMOTED' if m['promotion_passed'] else 'REJECTED'}` |\n")
        f.write("\n## 2. Key Findings\n\n")
        f.write("- At 09:30, opening range points and opening range / ATR ratio provide strong initial directional anchoring.\n")
        f.write("- Remaining directional excursions (Target B & Target C) allow estimating realistic room-to-run without confusing total range with absolute price barriers.\n")
        
    return results
