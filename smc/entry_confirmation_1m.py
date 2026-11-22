"""SMC Gwaidier 1-Minute (1M) Entry Confirmation Engine & HTF <-> LTF Bridge.

Implements the official Gwaidier Lecture 3: 6 Valid Pullback Patterns on 1M:
  1. CLASSIC_1_CANDLE_PULLBACK: Peak low swept + body close above peak high.
  2. OUTSIDE_CANDLE_LIQUIDITY_GRAB: Both-side sweep (outside bar) + body close.
  3. INSIDE_BAR_MOTHER_SWEEP: Inside bar bypassed; mother candle low swept + body close.
  4. SINGLE_CANDLE_ORDER_BLOCK (SCOB): Low swept & body closed above high in same candle.
  5. INSIDE_BAR_REJECTION_EXPANSION: Mother low swept & closed above mother high in same candle.
  6. MULTI_CANDLE_STEP_PULLBACK: Consecutive lower lows into zone + swing high break.

Full HTF <-> LTF Institutional Price Delivery Cycle:
  [HTF] 15M External Liquidity + Bias + Dealing Range (Premium/Discount) + 15M POI (OB/FVG)
    │
    ▼ (HTF -> LTF)
  [LTF] 1M Internal Liquidity + 6 Valid Pullbacks + SCOB Micro-Trigger + Tight SL
    │
    ▼ (LTF -> HTF)
  [HTF] Opposing External Liquidity Target (T1, T2, T3) + R:R Verification
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from math import isfinite
from typing import Sequence

from .models import Candle, Side


class PullbackPattern(str, Enum):
    CLASSIC_1_CANDLE = "CLASSIC_1_CANDLE"
    OUTSIDE_CANDLE_GRAB = "OUTSIDE_CANDLE_GRAB"
    INSIDE_BAR_MOTHER_SWEEP = "INSIDE_BAR_MOTHER_SWEEP"
    SINGLE_CANDLE_OB = "SINGLE_CANDLE_OB"  # SCOB
    INSIDE_BAR_REJECTION = "INSIDE_BAR_REJECTION"
    MULTI_CANDLE_STEP = "MULTI_CANDLE_STEP"
    NONE = "NONE"


@dataclass(frozen=True)
class ValidPullback1M:
    pattern: PullbackPattern
    direction: str  # BULLISH | BEARISH
    is_valid: bool
    reason: str
    peak_candle_index: int
    sweep_candle_index: int
    trigger_candle_index: int
    sweep_price: float
    trigger_close: float
    provisional_stop: float
    pattern_detail: dict

    def as_dict(self) -> dict:
        return {
            "pattern": self.pattern.value,
            "direction": self.direction,
            "is_valid": self.is_valid,
            "reason": self.reason,
            "peak_candle_index": self.peak_candle_index,
            "sweep_candle_index": self.sweep_candle_index,
            "trigger_candle_index": self.trigger_candle_index,
            "sweep_price": self.sweep_price,
            "trigger_close": self.trigger_close,
            "provisional_stop": self.provisional_stop,
            "pattern_detail": self.pattern_detail,
        }


def is_inside_bar(candle: Candle, mother: Candle) -> bool:
    """Return True if candle is inside mother candle's high-low range."""
    return candle.high <= mother.high and candle.low >= mother.low


def find_mother_candle(candles: Sequence[Candle], current_index: int) -> tuple[int, Candle] | None:
    """
    Given an inside bar sequence ending at current_index, walk backwards to find
    the true 'Mother Candle' that contains all subsequent inside bars.
    """
    if current_index <= 0 or current_index >= len(candles):
        return None
    curr = candles[current_index]
    idx = current_index - 1
    while idx >= 0:
        candidate = candles[idx]
        if is_inside_bar(curr, candidate):
            # Check if candidate itself is inside a prior candle
            if idx > 0 and is_inside_bar(candidate, candles[idx - 1]):
                idx -= 1
                continue
            return idx, candidate
        idx -= 1
    return None


