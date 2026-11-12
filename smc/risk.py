"""Strict index target and RR gates, without assuming profitability."""
from dataclasses import dataclass
from .models import IndexSetup, Side

MIN_POINTS = {"SENSEX": 100.0, "NIFTY": 50.0}


@dataclass(frozen=True)
class Validation:
    accepted: bool
    reasons: tuple[str, ...]
    index_rr: float | None


def validate_index_setup(setup: IndexSetup) -> Validation:
    reasons = []
    if setup.symbol not in MIN_POINTS:
        reasons.append("UNKNOWN_SYMBOL")
    if not setup.confirmed or setup.scheme == "UNVERIFIED":
        reasons.append("UNCONFIRMED_SMC_SCHEME")
    if setup.side == Side.CE and not (setup.stop < setup.entry < setup.target):
        reasons.append("INVALID_CE_LEVELS")
    if setup.side == Side.PE and not (setup.target < setup.entry < setup.stop):
        reasons.append("INVALID_PE_LEVELS")
    if min(setup.entry, setup.stop, setup.target) <= 0:
        reasons.append("NON_POSITIVE_PRICE")
    risk = abs(setup.entry - setup.stop)
    reward = abs(setup.target - setup.entry)
    rr = reward / risk if risk > 0 else None
    if rr is None or rr < 2.0:
        reasons.append("INDEX_RR_BELOW_2")
    if setup.symbol in MIN_POINTS and reward < MIN_POINTS[setup.symbol]:
        reasons.append("INDEX_TARGET_TOO_SMALL")
    return Validation(not reasons, tuple(reasons), rr)
