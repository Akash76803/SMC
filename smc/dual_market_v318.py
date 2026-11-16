"""Read-only multi-market source router for a SINGLE localhost UI.

NIFTY and SENSEX are independent: no cross-market fallback, guessing,
stale results passed as live, or artificial bars. Missing history is explicit.
"""
from __future__ import annotations
from pathlib import Path

SYMBOLS = ("NIFTY", "SENSEX")


def select_symbol(raw: str | None) -> str:
    symbol = (raw or "NIFTY").upper().strip()
    if symbol not in SYMBOLS:
        raise ValueError("INVALID_MARKET_SYMBOL")
    return symbol


def market_paths(root: str | Path, symbol: str) -> dict[str, Path]:
    symbol = select_symbol(symbol)
    root = Path(root)
    low = symbol.lower()
    return {
        "csv": root / "data" / f"{low}_angel_historical_raw.csv",
        "report": root / "results" / f"v316_{low}_report.json",
        "live": root / "results" / f"live_{low}.jsonl",
        "status": root / "results" / f"live_{low}_status.json",
        "options": root / "results" / f"live_{low}_options.json",
        "option_tape": root / "results" / f"live_{low}_option_quotes.jsonl",
        "learning": root / "results" / f"strategy_learning_{low}.json",
    }


def unavailable_snapshot(symbol: str, reason: str) -> dict:
    symbol = select_symbol(symbol)
    return {
        "symbol": symbol, "historical_available": False,
        "historical_reason": reason,
        "sessions": [], "observation_count": 0, "ict_complete": 0,
        "index_brackets": 0, "retest_confirmed": 0, "lifecycle_states": {},
        "excluded_count": 0, "quarantined_count": 0,
        "research_only": True, "orders_enabled": False,
    }


def get_historical_snapshots(root: str | Path) -> dict[str, dict]:
    # Import deferred so routing can be tested without any local data.
    from .app_terminal_v316 import build_snapshot
    result = {}
    for symbol in SYMBOLS:
        paths = market_paths(root, symbol)
        try:
            snapshot = build_snapshot(paths["csv"], paths["report"])
            if snapshot["symbol"] != symbol:
                raise ValueError("REPORT_SYMBOL_MISMATCH")
            snapshot["historical_available"] = True
            snapshot["historical_reason"] = None
        except (ValueError, OSError, KeyError, TypeError):
            snapshot = unavailable_snapshot(symbol, "AUDITED_HISTORY_NOT_AVAILABLE")
        result[symbol] = snapshot
    return result


def get_symbol_payload(root: str | Path, symbol: str,
                       *, has_live: bool) -> dict:
    symbol = select_symbol(symbol)
    from .app_terminal_v316 import live_screen_payload
    paths = market_paths(root, symbol)
    if has_live:
        result = live_screen_payload(paths["live"], paths["status"])
    else:
        result = live_screen_payload(None, None)
    result["symbol"] = symbol
    return result
