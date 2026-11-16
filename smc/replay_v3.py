"""V3.7 conservative index-only historical diagnostic replay.

No order execution, no option P&L, no fill simulation. Uses closed-candle
prefixes; each assessment is immutable once a new transition is observed.
A V3.5 WAIT report with an index bracket is diagnostic only, NEVER a trade.
Target/stop collisions are recorded as ambiguous, not silently profitable.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import timedelta
from math import isfinite

from .decision_v3 import DecisionStatus, ResearchBracket
from .models import Candle
from .unified_setup_v3 import UnifiedSetupReport, evaluate_unified_reversal


@dataclass(frozen=True)
class LevelOutcome:
    name: str
    price: float
    result: str  # HIT / STOP_FIRST / AMBIGUOUS_SAME_BAR / TIME_EXIT / DATA_GAP / NO_FUTURE_BARS
    resolved_index: int | None
    maximum_favorable_points: float
    maximum_adverse_points: float

    def as_dict(self) -> dict:
        return vars(self).copy()


@dataclass(frozen=True)
class ReplayObservation:
    transition_index: int
    timestamp: str
    status: str
    reason: str
    direction: str | None
    index_bracket: dict | None
    level_outcomes: tuple[LevelOutcome, ...]
    research_only: bool = True
    diagnostics: dict | None = None
    terminal_cause: str | None = None

    def as_dict(self) -> dict:
        return {
            "transition_index": self.transition_index,
            "timestamp": self.timestamp,
            "status": self.status,
            "reason": self.reason,
            "direction": self.direction,
            "index_bracket": self.index_bracket,
            "level_outcomes": [o.as_dict() for o in self.level_outcomes],
            "diagnostics": self.diagnostics,
            "terminal_cause": self.terminal_cause,
            "research_only": True,
        }


@dataclass(frozen=True)
class ReplaySummary:
    symbol: str
    observed_bars: int
    status_counts: dict[str, int]
    reason_counts: dict[str, int]
    observations: tuple[ReplayObservation, ...]
    evaluated_prefixes: int
    diagnostic_brackets: int
    terminal_cause_counts: dict[str, int] | None = None
    research_only: bool = True

    def as_dict(self) -> dict:
        return {
            "schema_version": "3.7",
            "symbol": self.symbol,
            "observed_bars": self.observed_bars,
            "evaluated_prefixes": self.evaluated_prefixes,
            "status_counts": self.status_counts,
            "reason_counts": self.reason_counts,
            "diagnostic_brackets": self.diagnostic_brackets,
            "terminal_cause_counts": self.terminal_cause_counts or {},
            "observations": [x.as_dict() for x in self.observations],
            "research_only": True,
            "option_pnl": None,
            "live_orders_enabled": False,
        }


def evaluate_level_outcomes(*, candles: list[Candle], confirmation_index: int,
                            bracket: ResearchBracket, levels: tuple[tuple[str, float], ...],
                            max_holding_bars: int = 24,
                            expected_bar_seconds: int = 60) -> tuple[LevelOutcome, ...]:
    """Start strictly AFTER the confirmation close. No assumed execution.

    The same bar can contain both SL and target: outcome is AMBIGUOUS.
    Missing contiguous candles fail closed with DATA_GAP; time-exit is not P&L.
    """
    if max_holding_bars < 1 or expected_bar_seconds < 1:
        raise ValueError("INVALID_REPLAY_PARAMETERS")
    if not 0 <= confirmation_index < len(candles):
        raise ValueError("INVALID_CONFIRMATION_INDEX")
    if any(not c.complete for c in candles):
        raise ValueError("REPLAY_REQUIRES_COMPLETED_BARS")
    if any(a.timestamp >= b.timestamp for a,b in zip(candles,candles[1:])):
        raise ValueError("UNORDERED_REPLAY_BARS")
    direction = bracket.direction
    for name, price in levels:
        if not name or not isfinite(price) or (
                price <= bracket.entry if direction == "BULLISH"
                else price >= bracket.entry):
            raise ValueError("INVALID_TARGET_LEVEL")
    resolved = []
    for name, price in levels:
        favorable, adverse = 0.0, 0.0
        outcome, index = "NO_FUTURE_BARS", None
        previous = candles[confirmation_index].timestamp
        for i in range(confirmation_index+1,
                       min(len(candles), confirmation_index+1+max_holding_bars)):
            bar = candles[i]
            if (bar.timestamp-previous).total_seconds() != expected_bar_seconds:
                outcome, index = "DATA_GAP", i
                break
            previous = bar.timestamp
            if direction == "BULLISH":
                favorable = max(favorable, bar.high-bracket.entry)
                adverse = max(adverse, bracket.entry-bar.low)
                sl_hit, tp_hit = bar.low <= bracket.stop, bar.high >= price
            else:
                favorable = max(favorable, bracket.entry-bar.low)
                adverse = max(adverse, bar.high-bracket.entry)
                sl_hit, tp_hit = bar.high >= bracket.stop, bar.low <= price
            if sl_hit and tp_hit:
                outcome, index = "AMBIGUOUS_SAME_BAR", i
                break
            if sl_hit:
                outcome, index = "STOP_FIRST", i
                break
            if tp_hit:
                outcome, index = "HIT", i
                break
            outcome, index = "TIME_EXIT", i
        resolved.append(LevelOutcome(name, price, outcome, index,
                                     favorable, adverse))
    return tuple(resolved)


def replay_unified_reversal(*, symbol: str, ltf: list[Candle],
                            monthly: list[Candle], weekly: list[Candle],
                            daily: list[Candle], data_healthy: bool = False,
                            min_warmup_bars: int = 16,
                            max_holding_bars: int = 24,
                            expected_bar_seconds: int = 60) -> ReplaySummary:
    """One causal assessment per completed bar; diagnostic replay only.

    Setup events are deduplicated by their original transition index. Status
    and reason counts are PER-BAR evaluations, not number of unique trades.
    Calendar/session-specific gap handling must be provided upstream.
    """
    if symbol not in ("NIFTY", "SENSEX") or min_warmup_bars < 1:
        raise ValueError("INVALID_REPLAY_CONFIGURATION")
    if max_holding_bars < 1 or expected_bar_seconds < 1:
        raise ValueError("INVALID_REPLAY_CONFIGURATION")
    if any(not c.complete for c in ltf):
        raise ValueError("INCOMPLETE_LTF_REPLAY")
    if any(a.timestamp >= b.timestamp for a,b in zip(ltf, ltf[1:])):
        raise ValueError("UNORDERED_LTF_REPLAY")
    # Future HTF bars are filtered by the V3.5 engine. Inputs are time-ordered
    # full historical records with timestamps at their real completed CLOSE.
    status_counts, reasons = Counter(), Counter()
    observations = []
    seen_transitions = set()
    terminal_causes = Counter()
    for i in range(min_warmup_bars-1, len(ltf)):
        prefix = ltf[:i+1]
        report = evaluate_unified_reversal(
            symbol=symbol, ltf=prefix,
            monthly=monthly, weekly=weekly, daily=daily,
            observed_at=prefix[-1].timestamp,
            data_healthy=data_healthy, option_data_verified=False)
        status_counts[report.status.value] += 1
        reasons[report.primary_reason] += 1
        transition = report.selected_transition_index
        # WAIT states can change their transition index on each new candle;
        # count those under per-bar status totals only, not unique setups.
        # Log only a terminal retest decision or a terminal expiry/failure.
        terminal = report.evidence.entry_state in (
            "CANDIDATE", "REJECTED", "INVALIDATED", "EXPIRED")
        if (transition is None or transition != i or
                transition in seen_transitions or not terminal):
            continue
        seen_transitions.add(transition)
        terminal_cause = report.evidence.entry_reason
        if terminal_cause:
            terminal_causes[terminal_cause] += 1
        bracket = report.index_bracket
        targets = report.multi_targets
        levels = tuple((x.name,x.candidate.price) for x in targets.levels) if targets else ()
        if bracket is not None and targets is not None and levels:
            # Even when there is a bracket the setup may be WAIT; this is not
            # an accepted strategy trade or an executable entry.
            outcomes = evaluate_level_outcomes(
                candles=ltf, confirmation_index=i, bracket=bracket,
                levels=levels, max_holding_bars=max_holding_bars,
                expected_bar_seconds=expected_bar_seconds)
        else:
            outcomes = ()
        target = report.target_review
        nearest = target.target if target else None
        diagnostics = {
            "selected_sweep_index": report.evidence.selected_sweep_index,
            "entry_state": report.evidence.entry_state,
            "entry_reason": report.evidence.entry_reason,
            "terminal_cause": terminal_cause,
            "decision_stage_reason": report.primary_reason,
            "pending_stages": [
                stage["code"] for stage in report.evidence.assessment.stage_progress
                if stage["state"] != "PASS"],
            "htf_alignment": report.context.alignment.value,
            "htf_alignment_reason": report.context.reason,
            "nearest_target_status": target.status if target else "UNAVAILABLE",
            "nearest_target_reason": target.reason if target else "NO_CANDIDATE_ENTRY",
            "nearest_target_level": nearest.price if nearest else None,
            "nearest_target_kind": nearest.level_kind if nearest else None,
            "nearest_target_points": nearest.index_points if nearest else None,
            "nearest_target_index_rr": nearest.index_rr if nearest else None,
            "minimum_index_target_points": 50 if symbol == "NIFTY" else 100,
            "minimum_index_rr": 2.0,
            "target_evidence_id": nearest.evidence_id if nearest else None,
            "index_entry": bracket.entry if bracket else None,
            "index_stop": bracket.stop if bracket else None,
        }
        observations.append(ReplayObservation(
            transition, prefix[-1].timestamp.isoformat(), report.status.value,
            report.primary_reason, report.direction,
            None if bracket is None else {
                "entry": bracket.entry, "stop": bracket.stop,
                "target": bracket.target, "index_rr": bracket.rr},
            outcomes, diagnostics=diagnostics,
            terminal_cause=terminal_cause))
    return ReplaySummary(
        symbol, len(ltf), dict(status_counts), dict(reasons),
        tuple(observations), max(0,len(ltf)-min_warmup_bars+1),
        sum(o.index_bracket is not None for o in observations),
        dict(terminal_causes))
