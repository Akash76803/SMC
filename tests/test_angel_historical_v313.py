"""V3.13 history-to-research and causally honest paper bracket tests."""
from datetime import datetime, timedelta, timezone
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
import json

import pytest

from smc.models import Candle
from smc.historical_brackets_v313 import paper_outcome, analyze_trade_references
from smc.angel_historical_research_cli_v313 import analyze_downloaded, fetch_and_analyze
from smc.angel_history import HistoryError

IST = timezone(timedelta(hours=5, minutes=30))
START = datetime(2026, 11, 2, 9, 16, tzinfo=IST)


def bars(n=360, start=START):
    return [
        Candle(start+timedelta(minutes=i), 100+i*.01,
               101+i*.01, 99+i*.01, 100+i*.01)
        for i in range(n)]


def test_same_bar_stop_target_collision_assumes_stop_first():
    c = [
        Candle(START, 100, 101, 99, 100),
        Candle(START+timedelta(minutes=1), 100, 105, 95, 101),
    ]
    result = paper_outcome(session=c, confirm_index=0, direction="BULLISH",
                           stop=98, target=104, min_points=1)
    assert result["status"] == "HYPOTHETICAL"
    assert result["exit_reason"] == "SL_FIRST_OR_SAME_BAR_AMBIGUOUS"
    assert result["index_points_gross"] == -2


def test_next_open_retests_rr_and_min_points():
    c = [
        Candle(START, 100, 101, 99, 100),
        Candle(START+timedelta(minutes=1), 102, 102.5, 101.5, 102),
    ]
    x = paper_outcome(session=c, confirm_index=0, direction="BULLISH",
                      stop=99, target=104, min_points=1)
    assert x["status"] == "NO_TRADE"
    assert x["reason"] == "NEXT_BAR_OPEN_RISK_OR_ROOM_FAILED"


def test_eod_exit_is_index_points_not_options_pnl():
    c = [
        Candle(START, 100, 101, 99, 100),
        Candle(START+timedelta(minutes=1), 100, 101, 99, 101),
        Candle(START+timedelta(minutes=2), 102, 103, 101, 103),
    ]
    x = paper_outcome(session=c, confirm_index=0, direction="BULLISH",
                      stop=90, target=150, min_points=50)
    assert x["exit_reason"] == "EOD_EXIT"
    assert x["index_points_gross"] == 3
    assert x["index_not_option_pnl"] is True


def test_incomplete_downloaded_session_excluded_without_fabricated_targets():
    report = analyze_downloaded(symbol="NIFTY", candles=bars(80))
    assert report["usable_sessions"] == 0
    assert report["executed_trades"] == 0
    assert report["excluded_sessions"][0]["reason"] == "INCOMPLETE_REGULAR_360_BARS"


def test_valid_360_session_runs_existing_smc_gates_and_never_orders():
    report = analyze_downloaded(symbol="NIFTY", candles=bars())
    assert report["usable_sessions"] == 1
    assert report["usable_candles"] == 360
    assert report["executed_trades"] == 0
    assert report["days"][0]["brackets"]["research_only"]
    assert report["days"][0]["brackets"]["executed_trades"] == 0
    assert json.loads(json.dumps(report)) == report


def test_gap_day_is_excluded():
    data = bars()
    del data[40]
    report = analyze_downloaded(symbol="NIFTY", candles=data)
    assert report["usable_sessions"] == 0
    assert report["excluded_sessions"]


def test_terminal_1530_index_record_dropped_conservatively():
    data = bars()
    data.append(Candle(START.replace(hour=15, minute=30),
                       100, 101, 99, 100))
    report = analyze_downloaded(symbol="NIFTY", candles=data)
    assert report["usable_sessions"] == 1
    assert report["downloaded_candles"] == 361
    assert report["usable_candles"] == 360


def test_paper_report_no_trade_when_no_verified_target():
    session = bars()
    report = {"observations": [{
        "confirmed_at": session[30].timestamp.isoformat(),
        "direction": "BULLISH", "entry_reference": 100,
        "stop_reference": 90, "status": "WAIT", "reason": "NO_TARGET",
        "intraday_mtf": {"alignment": "UNVERIFIED"},
        "evidence_review": {
            "index_targets": {"status": "WAIT", "targets": []},
            "protected_structure": {"status": "PROVISIONAL"},
            "poi": {"status": "UNVERIFIED"},
        },
    }]}
    x = analyze_trade_references(symbol="NIFTY", session=session, report=report)
    assert x["qualified_index_brackets"] == 0
    assert x["observations"][0]["paper_outcome"] is None
    assert x["observations"][0]["broker_order_eligible"] is False


def test_paper_outcome_requires_nearest_liquidity_and_rr():
    session = bars()
    report = {"observations": [{
        "confirmed_at": session[10].timestamp.isoformat(),
        "direction": "BULLISH", "entry_reference": 100,
        "stop_reference": 90, "status": "WAIT", "reason": "POI_PENDING",
        "intraday_mtf": {"alignment": "UNVERIFIED"},
        "evidence_review": {
            "index_targets": {
                "status": "CANDIDATE",
                "targets": [{"name": "T1", "price": 160, "index_points": 60,
                             "index_rr": 6, "feasible": True}]},
            "protected_structure": {"status": "PROVISIONAL"},
            "poi": {"status": "UNVERIFIED"},
        },
    }]}
    x = analyze_trade_references(symbol="NIFTY", session=session, report=report)
    assert x["qualified_index_brackets"] == 1
    assert x["observations"][0]["paper_outcome"]["status"] == "HYPOTHETICAL"
    assert x["executed_trades"] == 0


def test_fetch_and_analyze_uses_historical_method_only(tmp_path):
    # Actual SmartAPI response contract; no network or credentials in CI.
    class FakeAngel:
        def __init__(self):
            self.calls = []
        def getCandleData(self, params):
            self.calls.append(params)
            start = START - timedelta(minutes=1)
            rows = []
            for i, c in enumerate(bars()):
                at = start + timedelta(minutes=i)
                rows.append([at.isoformat(), c.open, c.high, c.low, c.close, 0])
            return {"status": True, "data": rows}
    api = FakeAngel()
    report = fetch_and_analyze(
        client=api, symbol="NIFTY", token="99926000",
        start=START, end=START,
        raw_csv=tmp_path/"raw.csv", report_json=tmp_path/"research.json")
    assert len(api.calls) == 1
    assert api.calls[0]["interval"] == "ONE_MINUTE"
    assert api.calls[0]["exchange"] == "NSE"
    assert report["usable_sessions"] == 1
    assert report["executed_trades"] == 0
    assert (tmp_path/"raw.csv").exists()
    assert (tmp_path/"research.json").exists()

def test_compact_candidates_csv_has_index_references_not_option_pnl(tmp_path):
    from smc.angel_historical_research_cli_v313 import export_brackets_csv
    payload = analyze_downloaded(symbol="NIFTY", candles=bars())
    path = tmp_path / "candidates.csv"
    export_brackets_csv(payload, path)
    text = path.read_text(encoding="utf-8")
    assert "index_stop_reference" in text
    assert "paper_exit_reason" in text
    assert "option_pnl" not in text
