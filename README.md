# SMC Trading Terminal — Sandbox MVP

**Branch policy:** `main` = production baseline; `sandbox` = development/testing. Never merge without local tests and explicit approval.

## Implemented (phase 1)
- Closed-candle confirmed fractal swings and deterministic structure events (BOS / CHoCH).
- Three-candle FVG, ATR(14), liquidity sweep detection, basic order-block candidate marking.
- Strict index target room: SENSEX >=100 pts; NIFTY >=50 pts; index RR >=2.
- ATM / nearest one-step ITM option candidates; delta, ATR, option spread and *net option RR* gates.
- Safe NO TRADE on stale/incomplete feeds or missing Greeks. JSON CLI and unit tests.
- **No broker login, no live feed, no auto-execution, no guarantee of profitability.**
- Six PDF entry schemes are **not** implemented yet. The core intentionally never invents confirmations.

## Local setup (Windows PowerShell)
```powershell
git clone https://github.com/Akash76803/SMC.git
cd SMC
git switch sandbox
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
python -m pytest -q
python -m smc.cli --demo
```
If `py` is unavailable, install Python 3.11+ and enable the Python launcher. Run `python --version` to verify.

## Engine integration
`smc.engine.analyze(candles)` computes *confirmed* structures. `smc.risk.validate_index_setup` checks objective index targets. `smc.options.rank_options` considers only fresh, liquid ATM and 1-step ITM contracts with reliable delta and scenario premiums.

Option pricing uses **explicit scenario exit bid estimates supplied by a pricing adapter**, not a delta-only profit assumption. Missing scenarios => no recommendation.

## What remains
1. Convert uploaded SMC PDFs (including six entry schemes, IDM and IFC) into versioned deterministic rules with golden fixtures.
2. Angel One SmartAPI historical/streaming adapters + verified BFO Greeks source.
3. Real volatility regime calibration, option-chain liquidity/depth, IV/theta/gamma scenario pricing.
4. Desktop chart UI, alerts, paper fills and backtests with fees/slippage.

**Market disclaimer:** Demonstration code only. No live trade advice. Index points do not equal option premium points.

## Phase 3.4: walk-forward historical research backtest

```powershell
python -m smc.backtest_cli
python -m pytest -q
```

The demo uses **synthetic index candles only**. `smc.backtest.walk_forward_backtest(candles, signal_fn)` supplies `signal_fn` only the candle prefix available at each historical close. The callback should return `Signal(IndexSetup(...), signal_index=len(prefix)-1)` or `None`. An accepted signal fills at the NEXT completed candle's open, never retroactively at the signal close. A pending trade is rejected if that opening price lies outside its bracket.

Conservative intrabar treatment: if a candle touches both stop and target, stop wins. Gaps beyond exits fill at open, not the old threshold. Fees/slippage inputs are **index-point-equivalent illustration**, *not* actual option fees. Result `total_net_index_points` must never be reported as rupee profit or option premium P&L.

**Not yet implemented:** automatic reconstruction of complete historic SMC/HTF signals, a real historical market-data loader, historical option bid/ask and Greeks, exchange calendars, actual option-premium P&L, broker fills, validated strategy performance, and live trading.

## Phase 3.5: historical CSV loader and causal SMC research replay

Use two independently sourced CSV files with the exact headers:
```csv
timestamp,open,high,low,close,volume
2026-11-12T09:16:00+05:30,25000,25010,24990,25004,100000
2026-11-12T09:17:00+05:30,25004,25012,24998,25008,100500
```

- **LTF timestamps are bar CLOSE times**, e.g. a 09:15–09:16 1-minute candle has timestamp 09:16.
- **HTF timestamps are bar START times** for this phase, e.g. a 09:15–10:15 hourly candle is recorded at 09:15. Only its close at 10:15 becomes visible during replay.
- CSV ISO-8601 timestamp MUST contain a UTC offset; no naive timestamps. Every OHLC row must be complete and strictly time ordered.
- You must supply **real, independently validated historical market CSVs** yourself. There is no bundled market feed or option data. Inadequate history or unconfirmed structure appropriately produces zero signals.
- Historical signal reconstruction re-runs closed-candle swing/liquidity, structure, provisional OB/IDM, FVG, HTF bias, target, ATR and index RR checks on each prefix. Historical option Greeks, option spread, premium PnL and actual broker fills are **not** checked; this experiment must NOT be interpreted as the full live option strategy.
- Requires sufficient HTF warmup (at least `2*external_k+2` fully closed HTF candles) plus LTF ATR warmup, with additional historical structure needed for actual candidates.