def detect_bullish_pullback_1m(candles: Sequence[Candle], window: int = 15) -> ValidPullback1M:
    """
    Scan the last `window` completed 1M candles for any of the 6 Gwaidier Valid Bullish Pullbacks.
    Bullish Pullback Rule: Must take previous candle/mother low, and trigger must body-close above high.
    """
    if len(candles) < 2:
        return ValidPullback1M(
            PullbackPattern.NONE, "BULLISH", False, "INSUFFICIENT_CANDLES",
            -1, -1, -1, 0.0, 0.0, 0.0, {}
        )

    end_idx = len(candles) - 1
    start_idx = max(1, end_idx - window)

    for i in range(end_idx, start_idx - 1, -1):
        trigger = candles[i]
        if not trigger.complete:
            continue

        # ── Pattern 5: Inside Bar + Rejection Expansion ───────────────────────
        # Mother -> Inside bar -> Candle sweeps Mother's Low AND closes above Mother's High
        if i >= 2:
            prev_bar = candles[i - 1]
            mother_res = find_mother_candle(candles, i - 1)
            if mother_res is not None:
                m_idx, mother = mother_res
                if trigger.low < mother.low and trigger.close > mother.high:
                    return ValidPullback1M(
                        pattern=PullbackPattern.INSIDE_BAR_REJECTION,
                        direction="BULLISH",
                        is_valid=True,
                        reason="INSIDE_BAR_REJECTION_EXPANSION_OVER_MOTHER",
                        peak_candle_index=m_idx,
                        sweep_candle_index=i,
                        trigger_candle_index=i,
                        sweep_price=trigger.low,
                        trigger_close=trigger.close,
                        provisional_stop=trigger.low,
                        pattern_detail={
                            "mother_candle_index": m_idx,
                            "inside_candle_index": i - 1,
                            "mother_high": mother.high,
                            "mother_low": mother.low,
                        },
                    )

        # ── Pattern 3: Inside Bar + Mother Candle Low Taken ───────────────────
        # Mother (Peak) -> Inside bar -> Sweep candle sweeps Mother Low -> Trigger closes above Mother High
        if i >= 3:
            sweep_bar = candles[i - 1]
            inside_bar = candles[i - 2]
            mother_res = find_mother_candle(candles, i - 2)
            if mother_res is not None:
                m_idx, mother = mother_res
                if sweep_bar.low < mother.low and trigger.close > mother.high:
                    stop_level = min(sweep_bar.low, trigger.low)
                    return ValidPullback1M(
                        pattern=PullbackPattern.INSIDE_BAR_MOTHER_SWEEP,
                        direction="BULLISH",
                        is_valid=True,
                        reason="INSIDE_BAR_MOTHER_LOW_SWEPT_CONFIRMED",
                        peak_candle_index=m_idx,
                        sweep_candle_index=i - 1,
                        trigger_candle_index=i,
                        sweep_price=sweep_bar.low,
                        trigger_close=trigger.close,
                        provisional_stop=stop_level,
                        pattern_detail={
                            "mother_candle_index": m_idx,
                            "inside_candle_index": i - 2,
                            "sweep_candle_index": i - 1,
                            "mother_low": mother.low,
                        },
                    )

        # ── Pattern 2: Outside Candle Liquidity Grab ──────────────────────────
        # Candle sweeps both sides of previous candle, next candle closes above outside bar
        if i >= 2:
            outside_bar = candles[i - 1]
            prior = candles[i - 2]
            if (outside_bar.low < prior.low and outside_bar.high > prior.high
                    and trigger.close > outside_bar.high):
                return ValidPullback1M(
                    pattern=PullbackPattern.OUTSIDE_CANDLE_GRAB,
                    direction="BULLISH",
                    is_valid=True,
                    reason="OUTSIDE_BAR_BOTH_SIDE_GRAB_CONFIRMED",
                    peak_candle_index=i - 2,
                    sweep_candle_index=i - 1,
                    trigger_candle_index=i,
                    sweep_price=outside_bar.low,
                    trigger_close=trigger.close,
                    provisional_stop=outside_bar.low,
                    pattern_detail={
                        "outside_bar_index": i - 1,
                        "swept_low": prior.low,
                        "broken_high": outside_bar.high,
                    },
                )

        # ── Pattern 6: Multi-Candle Step-by-Step Pullback ─────────────────────
        # Peak -> 2 or more consecutive lower lows -> Trigger closes above peak high
        matched_p6 = False
        for pullback_len in (4, 3, 2):
            if i >= pullback_len + 1:
                peak_idx = i - pullback_len - 1
                peak = candles[peak_idx]
                pullback_candles = [candles[peak_idx + k] for k in range(1, pullback_len + 1)]
                valid_step = True
                lowest_low = peak.low
                for k, pc in enumerate(pullback_candles):
                    prev_c = peak if k == 0 else pullback_candles[k - 1]
                    if pc.low >= prev_c.low:
                        valid_step = False
                        break
                    lowest_low = min(lowest_low, pc.low)

                if valid_step and trigger.close > peak.high:
                    matched_p6 = True
                    return ValidPullback1M(
                        pattern=PullbackPattern.MULTI_CANDLE_STEP,
                        direction="BULLISH",
                        is_valid=True,
                        reason=f"MULTI_CANDLE_{pullback_len}_STEP_PULLBACK_CONFIRMED",
                        peak_candle_index=peak_idx,
                        sweep_candle_index=i - 1,
                        trigger_candle_index=i,
                        sweep_price=lowest_low,
                        trigger_close=trigger.close,
                        provisional_stop=min(lowest_low, trigger.low),
                        pattern_detail={
                            "pullback_length": pullback_len,
                            "peak_index": peak_idx,
                            "lowest_low": lowest_low,
                        },
                    )

        # ── Pattern 4: Single Candle Order Block (SCOB) ──────────────────────
        # Single 1M candle sweeps previous candle's low AND body-closes above previous candle's high
        prev = candles[i - 1]
        if prev.complete:
            # Must not be an inside bar of an unresolved mother
            is_in = False
            if i >= 2 and is_inside_bar(prev, candles[i - 2]):
                is_in = True
            if not is_in and trigger.low < prev.low and trigger.close > prev.high:
                return ValidPullback1M(
                    pattern=PullbackPattern.SINGLE_CANDLE_OB,
                    direction="BULLISH",
                    is_valid=True,
                    reason="SCOB_SINGLE_CANDLE_SWEEP_AND_BODY_CLOSE",
                    peak_candle_index=i - 1,
                    sweep_candle_index=i,
                    trigger_candle_index=i,
                    sweep_price=trigger.low,
                    trigger_close=trigger.close,
                    provisional_stop=trigger.low,
                    pattern_detail={
                        "type": "SCOB",
                        "swept_low": prev.low,
                        "broken_high": prev.high,
                        "reversal_candle_index": i,
                    },
                )

        # ── Pattern 1: Classic 1-Candle Pullback ──────────────────────────────
        # Peak candle (i-2) -> Candle i-1 sweeps peak low -> Trigger candle i closes above peak high
        if i >= 2:
            peak = candles[i - 2]
            sweep_candle = candles[i - 1]
            if sweep_candle.low < peak.low and trigger.close > peak.high:
                stop_level = min(sweep_candle.low, trigger.low)
                return ValidPullback1M(
                    pattern=PullbackPattern.CLASSIC_1_CANDLE,
                    direction="BULLISH",
                    is_valid=True,
                    reason="CLASSIC_1_CANDLE_PULLBACK_CONFIRMED",
                    peak_candle_index=i - 2,
                    sweep_candle_index=i - 1,
                    trigger_candle_index=i,
                    sweep_price=sweep_candle.low,
                    trigger_close=trigger.close,
                    provisional_stop=stop_level,
                    pattern_detail={
                        "peak_index": i - 2,
                        "swept_low": peak.low,
                        "broken_high": peak.high,
                    },
                )

    return ValidPullback1M(
        PullbackPattern.NONE, "BULLISH", False, "NO_VALID_BULLISH_PULLBACK",
        -1, -1, -1, 0.0, 0.0, 0.0, {}
    )


