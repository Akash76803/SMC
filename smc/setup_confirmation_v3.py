"""Explainable Phase V3 setup orchestration. Research-only: no orders or inference from raw candles."""
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
from .decision_v3 import CheckState, DecisionStatus, EvidenceCheck, ResearchBracket, SetupDecision, decide_setup
from .premium_feasibility_v3 import PremiumFeasibility, evaluate_premium_bracket

class SetupKind(str, Enum):
    REVERSAL = "REVERSAL"
    CONTINUATION = "CONTINUATION"

STAGES: dict[SetupKind, tuple[str, ...]] = {
    SetupKind.REVERSAL: (
        "HTF_BIAS", "LIQUIDITY_SWEEP", "HTF_POI", "MSS_CONFIRMED",
        "DISPLACEMENT_FVG", "RETEST_CONFIRMED"),
    SetupKind.CONTINUATION: (
        "HTF_BIAS", "PROTECTED_STRUCTURE", "HTF_POI", "PULLBACK",
        "CONTINUATION_BOS", "RETEST_CONFIRMED"),
}

@dataclass(frozen=True)
class ObservedStage:
    code: str
    state: CheckState
    description: str
    confirmed_at: datetime | None = None
    source_id: str | None = None

    def __post_init__(self) -> None:
        if not self.code or not self.description or not isinstance(self.state, CheckState):
            raise ValueError("INVALID_SETUP_STAGE")
        if self.confirmed_at is not None and self.confirmed_at.tzinfo is None:
            raise ValueError("STAGE_TIMESTAMP_REQUIRES_OFFSET")
        if self.state is CheckState.PASS and (self.confirmed_at is None or not self.source_id):
            raise ValueError("PASS_REQUIRES_TIMESTAMP_AND_EVIDENCE")

@dataclass(frozen=True)
class PremiumPlan:
    """Hypothetical per-contract bracket; not an observed quote or fill."""
    target_points: float
    stop_points: float
    round_trip_cost_per_unit: float

@dataclass(frozen=True)
class SetupAssessment:
    decision: SetupDecision
    next_confirmation: str | None
    premium: PremiumFeasibility | None
    stage_progress: tuple[dict, ...]

    def as_dict(self) -> dict:
        output = self.decision.as_dict()
        output["next_confirmation"] = self.next_confirmation
        output["stages"] = list(self.stage_progress)
        output["premium_feasibility"] = None if self.premium is None else {
            "accepted": self.premium.accepted,
            "reason": self.premium.reason,
            "gross_target_points": self.premium.gross_target_points,
            "gross_stop_points": self.premium.gross_stop_points,
            "net_reward_points": self.premium.net_reward_points,
            "net_risk_points": self.premium.net_risk_points,
            "net_rr": self.premium.net_rr,
        }
        return output

def assess_setup(*, symbol: str, kind: SetupKind, direction: str,
                 observed_at: datetime, stages: tuple[ObservedStage, ...],
                 index_bracket: ResearchBracket | None = None,
                 premium_plan: PremiumPlan | None = None,
                 data_healthy: bool = False,
                 option_data_verified: bool = False,
                 setup_created_at: datetime | None = None,
                 ttl_minutes: int = 60) -> SetupAssessment:
    """Caller must verify closed-candle stage evidence and data independently."""
    if not isinstance(kind, SetupKind) or direction not in ("BULLISH", "BEARISH"):
        raise ValueError("INVALID_SETUP_KIND_OR_DIRECTION")
    if observed_at.tzinfo is None or (setup_created_at is not None and setup_created_at.tzinfo is None):
        raise ValueError("TIMESTAMPS_REQUIRE_OFFSET")
    if ttl_minutes <= 0:
        raise ValueError("INVALID_SETUP_TTL")
    if setup_created_at is not None and setup_created_at > observed_at:
        raise ValueError("SETUP_CREATED_IN_FUTURE")
    if index_bracket is not None and index_bracket.direction != direction:
        raise ValueError("BRACKET_DIRECTION_MISMATCH")
    required = STAGES[kind]
    mapping = {s.code: s for s in stages}
    if len(mapping) != len(stages) or any(code not in required for code in mapping):
        raise ValueError("DUPLICATE_OR_UNKNOWN_STAGE")
    for stage in stages:
        if stage.confirmed_at is not None and stage.confirmed_at > observed_at:
            raise ValueError("FUTURE_STAGE_EVIDENCE")
        if (setup_created_at is not None and stage.confirmed_at is not None
                and stage.confirmed_at < setup_created_at):
            raise ValueError("STAGE_PREDATES_SETUP")
    checks = []
    progress = []
    next_confirmation = None
    for code in required:
        s = mapping.get(code)
        state = s.state if s is not None else CheckState.PENDING
        desc = s.description if s is not None else "Awaiting confirmed closed-candle evidence"
        if state is CheckState.PENDING and next_confirmation is None:
            next_confirmation = code
        checks.append(EvidenceCheck(code, state, desc, s.source_id if s else None))
        progress.append({"code": code, "state": state.value, "description": desc,
                         "confirmed_at": s.confirmed_at.isoformat() if s and s.confirmed_at else None,
                         "source_id": s.source_id if s else None})
    expired = (setup_created_at is not None and
               observed_at > setup_created_at + timedelta(minutes=ttl_minutes))
    if expired:
        checks.insert(0, EvidenceCheck("SETUP_EXPIRED", CheckState.FAIL,
                                      "Setup exceeded its allowed time window"))
        next_confirmation = None
    premium = None
    if premium_plan is None:
        checks.append(EvidenceCheck("PREMIUM_PLAN", CheckState.PENDING,
                                    "Premium target/stop/cost scenario required"))
        if next_confirmation is None and not expired:
            next_confirmation = "PREMIUM_PLAN"
    else:
        premium = evaluate_premium_bracket(
            target_points=premium_plan.target_points,
            stop_points=premium_plan.stop_points,
            round_trip_cost_per_unit=premium_plan.round_trip_cost_per_unit)
        checks.append(EvidenceCheck(
            "PREMIUM_FEASIBILITY",
            CheckState.PASS if premium.accepted else CheckState.FAIL,
            premium.reason,
            "policy:v3-15pt-net3r" if premium.accepted else None))
    decision = decide_setup(symbol=symbol, strategy=kind.value,
                            checks=checks, bracket=index_bracket,
                            data_healthy=data_healthy,
                            option_data_verified=option_data_verified,
                            policy_version="v3.1-setup-confirmation")
    if decision.status is not DecisionStatus.WAIT:
        next_confirmation = None
    elif decision.primary_reason == "ENTRY_SL_TARGET_NOT_VERIFIED":
        next_confirmation = "INDEX_BRACKET"
    elif decision.primary_reason == "OPTION_QUOTES_GREEKS_NOT_VERIFIED":
        next_confirmation = "OPTION_QUOTES_GREEKS"
    return SetupAssessment(decision, next_confirmation, premium, tuple(progress))
