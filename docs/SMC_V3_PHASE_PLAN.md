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
- [~] P3 V3.8 verified-complete regular-session 1m->5m/15m/1h/daily aggregate research added; calendar verified weekly/monthly boundaries, HTF historical validation and bias stability pending
- [~] P4 Initial V3.4 OB/FVG overlap candidate scanner and invalidation/retest diagnostics committed; full HTF POI validation, advanced OB and real-data research pending
- [~] P5 V3.5 opt-in explainable reversal-only unified orchestrator committed; true MSS/HTF-POI and full continuation strategy gates remain pending
- [ ] P6 Conservative ATM/ITM option/quote gates, slippage/fees and paper engine
- [ ] P7 Desktop chart UI, setup inspector, scan, logs and journal
- [~] P8 V3.7 opt-in causal historical index-only diagnostic replay plus CSV CLI and synthetic tests committed; real verified Angel One replay, walk-forward and out-of-sample evaluation pending

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
- `tests/test_unified_setup_v3.py` adds **13 unverified-at-commit test cases** focused on fail-closed behavior, unverified HTF/POI, unsupported instruments, future candles, serialization and option gates. Github actions here cannot run tests. Prior user-verified complete suite: **216 passed**; user subsequently verified **229 passed** after V3.5.
- Next: real verified historical feed end-to-end, strict session/calendar data quality, full POI/MSS/IDM rules, option quote/volatility/delta feasibility, golden replay fixtures; desktop inspector later.
- Local: `python -m pytest -q tests/test_unified_setup_v3.py`, then `python -m pytest -q`.

## V3.6 Multi-target and RR Intelligence — 2026-11-16
- Added `smc/multi_target_v3.py` with `rank_liquidity_targets` and `evaluate_premium_scenarios`.
- Targets T1/T2/T3 rank **distinct, unconsumed, causally eligible** opposing index liquidity levels by distance. All eligible levels may be considered for a separately labeled `maximum_observed_index_rr`; this is the farthest eligible level **in the current finite data snapshot**, not a guaranteed move or true market maximum. Extra ranks can be hidden without affecting the farthest observed estimate.
- The conservative gate is the **nearest** eligible target. If T1 fails minimum NIFTY=50/SENSEX=100 underlying index points or index R:R >=2, the setup is NO_TRADE, even if a farther T2/T3 would exceed requirements. No skipping near liquidity to manufacture an attractive R:R.
- Option premium scenarios are supplied **independently**, never inferred from index points or delta alone. Each scenario evaluates gross premium target >=15 points, net R:R >=3 after estimated round-trip per-unit cost. Missing option scenarios => `PREMIUM_TARGETS_UNVERIFIED`. A user-provided premium bracket in V3.5 appears with `SCENARIOS_ONLY_NOT_VERIFIED`; it is not a verified fill, quote or forecast.
- The V3.5 JSON now includes optional `multi_targets` and `premium_ladder` keys; missing entry/SL produces null multi-targets and never fabricates an index or premium maximum.
- The upstream HTF POI/MSS and quote validations remain unresolved; no executable READY signal is authorized.
- `tests/test_multi_target_v3.py` adds **17 tests**, plus three integration tests to `tests/test_unified_setup_v3.py`; local regression required. Last user-verified baseline was **229 tests passed** before V3.6, new expected count 249 if all collected.
- Test commands: `python -m pytest -q tests/test_multi_target_v3.py tests/test_unified_setup_v3.py` and `python -m pytest -q`.

## V3.7 Historical Replay Diagnostics — 2026-11-16
- New opt-in `smc/replay_v3.py`: evaluates V3.5 unified reversal **once per closed-candle prefix** and reports per-bar WAIT/NO_TRADE/DATA_BLOCKED reasoning. Terminal observations only are recorded once per transition index (not one trade per WAIT candle); research-only and never an order signal.
- When an already qualified *index-only* bracket and T1/T2/T3 were present at the confirmation candle, `evaluate_level_outcomes` examines candles strictly AFTER confirmation. Each level independently becomes HIT, STOP_FIRST, AMBIGUOUS_SAME_BAR, DATA_GAP, TIME_EXIT or NO_FUTURE_BARS. These are historical index high/low touches, **not simulated fills, executable trades, or option profits**.
- Safety: future HTF candle closure and post-decision target creation are disallowed by V3.5; same-bar SL/target is labeled AMBIGUOUS, not a win. Unexpected timestamp gaps fail closed with DATA_GAP. Replay remains diagnostic even if a non-executable WAIT report has a hypothetical bracket; do not interpret the number of target touches as profitable trade count.
- `smc/replay_v3_cli.py` reads the existing `csv_data.read_candles_csv` format, runs `audit_1m` and rejects unsafe 1m feeds, writes serializable JSON. Example:
  `python -m smc.replay_v3_cli --ltf data/nifty_1m.csv --symbol NIFTY --out results/v37.json`
