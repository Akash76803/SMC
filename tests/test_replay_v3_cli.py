from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from smc.models import Candle
from smc.replay_v3_cli import prepare_ltf_for_replay

IST = ZoneInfo("Asia/Kolkata")


def bar(day, hour, minute):
    return Candle(datetime(2026, 11, day, hour, minute, tzinfo=IST),
                  100, 101, 99, 100)


def continuous(day=11):
    first = datetime(2026, 11, day, 9, 16, tzinfo=IST)
    return [Candle(first + timedelta(minutes=i), 100, 101, 99, 100)
            for i in range(360)]


def test_default_strict_audit_still_rejects_terminal_record():
    raw = continuous() + [bar(11, 15, 30)]
    with pytest.raises(ValueError, match="TERMINAL_1530_UNCLASSIFIED"):
        prepare_ltf_for_replay(raw)


def test_explicit_flag_removes_only_isolated_1530():
    valid = continuous()
    retained, removed = prepare_ltf_for_replay(
        valid + [bar(11, 15, 30)], drop_isolated_terminal_1530=True)
    assert retained == valid
    assert removed == 1


def test_other_missing_minute_still_blocks_replay():
    valid = continuous()
    raw = valid[:30] + valid[31:] + [bar(11, 15, 30)]
    with pytest.raises(ValueError, match="INTRADAY_GAP"):
        prepare_ltf_for_replay(raw, drop_isolated_terminal_1530=True)


def test_suspect_1530_not_after_1515_is_not_dropped():
    raw = continuous()[:-1] + [bar(11, 15, 30)]
    with pytest.raises(ValueError, match="INTRADAY_GAP"):
        prepare_ltf_for_replay(raw, drop_isolated_terminal_1530=True)


def test_clean_data_unchanged():
    valid = continuous()
    retained, removed = prepare_ltf_for_replay(valid, drop_isolated_terminal_1530=True)
    assert retained == valid and removed == 0