def detect_bearish_pullback_1m(candles: Sequence[Candle], window: int = 15) -> ValidPullback1M:
    """
    Scan the last `window` completed 1M candles for any of the 6 Gwaidier Valid Bearish Pullbacks.
    Bearish Pullback Rule: Must take previous candle/mother high, and trigger must body-close below low.
    """
    if len(candles) < 2:
        return ValidPullback1M(
            PullbackPattern.NONE, "BEARISH", False, "INSUFFICIENT_CANDLES",
            -1, -1, -1, 0.0, 0.0, 0.0, {}
        )

    end_idx = len(candles) - 1
    start_idx = max(1, end_idx - window)

    for i in range(end_idx, start_idx - 1, -1):
        trigger = candles[i]
        if not trigger.complete:
            continue

        # ── Pattern 5: Inside Bar + Rejection Bearish ─────────────────────────
        if i >= 2:
            prev_bar = candles[i - 1]
            mother_res = find_mother_candle(candles, i - 1)
            if mother_res is not None:
                m_idx, mother = mother_res
                if trigger.high > mother.high and trigger.close < mother.low:
                    return ValidPullback1M(
                        pattern=PullbackPattern.INSIDE_BAR_REJECTION,
                        direction="BEARISH",
                        is_valid=True,
                        reason="INSIDE_BAR_BEARISH_REJECTION_EXPANSION",
                        peak_candle_index=m_idx,
                        sweep_candle_index=i,
                        trigger_candle_index=i,
                        sweep_price=trigger.high,
                        trigger_close=trigger.close,
                        provisional_stop=trigger.high,
                        pattern_detail={
                            "mother_candle_index": m_idx,
                            "inside_candle_index": i - 1,
                            "mother_high": mother.high,
                            "mother_low": mother.low,
                        },
                    )

        # ── Pattern 3: Inside Bar + Mother Candle High Taken Bearish ──────────
        if i >= 3:
            sweep_bar = candles[i - 1]
            inside_bar = candles[i - 2]
            mother_res = find_mother_candle(candles, i - 2)
            if mother_res is not None:
                m_idx, mother = mother_res
                if sweep_bar.high > mother.high and trigger.close < mother.low:
                    stop_level = max(sweep_bar.high, trigger.high)
                    return ValidPullback1M(
                        pattern=PullbackPattern.INSIDE_BAR_MOTHER_SWEEP,
                        direction="BEARISH",
                        is_valid=True,
                        reason="INSIDE_BAR_MOTHER_HIGH_SWEPT_CONFIRMED",
                        peak_candle_index=m_idx,
                        sweep_candle_index=i - 1,
                        trigger_candle_index=i,
                        sweep_price=sweep_bar.high,
                        trigger_close=trigger.close,
                        provisional_stop=stop_level,
                        pattern_detail={
                            "mother_candle_index": m_idx,
                            "inside_candle_index": i - 2,
                            "sweep_candle_index": i - 1,
                            "mother_high": mother.high,
                        },
                    )

        # ── Pattern 2: Outside Candle Grab Bearish ────────────────────────────
        if i >= 2:
            outside_bar = candles[i - 1]
            prior = candles[i - 2]
            if (outside_bar.high > prior.high and outside_bar.low < prior.low
                    and trigger.close < outside_bar.low):
                return ValidPullback1M(
                    pattern=PullbackPattern.OUTSIDE_CANDLE_GRAB,
                    direction="BEARISH",
                    is_valid=True,
                    reason="OUTSIDE_BAR_BEARISH_GRAB_CONFIRMED",
                    peak_candle_index=i - 2,
                    sweep_candle_index=i - 1,
                    trigger_candle_index=i,
                    sweep_price=outside_bar.high,
                    trigger_close=trigger.close,
                    provisional_stop=outside_bar.high,
                    pattern_detail={
                        "outside_bar_index": i - 1,
                        "swept_high": prior.high,
                        "broken_low": outside_bar.low,
                    },
                )

        # ── Pattern 6: Multi-Candle Step Pullback Bearish ─────────────────────
        for pullback_len in (4, 3, 2):
            if i >= pullback_len + 1:
                valley_idx = i - pullback_len - 1
                valley = candles[valley_idx]
                pullback_candles = [candles[valley_idx + k] for k in range(1, pullback_len + 1)]
                valid_step = True
                highest_high = valley.high
                for k, pc in enumerate(pullback_candles):
                    prev_c = valley if k == 0 else pullback_candles[k - 1]
                    if pc.high <= prev_c.high:
                        valid_step = False
                        break
                    highest_high = max(highest_high, pc.high)

                if valid_step and trigger.close < valley.low:
                    return ValidPullback1M(
                        pattern=PullbackPattern.MULTI_CANDLE_STEP,
                        direction="BEARISH",
                        is_valid=True,
                        reason=f"MULTI_CANDLE_{pullback_len}_STEP_BEARISH_PULLBACK",
                        peak_candle_index=valley_idx,
                        sweep_candle_index=i - 1,
                        trigger_candle_index=i,
                        sweep_price=highest_high,
                        trigger_close=trigger.close,
                        provisional_stop=max(highest_high, trigger.high),
                        pattern_detail={
                            "pullback_length": pullback_len,
                            "valley_index": valley_idx,
                            "highest_high": highest_high,
                        },
                    )

        # ── Pattern 4: Single Candle Order Block (SCOB) Bearish ───────────────
        prev = candles[i - 1]
        if prev.complete:
            is_in = False
            if i >= 2 and is_inside_bar(prev, candles[i - 2]):
                is_in = True
            if not is_in and trigger.high > prev.high and trigger.close < prev.low:
                return ValidPullback1M(
                    pattern=PullbackPattern.SINGLE_CANDLE_OB,
                    direction="BEARISH",
                    is_valid=True,
                    reason="SCOB_SINGLE_CANDLE_BEARISH_SWEEP_AND_CLOSE",
                    peak_candle_index=i - 1,
                    sweep_candle_index=i,
                    trigger_candle_index=i,
                    sweep_price=trigger.high,
                    trigger_close=trigger.close,
                    provisional_stop=trigger.high,
                    pattern_detail={
                        "type": "SCOB_BEARISH",
                        "swept_high": prev.high,
                        "broken_low": prev.low,
                    },
                )

        # ── Pattern 1: Classic 1-Candle Pullback Bearish ──────────────────────
        if i >= 2:
            valley = candles[i - 2]
            sweep_candle = candles[i - 1]
            if sweep_candle.high > valley.high and trigger.close < valley.low:
                stop_level = max(sweep_candle.high, trigger.high)
                return ValidPullback1M(
                    pattern=PullbackPattern.CLASSIC_1_CANDLE,
                    direction="BEARISH",
                    is_valid=True,
                    reason="CLASSIC_1_CANDLE_BEARISH_PULLBACK_CONFIRMED",
                    peak_candle_index=i - 2,
                    sweep_candle_index=i - 1,
                    trigger_candle_index=i,
                    sweep_price=sweep_candle.high,
                    trigger_close=trigger.close,
                    provisional_stop=stop_level,
                    pattern_detail={
                        "valley_index": i - 2,
                        "swept_high": valley.high,
                        "broken_low": valley.low,
                    },
                )

    return ValidPullback1M(
        PullbackPattern.NONE, "BEARISH", False, "NO_VALID_BEARISH_PULLBACK",
        -1, -1, -1, 0.0, 0.0, 0.0, {}
    )


