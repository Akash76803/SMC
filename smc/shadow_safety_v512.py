"""SMC Phase 5.1.2 — Minimal Safety Fixes for 3 Deferred Items.

DEVELOPMENT FREEZE: No new models, strategies, or UI features.
Only the three non-blocking deferred safety items from Phase 5.1.2 gate decision:
  1. Market holiday detection (NSE/BSE 2026 calendar)
  2. EOD reconciliation log at 15:15 IST
  3. Cross-restart quote deduplication checkpoint

SAFETY (enforced, never overridden):
  ORDERS_ENABLED = False
  RESEARCH_ONLY = True
  RANGE_SMC_CONFLUENCE_ENABLED = False
"""
from __future__ import annotations

import json
import os
import pathlib
import tempfile
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")
ROOT_DIR = Path("E:/Project/SMC")
RESULTS_DIR = ROOT_DIR / "results"

# ── Safety constants (never modified) ─────────────────────────────────────
ORDERS_ENABLED: bool = False
RESEARCH_ONLY: bool = True
RANGE_SMC_CONFLUENCE_ENABLED: bool = False

# ══════════════════════════════════════════════════════════════════════════
# FIX 1 — Market Holiday Detection
# ══════════════════════════════════════════════════════════════════════════

# NSE/BSE 2026 trading holidays (equity segment, NSE India official calendar).
# Source: NSE India website — NSE Holidays 2026 (Equity Segment)
# https://www.nseindia.com/global/content/market_timings_holidays/market_timings_holidays.htm
# Same days apply to BSE equity and F&O segments in 2026.
NSE_HOLIDAYS_2026: frozenset[date] = frozenset({
    date(2026, 1, 26),  # Republic Day
    date(2026, 2, 19),  # Chhatrapati Shivaji Maharaj Jayanti (Maharashtra)
    date(2026, 3, 20),  # Holi
    date(2026, 3, 31),  # Id-ul-Fitr (Ramzan Id)
    date(2026, 4, 2),   # Ram Navami
    date(2026, 4, 3),   # Good Friday
    date(2026, 4, 14),  # Dr. Baba Saheb Ambedkar Jayanti
    date(2026, 5, 1),   # Maharashtra Day / Labour Day
    date(2026, 6, 27),  # Id ul Adha (Bakri Id)
    date(2026, 8, 15),  # Independence Day
    date(2026, 8, 17),  # Parsi New Year (Shahenshahi)
    date(2026, 10, 2),  # Gandhi Jayanti / Mahatma Gandhi
    date(2026, 10, 24), # Dussehra (Vijaya Dashami)
    date(2026, 11, 14), # Diwali - Laxmi Pujan (Muhurat Trading possible)
    date(2026, 11, 16), # Diwali - Balipratipada
    date(2026, 12, 25), # Christmas Day
})

# NOTE: 14-Nov (Diwali) is typically a holiday but NSE may hold a 1-hour
# Muhurat Trading session. Treat as holiday for research purposes.


def is_market_holiday(check_date: date) -> bool:
    """Return True if check_date is a weekend or NSE/BSE declared holiday."""
    if check_date.weekday() >= 5:   # Saturday=5, Sunday=6
        return True
    return check_date in NSE_HOLIDAYS_2026


def is_market_open_today() -> bool:
    """Return True if the market is open today (IST date)."""
    return not is_market_holiday(datetime.now(IST).date())


def next_trading_day(from_date: date | None = None) -> date:
    """Return the next trading day on or after from_date (IST today if None)."""
    d = from_date or datetime.now(IST).date()
    while is_market_holiday(d):
        d += timedelta(days=1)
    return d


def holiday_gate_check(check_date: date | None = None) -> dict[str, Any]:
    """
    Pre-session gate: verify market is open today (or on check_date).
    Returns a dict with 'open', 'date', and 'reason'.
    """
    today = check_date or datetime.now(IST).date()
    open_ = not is_market_holiday(today)
    reason = "MARKET_OPEN" if open_ else (
        "WEEKEND" if today.weekday() >= 5 else "NSE_BSE_DECLARED_HOLIDAY"
    )
    return {
        "date": today.isoformat(),
        "market_open": open_,
        "reason": reason,
        "next_trading_day": next_trading_day(today + timedelta(days=1)).isoformat()
        if not open_ else today.isoformat(),
        "orders_enabled": ORDERS_ENABLED,
        "research_only": RESEARCH_ONLY,
    }


# ══════════════════════════════════════════════════════════════════════════
# FIX 2 — EOD Reconciliation Log at 15:15 IST
# ══════════════════════════════════════════════════════════════════════════

EOD_LOG_DIR = RESULTS_DIR / "eod_reconciliation"


