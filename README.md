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
