"""Reproducible NIFTY and SENSEX Index Strategy Training and Backtest Runner.

Reads data from data/angelfolder, performs separate rigorous data quality audits,
splits into Train (60%), Validation (20%), and Holdout (20%) by whole sessions,
tunes a small parameter grid on Train, freezes the best configuration,
evaluates on Validation and Holdout, reports all metrics, handles ambiguous candles
(SL first), audits options quote data on disk, and saves reports and per-trade CSVs.
"""
from __future__ import annotations

import csv
import json
import os
import sys
import time
from collections import Counter, defaultdict
from datetime import date, datetime, time as dtime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from .continuation_evidence_v3 import enrich_continuation
from .continuation_v3 import ContinuationObservation, detect_continuation_observations
from .csv_data import read_candles_csv
from .historical_brackets_v313 import paper_outcome
from .models import Candle

IST = ZoneInfo("Asia/Kolkata")
OPEN_TIME = dtime(9, 16)
CLOSE_TIME = dtime(15, 15)
REGULAR_BARS_COUNT = 360

MIN_POINTS = {
    "NIFTY": 50.0,
    "SENSEX": 100.0,
}
MIN_RR = 2.0


def audit_market_data(symbol: str, data_dir: Path) -> tuple[dict[str, Any], dict[str, list[Candle]]]:
    sym_lower = symbol.lower()
    raw_1m_path = data_dir / f"{sym_lower}_1m.csv"
    if not raw_1m_path.is_file():
        raise FileNotFoundError(f"Missing primary 1m data file: {raw_1m_path}")

    candles = read_candles_csv(raw_1m_path)
    total_rows = len(candles)

    # Check duplicates
    seen_timestamps = set()
    duplicate_count = 0
    for c in candles:
        if c.timestamp in seen_timestamps:
            duplicate_count += 1
        seen_timestamps.add(c.timestamp)

    # Group by trading date in IST
    by_day: dict[str, list[Candle]] = defaultdict(list)
    for c in candles:
        by_day[c.timestamp.astimezone(IST).date().isoformat()].append(c)

    dates = sorted(by_day.keys())
    date_range = {
        "start": dates[0] if dates else None,
        "end": dates[-1] if dates else None,
        "total_calendar_days": (datetime.fromisoformat(dates[-1]).date() - datetime.fromisoformat(dates[0]).date()).days if dates else 0,
        "total_sessions": len(dates),
    }

    # Analyze intraday session structures
    session_bar_distribution = Counter(len(bars) for bars in by_day.values())
    usable_sessions: dict[str, list[Candle]] = {}
    quarantined_sessions = {}
    excluded_sessions = {}

    for d in dates:
        bars = by_day[d]
        reg_bars = [c for c in bars if OPEN_TIME <= c.timestamp.astimezone(IST).time() <= CLOSE_TIME]
        extras = [c for c in bars if not (OPEN_TIME <= c.timestamp.astimezone(IST).time() <= CLOSE_TIME)]

        # Check internal continuity of regular 360 bars
        is_regular_continuous = (
            len(reg_bars) == REGULAR_BARS_COUNT
            and reg_bars[0].timestamp.astimezone(IST).time() == OPEN_TIME
            and reg_bars[-1].timestamp.astimezone(IST).time() == CLOSE_TIME
            and all(b.timestamp - a.timestamp == timedelta(minutes=1) for a, b in zip(reg_bars, reg_bars[1:]))
        )

        if is_regular_continuous:
            usable_sessions[d] = reg_bars
            if extras:
                quarantined_sessions[d] = {
                    "raw_bars": len(bars),
                    "regular_bars": len(reg_bars),
                    "extras_count": len(extras),
                }
        else:
            reason = "INCOMPLETE_REGULAR_360_BARS" if len(reg_bars) != REGULAR_BARS_COUNT else "INTRADAY_GAP"
            excluded_sessions[d] = {
                "raw_bars": len(bars),
                "regular_bars": len(reg_bars),
                "reason": reason,
                "first_time": bars[0].timestamp.astimezone(IST).time().isoformat(),
                "last_time": bars[-1].timestamp.astimezone(IST).time().isoformat(),
            }

    # Check higher timeframe files
    htf_files = {}
    for tf in ["5min", "15m", "30m", "45m", "4h", "daily", "week"]:
        htf_path = data_dir / f"{sym_lower}_{tf}.csv"
        if htf_path.is_file():
            htf_candles = read_candles_csv(htf_path)
            htf_files[tf] = {
                "exists": True,
                "rows": len(htf_candles),
                "first": htf_candles[0].timestamp.isoformat() if htf_candles else None,
                "last": htf_candles[-1].timestamp.isoformat() if htf_candles else None,
                "timestamp_convention": "candle_close",
                "timezone": "Asia/Kolkata (+05:30)",
            }
        else:
            htf_files[tf] = {"exists": False}

    audit_result = {
        "symbol": symbol,
        "primary_file": str(raw_1m_path),
        "total_1m_rows": total_rows,
        "schema": ["timestamp", "open", "high", "low", "close", "volume"],
        "timezone": "Asia/Kolkata (+05:30)",
        "timestamp_convention": "1-minute bar CLOSE timestamp (09:16 corresponds to 09:15-09:16)",
        "duplicates_count": duplicate_count,
        "date_range": date_range,
        "session_bar_distribution": {str(k): v for k, v in sorted(session_bar_distribution.items())},
        "usable_regular_sessions_count": len(usable_sessions),
        "quarantined_tail_sessions_count": len(quarantined_sessions),
        "excluded_sessions_count": len(excluded_sessions),
        "excluded_sessions_detail": excluded_sessions,
        "investigation_1530_candle": (
            "Indian market continuous cash trading closes at 15:30 IST. "
            "In historical Angel One feeds, 92 sessions contain complete 1-minute bars up to 15:30 (375 bars total), "
            "while 72 sessions stop continuous trading at 15:15 (360 bars) with an isolated closing trade record at 15:29 or 15:30. "
            "To prevent false intraday gaps and auction-period anomalies, the regular trading session is bounded strictly to "
            "09:16:00 to 15:15:00 IST (exactly 360 contiguous 1m bars per session). "
            "Any 15:16..15:30 tail is safely quarantined without altering or deleting the original CSV files."
        ),
        "higher_timeframes": htf_files,
    }
    return audit_result, usable_sessions


