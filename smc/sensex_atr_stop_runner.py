"""SENSEX ATR-Based Stop Loss Experiment (1.5 x ATR(14)).

Evaluates whether replacing the wide 1m structural pullback swing stop with an
ATR-based stop distance (1.5 x ATR(14)) improves SENSEX performance across 164 sessions
(Train: 98, Validation: 32, Holdout: 34), keeping the 100-point minimum target and
2:1 minimum planned reward-to-risk intact.

Variants evaluated:
  1. Structural_Stop (Baseline): Stop at pullback swing (low/high).
  2. ATR_Stop_1.5x: Stop distance = 1.5 * ATR(14).
  3. Session_Window_Plus_ATR: Session window [09:30, 11:00) / [13:15, 14:45) + ATR stop.

Outputs:
  - results/sensex_atr_stop/sensex_atr_summary.json
  - results/sensex_atr_stop/sensex_atr_summary.md
  - results/sensex_atr_stop/sensex_trades_structural.csv
  - results/sensex_atr_stop/sensex_trades_atr.csv
  - results/sensex_atr_stop/sensex_trades_session_atr.csv
"""
from __future__ import annotations

import csv
import json
import sys
from collections import Counter
from datetime import datetime, time
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from .angelfolder_backtest_runner import (
    MIN_RR,
    audit_market_data,
    compute_metrics,
)
from .continuation_evidence_v3 import enrich_continuation
from .continuation_v3 import detect_continuation_observations
from .engine import atr
from .historical_brackets_v313 import paper_outcome
from .htf_session_gates import evaluate_session_timing_window

IST = ZoneInfo("Asia/Kolkata")
MIN_TARGET_POINTS = 100.0


