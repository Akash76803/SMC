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
