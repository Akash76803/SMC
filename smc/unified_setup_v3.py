"""V3.5 unified research assessment: HTF context + LTF events + target + POI.

Opt-in only. Evidence is evaluated as-of a selected setup's transition bar
and no later-confirmed liquidity level or HTF close can backfill the setup.
A candidate OB/FVG overlap is never a verified HTF POI or a trade trigger.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from .decision_v3 import DecisionStatus, ResearchBracket
from .entry_v1 import State, evaluate_entry
from .evidence_adapter_v3 import EvidenceAdapterReport, adapt_reversal_candles
from .htf_context_v3 import HTFContext, analyze_htf, bias_stage
from .models import Candle
from .phase2 import scan
from .poi_liquidity_v3 import (
    POIReview, TargetReview, candidate_poi_stage,
    index_bracket_from_target, review_liquidity_target, review_ob_fvg_poi,
)
from .setup_confirmation_v3 import PremiumPlan


@dataclass(frozen=True)
class UnifiedSetupReport:
    status: DecisionStatus
    primary_reason: str
    context: HTFContext
    evidence: EvidenceAdapterReport
    target_review: TargetReview | None
    poi_review: POIReview | None
    direction: str | None
    index_bracket: ResearchBracket | None
    assessment_at: datetime
    selected_transition_index: int | None

    def as_dict(self) -> dict:
        return {
            "schema_version": "3.5",
            "status": self.status.value,
            "primary_reason": self.primary_reason,
            "direction": self.direction,
            "assessment_at": self.assessment_at.isoformat(),
            "selected_transition_index": self.selected_transition_index,
            "htf": self.context.as_dict(),
            "setup": self.evidence.as_dict(),
            "target_review": self.target_review.as_dict() if self.target_review else None,
            "poi_review": self.poi_review.as_dict() if self.poi_review else None,
            "index_bracket": (None if self.index_bracket is None else {
                "entry": self.index_bracket.entry,
                "stop": self.index_bracket.stop,
                "target": self.index_bracket.target,
                "index_rr": self.index_bracket.rr,
                "index_target_points": self.index_bracket.target_points,
            }),
            "research_only": True,
            "live_orders_enabled": False,
        }


def evaluate_unified_reversal(*, symbol: str, ltf: list[Candle],
                              monthly: list[Candle], weekly: list[Candle],
                              daily: list[Candle], observed_at: datetime,
                              data_healthy: bool = False,
                              option_data_verified: bool = False,
                              premium_plan: PremiumPlan | None = None,
                              ttl_minutes: int = 60) -> UnifiedSetupReport:
    """Compose independent V3 research modules without inventing missing evidence.

    Inputs to the HTF engine must have candle-CLOSE timestamps. The data_healthy
    flag is granted only by an external feed quality checker; if false the
    unified setup cannot be a trading candidate. Quotes are verified externally.
    """
    if symbol not in ("NIFTY", "SENSEX"):
        raise ValueError("UNSUPPORTED_SYMBOL")
    if observed_at.tzinfo is None:
        raise ValueError("OBSERVED_AT_REQUIRES_OFFSET")

    preliminary = adapt_reversal_candles(
        symbol=symbol, candles=ltf, observed_at=observed_at,
        data_healthy=data_healthy, option_data_verified=False,
        ttl_minutes=ttl_minutes)
    direction = preliminary.selected_direction
    transition_index = None
    selected = None

    if direction is not None and data_healthy and ltf and all(c.complete for c in ltf):
        full_scan = scan(ltf)
        all_entries = evaluate_entry(
            ltf, full_scan.liquidity_events, full_scan.structure_events,
            symbol=symbol)
        # Same deterministic selection policy as V3.2.
        selected = max(
            all_entries,
            key=lambda e: (e.sweep_index, e.transition_index),
            default=None)
        if selected is None or selected.sweep_index != preliminary.selected_sweep_index:
            raise ValueError("INCONSISTENT_SELECTED_SETUP")
        transition_index = selected.transition_index
        if not 0 <= transition_index < len(ltf):
            raise ValueError("INVALID_TRANSITION_INDEX")

    # Never leak HTF information closed after the ORIGINAL sweep, including
    # when a later FVG/retest supplies the eventual index bracket.
    htf_at = (ltf[preliminary.selected_sweep_index].timestamp
              if preliminary.selected_sweep_index is not None else observed_at)
    context = analyze_htf(
        monthly=[c for c in monthly if c.timestamp <= htf_at],
        weekly=[c for c in weekly if c.timestamp <= htf_at],
        daily=[c for c in daily if c.timestamp <= htf_at],
        as_of=htf_at)
    if direction is None:
        # No trade direction identified: HTF bias is context only.
        htf_stage = None
    else:
        htf_stage = bias_stage(context, desired_direction=direction)

    target_review = None
    poi_review = None
    bracket = None
    poi_stage = None
    if selected is not None and direction is not None:
        # Limit POI/target eligibility to the moment a retest or timeout was
        # resolved; later candles must not supply retroactive targets.
        partial = ltf[:transition_index + 1]
        history = scan(partial)
        poi_review = review_ob_fvg_poi(
            candles=partial, breaks=list(history.structure_events),
            direction=direction, as_of=partial[-1].timestamp)
        poi_stage = candidate_poi_stage(poi_review)
        if (selected.entry is not None and selected.stop is not None
                and selected.state in (State.REJECTED, State.CANDIDATE)):
            target_review = review_liquidity_target(
                candles=partial, levels=list(history.levels),
                events=list(history.liquidity_events), direction=direction,
                entry=selected.entry, stop=selected.stop, symbol=symbol,
                as_of=partial[-1].timestamp)
            bracket = index_bracket_from_target(
                entry=selected.entry, stop=selected.stop,
                direction=direction, review=target_review)

    htf_stages = tuple(s for s in (htf_stage, poi_stage) if s is not None)
    evidence = adapt_reversal_candles(
        symbol=symbol, candles=ltf, observed_at=observed_at,
        data_healthy=data_healthy, verified_htf=htf_stages,
        index_bracket=bracket, premium_plan=premium_plan,
        option_data_verified=option_data_verified,
        ttl_minutes=ttl_minutes)

    status = evidence.assessment.decision.status
    reason = evidence.assessment.decision.primary_reason
    if status is not DecisionStatus.DATA_BLOCKED and target_review is not None:
        if target_review.status == "NO_TRADE":
            status, reason = DecisionStatus.NO_TRADE, target_review.reason
    # Even with a hypothetical cost-adjusted premium plan and quote flags,
    # incomplete ICT MSS/displacement and candidate POI cannot be promoted.
    if status is DecisionStatus.RESEARCH_READY:
        raise ValueError("V3_5_UNVERIFIED_POI_MUST_NOT_BE_READY")
    return UnifiedSetupReport(
        status, reason, context, evidence, target_review, poi_review,
        direction, bracket, observed_at, transition_index)
