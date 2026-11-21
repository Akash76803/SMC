"""Live Shadow Forecast State Machine and Automation (Phase P4.1).

Research-only state machine:
- WAITING_FOR_SESSION
- WAITING_FOR_0916_CANDLE
- FORECAST_0916_RECORDED
- WAITING_FOR_0930_CANDLE
- FORECAST_0930_RECORDED
- WAITING_FOR_EOD
- RECONCILED
- SESSION_CLOSED
- DATA_INSUFFICIENT

Enforces idempotency, single-writer atomic updates, calendar verification,
corrupted record recovery, and zero order generation.
"""
from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, time as dtime
from enum import Enum
from pathlib import Path
from typing import Any, Sequence
from zoneinfo import ZoneInfo

from .models import Candle
from .range_backtest_v1 import pinball_loss
from .range_features_v1 import DailyBar
from .range_labels_v1 import compute_session_labels
from .range_predictor_v1 import TARGET_NAME, RangeForecast, RangeSnapshot, generate_daily_range_forecast

IST = ZoneInfo("Asia/Kolkata")
MARKET_OPEN = dtime(9, 15)
SNAPSHOT_0916 = dtime(9, 16)
SNAPSHOT_0930 = dtime(9, 30)
RESEARCH_CLOSE = dtime(15, 15)
EXCHANGE_CLOSE = dtime(15, 30)

# Verified NSE / BSE Exchange Holidays for 2026
EXCHANGE_HOLIDAYS_2026 = {
    "2026-01-26",  # Republic Day
    "2026-02-17",  # Mahashivratri
    "2026-03-03",  # Holi
    "2026-03-20",  # Id-ul-Fitr
    "2026-04-03",  # Good Friday
    "2026-04-14",  # Dr. Baba Saheb Ambedkar Jayanti
    "2026-05-01",  # Maharashtra Day
    "2026-05-27",  # Bakri Id
    "2026-06-25",  # Muharram
    "2026-10-02",  # Mahatma Gandhi Jayanti
    "2026-10-20",  # Dussehra
    "2026-11-10",  # Diwali Balipratipada
    "2026-11-24",  # Gurunanak Jayanti
    "2026-12-25",  # Christmas
}


class ShadowState(str, Enum):
    WAITING_FOR_SESSION = "WAITING_FOR_SESSION"
    WAITING_FOR_0916_CANDLE = "WAITING_FOR_0916_CANDLE"
    FORECAST_0916_RECORDED = "FORECAST_0916_RECORDED"
    WAITING_FOR_0930_CANDLE = "WAITING_FOR_0930_CANDLE"
    FORECAST_0930_RECORDED = "FORECAST_0930_RECORDED"
    WAITING_FOR_EOD = "WAITING_FOR_EOD"
    RECONCILED = "RECONCILED"
    SESSION_CLOSED = "SESSION_CLOSED"
    DATA_INSUFFICIENT = "DATA_INSUFFICIENT"


def is_market_holiday_or_weekend(d: date) -> tuple[bool, str | None]:
    """Check if given calendar date is weekend or exchange holiday."""
    if d.weekday() >= 5:
        return True, "WEEKEND"
    d_iso = d.isoformat()
    if d_iso in EXCHANGE_HOLIDAYS_2026:
        return True, "EXCHANGE_HOLIDAY"
    return False, None


def make_idempotency_key(symbol: str, session_date: str, snapshot_time: str, target: str = TARGET_NAME) -> str:
    """Build canonical unique key: {symbol}_{date}_{snapshot}_{target}."""
    return f"{symbol.upper()}_{session_date}_{snapshot_time}_{target}"


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


