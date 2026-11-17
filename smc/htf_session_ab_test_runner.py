"""Reproducible Offline NIFTY & SENSEX HTF Alignment and Session Timing Backtest.

Compares three independent variants against the sentiment-OFF baseline (pb=12, cb=8)
across the audited 164-session dataset (Train: 98, Validation: 32, Holdout: 34):
  1. Only 15m directional alignment (structure_snapshot on closed 15m bars).
  2. Only 1H directional alignment (structure_snapshot on closed 1H bars).
  3. Only entry windows: [09:30, 11:00) or [13:15, 14:45) IST on simulated entry time.

Keeps sentiment OFF throughout this experiment.
Outputs:
  - results/htf_session_ab_test/htf_session_summary.json
  - results/htf_session_ab_test/htf_session_summary.md
  - per-variant trade and blocked trade CSVs for both NIFTY and SENSEX.
"""
from __future__ import annotations

import csv
import json
import sys
import time
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from .angelfolder_backtest_runner import (
    MIN_POINTS,
    MIN_RR,
    audit_market_data,
    audit_option_data_on_disk,
    compute_metrics,
    evaluate_single_observation,
)
from .continuation_v3 import detect_continuation_observations
from .htf_session_gates import (
    build_aggregated_htf_bars,
    evaluate_htf_gate,
    evaluate_session_timing_window,
)

IST = ZoneInfo("Asia/Kolkata")