Run from project root after installing the editable package:
```powershell
python -m smc.replay_cli --ltf data\nifty_1m.csv --htf data\nifty_1h.csv --symbol NIFTY --htf-minutes 60 --out trades.csv
```
For SENSEX, change symbol and paths. This writes per-trade INDEX-points research results in `trades.csv`. `total_net_index_points` is **not rupees, option premium or a live trading return**. Review time conventions carefully to prevent accidental lookahead.

Phase 3.5 is an early backtest research adapter, NOT a benchmark result. No strategy profitability can be inferred until independently verified real-data history, correct market hours, options pricing and out-of-sample evaluation are added.

## Phase 4.1: Angel One historical candle download (read-only)

The downloader uses the official Angel One Historical API. API supports ONE_MINUTE (up to 30 days per request) and ONE_HOUR (up to 400 days per request); downloader splits into slightly shorter windows, checks response status, deduplicates by timestamp, and refuses conflicting candles. It **does not** place orders. Source: https://smartapi.angelone.in/docs

Install optional SDK dependencies:
```powershell
python -m pip install -e ".[dev,angel]"
```

**First verify login and the registered outbound static IP.** API login success does not guarantee Historical API access. Authentication fields are typed at runtime and are NEVER saved. The SDK logger is disabled before login because some versions print sensitive headers. If you used an earlier login script that logged request headers, inspect/remove local `logs/` files safely. Never put TOTP secret, API key, MPIN, access tokens or full SDK logs in commits or chat. `.gitignore` excludes `data/`, `logs/`, and `.env*`.

Test a **small** NIFTY sample first:
```powershell
python -m smc.angel_history_cli --symbol NIFTY --interval ONE_MINUTE --from-date 2026-11-10 --to-date 2026-11-10 --out data/nifty_1m.csv
```
Then 1-hour candles:
```powershell
python -m smc.angel_history_cli --symbol NIFTY --interval ONE_HOUR --from-date 2026-10-01 --to-date 2026-11-10 --out data/nifty_1h.csv
```
For SENSEX change `--symbol SENSEX` and output paths to `data/sensex_1m.csv` / `data/sensex_1h.csv`. The downloader resolves tokens by exact *index name and exchange* from Angel One's official instrument master; if that fails, verify current token in the master and supply `--token VERIFIED_TOKEN`. Never guess tokens or use options tokens for index candles. Use `--master-file path/to/OpenAPIScripMaster.json` if a local official master is available.

**Timestamp contract:** broker historical timestamps are candle START timestamps. ONE_MINUTE adds one minute and writes **close** timestamps for the replay CSV loader. ONE_HOUR retains **start** timestamps, because the replay expects HTF starts. All exported timestamps are Asia/Kolkata offsets. This convention currently applies only to 1M and 1H.

**Data quality:** duplicate conflicting bars and API failures abort the download (no partial CSV). This first version does not validate full market-session completeness or holiday calendars: inspect gaps before drawing conclusions. Neither market-data entitlements nor a six-month historical lookback is guaranteed. No real option premium, Greeks, IV or broker execution model is included.

The independent index-only replay can then read the two exported files:
```powershell
python -m smc.replay_cli --ltf data/nifty_1m.csv --htf data/nifty_1h.csv --symbol NIFTY --htf-minutes 60 --out trades.csv
```

## Phase 4.2 — session continuity quality gate (NIFTY/SENSEX 1M)

Run the auditor before interpreting any historical backtest:
```powershell
python -m smc.data_quality_cli --ltf data/nifty_1m.csv
```
Exit code `2` means the auditor found a quality issue. A 2026-11-11 NIFTY sample has 09:16–15:15 continuous close timestamps and an isolated 15:30 record after a 14-minute gap. This record is labeled **TERMINAL_1530_UNCLASSIFIED**, **not** an authenticated 1-minute CAS candle or validated closing price. No missing OHLC values are invented.

