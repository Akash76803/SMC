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

## V3 Premium Target Feasibility Policy — 2026-11-15
- New research gate: minimum **15 option-premium points gross target**, minimum **3.0 cost-adjusted reward:risk**.
- Computation: net_reward = target_points - round_trip_cost_per_unit; net_risk = stop_points + round_trip_cost_per_unit; net_rr = net_reward/net_risk.
- Default observed-quote CLI: `python -m smc.phase6_cli --signals phase5_signals.csv --quotes data/nifty_option_quotes.csv --target 15 --stop 3 --cost-per-unit 1`.
- A 15 point target / 5 point stop is gross 3R but net less than 3R with positive costs and is rejected. The 15/3/1 example gives 14/4 = 3.5R **hypothetical**.
- `smc/premium_feasibility_v3.py` is separately testable, and `smc/phase6_cli.py` invokes it before observed quote replay. Existing `Settings` defaults and `phase6_ohlc_cli` remain unchanged for reproducible legacy research; OHLC does not provide observed bid/ask and must not claim verified net 3R.
- This gate checks only configured bracket arithmetic, NOT market feasibility (liquidity, actual attainable target, slippage, fills, or strategy profitability). It may be strict for real market conditions. No live order execution.
