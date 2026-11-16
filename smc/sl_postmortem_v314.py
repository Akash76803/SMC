"""Post-exit research diagnostics without retroactively changing the trade.

Future bars are used ONLY to assess what happened after hypothetical exit.
They never alter entry, stop, target or original research qualification.
"""
from __future__ import annotations
from .models import Candle


def review_stopped_setup(*, session: list[Candle], direction: str,
                         entry: float, stop: float, target: float,
                         exit_at: str) -> dict:
    indices = {c.timestamp.isoformat(): i for i, c in enumerate(session)}
    if exit_at not in indices or direction not in ("BULLISH", "BEARISH"):
        raise ValueError("INVALID_SL_POSTMORTEM")
    stop_index = indices[exit_at]
    after = session[stop_index+1:]
    bullish = direction == "BULLISH"
    touched_target_later = next(
        (c.timestamp.isoformat() for c in after
         if c.high >= target if bullish), None) if bullish else next(
        (c.timestamp.isoformat() for c in after if c.low <= target), None)
    # These extrema are look-ahead diagnostics, never tradable signals.
    post_best = (max(c.high for c in after) if bullish
                 else min(c.low for c in after)) if after else None
    return {
        "after_sl_bars": len(after),
        "target_touched_after_exit_at": touched_target_later,
        "max_favorable_points_after_sl_vs_entry": (
            (post_best-entry if bullish else entry-post_best)
            if post_best is not None else None),
        "does_not_prove_stop_was_too_tight": True,
        "lookahead_postmortem_only": True,
    }
