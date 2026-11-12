"""Options screen: ATM/ITM, delta, freshness, spread and cost-adjusted exit scenarios."""
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime
from .models import IndexSetup, OptionQuote, Side
from .risk import validate_index_setup


@dataclass(frozen=True)
class RankedOption:
    quote: OptionQuote
    net_rr: float
    net_reward: float
    net_risk: float


def rank_options(
    setup: IndexSetup,
    spot: float,
    quotes: list[OptionQuote],
    now: datetime,
    *,
    max_quote_age_seconds: int = 10,
    max_spread_fraction: float = 0.03,
    min_volume: int = 1,
    round_trip_cost_per_unit: float = 2.0,
) -> list[RankedOption]:
    if not validate_index_setup(setup).accepted or not quotes or spot <= 0:
        return []
    if now.tzinfo is None:
        raise ValueError("now must have timezone")
    same_side = [q for q in quotes if q.side == setup.side]
    if not same_side:
        return []
    valid_strikes = sorted({q.strike for q in same_side})
    atm = min(valid_strikes, key=lambda s: (abs(s-spot), s))
    # One step ITM (not necessarily same *numeric* distance for every exchange)
    itm_candidates = ([x for x in valid_strikes if x < atm] if setup.side == Side.CE
                      else [x for x in valid_strikes if x > atm])
    itm = (max(itm_candidates) if setup.side == Side.CE
           else min(itm_candidates)) if itm_candidates else None
    candidate_strikes = {atm, itm}
    ranked = []
    for q in same_side:
        if q.strike not in candidate_strikes:
            continue
        if q.lot_size < 1 or q.volume < min_volume or not (0 < q.bid <= q.ask):
            continue
        age = (now - q.quote_time).total_seconds()
        if age < 0 or age > max_quote_age_seconds or q.expiry <= now:
            continue
        if (q.ask - q.bid) / q.ask > max_spread_fraction:
            continue
        # Delta is signed for PE and CE, use magnitude to select responsiveness.
        if q.delta is None or not (0.50 <= abs(q.delta) <= 0.70):
            continue
        if q.target_exit_bid is None or q.stop_exit_bid is None:
            continue  # No invented option scenario
        if q.target_exit_bid < 0 or q.stop_exit_bid < 0:
            continue
        reward = (q.target_exit_bid - q.ask) - round_trip_cost_per_unit
        risk = (q.ask - q.stop_exit_bid) + round_trip_cost_per_unit
        if risk <= 0 or reward <= 0 or reward / risk < 2.0:
            continue
        ranked.append(RankedOption(q, reward/risk, reward*q.lot_size, risk*q.lot_size))
    return sorted(ranked, key=lambda r: (r.net_rr, r.net_reward), reverse=True)
