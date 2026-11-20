"""Read-only SmartWebSocketV2 live research CLI.

Interactive local .env/keyring auth; a single websocket subscription; no
order calls. Writes compact research JSONL without tokens or user identity.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from threading import Timer

from .angel_history import INDICES, HistoryError, load_master, resolve_token
from .angel_local_auth import CredentialError, load_local_env, resolve_login_fields, current_totp
from .angel_stream_v312 import parse_tick, StreamDataError
from .live_research_v312 import LiveResearchEngine
from .angel_secure_ws_v312 import make_secure_websocket


def run_live(*, symbol: str, token: str, ws, output, max_seconds: int) -> dict:
    """Pluggable SDK websocket for tests. Websocket is closed on timeout."""
    if max_seconds < 5 or max_seconds > 14400:
        raise ValueError("INVALID_STREAM_DURATION")
    engine = LiveResearchEngine(symbol)
    counts = {"ticks": 0, "candles": 0, "rejected_ticks": 0,
              "errors": 0, "disconnects": 0,
              "orders_enabled": False}
    stopped = False
    def close_safely():
        nonlocal stopped
        if stopped:
            return
        stopped = True
        try:
            ws.close_connection()
        except Exception:
            counts["errors"] += 1

    def on_open(_):
        # Official SDK exchangeType: NSE_CM=1, BSE_CM=3; mode 1 = LTP.
        exchange_type = 1 if symbol == "NIFTY" else 3
        try:
            ws.subscribe("smcV312", 1,
                         [{"exchangeType": exchange_type, "tokens": [token]}])
            print(f"STREAM_SUBSCRIBED: {symbol} | READ_ONLY")
        except Exception:
            counts["errors"] += 1
            engine.on_disconnect()
            close_safely()

    def on_data(_wsapp, packet):
        if stopped:
            return
        try:
            tick = parse_tick(packet, symbol=symbol, token=token,
                              received_at=datetime.now(timezone.utc))
            counts["ticks"] += 1
            event = engine.on_tick(tick)
            if event:
                counts["candles"] += 1
                output.write(json.dumps(event, separators=(",", ":")) + "\n")
                output.flush()
                print(f"{event['last_candle_close_at']} | "
                      f"close={event['last_candle_close']} | "
                      f"{event['status']} | {event['reason']}")
        except (StreamDataError, ValueError):
            counts["rejected_ticks"] += 1
            engine.on_disconnect()
        except Exception:
            counts["errors"] += 1
            engine.on_disconnect()

    def on_error(_wsapp, _error):
        counts["errors"] += 1
        engine.on_disconnect()

    def on_close(_wsapp):
        counts["disconnects"] += 1
        engine.on_disconnect()

    ws.on_open = on_open
    ws.on_data = on_data
    ws.on_error = on_error
    ws.on_close = on_close
    timer = Timer(max_seconds, close_safely)
    timer.daemon = True
    timer.start()
    try:
        ws.connect()
    finally:
        timer.cancel()
        close_safely()
    return counts


def write_live_status(path: str | None, status: str, reason: str) -> None:
    """Atomic, secret-free local process status for dashboard UI."""
    if path is None:
        return
    if status not in ("AUTHENTICATION_REQUIRED", "AUTHENTICATED",
                      "SUBSCRIBING", "STREAM_STOPPED", "DISCONNECTED",
                      "ERROR", "CANCELLED", "SESSION_CLOSED"):
        raise ValueError("INVALID_LIVE_STATE")
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temp = target.with_name(target.name + f".{os.getpid()}.tmp")
    payload = {"status": status, "reason": reason,
               "updated_at": datetime.now(timezone.utc).isoformat(),
               "research_only": True, "orders_enabled": False}
    try:
        temp.write_text(json.dumps(payload), encoding="utf-8")
        os.replace(temp, target)
    finally:
        temp.unlink(missing_ok=True)


def main() -> int:
    p = argparse.ArgumentParser(description="V3.12 Angel WebSocket live SMC research; NO ORDERS")
    p.add_argument("--symbol", choices=("NIFTY", "SENSEX"), required=True)
    p.add_argument("--token", help="Verified index token (optional)")
    p.add_argument("--master-file", help="Official Angel instrument master")
    p.add_argument("--env-file", help="Local .env path")
    p.add_argument("--seconds", type=int, default=180)
    p.add_argument("--out", required=True, help="Local JSONL research observations")
    p.add_argument("--status-file", help="Local secret-free feed state JSON")
    a = p.parse_args()
    if not 5 <= a.seconds <= 14400:
        p.error("--seconds must be between 5 and 14400")

    try:
        token = a.token or resolve_token(load_master(a.master_file), a.symbol)
    except (HistoryError, ValueError):
        p.error("INDEX_TOKEN_MISSING_OR_AMBIGUOUS")
    write_live_status(a.status_file, "AUTHENTICATION_REQUIRED", "ENTER_LOCAL_TOTP_TO_CONNECT")
    logging.disable(logging.CRITICAL)
    try:
        from logzero import logger
        logger.disabled = True
        from SmartApi import SmartConnect
    except ImportError:
        p.error('SDK_MISSING: python -m pip install -e ".[angel]"')
    logged_in = False
    client_id = ""
    try:
        api_key, client_id, pin = resolve_login_fields(load_local_env(a.env_file))
        otp = current_totp()
        write_live_status(a.status_file, "AUTHENTICATION_REQUIRED", "LOCAL_TOTP_RECEIVED_LOGIN_PENDING")
        api = SmartConnect(api_key=api_key)
        try:
            session = api.generateSession(clientCode=client_id, password=pin, totp=otp)
        except Exception:
            raise CredentialError("BROKER_LOGIN_FAILED") from None
        if not isinstance(session, dict) or session.get("status") is not True:
            raise CredentialError("BROKER_LOGIN_REJECTED")
        logged_in = True
        data = session.get("data") or {}
        auth_token = data.get("jwtToken")
        try:
            feed_token = api.getfeedToken()
        except Exception:
            raise CredentialError("BROKER_FEED_TOKEN_FAILED") from None
        if not isinstance(auth_token, str) or not auth_token or not isinstance(feed_token, str) or not feed_token:
            raise CredentialError("BROKER_STREAM_TOKEN_MISSING")
        write_live_status(a.status_file, "AUTHENTICATED", "BROKER_LOGIN_OK_NO_TICKS_YET")
        ws = make_secure_websocket(auth_token, api_key, client_id, feed_token)
        out = Path(a.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        write_live_status(a.status_file, "SUBSCRIBING", "WAITING_FOR_VERIFIED_MARKET_TICKS")
        with out.open("w", encoding="utf-8") as stream:
            counts = run_live(symbol=a.symbol, token=token, ws=ws,
                              output=stream, max_seconds=a.seconds)
        write_live_status(a.status_file, "STREAM_STOPPED", "STREAM_SESSION_ENDED")
        print("STREAM_SUMMARY: " + json.dumps(counts, sort_keys=True))
        print("NO_ORDERS | NO_OPTION_QUOTE_VERIFICATION")
        return 0 if counts["ticks"] > 0 and counts["errors"] == 0 else 1
    except (KeyboardInterrupt, EOFError):
        write_live_status(a.status_file, "CANCELLED", "LOCAL_AUTH_OR_STREAM_INTERRUPTED")
        print("LIVE_STREAM_CANCELLED | DASHBOARD_STAYS_READ_ONLY")
        return 130
    except (CredentialError, ValueError) as exc:
        write_live_status(a.status_file, "ERROR", "AUTHENTICATION_OR_FEED_SETUP_FAILED")
        print("FAILED: " + str(exc))
        return 1
    except Exception:
        write_live_status(a.status_file, "ERROR", "STREAM_SDK_OR_NETWORK_ERROR")
        print("FAILED: STREAM_SDK_OR_NETWORK_ERROR")
        return 1
    finally:
        if logged_in:
            try:
                api.terminateSession(client_id)
            except Exception:
                print("LOGOUT_NOT_CONFIRMED")


if __name__ == "__main__":
    raise SystemExit(main())
