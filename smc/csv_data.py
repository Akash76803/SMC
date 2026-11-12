"""Strict CSV OHLC loader. Timestamps MUST be timezone-aware candle CLOSE times.

CSV columns: timestamp,open,high,low,close,volume (volume optional).
ISO-8601 timestamp with UTC offset (e.g. 2026-01-05T09:16:00+05:30).
Naive timestamps, duplicate times, unclosed candles, and inconsistent OHLC
are rejected rather than silently repaired.
"""
from __future__ import annotations
import csv
from datetime import datetime
from pathlib import Path
from typing import TextIO

from .models import Candle


def read_candles_csv(source: str | Path | TextIO) -> list[Candle]:
    close_source = not hasattr(source, "read")
    f = open(source, "r", newline="", encoding="utf-8-sig") if close_source else source
    candles: list[Candle] = []
    try:
        reader = csv.DictReader(f)
        required = {"timestamp", "open", "high", "low", "close"}
        if reader.fieldnames is None or not required.issubset(set(reader.fieldnames)):
            raise ValueError("CSV requires timestamp,open,high,low,close columns")
        for row_num, row in enumerate(reader, start=2):
            try:
                ts = datetime.fromisoformat(row["timestamp"].strip())
                if ts.tzinfo is None or ts.utcoffset() is None:
                    raise ValueError("timestamp must include UTC offset")
                volume = float(row["volume"]) if row.get("volume") not in (None, "") else 0.0
                c = Candle(ts, *(float(row[name]) for name in ("open","high","low","close")),
                           volume=volume)
            except (ValueError, TypeError, AttributeError, KeyError) as exc:
                raise ValueError(f"invalid CSV row {row_num}: {exc}") from exc
            if candles and c.timestamp <= candles[-1].timestamp:
                raise ValueError(f"CSV rows not strictly increasing at row {row_num}")
            candles.append(c)
    finally:
        if close_source:
            f.close()
    if not candles:
        raise ValueError("CSV contains no candles")
    return candles
