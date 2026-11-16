"""Acceptance tests for local integrated terminal and live fail-closed modes."""
import json
from datetime import datetime, timedelta, timezone
from http.server import ThreadingHTTPServer
from threading import Thread
from urllib.request import urlopen
from urllib.error import HTTPError

import pytest

from smc.app_terminal_v316 import _tail_live, build_snapshot, make_handler
from smc.angel_historical_research_cli_v313 import analyze_downloaded

IST = timezone(timedelta(hours=5, minutes=30))
START = datetime(2026, 11, 2, 9, 16, tzinfo=IST)


def fixture_paths(tmp_path):
    from smc.models import Candle
    from smc.angel_history import HistoryResult, export_csv
    candles = [
        Candle(START+timedelta(minutes=i), 100, 102, 98, 100)
        for i in range(360)]
    result = analyze_downloaded(symbol="NIFTY", candles=candles)
    # export using known loader's exact schema
    import csv
    source = tmp_path / "raw.csv"
    with source.open("w", newline="") as out:
        writer=csv.writer(out)
        writer.writerow(["timestamp","open","high","low","close","volume"])
        for c in candles:
            writer.writerow([c.timestamp.isoformat(),c.open,c.high,c.low,c.close,c.volume])
    report = tmp_path / "research.json"
    report.write_text(json.dumps(result))
    return source, report


def test_terminal_loads_checked_sessions_and_evidence(tmp_path):
    csv, report = fixture_paths(tmp_path)
    snapshot = build_snapshot(csv, report)
    assert snapshot["research_only"]
    assert snapshot["orders_enabled"] is False
    assert snapshot["symbol"] == "NIFTY"
    assert snapshot["sessions"][0]["date"] == "2026-11-02"
    assert len(snapshot["sessions"][0]["candles"]) == 360
    assert snapshot["live"]["status"] == "NOT_CONNECTED"


def test_terminal_rejects_non_research_report(tmp_path):
    csv, report = fixture_paths(tmp_path)
    data=json.loads(report.read_text())
    data["orders_enabled"]=True
    report.write_text(json.dumps(data))
    with pytest.raises(ValueError,match="REPORT_NOT_MARKED_RESEARCH_ONLY"):
        build_snapshot(csv,report)


def test_terminal_rejects_report_date_mismatch(tmp_path):
    csv,report=fixture_paths(tmp_path)
    data=json.loads(report.read_text())
    data["days"][0]["date"]="2026-11-03"
    report.write_text(json.dumps(data))
    with pytest.raises(ValueError,match="SESSION_DATES_MISMATCH"):
        build_snapshot(csv,report)


def test_live_status_fails_closed_without_auth_or_bar(tmp_path):
    missing = tmp_path/"missing.jsonl"
    assert _tail_live(missing)["status"]=="NOT_CONNECTED"
    missing.write_text('{"research_only":true,"status":"RESEARCH_ONLY"}\n')
    assert _tail_live(missing)["status"]=="WAIT"


def test_live_status_stale_timestamp_stays_stale(tmp_path):
    stream=tmp_path/"live.jsonl"
    stream.write_text(json.dumps({
        "research_only":True,"last_candle_close_at":"2026-11-02T12:00:00+05:30",
        "stream_quality":{"quality_blocked":False},
        "last_candle_close":25000})+"\n")
    assert _tail_live(stream)["status"]=="STALE"


def test_live_status_continuity_blocks_even_fresh_timestamp(tmp_path):
    stream=tmp_path/"live.jsonl"
    stream.write_text(json.dumps({
        "research_only":True,
        "last_candle_close_at":datetime.now(IST).isoformat(),
        "stream_quality":{"quality_blocked":True},
        "last_candle_close":25000})+"\n")
    assert _tail_live(stream)["status"]=="WAIT"


def test_http_only_gets_local_safe_dashboard(tmp_path):
    csv,report=fixture_paths(tmp_path)
    server=ThreadingHTTPServer(("127.0.0.1",0),
                               make_handler(str(csv),str(report),None))
    thread=Thread(target=server.serve_forever,daemon=True)
    thread.start()
    try:
        base=f"http://127.0.0.1:{server.server_port}"
        with urlopen(base+"/") as response:
            html=response.read().decode()
            assert "SMC / MARKET RESEARCH TERMINAL" in html
            assert "AUTO-ORDERS DISABLED" in html
        with urlopen(base+"/api/snapshot") as response:
            data=json.load(response)
            assert data["orders_enabled"] is False
            assert data["observation_count"]>=0
        with pytest.raises(HTTPError) as err:
            urlopen(base+"/api/place-order")
        assert err.value.code==404
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)

def test_live_structure_warmup_must_remain_wait(tmp_path):
    stream = tmp_path / "feed.jsonl"
    stream.write_text(json.dumps({
        "research_only": True,
        "status": "WAIT",
        "reason": "STRUCTURE_WARMUP",
        "last_candle_close_at": datetime.now(IST).isoformat(),
        "stream_quality": {"quality_blocked": False},
        "last_candle_close": 25000,
    })+"\n")
    status = _tail_live(stream)
    assert status["status"] == "WAIT"
    assert status["reason"] == "STRUCTURE_WARMUP"
