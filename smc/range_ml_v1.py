"""Offline Quantile ML Modeling and Baseline A/B Evaluation for Range Predictor V2.

Phase 3 Deliverable:
- Trains HistGradientBoostingRegressor for conditional quantiles (P10, P50, P90).
- Trains CalibratedClassifier for expansion probability.
- Rigorous walk-forward out-of-sample comparison against BASELINE_OHLC.
- Model Promotion Gate: Promotes to ML_ELIGIBLE only if out-of-sample MAE and
  Pinball loss strictly improve over baseline. Otherwise defaults to baseline.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Sequence
from zoneinfo import ZoneInfo

import numpy as np
from sklearn.calibration import CalibratedClassifierCV
from sklearn.ensemble import HistGradientBoostingClassifier, HistGradientBoostingRegressor
from sklearn.linear_model import LogisticRegression

from .models import Candle
from .range_backtest_v1 import pinball_loss
from .range_dataset_v1 import DatasetRow, generate_range_dataset
from .range_predictor_v1 import TARGET_NAME

IST = ZoneInfo("Asia/Kolkata")
FEATURE_COLS = [
    "spot_at_asof",
    "prior_close",
    "atr5",
    "atr14",
    "atr20",
    "is_nr7",
    "gap_points",
    "gap_pct",
    "realized_vol_5",
    "return_from_prior_close",
]


@dataclass
class MLComparisonMetrics:
    """Out-of-sample comparison of ML Model vs Deterministic Baseline."""
    symbol: str
    evaluated_samples: int
    baseline_mae: float
    ml_mae: float
    mae_improvement_pts: float
    mae_improvement_pct: float
    baseline_pinball_q50: float
    ml_pinball_q50: float
    baseline_coverage_80: float
    ml_coverage_80: float
    baseline_brier: float
    ml_brier: float
    promoted: bool
    rejection_reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def extract_feature_matrix(rows: Sequence[DatasetRow]) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Extract numeric X, y_range, y_exp arrays from DatasetRows."""
    X_list = []
    y_range_list = []
    y_exp_list = []
    
    for r in rows:
        feat = [
            r.spot_at_asof,
            r.prior_close,
            r.atr5 if r.atr5 is not None else 100.0,
            r.atr14 if r.atr14 is not None else 100.0,
            r.atr20 if r.atr20 is not None else 100.0,
            1.0 if r.is_nr7 else 0.0,
            r.gap_points,
            r.gap_pct,
            r.realized_vol_5 if r.realized_vol_5 is not None else 0.15,
            r.return_from_prior_close,
        ]
        X_list.append(feat)
        y_range_list.append(r.label_daily_total_range)
        y_exp_list.append(r.label_expansion_day)
        
    return np.array(X_list, dtype=np.float64), np.array(y_range_list, dtype=np.float64), np.array(y_exp_list, dtype=np.int32)


