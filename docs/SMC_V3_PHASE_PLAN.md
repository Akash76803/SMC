# SMC Terminal V3 — Development Tracker

Repository: Akash76803/SMC. Work exclusively on `sandbox`; do not modify `main`.
Basis: SMC Trading Terminal V3.0 Design Plan (2026-11-15), user-provided SMC Lectures 3–9.

## Goal
Research/paper-only user-friendly NIFTY/SENSEX terminal. Explain M/W/D bias, liquidity targets, POIs, confirmation stages, invalidation, underlying index SL/TP, option quotes, and why WAIT/NO TRADE. No automatic live orders or promised success rate.

## Phases
- [x] P0A Inspect baseline architecture, structure_v2 and liquidity implementation
- [x] P0B Introduce V3 decision DTO, fail-closed reasoning and isolated unit tests (9 passed locally)
- [x] P0C User confirmed 187/187 regression tests passed locally (V3.2 baseline, before V3.3 changes)
- [~] P1 Initial opt-in `smc/structure_v3.py` hierarchy + wick/close structure events + candidate IDM and `tests/test_structure_v3.py` committed; inside-bar/full IDM source fixtures and local pytest verification still pending
- [~] P2 Existing liquidity detection + new V3.4 unconsumed opposing target selection and index RR gates committed; target freshness/session completeness replay QA pending
- [~] P3 Initial opt-in Monthly/Weekly/Daily confirmed external-break bias, dealing range EQ/premium/discount, strict conflict/neutral handling and sweep-time causal HTF adapter committed; calendar/close timestamp adapters and historical validation pending
- [~] P4 Initial V3.4 OB/FVG overlap candidate scanner and invalidation/retest diagnostics committed; full HTF POI validation, advanced OB and real-data research pending
- [~] P5 V3.5 opt-in explainable reversal-only unified orchestrator committed; true MSS/HTF-POI and full continuation strategy gates remain pending
- [ ] P6 Conservative ATM/ITM option/quote gates, slippage/fees and paper engine
- [ ] P7 Desktop chart UI, setup inspector, scan, logs and journal
- [ ] P8 Walk-forward research, no-lookahead golden fixtures and out-of-sample evaluation

## First module
`smc/decision_v3.py` returns `DATA_BLOCKED`, `NO_TRADE`, `WAIT`, `RESEARCH_READY`.
Default parameters are unsafe-to-trade/fail-closed. Research-ready is **not** executable trading permission. Upstream data and options validation must be independently verified before their flags are set. `tests/test_decision_v3.py` tests the initial contract.

## Progress protocol
Each phase: confirm source method, define deterministic rule and counterexamples, add closed-candle golden tests, replay on real verified data, review failure reasons, then integrate into UI. Retain legacy strategies separately; never use current candle's future data. Do not merge into `main` until tests and explicit approval.

## V3 Premium Target Feasibility Policy — 2026-11-15
- New research gate: minimum **15 option-premium points gross target**, minimum **3.0 cost-adjusted reward:risk**.
- Computation: net_reward = target_points - round_trip_cost_per_unit; net_risk = stop_points + round_trip_cost_per_unit; net_rr = net_reward/net_risk.
- Default observed-quote CLI: `python -m smc.phase6_cli --signals phase5_signals.csv --quotes data/nifty_option_quotes.csv --target 15 --stop 3 --cost-per-unit 1`.
- A 15 point target / 5 point stop is gross 3R but net less than 3R with positive costs and is rejected. The 15/3/1 example gives 14/4 = 3.5R **hypothetical**.
- `smc/premium_feasibility_v3.py` is separately testable, and `smc/phase6_cli.py` invokes it before observed quote replay. Existing `Settings` defaults and `phase6_ohlc_cli` remain unchanged for reproducible legacy research; OHLC does not provide observed bid/ask and must not claim verified net 3R.
- This gate checks only configured bracket arithmetic, NOT market feasibility (liquidity, actual attainable target, slippage, fills, or strategy profitability). It may be strict for real market conditions. No live order execution.

