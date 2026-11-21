"""Straddle quote evaluation and validation for Range Predictor V2.

Strictly requires contemporaneous, authenticated broker quotes for both CE and PE legs
with matched ATM strike and expiry. Rejects stale, future, or wide-spread quotes.
Breakevens are strictly defined as expiry payoffs, NEVER intraday reversal walls.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")


@dataclass(frozen=True)
class StraddleQuote:
    """Individual option leg quote snapshot."""
    trading_symbol: str
    symbol: str
    expiry: str
    side: str
    strike: float
    bid: float
    ask: float
    quote_at: str
    volume: int = 0


@dataclass(frozen=True)
class StraddleAnalysis:
    """Validated straddle pricing and expiry breakeven bands."""
    is_available: bool
    rejection_reason: str | None
    source: str
    symbol: str | None = None
    strike: float | None = None
    expiry: str | None = None
    straddle_mid: float | None = None
    straddle_ask: float | None = None
    expiry_be_low: float | None = None
    expiry_be_high: float | None = None
    time_to_expiry_minutes: int | None = None
    ce_quote: StraddleQuote | None = None
    pe_quote: StraddleQuote | None = None


def parse_quote(data: dict[str, Any] | StraddleQuote | None) -> StraddleQuote | None:
    if data is None:
        return None
    if isinstance(data, StraddleQuote):
        return data
    try:
        return StraddleQuote(
            trading_symbol=str(data.get("trading_symbol", "")),
            symbol=str(data.get("symbol") or data.get("market", "")),
            expiry=str(data.get("expiry", "")),
            side=str(data.get("side", "")).upper(),
            strike=float(data.get("strike", 0.0)),
            bid=float(data.get("bid", 0.0)),
            ask=float(data.get("ask", 0.0)),
            quote_at=str(data.get("quote_at") or data.get("timestamp", "")),
            volume=int(data.get("volume", 0)),
        )
    except (ValueError, TypeError):
        return None


def evaluate_straddle_pair(
    ce_input: dict[str, Any] | StraddleQuote | None,
    pe_input: dict[str, Any] | StraddleQuote | None,
    as_of_ist_iso: str,
    max_age_seconds: int = 60,
    max_spread_pct: float = 0.08,
) -> StraddleAnalysis:
    """Evaluate matched CE/PE ATM pair with strict quality gates."""
    ce = parse_quote(ce_input)
    pe = parse_quote(pe_input)
    
    if ce is None or pe is None:
        return StraddleAnalysis(
            is_available=False,
            rejection_reason="CE_OR_PE_MISSING",
            source="STRADDLE_UNAVAILABLE",
        )
    
    # 1. Strike matching
    if abs(ce.strike - pe.strike) > 1e-4:
        return StraddleAnalysis(
            is_available=False,
            rejection_reason="ATM_STRIKE_MISMATCH",
            source="STRADDLE_UNAVAILABLE",
            strike=ce.strike,
        )
    
    # 2. Expiry matching
    if ce.expiry != pe.expiry:
        return StraddleAnalysis(
            is_available=False,
            rejection_reason="EXPIRY_MISMATCH",
            source="STRADDLE_UNAVAILABLE",
            expiry=ce.expiry,
        )
    
    # 3. Valid bid/ask prices
    if ce.bid <= 0 or ce.ask <= 0 or pe.bid <= 0 or pe.ask <= 0:
        return StraddleAnalysis(
            is_available=False,
            rejection_reason="INVALID_ZERO_PRICE",
            source="STRADDLE_UNAVAILABLE",
        )
    
    # 4. Bid <= Ask sanity
    if ce.bid > ce.ask or pe.bid > pe.ask:
        return StraddleAnalysis(
            is_available=False,
            rejection_reason="CROSSED_BID_ASK",
            source="STRADDLE_UNAVAILABLE",
        )
    
    # 5. Spread width check
    ce_spread = (ce.ask - ce.bid) / ce.ask
    pe_spread = (pe.ask - pe.bid) / pe.ask
    if ce_spread > max_spread_pct or pe_spread > max_spread_pct:
        return StraddleAnalysis(
            is_available=False,
            rejection_reason="WIDE_SPREAD",
            source="STRADDLE_UNAVAILABLE",
        )
    
    # 6. Timestamp verification against as_of
    try:
        as_of_dt = datetime.fromisoformat(as_of_ist_iso)
        if as_of_dt.tzinfo is None:
            as_of_dt = as_of_dt.replace(tzinfo=IST)
        
        ce_dt = datetime.fromisoformat(ce.quote_at)
        if ce_dt.tzinfo is None:
            ce_dt = ce_dt.replace(tzinfo=IST)
            
        pe_dt = datetime.fromisoformat(pe.quote_at)
        if pe_dt.tzinfo is None:
            pe_dt = pe_dt.replace(tzinfo=IST)
    except (ValueError, TypeError):
        return StraddleAnalysis(
            is_available=False,
            rejection_reason="MALFORMED_TIMESTAMP",
            source="STRADDLE_UNAVAILABLE",
        )
    
    # No future quotes
    if ce_dt > as_of_dt or pe_dt > as_of_dt:
        return StraddleAnalysis(
            is_available=False,
            rejection_reason="QUOTE_AFTER_AS_OF",
            source="STRADDLE_UNAVAILABLE",
        )
    
    # Staleness check
    ce_age = (as_of_dt - ce_dt).total_seconds()
    pe_age = (as_of_dt - pe_dt).total_seconds()
    if ce_age > max_age_seconds or pe_age > max_age_seconds:
        return StraddleAnalysis(
            is_available=False,
            rejection_reason="STALE_QUOTE",
            source="STRADDLE_UNAVAILABLE",
        )
    
    # 7. Math calculations
    straddle_mid = ((ce.bid + ce.ask) / 2.0) + ((pe.bid + pe.ask) / 2.0)
    straddle_ask = ce.ask + pe.ask
    expiry_be_low = round(ce.strike - straddle_ask, 2)
    expiry_be_high = round(ce.strike + straddle_ask, 2)
    
    # Expiry DTE in minutes
    try:
        exp_date = datetime.strptime(ce.expiry, "%Y-%m-%d").date()
        exp_close = datetime.combine(exp_date, datetime.min.time(), tzinfo=IST).replace(hour=15, minute=30)
        dte_mins = max(0, int((exp_close - as_of_dt).total_seconds() // 60))
    except Exception:
        dte_mins = None
    
    return StraddleAnalysis(
        is_available=True,
        rejection_reason=None,
        source="OBSERVED_BROKER_DEPTH",
        symbol=ce.symbol or pe.symbol,
        strike=ce.strike,
        expiry=ce.expiry,
        straddle_mid=round(straddle_mid, 2),
        straddle_ask=round(straddle_ask, 2),
        expiry_be_low=expiry_be_low,
        expiry_be_high=expiry_be_high,
        time_to_expiry_minutes=dte_mins,
        ce_quote=ce,
        pe_quote=pe,
    )