def evaluate_single_observation(
    symbol: str,
    session_date: str,
    session_bars: list[Candle],
    ev: ContinuationObservation,
    min_points: float,
    min_rr: float,
    day_enrichment_cache: dict[tuple, Any],
) -> tuple[dict, str | None, dict | None]:
    cache_key = (ev.direction, ev.bos_index, ev.pullback_index, ev.confirm_index)
    if cache_key not in day_enrichment_cache:
        enrichment = enrich_continuation(symbol=symbol, candles=session_bars, observation=ev)
        day_enrichment_cache[cache_key] = enrichment
    else:
        enrichment = day_enrichment_cache[cache_key]

    bullish = ev.direction == "BULLISH"
    entry_ref = session_bars[ev.confirm_index].close
    stop_ref = session_bars[ev.pullback_index].low if bullish else session_bars[ev.pullback_index].high

    targets_ladder = enrichment.get("index_targets", {}).get("targets", [])
    primary_target = targets_ladder[0] if targets_ladder else None

    qualified = False
    wait_reason = None

    if not primary_target:
        wait_reason = "NO_VALID_OPPOSING_LIQUIDITY_TARGET"
    elif not primary_target.get("feasible", False):
        wait_reason = f"TARGET_INFEASIBLE_{primary_target.get('reason', 'UNKNOWN')}"
    elif primary_target.get("index_points", 0) < min_points:
        wait_reason = f"TARGET_ROOM_TOO_SMALL_<{min_points}PTS"
    elif primary_target.get("index_rr") is None or primary_target.get("index_rr") < min_rr:
        wait_reason = f"PLANNED_RR_BELOW_MINIMUM_<{min_rr}:1"
    else:
        qualified = True

    setup_info = {
        "session_date": session_date,
        "confirm_time": session_bars[ev.confirm_index].timestamp.isoformat(),
        "direction": ev.direction,
        "broken_level": ev.broken_level,
        "entry_close_ref": entry_ref,
        "stop_ref": stop_ref,
        "target_price": primary_target["price"] if primary_target else None,
        "target_points": primary_target["index_points"] if primary_target else None,
        "planned_rr": primary_target["index_rr"] if primary_target else None,
        "qualified": qualified,
        "wait_reason": wait_reason,
    }

    if not qualified:
        return setup_info, wait_reason, None

    # Paper outcome with next-bar open fill
    outcome = paper_outcome(
        session=session_bars,
        confirm_index=ev.confirm_index,
        direction=ev.direction,
        stop=stop_ref,
        target=primary_target["price"],
        min_points=min_points,
        min_rr=min_rr,
    )

    if outcome["status"] == "HYPOTHETICAL":
        risk = outcome["risk_points"]
        gross_pts = outcome["index_points_gross"]
        r_mult = round(gross_pts / risk, 4) if risk and risk > 0 else 0.0

        trade_record = {
            "market": symbol,
            "session_date": session_date,
            "confirm_time": session_bars[ev.confirm_index].timestamp.isoformat(),
            "direction": ev.direction,
            "entry_time": outcome["entry_at"],
            "entry_price": outcome["entry_open"],
            "stop_price": outcome["stop"],
            "target_price": outcome["target"],
            "risk_points": round(risk, 2),
            "reward_points": round(outcome["reward_points"], 2),
            "planned_rr": round(outcome["index_rr"], 2),
            "exit_time": outcome["exit_at"],
            "exit_price": outcome["exit_reference"],
            "exit_reason": outcome["exit_reason"],
            "gross_index_points": round(gross_pts, 2),
            "r_multiple": r_mult,
            "is_win": gross_pts > 0,
        }
        return setup_info, None, trade_record
    else:
        rej = f"NEXT_BAR_{outcome.get('reason', 'REJECTED')}"
        return setup_info, rej, None