## V3.1 Setup Confirmation Orchestrator — 2026-11-15
- New opt-in `smc/setup_confirmation_v3.py` with explicit `REVERSAL` and `CONTINUATION` stage sequences. Each `PASS` requires source ID + offset-aware confirmation timestamp.
- `assess_setup` combines stage evidence, stale-data gate, underlying index bracket, verified option-data flag and 15+ gross premium-point / >=3 cost-adjusted option R:R policy into explainable `DATA_BLOCKED`, `WAIT`, `NO_TRADE`, `RESEARCH_READY` responses.
- Missing evidence defaults to WAIT, failed evidence / setup expiry produce NO_TRADE, and future evidence is rejected. JSON-ready stage progress and next confirmation provided for a future frontend.
- `tests/test_setup_confirmation_v3.py`: 15 isolated tests passed in an independent local harness, **repository-wide regression still requires user's Windows checkout**.
- This is a DTO/orchestrator, NOT a complete automatic setup detector. Stage evidence and quote health remain supplied by separately verified upstream modules; no signal is emitted by default; no live execution.
- Test: `python -m pytest -q tests/test_setup_confirmation_v3.py` then `python -m pytest -q`.

## V3.2 Automatic LTF Evidence Adapter — 2026-11-15
- New opt-in `smc/evidence_adapter_v3.py`: takes independently quality-gated, fully completed 1-minute LTF candles and uses existing `phase2.scan` plus `entry_v1.evaluate_entry` to produce a traceable V3 reversal setup assessment.
- Each real closed-candle liquidity sweep can be marked PASS with timestamp/source. An internal CHoCH is **not** automatically a full ICT MSS; it remains PENDING with a candidate source reference until verified. A three-candle FVG is not proof of displacement; it also remains PENDING. A closed-candle FVG retest/rejection may be marked PASS only when entry_v1 returns the causal retest event. All HTF bias/HTF POI evidence requires separate, independently checked inputs; no HTF claims are derived from LTF.
- Disqualifying entry expiry/invalidation is mapped to FAIL. A chosen source event is the latest sweep, never selected using hindsight performance. No candidate returns WAIT; missing/incomplete candles or no independently verified feed health returns DATA_BLOCKED.
- Separate bracket/premium/verified option quote inputs are never fabricated. No live signal, P&L, or executable advice. Adapter is NOT wired to replay/live execution yet. It provides explainable DTOs for upcoming UI.
- `tests/test_evidence_adapter_v3.py` adds 11 tests. An additional HTF-prior-to-sweep test was added to `tests/test_setup_confirmation_v3.py`. These repository tests require local run; GitHub connector cannot execute code and this environment cannot reach GitHub via network.
- Validate with `python -m pytest -q tests/test_evidence_adapter_v3.py tests/test_setup_confirmation_v3.py` then `python -m pytest -q`.

## V3.3 HTF Bias + Dealing Range — 2026-11-16
- `smc/htf_context_v3.py` computes independent Monthly/Weekly/Daily **confirmed external structure-break proxy** (using existing `structure_v2.detect_structure`), or NEUTRAL if no recent verified event. Bias agreement is strict: all three same direction = aligned; conflicting directions = CONFLICT; missing/neutral data = UNVERIFIED. Neither conflict nor neutral means reversal.
- `confirmed_pivots` defines a preliminary dealing range from the latest confirmed HIGH and LOW. Midpoint EQ = (high + low)/2; PREMIUM/DISCOUNT labels describe the last close position versus EQ, not guaranteed prices or target fills. No HTF_POI pass is inferred from range alone.
- `bias_stage` converts verified aligned context to `HTF_BIAS=PASS` with causal evidence/source timestamps. Other cases remain PENDING.
- `adapt_reversal_with_htf` links this HTF stage into the V3.2 reversal adapter. For any selected liquidity sweep, it filters all M/W/D input candles to those closing **no later than the sweep candle**, preventing future HTF confirmation being assigned retroactively. Selected candidate direction is provided explicitly by V3.2.
- Assumption: all input HTF timestamps are the actual **candle CLOSE**, not broker start timestamps; all candles must be complete and ordered. Unsupported market calendar, stale datasets, timeframe aggregation, market-session validation and complete Lecture 9 time/price rules remain unfinished. Do not drive live execution.
- `tests/test_htf_context_v3.py` adds 14 tests for alignment, bearish/bullish, conflict, range, neutral, invalid input, future data, and integration. Run `python -m pytest -q tests/test_htf_context_v3.py tests/test_evidence_adapter_v3.py`, then full `python -m pytest -q`; GitHub connector cannot execute full suite. Previous local verified baseline = 187 tests before this milestone.