# ═══════════════════════════════════════════════════════════════════════════
# HTF <-> LTF Institutional Bridge
# ═══════════════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class HTFLTFConfirmationResult:
    status: str  # CONFIRMED_SNIPER_ENTRY | WAIT_HTF_POI | WAIT_1M_PULLBACK | INVALID_RR
    direction: str  # BULLISH | BEARISH
    htf_bias: str
    htf_zone_type: str  # DISCOUNT | PREMIUM
    htf_poi_tapped: bool
    ltf_pullback: ValidPullback1M
    entry_price: float | None
    stop_loss: float | None
    target_1: float | None
    target_2: float | None
    target_3: float | None
    risk_points: float | None
    reward_points: float | None
    index_rr: float | None
    is_qualified: bool
    reason: str

    def as_dict(self) -> dict:
        return {
            "status": self.status,
            "direction": self.direction,
            "htf_bias": self.htf_bias,
            "htf_zone_type": self.htf_zone_type,
            "htf_poi_tapped": self.htf_poi_tapped,
            "ltf_pullback": self.ltf_pullback.as_dict(),
            "entry_price": self.entry_price,
            "stop_loss": self.stop_loss,
            "target_1": self.target_1,
            "target_2": self.target_2,
            "target_3": self.target_3,
            "risk_points": self.risk_points,
            "reward_points": self.reward_points,
            "index_rr": self.index_rr,
            "is_qualified": self.is_qualified,
            "reason": self.reason,
            "research_only": True,
            "orders_enabled": False,
        }


