"""Secret-free observed option quote tape for momentum and future paper research.

The stream must consist of broker-normalized snapshots. Historical quote
records are never produced by indexing implied volatility or synthetic OHLC.
"""
from __future__ import annotations
from datetime import datetime, timezone
from pathlib import Path
from .option_momentum_v319 import rank_momentum, MomentumPolicy
import json
import os


def append_snapshot(path: str | Path, snapshot: dict) -> int:
    if snapshot.get("orders_enabled") is not False or snapshot.get("research_only") is not True:
        raise ValueError("UNTRUSTED_OPTION_SNAPSHOT")
    symbol=snapshot.get("symbol")
    if symbol not in ("NIFTY","SENSEX"):
        raise ValueError("INVALID_MARKET")
    rows=[]
    for contract in snapshot.get("contracts", []):
        if not isinstance(contract,dict):
            continue
        if not contract.get("trading_symbol") or contract.get("side") not in ("CE","PE"):
            continue
        rows.append({**{k:contract.get(k) for k in (
            "trading_symbol","expiry","side","strike","moneyness","bid","ask",
            "volume","bid_qty","ask_qty","delta","iv","quote_at","lot_size")},
            "market":symbol,"research_only":True,"orders_enabled":False})
    if not rows:
        return 0
    target=Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    # Single writer process. Every complete JSONL line can be replayed.
    with target.open("a",encoding="utf-8",newline="\n") as output:
        for item in rows:
            output.write(json.dumps(item,allow_nan=False,separators=(",",":"))+"\n")
    return len(rows)


def read_recent(path: str | Path | None, *, symbol: str, now: datetime,
                lookback_seconds: int = 180) -> list[dict]:
    if symbol not in ("NIFTY","SENSEX") or now.tzinfo is None or lookback_seconds<1:
        raise ValueError("INVALID_TAPE_QUERY")
    if path is None:
        return []
    try:
        target=Path(path)
        with target.open("rb") as handle:
            handle.seek(0,os.SEEK_END)
            size=handle.tell()
            handle.seek(max(0,size-1_048_576))
            lines=handle.read().decode("utf-8","replace").splitlines()
    except OSError:
        return []
    latest={}
    for line in lines:
        try:
            row=json.loads(line)
            if not isinstance(row,dict) or row.get("market")!=symbol or row.get("orders_enabled") is not False:
                continue
            when=datetime.fromisoformat(row["quote_at"])
            age=(now-when).total_seconds()
            if not 0<=age<=lookback_seconds:
                continue
            key=(row.get("trading_symbol"),row["quote_at"])
            latest[key]=row
        except (KeyError,ValueError,TypeError):
            continue
    return sorted(latest.values(),key=lambda x:x["quote_at"])


def live_momentum(path: str | Path | None, *, symbol: str, spot: float,
                  now: datetime, policy: MomentumPolicy = MomentumPolicy()) -> dict:
    rows=read_recent(path,symbol=symbol,now=now,
                     lookback_seconds=policy.max_span_seconds)
    return {
        "symbol":symbol,
        "status":"OBSERVED_MOMENTUM_CANDIDATES" if rows else "NO_VERIFIED_OPTION_TAPE",
        "candidates":sorted(
            rank_momentum(rows,symbol=symbol,spot=spot,now=now,side="CE",policy=policy)
            +rank_momentum(rows,symbol=symbol,spot=spot,now=now,side="PE",policy=policy),
            key=lambda r:r["score"],reverse=True)[:12],
        "observed_samples":len(rows),
        "research_only":True,"orders_enabled":False,
    }
