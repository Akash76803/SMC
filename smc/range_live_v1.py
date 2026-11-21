"""Live Shadow Testing and EOD Outcome Reconciliation for Range Predictor V2.

Phase 4 Deliverable:
- Generates and archives immutable 09:16 and 09:30 live forecasts in JSONL.
- Never overwrites previous forecasts.
- Reconciles realized REGULAR_360_RANGE post-15:15 without lookahead.
- Maintains atomic latest status files.
"""
from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Sequence
from zoneinfo import ZoneInfo

from .models import Candle
from .range_backtest_v1 import pinball_loss
from .range_features_v1 import DailyBar
from .range_labels_v1 import compute_session_labels
from .range_predictor_v1 import TARGET_NAME, RangeForecast, RangeSnapshot, generate_daily_range_forecast

IST = ZoneInfo("Asia/Kolkata")


def atomic_write_json(file_path: Path, data: dict[str, Any]) -> None:
    """Atomically write JSON data to file to prevent partial writes."""
    file_path.parent.mkdir(parents=True, exist_ok=True)
    dir_name = file_path.parent
    with tempfile.NamedTemporaryFile("w", dir=dir_name, delete=False, encoding="utf-8") as tf:
        json.dump(data, tf, indent=2)
        temp_name = tf.name
    os.replace(temp_name, file_path)


def append_jsonl(file_path: Path, record: dict[str, Any]) -> None:
    """Append single JSON record to immutable JSONL log."""
    file_path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(record) + "\n"
    with open(file_path, "a", encoding="utf-8") as f:
        f.write(line)


def record_live_shadow_forecast(
    symbol: str,
    as_of_ist_iso: str,
    trading_date: str,
    spot_at_asof: float,
    prior_completed_days: Sequence[DailyBar],
    intraday_bars: Sequence[Candle],
    vix_observed: float | None = None,
    ce_quote: dict[str, Any] | None = None,
    pe_quote: dict[str, Any] | None = None,
    out_dir: Path | None = None,
) -> RangeForecast:
    """Generate and safely log live shadow forecast.
    
    Appends to {symbol}_shadow_forecasts.jsonl and updates {symbol}_latest.json atomically.
    """
    if out_dir is None:
        out_dir = Path("results/range_forecast")
    out_dir.mkdir(parents=True, exist_ok=True)
    
    snapshot = RangeSnapshot(
        symbol=symbol.upper(),
        trading_date=trading_date,
        as_of_ist=as_of_ist_iso,
        session_definition="REGULAR_360",
        spot_at_asof=spot_at_asof,
        vix_observed=vix_observed,
        ce_quote=ce_quote,
        pe_quote=pe_quote,
        prior_completed_days=list(prior_completed_days),
        intraday_bars=list(intraday_bars),
    )
    
    forecast = generate_daily_range_forecast(snapshot)
    forecast_dict = forecast.to_dict()
    
    # 1. Append to immutable history JSONL
    history_file = out_dir / f"{symbol.lower()}_shadow_forecasts.jsonl"
    append_jsonl(history_file, forecast_dict)
    
    # 2. Atomic latest status file
    latest_file = out_dir / f"{symbol.lower()}_latest.json"
    atomic_write_json(latest_file, forecast_dict)
    
    return forecast


def reconcile_shadow_outcomes(
    symbol: str,
    trading_date: str,
    regular_bars: Sequence[Candle],
    expansion_factor: float = 1.25,
    out_dir: Path | None = None,
) -> list[dict[str, Any]]:
    """EOD post-15:15 reconciliation of recorded shadow forecasts.
    
    Reads forecasts recorded on trading_date, evaluates them against realized session
    bars, and appends reconciliation metrics to {symbol}_reconciled.jsonl.
    Never mutates or overwrites the original forecasts.
    """
    if out_dir is None:
        out_dir = Path("results/range_forecast")
    sym_lower = symbol.lower()
    history_file = out_dir / f"{sym_lower}_shadow_forecasts.jsonl"
    if not history_file.is_file():
        return []
    
    # Read forecasts matching trading_date
    day_forecasts: list[dict[str, Any]] = []
    with open(history_file, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                fc = json.loads(line)
                if fc.get("trading_date") == trading_date and fc.get("symbol") == symbol.upper():
                    day_forecasts.append(fc)
            except json.JSONDecodeError:
                pass
                
    if not day_forecasts or not regular_bars:
        return []
        
    session_high = max(b.high for b in regular_bars)
    session_low = min(b.low for b in regular_bars)
    actual_range = round(session_high - session_low, 2)
    
    reconciled_records: list[dict[str, Any]] = []
    
    for fc in day_forecasts:
        as_of_ist = fc.get("as_of_ist", "")
        as_of_time = as_of_ist[11:16] if len(as_of_ist) >= 16 else "09:16"
        spot = fc.get("snapshot", {}).get("spot_at_asof") or regular_bars[0].close
        f_data = fc.get("forecast", {})
        
        q10 = f_data.get("daily_total_range_q10")
        q50 = f_data.get("daily_total_range_q50")
        q90 = f_data.get("daily_total_range_q90")
        p_exp = f_data.get("p_expansion")
        
        # High/low asymmetry labels strictly for bars after as_of
        labels = compute_session_labels(regular_bars, as_of=as_of_time, spot_at_asof=spot)
        
        abs_err = round(abs(actual_range - q50), 2) if q50 is not None else None
        covered = (q10 <= actual_range <= q90) if (q10 is not None and q90 is not None) else None
        pb10 = round(pinball_loss(actual_range, q10, 0.10), 3) if q10 is not None else None
        pb50 = round(pinball_loss(actual_range, q50, 0.50), 3) if q50 is not None else None
        pb90 = round(pinball_loss(actual_range, q90, 0.90), 3) if q90 is not None else None
        
        rec = {
            "reconciled_at": datetime.now(IST).isoformat(),
            "symbol": symbol.upper(),
            "trading_date": trading_date,
            "as_of_ist": as_of_ist,
            "target_name": TARGET_NAME,
            "spot_at_asof": spot,
            "forecast_q10": q10,
            "forecast_q50": q50,
            "forecast_q90": q90,
            "forecast_p_expansion": p_exp,
            "actual_range": actual_range,
            "actual_session_high": round(session_high, 2),
            "actual_session_low": round(session_low, 2),
            "actual_future_upside": labels.future_upside,
            "actual_future_downside": labels.future_downside,
            "absolute_error_q50": abs_err,
            "covered_in_interval": covered,
            "pinball_q10": pb10,
            "pinball_q50": pb50,
            "pinball_q90": pb90,
            "forecast_snapshot_digest": fc.get("data_quality", {}).get("snapshot_digest"),
        }
        reconciled_records.append(rec)
        
    # Append to immutable reconciled log
    reconciled_file = out_dir / f"{sym_lower}_reconciled.jsonl"
    for r in reconciled_records:
        append_jsonl(reconciled_file, r)
        
    # Update atomic latest reconciled file
    if reconciled_records:
        latest_rec_file = out_dir / f"{sym_lower}_latest_reconciled.json"
        atomic_write_json(latest_rec_file, reconciled_records[-1])
        
    return reconciled_records
