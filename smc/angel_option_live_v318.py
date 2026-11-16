"""Read-only Angel FULL option depth and NSE Greeks snapshot.

No quote is backfilled, premium is never derived from the index, and this
does NOT predict option price at index SL/target. BFO/SENSEX Greeks are
UNSUPPORTED by the documented Angel NSE-only endpoint.
"""
from __future__ import annotations
from datetime import datetime, timedelta, timezone
from math import isfinite
from pathlib import Path
import json
import os

from .dual_market_v318 import select_symbol

IST=timezone(timedelta(hours=5,minutes=30))


def parse_expiry(value: str):
    for fmt in ("%d%b%Y","%d%b%y"):
        try:
            return datetime.strptime(value.strip().upper(),fmt).date()
        except ValueError:
            continue
    raise ValueError("UNKNOWN_BROKER_EXPIRY_FORMAT")


def _positive(value) -> float | None:
    try:
        n=float(value)
        return n if isfinite(n) and n>0 else None
    except (TypeError,ValueError):
        return None


def _normalized_strike(raw: str, spot: float) -> float | None:
    value=_positive(raw)
    if value is None or not spot>0:return None
    options=[x for x in (value,value/100) if abs(x-spot)/spot<=0.20]
    return options[0] if len(options)==1 else None


def select_atm_itm(master: list[dict], *, symbol: str,
                   spot: float, as_of: datetime) -> list[dict]:
    symbol=select_symbol(symbol)
    if as_of.tzinfo is None or not _positive(spot):
        raise ValueError("INVALID_SPOT_OR_TIME")
    exchange="NFO" if symbol=="NIFTY" else "BFO"
    today=as_of.astimezone(IST).date()
    contracts=[]
    for item in master:
        if str(item.get("exch_seg","")).upper()!=exchange:
            continue
        if str(item.get("instrumenttype","")).upper()!="OPTIDX":
            continue
        trading=str(item.get("symbol","")).upper()
        if not trading.startswith(symbol) or not trading.endswith(("CE","PE")):
            continue
        token=str(item.get("token","")).strip()
        if not token:continue
        try:expiry=parse_expiry(str(item.get("expiry","")))
        except ValueError:continue
        if expiry<today:continue
        strike=_normalized_strike(str(item.get("strike","")),spot)
        if strike is None:continue
        try:lot=int(item.get("lotsize","0"))
        except (TypeError,ValueError):continue
        if lot<=0:continue
        contracts.append({"exchange":exchange,"trading_symbol":trading,
                          "token":token,"strike":strike,
                          "expiry":expiry.isoformat(),
                          "expiry_broker":str(item["expiry"]).strip().upper(),
                          "lot_size":lot,
                          "side":trading[-2:]})
    if not contracts:return []
    earliest=min(c["expiry"] for c in contracts)
    contracts=[c for c in contracts if c["expiry"]==earliest]
    output=[]
    for side in ("CE","PE"):
        options=[c for c in contracts if c["side"]==side]
        if not options:continue
        strikes=sorted(set(c["strike"] for c in options))
        atm=min(strikes,key=lambda n:(abs(n-spot),n))
        itm=(max((x for x in strikes if x<atm),default=None) if side=="CE"
             else min((x for x in strikes if x>atm),default=None))
        for kind,strike in (("ATM",atm),("ITM",itm)):
            if strike is None:continue
            matching=[c for c in options if c["strike"]==strike]
            if len(matching)!=1:continue
            output.append({**matching[0],"moneyness":kind})
    return output


def _exchange_time(raw) -> datetime | None:
    if not isinstance(raw,str) or not raw.strip():
        return None
    for fmt in ("%d-%b-%Y %H:%M:%S","%d-%b-%Y %H:%M",
                "%Y-%m-%dT%H:%M:%S%z"):
        try:
            dt=datetime.strptime(raw.strip(),fmt)
            return dt if dt.tzinfo else dt.replace(tzinfo=IST)
        except ValueError:continue
    return None


def _quote_row(packet: dict, contract: dict, at: datetime) -> dict | None:
    if (str(packet.get("symbolToken",""))!=contract["token"]
        or packet.get("exchange")!=contract["exchange"]):
        return None
    depth=packet.get("depth") or {}
    bid_entries=depth.get("buy") or []
    ask_entries=depth.get("sell") or []
    if not isinstance(bid_entries,list) or not isinstance(ask_entries,list):
        return None
    if not bid_entries or not ask_entries:
        return None
    bid=_positive(bid_entries[0].get("price"))
    ask=_positive(ask_entries[0].get("price"))
    if not bid or not ask or bid>ask:return None
    quote_time=_exchange_time(packet.get("exchFeedTime"))
    if quote_time is None:return None
    age=(at-quote_time).total_seconds()
    if not 0<=age<=10:return None
    try:
        bid_size=int(bid_entries[0].get("quantity",0))
        ask_size=int(ask_entries[0].get("quantity",0))
        volume=int(packet.get("tradeVolume",0))
    except (TypeError,ValueError):return None
    if bid_size<=0 or ask_size<=0 or volume<1:return None
    if (ask-bid)/ask>0.03:return None
    return {
        "trading_symbol":contract["trading_symbol"],
        "symbol":contract["trading_symbol"], "side":contract["side"],
        "expiry":contract["expiry"],"strike":contract["strike"],
        "lot_size":contract["lot_size"],"moneyness":contract["moneyness"],
        "bid":bid,"ask":ask,"spread":round(ask-bid,4),
        "bid_qty":bid_size,"ask_qty":ask_size,"volume":volume,
        "quote_at":quote_time.isoformat(),
        "delta":None,"iv":None,"greeks_source":"UNAVAILABLE",
    }


