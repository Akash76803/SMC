"""V3.2 opt-in adapter: closed-candle SMC events -> explainable setup stages.

This adapter cannot assert higher-timeframe bias/POI, verified quote prices or
actual stop orders. Those remain PENDING until separately supplied and checked.
No live orders, no lookahead, no automatically generated PREMIUM_PLAN.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from .decision_v3 import CheckState, ResearchBracket
from .entry_v1 import EntryResult, State, evaluate_entry
from .models import Candle
from .phase2 import scan
from .setup_confirmation_v3 import (
    ObservedStage, PremiumPlan, SetupAssessment, SetupKind, assess_setup,
)


@dataclass(frozen=True)
class EvidenceAdapterReport:
    assessment: SetupAssessment
    selected_sweep_index: int | None
    entry_state: str | None
    entry_reason: str | None
    liquidity_events_count: int
    structure_events_count: int

    def as_dict(self) -> dict:
        data = self.assessment.as_dict()
        data["candle_evidence"] = {
            "selected_sweep_index": self.selected_sweep_index,
            "entry_state": self.entry_state,
            "entry_reason": self.entry_reason,
            "liquidity_events_count": self.liquidity_events_count,
            "structure_events_count": self.structure_events_count,
        }
        return data


def _pass(code: str, description: str, index: int,
          candles: list[Candle]) -> ObservedStage:
    if not 0 <= index < len(candles) or not candles[index].complete:
        raise ValueError("UNCONFIRMED_CANDLE_EVIDENCE")
    return ObservedStage(
        code, CheckState.PASS, description,
        candles[index].timestamp, f"ltf:closed:{index}",
    )


def _latest_candidate(results: list[EntryResult]) -> EntryResult | None:
    # Choose most recent sweep deterministically, not the setup with the best
    # hindsight outcome. Same sweep levels can yield separate duplicate events.
    return max(results, key=lambda r: (r.sweep_index, r.transition_index),
               default=None)


def adapt_reversal_candles(*, symbol: str, candles: list[Candle],
                           observed_at: datetime,
                           data_healthy: bool = False,
                           verified_htf: tuple[ObservedStage, ...] = (),
                           index_bracket: ResearchBracket | None = None,
                           premium_plan: PremiumPlan | None = None,
                           option_data_verified: bool = False,
                           ttl_minutes: int = 60) -> EvidenceAdapterReport:
    """Map existing research detectors to the reversal UI contract.

    HTF evidence is not inferred from LTF candles. The caller must separately
    validate any supplied HTF_BIAS / HTF_POI PASS against fully closed HTF
    candles and a versioned rule. No auto READY on LTF evidence alone.
    """
    if observed_at.tzinfo is None:
        raise ValueError("OBSERVED_AT_REQUIRES_OFFSET")
    if any(a.timestamp >= b.timestamp for a, b in zip(candles, candles[1:])):
        raise ValueError("UNORDERED_CANDLES")
    if any(c.timestamp > observed_at for c in candles):
        raise ValueError("FUTURE_CANDLE_INPUT")
    if any(s.code not in ("HTF_BIAS", "HTF_POI") for s in verified_htf):
        raise ValueError("ONLY_HTF_STAGES_ACCEPTED")
    if len(set(s.code for s in verified_htf)) != len(verified_htf):
        raise ValueError("DUPLICATE_HTF_STAGE")
    if not candles or not all(c.complete for c in candles):
        data_healthy = False

    # Data quality belongs to the feed auditor; a caller's healthy flag is
    # necessary but not enough to override missing/incomplete candle data.
    if data_healthy:
        result = scan(candles)
        entries = evaluate_entry(
            candles, result.liquidity_events, result.structure_events,
            symbol=symbol,
        )
    else:
        result = None
        entries = []
    selected = _latest_candidate(entries)
    stages = list(verified_htf)
    created_at = None
    if selected is not None:
        idx = selected.sweep_index
        created_at = candles[idx].timestamp
        stages.append(_pass(
            "LIQUIDITY_SWEEP", "Closed-candle external/internal price-level sweep",
            idx, candles,
        ))
        if selected.choch_index is not None:
            stages.append(ObservedStage(
                "MSS_CONFIRMED", CheckState.PENDING,
                "Internal CHoCH detected; ICT MSS/displacement verification pending",
                source_id=f"ltf:choch:{selected.choch_index}",
            ))
        if selected.fvg_index is not None:
            stages.append(ObservedStage(
                "DISPLACEMENT_FVG", CheckState.PENDING,
                "Directional FVG found; displacement strength requires independent confirmation",
                source_id=f"ltf:fvg:{selected.fvg_index}",
            ))
        if selected.entry is not None and selected.fvg_index is not None:
            stages.append(_pass(
                "RETEST_CONFIRMED",
                "Closed-candle FVG retest/rejection proxy; not an option fill",
                selected.transition_index, candles,
            ))
        if selected.state in (State.INVALIDATED, State.EXPIRED):
            # A timed-out/invalidated setup cannot be revived by a later
            # premium plan or external HTF evidence.
            fail_code = ("RETEST_CONFIRMED" if selected.fvg_index is not None
                         else "MSS_CONFIRMED" if selected.choch_index is None
                         else "DISPLACEMENT_FVG")
            stages = [s for s in stages if s.code != fail_code]
            stages.append(ObservedStage(
                fail_code, CheckState.FAIL,
                f"{selected.state.value}: {selected.reason}",
            ))
    assessment = assess_setup(
        symbol=symbol, kind=SetupKind.REVERSAL,
        direction="BEARISH" if selected and selected.side.value == "PE" else "BULLISH",
        observed_at=observed_at, stages=tuple(stages),
        index_bracket=index_bracket, premium_plan=premium_plan,
        data_healthy=data_healthy,
        option_data_verified=option_data_verified,
        setup_created_at=created_at, ttl_minutes=ttl_minutes,
    )
    return EvidenceAdapterReport(
        assessment,
        selected.sweep_index if selected else None,
        selected.state.value if selected else None,
        selected.reason if selected else None,
        len(result.liquidity_events) if result else 0,
        len(result.structure_events) if result else 0,
    )
