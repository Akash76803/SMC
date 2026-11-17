"""Bulk Angel One downloader and multi-timeframe aggregator for NIFTY and SENSEX.

Downloads 7-8 months of 1-minute historical data in day-aligned 27-day chunks,
then aggregates into week, daily, 4h, 45m, 30m, 15m, 5min, 1m CSV files.
Features automatic exponential-backoff retries, rate-limit throttling handling,
and batch checkpointing to resume without re-downloading.
"""
from __future__ import annotations

import argparse
import csv
import json
import logging
import os
import sys
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from getpass import getpass
from pathlib import Path
from zoneinfo import ZoneInfo

from .angel_local_auth import CredentialError, load_local_env, read_totp_seed
from .models import Candle

IST = ZoneInfo("Asia/Kolkata")
INDICES = {
    "NIFTY": {"exchange": "NSE", "token": "99926000"},
    "SENSEX": {"exchange": "BSE", "token": "99919000"},
}

TIMEFRAMES_INTRADAY = [
    ("5min", 5),
    ("15m", 15),
    ("30m", 30),
    ("45m", 45),
    ("4h", 240),
]


def _parse_date(s: str) -> date:
    try:
        return datetime.strptime(s.strip(), "%Y-%m-%d").date()
    except ValueError:
        raise argparse.ArgumentTypeError(f"Invalid date '{s}'; expected YYYY-MM-DD")


def generate_batches(start_date: date, end_date: date, chunk_days: int = 27) -> list[tuple[datetime, datetime]]:
    """Generate day-aligned batches so sessions are never split across requests."""
    batches = []
    cur = start_date
    while cur <= end_date:
        chunk_end = min(end_date, cur + timedelta(days=chunk_days))
        start_dt = datetime(cur.year, cur.month, cur.day, 9, 15, tzinfo=IST)
        end_dt = datetime(chunk_end.year, chunk_end.month, chunk_end.day, 15, 30, tzinfo=IST)
        batches.append((start_dt, end_dt))
        cur = chunk_end + timedelta(days=1)
    return batches


def parse_raw_candle(raw: list) -> Candle:
    t = datetime.fromisoformat(str(raw[0]))
    if t.tzinfo is None or t.utcoffset() is None:
        t = t.replace(tzinfo=IST)
    else:
        t = t.astimezone(IST)
    t += timedelta(minutes=1)  # close-time convention
    return Candle(
        timestamp=t,
        open=float(raw[1]),
        high=float(raw[2]),
        low=float(raw[3]),
        close=float(raw[4]),
        volume=float(raw[5]),
        complete=True,
    )


