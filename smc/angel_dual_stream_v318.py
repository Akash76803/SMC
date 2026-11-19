"""One login, two *read-only* Angel SmartWebSocketV2 index subscriptions.

Separate NIFTY/SENSEX 1m research files and atomic feed status.
All broker credentials stay local; no brokerage order methods are used.

Auto-backfill: on startup, any gap between today's first recorded candle
and the current time is fetched from Angel One Historical API and injected
into the live.jsonl file so the LiveResearchEngine always has gapless context.
"""
from __future__ import annotations
import argparse
import json
import logging
from datetime import datetime, timedelta, timezone, time
from zoneinfo import ZoneInfo
from pathlib import Path
from threading import Timer, Thread, Event

IST = ZoneInfo('Asia/Kolkata')

from .angel_history import load_master, resolve_token, HistoryError, download_history
from .angel_local_auth import load_local_env, resolve_login_fields, current_totp, CredentialError
from .angel_secure_ws_v312 import make_secure_websocket
from .angel_stream_v312 import parse_tick, StreamDataError
from .angel_stream_cli_v312 import write_live_status
from .dual_market_v318 import market_paths, SYMBOLS
from .live_research_v312 import LiveResearchEngine
from .models import Candle
from .angel_option_live_v318 import fetch_option_snapshot, write_option_snapshot
from .option_quote_tape_v319 import append_snapshot

_SESSION_OPEN_H, _SESSION_OPEN_M = 9, 16   # first regular bar closes at 09:16


def _backfill_missing_candles(api, live_path: Path, symbol: str, token: str) -> int:
    """Fetch any intraday candles missing from live_path and insert them.

    Returns the number of candles that were back-filled.
    """
    from zoneinfo import ZoneInfo
    ist = ZoneInfo('Asia/Kolkata')
    today = datetime.now(ist).date()

    # Read all timestamps already recorded for today
    recorded: dict[str, dict] = {}
    if live_path.exists():
        for raw in live_path.read_text(encoding='utf-8', errors='replace').splitlines():
            raw = raw.strip()
            if not raw:
                continue
            try:
                ev = json.loads(raw)
                ts = ev.get('last_candle_close_at', '')
                if ts and str(today) in ts:
                    recorded[ts] = ev
            except (json.JSONDecodeError, ValueError):
                continue

    # Determine fetch window: from session open (09:15) to current minute (minute-aligned)
    now_ist = datetime.now(ist)
    fetch_start = datetime(today.year, today.month, today.day, 9, 15, tzinfo=ist)
    fetch_end = datetime(today.year, today.month, today.day, now_ist.hour, now_ist.minute, tzinfo=ist)
    if fetch_end <= fetch_start:
        return 0  # Market not yet open or too early

    try:
        result = download_history(api, symbol=symbol, token=token,
                                  interval='ONE_MINUTE',
                                  start=fetch_start, end=fetch_end)
    except Exception as exc:
        print(f'[BACKFILL] {symbol}: history fetch failed: {exc}')
        return 0

    # Find candles missing from live.jsonl
    missing_entries: list[tuple[str, str]] = []
    for c in result.candles:
        ts_ist = c.timestamp.astimezone(ist)
        if ts_ist.hour < _SESSION_OPEN_H or (ts_ist.hour == _SESSION_OPEN_H and ts_ist.minute < _SESSION_OPEN_M):
            continue   # skip pre-session
        iso = ts_ist.isoformat()
        if iso in recorded:
            continue   # already present
        synthetic = {
            'symbol': symbol,
            'last_candle_close_at': iso,
            'last_candle_close': c.close,
            'status': 'WAIT',
            'reason': 'HISTORY_BACKFILL',
            'stream_quality': {
                'symbol': symbol, 'completed_candles': 0,
                'gaps': 0, 'quality_blocked': True,
                'orders_enabled': False, 'research_only': True,
            },
            'entry': None, 'stop': None, 'target': None,
            'orders_enabled': False, 'research_only': True,
            'sampled_live_candles': [{'timestamp': iso,
                                      'open': c.open, 'high': c.high,
                                      'low': c.low, 'close': c.close}],
            'live_candle_source': 'ANGEL_HISTORY_BACKFILL',
        }
        missing_entries.append((iso, json.dumps(synthetic, separators=(',', ':'))))
        hm = ts_ist.strftime('%H:%M')
        print(f'[BACKFILL] {symbol} {hm}: O={c.open} H={c.high} L={c.low} C={c.close}')

    if not missing_entries:
        print(f'[BACKFILL] {symbol}: no missing candles — stream is continuous')
        return 0

    # Merge and re-write today's portion of the file in chronological order
    live_path.parent.mkdir(parents=True, exist_ok=True)
    existing_lines = live_path.read_text(encoding='utf-8', errors='replace').splitlines() if live_path.exists() else []
    pre_today = [l for l in existing_lines
                 if str(today) not in json.loads(l).get('last_candle_close_at', '')
                 if l.strip()]
    today_dict: dict[str, str] = {
        json.loads(l).get('last_candle_close_at', ''): l
        for l in existing_lines if l.strip() and str(today) in json.loads(l).get('last_candle_close_at', '')
    }
    for iso, line in missing_entries:
        today_dict[iso] = line
    sorted_today = [v for k, v in sorted(today_dict.items())]
    live_path.write_text('\n'.join(pre_today + sorted_today) + '\n', encoding='utf-8')
    print(f'[BACKFILL] {symbol}: {len(missing_entries)} candles back-filled ✓')
    return len(missing_entries)