def run_sensex_atr_experiment() -> int:
    base_dir = Path("E:/Project/SMC")
    data_dir = base_dir / "data" / "angelfolder"
    out_dir = base_dir / "results" / "sensex_atr_stop"
    out_dir.mkdir(parents=True, exist_ok=True)

    print("=" * 75, flush=True)
    print(" SENSEX ATR-BASED STOP EXPERIMENT (1.5 x ATR(14))", flush=True)
    print("=" * 75, flush=True)

    # 1. Audit SENSEX data
    audit, usable_sessions = audit_market_data("SENSEX", data_dir)
    all_dates = sorted(usable_sessions.keys())
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

    pb = 12
    cb = 8

    variants = [
        "Structural_Stop",
        "ATR_Stop_1.5x",
        "Session_Window_Plus_ATR",
    ]

    trades_by_variant: dict[str, list[dict]] = {v: [] for v in variants}
    split_results: dict[str, dict[str, Any]] = {}

    for split_name, split_dates in splits_list:
        split_data: dict[str, dict[str, Any]] = {
            v: {"setups": [], "rejections": Counter(), "trades": []} for v in variants
        }

        for d in split_dates:
            sess = usable_sessions[d]
            day_cache: dict[tuple, Any] = {}
            obs_list = detect_continuation_observations(sess, max_pullback_bars=pb, max_confirmation_bars=cb)

            for ev in obs_list:
                cache_key = (ev.direction, ev.bos_index, ev.pullback_index, ev.confirm_index)
                if cache_key not in day_cache:
                    enrichment = enrich_continuation(symbol="SENSEX", candles=sess, observation=ev)
                    day_cache[cache_key] = enrichment
                else:
                    enrichment = day_cache[cache_key]

                bullish = ev.direction == "BULLISH"
                entry_ref = sess[ev.confirm_index].close
                confirm_time_str = sess[ev.confirm_index].timestamp.isoformat()

                # Structural stop
                struct_stop = sess[ev.pullback_index].low if bullish else sess[ev.pullback_index].high

                # ATR(14) stop
                atr_val = atr(sess[: ev.confirm_index + 1], length=14)
                if atr_val is not None and atr_val > 0:
                    atr_dist = round(1.5 * atr_val, 2)
                    atr_stop = round(entry_ref - atr_dist if bullish else entry_ref + atr_dist, 2)
                else:
                    atr_dist = None
                    atr_stop = None

                targets_ladder = enrichment.get("index_targets", {}).get("targets", [])
                primary_target = targets_ladder[0] if targets_ladder else None

                # 1. Evaluate Structural Stop (Baseline)
                qual_struct = False
                wait_struct = None
                if not primary_target:
                    wait_struct = "NO_VALID_OPPOSING_LIQUIDITY_TARGET"
                elif not primary_target.get("feasible", False):
                    wait_struct = f"TARGET_INFEASIBLE_{primary_target.get('reason', 'UNKNOWN')}"
                elif primary_target.get("index_points", 0) < MIN_TARGET_POINTS:
                    wait_struct = f"TARGET_ROOM_TOO_SMALL_<{MIN_TARGET_POINTS}PTS"
                elif primary_target.get("index_rr") is None or primary_target.get("index_rr") < MIN_RR:
                    wait_struct = f"PLANNED_RR_BELOW_MINIMUM_<{MIN_RR}:1"
                else:
                    qual_struct = True

                s_info_struct = {
                    "session_date": d,
                    "confirm_time": confirm_time_str,
                    "direction": ev.direction,
                    "entry_ref": entry_ref,
                    "stop_ref": struct_stop,
                    "target_price": primary_target["price"] if primary_target else None,
                    "qualified": qual_struct,
                    "wait_reason": wait_struct,
                }
                split_data["Structural_Stop"]["setups"].append(s_info_struct)
                if wait_struct:
                    split_data["Structural_Stop"]["rejections"][wait_struct] += 1

                if qual_struct:
                    out_struct = paper_outcome(
                        session=sess,
                        confirm_index=ev.confirm_index,
                        direction=ev.direction,
                        stop=struct_stop,
                        target=primary_target["price"],
                        min_points=MIN_TARGET_POINTS,
                        min_rr=MIN_RR,
                    )
                    if out_struct["status"] == "HYPOTHETICAL":
                        risk = out_struct["risk_points"]
                        gross = out_struct["index_points_gross"]
                        r_mult = round(gross / risk, 4) if risk and risk > 0 else 0.0
                        t_rec_struct = {
                            "market": "SENSEX",
                            "variant": "Structural_Stop",
                            "split": split_name,
                            "session_date": d,
                            "confirm_time": confirm_time_str,
                            "direction": ev.direction,
                            "entry_time": out_struct["entry_at"],
                            "entry_price": out_struct["entry_open"],
                            "stop_price": out_struct["stop"],
                            "target_price": out_struct["target"],
                            "risk_points": round(risk, 2),
                            "reward_points": round(out_struct["reward_points"], 2),
                            "planned_rr": round(out_struct["index_rr"], 2),
                            "exit_time": out_struct["exit_at"],
                            "exit_price": out_struct["exit_reference"],
                            "exit_reason": out_struct["exit_reason"],
                            "gross_index_points": round(gross, 2),
                            "r_multiple": r_mult,
                            "is_win": gross > 0,
                        }
                        split_data["Structural_Stop"]["trades"].append(t_rec_struct)
                        trades_by_variant["Structural_Stop"].append(t_rec_struct)

                # 2. Evaluate ATR Stop 1.5x
                qual_atr = False
                wait_atr = None
                if not atr_stop:
                    wait_atr = "ATR14_UNAVAILABLE"
                elif not primary_target:
                    wait_atr = "NO_VALID_OPPOSING_LIQUIDITY_TARGET"
                elif not primary_target.get("feasible", False):
                    wait_atr = f"TARGET_INFEASIBLE_{primary_target.get('reason', 'UNKNOWN')}"
                else:
                    target_pts = abs(primary_target["price"] - entry_ref)
                    planned_rr_atr = round(target_pts / atr_dist, 2) if atr_dist and atr_dist > 0 else 0.0
                    if target_pts < MIN_TARGET_POINTS:
                        wait_atr = f"TARGET_ROOM_TOO_SMALL_<{MIN_TARGET_POINTS}PTS"
                    elif planned_rr_atr < MIN_RR:
                        wait_atr = f"PLANNED_RR_BELOW_MINIMUM_<{MIN_RR}:1 (RR={planned_rr_atr})"
                    else:
                        qual_atr = True

                s_info_atr = {
                    "session_date": d,
                    "confirm_time": confirm_time_str,
                    "direction": ev.direction,
                    "entry_ref": entry_ref,
                    "stop_ref": atr_stop,
                    "target_price": primary_target["price"] if primary_target else None,
                    "qualified": qual_atr,
                    "wait_reason": wait_atr,
                }
                split_data["ATR_Stop_1.5x"]["setups"].append(s_info_atr)
                if wait_atr:
                    split_data["ATR_Stop_1.5x"]["rejections"][wait_atr] += 1

                t_rec_atr = None
                if qual_atr:
                    out_atr = paper_outcome(
                        session=sess,
                        confirm_index=ev.confirm_index,
                        direction=ev.direction,
                        stop=atr_stop,
                        target=primary_target["price"],
                        min_points=MIN_TARGET_POINTS,
                        min_rr=MIN_RR,
                    )
                    if out_atr["status"] == "HYPOTHETICAL":
                        risk = out_atr["risk_points"]
                        gross = out_atr["index_points_gross"]
                        r_mult = round(gross / risk, 4) if risk and risk > 0 else 0.0
                        t_rec_atr = {
                            "market": "SENSEX",
                            "variant": "ATR_Stop_1.5x",
                            "split": split_name,
                            "session_date": d,
                            "confirm_time": confirm_time_str,
                            "direction": ev.direction,
                            "entry_time": out_atr["entry_at"],
                            "entry_price": out_atr["entry_open"],
                            "stop_price": out_atr["stop"],
                            "target_price": out_atr["target"],
                            "risk_points": round(risk, 2),
                            "reward_points": round(out_atr["reward_points"], 2),
                            "planned_rr": round(out_atr["index_rr"], 2),
                            "exit_time": out_atr["exit_at"],
                            "exit_price": out_atr["exit_reference"],
                            "exit_reason": out_atr["exit_reason"],
                            "gross_index_points": round(gross, 2),
                            "r_multiple": r_mult,
                            "is_win": gross > 0,
                            "atr14": atr_val,
                        }
                        split_data["ATR_Stop_1.5x"]["trades"].append(t_rec_atr)
                        trades_by_variant["ATR_Stop_1.5x"].append(t_rec_atr)

                # 3. Evaluate Session Window + ATR Stop
                split_data["Session_Window_Plus_ATR"]["setups"].append(s_info_atr)
                if t_rec_atr:
                    entry_dt = datetime.fromisoformat(t_rec_atr["entry_time"])
                    res_win = evaluate_session_timing_window(entry_dt)
                    if res_win.allowed:
                        t_sess_atr = dict(t_rec_atr)
                        t_sess_atr["variant"] = "Session_Window_Plus_ATR"
                        split_data["Session_Window_Plus_ATR"]["trades"].append(t_sess_atr)
                        trades_by_variant["Session_Window_Plus_ATR"].append(t_sess_atr)
                    else:
                        split_data["Session_Window_Plus_ATR"]["rejections"][res_win.block_reason] += 1

        # Compute metrics for this split
        split_metrics = {}
        for v in variants:
            v_data = split_data[v]
            m = compute_metrics(v_data["trades"], len(v_data["setups"]), v_data["rejections"])
            tot_r = round(sum(t["r_multiple"] for t in v_data["trades"]), 3) if v_data["trades"] else 0.0
            split_metrics[v] = {
                "metrics": m,
                "total_r": tot_r,
            }
        split_results[split_name] = split_metrics

        print(f"  [{split_name} ({len(split_dates)} sessions)]", flush=True)
        for v in variants:
            vm = split_metrics[v]["metrics"]
            wr_str = f"{vm['win_rate_pct']:.1f}%" if vm['win_rate_pct'] is not None else "N/A"
            exp_str = f"{vm['expectancy_r']:.3f}" if vm['expectancy_r'] is not None else "N/A"
            print(f"    {v:<23}: {vm['trade_count']:2d} trades, WR: {wr_str:>6}, Exp: {exp_str:>6}R, Tot: {split_metrics[v]['total_r']:+6.2f}R, MaxDD: {vm['max_drawdown_r']:4.2f}R", flush=True)

    # Full metrics
    full_metrics = {}
    for v in variants:
        t_list = trades_by_variant[v]
        setups_cnt = sum(split_results[sp][v]["metrics"]["setup_count"] for sp in ["Train", "Validation", "Holdout"])
        m_full = compute_metrics(t_list, setups_cnt, Counter())
        tot_r_full = round(sum(t["r_multiple"] for t in t_list), 3) if t_list else 0.0
        full_metrics[v] = {
            "metrics": m_full,
            "total_r": tot_r_full,
        }

    full_summary = {
        "run_timestamp": datetime.now(IST).isoformat(),
        "market": "SENSEX",
        "parameters": {"max_pullback_bars": pb, "max_confirmation_bars": cb, "min_target_points": MIN_TARGET_POINTS, "min_rr": MIN_RR},
        "splits": split_results,
        "full_dataset": full_metrics,
    }

    # Save summary JSON
    with (out_dir / "sensex_atr_summary.json").open("w", encoding="utf-8") as f:
        json.dump(full_summary, f, indent=2)

    # Save per-trade CSVs
    fieldnames = [
        "market", "variant", "split", "session_date", "confirm_time", "direction",
        "entry_time", "entry_price", "stop_price", "target_price", "risk_points",
        "reward_points", "planned_rr", "exit_time", "exit_price", "exit_reason",
        "gross_index_points", "r_multiple", "is_win"
    ]
    for v_code, file_suffix in [
        ("Structural_Stop", "structural"),
        ("ATR_Stop_1.5x", "atr"),
        ("Session_Window_Plus_ATR", "session_atr"),
    ]:
        csv_path = out_dir / f"sensex_trades_{file_suffix}.csv"
        with csv_path.open("w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
            w.writeheader()
            for r in trades_by_variant[v_code]:
                w.writerow(r)

    # Generate Markdown Summary
    md_lines = [
        "# SENSEX ATR-Based Stop Loss Experiment Report (1.5 x ATR(14))",
        "",
        f"- **Execution Timestamp:** {datetime.now(IST).isoformat()}",
        f"- **Dataset:** Audited SENSEX 1m cache (`data/angelfolder/sensex_1m.csv`), 164 contiguous regular sessions",
        f"- **Target / Risk Floor:** SENSEX $\\ge 100$ pts minimum target, Planned RR $\\ge 2.0$",
        f"- **Fill & Exit Semantics:** Next-bar open fill, `SL_FIRST_OR_SAME_BAR_AMBIGUOUS` tie-break, 15:15 EOD exit",
        f"- **ATR Stop Definition:** Stop distance is set to $1.5 \\times ATR(14)$ on 1m closed bars at confirmation.",
        "",
        "---",
        "",
        "## 1. Head-to-Head Performance Comparison",
        "",
        "| Variant | Split | Sessions | Setups | Trades | Wins / Losses | Win Rate (%) | Exp (R) | Total R | Max DD (R) | Status |",
        "| :--- | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :--- |",
    ]

    for v in variants:
        for split_name in ["Train", "Validation", "Holdout"]:
            sm = split_results[split_name][v]["metrics"]
            tot_r = split_results[split_name][v]["total_r"]
            wr_str = f"{sm['win_rate_pct']:.1f}%" if sm['win_rate_pct'] is not None else "N/A"
            exp_str = f"{sm['expectancy_r']:.3f}" if sm['expectancy_r'] is not None else "N/A"
            sess_cnt = 98 if split_name == "Train" else (32 if split_name == "Validation" else 34)
            md_lines.append(
                f"| **{v}** | {split_name} | {sess_cnt} | {sm['setup_count']} | {sm['trade_count']} | "
                f"{sm['wins']}W / {sm['losses']}L | {wr_str} | {exp_str} | {tot_r:+.2f}R | {sm['max_drawdown_r']:.2f}R | {sm['status']} |"
            )

        # Full
        fm = full_metrics[v]["metrics"]
        f_tot_r = full_metrics[v]["total_r"]
        f_wr = f"{fm['win_rate_pct']:.1f}%" if fm['win_rate_pct'] is not None else "N/A"
        f_exp = f"{fm['expectancy_r']:.3f}" if fm['expectancy_r'] is not None else "N/A"
        md_lines.append(
            f"| **{v}** | **FULL (164s)** | 164 | {fm['setup_count']} | {fm['trade_count']} | "
            f"{fm['wins']}W / {fm['losses']}L | {f_wr} | {f_exp} | {f_tot_r:+.2f}R | {fm['max_drawdown_r']:.2f}R | {fm['status']} |"
        )

    summary_md_path = out_dir / "sensex_atr_summary.md"
    summary_md_path.write_text("\n".join(md_lines) + "\n", encoding="utf-8")
    print(f"\n[Done] Summary saved:\n  - {out_dir / 'sensex_atr_summary.json'}\n  - {summary_md_path}", flush=True)

    return 0


if __name__ == "__main__":
    sys.exit(run_sensex_atr_experiment())