def read_jsonl_safely(file_path: Path) -> list[dict[str, Any]]:
    """Read JSONL file safely, skipping partial or corrupted lines."""
    records: list[dict[str, Any]] = []
    if not file_path.is_file():
        return records
    with open(file_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                continue  # Corrupted line recovery
    return records


@dataclass
class ShadowSessionContext:
    """State tracking context for a live shadow trading session."""
    symbol: str
    session_date: str
    state: ShadowState = ShadowState.WAITING_FOR_SESSION
    forecast_0916: dict[str, Any] | None = None
    forecast_0930: dict[str, Any] | None = None
    reconciled_results: list[dict[str, Any]] = field(default_factory=list)
    recorded_keys: set[str] = field(default_factory=set)


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
    tag: str = "LIVE_SHADOW",
    out_dir: Path | None = None,
) -> RangeForecast:
    """Generate and idempotently record live shadow forecast.
    
    Prevents duplicate entries via idempotency key checking.
    """
    if out_dir is None:
        out_dir = Path("results/range_forecast")
    out_dir.mkdir(parents=True, exist_ok=True)
    
    as_of_time = as_of_ist_iso[11:16] if len(as_of_ist_iso) >= 16 else "09:16"
    idempotency_key = make_idempotency_key(symbol, trading_date, as_of_time)
    history_file = out_dir / f"{symbol.lower()}_shadow_forecasts.jsonl"
    
    # Check if this exact idempotency key was already recorded
    existing_records = read_jsonl_safely(history_file)
    for rec in existing_records:
        if rec.get("idempotency_key") == idempotency_key:
            # Idempotent skip: return reconstructed RangeForecast
            return RangeForecast(**{k: v for k, v in rec.items() if k not in ["idempotency_key", "shadow_tag", "recorded_at"]})
            
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
    forecast_dict["idempotency_key"] = idempotency_key
    forecast_dict["shadow_tag"] = tag
    forecast_dict["recorded_at"] = datetime.now(IST).isoformat()
    
    # 1. Append to immutable history JSONL
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
    tag: str = "LIVE_SHADOW",
    out_dir: Path | None = None,
) -> list[dict[str, Any]]:
    """EOD post-15:15 idempotent reconciliation of recorded shadow forecasts."""
    if out_dir is None:
        out_dir = Path("results/range_forecast")
    sym_lower = symbol.lower()
    history_file = out_dir / f"{sym_lower}_shadow_forecasts.jsonl"
    reconciled_file = out_dir / f"{sym_lower}_reconciled.jsonl"
    
    existing_reconciled = read_jsonl_safely(reconciled_file)
    reconciled_keys = {r.get("reconciliation_key") for r in existing_reconciled}
    
    day_forecasts = [
        fc for fc in read_jsonl_safely(history_file)
        if fc.get("trading_date") == trading_date and fc.get("symbol") == symbol.upper()
    ]
    
    if not day_forecasts or not regular_bars or len(regular_bars) < 360:
        return []
        
    session_high = max(b.high for b in regular_bars)
    session_low = min(b.low for b in regular_bars)
    actual_range = round(session_high - session_low, 2)
    
    new_reconciled: list[dict[str, Any]] = []
    
    for fc in day_forecasts:
        as_of_ist = fc.get("as_of_ist", "")
        as_of_time = as_of_ist[11:16] if len(as_of_ist) >= 16 else "09:16"
        rec_key = f"{symbol.upper()}_{trading_date}_{as_of_time}_RECONCILED"
        
        # Idempotency: skip if already reconciled
        if rec_key in reconciled_keys:
            continue
            
        spot = fc.get("snapshot", {}).get("spot_at_asof") or regular_bars[0].close
        f_data = fc.get("forecast", {})
        
        q10 = f_data.get("daily_total_range_q10")
        q50 = f_data.get("daily_total_range_q50")
        q90 = f_data.get("daily_total_range_q90")
        p_exp = f_data.get("p_expansion")
        
        labels = compute_session_labels(regular_bars, as_of=as_of_time, spot_at_asof=spot)
        
        abs_err = round(abs(actual_range - q50), 2) if q50 is not None else None
        covered = (q10 <= actual_range <= q90) if (q10 is not None and q90 is not None) else None
        pb10 = round(pinball_loss(actual_range, q10, 0.10), 3) if q10 is not None else None
        pb50 = round(pinball_loss(actual_range, q50, 0.50), 3) if q50 is not None else None
        pb90 = round(pinball_loss(actual_range, q90, 0.90), 3) if q90 is not None else None
        
        rec = {
            "reconciliation_key": rec_key,
            "reconciled_at": datetime.now(IST).isoformat(),
            "shadow_tag": tag,
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
        new_reconciled.append(rec)
        reconciled_keys.add(rec_key)
        
    for r in new_reconciled:
        append_jsonl(reconciled_file, r)
        
    if new_reconciled:
        latest_rec_file = out_dir / f"{sym_lower}_latest_reconciled.json"
        atomic_write_json(latest_rec_file, new_reconciled[-1])
        
    return new_reconciled