def fetch_option_snapshot(client, master: list[dict], *, symbol: str,
                          spot: float, received_at: datetime) -> dict:
    symbol=select_symbol(symbol)
    if received_at.tzinfo is None:
        raise ValueError("QUOTE_RECEIPT_NEEDS_TIMEZONE")
    base={"symbol":symbol,"at":received_at.isoformat(),
          "status":"UNAVAILABLE","reason":"NO_VERIFIED_OPTION_DEPTH",
          "contracts":[],"research_only":True,"orders_enabled":False,
          "premium_exit_prices_verified":False}
    contracts=select_atm_itm(master,symbol=symbol,spot=spot,as_of=received_at)
    if not contracts:
        return {**base,"reason":"NO_VERIFIED_CURRENT_EXPIRY_CONTRACTS"}
    exchange=contracts[0]["exchange"]
    tokens=[c["token"] for c in contracts]
    try:
        response=client.getMarketData("FULL",{exchange:tokens})
    except Exception:
        return {**base,"reason":"ANGEL_FULL_QUOTES_UNAVAILABLE"}
    if not isinstance(response,dict) or response.get("status") is not True:
        return {**base,"reason":"ANGEL_FULL_QUOTES_REJECTED"}
    data=response.get("data") or {}
    packets=data.get("fetched") or []
    rows=[]
    for contract in contracts:
        matched=[x for x in packets if isinstance(x,dict)
                 and str(x.get("symbolToken",""))==contract["token"]]
        if len(matched)!=1:continue
        item=_quote_row(matched[0],contract,received_at)
        if item:rows.append(item)
    if not rows:
        return {**base,"reason":"NO_FRESH_LIQUID_BID_ASK"}
    status="OBSERVED_OPTION_QUOTES"
    greek_reason="GREEKS_NOT_AVAILABLE"
    if symbol=="NIFTY" and hasattr(client,"optionGreek"):
        expiry=contracts[0]["expiry_broker"]
        try:greeks=client.optionGreek({"name":"NIFTY","expirydate":expiry})
        except Exception:greeks=None
        if isinstance(greeks,dict) and greeks.get("status") is True:
            candidates=greeks.get("data") or []
            for row in rows:
                found=[g for g in candidates if isinstance(g,dict)
                       and str(g.get("optionType","")).upper()==row["side"]
                       and _positive(g.get("strikePrice"))==row["strike"]]
                if len(found)!=1:continue
                try:
                    delta=float(found[0]["delta"])
                    iv=float(found[0]["impliedVolatility"])
                    if not (-1<=delta<=1 and 0<iv<=500
                            and isfinite(delta) and isfinite(iv)):continue
                except (ValueError,TypeError,KeyError):continue
                row.update(delta=delta,iv=iv,greeks_source="ANGEL_NSE_OPTION_GREEKS")
            greek_reason=("NSE_GREEKS_PARTIALLY_OBSERVED" if
                          any(x["delta"] is not None for x in rows)
                          else "NSE_GREEKS_UNAVAILABLE")
    elif symbol=="SENSEX":
        greek_reason="BFO_SENSEX_GREEKS_NOT_SUPPORTED_BY_ANGEL_NSE_ENDPOINT"
    return {**base,"status":status,"reason":greek_reason,"contracts":rows}


def write_option_snapshot(path: str | Path, value: dict) -> None:
    if value.get("research_only") is not True or value.get("orders_enabled") is not False:
        raise ValueError("UNSAFE_OPTION_DATA")
    dest=Path(path);dest.parent.mkdir(parents=True,exist_ok=True)
    temp=dest.with_name(dest.name+f".{os.getpid()}.tmp")
    try:
        temp.write_text(json.dumps(value,allow_nan=False),encoding="utf-8")
        os.replace(temp,dest)
    finally:temp.unlink(missing_ok=True)


def read_option_snapshot(path: str | Path | None, *,
                         symbol: str, max_age: int=20) -> dict:
    default={"symbol":symbol,"status":"UNAVAILABLE",
             "reason":"NO_FRESH_BROKER_OPTION_QUOTES",
             "contracts":[],"research_only":True,"orders_enabled":False}
    if path is None:return default
    try:
        obj=json.loads(Path(path).read_text(encoding="utf-8"))
        if (obj.get("symbol")!=symbol or obj.get("research_only") is not True
            or obj.get("orders_enabled") is not False):return default
        at=datetime.fromisoformat(obj["at"])
        age=(datetime.now(timezone.utc)-at).total_seconds()
        if not 0<=age<=max_age:return default
        return obj
    except (OSError,ValueError,TypeError,KeyError):
        return default