The replay CLI now rejects 1M CSVs with intraday gaps by default. For the **specific** terminal 15:15→15:30 pattern only, you can explicitly exclude the final isolated record:
```powershell
python -m smc.replay_cli --ltf data/nifty_1m.csv --htf data/nifty_1h.csv --symbol NIFTY --htf-minutes 60 --drop-terminal-1530 --out trades.csv
```
This removes the anomalous final record; it does not interpolate or mark missing candles as valid. All other intraday gaps remain fatal. Additionally, the current backtester does **not** model overnight next-bar fills, so replay rejects multi-day LTF input until session-aware backtesting is built. This is a deliberate safety gate; the separate download service may still collect multiple days.

Exchange CAS is only for eligible cash stocks in phase 1; never automatically categorize a NIFTY index bar as CAS solely from its timestamp. See NSE's official CAS page: https://www.nseindia.com/static/products-services/closing-auction-session . Holiday calendar, partial early-closes, HTF completeness and full session-specific rule validation remain pending.

## Phase 4.4 — safe multi-day research replay

The replay runs **one session per trading date** and resets the backtest position and pending signal at each boundary. A position that remains open at day-end uses the last eligible LTF bar close (END_OF_DATA); no overnight fills and no cross-session trades. LTF must pass the existing 1M continuity quality gate, including the explicit `--drop-terminal-1530` option. No synthetic candles are ever created. Every day is rescanned independently: **prior-day LTF context (PDH/PDL and morning warmup) is not yet imported**, so the multi-day setup count is deliberately incomplete.

HTF data is validated as exact 60-minute bars aligned to 09:15, 10:15, ... 14:15 IST. The 15:15 START timestamp is a potentially partial final hour and is **excluded from HTF bias**, rather than incorrectly treated as a 60-minute bar. Unsupported HTF timings or missing HTF warmup fail closed or produce WAIT; market-holiday and broker-data-level completeness still require independent validation.

```powershell
python -m smc.replay_cli --ltf data/nifty_1m.csv --htf data/nifty_1h.csv --symbol NIFTY --htf-minutes 60 --drop-terminal-1530 --out trades.csv --setups-out setup_diagnostics.csv
```

`setup_diagnostics.csv` provides **one final evaluation per observed sweep**, including stage, timestamps, entry and sweep stop where available. A preliminary `MISSING_VERIFIED_LIQUIDITY_TARGET` means the entry-only stage was deliberately run without a target. It is **not** a broker failure or a final verified risk rejection. The net result remains INDEX POINTS, NOT option premium P&L.

## November 2026 normal-session research profile

The actual November 2–11 NIFTY history can include a special Muhurat session
on **Sunday November 8, 2026**, and inconsistent broker closing-tail timestamps
(15:29 or 15:30 after 15:15). Do **not** interpret these as a complete normal
1-minute stream or as verified regular 1-minute candles.

The **explicit**, narrowly scoped flag `--nov-2026-regular-only` removes
the known special date (November 8) and retains regular-day close-timestamps
only through **15:15 IST**. It also excludes that special date from HTF.
The remaining LTF still passes the strict continuity gate; no arbitrary
gaps are accepted or filled. This is a conservative research subset, **not**
complete session coverage, and it is not a universal exchange calendar.

```powershell
python -m smc.replay_cli --ltf data/nifty_multi_1m.csv --htf data/nifty_1h.csv --symbol NIFTY --htf-minutes 60 --nov-2026-regular-only --out trades_multi.csv --setups-out setup_diagnostics_multi.csv
```

NSE confirmed the November 8 special Muhurat session (14:20 onward):
https://archives.nseindia.com/content/circulars/FAOP76940.pdf

If the strict 1-hour HTF validator raises a missing-slot error, inspect the
broker hourly dataset against the trading-day/session calendar; do not
manufacture hour bars to make the test pass.

## Phase 5 — separate setup experiments

Opt-in `--phase5` runs two **independent**, same-day research backtests
alongside the existing conservative sweep → CHoCH → FVG reversal baseline:

* `BOS_FVG_CONTINUATION`: confirmed internal BOS in HTF direction, followed
  by a same-direction FVG and a later closed-candle retest/rejection.
* `PIVOT_BREAKOUT_RETEST`: confirmed internal BOS through an old pivot level,
  followed by a **separate** candle touching that level and closing beyond it.

Both use the **existing** verified opposing liquidity target selection and
unchanged index 2R / 50-point NIFTY / 100-point SENSEX risk gates. No fixed
price targets are fabricated. The backtester enters no earlier than the
following bar open and never carries a position between sessions.

```powershell
python -m smc.replay_cli --ltf data/nifty_multi_1m.csv --htf data/nifty_1h.csv --symbol NIFTY --htf-minutes 60 --nov-2026-regular-only --phase5 --out trades_multi.csv --setups-out setup_diagnostics_multi.csv --phase5-trades-out phase5_trades.csv
```

Results in `phase5_independent_archetype_results` are **not additive** and
must never be advertised as a combined strategy or option P&L. MFE/MAE are
full OHLC **bar-envelope diagnostics**, not verified pre-exit intrabar
excursions; worst-case stop-first ordering still controls the trade.
The starting dataset is too small to validate profitability. Future phases
need multiple out-of-sample market regimes, 5M confirmation variants, real
option bid/ask and Greeks, and market-calendar verified session definitions.

## Phase 6 — observed option premium research (initial implementation)

**Goal:** Seek genuine CE/PE option-buying opportunities with a gross premium
gain of 20–25 points per unit, **without fixing a cheap-premium price range**.
No daily return is guaranteed. This is not an auto-trading system.

1. Phase 5 generates *causally approved index* signals (no future bars).
2. For each signal, select an actual historical quote **strictly after** its
   1-minute bar-close timestamp. Only same-side NIFTY/SENSEX contracts, valid
   expiry, positive liquidity, and acceptable bid–ask spread qualify.
3. Buy at observed **ask**, exit at observed **bid** at the first seen premium
   stop or target, or at an observed time exit. Missing quotes and intraday
   gaps are *unobservable*, **not filled**. One completed trade per session;
   overlapping setups are skipped rather than combined.
4. Target/stop/fees are per-option-unit; report 1-lot indicative rupees from
   the supplied historical lot size. At least 2R after per-unit costs is
   mandatory. Targets are observed quote thresholds, not promised fills.
5. No index-points-to-premium conversion, imaginary delta/IV forecasts,
   exchange data downloads, authenticated brokerage orders, live signals,
   calendar inference or no-data profits.

### Commands

```powershell
git switch sandbox
git pull origin sandbox
python -m pytest -q
python -u -m smc.phase5_cli --ltf data/nifty_multi_1m.csv --htf data/nifty_1h.csv --symbol NIFTY --strategy ALL --nov-2026-regular-only --signals-out phase5_signals.csv --result-out phase5_result.json
# ONLY once you have genuine timestamped historical option bid/ask quotes:
python -m smc.phase6_cli --signals phase5_signals.csv --quotes data/nifty_option_quotes.csv --target 25 --stop 10 --cost-per-unit 1 --out phase6_trades.csv --result-out phase6_result.json
```

The option tape CSV must be sorted by quote timestamp (many contracts may
share a timestamp), with these columns:

`timestamp,symbol,side,strike,expiry,bid,ask,lot_size,volume,delta`

All timestamps are offset-aware ISO 8601, e.g.
`2026-11-11T12:15:30+05:30`; expiry also requires offset.
`side` is `CE` or `PE`, symbol `NIFTY` or `SENSEX`. Delta is optional
and not used to project premium returns. Volume represents provider-reported
option volume; it is not invented. Price range has no arbitrary upper/lower
limit. Different contracts at the same earliest quote instant are ranked by
spread and volume, **not** by later returns. Provider quote coverage must
be independently audited before any performance interpretation.