- Optional `--monthly/--weekly/--daily` require independently aggregated, actual CLOSE-timestamp completed candles. Broker ONE_HOUR timestamps are known to be START-stamped; do not confuse START with CLOSE or treat 1h as Monthly/Weekly/Daily. Missing HTF remains UNVERIFIED.
- V3.7 does not estimate option bid-ask, delta, theta, volatility, transaction expenses or net premium P&L; no confidence/profitability claim is possible. Full M/W/D session-calendar validation, observed-options replay, and walk-forward evaluation are still pending.
- `tests/test_replay_v3.py` adds 15 synthetic tests. GitHub connector cannot execute the repository test suite; previous user-confirmed baseline = **249 passed**. Run `python -m pytest -q tests/test_replay_v3.py` then `python -m pytest -q`; expected 264 if tests collect and pass.

## V3.7 Data quality fix — 2026-11-16
- User verified **264/264 full tests passed** locally. Running `replay_v3_cli` with Angel One 1-minute CSV then correctly failed with `LTF_DATA_QUALITY_FAILED: TERMINAL_1530_UNCLASSIFIED`.
- CLI now has opt-in `--drop-terminal-1530`, calling existing `data_quality.drop_terminal_1530` BEFORE the strict `audit_1m`. It drops only an isolated same-day 15:30 record directly after a 15:15 close; it does not impute missing 15:16–15:29 data.
- Every other remaining issue (including `INTRADAY_GAP`, `SESSION_START_UNVERIFIED`) still blocks replay. The default without flag remains unchanged and fail-closed. The CLI reports number of excluded terminal records and does not overwrite input CSV.
- Added `tests/test_replay_v3_cli.py` with 5 regression tests for safe opt-in exclusion and preservation of real-gap failure. Run `python -m pytest -q tests/test_replay_v3_cli.py` then full `python -m pytest -q`; new suite count expected 269 if tests pass.
- Example: `python -m smc.replay_v3_cli --ltf "data/nifty_1m.csv" --symbol NIFTY --drop-terminal-1530 --out "results/v37_nifty.json"`.
- This fix does not guarantee that any given historical CSV is safe: multi-day feeds with real gaps remain rejected. For long datasets, replay can be computationally expensive because it recalculates a prefix for each closed bar.

## V3.8 Initial HTF Aggregation + Rejection Diagnostics — 2026-11-16
- New `smc/htf_aggregation_v3.py` verifies strict 1-minute data quality and **complete 360 one-minute regular sessions** (09:16..15:15 IST). It constructs candle-CLOSE timestamps for 5m (72/session), 15m (24/session), 1h (6/session), daily (1/session). No incomplete session can be silently promoted to confirmed Daily.
- Weekly/Monthly outputs default EMPTY even with a complete day. They may be produced only with externally verified period-end session dates supplied by a trusted calendar source; OHLC alone cannot establish the real last trading day of a week/month, or absent sessions. The aggregation helper does not itself prove calendar completeness or holidays. Special sessions need a separate, audited model.
- Optional CLI `--aggregate-regular-htf` writes `htf_aggregation` counts to the JSON and supplies **daily** bars to the existing V3.3 bias engine. 5m/15m/1h are included in diagnostics only, not secretly substituted for M/W/D inputs. Without separate weekly/monthly data, strict HTF alignment remains UNVERIFIED.
- Replay terminal observations now include `diagnostics`: entry state/reason, sweep index, pending stages, HTF alignment, nearest candidate target level/kind/points/index RR and target rejection reason. A failed index target does not become a backtest trade. Currently `index_entry/index_stop` fields are present only for approved diagnostic brackets; raw rejected candidate entry/stop requires a follow-on adapter change.
- Added 11 unit tests for HTF aggregation and two replay diagnostics serialization tests. **Last user-verified baseline: 269 passed**; expected 282 tests, subject to local execution. No claim of market predictive accuracy.
- Test: `python -m pytest -q tests/test_htf_aggregation_v3.py tests/test_replay_v3.py tests/test_replay_v3_cli.py` then `python -m pytest -q`.
- Replay: `python -m smc.replay_v3_cli --ltf "data/nifty_1m.csv" --symbol NIFTY --drop-terminal-1530 --aggregate-regular-htf --out "results/v38_nifty.json"`. No live execution or option P&L.
- Remaining V3.8 tasks: broker-session calendar validation/verified market closures, independently sourced complete multiweek/month history, full M/W/D bias integration, raw rejected entry/SL diagnostics and actual NIFTY/SENSEX multi-session replay.

