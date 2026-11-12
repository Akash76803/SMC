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
