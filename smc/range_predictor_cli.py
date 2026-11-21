"""Command-line interface for Range Predictor V2.

Supported subcommands:
  audit-data: Audits local historical CSV files and quote tapes for REGULAR_360 compliance.
  backtest:   Executes causal rolling-origin walk-forward evaluation on NIFTY or SENSEX.
  train-ml:   Executes offline Phase 3 ML quantile benchmark vs deterministic baseline.
  reconcile:  Performs EOD outcome reconciliation for recorded shadow forecasts.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from .angelfolder_backtest_runner import audit_market_data
from .range_backtest_v1 import run_walk_forward_backtest, save_backtest_artifacts
from .range_live_v1 import reconcile_shadow_outcomes
from .range_ml_v1 import evaluate_ml_vs_baseline_walk_forward
from .range_predictor_v1 import TARGET_NAME

IST = ZoneInfo("Asia/Kolkata")


def audit_quote_tape(tape_path: Path) -> dict[str, Any]:
    """Audit recorded option quotes for date coverage and time compliance."""
    if not tape_path.is_file():
        return {"exists": False, "total_records": 0, "dates": []}
    
    count = 0
    dates: set[str] = set()
    first_dt = None
    last_dt = None
    
    try:
        with open(tape_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                count += 1
                try:
                    d = json.loads(line)
                    qa = d.get("quote_at") or d.get("timestamp")
                    if qa:
                        dates.add(qa[:10])
                        if first_dt is None:
                            first_dt = qa
                        last_dt = qa
                except json.JSONDecodeError:
                    pass
    except Exception as e:
        return {"exists": True, "error": str(e), "total_records": count}
        
    return {
        "exists": True,
        "total_records": count,
        "unique_dates_count": len(dates),
        "dates": sorted(dates),
        "first_timestamp": first_dt,
        "last_timestamp": last_dt,
    }


def handle_audit_data(args: argparse.Namespace) -> int:
    root_dir = Path(args.root).resolve()
    data_dir = Path(args.data_dir).resolve() if Path(args.data_dir).is_absolute() else (root_dir / args.data_dir)
    out_dir = Path(args.out).resolve() if Path(args.out).is_absolute() else (root_dir / args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    
    print("=" * 70)
    print(" SMC RANGE PREDICTOR V2: DATA & QUOTE AUDIT")
    print("=" * 70)
    print(f"Target Name: {TARGET_NAME}")
    print(f"Root: {root_dir}")
    print(f"Data Dir: {data_dir}")
    print(f"Output Dir: {out_dir}")
    
    audit_results: dict[str, Any] = {
        "audit_timestamp": datetime.now(IST).isoformat(),
        "target_name": TARGET_NAME,
        "markets": {},
        "quote_tapes": {},
        "vix_status": {
            "available": False,
            "reason": "VIX_UNAVAILABLE",
            "note": "Historical India VIX series not present in pinned repository.",
        },
    }
    
    for symbol in ["NIFTY", "SENSEX"]:
        print(f"\n--- Auditing {symbol} 1-minute historical data ---")
        try:
            market_audit, usable_sessions = audit_market_data(symbol, data_dir)
            audit_results["markets"][symbol] = market_audit
            print(f"  Total 1m rows: {market_audit['total_1m_rows']:,}")
            print(f"  Total calendar sessions: {market_audit['date_range']['total_sessions']}")
            print(f"  Usable regular 360-bar sessions: {market_audit['usable_regular_sessions_count']}")
            print(f"  Quarantined tail sessions: {market_audit['quarantined_tail_sessions_count']}")
            print(f"  Excluded sessions: {market_audit['excluded_sessions_count']}")
            if market_audit['excluded_sessions_count'] > 0:
                print(f"  Excluded details: {market_audit['excluded_sessions_detail']}")
        except Exception as e:
            print(f"  ERROR auditing {symbol}: {e}")
            audit_results["markets"][symbol] = {"error": str(e)}
            
    # Audit quote tapes
    print("\n--- Auditing Option Quote Tapes ---")
    results_dir = root_dir / "results"
    for symbol, fname in [("NIFTY", "live_nifty_option_quotes.jsonl"), ("SENSEX", "live_sensex_option_quotes.jsonl")]:
        tape_path = results_dir / fname
        res = audit_quote_tape(tape_path)
        audit_results["quote_tapes"][symbol] = res
        print(f"  {symbol} Quote Tape: {res.get('total_records', 0):,} records across {res.get('unique_dates_count', 0)} dates")
        if res.get("dates"):
            print(f"    Dates: {res['dates']}")
            
    # Save machine-readable report
    report_path = out_dir / "audit_report.json"
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(audit_results, f, indent=2)
    print(f"\n[OK] Audit report saved: {report_path}")
    return 0


def handle_backtest(args: argparse.Namespace) -> int:
    root_dir = Path(args.root).resolve()
    data_dir = Path(args.data_dir).resolve() if Path(args.data_dir).is_absolute() else (root_dir / args.data_dir)
    out_dir = Path(args.out).resolve() if Path(args.out).is_absolute() else (root_dir / args.out)
    symbol = args.symbol.upper()
    
    print("=" * 70)
    print(f" SMC RANGE PREDICTOR V2: HISTORICAL WALK-FORWARD BACKTEST ({symbol})")
    print("=" * 70)
    print(f"Target: {TARGET_NAME} (09:16 to 15:15 IST, 360 contiguous bars)")
    print(f"Root: {root_dir}")
    print(f"Data Dir: {data_dir}")
    print(f"Symbol: {symbol}")
    
    try:
        _, usable_sessions = audit_market_data(symbol, data_dir)
    except Exception as e:
        print(f"ERROR reading market data: {e}", file=sys.stderr)
        return 1
        
    print(f"Audited usable REGULAR_360 sessions: {len(usable_sessions)}")
    
    warmup = getattr(args, "warmup", 20)
    print(f"Running rolling-origin walk-forward evaluation (Warmup={warmup} sessions)...")
    summary, records = run_walk_forward_backtest(
        symbol=symbol,
        usable_sessions=usable_sessions,
        warmup_sessions=warmup,
    )
    
    run_id = f"{symbol.lower()}_baseline_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    saved_path = save_backtest_artifacts(summary, records, out_dir, run_id=run_id)
    
    s16 = summary.snapshot_0916
    s30 = summary.snapshot_0930
    d = summary.delta_0930_vs_0916
    
    print("\n" + "=" * 70)
    print(f" BACKTEST RESULTS FOR {symbol} ({TARGET_NAME})")
    print("=" * 70)
    print(f"Total Audited Sessions : {summary.total_audited_sessions}")
    print(f"Evaluated Sessions     : {summary.evaluated_sessions} (after {summary.warmup_sessions} warmup days)")
    print(f"\n[INDEPENDENT SNAPSHOT COHORTS]")
    print(f"  --- 09:16 IST Snapshot ({s16['sample_sessions_count']} sessions) ---")
    print(f"    MAE Q50               : {s16['mae_q50']} pts")
    print(f"    Median Absolute Error : {s16['median_absolute_error']} pts")
    print(f"    Nominal 80% Coverage  : {s16['empirical_coverage_80pct']:.1%} (Target ~80%)")
    print(f"    Pinball Loss (Q10/50/90): {s16['pinball_loss_q10']} / {s16['pinball_loss_q50']} / {s16['pinball_loss_q90']}")
    print(f"    Expansion Brier Score : {s16['expansion_brier_score']:.4f}")
    print(f"    Rolling Base-Rate Ref : {s16['expansion_reference_brier']:.4f}")
    print(f"    Brier Skill Score     : {s16['brier_skill_score']:+.4f} ({'BEATS base rate' if s16['brier_skill_score'] > 0 else 'Base rate better'})")
    
    print(f"\n  --- 09:30 IST Snapshot ({s30['sample_sessions_count']} sessions) ---")
    print(f"    MAE Q50               : {s30['mae_q50']} pts")
    print(f"    Median Absolute Error : {s30['median_absolute_error']} pts")
    print(f"    Nominal 80% Coverage  : {s30['empirical_coverage_80pct']:.1%} (Target ~80%)")
    print(f"    Pinball Loss (Q10/50/90): {s30['pinball_loss_q10']} / {s30['pinball_loss_q50']} / {s30['pinball_loss_q90']}")
    print(f"    Expansion Brier Score : {s30['expansion_brier_score']:.4f}")
    print(f"    Rolling Base-Rate Ref : {s30['expansion_reference_brier']:.4f}")
    print(f"    Brier Skill Score     : {s30['brier_skill_score']:+.4f}")
    
    print(f"\n  --- Delta Comparison (09:30 vs 09:16) ---")
    print(f"    Delta MAE             : {d['delta_mae_pts']:+.2f} pts")
    print(f"    Delta Median AE       : {d['delta_median_ae_pts']:+.2f} pts")
    print(f"    Delta Coverage        : {d['delta_coverage_pct']:+.2%}")
    print(f"    Delta Brier Skill     : {d['delta_brier_skill']:+.4f}")
    
    print(f"\n[VOLATILITY REGIME BREAKDOWN (09:16 Cohort)]")
    for reg_name, reg_stats in summary.volatility_regimes.items():
        if reg_stats:
            print(f"  {reg_name.replace('_', ' ').title():<24}: {reg_stats['sessions_count']} days | MAE: {reg_stats['mae_q50']} pts | 80% Cov: {reg_stats['coverage_80pct']:.1%} | Exp Rate: {reg_stats['expansion_rate']:.1%}")
            
    print(f"\n[OK] Artifacts archived in: {saved_path}")
    return 0


def handle_train_ml(args: argparse.Namespace) -> int:
    root_dir = Path(args.root).resolve()
    data_dir = Path(args.data_dir).resolve() if Path(args.data_dir).is_absolute() else (root_dir / args.data_dir)
    out_dir = Path(args.out).resolve() if Path(args.out).is_absolute() else (root_dir / args.out)
    symbol = args.symbol.upper()
    
    print("=" * 70)
    print(f" SMC RANGE PREDICTOR V2: PHASE 3 ML BENCHMARK ({symbol})")
    print("=" * 70)
    print(f"Target: {TARGET_NAME}")
    
    try:
        _, usable_sessions = audit_market_data(symbol, data_dir)
    except Exception as e:
        print(f"ERROR reading market data: {e}", file=sys.stderr)
        return 1
        
    print(f"Audited usable REGULAR_360 sessions: {len(usable_sessions)}")
    print("Training HistGradientBoostingRegressor (P10/P50/P90) & LogisticRegression...")
    print("Running chronological walk-forward benchmark...")
    
    metrics, manifest = evaluate_ml_vs_baseline_walk_forward(symbol, usable_sessions, warmup_sessions=25)
    
    print("\n" + "=" * 70)
    print(" ML MODEL vs DETERMINISTIC BASELINE RESULTS")
    print("=" * 70)
    print(f"Evaluated Test Samples : {metrics.evaluated_samples}")
    print(f"Baseline MAE           : {metrics.baseline_mae:.2f} pts")
    print(f"ML Model MAE           : {metrics.ml_mae:.2f} pts")
    print(f"MAE Improvement        : {metrics.mae_improvement_pts:+.2f} pts ({metrics.mae_improvement_pct:+.2f}%)")
    print(f"Baseline Pinball Q50   : {metrics.baseline_pinball_q50:.3f}")
    print(f"ML Pinball Q50         : {metrics.ml_pinball_q50:.3f}")
    print(f"Baseline 80% Coverage  : {metrics.baseline_coverage_80:.1%}")
    print(f"ML 80% Coverage        : {metrics.ml_coverage_80:.1%}")
    print(f"Baseline Brier Score   : {metrics.baseline_brier:.4f}")
    print(f"ML Brier Score         : {metrics.ml_brier:.4f}")
    print(f"Promotion Gate Decision: {'PROMOTED TO ML_ELIGIBLE' if metrics.promoted else 'REJECTED - RETAIN BASELINE'}")
    if metrics.rejection_reason:
        print(f"Note                   : {metrics.rejection_reason}")
        
    manifest_dir = out_dir / "models" / symbol.lower() / "v1"
    manifest_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = manifest_dir / "manifest.json"
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)
    print(f"\n[OK] Model manifest saved: {manifest_path}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="smc.range_predictor_cli",
        description="Range Predictor V2 Research CLI",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    
    # audit-data
    audit_parser = subparsers.add_parser("audit-data", help="Audit historical data and quotes")
    audit_parser.add_argument("--root", default=".", help="Project repository root path")
    audit_parser.add_argument("--data-dir", default="angelfolder", help="Historical 1m CSV data directory")
    audit_parser.add_argument("--out", default="results/range_forecast", help="Output directory for reports")
    audit_parser.set_defaults(func=handle_audit_data)
    
    # backtest
    backtest_parser = subparsers.add_parser("backtest", help="Run walk-forward backtest")
    backtest_parser.add_argument("--root", default=".", help="Project repository root path")
    backtest_parser.add_argument("--data-dir", default="angelfolder", help="Historical 1m CSV data directory")
    backtest_parser.add_argument("--symbol", required=True, choices=["NIFTY", "SENSEX", "nifty", "sensex"], help="Index symbol")
    backtest_parser.add_argument("--warmup", type=int, default=20, help="Warmup sessions before scoring")
    backtest_parser.add_argument("--out", default="results/range_forecast", help="Output directory for backtest artifacts")
    backtest_parser.set_defaults(func=handle_backtest)
    
    # train-ml
    ml_parser = subparsers.add_parser("train-ml", help="Train and benchmark offline ML model vs baseline")
    ml_parser.add_argument("--root", default=".", help="Project repository root path")
    ml_parser.add_argument("--data-dir", default="angelfolder", help="Historical 1m CSV data directory")
    ml_parser.add_argument("--symbol", required=True, choices=["NIFTY", "SENSEX", "nifty", "sensex"], help="Index symbol")
    ml_parser.add_argument("--out", default="results/range_forecast", help="Output directory for model artifacts")
    ml_parser.set_defaults(func=handle_train_ml)
    
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
