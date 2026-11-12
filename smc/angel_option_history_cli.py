"""NFO option contract historical OHLC only; strictly read-only SmartAPI."""
from __future__ import annotations
import argparse
import logging
from getpass import getpass
from pathlib import Path
from .angel_history import HistoryError,load_master
from .angel_history_cli import day
from .angel_option_history import resolve_option,download_option,export_option_ohlc

def main():
    ap=argparse.ArgumentParser(description="Exact NFO OPTIDX option contract OHLC (NO orders, NOT bid/ask)")
    ap.add_argument("--trading-symbol",required=True,help="Exact broker NFO symbol from current/archived instrument master")
    ap.add_argument("--token",help="Optional verified matching NFO symboltoken")
    ap.add_argument("--master-file",help="Official Angel instrument master JSON; defaults to current online master")
    ap.add_argument("--interval",choices=("ONE_MINUTE","ONE_HOUR"),default="ONE_MINUTE")
    ap.add_argument("--from-date",type=day,required=True)
    ap.add_argument("--to-date",type=day,required=True)
    ap.add_argument("--out",required=True,help="Output OPTION OHLC CSV, NOT quote tape")
    args=ap.parse_args()
    if args.to_date<args.from_date:ap.error("INVALID_DATE_RANGE")
    # Validate instrument identity BEFORE credentials and API requests.
    try:
        identity=resolve_option(load_master(args.master_file),args.trading_symbol,
                                token=args.token)
    except (ValueError,HistoryError) as ex:
        ap.error(str(ex)+"; expired contracts may not exist in current master")
    logging.disable(logging.CRITICAL)
    try:
        from logzero import logger
        logger.disabled=True
        from SmartApi import SmartConnect
    except ImportError:
        ap.error('SDK_MISSING: python -m pip install -e ".[angel]"')
    logged_in=False
    client_id=""
    try:
        api=SmartConnect(api_key=getpass("SmartAPI API Key (hidden): ").strip())
        client_id=input("Angel One Client ID: ").strip()
        mpin=getpass("Angel One MPIN (hidden): ").strip()
        totp=getpass("Authenticator TOTP (hidden): ").strip()
        session=api.generateSession(clientCode=client_id,password=mpin,totp=totp)
        if not isinstance(session,dict) or session.get("status") is not True:
            raise HistoryError("LOGIN_REJECTED")
        logged_in=True
        result=download_option(api,token=identity["token"],interval=args.interval,
               start=args.from_date.replace(hour=9,minute=15),
               end=args.to_date.replace(hour=15,minute=30))
        export_option_ohlc(result,args.out,identity)
        print(f"SUCCESS: {len(result.candles)} option OHLC candles, {result.requests} API requests")
        print(f"Contract: {identity['trading_symbol']} | token: {identity['token']}")
        print(f"Saved: {Path(args.out)}")
        print("IMPORTANT: OPTION OHLC ONLY; NOT BID/ASK; NOT compatible with phase6_cli --quotes")
    except HistoryError as e:
        print("FAILED:",e)
    except Exception:
        print("FAILED: SDK_OR_NETWORK_ERROR (sensitive details hidden)")
    finally:
        if logged_in:
            try:api.terminateSession(client_id)
            except Exception:print("LOGOUT_NOT_CONFIRMED")

if __name__=="__main__":main()
