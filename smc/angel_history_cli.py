"""Interactive, read-only historical downloader. Secrets never stored."""
from __future__ import annotations
import argparse
import logging
from datetime import datetime
from getpass import getpass
from pathlib import Path
from zoneinfo import ZoneInfo
from .angel_history import HistoryError,download_history,export_csv,load_master,resolve_token

def day(value):
    try: return datetime.strptime(value,"%Y-%m-%d").replace(tzinfo=ZoneInfo("Asia/Kolkata"))
    except ValueError: raise argparse.ArgumentTypeError("date must be YYYY-MM-DD")

def main():
    ap=argparse.ArgumentParser(description="Historical OHLC only (NO orders)")
    ap.add_argument("--symbol",choices=["NIFTY","SENSEX"],required=True)
    ap.add_argument("--interval",choices=["ONE_MINUTE","ONE_HOUR"],required=True)
    ap.add_argument("--from-date",type=day,required=True)
    ap.add_argument("--to-date",type=day,required=True)
    ap.add_argument("--token",help="Verified broker index token")
    ap.add_argument("--master-file",help="Optional official instrument master JSON")
    ap.add_argument("--out",required=True)
    args=ap.parse_args()
    if args.to_date<args.from_date: ap.error("Invalid date range")
    # Silence SDK logs before SmartConnect import: it can log request headers.
    logging.disable(logging.CRITICAL)
    try:
        from logzero import logger
        logger.disabled=True
        from SmartApi import SmartConnect
    except ImportError:
        print("SDK_MISSING: python -m pip install -e \".[angel]\"")
        return
    try:
        token=args.token or resolve_token(load_master(args.master_file),args.symbol)
        key=getpass("SmartAPI API Key (hidden): ").strip()
        client_id=input("Angel One Client ID: ").strip()
        mpin=getpass("Angel One MPIN (hidden): ").strip()
        totp=getpass("Authenticator current 6-digit TOTP (hidden): ").strip()
        api=SmartConnect(api_key=key)
        logged_in=False
        try:
            session=api.generateSession(clientCode=client_id,password=mpin,totp=totp)
            if not isinstance(session,dict) or session.get("status") is not True:
                raise HistoryError("LOGIN_REJECTED")
            logged_in=True
            result=download_history(api,symbol=args.symbol,token=token,
                interval=args.interval,start=args.from_date.replace(hour=9,minute=15),
                end=args.to_date.replace(hour=15,minute=30))
            export_csv(result,args.out)
            print(f"SUCCESS: {len(result.candles)} candles from {result.requests} requests")
            print(f"Saved CSV: {Path(args.out)}")
            print("1M timestamps=CLOSE, 1H timestamps=START; index data only")
        finally:
            if logged_in:
                try: api.terminateSession(client_id)
                except Exception: print("LOGOUT_NOT_CONFIRMED")
    except HistoryError as exc: print("FAILED:",exc)
    except Exception: print("FAILED: SDK_OR_NETWORK_ERROR (sensitive details hidden)")

if __name__=="__main__": main()
