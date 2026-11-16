"""Offline desktop viewer contracts: no GUI required for these tests."""
import json
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from smc.desktop_v3 import load_research_sessions, summary_for_session


def write_csv(path, count=3, date="2026-11-11"):
    start = datetime.fromisoformat(date + "T09:16:00+05:30")
    lines = ["timestamp,open,high,low,close,volume"]
    for i in range(count):
        stamp = (start + timedelta(minutes=i)).isoformat()
        lines.append(f"{stamp},100,105,95,{100+i},1000")
    path.write_text(chr(10).join(lines) + chr(10), encoding="utf-8")


def write_json(directory, day, n=3, *, obs=None, live=False):
    directory.mkdir(parents=True, exist_ok=True)
    payload = {
        "research_only": True, "live_orders_enabled": live,
        "observed_bars": n, "observations": obs or [],
    }
    (directory / ("replay_" + day + ".json")).write_text(
        json.dumps(payload), encoding="utf-8")


def test_viewer_without_replay_is_research_only(tmp_path):
    source = tmp_path / "candles.csv"
    write_csv(source)
    views = load_research_sessions(source, tmp_path / "missing")
    assert len(views) == 1
    assert views[0].date == "2026-11-11"
    report = summary_for_session(views[0])
    assert report["bars"] == 3
    assert report["observations"] == 0
    assert report["high"] == 105
    assert report["research_only"] is True


def test_terminal_causes_count_without_claiming_trades(tmp_path):
    source = tmp_path / "candles.csv"
    write_csv(source)
    write_json(tmp_path, "2026-11-11", obs=[
        {"timestamp": "2026-11-11T09:17:00+05:30",
         "reason": "MSS_CONFIRMED", "terminal_cause": "CHOCH_TIMEOUT"},
        {"timestamp": "2026-11-11T09:18:00+05:30",
         "reason": "INDEX_TARGET_TOO_SMALL",
         "diagnostics": {"entry_reason": "MISSING_VERIFIED_LIQUIDITY_TARGET"}},
    ])
    report = summary_for_session(load_research_sessions(source, tmp_path)[0])
    assert report["observations"] == 2
    assert report["terminal_causes"] == {
        "CHOCH_TIMEOUT": 1, "MISSING_VERIFIED_LIQUIDITY_TARGET": 1}


def test_reject_replay_from_wrong_day(tmp_path):
    source = tmp_path / "candles.csv"
    write_csv(source)
    write_json(tmp_path, "2026-11-11", obs=[
        {"timestamp": "2026-11-12T09:19:00+05:30"}])
    with pytest.raises(ValueError, match="CROSS_SESSION"):
        load_research_sessions(source, tmp_path)


def test_reject_replay_from_different_candle_count(tmp_path):
    source = tmp_path / "candles.csv"
    write_csv(source)
    write_json(tmp_path, "2026-11-11", n=360)
    with pytest.raises(ValueError, match="LENGTH_MISMATCH"):
        load_research_sessions(source, tmp_path)


def test_reject_non_research_or_live_order_payload(tmp_path):
    source = tmp_path / "candles.csv"
    write_csv(source)
    write_json(tmp_path, "2026-11-11", live=True)
    with pytest.raises(ValueError, match="UNSAFE"):
        load_research_sessions(source, tmp_path)


def test_missing_csv_does_not_fabricate_market_data(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_research_sessions(tmp_path / "missing.csv", tmp_path)