def _count_tape_records(tape_path: Path, session_date: date) -> dict[str, int]:
    """Count records in a quote tape for the given session date."""
    counts: dict[str, int] = {"total": 0, "session_date": 0, "ce": 0, "pe": 0}
    if not tape_path.is_file():
        return counts
    date_str = session_date.isoformat()
    try:
        with tape_path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                    counts["total"] += 1
                    qt = rec.get("quote_at", "")
                    if date_str in qt:
                        counts["session_date"] += 1
                        side = rec.get("side", "")
                        if side == "CE":
                            counts["ce"] += 1
                        elif side == "PE":
                            counts["pe"] += 1
                except json.JSONDecodeError:
                    continue
    except OSError:
        pass
    return counts


def _count_live_events(events_path: Path, session_date: date) -> dict[str, int]:
    """Count SMC signal events for the given session date."""
    counts: dict[str, int] = {"total_events": 0, "signals": 0, "wait": 0}
    if not events_path.is_file():
        return counts
    date_str = session_date.isoformat()
    try:
        with events_path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    ev = json.loads(line)
                    at = ev.get("last_candle_close_at", "") or ""
                    if date_str not in at:
                        continue
                    counts["total_events"] += 1
                    status = ev.get("status", "WAIT")
                    if status not in ("WAIT", "SESSION_CLOSED"):
                        counts["signals"] += 1
                    else:
                        counts["wait"] += 1
                except json.JSONDecodeError:
                    continue
    except OSError:
        pass
    return counts


def write_eod_reconciliation_log(
    session_date: date | None = None,
    out_dir: Path = EOD_LOG_DIR,
) -> Path:
    """
    Write an EOD reconciliation log at 15:15 IST (or on demand).
    Records: session date, quote tape record counts, live event counts,
    paper portfolio state, and safety constraints.
    Returns the path of the written log file.
    """
    if session_date is None:
        session_date = datetime.now(IST).date()

    out_dir.mkdir(parents=True, exist_ok=True)
    log_path = out_dir / f"eod_{session_date.isoformat()}.json"

    record: dict[str, Any] = {
        "log_type": "EOD_RECONCILIATION",
        "generated_at": datetime.now(IST).isoformat(),
        "session_date": session_date.isoformat(),
        "market_holiday": is_market_holiday(session_date),
        "safety_constraints": {
            "orders_enabled": ORDERS_ENABLED,
            "research_only": RESEARCH_ONLY,
            "RANGE_SMC_CONFLUENCE_ENABLED": RANGE_SMC_CONFLUENCE_ENABLED,
        },
        "quote_tapes": {},
        "smc_events": {},
        "paper_portfolios": {},
    }

    for market in ("NIFTY", "SENSEX"):
        sym_lower = market.lower()
        tape_path = RESULTS_DIR / f"live_{sym_lower}_option_quotes.jsonl"
        events_path = RESULTS_DIR / f"live_{sym_lower}.jsonl"
        portfolio_path = RESULTS_DIR / f"paper_portfolio_{sym_lower}.json"

        record["quote_tapes"][market] = _count_tape_records(tape_path, session_date)
        record["quote_tapes"][market]["tape_file_exists"] = tape_path.is_file()
        record["quote_tapes"][market]["tape_path"] = str(tape_path)

        record["smc_events"][market] = _count_live_events(events_path, session_date)
        record["smc_events"][market]["events_file_exists"] = events_path.is_file()

        if portfolio_path.is_file():
            try:
                port = json.loads(portfolio_path.read_text(encoding="utf-8"))
                record["paper_portfolios"][market] = {
                    "exists": True,
                    "open_positions": len(port.get("open_positions", [])),
                    "closed_trades": len(port.get("closed_trades", [])),
                    "research_only": port.get("research_only", True),
                    "orders_enabled": port.get("orders_enabled", False),
                }
            except (json.JSONDecodeError, OSError):
                record["paper_portfolios"][market] = {"exists": True, "readable": False}
        else:
            record["paper_portfolios"][market] = {"exists": False}

    # Atomic write (write to temp then rename)
    tmp_path = log_path.with_suffix(".tmp")
    try:
        tmp_path.write_text(json.dumps(record, indent=2), encoding="utf-8")
        tmp_path.replace(log_path)
    finally:
        if tmp_path.exists():
            try:
                tmp_path.unlink()
            except OSError:
                pass

    return log_path


def should_run_eod_now() -> bool:
    """Return True if current IST time is at or just after 15:15 (EOD window)."""
    now = datetime.now(IST)
    # Fire between 15:15 and 15:20
    return (now.hour == 15 and 15 <= now.minute <= 20)


# ══════════════════════════════════════════════════════════════════════════
# FIX 3 — Cross-Restart Quote Deduplication Checkpoint
# ══════════════════════════════════════════════════════════════════════════

DEDUP_CHECKPOINT_DIR = RESULTS_DIR / "dedup_checkpoints"
_CHECKPOINT_MAX_AGE_HOURS = 25  # older than one session → purge