**Limitations and next work:** add richer bid/ask/size/orderbook quote
quality checks, contract-specific trading calendars and lot sizes, robust
multi-quote intrabar sampling, signal/quote alignment and one-position-at-a-time
across overlapping strategies (rather than today's one-completed-trade-per-day
research safeguard), fees/slippage model, premium-vs-index joint attribution,
walk-forward train/validation splits, forward paper trading, and broker-specific
historical data adapter after source capabilities/licensing are verified.
Never turn on live orders by default.

## Phase 6.3 — independent premium OHLC comparison

The quote-tape replay (`smc.phase6_cli`) **still requires actual bid/ask**.
For broker option OHLC files, use this separate, strictly labeled educational
scenario runner instead:

```powershell
python -u -m smc.phase5_cli --ltf data/nifty_multi_1m.csv --htf data/nifty_1h.csv --symbol NIFTY --strategy ALL --nov-2026-regular-only --signals-out phase5_signals.csv --result-out phase5_result.json
python -m smc.phase6_ohlc_cli --signals phase5_signals.csv --option-ohlc data/nifty_25350_ce_1m.csv data/nifty_25400_ce_1m.csv --target 25 --stop 10 --holding-bars 24 --out phase6_ohlc_trades.csv --result-out phase6_ohlc_result.json
```

Each Phase 5 signal at minute close T allows an option scenario entry ONLY at
the **open of the option candle closing T+1 minute**. Index decision and
option timestamps must be aligned; future close cannot be used as entry.
An independent hypothetical scenario is evaluated for each matching CE/PE
contract, not a live contract selection algorithm. A threshold touched by
a bar is assigned a hypothetical threshold exit; where both stop and target
are inside a bar, STOP wins. Intraday gaps, missing option entry bars, and
trades lacking an observed exit within the holding window are excluded.
Session ends at the last regular continuous 15:15 IST minute-close candle.
No overlapping scenario results may be added into a portfolio return.
There are no bid/ask fills, brokerage, spreads, slippage or option orderbook
available here. `max_favorable_envelope` / `max_adverse_envelope` include
the OHLC exit bar and do NOT prove intrabar ordering. Results cannot establish
whether a genuine ₹20–₹25 premium scalp was executable.

## Offline desktop application — research viewer (sandbox)

A real Windows desktop window now exists (standard-library Tkinter). It reads
**your local files**, not live broker quotes. Run from repository root:

```powershell
git switch sandbox
git pull --ff-only origin sandbox
python -m pytest -q
python -m smc.desktop_v3 --ltf "data/nifty_multi_regular_1m.csv" --results-dir "results/v38_sessions"
```

Features:
- Choose any locally audited session, see actual 1-minute candlesticks, daily OHLC and terminal-event markings.
- Browse date-matched replay decisions and open evidence details: entry state, terminal cause, HTF alignment, target rejection, pending stages.
- Rejects mismatched-session/replay-length files and any replay that does not explicitly prohibit live orders.
- Session-isolated presentation; no calendar gaps are filled.
- If replay JSON is missing, candlestick chart still opens and displays zero observations rather than inventing trades.

**Not yet built:** broker-streaming UI, chart pan/zoom, historical continuation/rally detector, verified weekly/monthly trend, full options chain with premium bid/ask/Greeks, option P&L, paper fill engine, and packaged Windows installer.
This viewer is **not** a BUY/SELL recommendation service; yellow marks are terminal diagnostic events.

## V3.9A — provisional continuation observations (sandbox)

The offline desktop viewer now **also** inspects each selected audited 1-minute
session for an INTERNAL closed-candle **BOS -> opposite-body pullback ->
closed-candle reclaim of that pullback candle's high/low**.

- Reversal replay yellow markers and continuation research blue markers are
  clearly separated in the chart and inspector; selecting either focuses the
  historical event.
- Every continuation observation stays **WAIT**, with no index bracket, option
  strike, premium forecast, paper fill, or executable trade. The pullback
  definition and internal BOS are provisional proxies, **not independently
  verified ICT continuation, protected structure, or HTF POI**.
- CHoCH of the opposite direction cancels the candidate; incomplete, unordered,
  or multi-session inputs fail closed in the new detector.
- Continuations are computed on the local historical CSV in the desktop viewer;
  existing 7-day reversal JSON and its 93 terminal rejections are unmodified.