def run_htf_session_ab_test() -> int:
    base_dir = Path("E:/Project/SMC")
    data_dir = base_dir / "data" / "angelfolder"
    out_dir = base_dir / "results" / "htf_session_ab_test"
    out_dir.mkdir(parents=True, exist_ok=True)

    print("=" * 80, flush=True)
    print(" SMC HTF DIRECTIONAL ALIGNMENT & SESSION TIMING A/B BACKTEST", flush=True)
    print("=" * 80, flush=True)

    markets = ["NIFTY", "SENSEX"]
    usable_sessions_by_mkt: dict[str, dict[str, list]] = {}
    audits: dict[str, Any] = {}

    for sym in markets:
        audit, usable = audit_market_data(sym, data_dir)
        usable_sessions_by_mkt[sym] = usable
        audits[sym] = audit
        print(f"[{sym}] Loaded {len(usable)} usable sessions (360 bars/day).", flush=True)

    options_audit = audit_option_data_on_disk(data_dir.parent)

    # 98/32/34 session partitions
    all_dates = sorted(usable_sessions_by_mkt["NIFTY"].keys())
    n_total = len(all_dates)
    n_train = int(n_total * 0.60)
    n_val = int(n_total * 0.20)

    train_dates = all_dates[:n_train]
    val_dates = all_dates[n_train : n_train + n_val]
    holdout_dates = all_dates[n_train + n_val :]

    splits_list = [
        ("Train", train_dates),
        ("Validation", val_dates),
        ("Holdout", holdout_dates),
    ]

    splits_meta = {
        "total_usable_sessions": n_total,
        "train": {"count": len(train_dates), "start": train_dates[0], "end": train_dates[-1]},
        "validation": {"count": len(val_dates), "start": val_dates[0], "end": val_dates[-1]},
        "holdout": {"count": len(holdout_dates), "start": holdout_dates[0], "end": holdout_dates[-1]},
    }

    pb = 12
    cb = 8

    full_report: dict[str, Any] = {
        "run_timestamp": datetime.now(IST).isoformat(),
        "splits_metadata": splits_meta,
        "parameters": {"max_pullback_bars": pb, "max_confirmation_bars": cb, "min_rr": MIN_RR},
        "options_history_status": options_audit,
        "markets": {},
    }

    variants = [
        ("Baseline", "OFF baseline (no gates)"),
        ("15m_Alignment", "Only 15m HTF directional alignment"),
        ("1H_Alignment", "Only 1H HTF directional alignment"),
        ("Session_Window", "Only entry windows [09:30, 11:00) or [13:15, 14:45) IST"),
    ]

    for sym in markets:
        print(f"\n" + "=" * 60, flush=True)
        print(f" EVALUATING HTF & SESSION TIMING VARIANTS: {sym}", flush=True)
        print("=" * 60, flush=True)

        usable_sessions = usable_sessions_by_mkt[sym]
        min_pts = MIN_POINTS[sym]

        # Pre-build session-aligned 15m and 1H candles
        print(f"[{sym}] Pre-aggregating 15m and 1H bars across 164 sessions...", flush=True)
        all_15m, all_1h = build_aggregated_htf_bars(usable_sessions)
        ts_15m = [c.timestamp for c in all_15m]
        ts_1h = [c.timestamp for c in all_1h]
        print(f"[{sym}] Aggregated: {len(all_15m)} 15m bars, {len(all_1h)} 1H bars.", flush=True)

        market_results: dict[str, Any] = {
            "splits": {},
            "variants_full": {},
        }

        # Data structures to store trades and blocked trades for each variant
        variant_trades_all: dict[str, list[dict]] = {v[0]: [] for v in variants}
        variant_blocked_all: dict[str, list[dict]] = {v[0]: [] for v in variants if v[0] != "Baseline"}

        # First pass: evaluate all baseline trades and enrich with HTF and session gates
        split_evaluations: dict[str, dict[str, Any]] = {}

        for split_name, split_dates in splits_list:
            split_data: dict[str, Any] = {
                "sessions_count": len(split_dates),
                "variants": {v[0]: {"setups": [], "rejections": Counter(), "trades": []} for v in variants},
                "blocked": {v[0]: [] for v in variants if v[0] != "Baseline"},
            }

            for d in split_dates:
                sess = usable_sessions[d]
                day_cache: dict[tuple, Any] = {}
                obs_list = detect_continuation_observations(sess, max_pullback_bars=pb, max_confirmation_bars=cb)

                for ev in obs_list:
                    confirm_dt = sess[ev.confirm_index].timestamp

                    # 1. Evaluate baseline setup and paper fill
                    s_info, wait_reason, t_rec = evaluate_single_observation(
                        sym, d, sess, ev, min_pts, MIN_RR, day_cache
                    )

                    # Evaluate 15m HTF gate at confirmation time (using only closed 15m bars)
                    res_15m = evaluate_htf_gate(ev.direction, all_15m, ts_15m, confirm_dt, "15m")

                    # Evaluate 1H HTF gate at confirmation time (using only closed 1H bars)
                    res_1h = evaluate_htf_gate(ev.direction, all_1h, ts_1h, confirm_dt, "1h")

                    # Setup level logging
                    # Baseline
                    split_data["variants"]["Baseline"]["setups"].append(s_info)
                    if wait_reason:
                        split_data["variants"]["Baseline"]["rejections"][wait_reason] += 1

                    # 15m Variant
                    s_15m = dict(s_info)
                    rej_15m = res_15m.block_reason if not res_15m.allowed else wait_reason
                    s_15m["wait_reason"] = rej_15m
                    split_data["variants"]["15m_Alignment"]["setups"].append(s_15m)
                    if rej_15m:
                        split_data["variants"]["15m_Alignment"]["rejections"][rej_15m] += 1

                    # 1H Variant
                    s_1h = dict(s_info)
                    rej_1h = res_1h.block_reason if not res_1h.allowed else wait_reason
                    s_1h["wait_reason"] = rej_1h
                    split_data["variants"]["1H_Alignment"]["setups"].append(s_1h)
                    if rej_1h:
                        split_data["variants"]["1H_Alignment"]["rejections"][rej_1h] += 1

                    # If trade passed baseline, evaluate gate decisions for executed trade
                    if t_rec:
                        t_base = dict(t_rec)
                        t_base["split"] = split_name
                        t_base["market"] = sym
                        t_base["htf_15m_bias"] = res_15m.htf_bias
                        t_base["htf_15m_state"] = res_15m.state
                        t_base["htf_1h_bias"] = res_1h.htf_bias
                        t_base["htf_1h_state"] = res_1h.state

                        entry_dt = datetime.fromisoformat(t_rec["entry_time"])
                        res_session = evaluate_session_timing_window(entry_dt)
                        t_base["session_window_status"] = res_session.status

                        # Record baseline trade
                        split_data["variants"]["Baseline"]["trades"].append(t_base)
                        variant_trades_all["Baseline"].append(t_base)

                        # Variant 1: 15m Alignment
                        if res_15m.allowed:
                            t_15m = dict(t_base)
                            split_data["variants"]["15m_Alignment"]["trades"].append(t_15m)
                            variant_trades_all["15m_Alignment"].append(t_15m)
                        else:
                            blocked_15m_item = {
                                "market": sym,
                                "split": split_name,
                                "session_date": d,
                                "confirm_time": t_base["confirm_time"],
                                "direction": ev.direction,
                                "htf_timeframe": "15m",
                                "htf_bias": res_15m.htf_bias,
                                "htf_state": res_15m.state,
                                "block_reason": res_15m.block_reason,
                                "closed_htf_bars": res_15m.closed_htf_bars_count,
                                "baseline_entry_time": t_base["entry_time"],
                                "baseline_entry_price": t_base["entry_price"],
                                "baseline_exit_time": t_base["exit_time"],
                                "baseline_exit_price": t_base["exit_price"],
                                "baseline_exit_reason": t_base["exit_reason"],
                                "baseline_gross_points": t_base["gross_index_points"],
                                "baseline_r": t_base["r_multiple"],
                                "baseline_is_win": t_base["is_win"],
                            }
                            split_data["blocked"]["15m_Alignment"].append(blocked_15m_item)
                            variant_blocked_all["15m_Alignment"].append(blocked_15m_item)

                        # Variant 2: 1H Alignment
                        if res_1h.allowed:
                            t_1h = dict(t_base)
                            split_data["variants"]["1H_Alignment"]["trades"].append(t_1h)
                            variant_trades_all["1H_Alignment"].append(t_1h)
                        else:
                            blocked_1h_item = {
                                "market": sym,
                                "split": split_name,
                                "session_date": d,
                                "confirm_time": t_base["confirm_time"],
                                "direction": ev.direction,
                                "htf_timeframe": "1h",
                                "htf_bias": res_1h.htf_bias,
                                "htf_state": res_1h.state,
                                "block_reason": res_1h.block_reason,
                                "closed_htf_bars": res_1h.closed_htf_bars_count,
                                "baseline_entry_time": t_base["entry_time"],
                                "baseline_entry_price": t_base["entry_price"],
                                "baseline_exit_time": t_base["exit_time"],
                                "baseline_exit_price": t_base["exit_price"],
                                "baseline_exit_reason": t_base["exit_reason"],
                                "baseline_gross_points": t_base["gross_index_points"],
                                "baseline_r": t_base["r_multiple"],
                                "baseline_is_win": t_base["is_win"],
                            }
                            split_data["blocked"]["1H_Alignment"].append(blocked_1h_item)
                            variant_blocked_all["1H_Alignment"].append(blocked_1h_item)

                        # Variant 3: Session Timing Window (evaluated at entry time)
                        if res_session.allowed:
                            t_sess = dict(t_base)
                            split_data["variants"]["Session_Window"]["trades"].append(t_sess)
                            variant_trades_all["Session_Window"].append(t_sess)
                        else:
                            blocked_sess_item = {
                                "market": sym,
                                "split": split_name,
                                "session_date": d,
                                "confirm_time": t_base["confirm_time"],
                                "direction": ev.direction,
                                "entry_time": t_base["entry_time"],
                                "session_status": res_session.status,
                                "block_reason": res_session.block_reason,
                                "baseline_entry_price": t_base["entry_price"],
                                "baseline_exit_time": t_base["exit_time"],
                                "baseline_exit_price": t_base["exit_price"],
                                "baseline_exit_reason": t_base["exit_reason"],
                                "baseline_gross_points": t_base["gross_index_points"],
                                "baseline_r": t_base["r_multiple"],
                                "baseline_is_win": t_base["is_win"],
                            }
                            split_data["blocked"]["Session_Window"].append(blocked_sess_item)
                            variant_blocked_all["Session_Window"].append(blocked_sess_item)

                    # Session window setup level tracking
                    s_sess = dict(s_info)
                    # Note: session window is evaluated on entry time of valid trade setups
                    split_data["variants"]["Session_Window"]["setups"].append(s_sess)
                    if wait_reason:
                        split_data["variants"]["Session_Window"]["rejections"][wait_reason] += 1

            # Compute split metrics for all variants
            split_metrics: dict[str, Any] = {}
            for v_code, _ in variants:
                v_data = split_data["variants"][v_code]
                m = compute_metrics(v_data["trades"], len(v_data["setups"]), v_data["rejections"])
                tot_r = round(sum(t["r_multiple"] for t in v_data["trades"]), 3) if v_data["trades"] else 0.0

                b_list = split_data["blocked"].get(v_code, [])
                bw_count = sum(1 for b in b_list if b["baseline_is_win"])
                bw_r = sum(b["baseline_r"] for b in b_list if b["baseline_is_win"])
                bl_count = sum(1 for b in b_list if not b["baseline_is_win"])
                bl_r = sum(b["baseline_r"] for b in b_list if not b["baseline_is_win"])

                split_metrics[v_code] = {
                    "metrics": m,
                    "total_r": tot_r,
                    "blocked_baseline": {
                        "total_blocked": len(b_list),
                        "blocked_winners": {"count": bw_count, "total_r": round(bw_r, 3)},
                        "blocked_losers": {"count": bl_count, "total_r": round(bl_r, 3)},
                        "net_blocked_r": round(bw_r + bl_r, 3),
                        "reasons": dict(Counter(b["block_reason"] for b in b_list)),
                    } if v_code != "Baseline" else None,
                }

            split_evaluations[split_name] = split_metrics

            print(f"  [{split_name} ({len(split_dates)} sessions)]", flush=True)
            for v_code, _ in variants:
                vm = split_metrics[v_code]["metrics"]
                wr_str = f"{vm['win_rate_pct']:.1f}%" if vm['win_rate_pct'] is not None else "N/A"
                exp_str = f"{vm['expectancy_r']:.3f}" if vm['expectancy_r'] is not None else "N/A"
                b_info = split_metrics[v_code]["blocked_baseline"]
                b_str = f"Blocked: {b_info['total_blocked']} (W: {b_info['blocked_winners']['count']}, L: {b_info['blocked_losers']['count']})" if b_info else "Baseline"
                print(f"    {v_code:<15}: {vm['trade_count']:2d} trades, WR: {wr_str:>6}, Exp: {exp_str:>6}R, Tot: {split_metrics[v_code]['total_r']:+6.2f}R, MaxDD: {vm['max_drawdown_r']:4.2f}R | {b_str}", flush=True)

        market_results["splits"] = split_evaluations

        # Compute full dataset metrics across 164 sessions
        for v_code, _ in variants:
            trades_v = variant_trades_all[v_code]
            setups_cnt = sum(split_evaluations[sp][v_code]["metrics"]["setup_count"] for sp in ["Train", "Validation", "Holdout"])
            m_full = compute_metrics(trades_v, setups_cnt, Counter())
            tot_r_full = round(sum(t["r_multiple"] for t in trades_v), 3) if trades_v else 0.0

            b_full = variant_blocked_all.get(v_code, [])
            bw_cnt = sum(1 for b in b_full if b["baseline_is_win"])
            bw_r = sum(b["baseline_r"] for b in b_full if b["baseline_is_win"])
            bl_cnt = sum(1 for b in b_full if not b["baseline_is_win"])
            bl_r = sum(b["baseline_r"] for b in b_full if not b["baseline_is_win"])

            market_results["variants_full"][v_code] = {
                "total_sessions": n_total,
                "metrics": m_full,
                "total_r": tot_r_full,
                "blocked_baseline": {
                    "total_blocked": len(b_full),
                    "blocked_winners": {"count": bw_cnt, "total_r": round(bw_r, 3)},
                    "blocked_losers": {"count": bl_cnt, "total_r": round(bl_r, 3)},
                    "net_blocked_r": round(bw_r + bl_r, 3),
                    "reasons": dict(Counter(b["block_reason"] for b in b_full)),
                } if v_code != "Baseline" else None,
            }

        full_report["markets"][sym] = market_results

        # Export CSVs for this market
        # 1. Baseline trades
        base_csv = out_dir / f"{sym.lower()}_trades_baseline.csv"
        with base_csv.open("w", encoding="utf-8", newline="") as f:
            fields = [
                "market", "split", "session_date", "confirm_time", "direction",
                "htf_15m_bias", "htf_15m_state", "htf_1h_bias", "htf_1h_state",
                "session_window_status", "entry_time", "entry_price", "stop_price",
                "target_price", "risk_points", "reward_points", "planned_rr",
                "exit_time", "exit_price", "exit_reason", "gross_index_points", "r_multiple", "is_win"
            ]
            w = csv.DictWriter(f, fieldnames=fields)
            w.writeheader()
            for tr in variant_trades_all["Baseline"]:
                w.writerow(tr)

        # 2. 15m Variant Trades and Blocked
        tr_15m_csv = out_dir / f"{sym.lower()}_trades_15m.csv"
        with tr_15m_csv.open("w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=fields)
            w.writeheader()
            for tr in variant_trades_all["15m_Alignment"]:
                w.writerow(tr)

        blk_15m_csv = out_dir / f"{sym.lower()}_blocked_15m.csv"
        with blk_15m_csv.open("w", encoding="utf-8", newline="") as f:
            blk_fields = [
                "market", "split", "session_date", "confirm_time", "direction",
                "htf_timeframe", "htf_bias", "htf_state", "block_reason", "closed_htf_bars",
                "baseline_entry_time", "baseline_entry_price", "baseline_exit_time",
                "baseline_exit_price", "baseline_exit_reason", "baseline_gross_points",
                "baseline_r", "baseline_is_win"
            ]
            w = csv.DictWriter(f, fieldnames=blk_fields)
            w.writeheader()
            for r in variant_blocked_all["15m_Alignment"]:
                w.writerow(r)

        # 3. 1H Variant Trades and Blocked
        tr_1h_csv = out_dir / f"{sym.lower()}_trades_1h.csv"
        with tr_1h_csv.open("w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=fields)
            w.writeheader()
            for tr in variant_trades_all["1H_Alignment"]:
                w.writerow(tr)

        blk_1h_csv = out_dir / f"{sym.lower()}_blocked_1h.csv"
        with blk_1h_csv.open("w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=blk_fields)
            w.writeheader()
            for r in variant_blocked_all["1H_Alignment"]:
                w.writerow(r)

        # 4. Session Window Variant Trades and Blocked
        tr_sess_csv = out_dir / f"{sym.lower()}_trades_session_window.csv"
        with tr_sess_csv.open("w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=fields)
            w.writeheader()
            for tr in variant_trades_all["Session_Window"]:
                w.writerow(tr)

        blk_sess_csv = out_dir / f"{sym.lower()}_blocked_session_window.csv"
        with blk_sess_csv.open("w", encoding="utf-8", newline="") as f:
            blk_sess_fields = [
                "market", "split", "session_date", "confirm_time", "direction",
                "entry_time", "session_status", "block_reason",
                "baseline_entry_price", "baseline_exit_time", "baseline_exit_price",
                "baseline_exit_reason", "baseline_gross_points", "baseline_r", "baseline_is_win"
            ]
            w = csv.DictWriter(f, fieldnames=blk_sess_fields)
            w.writeheader()
            for r in variant_blocked_all["Session_Window"]:
                w.writerow(r)

        print(f"[{sym}] Exported CSVs to {out_dir.name}:", flush=True)
        print(f"  - Baseline: {len(variant_trades_all['Baseline'])} trades", flush=True)
        print(f"  - 15m Variant: {len(variant_trades_all['15m_Alignment'])} trades, {len(variant_blocked_all['15m_Alignment'])} blocked", flush=True)
        print(f"  - 1H Variant: {len(variant_trades_all['1H_Alignment'])} trades, {len(variant_blocked_all['1H_Alignment'])} blocked", flush=True)
        print(f"  - Session Window: {len(variant_trades_all['Session_Window'])} trades, {len(variant_blocked_all['Session_Window'])} blocked", flush=True)

    # Save summary JSON
    summary_json_path = out_dir / "htf_session_summary.json"
    with summary_json_path.open("w", encoding="utf-8") as f:
        json.dump(full_report, f, indent=2)

    # Generate Markdown Summary
    md_lines = [
        "# SMC HTF Alignment and Session Timing A/B Backtest Report",
        "",
        f"- **Execution Timestamp:** {datetime.now(IST).isoformat()}",
        f"- **Dataset:** Audited Angel One 1m cache (`data/angelfolder/`), 164 contiguous regular sessions",
        f"- **Session Cutoff:** 09:16 to 15:15 IST (strictly 360 bars/day)",
        f"- **Session Partitions:** Train (60%, 98 sess) | Validation (20%, 32 sess) | Holdout (20%, 34 sess)",
        f"- **Target / Risk Floor:** NIFTY $\\ge 50$ pts, SENSEX $\\ge 100$ pts, Planned RR $\\ge 2.0$",
        f"- **Fill & Exit Semantics:** Next-bar open fill, `SL_FIRST_OR_SAME_BAR_AMBIGUOUS` tie-break, 15:15 EOD exit",
        f"- **Sentiment Gate:** **OFF** across all variants in this experiment",
        "",
        "---",
        "",
        "## 1. Variant Definitions & Directional Rules",
        "",
        "1. **Baseline (OFF):** Unfiltered continuation strategy (`max_pullback=12, max_confirmation=8`).",
        "2. **Variant 1 (15m Alignment):** 15m bars built from audited 1m candles (24 bars/session). "
        "At setup confirmation, only closed 15m bars (`timestamp <= confirm_time`) are evaluated. "
        "HTF bias is the last confirmed external structural break via `smc.market_context_v310.structure_snapshot`. "
        "Allows trade ONLY if `15m_bias == setup_direction`.",
        "3. **Variant 2 (1H Alignment):** 1H (60m) bars built from audited 1m candles (6 bars/session). "
        "At setup confirmation, only closed 1H bars (`timestamp <= confirm_time`) are evaluated. "
        "Allows trade ONLY if `1H_bias == setup_direction`.",
        "4. **Variant 3 (Session Window):** Evaluated strictly at simulated next-bar entry time. "
        "Allows trade ONLY if `entry_time` falls within `[09:30, 11:00)` or `[13:15, 14:45)` IST. "
        "Blocks early morning noise (<09:30), lunchtime chop [11:00, 13:15), and late rush (>=14:45).",
        "",
        "> [!IMPORTANT]",
        "> **Exploratory Holdout Status:** The Holdout split (sessions 131–164) is exploratory. "
        "> All rules remain frozen for final verification on future unseen sessions.",
        "",
        "---",
        "",
        "## 2. Performance Comparison Table",
        "",
        "| Market | Variant | Split | Sessions | Setups | Trades | Wins / Losses | Win Rate (%) | Exp (R) | Total R | Max DD (R) | Status |",
        "| :--- | :--- | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :--- |",
    ]

    for sym in markets:
        mkt_data = full_report["markets"][sym]
        for v_code, _ in variants:
            for split_name in ["Train", "Validation", "Holdout"]:
                row_m = mkt_data["splits"][split_name][v_code]["metrics"]
                tot_r = mkt_data["splits"][split_name][v_code]["total_r"]
                wr_str = f"{row_m['win_rate_pct']:.1f}%" if row_m['win_rate_pct'] is not None else "N/A"
                exp_str = f"{row_m['expectancy_r']:.3f}" if row_m['expectancy_r'] is not None else "N/A"
                md_lines.append(
                    f"| **{sym}** | **{v_code}** | {split_name} | {len(train_dates) if split_name=='Train' else (len(val_dates) if split_name=='Validation' else len(holdout_dates))} | "
                    f"{row_m['setup_count']} | {row_m['trade_count']} | {row_m['wins']}W / {row_m['losses']}L | "
                    f"{wr_str} | {exp_str} | {tot_r:+.2f}R | {row_m['max_drawdown_r']:.2f}R | {row_m['status']} |"
                )

            # Full row
            f_row = mkt_data["variants_full"][v_code]["metrics"]
            f_tot_r = mkt_data["variants_full"][v_code]["total_r"]
            f_wr = f"{f_row['win_rate_pct']:.1f}%" if f_row['win_rate_pct'] is not None else "N/A"
            f_exp = f"{f_row['expectancy_r']:.3f}" if f_row['expectancy_r'] is not None else "N/A"
            md_lines.append(
                f"| **{sym}** | **{v_code}** | **FULL (164s)** | 164 | "
                f"{f_row['setup_count']} | {f_row['trade_count']} | {f_row['wins']}W / {f_row['losses']}L | "
                f"{f_wr} | {f_exp} | {f_tot_r:+.2f}R | {f_row['max_drawdown_r']:.2f}R | {f_row['status']} |"
            )

    md_lines.extend([
        "",
        "---",
        "",
        "## 3. Impact on Baseline Trades: Blocked Winners vs Blocked Losers",
        "",
        "| Market | Variant | Split | Total Blocked | Blocked Winners (Missed R) | Blocked Losers (Saved R) | Net R Impact | Block Reasons |",
        "| :--- | :--- | :--- | :---: | :---: | :---: | :---: | :--- |",
    ])

    for sym in markets:
        mkt_data = full_report["markets"][sym]
        for v_code, _ in variants[1:]:
            for split_name in ["Train", "Validation", "Holdout"]:
                b_info = mkt_data["splits"][split_name][v_code]["blocked_baseline"]
                bw = b_info["blocked_winners"]
                bl = b_info["blocked_losers"]
                reasons_str = ", ".join(f"`{k}`: {v}" for k, v in b_info["reasons"].items()) if b_info["reasons"] else "None"
                md_lines.append(
                    f"| **{sym}** | **{v_code}** | {split_name} | {b_info['total_blocked']} | "
                    f"{bw['count']} ({bw['total_r']:+.2f} R) | {bl['count']} ({bl['total_r']:+.2f} R) | "
                    f"**{b_info['net_blocked_r']:+.2f} R** | {reasons_str} |"
                )

            # Full
            tot_b = mkt_data["variants_full"][v_code]["blocked_baseline"]
            bw_tot = tot_b["blocked_winners"]
            bl_tot = tot_b["blocked_losers"]
            tot_reasons_str = ", ".join(f"`{k}`: {v}" for k, v in tot_b["reasons"].items())
            md_lines.append(
                f"| **{sym}** | **{v_code}** | **FULL (164s)** | **{tot_b['total_blocked']}** | "
                f"**{bw_tot['count']} ({bw_tot['total_r']:+.2f} R)** | **{bl_tot['count']} ({bl_tot['total_r']:+.2f} R)** | "
                f"**{tot_b['net_blocked_r']:+.2f} R** | {tot_reasons_str} |"
            )

    summary_md_path = out_dir / "htf_session_summary.md"
    summary_md_path.write_text("\n".join(md_lines) + "\n", encoding="utf-8")
    print(f"\n[Done] Summary reports saved:\n  - {summary_json_path}\n  - {summary_md_path}", flush=True)

    return 0


if __name__ == "__main__":
    sys.exit(run_htf_session_ab_test())