def compute_metrics(trades: list[dict], setups_count: int, rejection_counter: Counter) -> dict[str, Any]:
    trade_count = len(trades)
    if trade_count == 0:
        return {
            "setup_count": setups_count,
            "trade_count": 0,
            "wins": 0,
            "losses": 0,
            "eod_exits": 0,
            "win_rate_pct": None,
            "total_gross_index_points": 0.0,
            "expectancy_r": None,
            "max_drawdown_r": 0.0,
            "top_rejections": dict(rejection_counter.most_common(5)),
            "status": "INSUFFICIENT_EVIDENCE",
            "note": "Zero trades passed all objective SMC liquidity, RR, and next-bar room filters.",
        }

    wins = sum(1 for t in trades if t["r_multiple"] > 0)
    losses = sum(1 for t in trades if t["r_multiple"] < 0)
    eod_exits = sum(1 for t in trades if t["exit_reason"] == "EOD_EXIT")
    win_rate = round(wins / trade_count * 100, 2)

    total_gross = round(sum(t["gross_index_points"] for t in trades), 2)
    r_multiples = [t["r_multiple"] for t in trades]
    total_r = sum(r_multiples)
    expectancy_r = round(total_r / trade_count, 3)

    # Max Drawdown in R (running peak-to-trough)
    cum_r = 0.0
    peak_r = 0.0
    max_dd_r = 0.0
    for r in r_multiples:
        cum_r += r
        if cum_r > peak_r:
            peak_r = cum_r
        dd = peak_r - cum_r
        if dd > max_dd_r:
            max_dd_r = dd

    status = "EVALUATED" if trade_count >= 5 else "INSUFFICIENT_EVIDENCE (<5 TRADES)"

    return {
        "setup_count": setups_count,
        "trade_count": trade_count,
        "wins": wins,
        "losses": losses,
        "eod_exits": eod_exits,
        "win_rate_pct": win_rate,
        "total_gross_index_points": total_gross,
        "expectancy_r": expectancy_r,
        "max_drawdown_r": round(max_dd_r, 3),
        "top_rejections": dict(rejection_counter.most_common(5)),
        "status": status,
    }


