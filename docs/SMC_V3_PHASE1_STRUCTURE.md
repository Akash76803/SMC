# Phase 1 — Structure V3 engineering notes

**Status:** initial opt-in research implementation. Existing `smc.structure_v2` and existing replay pathways remain unchanged.

- `three_candle_points`: strict 3-candle STH/STL, confirmed only on the right candle close (index i+1).
- `structure_hierarchy`: ITH higher than adjacent STHs; ITL lower than adjacent STLs. Confirm at right neighbor's confirmed timestamp, not the center pivot's time.
- `detect_hierarchical_structure`: close-confirmed breaks, wick sweep ≠ BOS, and later close must exceed stored wick extreme. Tiers independently maintain provisional protected pivots; a protected pivot may be a proxy and is not yet validated against full lecture 3 IDM rules. A candle breaking two competing bounds is ignored.
- `detect_idm_touches`: candidate IDM *proxy*, nearest opposite STH/STL before a confirmed extreme and first subsequent touch, no reused future candle data. DO NOT use candidate IDMs as validated entry signals.
- **Limits:** not full 6-valid/6-invalid pullback patterns; no comprehensive inside-bar collapsing; no HTF alignment; no option trade recommendations; no broker execution; no profitability claim. Equal-highs rejected as strict pivots.
- **Acceptance remaining:** source-derived manual fixture catalog, corpus replay comparisons, old vs V3 diagnostics, full test suite, and integrating into decision engine only after review.
- To test: `python -m pytest -q tests/test_structure_v3.py`.