def _load_session_candles(live_path: Path | None, max_candles: int = 360) -> list[Candle]:
    """Load previously recorded closed candles from today's session."""
    if not live_path or not live_path.is_file():
        return []
    today = datetime.now(timezone.utc).astimezone().date()
    candles = []
    seen = set()
    try:
        with live_path.open("r", encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    ev = json.loads(line)
                    at_str = ev.get("last_candle_close_at")
                    close_p = ev.get("last_candle_close")
                    if at_str and close_p and at_str not in seen:
                        dt = datetime.fromisoformat(at_str)
                        if dt.date() == today:
                            sampled = ev.get("sampled_live_candles") or []
                            matching = next((c for c in sampled if c.get("timestamp") == at_str), None)
                            if matching:
                                c = Candle(dt, float(matching["open"]), float(matching["high"]),
                                           float(matching["low"]), float(matching["close"]), 0.0)
                            else:
                                c = Candle(dt, float(close_p), float(close_p), float(close_p), float(close_p), 0.0)
                            candles.append(c)
                            seen.add(at_str)
                except (ValueError, TypeError, KeyError):
                    continue
    except OSError:
        pass
    return candles[-max_candles:]


def run_dual_stream(*, ws, tokens: dict[str,str], outputs: dict,
                    statuses: dict[str,str], max_seconds: int) -> dict:
    """Injectable websocket for CI. Individual symbol continuity never mixes."""
    if set(tokens)!=set(SYMBOLS) or not 5<=max_seconds<=28800:
        raise ValueError("INVALID_DUAL_FEED_CONFIG")
    engines={s:LiveResearchEngine(s) for s in SYMBOLS}
    for s in SYMBOLS:
        out_handle = outputs.get(s)
        p = Path(out_handle.name) if hasattr(out_handle, "name") else None
        prior = _load_session_candles(p)
        if prior:
            engines[s].builder.seed_completed(prior)
    counts={s:{"ticks":0,"candles":0,"errors":0} for s in SYMBOLS}
    stopped=False
    def safe_close():
        nonlocal stopped
        if stopped:return
        stopped=True
        try:ws.close_connection()
        except Exception:pass
    def on_open(_):
        try:
            ws.subscribe("smcDualReadOnly",1,[
                {"exchangeType":1,"tokens":[tokens["NIFTY"]]},
                {"exchangeType":3,"tokens":[tokens["SENSEX"]]},
            ])
            for s in SYMBOLS:
                write_live_status(statuses[s],"SUBSCRIBING",
                                  "WAITING_FOR_VERIFIED_MARKET_TICKS")
            print("NIFTY_AND_SENSEX_SUBSCRIBED | NO_ORDERS")
        except Exception:
            for s in SYMBOLS:
                write_live_status(statuses[s],"ERROR","DUAL_SUBSCRIPTION_FAILED")
            safe_close()
    # Tick-level errors that mean the packet is bad but the stream is healthy.
    _SKIP_ERRORS = frozenset({
        "NONMONOTONIC_STREAM_SEQUENCE", "NONMONOTONIC_STREAM_TIME",
        "STALE_WS_TICK", "FUTURE_WS_TICK", "TICK_OUTSIDE_REGULAR_SESSION",
        "UNSUPPORTED_WS_MODE", "WS_WRONG_EXCHANGE", "WS_WRONG_TOKEN",
        "INVALID_WS_PACKET", "INVALID_WS_TICK_FIELDS", "INVALID_WS_PRICE",
        "CANDLE_SYMBOL_MISMATCH", "candles must be ordered",
    })
    def on_data(_ws,packet):
        if stopped or not isinstance(packet,dict):return
        symbol=None
        for s in SYMBOLS:
            ex_type=1 if s=="NIFTY" else 3
            if packet.get("exchange_type")==ex_type and str(packet.get("token","")).strip()==tokens[s]:
                symbol=s
                break
        if not symbol:return
        try:
            tick=parse_tick(packet,symbol=symbol,token=tokens[symbol],
                            received_at=datetime.now(timezone.utc))
            counts[symbol]["ticks"]+=1
            event=engines[symbol].on_tick(tick)
            if event:
                counts[symbol]["candles"]+=1
                outputs[symbol].write(json.dumps(event,separators=(",",":"))+"\n")
                outputs[symbol].flush()
        except (StreamDataError,ValueError) as err:
            err_code=str(err)
            counts[symbol]["errors"]+=1
            if err_code in _SKIP_ERRORS:
                # Recoverable bad tick — reset sequence guard so next good
                # tick is accepted; do NOT kill the stream or set ERROR status.
                engines[symbol].builder.reset_sequence()
                return
            engines[symbol].on_disconnect()
            write_live_status(statuses[symbol],"ERROR",f"FEED_ERROR: {err}")
        except Exception as exc:
            counts[symbol]["errors"]+=1
            engines[symbol].on_disconnect()
            write_live_status(statuses[symbol],"ERROR",f"LIVE_ERROR: {exc}")
    def on_error(*args,**kwargs):
        for s in SYMBOLS:
            engines[s].on_disconnect()
            write_live_status(statuses[s],"DISCONNECTED","BROKER_WEBSOCKET_ERROR")
    def on_close(*args,**kwargs):
        for s in SYMBOLS:
            engines[s].on_disconnect()
            write_live_status(statuses[s],"DISCONNECTED","BROKER_WEBSOCKET_CLOSED")
    ws.on_open=on_open
    ws.on_data=on_data
    ws.on_error=on_error
    ws.on_close=on_close
    timer=Timer(max_seconds,safe_close);timer.daemon=True;timer.start()
    try:ws.connect()
    finally:
        timer.cancel()
        safe_close()
    return counts


def main() -> int:
    p=argparse.ArgumentParser(description="Angel read-only DUAL index live stream")
    p.add_argument("--root",default=".")
    p.add_argument("--seconds",type=int,default=28800)
    p.add_argument("--nifty-token")
    p.add_argument("--sensex-token")
    p.add_argument("--master-file")
    p.add_argument("--env-file")
    p.add_argument("--option-refresh-seconds", type=int, default=15)
    a=p.parse_args()
    if not 5<=a.seconds<=28800:
        p.error("INVALID_STREAM_DURATION")
    paths={s:market_paths(a.root,s) for s in SYMBOLS}
    def state(status,reason):
        for s in SYMBOLS:
            write_live_status(str(paths[s]["status"]),status,reason)
    state("AUTHENTICATION_REQUIRED","ENTER_TOTP_IN_BROKER_CONSOLE")
    print("============================================================")
    print(" SMC ANGEL ONE DUAL STREAM GATEWAY (READ-ONLY)")
    print("============================================================")
    print("[1/3] Loading instrument master...")
    master = []
    try:
        master = load_master(a.master_file)
        tokens={
            "NIFTY":a.nifty_token or resolve_token(master,"NIFTY"),
            "SENSEX":a.sensex_token or resolve_token(master,"SENSEX"),
        }
        print(f"      Tokens resolved: NIFTY={tokens['NIFTY']}, SENSEX={tokens['SENSEX']}")
    except (HistoryError,ValueError):
        state("ERROR","BROKER_INDEX_TOKEN_UNAVAILABLE")
        print("FAILED: INDEX_TOKEN_MISSING_OR_AMBIGUOUS")
        return 1
    if not 10 <= a.option_refresh_seconds <= 120:
        p.error("OPTION_REFRESH_OUT_OF_RANGE")
    logging.disable(logging.CRITICAL)
    try:
        from logzero import logger
        logger.disabled=True
        from SmartApi import SmartConnect
    except ImportError:
        state("ERROR","SMARTAPI_SDK_UNAVAILABLE")
        print("FAILED: SMARTAPI_SDK_UNAVAILABLE")
        return 1
    logged_in=False;client_id="";api=None
    try:
        env_cfg = load_local_env(a.env_file)
        key,client_id,pin=resolve_login_fields(env_cfg)
        print("[2/3] Connecting to Angel One authentication...")
        otp=current_totp(env_values=env_cfg)
        api=SmartConnect(api_key=key)
        try:session=api.generateSession(clientCode=client_id,password=pin,totp=otp)
        except Exception as exc:
            raise CredentialError(f"BROKER_LOGIN_EXCEPTION: {exc}") from None
        if not isinstance(session,dict) or session.get("status") is not True:
            msg = session.get("message") if isinstance(session, dict) else "REJECTED"
            raise CredentialError(f"BROKER_LOGIN_REJECTED: {msg}")
        logged_in=True
        jwt=(session.get("data") or {}).get("jwtToken")
        feed=api.getfeedToken()
        if not jwt or not feed:
            raise CredentialError("MISSING_BROKER_FEED_TOKEN")
        state("AUTHENTICATED","BROKER_LOGIN_OK_NO_TICKS_YET")
        # ── Auto-backfill missing intraday candles before connecting WS ─────
        print("\n[2.5/3] Auto-backfill: checking for missing candles since market open...")
        for i, sym in enumerate(SYMBOLS):
            try:
                if i > 0:
                    import time; time.sleep(1.0)
                _backfill_missing_candles(api, paths[sym]["live"], sym, tokens[sym])
            except Exception as _bf_err:
                print(f"[BACKFILL] {sym}: skipped ({_bf_err})")
        # ────────────────────────────────────────────────────────────────────
        print("\n[3/3] Broker login SUCCESSFUL! Connecting WebSocket stream...")
        print("      Dual stream active. Do NOT close this console window.")
        ws=make_secure_websocket(jwt,key,client_id,feed)
        # Option snapshots use separately observed market-depth quotes.
        option_stop=Event()
        def poll_options():
            from .app_terminal_v316 import _latest_live_event
            while not option_stop.is_set():
                for market in SYMBOLS:
                    live=_latest_live_event(paths[market]["live"])
                    if not isinstance(live,dict):
                        continue
                    try:
                        now=datetime.now(timezone.utc)
                        closed=datetime.fromisoformat(live["last_candle_close_at"])
                        age=(now-closed).total_seconds()
                        valid=(live.get("status")=="RESEARCH_ONLY"
                               and (live.get("stream_quality") or {}).get("quality_blocked") is False
                               and 0<=age<=120)
                        if not valid:
                            continue
                        quote=fetch_option_snapshot(
                            api, master, symbol=market,
                            spot=float(live["last_candle_close"]),
                            received_at=datetime.now(timezone.utc))
                        write_option_snapshot(paths[market]["options"],quote)
                        append_snapshot(paths[market]["option_tape"],quote)
                    except (TypeError,ValueError,OSError):
                        continue
                option_stop.wait(a.option_refresh_seconds)
        poller=Thread(target=poll_options,daemon=True,name="smc-option-poller")
        poller.start()
        for s in SYMBOLS:
            paths[s]["live"].parent.mkdir(parents=True,exist_ok=True)
        with paths["NIFTY"]["live"].open("a",encoding="utf-8") as n, \
             paths["SENSEX"]["live"].open("a",encoding="utf-8") as b:
            elapsed = 0
            start_stream = datetime.now(timezone.utc)
            retry_count = 0
            while not option_stop.is_set() and elapsed < a.seconds:
                now_ist = datetime.now(timezone.utc).astimezone(IST)
                if now_ist.time() >= time(15, 30) and now_ist.time() < time(18, 0):
                    print("[DUAL_STREAM] Market hours ended (15:30 IST). Completing session.")
                    break
                try:
                    remaining = max(10, int(a.seconds - elapsed))
                    totals = run_dual_stream(
                        ws=ws, tokens=tokens, outputs={"NIFTY": n, "SENSEX": b},
                        statuses={s: str(paths[s]["status"]) for s in SYMBOLS},
                        max_seconds=remaining)
                except Exception as stream_err:
                    print(f"[DUAL_STREAM] Stream exception: {stream_err}")

                elapsed = (datetime.now(timezone.utc) - start_stream).total_seconds()
                now_ist = datetime.now(timezone.utc).astimezone(IST)
                if now_ist.time() >= time(15, 30) and now_ist.time() < time(18, 0):
                    break
                if elapsed >= a.seconds:
                    break

                # Automatic reconnect loop during active market hours
                retry_count += 1
                if retry_count > 10:
                    print("[DUAL_STREAM] Exceeded maximum reconnect attempts.")
                    break
                print(f"[DUAL_STREAM] Reconnecting WebSocket in 3 seconds (attempt {retry_count}/10)...")
                state("RECONNECTING", f"RECONNECT_ATTEMPT_{retry_count}")
                import time as _t; _t.sleep(3.0)
                try:
                    ws = make_secure_websocket(jwt, key, client_id, feed)
                except Exception as ws_err:
                    print(f"[DUAL_STREAM] WebSocket recreate failed: {ws_err}")

        option_stop.set()
        poller.join(timeout=3)
        now_ist = datetime.now(timezone.utc).astimezone(IST)
        if now_ist.time() >= time(15, 30):
            state("SESSION_CLOSED", "MARKET_HOURS_ENDED_330PM")
        else:
            state("STREAM_STOPPED", "DUAL_STREAM_SESSION_ENDED")
        # Re-evaluate research only after the observed quote tape is closed
        # or the stream session has finished. Uses the previous day records;
        # no live strategy changes, broker orders or account mutations.
        try:
            from .self_learning_cli_v319 import run_learning
            for market in SYMBOLS:
                report=run_learning(
                    market=market,
                    event_file=paths[market]["live"],
                    quote_file=paths[market]["option_tape"])
                dest=paths[market]["learning"]
                dest.parent.mkdir(parents=True,exist_ok=True)
                dest.write_text(json.dumps(report,indent=2,allow_nan=False)+"\n",
                                encoding="utf-8")
                print(f"{market}_LEARNING: {report['status']} | RESEARCH_ONLY")
        except (OSError,ValueError,TypeError):
            print("LEARNING_REPORT_UNAVAILABLE_NO_PRODUCTION_CHANGE")
        print("READ_ONLY_FEED_COUNTS: "+json.dumps(totals))
        return 0 if all(totals[s]["ticks"]>0 and totals[s]["errors"]==0
                        for s in SYMBOLS) else 1
    except (KeyboardInterrupt,EOFError):
        state("CANCELLED","TOTP_OR_STREAM_CANCELLED")
        print("DUAL_LIVE_CANCELLED")
        return 130
    except (CredentialError,ValueError) as exc:
        state("ERROR",f"LOGIN_FAILED: {exc}")
        print(f"FAILED: BROKER_LOGIN_OR_FEED_FAILED: {exc}")
        try:
            input("\n[ERROR] Login or Feed failed. Press Enter to exit this window...")
        except Exception:
            pass
        return 1
    except Exception as exc:
        state("ERROR",f"BROKER_ERROR: {exc}")
        print(f"FAILED: BROKER_NETWORK_OR_SDK_ERROR: {exc}")
        try:
            input("\n[ERROR] Broker error occurred. Press Enter to exit this window...")
        except Exception:
            pass
        return 1
    finally:
        if "option_stop" in locals():
            option_stop.set()
            try:
                poller.join(timeout=3)
            except (NameError,RuntimeError):
                pass
        if logged_in and api is not None:
            try:api.terminateSession(client_id)
            except Exception:print("LOGOUT_NOT_CONFIRMED")


if __name__=="__main__":
    raise SystemExit(main())
