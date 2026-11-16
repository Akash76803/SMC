"""Regression tests for recovered index sessions and stop postmortems."""
from datetime import datetime, timedelta, timezone
import pytest

from smc.models import Candle
from smc.session_reconciliation_v314 import reconcile_sessions
from smc.angel_historical_research_cli_v313 import analyze_downloaded
from smc.sl_postmortem_v314 import review_stopped_setup
from smc.historical_brackets_v313 import paper_outcome

IST = timezone(timedelta(hours=5, minutes=30))
START = datetime(2026, 11, 5, 9, 16, tzinfo=IST)


def candles(date=START, count=360):
    return [Candle(date+timedelta(minutes=i), 100, 102, 98, 100)
            for i in range(count)]


@pytest.mark.parametrize("terminal", [(15, 29), (15, 30)])
def test_regular_day_plus_one_isolated_terminal_recovered(terminal):
    data = candles()
    data.append(Candle(START.replace(hour=terminal[0], minute=terminal[1]),
                       100, 102, 98, 100))
    regular, audit = reconcile_sessions(data)
    assert len(regular["2026-11-05"]) == 360
    assert audit[0]["status"] == "RECOVERED_ISOLATED_POST_SESSION"
    assert len(audit[0]["quarantined_timestamps"]) == 1
    report = analyze_downloaded(symbol="NIFTY", candles=data)
    assert report["usable_sessions"] == 1
    assert report["recovered_sessions"] == 1
    assert report["usable_candles"] == 360


def test_unknown_extra_terminal_is_not_silently_removed():
    data = candles()
    data.append(Candle(START.replace(hour=15, minute=28),
                       100, 102, 98, 100))
    regular, audit = reconcile_sessions(data)
    assert not regular
    assert audit[0]["status"] == "EXCLUDED"


def test_gap_plus_terminal_stays_excluded():
    data = candles()
    del data[100]
    data.append(Candle(START.replace(hour=15, minute=29),
                       100, 102, 98, 100))
    regular, audit = reconcile_sessions(data)
    assert not regular
    assert audit[0]["status"] == "EXCLUDED"


def test_nonstandard_partial_sunday_rejected():
    sunday = datetime(2026, 11, 8, 14, 21, tzinfo=IST)
    data = candles(sunday, 55)
    data.append(Candle(sunday.replace(hour=15, minute=30), 100, 102, 98, 100))
    regular, audit = reconcile_sessions(data)
    assert regular == {}
    assert audit[0]["status"] == "EXCLUDED"


def test_three_recoverable_days_plus_previous_complete():
    all_bars = []
    for d in (2, 5, 9, 13):
        day = START.replace(day=d)
        all_bars.extend(candles(day))
        if d != 2:
            all_bars.append(Candle(day.replace(hour=15, minute=29),
                                   100, 102, 98, 100))
    report = analyze_downloaded(symbol="NIFTY", candles=all_bars)
    assert report["usable_sessions"] == 4
    assert report["recovered_sessions"] == 3


def test_post_stop_target_later_is_diagnostic_only():
    bars = [
        Candle(START, 100, 101, 99, 100),
        Candle(START + timedelta(minutes=1), 100, 105, 95, 99),
        Candle(START + timedelta(minutes=2), 101, 108, 100, 106),
    ]
    paper = paper_outcome(session=bars, confirm_index=0,
                          direction="BULLISH", stop=98, target=104,
                          min_points=1)
    assert paper["exit_reason"] == "SL_FIRST_OR_SAME_BAR_AMBIGUOUS"
    review = review_stopped_setup(
        session=bars, direction="BULLISH", entry=100, stop=98,
        target=104, exit_at=paper["exit_at"])
    assert review["target_touched_after_exit_at"] == bars[-1].timestamp.isoformat()
    assert review["lookahead_postmortem_only"]
    assert review["does_not_prove_stop_was_too_tight"]


def test_post_stop_no_future_bars_no_target_claim():
    bars = [Candle(START, 100, 101, 99, 100)]
    review = review_stopped_setup(session=bars, direction="BEARISH",
                                 entry=100, stop=101, target=90,
                                 exit_at=bars[0].timestamp.isoformat())
    assert review["after_sl_bars"] == 0
    assert review["target_touched_after_exit_at"] is None
