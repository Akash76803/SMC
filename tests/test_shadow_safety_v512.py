"""Tests for SMC shadow_safety_v512 — 3 Deferred Safety Fixes.

No new strategies or ML. Tests only the minimal safety fixes:
  1. Holiday detection
  2. EOD reconciliation log
  3. Cross-restart deduplication checkpoint
"""
from __future__ import annotations

import json
import tempfile
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

IST = ZoneInfo("Asia/Kolkata")


def _ss():
    from smc import shadow_safety_v512 as ss
    return ss


# ══════════════════════════════════════════════════════════════════════════
# Safety Constraints
# ══════════════════════════════════════════════════════════════════════════

class TestSafetyConstraints:
    def test_orders_disabled(self):
        ss = _ss()
        assert ss.ORDERS_ENABLED is False

    def test_research_only(self):
        ss = _ss()
        assert ss.RESEARCH_ONLY is True

    def test_range_smc_disabled(self):
        ss = _ss()
        assert ss.RANGE_SMC_CONFLUENCE_ENABLED is False


# ══════════════════════════════════════════════════════════════════════════
# Fix 1 — Holiday Detection
# ══════════════════════════════════════════════════════════════════════════

class TestHolidayDetection:
    def test_known_holiday_republic_day(self):
        ss = _ss()
        assert ss.is_market_holiday(date(2026, 1, 26)) is True

    def test_known_holiday_holi(self):
        ss = _ss()
        assert ss.is_market_holiday(date(2026, 3, 20)) is True

    def test_known_holiday_diwali(self):
        ss = _ss()
        assert ss.is_market_holiday(date(2026, 11, 14)) is True

    def test_known_holiday_diwali_bali(self):
        ss = _ss()
        assert ss.is_market_holiday(date(2026, 11, 16)) is True

    def test_saturday_is_holiday(self):
        ss = _ss()
        # 2026-11-21 is a Saturday
        assert date(2026, 11, 21).weekday() == 5
        assert ss.is_market_holiday(date(2026, 11, 21)) is True

    def test_sunday_is_holiday(self):
        ss = _ss()
        assert date(2026, 11, 22).weekday() == 6
        assert ss.is_market_holiday(date(2026, 11, 22)) is True

    def test_regular_monday_is_open(self):
        ss = _ss()
        # 2026-11-23 Monday, not a holiday
        assert ss.is_market_holiday(date(2026, 11, 23)) is False

    def test_regular_friday_is_open(self):
        ss = _ss()
        # 2026-11-20 Friday, not a holiday
        assert ss.is_market_holiday(date(2026, 11, 20)) is False

    def test_next_trading_day_skips_weekend(self):
        ss = _ss()
        # Starting from Saturday 21-Nov → next trading day = Monday 23-Nov
        nxt = ss.next_trading_day(date(2026, 11, 21))
        assert nxt == date(2026, 11, 23)

    def test_next_trading_day_skips_holiday(self):
        ss = _ss()
        # 14-Nov is Diwali holiday; next_trading_day(14-Nov) → 17-Nov (Mon)
        # but 15-Nov and 16-Nov - 15 is Sunday, 16 is Diwali Bali holiday
        nxt = ss.next_trading_day(date(2026, 11, 14))
        assert nxt.weekday() < 5
        assert not ss.is_market_holiday(nxt)

    def test_holiday_gate_check_returns_dict(self):
        ss = _ss()
        result = ss.holiday_gate_check()
        assert "market_open" in result
        assert "date" in result
        assert "reason" in result
        assert "next_trading_day" in result
        assert result["orders_enabled"] is False
        assert result["research_only"] is True

    def test_holiday_gate_holiday_day(self):
        ss = _ss()
        # Monkeypatch: test a known holiday directly via is_market_holiday
        assert ss.is_market_holiday(date(2026, 1, 26)) is True

    def test_holidays_set_has_minimum_count(self):
        ss = _ss()
        # NSE should have at least 10 holidays in 2026
        assert len(ss.NSE_HOLIDAYS_2026) >= 10

    def test_all_holidays_in_2026(self):
        ss = _ss()
        for h in ss.NSE_HOLIDAYS_2026:
            assert h.year == 2026, f"Non-2026 holiday found: {h}"

    def test_christmas_is_holiday(self):
        ss = _ss()
        assert ss.is_market_holiday(date(2026, 12, 25)) is True