## V3.8 JSON Serialization Hotfix — 2026-11-16
- User reported 282 passing full tests and a successful NIFTY research replay, but `ConvertFrom-Json` raised `Invalid JSON primitive: n`.
- Confirmed code wrote literal backslash-n after the completed JSON object. Replaced with a dedicated `write_replay_json` that appends a genuine newline, and added a strict JSON regression test.
- Prior full-suite user-confirmed count: 282; one new test should raise it to 283 after user validation. No replay metrics changed by this fix.

## V3.8 Replay Reason Separation — 2026-11-16
- User verified **283/283 regression tests passed** and JSON is parseable. On the 2026-11-11 NIFTY regular session, aggregation yielded 72x5m, 24x15m, 6x1h, 1 daily, 0 weekly/monthly; 345 research-only prefixes, 12 terminal observations, 0 qualified hypothetical brackets.
- The replay showed `reason=MSS_CONFIRMED` but underlying entry state `EXPIRED`, `entry_reason=CHOCH_TIMEOUT`. This is a distinction, not evidence MSS passed: `MSS_CONFIRMED` names the FAILED stage; `CHOCH_TIMEOUT` names the concrete terminal trigger.
- Added explicit `terminal_cause` to each terminal observation and separate `terminal_cause_counts` to summary. The existing `reason` and `reason_counts` remain unchanged as **decision-stage reasons per evaluated candle**, preserving downstream compatibility. Diagnostics also distinguish `decision_stage_reason` from `terminal_cause`. Counts of terminal causes are per distinct terminal observation, not 345 evaluations.
- Two tests added; prior locally verified baseline 283; expect 285 if new tests pass. Run `python -m pytest -q tests/test_replay_v3.py` and `python -m pytest -q`.
- Real multiweek/month HTF history and protected-structure MSS/displacement remain unverified; do not loosen gates just to manufacture index brackets.

## V3.9B — Three backend gates (2026-11-16)

The following **research-only** components were added on `sandbox`:

1. **HTF alignment gate:** `smc/continuation_validation_v3.py` evaluates the existing Monthly/Weekly/Daily `HTFContext` at the actual confirmation close. Missing, conflicting or later-closing HTF candles cannot authorize trade readiness.
2. **Entry and protective-stop reference:** the candle-close at BOS/pullback reclaim is the hypothetical **entry reference**, and the pullback high/low is the **unverified stop reference**. Invalid direction or stop geometry rejects the case; do not confuse it with a verified protected swing or executable bracket.
3. **Liquidity target and index R:R gate:** reuses `review_liquidity_target` with only as-of-close eligible index levels and completed 1m prefix. Uses NIFTY >= 50 points / SENSEX >= 100 points and minimum index R:R 2. Too-small targets become NO_TRADE; missing target stays WAIT. Even with index room and aligned HTF, `PROTECTED_STRUCTURE`, `HTF_POI`, and `OPTION_QUOTES_GREEKS` remain pending; no executable index bracket or premium P&L is generated.

**Session-isolated CLI**:
```powershell
python -m smc.continuation_validation_cli --ltf "results/v38_sessions/nifty_2026-11-02.csv" --symbol NIFTY --out "results/v39b_2026-11-02.json"
```
Use optional `--monthly`, `--weekly`, and `--daily` only with independently verified **CLOSE-stamped** HTF files. Do not pass the broker 1H START-stamped CSV as an HTF close file. No option fills or order execution.

Tests added: `tests/test_continuation_validation_v3.py`; run `python -m pytest -q` in the repository venv. These gates **do not** change the old V3.8 reversal replay metrics or the V3.9A desktop marker counts. Next: verified POI/protected structure, then real option quote matching and UI decision inspector integration.

## V3.9C — Continuation research enrichment

- `smc/continuation_evidence_v3.py`: three **fail-closed** views: (a) candidate opposite confirmed pivot available before BOS, explicitly **not verified protected structure**; (b) candidate LTF OB/FVG confluence retested by the setup close, explicitly **not verified HTF POI**; (c) `rank_liquidity_targets` T1/T2/T3 from completed as-of-setup candles, **never a guaranteed market target**.
- `smc/continuation_validation_cli.py` now emits `evidence_review.protected_structure`, `evidence_review.poi` and `evidence_review.index_targets`, without changing `status` or `qualified_trades=0` from V3.9B.
- Regression cases `tests/test_continuation_evidence_v3.py` cover zero lookahead, wrong dates, incomplete bars, invalid indices and no executable trade claims.
- Use the previously saved regular session CSV:
```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m smc.continuation_validation_cli --ltf "results\v38_sessions\nifty_2026-11-02.csv" --symbol NIFTY --out "results\v39c_nifty_02nov.json"
```
- The review fields are diagnostic. Genuine protected-swing confirmation, market-calendar-verified M/W/D bias, HTF POI and option chain/Greeks are still absent.