def evaluate_htf_ltf_bridge(
    *,
    symbol: str,
    direction: str,
    ltf_candles: Sequence[Candle],
    htf_bias: str,
    htf_equilibrium: float,
    htf_poi_zone: tuple[float, float] | None,  # (lower, upper) of 15M OB/FVG
    htf_target_pool: float,                   # 15M Opposing Liquidity Target
    htf_target_2: float | None = None,
    htf_target_3: float | None = None,
    min_points: float = 50.0,
    min_rr: float = 2.0,
    sl_buffer_pts: float = 1.0,
) -> HTFLTFConfirmationResult:
    """
    Complete Gwaidier HTF -> LTF -> HTF -> LTF Evaluation:
      1. Check HTF Bias alignment (direction == htf_bias).
      2. Check Dealing Range: Bullish must be in Discount (< Equilibrium), Bearish in Premium (> Equilibrium).
      3. Check HTF POI tap (current price has mitigated 15M OB/FVG zone).
      4. Detect 1M Valid Pullback (6 patterns).
      5. Calculate 1M Micro Stop-Loss (tight SL at sweep extreme + buffer).
      6. Connect to HTF External Liquidity Target (T1, T2, T3) and verify R:R >= min_rr & points >= min_points.
    """
    if direction not in ("BULLISH", "BEARISH"):
        raise ValueError("Invalid direction: must be BULLISH or BEARISH")
    if not ltf_candles:
        raise ValueError("Empty 1M candle list")

    curr_price = ltf_candles[-1].close

    # 1. HTF Bias Filter
    if direction != htf_bias:
        pb_empty = ValidPullback1M(PullbackPattern.NONE, direction, False, "HTF_BIAS_MISMATCH", -1, -1, -1, 0.0, 0.0, 0.0, {})
        return HTFLTFConfirmationResult(
            status="WAIT_HTF_BIAS", direction=direction, htf_bias=htf_bias,
            htf_zone_type="UNKNOWN", htf_poi_tapped=False, ltf_pullback=pb_empty,
            entry_price=None, stop_loss=None, target_1=None, target_2=None, target_3=None,
            risk_points=None, reward_points=None, index_rr=None, is_qualified=False,
            reason=f"Direction {direction} conflicts with HTF bias {htf_bias}",
        )

    # 2. Dealing Range (Premium vs Discount)
    is_discount = curr_price < htf_equilibrium
    zone_type = "DISCOUNT" if is_discount else "PREMIUM"
    if direction == "BULLISH" and not is_discount:
        pb_empty = ValidPullback1M(PullbackPattern.NONE, direction, False, "NOT_IN_DISCOUNT_ZONE", -1, -1, -1, 0.0, 0.0, 0.0, {})
        return HTFLTFConfirmationResult(
            status="WAIT_DISCOUNT_ZONE", direction=direction, htf_bias=htf_bias,
            htf_zone_type=zone_type, htf_poi_tapped=False, ltf_pullback=pb_empty,
            entry_price=None, stop_loss=None, target_1=None, target_2=None, target_3=None,
            risk_points=None, reward_points=None, index_rr=None, is_qualified=False,
            reason=f"Bullish setup rejected: Price {curr_price} is in PREMIUM (above Eq {htf_equilibrium})",
        )
    if direction == "BEARISH" and is_discount:
        pb_empty = ValidPullback1M(PullbackPattern.NONE, direction, False, "NOT_IN_PREMIUM_ZONE", -1, -1, -1, 0.0, 0.0, 0.0, {})
        return HTFLTFConfirmationResult(
            status="WAIT_PREMIUM_ZONE", direction=direction, htf_bias=htf_bias,
            htf_zone_type=zone_type, htf_poi_tapped=False, ltf_pullback=pb_empty,
            entry_price=None, stop_loss=None, target_1=None, target_2=None, target_3=None,
            risk_points=None, reward_points=None, index_rr=None, is_qualified=False,
            reason=f"Bearish setup rejected: Price {curr_price} is in DISCOUNT (below Eq {htf_equilibrium})",
        )

    # 3. HTF POI Tap Verification
    poi_tapped = False
    if htf_poi_zone is not None:
        poi_lo, poi_hi = htf_poi_zone
        # Checked if any of the recent 1M candles reached the POI zone
        for c in ltf_candles[-20:]:
            if c.low <= poi_hi and c.high >= poi_lo:
                poi_tapped = True
                break
    else:
        # If no explicit zone provided, allow sweep confirmation
        poi_tapped = True

    if not poi_tapped:
        pb_empty = ValidPullback1M(PullbackPattern.NONE, direction, False, "HTF_POI_NOT_TAPPED", -1, -1, -1, 0.0, 0.0, 0.0, {})
        return HTFLTFConfirmationResult(
            status="WAIT_HTF_POI", direction=direction, htf_bias=htf_bias,
            htf_zone_type=zone_type, htf_poi_tapped=False, ltf_pullback=pb_empty,
            entry_price=None, stop_loss=None, target_1=None, target_2=None, target_3=None,
            risk_points=None, reward_points=None, index_rr=None, is_qualified=False,
            reason="Price has not yet tapped 15M POI (OB/FVG zone)",
        )

    # 4. 1M Valid Pullback Detection
    if direction == "BULLISH":
        pb = detect_bullish_pullback_1m(ltf_candles)
    else:
        pb = detect_bearish_pullback_1m(ltf_candles)

    if not pb.is_valid:
        return HTFLTFConfirmationResult(
            status="WAIT_1M_PULLBACK", direction=direction, htf_bias=htf_bias,
            htf_zone_type=zone_type, htf_poi_tapped=True, ltf_pullback=pb,
            entry_price=None, stop_loss=None, target_1=None, target_2=None, target_3=None,
            risk_points=None, reward_points=None, index_rr=None, is_qualified=False,
            reason=f"1M Micro-confirmation pending: {pb.reason}",
        )

    # 5. Sniper Entry & Micro SL Calculation
    entry_price = pb.trigger_close
    if direction == "BULLISH":
        stop_loss = round(pb.provisional_stop - sl_buffer_pts, 2)
        risk_pts = round(entry_price - stop_loss, 2)
        reward_pts = round(htf_target_pool - entry_price, 2)
    else:
        stop_loss = round(pb.provisional_stop + sl_buffer_pts, 2)
        risk_pts = round(stop_loss - entry_price, 2)
        reward_pts = round(entry_price - htf_target_pool, 2)

    if risk_pts <= 0:
        return HTFLTFConfirmationResult(
            status="INVALID_STOP_LOSS", direction=direction, htf_bias=htf_bias,
            htf_zone_type=zone_type, htf_poi_tapped=True, ltf_pullback=pb,
            entry_price=entry_price, stop_loss=stop_loss, target_1=htf_target_pool,
            target_2=htf_target_2, target_3=htf_target_3, risk_points=risk_pts,
            reward_points=reward_pts, index_rr=None, is_qualified=False,
            reason=f"Calculated risk points non-positive: {risk_pts}",
        )

    index_rr = round(reward_pts / risk_pts, 2)

    # 6. Quality & Minimum Gates (Points & R:R)
    if reward_pts < min_points:
        return HTFLTFConfirmationResult(
            status="TARGET_ROOM_TOO_SMALL", direction=direction, htf_bias=htf_bias,
            htf_zone_type=zone_type, htf_poi_tapped=True, ltf_pullback=pb,
            entry_price=entry_price, stop_loss=stop_loss, target_1=htf_target_pool,
            target_2=htf_target_2, target_3=htf_target_3, risk_points=risk_pts,
            reward_points=reward_pts, index_rr=index_rr, is_qualified=False,
            reason=f"Target room {reward_pts} pts is below minimum {min_points} pts",
        )

    if index_rr < min_rr:
        return HTFLTFConfirmationResult(
            status="RR_BELOW_MINIMUM", direction=direction, htf_bias=htf_bias,
            htf_zone_type=zone_type, htf_poi_tapped=True, ltf_pullback=pb,
            entry_price=entry_price, stop_loss=stop_loss, target_1=htf_target_pool,
            target_2=htf_target_2, target_3=htf_target_3, risk_points=risk_pts,
            reward_points=reward_pts, index_rr=index_rr, is_qualified=False,
            reason=f"Planned R:R {index_rr} is below minimum {min_rr}:1",
        )

    # All gates passed: Confirmed Institutional Sniper Entry!
    return HTFLTFConfirmationResult(
        status="CONFIRMED_SNIPER_ENTRY",
        direction=direction,
        htf_bias=htf_bias,
        htf_zone_type=zone_type,
        htf_poi_tapped=True,
        ltf_pullback=pb,
        entry_price=entry_price,
        stop_loss=stop_loss,
        target_1=htf_target_pool,
        target_2=htf_target_2 or round(entry_price + (reward_pts * 1.5 if direction == "BULLISH" else -reward_pts * 1.5), 2),
        target_3=htf_target_3 or round(entry_price + (reward_pts * 2.0 if direction == "BULLISH" else -reward_pts * 2.0), 2),
        risk_points=risk_pts,
        reward_points=reward_pts,
        index_rr=index_rr,
        is_qualified=True,
        reason=f"1M {pb.pattern.value} confirmed inside 15M {zone_type} POI with R:R 1:{index_rr}",
    )