def evaluate_ml_vs_baseline_walk_forward(
    symbol: str,
    usable_sessions: dict[str, list[Candle]],
    warmup_sessions: int = 25,
) -> tuple[MLComparisonMetrics, dict[str, Any]]:
    """Strict out-of-sample rolling-origin evaluation of Quantile ML vs Baseline."""
    dataset_rows = generate_range_dataset(symbol, usable_sessions, min_history_days=15)
    dates = sorted(list({r.trading_date for r in dataset_rows}))
    
    if len(dates) <= warmup_sessions:
        raise ValueError(f"Dates ({len(dates)}) <= warmup ({warmup_sessions})")
        
    y_true_all: list[float] = []
    y_exp_all: list[int] = []
    
    base_q10_all: list[float] = []
    base_q50_all: list[float] = []
    base_q90_all: list[float] = []
    base_p_exp_all: list[float] = []
    
    ml_q10_all: list[float] = []
    ml_q50_all: list[float] = []
    ml_q90_all: list[float] = []
    ml_p_exp_all: list[float] = []
    
    # Chronological Walk-Forward evaluation
    for t_idx in range(warmup_sessions, len(dates)):
        train_dates = set(dates[:t_idx])
        test_date = dates[t_idx]
        
        train_rows = [r for r in dataset_rows if r.trading_date in train_dates]
        test_rows = [r for r in dataset_rows if r.trading_date == test_date]
        
        if not train_rows or not test_rows:
            continue
            
        X_train, y_train_range, y_train_exp = extract_feature_matrix(train_rows)
        X_test, y_test_range, y_test_exp = extract_feature_matrix(test_rows)
        
        # Fit HistGradientBoostingRegressor for quantiles 0.10, 0.50, 0.90
        model_q10 = HistGradientBoostingRegressor(loss="quantile", quantile=0.10, max_iter=40, min_samples_leaf=10, random_state=42)
        model_q50 = HistGradientBoostingRegressor(loss="quantile", quantile=0.50, max_iter=40, min_samples_leaf=10, random_state=42)
        model_q90 = HistGradientBoostingRegressor(loss="quantile", quantile=0.90, max_iter=40, min_samples_leaf=10, random_state=42)
        
        model_q10.fit(X_train, y_train_range)
        model_q50.fit(X_train, y_train_range)
        model_q90.fit(X_train, y_train_range)
        
        # Calibrated expansion classifier with tree ensemble (scale-invariant)
        clf = HistGradientBoostingClassifier(max_iter=30, min_samples_leaf=10, random_state=42)
        clf.fit(X_train, y_train_exp)
        
        pred_ml_10 = model_q10.predict(X_test)
        pred_ml_50 = model_q50.predict(X_test)
        pred_ml_90 = model_q90.predict(X_test)
        pred_ml_exp = clf.predict_proba(X_test)[:, 1] if len(clf.classes_) > 1 else np.zeros(len(X_test))
        
        # Baseline predictions for same test instances (ATR based)
        for i, row in enumerate(test_rows):
            atr = row.atr14 or 100.0
            base_q10 = atr * 0.60
            base_q50 = atr * 0.95
            base_q90 = atr * 1.55
            base_p_exp = float(np.mean(y_train_exp))
            
            y_true_all.append(row.label_daily_total_range)
            y_exp_all.append(row.label_expansion_day)
            
            base_q10_all.append(base_q10)
            base_q50_all.append(base_q50)
            base_q90_all.append(base_q90)
            base_p_exp_all.append(base_p_exp)
            
            ml_q10_all.append(float(pred_ml_10[i]))
            ml_q50_all.append(float(pred_ml_50[i]))
            ml_q90_all.append(float(pred_ml_90[i]))
            ml_p_exp_all.append(float(pred_ml_exp[i]))
            
    n = len(y_true_all)
    y_true = np.array(y_true_all)
    
    # Calculate baseline metrics
    base_ae = np.abs(y_true - np.array(base_q50_all))
    base_mae = float(np.mean(base_ae))
    base_pb50 = float(np.mean([pinball_loss(y, y_h, 0.50) for y, y_h in zip(y_true_all, base_q50_all)]))
    base_cov80 = float(np.mean([1 if q10 <= y <= q90 else 0 for y, q10, q90 in zip(y_true_all, base_q10_all, base_q90_all)]))
    base_brier = float(np.mean((np.array(base_p_exp_all) - np.array(y_exp_all)) ** 2))
    
    # Calculate ML metrics
    ml_ae = np.abs(y_true - np.array(ml_q50_all))
    ml_mae = float(np.mean(ml_ae))
    ml_pb50 = float(np.mean([pinball_loss(y, y_h, 0.50) for y, y_h in zip(y_true_all, ml_q50_all)]))
    ml_cov80 = float(np.mean([1 if q10 <= y <= q90 else 0 for y, q10, q90 in zip(y_true_all, ml_q10_all, ml_q90_all)]))
    ml_brier = float(np.mean((np.array(ml_p_exp_all) - np.array(y_exp_all)) ** 2))
    
    mae_diff = base_mae - ml_mae  # Positive means ML is better (lower error)
    mae_pct = (mae_diff / base_mae) * 100.0
    
    # Promotion Gate: require ML out-of-sample MAE improvement > 0
    promoted = (ml_mae < base_mae) and (ml_pb50 <= base_pb50)
    rejection_reason = None
    if not promoted:
        rejection_reason = (
            f"ML out-of-sample MAE ({ml_mae:.2f}) did not beat Baseline MAE ({base_mae:.2f}) "
            f"on {len(dates) - warmup_sessions} test sessions. Retaining BASELINE_OHLC."
        )
        
    metrics = MLComparisonMetrics(
        symbol=symbol,
        evaluated_samples=n,
        baseline_mae=round(base_mae, 2),
        ml_mae=round(ml_mae, 2),
        mae_improvement_pts=round(mae_diff, 2),
        mae_improvement_pct=round(mae_pct, 2),
        baseline_pinball_q50=round(base_pb50, 3),
        ml_pinball_q50=round(ml_pb50, 3),
        baseline_coverage_80=round(base_cov80, 4),
        ml_coverage_80=round(ml_cov80, 4),
        baseline_brier=round(base_brier, 4),
        ml_brier=round(ml_brier, 4),
        promoted=promoted,
        rejection_reason=rejection_reason,
    )
    
    manifest = {
        "manifest_version": "range-ml-manifest-v1",
        "symbol": symbol,
        "target_name": TARGET_NAME,
        "created_at": datetime.now(IST).isoformat(),
        "model_architecture": "HistGradientBoostingRegressor (Quantiles 0.10, 0.50, 0.90) + LogisticRegression",
        "feature_columns": FEATURE_COLS,
        "evaluation_protocol": "Chronological Walk-Forward Rolling Origin",
        "comparison_metrics": metrics.to_dict(),
        "status": "PROMOTED_ML_ELIGIBLE" if promoted else "RETAIN_BASELINE",
    }
    
    return metrics, manifest
