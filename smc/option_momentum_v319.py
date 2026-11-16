"""Observed-quote OTM momentum ranking for index options (research only).

Rank is based on *past broker bid/ask observations*, not an inferred index
premium or the distance from ATM. No quote history -> no momentum signal.
Only same contract/expiry, same session, verified increasing quote times.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from math import isfinite

@dataclass(frozen=True)
class MomentumPolicy:
    min_samples: int = 3
    min_span_seconds: int = 20
    max_span_seconds: int = 180
    min_bid_return: float = 0.04
    min_volume_growth: int = 1
    max_spread_pct: float = 0.03
    min_bid_qty: int = 1
    min_ask_qty: int = 1
    max_quote_age_seconds: int = 15
    max_otm_steps: int = 8

    def __post_init__(self):
        if (self.min_samples < 2 or self.min_span_seconds < 1
            or self.max_span_seconds < self.min_span_seconds
            or self.min_bid_return <= 0
            or self.min_volume_growth < 0
            or not 0 < self.max_spread_pct < 1
            or min(self.min_bid_qty,self.min_ask_qty) < 1
            or self.max_quote_age_seconds < 1 or self.max_otm_steps < 0):
            raise ValueError("INVALID_MOMENTUM_POLICY")


def _valid_number(value) -> bool:
    return isinstance(value,(float,int)) and not isinstance(value,bool) and isfinite(value)


def rank_momentum(quotes: list[dict], *, symbol: str, spot: float,
                  now: datetime, side: str, policy: MomentumPolicy = MomentumPolicy()) -> list[dict]:
    """All rows must be captured at or before 'now'. Never uses future data."""
    if symbol not in ("NIFTY","SENSEX") or side not in ("CE","PE"):
        raise ValueError("INVALID_OPTION_MARKET")
    if not _valid_number(spot) or spot <= 0 or now.tzinfo is None:
        raise ValueError("INVALID_SPOT_OR_NOW")
    grouped: dict[tuple,list[dict]] = {}
    for row in quotes:
        if row.get("market") != symbol or row.get("side") != side:
            continue
        try:
            at=datetime.fromisoformat(row["quote_at"])
            if at.tzinfo is None or at > now or at.date() != now.date():
                continue
            if (now-at).total_seconds()>policy.max_span_seconds:
                continue
            key=(row["trading_symbol"],row["expiry"],row["strike"])
            if any(not _valid_number(row.get(k)) for k in ("bid","ask","strike","volume","bid_qty","ask_qty")):
                continue
            if not 0 < row["bid"] <= row["ask"] or row["strike"] <= 0:
                continue
            grouped.setdefault(key,[]).append(row)
        except (ValueError,TypeError,KeyError):
            continue
    if not grouped:
        return []
    strikes=sorted({key[2] for key in grouped})
    atm=min(strikes,key=lambda strike:(abs(strike-spot),strike))
    gap_candidates=sorted(set(abs(strikes[i]-strikes[i-1])
                              for i in range(1,len(strikes)) if strikes[i]!=strikes[i-1]))
    if not gap_candidates:
        return []
    step=gap_candidates[0]
    result=[]
    for (name,expiry,strike),rows in grouped.items():
        ordered=sorted(rows,key=lambda r:r["quote_at"])
        # Collapse duplicate time samples to avoid synthetic momentum points.
        unique={r["quote_at"]:r for r in ordered}
        ordered=[unique[k] for k in sorted(unique)]
        if len(ordered)<policy.min_samples:
            continue
        recent=ordered[-1]
        span=(datetime.fromisoformat(recent["quote_at"])-
              datetime.fromisoformat(ordered[0]["quote_at"])).total_seconds()
        if not policy.min_span_seconds<=span<=policy.max_span_seconds:
            continue
        if (now-datetime.fromisoformat(recent["quote_at"])).total_seconds()>policy.max_quote_age_seconds:
            continue
        if recent["bid_qty"]<policy.min_bid_qty or recent["ask_qty"]<policy.min_ask_qty:
            continue
        if (recent["ask"]-recent["bid"])/recent["ask"]>policy.max_spread_pct:
            continue
        if recent["volume"]-ordered[0]["volume"]<policy.min_volume_growth:
            continue
        bid_return=recent["bid"]/ordered[0]["bid"]-1
        if bid_return<policy.min_bid_return:
            continue
        # OTM is higher strike for CE and lower strike for PE.
        otm=(strike>atm if side=="CE" else strike<atm)
        otm_steps=round(abs(strike-atm)/step)
        if otm and otm_steps>policy.max_otm_steps:
            continue
        # Momentum derived from observed bid change, volume growth, and spread;
        # not a guarantee price will keep going upward after the quote.
        result.append({
            "trading_symbol":name,"expiry":expiry,"side":side,"strike":strike,
            "moneyness":"OTM" if otm else "ATM" if strike==atm else "ITM",
            "otm_steps":otm_steps if otm else 0,
            "entry_ask_reference":recent["ask"],
            "last_bid":recent["bid"],
            "bid_change_pct":round(bid_return*100,3),
            "volume_growth":recent["volume"]-ordered[0]["volume"],
            "spread_pct":round(100*(recent["ask"]-recent["bid"])/recent["ask"],3),
            "quote_at":recent["quote_at"],
            "delta":recent.get("delta"),"iv":recent.get("iv"),
            "score":round(100*bid_return-100*(recent["ask"]-recent["bid"])/recent["ask"],3),
            "research_only":True,"entry_is_executable":False,
            "premium_stop":None,"premium_exit_target":None,
        })
    return sorted(result,key=lambda x:(x["score"],x["volume_growth"]),reverse=True)