def load_checkpoint(checkpoint_file: Path) -> dict[datetime, Candle]:
    candles: dict[datetime, Candle] = {}
    if not checkpoint_file.is_file():
        return candles
    try:
        with checkpoint_file.open("r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for r in reader:
                ts = datetime.fromisoformat(r["timestamp"])
                candles[ts] = Candle(
                    timestamp=ts,
                    open=float(r["open"]),
                    high=float(r["high"]),
                    low=float(r["low"]),
                    close=float(r["close"]),
                    volume=float(r["volume"]),
                    complete=True,
                )
    except Exception:
        pass
    return candles


def append_checkpoint(checkpoint_file: Path, new_candles: list[Candle]) -> None:
    checkpoint_file.parent.mkdir(parents=True, exist_ok=True)
    write_header = not checkpoint_file.exists() or checkpoint_file.stat().st_size == 0
    with checkpoint_file.open("a", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        if write_header:
            writer.writerow(["timestamp", "open", "high", "low", "close", "volume"])
        for c in new_candles:
            writer.writerow([c.timestamp.isoformat(), c.open, c.high, c.low, c.close, c.volume])


def download_symbol_1m(client, symbol: str, start_date: date, end_date: date,
                       output_dir: Path,
                       pause_seconds: float = 1.2,
                       max_retries: int = 5) -> list[Candle]:
    meta = INDICES[symbol]
    batches = generate_batches(start_date, end_date)
    checkpoint_file = output_dir / f".checkpoint_{symbol.lower()}_1m.csv"

    candles_dict = load_checkpoint(checkpoint_file)
    if candles_dict:
        print(f"[{symbol}] Resumed from existing checkpoint with {len(candles_dict)} bars.")

    print(f"\n[{symbol}] Fetching ~{(end_date - start_date).days} days in {len(batches)} batches...")
    for idx, (a, b) in enumerate(batches, 1):
        # Check if batch is already covered in checkpoint
        batch_covered = any(a <= c_time <= b for c_time in candles_dict)
        if batch_covered:
            # Check how many candles exist in this range
            existing = sum(1 for c_time in candles_dict if a <= c_time <= b)
            if existing >= 500:  # reasonable minimum for a 27-day trading period
                print(f"  [{symbol}] Batch {idx}/{len(batches)}: {a.strftime('%Y-%m-%d')} to {b.strftime('%Y-%m-%d')}... SKIPPED (Already cached: {existing} bars)")
                continue

        params = {
            "exchange": meta["exchange"],
            "symboltoken": meta["token"],
            "interval": "ONE_MINUTE",
            "fromdate": a.strftime("%Y-%m-%d %H:%M"),
            "todate": b.strftime("%Y-%m-%d %H:%M"),
        }
        print(f"  [{symbol}] Batch {idx}/{len(batches)}: {a.strftime('%Y-%m-%d')} to {b.strftime('%Y-%m-%d')}...", end=" ", flush=True)

        resp = None
        success = False
        for attempt in range(1, max_retries + 1):
            try:
                resp = client.getCandleData(params)
                if isinstance(resp, dict) and resp.get("status") is True:
                    success = True
                    break
                else:
                    err = resp.get("message", "API_REJECTED") if isinstance(resp, dict) else "INVALID_RESPONSE"
                    err_code = resp.get("errorcode", "") if isinstance(resp, dict) else ""
                    backoff = attempt * 3
                    print(f"\n    [Retry {attempt}/{max_retries}] API Error ({err_code} {err}). Waiting {backoff}s...", end=" ", flush=True)
                    time.sleep(backoff)
            except Exception as exc:
                exc_name = type(exc).__name__
                backoff = attempt * 3
                print(f"\n    [Retry {attempt}/{max_retries}] Network/SDK {exc_name}. Waiting {backoff}s...", end=" ", flush=True)
                time.sleep(backoff)

        if not success or not isinstance(resp, dict) or resp.get("status") is not True:
            err = resp.get("message", "FAILED_AFTER_RETRIES") if isinstance(resp, dict) else "FAILED_AFTER_RETRIES"
            print(f"FAILED ({err})")
            raise RuntimeError(f"Request failed for batch {idx} after {max_retries} retries: {err}")

        records = resp.get("data") or []
        new_batch_candles = []
        for r in records:
            if len(r) >= 6:
                c = parse_raw_candle(r)
                if c.timestamp not in candles_dict:
                    candles_dict[c.timestamp] = c
                    new_batch_candles.append(c)

        # Save progress immediately
        if new_batch_candles:
            append_checkpoint(checkpoint_file, new_batch_candles)

        print(f"OK (+{len(new_batch_candles)} bars, cumulative={len(candles_dict)})")
        if idx < len(batches) and pause_seconds > 0:
            time.sleep(pause_seconds)

    sorted_candles = [candles_dict[t] for t in sorted(candles_dict)]
    print(f"[{symbol}] Total 1m bars downloaded: {len(sorted_candles)}")
    return sorted_candles


def merge_candles(group: list[Candle]) -> Candle:
    return Candle(
        timestamp=group[-1].timestamp,
        open=group[0].open,
        high=max(c.high for c in group),
        low=min(c.low for c in group),
        close=group[-1].close,
        volume=sum(c.volume for c in group),
        complete=True,
    )


def resample_intraday(candles: list[Candle], interval_minutes: int) -> list[Candle]:
    by_day: dict[date, list[Candle]] = {}
    for c in candles:
        by_day.setdefault(c.timestamp.date(), []).append(c)

    resampled: list[Candle] = []
    for d, day_bars in by_day.items():
        base_time = datetime(d.year, d.month, d.day, 9, 15, tzinfo=IST)
        buckets: dict[int, list[Candle]] = {}
        for c in day_bars:
            candle_start = c.timestamp - timedelta(minutes=1)
            mins = int((candle_start - base_time).total_seconds() // 60)
            if mins < 0:
                mins = 0
            b_idx = mins // interval_minutes
            buckets.setdefault(b_idx, []).append(c)
        for b_idx in sorted(buckets.keys()):
            resampled.append(merge_candles(buckets[b_idx]))
    return resampled


def resample_daily(candles: list[Candle]) -> list[Candle]:
    by_day: dict[date, list[Candle]] = {}
    for c in candles:
        by_day.setdefault(c.timestamp.date(), []).append(c)
    return [merge_candles(by_day[d]) for d in sorted(by_day.keys())]


def resample_weekly(candles: list[Candle]) -> list[Candle]:
    by_week: dict[tuple[int, int], list[Candle]] = {}
    for c in candles:
        iso = c.timestamp.isocalendar()
        by_week.setdefault((iso.year, iso.week), []).append(c)
    return [merge_candles(by_week[k]) for k in sorted(by_week.keys())]


def save_to_csv(candles: list[Candle], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["timestamp", "open", "high", "low", "close", "volume"])
        for c in candles:
            writer.writerow([c.timestamp.isoformat(), c.open, c.high, c.low, c.close, c.volume])


def process_and_save_all_timeframes(candles: list[Candle], symbol: str, output_dirs: list[Path]) -> dict[str, int]:
    sym_lower = symbol.lower()
    counts = {}

    timeframe_datasets: list[tuple[str, list[Candle]]] = [
        ("1m", candles),
    ]

    for name, mins in TIMEFRAMES_INTRADAY:
        res = resample_intraday(candles, mins)
        timeframe_datasets.append((name, res))

    daily = resample_daily(candles)
    timeframe_datasets.append(("daily", daily))

    weekly = resample_weekly(candles)
    timeframe_datasets.append(("week", weekly))

    print(f"\n[{symbol}] Generating & saving all timeframes to disk:")
    for tf_name, bars in timeframe_datasets:
        file_name = f"{sym_lower}_{tf_name}.csv"
        counts[tf_name] = len(bars)
        for out_dir in output_dirs:
            save_to_csv(bars, out_dir / file_name)
        print(f"  -> {file_name:<20} : {len(bars):>6} bars")

    # Clean up checkpoint once finished
    for out_dir in output_dirs:
        cp = out_dir / f".checkpoint_{symbol.lower()}_1m.csv"
        if cp.is_file():
            try:
                cp.unlink()
            except Exception:
                pass

    return counts


def get_totp(arg_totp: str | None) -> str:
    if arg_totp and arg_totp.strip():
        token = arg_totp.strip().replace(" ", "")
        if len(token) == 6 and token.isdecimal():
            return token
        try:
            import pyotp
            return pyotp.TOTP(token).now()
        except Exception:
            raise CredentialError("INVALID_TOTP_ARGUMENT")

    seed = read_totp_seed()
    if seed:
        try:
            import pyotp
            return pyotp.TOTP(seed).now()
        except Exception:
            raise CredentialError("TOTP_SEED_EVAL_FAILED")

    entered = getpass("Enter current 6-digit Angel TOTP: ").strip()
    if len(entered) != 6 or not entered.isdecimal():
        raise CredentialError("INVALID_TOTP_FORMAT")
    return entered


def main() -> int:
    parser = argparse.ArgumentParser(description="Bulk download & resample NIFTY / SENSEX history")
    parser.add_argument("--symbol", choices=["NIFTY", "SENSEX", "BOTH"], default="BOTH",
                        help="Index to download (default: BOTH)")
    parser.add_argument("--months", type=int, default=8,
                        help="Number of past months to download (default: 8)")
    parser.add_argument("--from-date", type=_parse_date,
                        help="Start date YYYY-MM-DD (overrides --months)")
    parser.add_argument("--to-date", type=_parse_date,
                        help="End date YYYY-MM-DD (default: today)")
    parser.add_argument("--totp", help="Current 6-digit TOTP code or TOTP setup secret (optional)")
    parser.add_argument("--output-dir", default="angelfolder",
                        help="Target directory (default: angelfolder)")

    args = parser.parse_args()

    today = date.today()
    end_d = args.to_date or today
    if args.from_date:
        start_d = args.from_date
    else:
        start_d = end_d - timedelta(days=int(args.months * 30.5))

    if start_d >= end_d:
        print("ERROR: Start date must be earlier than end date.")
        return 1

    print("=" * 65)
    print(" SMC | Angel One Bulk Historical Data Downloader (v2)")
    print("=" * 65)
    print(f"Date Range    : {start_d} to {end_d} (~{(end_d - start_d).days} days)")
    print(f"Target Symbol : {args.symbol}")
    print(f"Output Folder : {args.output_dir}")
    print(f"Timeframes    : week, daily, 4h, 45m, 30m, 15m, 5min, 1m")

    env = load_local_env()
    api_key = env.get("ANGEL_API_KEY")
    client_id = env.get("ANGEL_CLIENT_ID")
    mpin = env.get("ANGEL_MPIN")

    if not api_key or not client_id or not mpin:
        print("ERROR: Missing ANGEL_API_KEY, ANGEL_CLIENT_ID, or ANGEL_MPIN in .env")
        return 1

    try:
        totp_code = get_totp(args.totp)
    except Exception as exc:
        print(f"ERROR: Failed to obtain valid TOTP: {exc}")
        return 1

    logging.disable(logging.CRITICAL)
    try:
        from logzero import logger
        logger.disabled = True
        from SmartApi import SmartConnect
    except ImportError:
        print("ERROR: SmartApi SDK missing. Run: python -m pip install -e .")
        return 1

    api = SmartConnect(api_key=api_key)
    logged_in = False
    symbols_to_fetch = ["NIFTY", "SENSEX"] if args.symbol == "BOTH" else [args.symbol]

    target_paths = [Path(args.output_dir), Path("data") / args.output_dir]

    summary_report = {}
    try:
        print("\nLogging into Angel One SmartAPI...", end=" ", flush=True)
        session = api.generateSession(clientCode=client_id, password=mpin, totp=totp_code)
        if not isinstance(session, dict) or session.get("status") is not True:
            err = session.get("message", "LOGIN_REJECTED") if isinstance(session, dict) else "LOGIN_FAILED"
            print(f"FAILED ({err})")
            return 1
        logged_in = True
        print("SUCCESS (Session active)")

        for sym in symbols_to_fetch:
            t0 = time.time()
            candles_1m = download_symbol_1m(
                api, sym, start_d, end_d,
                output_dir=target_paths[0],
                pause_seconds=1.2,
                max_retries=5
            )
            if not candles_1m:
                print(f"[{sym}] WARNING: No candles returned from API.")
                continue
            tf_counts = process_and_save_all_timeframes(candles_1m, sym, target_paths)
            elapsed = time.time() - t0
            summary_report[sym] = {
                "bars_1m": len(candles_1m),
                "timeframes": tf_counts,
                "elapsed_seconds": round(elapsed, 1),
            }

        print("\n" + "=" * 65)
        print(" ALL DOWNLOADS & TIMEFRAME AGGREGATIONS COMPLETED!")
        print("=" * 65)
        for sym, d in summary_report.items():
            print(f"\nSymbol: {sym} ({d['bars_1m']} 1m bars in {d['elapsed_seconds']}s)")
            for tf, count in d["timeframes"].items():
                print(f"  - {sym.lower()}_{tf}.csv : {count} bars")
        print(f"\nFiles saved in:")
        for tp in target_paths:
            print(f"  - {tp.resolve()}")

        return 0

    except Exception as exc:
        print(f"\nEXECUTION FAILED: {type(exc).__name__}: {exc}")
        return 1
    finally:
        if logged_in:
            try:
                api.terminateSession(client_id)
                print("\nAngel One session safely closed.")
            except Exception:
                pass


if __name__ == "__main__":
    sys.exit(main())
