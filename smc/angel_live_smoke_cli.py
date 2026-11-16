"""Read-only authenticated Angel One live market-data smoke test.

Does not call order/position endpoints. Price observations are not candle
closes and cannot authorize an SMC entry or a paper fill.
"""
from __future__ import annotations

import argparse
import json
import logging
from datetime import datetime, timezone
from getpass import getpass
from math import isfinite
from pathlib import Path

from .angel_history import INDICES, HistoryError, load_master, resolve_token


class LiveQuoteError(RuntimeError):
    """Code-only error messages; never include broker responses or secrets."""


def validate_live_quote(response: object, *, symbol: str, token: str,
                        received_at: datetime) -> dict:
    """Strictly validate requested LTP; never mistake response receipt for feed freshness."""
    if symbol not in INDICES or not str(token).strip():
        raise ValueError("INVALID_LIVE_SYMBOL")
    if received_at.tzinfo is None or received_at.utcoffset() is None:
        raise ValueError("RECEIVED_TIME_REQUIRES_OFFSET")
    if not isinstance(response, dict) or response.get("status") is not True:
        raise LiveQuoteError("MARKET_DATA_REJECTED")
    raw = response.get("data")
    if not isinstance(raw, dict) or not isinstance(raw.get("fetched"), list):
        raise LiveQuoteError("MALFORMED_MARKET_DATA")
    exchange = INDICES[symbol][0]
    matching = [x for x in raw["fetched"]
                if isinstance(x, dict)
                and str(x.get("symbolToken", "")).strip() == str(token).strip()
                and str(x.get("exchange", "")).upper() == exchange]
    if len(matching) != 1:
        raise LiveQuoteError("QUOTE_TOKEN_NOT_FOUND_OR_AMBIGUOUS")
    item = matching[0]
    try:
        value = float(item["ltp"])
    except (ValueError, TypeError, KeyError):
        raise LiveQuoteError("INVALID_LTP") from None
    if not isfinite(value) or value <= 0:
        raise LiveQuoteError("INVALID_LTP")
    # LTP mode does not guarantee an exchange timestamp in each response.
    # Don't manufacture a feed timestamp or label delayed prices as live.
    raw_time = item.get("exchFeedTime")
    feed_time = str(raw_time).strip() if raw_time is not None else None
    if not feed_time:
        feed_time = None
    return {
        "schema_version": "live-smoke-1",
        "symbol": symbol,
        "exchange": exchange,
        "symbol_token": str(token).strip(),
        "ltp": value,
        "exchange_feed_time_raw": feed_time,
        "received_at_utc": received_at.astimezone(timezone.utc).isoformat(),
        "feed_freshness_verified": False,
        "quote_type": "LTP_ONLY",
        "ohlc_history_verified": False,
        "options_quotes_verified": False,
        "smc_trade_ready": False,
        "orders_enabled": False,
        "research_only": True,
    }


def fetch_live_quote(client, *, symbol: str, token: str,
                     received_at: datetime | None = None) -> dict:
    """One REST LTP request only; allows mock client in offline CI."""
    if symbol not in INDICES or not str(token).strip():
        raise ValueError("INVALID_LIVE_SYMBOL")
    try:
        response = client.getMarketData("LTP", {INDICES[symbol][0]: [str(token).strip()]})
    except Exception:
        raise LiveQuoteError("BROKER_LTP_REQUEST_FAILED") from None
    return validate_live_quote(
        response, symbol=symbol, token=token,
        received_at=received_at or datetime.now(timezone.utc))


def main() -> int:
    p = argparse.ArgumentParser(
        description="Read-only Angel SmartAPI LTP smoke test; no trades")
    p.add_argument("--symbol", choices=("NIFTY", "SENSEX"), required=True)
    p.add_argument("--token", help="Verified index symbol token")
    p.add_argument("--master-file", help="Optional official instrument-master JSON")
    p.add_argument("--out", required=True)
    args = p.parse_args()

    try:
        token = args.token or resolve_token(load_master(args.master_file), args.symbol)
    except (HistoryError, ValueError):
        p.error("INDEX_MASTER_TOKEN_UNAVAILABLE_OR_AMBIGUOUS")
    # Suppress SDK logs before importing SmartConnect, since some versions
    # log request headers and access tokens. Never print raw API responses.
    logging.disable(logging.CRITICAL)
    try:
        from logzero import logger
        logger.disabled = True
        from SmartApi import SmartConnect
    except ImportError:
        p.error('SDK_MISSING: .\\.venv\\Scripts\\python.exe -m pip install -e ".[angel]"')

    client_id = ""
    logged_in = False
    try:
        api = SmartConnect(api_key=getpass("SmartAPI Key (hidden): ").strip())
        client_id = input("Angel Client ID (local only): ").strip()
        pin = getpass("Angel MPIN (hidden): ").strip()
        otp = getpass("Current TOTP (hidden): ").strip()
        try:
            session = api.generateSession(
                clientCode=client_id, password=pin, totp=otp)
        except Exception:
            raise LiveQuoteError("BROKER_LOGIN_FAILED") from None
        if not isinstance(session, dict) or session.get("status") is not True:
            raise LiveQuoteError("BROKER_LOGIN_REJECTED")
        logged_in = True
        quote = fetch_live_quote(api, symbol=args.symbol, token=token)
        path = Path(args.out)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(quote, indent=2) + "\n", encoding="utf-8")
        print(f"MARKET_DATA_RESPONSE_VALIDATED: {args.symbol} LTP={quote['ltp']}")
        print("FEED_FRESHNESS_UNVERIFIED | NOT A CLOSED CANDLE | NO ORDERS")
        print(f"Saved: {path}")
        return 0
    except LiveQuoteError as exc:
        print(f"FAILED: {exc}")
        return 1
    except Exception:
        print("FAILED: BROKER_SDK_OR_NETWORK_ERROR")
        return 1
    finally:
        if logged_in:
            try:
                api.terminateSession(client_id)
            except Exception:
                print("LOGOUT_NOT_CONFIRMED")


if __name__ == "__main__":
    raise SystemExit(main())