# ══════════════════════════════════════════════════════════════════════════
# Fix 2 — EOD Reconciliation Log
# ══════════════════════════════════════════════════════════════════════════

class TestEODReconciliationLog:
    def test_write_eod_log_creates_file(self, tmp_path):
        ss = _ss()
        log_path = ss.write_eod_reconciliation_log(
            session_date=date(2026, 11, 20),
            out_dir=tmp_path,
        )
        assert log_path.exists()
        assert log_path.suffix == ".json"

    def test_eod_log_valid_json(self, tmp_path):
        ss = _ss()
        log_path = ss.write_eod_reconciliation_log(
            session_date=date(2026, 11, 20),
            out_dir=tmp_path,
        )
        content = json.loads(log_path.read_text(encoding="utf-8"))
        assert content["log_type"] == "EOD_RECONCILIATION"
        assert content["session_date"] == "2026-11-20"
        assert "generated_at" in content

    def test_eod_log_safety_constraints(self, tmp_path):
        ss = _ss()
        log_path = ss.write_eod_reconciliation_log(
            session_date=date(2026, 11, 20),
            out_dir=tmp_path,
        )
        content = json.loads(log_path.read_text(encoding="utf-8"))
        sc = content["safety_constraints"]
        assert sc["orders_enabled"] is False
        assert sc["research_only"] is True
        assert sc["RANGE_SMC_CONFLUENCE_ENABLED"] is False

    def test_eod_log_contains_market_sections(self, tmp_path):
        ss = _ss()
        log_path = ss.write_eod_reconciliation_log(
            session_date=date(2026, 11, 20),
            out_dir=tmp_path,
        )
        content = json.loads(log_path.read_text(encoding="utf-8"))
        assert "NIFTY" in content["quote_tapes"]
        assert "SENSEX" in content["quote_tapes"]
        assert "NIFTY" in content["smc_events"]
        assert "SENSEX" in content["smc_events"]

    def test_eod_log_holiday_flag(self, tmp_path):
        ss = _ss()
        # 14-Nov is a holiday
        log_path = ss.write_eod_reconciliation_log(
            session_date=date(2026, 11, 14),
            out_dir=tmp_path,
        )
        content = json.loads(log_path.read_text(encoding="utf-8"))
        assert content["market_holiday"] is True

    def test_eod_log_non_holiday_flag(self, tmp_path):
        ss = _ss()
        # 20-Nov is a trading day
        log_path = ss.write_eod_reconciliation_log(
            session_date=date(2026, 11, 20),
            out_dir=tmp_path,
        )
        content = json.loads(log_path.read_text(encoding="utf-8"))
        assert content["market_holiday"] is False

    def test_eod_log_idempotent_overwrite(self, tmp_path):
        ss = _ss()
        # Writing twice should overwrite cleanly (not corrupt)
        ss.write_eod_reconciliation_log(session_date=date(2026, 11, 20), out_dir=tmp_path)
        log_path = ss.write_eod_reconciliation_log(session_date=date(2026, 11, 20), out_dir=tmp_path)
        content = json.loads(log_path.read_text(encoding="utf-8"))
        assert content["log_type"] == "EOD_RECONCILIATION"

    def test_eod_log_with_actual_tape_data(self, tmp_path):
        """Test with real tape file if it exists; skip if not."""
        actual_tape = Path("E:/Project/SMC/results/live_nifty_option_quotes.jsonl")
        if not actual_tape.is_file():
            pytest.skip("Live tape file not present")
        ss = _ss()
        log_path = ss.write_eod_reconciliation_log(
            session_date=date(2026, 11, 20),
            out_dir=tmp_path,
        )
        content = json.loads(log_path.read_text(encoding="utf-8"))
        # Should have some records if tape exists
        assert isinstance(content["quote_tapes"]["NIFTY"]["total"], int)