## V3.10 — Complete batch: MTF Trend + Historical Liquidity + Alignment

This is an **opt-in research context report**, not a change to executable signals.

1. `smc/market_context_v310.py` creates **only fully closed** 5-minute,
   15-minute and 1-hour bars from audited 1-minute candles. Every source
   session starts at 09:16 IST and is continuous; a partial current session
   does not create a daily candle. 1h/15m/5m trend snapshots expose confirmed
   external BOS/CHoCH, directional bias and descriptive HH-HL / LH-LL / MIXED.
   If a timeframe has insufficient evidence, the alignment is UNVERIFIED.
2. `smc/context_liquidity_v310.py` reports observed previous complete
   session high/low, causal confirmed swing/equal-high/equal-low liquidity
   candidates and optional explicitly **calendar-marked** completed week
   high/low. Unverified previous observation is *not* labeled exchange
   previous trading day. No PWH/PWL is fed to executable target validation:
   independently verified complete week history is not yet available.
   `verified_predecessors` is an explicit caller-certified input, never
   auto-enabled. Historical unconsumed-liquidity eligibility remains the
   earlier `review_liquidity_target` gate.
3. `smc/continuation_validation_cli.py` accepts optional
   `--context-ltf` containing complete audited 1m historical sessions,
   requires the current session's source to match identically, and evaluates
   each setup at its own confirmation close. Each observation now includes
   `intraday_mtf`, `intraday_mtf_gate`, `context_liquidity` and
   the existing V3.9C `evidence_review`. No substitute for verified
   Monthly/Weekly/Daily alignment; old `qualified_trades=0` policy remains.

### Try on the user's validated historical CSV

```powershell
cd E:\Project\SMC
git switch sandbox
git pull --ff-only origin sandbox
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m smc.continuation_validation_cli `
  --ltf "results\v38_sessions\nifty_2026-11-02.csv" `
  --context-ltf "data\nifty_multi_regular_1m.csv" `
  --symbol NIFTY `
  --out "results\v310_nifty_02nov.json"
$r = Get-Content "results\v310_nifty_02nov.json" -Raw | ConvertFrom-Json
$r.status_counts
$r.observations | Select-Object -First 2 |
  ForEach-Object { $_.intraday_mtf; $_.context_liquidity }
```

### Guardrails and future work

- 1H START-timestamp broker CSV cannot be used as close-stamped M/W/D input.
- More history is required to verify a genuine month-long rally and real
  calendar-complete weekly/monthly levels.
- The MTF view is a descriptive closed-candle structural proxy, not proof of
  future movement; absent liquidity remains absent.
- Existing entry rules and safety thresholds remain untouched.
- New tests `tests/test_market_context_v310.py` cover close-time buckets,
  no-lookahead, data gaps, calendar markers, and session matching.

## Angel One real market-data smoke test — read-only

Added `smc/angel_live_smoke_cli.py` for authenticated **live REST LTP**.
This is different from mocked CI tests and from end-to-end streaming.
SmartAPI credentials and TOTP remain in the operator's Windows console.
Never share API key, MPIN, login session or current TOTP in chats, GitHub,
test reports, environment dumps or screenshots.

```powershell
cd E:\Project\SMC
git switch sandbox
git pull --ff-only origin sandbox
.\.venv\Scripts\python.exe -m pip install -e ".[angel,dev]"
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m smc.angel_live_smoke_cli `
  --symbol NIFTY `
  --out "results\angel_live_nifty_smoke.json"
```

Index token is resolved from official instrument master by default,
or pass `--master-file` if the master is available offline. The code
makes one `getMarketData("LTP", ...)` request, validates response status,
matching exchange/token and finite positive LTP, then logs out. The output
contains no account or credential data. A successful HTTP response
does **not** prove a fresh exchange tick: `feed_freshness_verified=false`.
Historical candle data, option bid/ask, Greeks, entry, risk calculations,
paper-trade execution, WebSocket streaming and trade authorization remain
outside this smoke test.

CI tests in `tests/test_angel_live_smoke_cli.py` mock the SDK boundary:
no real market network or user account is used. An actual Angel One
authenticated response requires a human to run the command locally
with their own credentials; never claim otherwise.