## V3.4 Liquidity Target & POI Candidate Research — 2026-11-16
- `smc/poi_liquidity_v3.py` introduces `review_liquidity_target`, `review_ob_fvg_poi`, `index_bracket_from_target` and `candidate_poi_stage` with serializable, traceable research output.
- Nearest eligible opposing liquidity (BSL/EQH/PDH for bullish, SSL/EQL/PDL for bearish) only when unconsumed by any observed sweep/run or prior wick through the level. PDH/PDL may become active on the session's first candle; first-bar touches consume it. Missing target => WAIT, insufficient index target room or RR => NO_TRADE. Required historical completeness and session calendar must be validated upstream.
- Index gates are still NIFTY >=50 points, SENSEX >=100 points, underlying index RR >=2. These gates are **separate** from option target >=15 *premium points* and net premium RR >=3. No underlying-points-to-option-premium inference.
- `review_ob_fvg_poi` identifies an overlap of existing preliminary standard OB and directional 3-candle FVG, with close invalidation and later retest proxy. Candidate overlaps **never** set `HTF_POI=PASS` on their own; the stage remains PENDING until HTF origin and mitigation/quality rules are separately validated. Institutional activity is not observable from OHLC.
- No live orders, no guaranteed draw-on-liquidity and no automatic order execution. This opt-in module is not yet wired into complete V3.3->V3.2 detection chain.
- `tests/test_poi_liquidity_v3.py` includes tests for prior level consumption, first-bar PDH, target room/RR, bear/bull levels, future/incomplete candles, positive POI overlap and fail-closed stage. **GitHub connector cannot execute local tests**; user should run `python -m pytest -q tests/test_poi_liquidity_v3.py` and then `python -m pytest -q`. Previous user-verified baseline: 201 passed.

## V3.5 Unified Reversal Setup Assessment — 2026-11-16
- `smc/unified_setup_v3.py` introduces `evaluate_unified_reversal` combining V3.2 LTF candidate, V3.3 M/W/D structure bias, V3.4 unconsumed liquidity target and preliminary OB/FVG POI with V3.1 setup stages.
- HTF bars are filtered to close no later than the selected LTF **sweep**; POI/target are computed on a prefix ending at the selected entry/transition candle. This prevents retroactively using a future pivot/HTF bias/liquidity level to justify a historical setup.
- Index brackets are constructed only when a closed-candle retest supplies entry and stop and the opposing-liquidity review approves >=50 NIFTY / >=100 SENSEX index target and >=2 index R:R. Insufficient index target/RR is surfaced as `NO_TRADE` and a precise reason, never silently skipped.
- `HTF_POI` remains `PENDING` when an OB/FVG overlap is merely a research candidate. CHoCH and displacement proxies likewise remain pending. The pipeline intentionally cannot produce `RESEARCH_READY` with current unverified upstream evidence. Per-contract premium target >=15 pts, net premium R:R >=3 and quote quality remain separate gates, not inferred from index price moves.
- `UnifiedSetupReport.as_dict()` contains HTF context, stage reasons, selected entry transition, opposing liquidity details, OB/FVG diagnostics, and independent index / premium research metrics. No live order pathway, no execution permission.
- `tests/test_unified_setup_v3.py` adds **13 unverified-at-commit test cases** focused on fail-closed behavior, unverified HTF/POI, unsupported instruments, future candles, serialization and option gates. Github actions here cannot run tests. Prior user-verified complete suite: **216 passed**.
- Next: real verified historical feed end-to-end, strict session/calendar data quality, full POI/MSS/IDM rules, option quote/volatility/delta feasibility, golden replay fixtures; desktop inspector later.
- Local: `python -m pytest -q tests/test_unified_setup_v3.py`, then `python -m pytest -q`.