- The aim is to visualize where the continuation research stages appear on the
  actual rally, **not** to increase accepted trades by relaxing safety gates.

Run after git pull and pytest:
```powershell
python -m smc.desktop_v3 --ltf "data/nifty_multi_regular_1m.csv" --results-dir "results/v38_sessions"
```
Known gaps before real trade planning: verify 15M/1H/D/W/M regime and market
calendar, protected swings/IDM, independently eligible opposing liquidity
targets, retest/POI and FVG/displacement, actual option-chain bid/ask/Greeks,
slippage and paper fills.


## Integrated local SMC research terminal (sandbox)

The new local browser application combines audited 1m index candles,
per-observation ICT/SMC evidence, separately tracked setup lifecycles,
hypothetical index entry/stop/T1 and historical stop outcomes, and
**read-only** Angel WebSocket observation status. It requires no JavaScript
framework, cloud keys, broker-order permissions or public network port.
It is NOT a live trade execution system or a validated strategy.

On Windows PowerShell, from the checkout:

```powershell
git switch sandbox
git pull --ff-only origin sandbox
.\.venv\Scripts\python.exe -m pip install -e ".[dev,angel]"
.\.venv\Scripts\python.exe -m pytest -q

# Replays already downloaded actual NIFTY 1m history then opens browser:
.\run_smc.ps1

# Optional read-only Angel websocket; uses local interactive auth/TOTP:
.\run_smc.ps1 -Live

# SENSEX needs its own actual, audited CSV at
# data\sensex_angel_historical_raw.csv:
.\run_smc.ps1 -Symbol SENSEX -Live
```

Browser address: `http://127.0.0.1:8765` (bound only to loopback).
For `-Live`, Angel SmartAPI entitlements and exchange index subscription
must work on the actual user's PC; a successful CI test cannot verify them.
Connection failures, empty tick streams, incomplete sessions and old
index bars MUST remain WAIT/STALE; no candle gaps are synthesized.
Option chain, timestamped bid/ask and Greek entitlement are **not**
streamed through the index-only websocket; options premium P&L requires
independently observed contract quotes. Existing `smc.phase6_cli` can
evaluate verified historical option quotes separately.

The `run_smc.ps1` launcher only uses existing validated historical
CSV; no download or trade occurs automatically. Set up local Python
and broker credentials yourself, never share OTP, MPIN or tokens in chat
or Git. Press Ctrl+C in the terminal to close the localhost app.
If PowerShell script execution is restricted, invoke:
```powershell
.\.venv\Scripts\python.exe -m smc.historical_replay_v314_cli --symbol NIFTY --input-csv data\nifty_angel_historical_raw.csv --out results\v316_nifty_report.json --candidates-csv results\v316_nifty_brackets.csv --ict-csv results\v316_nifty_ict.csv
.\.venv\Scripts\python.exe -m smc.app_terminal_v316 --symbol NIFTY --csv data\nifty_angel_historical_raw.csv --report results\v316_nifty_report.json --open-browser
```

**Release gates still open:** actual broker tick delivery during exchange
hours; verified complete live candle coverage from session open; exchange
calendar; live option quotes, expiry/lot-size, delta/spread/IV validation;
paper fills/fees/slippage and walk-forward out-of-sample profitable
performance. Code-test success is **not** proof of profitable strategy
or real-time app operation. Do not enable automatic orders from this branch.

### Angel TOTP / quiet dashboard fix

With `./run_smc.ps1 -Live` on Windows the browser dashboard uses the original
PowerShell, and the broker authentication prompt runs in a **separate console**.
Enter the current 6-digit code in the broker console. The input is hidden;
this is expected. Cancelling that prompt exits the broker child cleanly,
without a Python traceback or interrupting the historical dashboard.
The UI reads only secret-free status JSON and displays
`AUTHENTICATION_REQUIRED`, `AUTHENTICATED`, `SUBSCRIBING`,
`CANCELLED`, `ERROR`, `WAIT`, or `RECENT_BAR` depending on verified
evidence. A successful login alone does **not** prove live tick delivery.
The 5-second polling now fetches only `/api/live`; historical sessions are
loaded once at server startup, and normal GET access logging is suppressed.
Offline launch ignores any old prior-run live-feed file.

