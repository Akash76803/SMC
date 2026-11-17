"""Reproducible Volatility-Adaptive (Dynamic ATR) Target Room Backtest.

Compares:
  1. Fixed Targets (Baseline): NIFTY >= 50 pts, SENSEX >= 100 pts, Planned RR >= 2.0.
  2. Dynamic ATR Targets:
     - NIFTY: min_target = max(30.0, round(2.0 * ATR(14), 1)), Planned RR >= 2.0.
     - SENSEX: min_target = max(60.0, round(2.0 * ATR(14), 1)), Planned RR >= 2.0.

Outputs:
  - results/dynamic_target_ab_test/dynamic_target_summary.json
  - results/dynamic_target_ab_test/dynamic_target_summary.md
  - per-market and per-variant trade CSVs.
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
    MIN_RR,
    audit_market_data,
    compute_metrics,
)
from .continuation_evidence_v3 import enrich_continuation
from .continuation_v3 import detect_continuation_observations
from .engine import atr
from .historical_brackets_v313 import paper_outcome

IST = ZoneInfo("Asia/Kolkata")

DYNAMIC_CONFIG = {
    "NIFTY": {"floor": 30.0, "atr_mult": 2.0, "fixed": 50.0},
    "SENSEX": {"floor": 60.0, "atr_mult": 2.0, "fixed": 100.0},
}


def run_dynamic_target_ab_test() -> int:
    base_dir = Path("E:/Project/SMC")
    data_dir = base_dir / "data" / "angelfolder"
    out_dir = base_dir / "results" / "dynamic_target_ab_test"
    out_dir.mkdir(parents=True, exist_ok=True)

    print("=" * 80, flush=True)
    print(" SMC DYNAMIC VOLATILITY-ADAPTIVE TARGET ROOM A/B BACKTEST", flush=True)
    print("=" * 80, flush=True)

    markets = ["NIFTY", "SENSEX"]
    usable_sessions_by_mkt: dict[str, dict[str, list]] = {}

    for sym in markets:
        _, usable = audit_market_data(sym, data_dir)
        usable_sessions_by_mkt[sym] = usable
        print(f"[{sym}] Loaded {len(usable)} usable sessions (360 bars/day).", flush=True)

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

    pb = 12
    cb = 8

    full_report: dict[str, Any] = {
        "run_timestamp": datetime.now(IST).isoformat(),
        "dynamic_rules": DYNAMIC_CONFIG,
        "parameters": {"max_pullback_bars": pb, "max_confirmation_bars": cb, "min_rr": MIN_RR},
        "markets": {},
    }

    modes = [
        ("Fixed_Target", "Fixed points threshold (NIFTY 50, SENSEX 100)"),
        ("Dynamic_ATR_Target", "Dynamic target = max(Floor, 2.0 * ATR(14))"),
    ]

    for sym in markets:
        print(f"\n" + "=" * 60, flush=True)
        print(f" EVALUATING TARGET ROOM ADAPTABILITY: {sym}", flush=True)
        print("=" * 60, flush=True)

        usable_sessions = usable_sessions_by_mkt[sym]
        cfg = DYNAMIC_CONFIG[sym]
        fixed_min = cfg["fixed"]
        floor = cfg["floor"]
        mult = cfg["atr_mult"]

        market_results: dict[str, Any] = {
            "splits": {},
            "modes_full": {},
        }

        trades_all_by_mode: dict[str, list[dict]] = {m[0]: [] for m in modes}
        split_evaluations: dict[str, Any] = {}

        for split_name, split_dates in splits_list:
            split_data: dict[str, dict[str, Any]] = {
                m[0]: {"setups": [], "rejections": Counter(), "trades": []} for m in modes
            }

            for d in split_dates:
                sess = usable_sessions[d]
                obs_list = detect_continuation_observations(sess, max_pullback_bars=pb, max_confirmation_bars=cb)

                for ev in obs_list:
                    confirm_dt_str = sess[ev.confirm_index].timestamp.isoformat()
                    bullish = ev.direction == "BULLISH"
                    entry_ref = sess[ev.confirm_index].close
                    stop_ref = sess[ev.pullback_index].low if bullish else sess[ev.pullback_index].high

                    # Compute ATR(14)
                    atr_val = atr(sess[: ev.confirm_index + 1], length=14)
                    dyn_min = max(floor, round(mult * atr_val, 1)) if atr_val else fixed_min

                    # 1. Mode A: Fixed Target
                    enrich_fixed = enrich_continuation(
                        symbol=sym, candles=sess, observation=ev, min_target_points=fixed_min
                    )
                    targets_f = enrich_fixed.get("index_targets", {}).get("targets", [])
                    t1_f = targets_f[0] if targets_f else None

                    qual_f = False
                    wait_f = None
                    if not t1_f:
                        wait_f = "NO_VALID_OPPOSING_LIQUIDITY_TARGET"
                    elif not t1_f.get("feasible", False):
                        wait_f = f"TARGET_INFEASIBLE_{t1_f.get('reason', 'UNKNOWN')}"
                    elif t1_f.get("index_points", 0) < fixed_min:
                        wait_f = f"TARGET_ROOM_TOO_SMALL_<{fixed_min}PTS"
                    elif t1_f.get("index_rr") is None or t1_f.get("index_rr") < MIN_RR:
                        wait_f = f"PLANNED_RR_BELOW_MINIMUM_<{MIN_RR}:1"
                    else:
                        qual_f = True

                    s_info_f = {
                        "session_date": d, "confirm_time": confirm_dt_str, "direction": ev.direction,
                        "entry_ref": entry_ref, "stop_ref": stop_ref,
                        "target_price": t1_f["price"] if t1_f else None,
                        "min_required": fixed_min, "qualified": qual_f, "wait_reason": wait_f,
                    }
                    split_data["Fixed_Target"]["setups"].append(s_info_f)
                    if wait_f:
                        split_data["Fixed_Target"]["rejections"][wait_f] += 1

                    if qual_f:
                        out_f = paper_outcome(
                            session=sess, confirm_index=ev.confirm_index, direction=ev.direction,
                            stop=stop_ref, target=t1_f["price"], min_points=fixed_min, min_rr=MIN_RR,
                        )
                        if out_f["status"] == "HYPOTHETICAL":
                            risk = out_f["risk_points"]
                            gross = out_f["index_points_gross"]
                            r_mult = round(gross / risk, 4) if risk and risk > 0 else 0.0
                            t_rec_f = {
                                "market": sym, "mode": "Fixed_Target", "split": split_name,
                                "session_date": d, "confirm_time": confirm_dt_str, "direction": ev.direction,
                                "entry_time": out_f["entry_at"], "entry_price": out_f["entry_open"],
                                "stop_price": out_f["stop"], "target_price": out_f["target"],
                                "risk_points": round(risk, 2), "reward_points": round(out_f["reward_points"], 2),
                                "planned_rr": round(out_f["index_rr"], 2), "exit_time": out_f["exit_at"],
                                "exit_price": out_f["exit_reference"], "exit_reason": out_f["exit_reason"],
                                "gross_index_points": round(gross, 2), "r_multiple": r_mult,
                                "is_win": gross > 0, "min_target_used": fixed_min,
                            }
                            split_data["Fixed_Target"]["trades"].append(t_rec_f)
                            trades_all_by_mode["Fixed_Target"].append(t_rec_f)

                    # 2. Mode B: Dynamic ATR Target
                    enrich_dyn = enrich_continuation(
                        symbol=sym, candles=sess, observation=ev, min_target_points=dyn_min
                    )
                    targets_d = enrich_dyn.get("index_targets", {}).get("targets", [])
                    t1_d = targets_d[0] if targets_d else None

                    qual_d = False
                    wait_d = None
                    if not t1_d:
                        wait_d = "NO_VALID_OPPOSING_LIQUIDITY_TARGET"
                    elif not t1_d.get("feasible", False):
                        wait_d = f"TARGET_INFEASIBLE_{t1_d.get('reason', 'UNKNOWN')}"
                    elif t1_d.get("index_points", 0) < dyn_min:
                        wait_d = f"TARGET_ROOM_TOO_SMALL_<{dyn_min:.1f}PTS"
                    elif t1_d.get("index_rr") is None or t1_d.get("index_rr") < MIN_RR:
                        wait_d = f"PLANNED_RR_BELOW_MINIMUM_<{MIN_RR}:1"
                    else:
                        qual_d = True

                    s_info_d = {
                        "session_date": d, "confirm_time": confirm_dt_str, "direction": ev.direction,
                        "entry_ref": entry_ref, "stop_ref": stop_ref,
                        "target_price": t1_d["price"] if t1_d else None,
                        "min_required": dyn_min, "atr14": atr_val,
                        "qualified": qual_d, "wait_reason": wait_d,
                    }
                    split_data["Dynamic_ATR_Target"]["setups"].append(s_info_d)
                    if wait_d:
                        split_data["Dynamic_ATR_Target"]["rejections"][wait_d] += 1

                    if qual_d:
                        out_d = paper_outcome(
                            session=sess, confirm_index=ev.confirm_index, direction=ev.direction,
                            stop=stop_ref, target=t1_d["price"], min_points=dyn_min, min_rr=MIN_RR,
                        )
                        if out_d["status"] == "HYPOTHETICAL":
                            risk = out_d["risk_points"]
                            gross = out_d["index_points_gross"]
                            r_mult = round(gross / risk, 4) if risk and risk > 0 else 0.0
                            t_rec_d = {
                                "market": sym, "mode": "Dynamic_ATR_Target", "split": split_name,
                                "session_date": d, "confirm_time": confirm_dt_str, "direction": ev.direction,
                                "entry_time": out_d["entry_at"], "entry_price": out_d["entry_open"],
                                "stop_price": out_d["stop"], "target_price": out_d["target"],
                                "risk_points": round(risk, 2), "reward_points": round(out_d["reward_points"], 2),
                                "planned_rr": round(out_d["index_rr"], 2), "exit_time": out_d["exit_at"],
                                "exit_price": out_d["exit_reference"], "exit_reason": out_d["exit_reason"],
                                "gross_index_points": round(gross, 2), "r_multiple": r_mult,
                                "is_win": gross > 0, "min_target_used": dyn_min, "atr14": atr_val,
                            }
                            split_data["Dynamic_ATR_Target"]["trades"].append(t_rec_d)
                            trades_all_by_mode["Dynamic_ATR_Target"].append(t_rec_d)

            # Compute split metrics
            split_metrics: dict[str, Any] = {}
            for m_code, _ in modes:
                m_data = split_data[m_code]
                met = compute_metrics(m_data["trades"], len(m_data["setups"]), m_data["rejections"])
                tot_r = round(sum(t["r_multiple"] for t in m_data["trades"]), 3) if m_data["trades"] else 0.0
                split_metrics[m_code] = {
                    "metrics": met,
                    "total_r": tot_r,
                }
            split_evaluations[split_name] = split_metrics

            print(f"  [{split_name} ({len(split_dates)} sessions)]", flush=True)
            for m_code, _ in modes:
                met = split_metrics[m_code]["metrics"]
                wr_str = f"{met['win_rate_pct']:.1f}%" if met['win_rate_pct'] is not None else "N/A"
                exp_str = f"{met['expectancy_r']:.3f}" if met['expectancy_r'] is not None else "N/A"
                print(f"    {m_code:<20}: {met['trade_count']:2d} trades, WR: {wr_str:>6}, Exp: {exp_str:>6}R, Tot: {split_metrics[m_code]['total_r']:+6.2f}R, MaxDD: {met['max_drawdown_r']:4.2f}R", flush=True)

        market_results["splits"] = split_evaluations

        # Compute full dataset metrics
        for m_code, _ in modes:
            tr_list = trades_all_by_mode[m_code]
            setups_cnt = sum(split_evaluations[sp][m_code]["metrics"]["setup_count"] for sp in ["Train", "Validation", "Holdout"])
            met_full = compute_metrics(tr_list, setups_cnt, Counter())
            tot_r_full = round(sum(t["r_multiple"] for t in tr_list), 3) if tr_list else 0.0
            market_results["modes_full"][m_code] = {
                "total_sessions": n_total,
                "metrics": met_full,
                "total_r": tot_r_full,
            }

        full_report["markets"][sym] = market_results

        # Export CSVs
        for m_code, file_suffix in [("Fixed_Target", "fixed"), ("Dynamic_ATR_Target", "dynamic")]:
            csv_path = out_dir / f"{sym.lower()}_trades_{file_suffix}.csv"
            with csv_path.open("w", encoding="utf-8", newline="") as f:
                fields = [
                    "market", "mode", "split", "session_date", "confirm_time", "direction",
                    "entry_time", "entry_price", "stop_price", "target_price", "risk_points",
                    "reward_points", "planned_rr", "exit_time", "exit_price", "exit_reason",
                    "gross_index_points", "r_multiple", "is_win", "min_target_used"
                ]
                w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
                w.writeheader()
                for tr in trades_all_by_mode[m_code]:
                    w.writerow(tr)

    # Save summary JSON
    summary_json_path = out_dir / "dynamic_target_summary.json"
    with summary_json_path.open("w", encoding="utf-8") as f:
        json.dump(full_report, f, indent=2)

    # Generate Markdown Summary
    md_lines = [
        "# SMC Volatility-Adaptive (Dynamic ATR) Target Room Backtest Report",
        "",
        f"- **Execution Timestamp:** {datetime.now(IST).isoformat()}",
        f"- **Dataset:** Audited Angel One 1m cache (`data/angelfolder/`), 164 contiguous regular sessions",
        f"- **Planned Reward-to-Risk Floor:** Strictly $\\ge 2.0$ across all runs",
        f"- **Dynamic Target Formula:**",
        f"  * **NIFTY:** $\\max(30.0,\\; 2.0 \\times ATR(14))$ (vs Fixed 50.0 pts)",
        f"  * **SENSEX:** $\\max(60.0,\\; 2.0 \\times ATR(14))$ (vs Fixed 100.0 pts)",
        f"- **Fill & Exit Semantics:** Next-bar open fill, `SL_FIRST_OR_SAME_BAR_AMBIGUOUS` tie-break, 15:15 EOD exit",
        "",
        "---",
        "",
        "## 1. Head-to-Head Performance Comparison",
        "",
        "| Market | Mode | Split | Sessions | Setups | Trades | Wins / Losses | Win Rate (%) | Exp (R) | Total R | Max DD (R) | Status |",
        "| :--- | :--- | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :--- |",
    ]

    for sym in markets:
        mkt_data = full_report["markets"][sym]
        for m_code, _ in modes:
            for split_name in ["Train", "Validation", "Holdout"]:
                row_m = mkt_data["splits"][split_name][m_code]["metrics"]
                tot_r = mkt_data["splits"][split_name][m_code]["total_r"]
                wr_str = f"{row_m['win_rate_pct']:.1f}%" if row_m['win_rate_pct'] is not None else "N/A"
                exp_str = f"{row_m['expectancy_r']:.3f}" if row_m['expectancy_r'] is not None else "N/A"
                sess_cnt = 98 if split_name == "Train" else (32 if split_name == "Validation" else 34)
                md_lines.append(
                    f"| **{sym}** | **{m_code}** | {split_name} | {sess_cnt} | "
                    f"{row_m['setup_count']} | {row_m['trade_count']} | {row_m['wins']}W / {row_m['losses']}L | "
                    f"{wr_str} | {exp_str} | {tot_r:+.2f}R | {row_m['max_drawdown_r']:.2f}R | {row_m['status']} |"
                )

            # Full row
            f_row = mkt_data["modes_full"][m_code]["metrics"]
            f_tot_r = mkt_data["modes_full"][m_code]["total_r"]
            f_wr = f"{f_row['win_rate_pct']:.1f}%" if f_row['win_rate_pct'] is not None else "N/A"
            f_exp = f"{f_row['expectancy_r']:.3f}" if f_row['expectancy_r'] is not None else "N/A"
            md_lines.append(
                f"| **{sym}** | **{m_code}** | **FULL (164s)** | 164 | "
                f"{f_row['setup_count']} | {f_row['trade_count']} | {f_row['wins']}W / {f_row['losses']}L | "
                f"{f_wr} | {f_exp} | {f_tot_r:+.2f}R | {f_row['max_drawdown_r']:.2f}R | {f_row['status']} |"
            )

    summary_md_path = out_dir / "dynamic_target_summary.md"
    summary_md_path.write_text("\n".join(md_lines) + "\n", encoding="utf-8")
    print(f"\n[Done] Summary saved:\n  - {summary_json_path}\n  - {summary_md_path}", flush=True)

    return 0


if __name__ == "__main__":
    sys.exit(run_dynamic_target_ab_test())

