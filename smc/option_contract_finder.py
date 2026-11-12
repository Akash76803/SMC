"""Discover exact NFO OPTIDX contracts in an official Angel instrument master.

Does not guess symbol tokens or reconstruct expired contracts. Read only.
Master strike is preserved raw because provider encoding varies by segment.
"""
from __future__ import annotations
import argparse
import json
from .angel_history import HistoryError,load_master

def find_nfo_options(master:list[dict],*,underlying:str="NIFTY",
                     side:str="ALL",expiry:str|None=None,
                     contains:str|None=None,limit:int=20)->list[dict]:
    if underlying not in ("NIFTY","BANKNIFTY","FINNIFTY","MIDCPNIFTY"):
        raise ValueError("SUPPORTED_NFO_UNDERLYING_REQUIRED")
    if side not in ("CE","PE","ALL") or limit<1:
        raise ValueError("INVALID_FILTER")
    matches=[]
    seen=set()
    for x in master:
        if str(x.get("exch_seg","")).strip().upper()!="NFO":continue
        if str(x.get("instrumenttype","")).strip().upper()!="OPTIDX":continue
        symbol=str(x.get("symbol","")).strip().upper()
        token=str(x.get("token","")).strip()
        date=str(x.get("expiry","")).strip().upper()
        if not symbol.startswith(underlying) or not symbol.endswith(("CE","PE")) or not token:continue
        if side!="ALL" and not symbol.endswith(side):continue
        if expiry and date!=expiry.strip().upper():continue
        if contains and contains.strip().upper() not in symbol:continue
        key=(symbol,token)
        if key in seen:continue
        seen.add(key)
        matches.append({"trading_symbol":symbol,"token":token,
                        "expiry":date,"strike_master_raw":str(x.get("strike","")).strip(),
                        "lot_size_master":str(x.get("lotsize","")).strip(),
                        "exchange":"NFO"})
    matches.sort(key=lambda x:(x["expiry"],x["trading_symbol"],x["token"]))
    return matches[:limit]

def main():
    ap=argparse.ArgumentParser(description="Find REAL NFO option symbols/tokens from Angel master; no orders")
    ap.add_argument("--underlying",choices=("NIFTY","BANKNIFTY","FINNIFTY","MIDCPNIFTY"),default="NIFTY")
    ap.add_argument("--side",choices=("CE","PE","ALL"),default="ALL")
    ap.add_argument("--expiry",help="Exact expiry text as displayed in master, e.g. 26NOV2026")
    ap.add_argument("--contains",help="Partial TRADING SYMBOL text, e.g. 25000")
    ap.add_argument("--limit",type=int,default=20)
    ap.add_argument("--master-file",help="Optional archived official master JSON")
    args=ap.parse_args()
    try:
        records=find_nfo_options(load_master(args.master_file),underlying=args.underlying,
                                 side=args.side,expiry=args.expiry,
                                 contains=args.contains,limit=args.limit)
    except (ValueError,HistoryError) as exc:ap.error(str(exc))
    print(json.dumps({"underlying":args.underlying,"count_returned":len(records),
         "contracts":records,
         "note":"Only contracts present in this master are shown. Empty results do not prove historical contract nonexistence; expired contract retrieval may be unavailable."},indent=2))
if __name__=="__main__":
    main()