class PersistentQuoteDeduplicator:
    """
    Session-scoped deduplicator with file-backed checkpoint.
    On startup, loads today's seen-keys from checkpoint so that quotes
    already written before a restart are not written again.
    Key: (trading_symbol, exchange_timestamp_ms)
    """

    def __init__(self, market: str, session_date: date | None = None) -> None:
        if market not in ("NIFTY", "SENSEX"):
            raise ValueError(f"Invalid market: {market}")
        self._market = market
        self._session_date = session_date or datetime.now(IST).date()
        self._checkpoint_path = (
            DEDUP_CHECKPOINT_DIR
            / f"dedup_{market.lower()}_{self._session_date.isoformat()}.jsonl"
        )
        self._seen: set[str] = set()   # JSON-encoded (symbol, ts_ms) tuples
        self._new_count: int = 0
        self._load_checkpoint()

    # ── Internal ──────────────────────────────────────────────────────────

    def _key(self, trading_symbol: str, exchange_timestamp_ms: int) -> str:
        return json.dumps([trading_symbol, exchange_timestamp_ms], separators=(",", ":"))

    def _load_checkpoint(self) -> None:
        """Load all previously seen keys from today's checkpoint file."""
        if not self._checkpoint_path.is_file():
            return
        try:
            with self._checkpoint_path.open("r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        self._seen.add(line)
        except OSError:
            pass

    def _flush_new_key(self, key: str) -> None:
        """Append a single new key to the checkpoint file (append-only, safe for crashes)."""
        try:
            self._checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
            with self._checkpoint_path.open("a", encoding="utf-8") as f:
                f.write(key + "\n")
        except OSError:
            pass  # Failure to write checkpoint is non-fatal; dedup is best-effort

    # ── Public API ────────────────────────────────────────────────────────

    def is_duplicate(self, trading_symbol: str, exchange_timestamp_ms: int) -> bool:
        """
        Return True if this (symbol, timestamp_ms) was already seen.
        On first occurrence: persist to checkpoint and return False.
        """
        key = self._key(trading_symbol, exchange_timestamp_ms)
        if key in self._seen:
            return True
        self._seen.add(key)
        self._flush_new_key(key)
        self._new_count += 1
        return False

    def seen_total(self) -> int:
        return len(self._seen)

    def new_this_session(self) -> int:
        return self._new_count

    def checkpoint_path(self) -> Path:
        return self._checkpoint_path

    @staticmethod
    def purge_old_checkpoints(max_age_hours: int = _CHECKPOINT_MAX_AGE_HOURS) -> int:
        """Remove checkpoint files older than max_age_hours. Returns count purged."""
        cutoff = datetime.now(IST).timestamp() - max_age_hours * 3600
        purged = 0
        if not DEDUP_CHECKPOINT_DIR.is_dir():
            return 0
        for f in DEDUP_CHECKPOINT_DIR.glob("dedup_*.jsonl"):
            try:
                if f.stat().st_mtime < cutoff:
                    f.unlink()
                    purged += 1
            except OSError:
                continue
        return purged


# ══════════════════════════════════════════════════════════════════════════
# Combined pre-session gate check
# ══════════════════════════════════════════════════════════════════════════

def run_presession_safety_gate(session_date: date | None = None) -> dict[str, Any]:
    """
    Run all three safety checks before starting a live shadow session.
    Returns a dict with 'gate_pass' (bool) and details for each check.
    """
    today = session_date or datetime.now(IST).date()

    holiday = holiday_gate_check(today)
    dedup_nifty_exists = (
        DEDUP_CHECKPOINT_DIR / f"dedup_nifty_{today.isoformat()}.jsonl"
    ).is_file()
    dedup_sensex_exists = (
        DEDUP_CHECKPOINT_DIR / f"dedup_sensex_{today.isoformat()}.jsonl"
    ).is_file()
    eod_log_exists = (
        EOD_LOG_DIR / f"eod_{today.isoformat()}.json"
    ).is_file()

    gate = {
        "gate_pass": holiday["market_open"],
        "session_date": today.isoformat(),
        "generated_at": datetime.now(IST).isoformat(),
        "checks": {
            "holiday_gate": holiday,
            "dedup_checkpoint_nifty_ready": dedup_nifty_exists,
            "dedup_checkpoint_sensex_ready": dedup_sensex_exists,
            "prior_eod_log_exists": eod_log_exists,
        },
        "safety_constraints": {
            "orders_enabled": ORDERS_ENABLED,
            "research_only": RESEARCH_ONLY,
            "RANGE_SMC_CONFLUENCE_ENABLED": RANGE_SMC_CONFLUENCE_ENABLED,
        },
        "action": "PROCEED_WITH_SHADOW" if holiday["market_open"] else "SKIP_HOLIDAY",
    }
    return gate


if __name__ == "__main__":
    import sys
    gate = run_presession_safety_gate()
    print(json.dumps(gate, indent=2))
    if not gate["gate_pass"]:
        print(f"\n[GATE] Market closed today ({gate['checks']['holiday_gate']['reason']}). "
              f"Next trading day: {gate['checks']['holiday_gate']['next_trading_day']}")
        sys.exit(1)
    print("\n[GATE] PASS — market open. Ready for supervised forward-shadow observation.")
    sys.exit(0)
