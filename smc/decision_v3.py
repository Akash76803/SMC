"""V3 Phase 0: explainable, fail-closed research-only setup decisions.

Pure contract: it does not generate market prices or execute orders.
"""
from __future__ import annotations
from dataclasses import dataclass
from enum import Enum
from typing import Iterable

class DecisionStatus(str, Enum):
    DATA_BLOCKED = "DATA_BLOCKED"
    NO_TRADE = "NO_TRADE"
    WAIT = "WAIT"
    RESEARCH_READY = "RESEARCH_READY"

class CheckState(str, Enum):
    PASS = "PASS"
    PENDING = "PENDING"
    FAIL = "FAIL"

@dataclass(frozen=True)
class EvidenceCheck:
    code: str
    state: CheckState
    description: str
    source_id: str | None = None

    def __post_init__(self) -> None:
        if not self.code or not self.description:
            raise ValueError("check code and description are required")
        if not isinstance(self.state, CheckState):
            raise ValueError("invalid check state")

@dataclass(frozen=True)
class ResearchBracket:
    """Underlying index points; not option premium or live order levels."""
    entry: float
    stop: float
    target: float
    direction: str

    def __post_init__(self) -> None:
        if self.direction not in ("BULLISH", "BEARISH"):
            raise ValueError("invalid direction")
        if min(self.entry, self.stop, self.target) <= 0:
            raise ValueError("prices must be positive")
        if self.direction == "BULLISH" and not (self.stop < self.entry < self.target):
            raise ValueError("invalid bullish bracket")
        if self.direction == "BEARISH" and not (self.target < self.entry < self.stop):
            raise ValueError("invalid bearish bracket")

    @property
    def rr(self) -> float:
        return abs(self.target - self.entry) / abs(self.entry - self.stop)

    @property
    def target_points(self) -> float:
        return abs(self.target - self.entry)

@dataclass(frozen=True)
class SetupDecision:
    schema_version: str
    policy_version: str
    symbol: str
    strategy: str
    status: DecisionStatus
    primary_reason: str
    checks: tuple[EvidenceCheck, ...]
    bracket: ResearchBracket | None
    research_only: bool = True

    def as_dict(self) -> dict:
        return {
            "schema_version": self.schema_version,
            "policy_version": self.policy_version,
            "symbol": self.symbol,
            "strategy": self.strategy,
            "status": self.status.value,
            "primary_reason": self.primary_reason,
            "checks": [
                {"code": c.code, "state": c.state.value,
                 "description": c.description, "source_id": c.source_id}
                for c in self.checks
            ],
            "bracket": None if self.bracket is None else {
                "direction": self.bracket.direction,
                "entry": self.bracket.entry,
                "stop": self.bracket.stop,
                "target": self.bracket.target,
                "index_rr": self.bracket.rr,
                "index_target_points": self.bracket.target_points,
            },
            "research_only": True,
        }

def decide_setup(*, symbol: str, strategy: str,
                 checks: Iterable[EvidenceCheck],
                 bracket: ResearchBracket | None = None,
                 data_healthy: bool = False,
                 option_data_verified: bool = False,
                 policy_version: str = "v3.0.0-research",
                 min_rr: float = 2.0) -> SetupDecision:
    """Fail closed. Research READY is never permission to trade."""
    if symbol not in ("NIFTY", "SENSEX"):
        raise ValueError("unsupported symbol")
    if not strategy or min_rr <= 0:
        raise ValueError("strategy and positive min_rr required")
    items = tuple(checks)
    if len(set(c.code for c in items)) != len(items):
        raise ValueError("duplicate check codes")
    if not data_healthy:
        status, reason = DecisionStatus.DATA_BLOCKED, "DATA_UNVERIFIED_OR_STALE"
    elif not items:
        status, reason = DecisionStatus.WAIT, "NO_CONFIRMED_SETUP_EVIDENCE"
    else:
        failed = next((c for c in items if c.state is CheckState.FAIL), None)
        pending = next((c for c in items if c.state is CheckState.PENDING), None)
        if failed:
            status, reason = DecisionStatus.NO_TRADE, failed.code
        elif pending:
            status, reason = DecisionStatus.WAIT, pending.code
        elif bracket is None:
            status, reason = DecisionStatus.WAIT, "ENTRY_SL_TARGET_NOT_VERIFIED"
        elif bracket.target_points < (50 if symbol == "NIFTY" else 100):
            status, reason = DecisionStatus.NO_TRADE, "INDEX_TARGET_TOO_SMALL"
        elif bracket.rr < min_rr:
            status, reason = DecisionStatus.NO_TRADE, "INDEX_RR_BELOW_MINIMUM"
        elif not option_data_verified:
            status, reason = DecisionStatus.WAIT, "OPTION_QUOTES_GREEKS_NOT_VERIFIED"
        else:
            status, reason = DecisionStatus.RESEARCH_READY, "RESEARCH_GATES_PASSED"
    return SetupDecision("3.0", policy_version, symbol, strategy, status,
                         reason, items, bracket)