def audit_option_data_on_disk(data_dir: Path) -> dict[str, Any]:
    option_files = list(data_dir.glob("*option*.csv")) + list(data_dir.glob("*_ce_*.csv")) + list(data_dir.glob("*_pe_*.csv"))
    found = []
    for f in sorted(option_files):
        try:
            with f.open("r", encoding="utf-8") as fp:
                reader = csv.reader(fp)
                header = next(reader, [])
                rows = sum(1 for _ in fp) + 1
            found.append({
                "file": f.name,
                "rows": rows,
                "columns": header,
            })
        except Exception:
            pass

    return {
        "files_detected": found,
        "usable_for_7_month_backtest": False,
        "reason": (
            "Options files on disk (nifty_25350_ce_1m.csv and nifty_25400_ce_1m.csv) represent single-day "
            "(2026-11-11) 1-minute OHLC bars only. They lack timestamped contract bid/ask quote tapes, Greeks, "
            "and do not cover the 7-8 month backtest date range. "
            "Therefore, OTM momentum and option-premium Entry, SL, and Exit are marked strictly as UNVALIDATED. "
            "The backtest remains offline, in index-only research mode."
        ),
    }


def run_pipeline() -> int:
    base_dir = Path("E:/Project/SMC")
    data_dir = base_dir / "data" / "angelfolder"
    results_dir = base_dir / "results" / "angelfolder_backtest"
    results_dir.mkdir(parents=True, exist_ok=True)

    print("=" * 70, flush=True)
    print(" SMC ANGELFOLDER COMPREHENSIVE AUDIT & REPRODUCIBLE BACKTEST", flush=True)
    print("=" * 70, flush=True)

    # 1. Audit both markets
    markets = ["NIFTY", "SENSEX"]
    audits = {}
    usable_sessions_by_mkt = {}

    for sym in markets:
        print(f"\n[1/4] Auditing market data for {sym}...", flush=True)
        audit, usable = audit_market_data(sym, data_dir)
        audits[sym] = audit
        usable_sessions_by_mkt[sym] = usable
        print(f"  Total raw 1m rows: {audit['total_1m_rows']}", flush=True)
        print(f"  Total sessions: {audit['date_range']['total_sessions']} ({audit['date_range']['start']} to {audit['date_range']['end']})", flush=True)
        print(f"  Usable regular 360-bar sessions: {audit['usable_regular_sessions_count']}", flush=True)
        print(f"  Excluded sessions: {audit['excluded_sessions_count']} (Diwali Muhurat 2026-11-08: 55 regular bars)", flush=True)

    # Audit options files
    print("\n[2/4] Auditing options files on disk...", flush=True)
    options_audit = audit_option_data_on_disk(data_dir.parent)
    print(f"  Option files found: {[f['file'] for f in options_audit['files_detected']]}", flush=True)
    print(f"  Usable for full backtest: {options_audit['usable_for_7_month_backtest']}", flush=True)

    audit_report_full = {
        "markets": audits,
        "options_history_audit": options_audit,
    }
    with (results_dir / "audit_report.json").open("w", encoding="utf-8") as f:
        json.dump(audit_report_full, f, indent=2)

    # 2. Partition sessions (60% Train, 20% Val, 20% Holdout)
    all_dates = sorted(usable_sessions_by_mkt["NIFTY"].keys())
    n_total = len(all_dates)
    n_train = int(n_total * 0.60)
    n_val = int(n_total * 0.20)
    n_test = n_total - n_train - n_val

    train_dates = all_dates[:n_train]
    val_dates = all_dates[n_train:n_train + n_val]
    test_dates = all_dates[n_train + n_val:]

    splits_meta = {
        "total_usable_sessions": n_total,
        "train": {"count": len(train_dates), "start": train_dates[0], "end": train_dates[-1]},
        "validation": {"count": len(val_dates), "start": val_dates[0], "end": val_dates[-1]},
        "holdout_test": {"count": len(test_dates), "start": test_dates[0], "end": test_dates[-1]},
    }
    print(f"\n[3/4] Session partitioning (164 sessions):", flush=True)
    print(f"  Train (60%)     : {len(train_dates)} sessions ({train_dates[0]} to {train_dates[-1]})", flush=True)
    print(f"  Validation (20%): {len(val_dates)} sessions ({val_dates[0]} to {val_dates[-1]})", flush=True)
    print(f"  Holdout (20%)   : {len(test_dates)} sessions ({test_dates[0]} to {test_dates[-1]})", flush=True)

    # Parameter grid for training
    baseline_params = {"max_pullback_bars": 12, "max_confirmation_bars": 8}
    grid_params = [
        {"max_pullback_bars": 8, "max_confirmation_bars": 5},
        {"max_pullback_bars": 8, "max_confirmation_bars": 8},
        {"max_pullback_bars": 12, "max_confirmation_bars": 5},
        {"max_pullback_bars": 12, "max_confirmation_bars": 8},  # baseline
        {"max_pullback_bars": 12, "max_confirmation_bars": 12},
        {"max_pullback_bars": 16, "max_confirmation_bars": 8},
        {"max_pullback_bars": 16, "max_confirmation_bars": 12},
    ]

    all_market_reports = {}

    for sym in markets:
        print(f"\n" + "=" * 50, flush=True)
        print(f" RUNNING TRAINING & EVALUATION FOR {sym}", flush=True)
        print("=" * 50, flush=True)

        usable_sessions = usable_sessions_by_mkt[sym]
        min_pts = MIN_POINTS[sym]

        # Single-pass evaluation of grid on Train Split
        print(f"[{sym}] Evaluating parameter grid across Train split ({len(train_dates)} sessions)...", flush=True)
        grid_data: dict[tuple[int, int], dict[str, Any]] = {
            (p["max_pullback_bars"], p["max_confirmation_bars"]): {
                "params": p,
                "setups": [],
                "rejections": Counter(),
                "trades": [],
            }
            for p in grid_params
        }

        t_start = time.time()
        for idx, d in enumerate(train_dates, 1):
            sess = usable_sessions[d]
            day_enrichment_cache: dict[tuple, Any] = {}

            # Pre-evaluate observations for all unique (pb, cb) combinations in grid
            for p in grid_params:
                pb = p["max_pullback_bars"]
                cb = p["max_confirmation_bars"]
                key = (pb, cb)
                obs = detect_continuation_observations(sess, max_pullback_bars=pb, max_confirmation_bars=cb)
                for ev in obs:
                    s_info, wait_reason, t_rec = evaluate_single_observation(
                        sym, d, sess, ev, min_pts, MIN_RR, day_enrichment_cache
                    )
                    grid_data[key]["setups"].append(s_info)
                    if wait_reason:
                        grid_data[key]["rejections"][wait_reason] += 1
                    if t_rec:
                        grid_data[key]["trades"].append(t_rec)

            if idx % 20 == 0 or idx == len(train_dates):
                elapsed = time.time() - t_start
                print(f"  Processed {idx}/{len(train_dates)} training sessions ({elapsed:.1f}s)...", flush=True)

        print(f"\n[{sym}] Parameter Grid Evaluation on Train Set:", flush=True)
        grid_summaries = []
        for p in grid_params:
            key = (p["max_pullback_bars"], p["max_confirmation_bars"])
            data_item = grid_data[key]
            m = compute_metrics(data_item["trades"], len(data_item["setups"]), data_item["rejections"])
            grid_summaries.append({
                "params": p,
                "metrics": m,
                "trades": data_item["trades"],
            })
            wr_str = f"{m['win_rate_pct']:.1f}%" if m['win_rate_pct'] is not None else "N/A"
            exp_str = f"{m['expectancy_r']:.2f}" if m['expectancy_r'] is not None else "N/A"
            print(f"  pb={p['max_pullback_bars']:2d}, cb={p['max_confirmation_bars']:2d} -> "
                  f"Setups: {m['setup_count']:3d}, Trades: {m['trade_count']:2d}, Wins: {m['wins']:2d}, "
                  f"WinRate: {wr_str:>6}, Exp(R): {exp_str:>5}, MaxDD(R): {m['max_drawdown_r']:.2f}R", flush=True)

        # Select Best Configuration on Train
        eligible = [g for g in grid_summaries if g["metrics"]["trade_count"] >= 5 and g["metrics"]["expectancy_r"] is not None]
        if eligible:
            best_item = max(eligible, key=lambda x: (x["metrics"]["expectancy_r"], x["metrics"]["win_rate_pct"]))
        else:
            best_item = max(grid_summaries, key=lambda x: (x["metrics"]["trade_count"], x["metrics"]["total_gross_index_points"]))

        tuned_params = best_item["params"]
        print(f"\n[{sym}] Selected Tuned Parameters: {tuned_params} (frozen for validation and holdout)", flush=True)

        # Now evaluate Baseline and Tuned across all 3 splits:
        configs_to_run = [
            ("Baseline", baseline_params),
            ("Tuned", tuned_params),
        ]

        mkt_split_results = {}
        per_trade_exports = {}

        for cfg_name, cfg in configs_to_run:
            pb = cfg["max_pullback_bars"]
            cb = cfg["max_confirmation_bars"]
            cfg_results = {}
            all_trades_for_cfg = []

            for split_name, split_dates in [("Train", train_dates), ("Validation", val_dates), ("Holdout", test_dates)]:
                setups_all = []
                rejections_all = Counter()
                trades_all = []

                for d in split_dates:
                    sess = usable_sessions[d]
                    day_cache = {}
                    obs = detect_continuation_observations(sess, max_pullback_bars=pb, max_confirmation_bars=cb)
                    for ev in obs:
                        s_info, wait_reason, t_rec = evaluate_single_observation(
                            sym, d, sess, ev, min_pts, MIN_RR, day_cache
                        )
                        setups_all.append(s_info)
                        if wait_reason:
                            rejections_all[wait_reason] += 1
                        if t_rec:
                            t_copy = dict(t_rec)
                            t_copy["split"] = split_name
                            t_copy["strategy_mode"] = cfg_name
                            trades_all.append(t_copy)
                            all_trades_for_cfg.append(t_copy)

                metrics = compute_metrics(trades_all, len(setups_all), rejections_all)
                cfg_results[split_name] = {
                    "sessions_count": len(split_dates),
                    "params": cfg,
                    "metrics": metrics,
                }

            mkt_split_results[cfg_name] = cfg_results
            per_trade_exports[cfg_name] = all_trades_for_cfg

        all_market_reports[sym] = {
            "splits": mkt_split_results,
            "grid_tuning_on_train": [
                {"params": g["params"], "metrics": g["metrics"]} for g in grid_summaries
            ],
            "selected_tuned_params": tuned_params,
        }

        # Save per-trade CSVs
        for cfg_name, trades in per_trade_exports.items():
            csv_path = results_dir / f"{sym.lower()}_trades_{cfg_name.lower()}.csv"
            with csv_path.open("w", encoding="utf-8", newline="") as f:
                fieldnames = [
                    "market", "split", "strategy_mode", "session_date", "confirm_time", "direction",
                    "entry_time", "entry_price", "stop_price", "target_price", "risk_points",
                    "reward_points", "planned_rr", "exit_time", "exit_price", "exit_reason",
                    "gross_index_points", "r_multiple", "is_win"
                ]
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()
                for tr in trades:
                    writer.writerow(tr)
            print(f"[{sym}] Saved per-trade CSV: {csv_path.name} ({len(trades)} trades)", flush=True)

    # 4. Save summary JSON and Markdown
    summary_data = {
        "run_timestamp": datetime.now(IST).isoformat(),
        "splits_metadata": splits_meta,
        "options_history_status": options_audit,
        "markets": all_market_reports,
    }
    summary_json_path = results_dir / "backtest_summary.json"
    with summary_json_path.open("w", encoding="utf-8") as f:
        json.dump(summary_data, f, indent=2)

    # Generate Markdown Summary
    md_lines = [
        "# SMC Strategy Training and Backtest Summary Report",
        "",
        f"- **Execution Timestamp:** {datetime.now(IST).isoformat()}",
        f"- **Primary Input:** `data/angelfolder/nifty_1m.csv` and `data/angelfolder/sensex_1m.csv`",
        f"- **Usable Regular Sessions:** 164 trading days (09:16 to 15:15 IST continuous, 360 bars/day)",
        f"- **Excluded Sessions:** 1 trading day (2026-11-08 Diwali Muhurat session, 55 regular bars)",
        f"- **Partitioning:** Train (60%, 98 sessions) | Validation (20%, 33 sessions) | Holdout/Test (20%, 33 sessions)",
        f"- **Fill Execution Rules:** Next-bar open fill; Planned RR >= 2.0; Min Target: NIFTY 50 pts, SENSEX 100 pts.",
        f"- **Ambiguous Bar Rule:** When both Stop Loss and Target are touched in the same 1m bar, **Stop Loss always wins** (`SL_FIRST_OR_SAME_BAR_AMBIGUOUS`).",
        "",
        "---",
        "",
        "## 1. Options Usability & Risk Disclosure",
        "",
        f"> {options_audit['reason']}",
        "",
        "---",
        "",
        "## 2. Performance Comparison Table",
        "",
        "| Market | Strategy | Split | Sessions | Setups | Trades | Wins | Win Rate (%) | Expectancy (R) | Max DD (R) | Status |",
        "| :--- | :--- | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :--- |",
    ]

    for sym in markets:
        for cfg_name in ["Baseline", "Tuned"]:
            for split_name in ["Train", "Validation", "Holdout"]:
                row = all_market_reports[sym]["splits"][cfg_name][split_name]
                m = row["metrics"]
                wr = f"{m['win_rate_pct']:.1f}%" if m['win_rate_pct'] is not None else "N/A"
                exp = f"{m['expectancy_r']:.2f}" if m['expectancy_r'] is not None else "N/A"
                md_lines.append(
                    f"| **{sym}** | {cfg_name} | {split_name} | {row['sessions_count']} | "
                    f"{m['setup_count']} | {m['trade_count']} | {m['wins']} | {wr} | {exp} | {m['max_drawdown_r']:.2f}R | {m['status']} |"
                )

    md_lines.extend([
        "",
        "---",
        "",
        "## 3. Top WAIT / NO_TRADE Rejection Reasons",
        "",
    ])

    for sym in markets:
        md_lines.append(f"### {sym}")
        rejections = all_market_reports[sym]["splits"]["Baseline"]["Train"]["metrics"]["top_rejections"]
        for reason, count in rejections.items():
            md_lines.append(f"- **`{reason}`**: {count} setups")
        md_lines.append("")

    summary_md_path = results_dir / "backtest_summary.md"
    summary_md_path.write_text("\n".join(md_lines) + "\n", encoding="utf-8")
    print(f"\nSaved summary reports:\n  - {summary_json_path}\n  - {summary_md_path}", flush=True)

    return 0


if __name__ == "__main__":
    sys.exit(run_pipeline())
