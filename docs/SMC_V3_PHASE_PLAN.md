# SMC Terminal V3 — Development Tracker

Repository: Akash76803/SMC. Work exclusively on `sandbox`; do not modify `main`.
Basis: SMC Trading Terminal V3.0 Design Plan (2026-11-15), user-provided SMC Lectures 3–9.

## Goal
Research/paper-only user-friendly NIFTY/SENSEX terminal. Explain M/W/D bias, liquidity targets, POIs, confirmation stages, invalidation, underlying index SL/TP, option quotes, and why WAIT/NO TRADE. No automatic live orders or promised success rate.

## Phases
- [x] P0A Inspect baseline architecture, structure_v2 and liquidity implementation
- [x] P0B Introduce V3 decision DTO, fail-closed reasoning and isolated unit tests (9 passed locally)
- [ ] P0C Run complete existing pytest suite on a checkout and record regression baseline; GitHub connector itself cannot execute code
- [~] P1 Initial opt-in `smc/structure_v3.py` hierarchy + wick/close structure events + candidate IDM and `tests/test_structure_v3.py` committed; inside-bar/full IDM source fixtures and local pytest verification still pending
- [ ] P2 External/internal liquidity and targets, eligibility and sweeps
- [ ] P3 Time/price, multi-timeframe bias and dealing ranges, conflict states
- [ ] P4 Standard and advanced blocks, FVG overlaps and POI selection
- [ ] P5 Versioned per-strategy setup state machines and expiry/invalidation
- [ ] P6 Conservative ATM/ITM option/quote gates, slippage/fees and paper engine
- [ ] P7 Desktop chart UI, setup inspector, scan, logs and journal
- [ ] P8 Walk-forward research, no-lookahead golden fixtures and out-of-sample evaluation

## First module
`smc/decision_v3.py` returns `DATA_BLOCKED`, `NO_TRADE`, `WAIT`, `RESEARCH_READY`.
Default parameters are unsafe-to-trade/fail-closed. Research-ready is **not** executable trading permission. Upstream data and options validation must be independently verified before their flags are set. `tests/test_decision_v3.py` tests the initial contract.

## Progress protocol
Each phase: confirm source method, define deterministic rule and counterexamples, add closed-candle golden tests, replay on real verified data, review failure reasons, then integrate into UI. Retain legacy strategies separately; never use current candle's future data. Do not merge into `main` until tests and explicit approval.