# ══════════════════════════════════════════════════════════════════════════
# Fix 3 — Cross-Restart Deduplication Checkpoint
# ══════════════════════════════════════════════════════════════════════════

class TestPersistentDeduplication:
    def _make_dedup(self, tmp_path: Path, market: str = "NIFTY") -> Any:
        ss = _ss()
        # Patch checkpoint dir to tmp_path
        import smc.shadow_safety_v512 as mod
        original = mod.DEDUP_CHECKPOINT_DIR
        mod.DEDUP_CHECKPOINT_DIR = tmp_path
        dedup = ss.PersistentQuoteDeduplicator(market, session_date=date(2026, 11, 20))
        mod.DEDUP_CHECKPOINT_DIR = original
        return dedup, tmp_path

    def test_first_occurrence_not_duplicate(self, tmp_path):
        ss = _ss()
        import smc.shadow_safety_v512 as mod
        original = mod.DEDUP_CHECKPOINT_DIR
        mod.DEDUP_CHECKPOINT_DIR = tmp_path
        try:
            d = ss.PersistentQuoteDeduplicator("NIFTY", session_date=date(2026, 11, 20))
            assert d.is_duplicate("NIFTY_CE_24000", 1700000000000) is False
        finally:
            mod.DEDUP_CHECKPOINT_DIR = original

    def test_second_occurrence_is_duplicate(self, tmp_path):
        ss = _ss()
        import smc.shadow_safety_v512 as mod
        original = mod.DEDUP_CHECKPOINT_DIR
        mod.DEDUP_CHECKPOINT_DIR = tmp_path
        try:
            d = ss.PersistentQuoteDeduplicator("NIFTY", session_date=date(2026, 11, 20))
            d.is_duplicate("NIFTY_CE_24000", 1700000000000)
            assert d.is_duplicate("NIFTY_CE_24000", 1700000000000) is True
        finally:
            mod.DEDUP_CHECKPOINT_DIR = original

    def test_checkpoint_persists_across_restart(self, tmp_path):
        """Simulate restart: second dedup instance reads checkpoint from first."""
        ss = _ss()
        import smc.shadow_safety_v512 as mod
        original = mod.DEDUP_CHECKPOINT_DIR
        mod.DEDUP_CHECKPOINT_DIR = tmp_path
        try:
            # First "session"
            d1 = ss.PersistentQuoteDeduplicator("NIFTY", session_date=date(2026, 11, 20))
            d1.is_duplicate("NIFTY_CE_24000", 1700000000000)
            d1.is_duplicate("NIFTY_PE_23900", 1700000000001)

            # Second "session" (simulates restart)
            d2 = ss.PersistentQuoteDeduplicator("NIFTY", session_date=date(2026, 11, 20))
            # Same keys should be recognized as duplicates
            assert d2.is_duplicate("NIFTY_CE_24000", 1700000000000) is True
            assert d2.is_duplicate("NIFTY_PE_23900", 1700000000001) is True
            # New key should not be duplicate
            assert d2.is_duplicate("NIFTY_CE_24050", 1700000000002) is False
        finally:
            mod.DEDUP_CHECKPOINT_DIR = original

    def test_different_markets_independent(self, tmp_path):
        ss = _ss()
        import smc.shadow_safety_v512 as mod
        original = mod.DEDUP_CHECKPOINT_DIR
        mod.DEDUP_CHECKPOINT_DIR = tmp_path
        try:
            dn = ss.PersistentQuoteDeduplicator("NIFTY", session_date=date(2026, 11, 20))
            ds = ss.PersistentQuoteDeduplicator("SENSEX", session_date=date(2026, 11, 20))
            dn.is_duplicate("SYM_X", 1000)
            # Same symbol/ts in SENSEX dedup should NOT be duplicate
            assert ds.is_duplicate("SYM_X", 1000) is False
        finally:
            mod.DEDUP_CHECKPOINT_DIR = original

    def test_checkpoint_file_created(self, tmp_path):
        ss = _ss()
        import smc.shadow_safety_v512 as mod
        original = mod.DEDUP_CHECKPOINT_DIR
        mod.DEDUP_CHECKPOINT_DIR = tmp_path
        try:
            d = ss.PersistentQuoteDeduplicator("NIFTY", session_date=date(2026, 11, 20))
            d.is_duplicate("SYM_A", 100)
            assert d.checkpoint_path().is_file()
        finally:
            mod.DEDUP_CHECKPOINT_DIR = original

    def test_invalid_market_raises(self):
        ss = _ss()
        with pytest.raises(ValueError):
            ss.PersistentQuoteDeduplicator("BANKNIFTY", session_date=date(2026, 11, 20))

    def test_purge_old_checkpoints(self, tmp_path):
        ss = _ss()
        import smc.shadow_safety_v512 as mod
        original = mod.DEDUP_CHECKPOINT_DIR
        mod.DEDUP_CHECKPOINT_DIR = tmp_path
        try:
            # Create a fake old checkpoint
            old_file = tmp_path / "dedup_nifty_2026-10-01.jsonl"
            old_file.write_text('["OLD",1000]\n', encoding="utf-8")
            import os, time
            # Set mtime to 30 hours ago
            old_mtime = time.time() - 30 * 3600
            os.utime(old_file, (old_mtime, old_mtime))
            purged = ss.PersistentQuoteDeduplicator.purge_old_checkpoints(max_age_hours=25)
            assert purged >= 1
            assert not old_file.exists()
        finally:
            mod.DEDUP_CHECKPOINT_DIR = original

    def test_seen_total_counts_correctly(self, tmp_path):
        ss = _ss()
        import smc.shadow_safety_v512 as mod
        original = mod.DEDUP_CHECKPOINT_DIR
        mod.DEDUP_CHECKPOINT_DIR = tmp_path
        try:
            d = ss.PersistentQuoteDeduplicator("SENSEX", session_date=date(2026, 11, 20))
            d.is_duplicate("A", 1)
            d.is_duplicate("B", 2)
            d.is_duplicate("A", 1)  # duplicate
            assert d.seen_total() == 2
            assert d.new_this_session() == 2
        finally:
            mod.DEDUP_CHECKPOINT_DIR = original


