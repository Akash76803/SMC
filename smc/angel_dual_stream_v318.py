"""One login, two *read-only* Angel SmartWebSocketV2 index subscriptions.

Separate NIFTY/SENSEX 1m research files and atomic feed status.
All broker credentials stay local; no brokerage order methods are used.
"""
from __future__ import annotations
import argparse
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from threading import Timer, Thread, Event

from .angel_history import load_master, resolve_token, HistoryError
from .angel_local_auth import load_local_env, resolve_login_fields, current_totp, CredentialError
from .angel_secure_ws_v312 import make_secure_websocket
from .angel_stream_v312 import parse_tick, StreamDataError
from .angel_stream_cli_v312 import write_live_status
from .dual_market_v318 import market_paths, SYMBOLS
from .live_research_v312 import LiveResearchEngine
from .angel_option_live_v318 import fetch_option_snapshot, write_option_snapshot
from .option_quote_tape_v319 import append_snapshot


def run_dual_stream(*, ws, tokens: dict[str,str], outputs: dict,
                    statuses: dict[str,str], max_seconds: int) -> dict:
    """Injectable websocket for CI. Individual symbol continuity never mixes."""
    if set(tokens)!=set(SYMBOLS) or not 5<=max_seconds<=14400:
        raise ValueError("INVALID_DUAL_FEED_CONFIG")
    engines={s:LiveResearchEngine(s) for s in SYMBOLS}
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
    def on_data(_ws,packet):
        if stopped or not isinstance(packet,dict):return
        symbol=next((s for s in SYMBOLS if
                     packet.get("exchange_type")==({"NIFTY":1,"SENSEX":3}[s])
                     and str(packet.get("token","")).strip()==tokens[s]),None)
        if not symbol:return
        try:
            tick=parse_tick(packet,symbol=symbol,token=tokens[s],
                            received_at=datetime.now(timezone.utc))
            counts[symbol]["ticks"]+=1
            event=engines[symbol].on_tick(tick)
            if event:
                counts[symbol]["candles"]+=1
                outputs[symbol].write(json.dumps(event,separators=(",",":"))+"\n")
                outputs[symbol].flush()
        except (StreamDataError,ValueError):
            counts[symbol]["errors"]+=1
            engines[symbol].on_disconnect()
            write_live_status(statuses[symbol],"ERROR","INVALID_OR_GAPPED_FEED")
        except Exception:
            counts[symbol]["errors"]+=1
            engines[symbol].on_disconnect()
            write_live_status(statuses[symbol],"ERROR","LIVE_ANALYSIS_FAILED")
    def on_error(_ws,_error):
        for s in SYMBOLS:
            engines[s].on_disconnect()
            write_live_status(statuses[s],"DISCONNECTED","BROKER_WEBSOCKET_ERROR")
    def on_close(_ws):
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
    p.add_argument("--seconds",type=int,default=14400)
    p.add_argument("--nifty-token")
    p.add_argument("--sensex-token")
    p.add_argument("--master-file")
    p.add_argument("--env-file")
    p.add_argument("--option-refresh-seconds", type=int, default=15)
    a=p.parse_args()
    if not 5<=a.seconds<=14400:
        p.error("INVALID_STREAM_DURATION")
    paths={s:market_paths(a.root,s) for s in SYMBOLS}
    def state(status,reason):
        for s in SYMBOLS:
            write_live_status(str(paths[s]["status"]),status,reason)
    state("AUTHENTICATION_REQUIRED","ENTER_TOTP_IN_BROKER_CONSOLE")
    try:
        tokens={
            "NIFTY":a.nifty_token or resolve_token(load_master(a.master_file),"NIFTY"),
            "SENSEX":a.sensex_token or resolve_token(load_master(a.master_file),"SENSEX"),
        }
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
        key,client_id,pin=resolve_login_fields(load_local_env(a.env_file))
        otp=current_totp()
        api=SmartConnect(api_key=key)
        try:session=api.generateSession(clientCode=client_id,password=pin,totp=otp)
        except Exception:
            raise CredentialError("BROKER_LOGIN_FAILED") from None
        if not isinstance(session,dict) or session.get("status") is not True:
            raise CredentialError("BROKER_LOGIN_REJECTED")
        logged_in=True
        jwt=(session.get("data") or {}).get("jwtToken")
        feed=api.getfeedToken()
        if not jwt or not feed:
            raise CredentialError("MISSING_BROKER_FEED_TOKEN")
        state("AUTHENTICATED","BROKER_LOGIN_OK_NO_TICKS_YET")
        ws=make_secure_websocket(jwt,key,client_id,feed)
        # Option snapshots use separately observed market-depth quotes.
        option_stop=Event()
        try:
            master=load_master(a.master_file)
        except (HistoryError,ValueError,OSError):
            master=[]
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
        with paths["NIFTY"]["live"].open("w",encoding="utf-8") as n, \
             paths["SENSEX"]["live"].open("w",encoding="utf-8") as b:
            totals=run_dual_stream(
                ws=ws,tokens=tokens,outputs={"NIFTY":n,"SENSEX":b},
                statuses={s:str(paths[s]["status"]) for s in SYMBOLS},
                max_seconds=a.seconds)
        option_stop.set()
        poller.join(timeout=3)
        state("STREAM_STOPPED","DUAL_STREAM_SESSION_ENDED")
        print("READ_ONLY_FEED_COUNTS: "+json.dumps(totals))
        return 0 if all(totals[s]["ticks"]>0 and totals[s]["errors"]==0
                        for s in SYMBOLS) else 1
    except (KeyboardInterrupt,EOFError):
        state("CANCELLED","TOTP_OR_STREAM_CANCELLED")
        print("DUAL_LIVE_CANCELLED")
        return 130
    except (CredentialError,ValueError):
        state("ERROR","BROKER_LOGIN_OR_FEED_FAILED")
        print("FAILED: BROKER_LOGIN_OR_FEED_FAILED")
        return 1
    except Exception:
        state("ERROR","BROKER_NETWORK_OR_SDK_ERROR")
        print("FAILED: BROKER_NETWORK_OR_SDK_ERROR")
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