Exit the dashboard with Ctrl+C in its main PowerShell window; do not paste
OTP, PIN, secret, API key, or access tokens into issue reports.

## Live SMC setup screen (read-only)

The integrated localhost terminal now has a prominent LIVE SMC TRADE SETUP
panel and sampled 1m index-candle chart. Its per-bar screen model is in
`smc/live_setup_screen_v317.py`. It reports:

- Broker stream state, latest closed index candle and provisional
  bullish/bearish **bias** (not a BUY/SELL trade instruction).
- Candidate sweep and IDM prices, order-block/FVG zones, independent
  BOS/CHoCH lifecycle stage, reason for WAIT and explicit missing evidence.
- Slots for verified entry, protected SL, T1/T2/T3, index R:R, CE/PE
  strike, premium bid/ask, delta, IV and premium stop/target.
  **Unavailable values stay UNAVAILABLE**; this is intentional.

The core will not promote any recorded setup into executable trade advice
until independently validated index targets, protected swing and
fresh observed option bid/ask + contract/Greeks exist. The current broker
stream only subscribes to the underlying index; index ticks CANNOT supply
option premiums. `CE/PE BIAS` is a direction hypothesis, not a verified
contract selection.

Historical data remains audited separately. Live OHLC is marked
`TICK_SAMPLED_UNVERIFIED_FULL_COVERAGE`: it is based on individual
WebSocket index ticks, which may omit market events. If the feed starts
after 09:15, breaks continuity or is stale, it stays WAIT. A new session
requires complete market hours; do not backfill fake minute candles.

To see the screen locally (PowerShell from repo root):

```powershell
git switch sandbox
git pull --ff-only origin sandbox
.\run_smc.ps1 -Live
```

Broker authentication happens in a separate Windows console. The localhost
browser opens automatically. On a closed-market date expect
NOT_CONNECTED/SUBSCRIBING/STALE, not a live setup.


## Single-screen NIFTY and SENSEX selector + prominent SMC alerts

`run_smc.ps1` now opens one read-only dashboard for **both indices**.
Use the MARKET dropdown to switch NIFTY/SENSEX without restarting the app.
The worker uses one authenticated Angel SmartWebSocketV2 session subscribing to
two different index tokens, and maintains separate candle streams and status
files. If only NIFTY history exists, SENSEX history is explicitly
`AUDITED_HISTORY_NOT_AVAILABLE`; no cross-symbol data substitution.

```powershell
cd E:\Project\SMC
git switch sandbox
git pull --ff-only origin sandbox
.\.venv\Scripts\python.exe -m pip install -e ".[dev,angel]"
.\run_smc.ps1 -Live
```

The app polls both markets while the browser tab is open. A just-observed
SMC retest on either market opens a **large in-page notification**; optional
Windows/browser desktop notifications require clicking `Enable desktop
alerts` and granting permission. The alert is explicitly labeled
`SMC RETEST OBSERVED — RESEARCH ONLY`, is deduplicated by market/setup,
and is **not a BUY CE/PE instruction**. Neither browser delivery nor
an external notification service is guaranteed while the browser is closed.

A read-only option-data poller uses the existing Angel login and current
instrument master to request current-expiry ATM / one-step ITM option FULL
depth for both indices, only after current valid closed index candles.
It shows timestamp-checked bid/ask and, where returned by the NSE-specific
Greek endpoint, delta and IV. It does not derive option prices from
underlying index movements. SENSEX/BFO Greeks are marked unavailable unless
an independent verified source exists. Displaying options does not imply
a recommended strike or a validated premium entry/SL/T1/T2/T3.
No broker order methods are implemented.

The live index bracket research calculates a *last close price reference*,
a provisional sweep/OB structural stop proxy and nearest unconsumed
confirmed-liquidity T1–T3; any bracket below 1:2 risk:reward, NIFTY 50
points or SENSEX 100 points is rejected. These references are displayed
separately from executable trade levels. Historical winning trades,
future paper fills, an authentic protected-swing SL, and option entry/
stop/target exit bids are **not yet independently verified**.
Do not execute trades solely based on this terminal.