# ══════════════════════════════════════════════════════════════════════════
# Combined Pre-Session Gate
# ══════════════════════════════════════════════════════════════════════════

class TestPresessionGate:
    def test_gate_returns_dict(self):
        ss = _ss()
        gate = ss.run_presession_safety_gate(session_date=date(2026, 11, 20))
        assert isinstance(gate, dict)
        assert "gate_pass" in gate
        assert "checks" in gate
        assert "action" in gate
        assert "safety_constraints" in gate

    def test_gate_pass_on_trading_day(self):
        ss = _ss()
        gate = ss.run_presession_safety_gate(session_date=date(2026, 11, 20))
        assert gate["gate_pass"] is True
        assert gate["action"] == "PROCEED_WITH_SHADOW"

    def test_gate_fail_on_holiday(self):
        ss = _ss()
        gate = ss.run_presession_safety_gate(session_date=date(2026, 11, 14))
        assert gate["gate_pass"] is False
        assert gate["action"] == "SKIP_HOLIDAY"

    def test_gate_fail_on_saturday(self):
        ss = _ss()
        gate = ss.run_presession_safety_gate(session_date=date(2026, 11, 21))
        assert gate["gate_pass"] is False

    def test_gate_safety_constraints(self):
        ss = _ss()
        gate = ss.run_presession_safety_gate(session_date=date(2026, 11, 20))
        sc = gate["safety_constraints"]
        assert sc["orders_enabled"] is False
        assert sc["research_only"] is True
