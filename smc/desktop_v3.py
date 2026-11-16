"""Offline desktop research viewer for V3 replay outputs.

No brokerage connectivity, order buttons, live quotes, or P&L claims.
Launch: python -m smc.desktop_v3
"""
from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from .continuation_v3 import detect_continuation_observations
from .csv_data import read_candles_csv
from .models import Candle


@dataclass(frozen=True)
class SessionView:
    date: str
    candles: tuple[Candle, ...]
    observations: tuple[dict[str, Any], ...]
    continuations: tuple[dict[str, Any], ...] = ()


def load_research_sessions(csv_path: str | Path, results_dir: str | Path) -> tuple[SessionView, ...]:
    """Group actual 1m candles by local session date; attach same-date JSON only.

    CSV rows must already be normalized/audited. Never manufacture gaps or
    silently match a replay from another date.
    """
    candles = read_candles_csv(csv_path)
    by_day: dict[str, list[Candle]] = {}
    for candle in candles:
        day = candle.timestamp.date().isoformat()
        by_day.setdefault(day, []).append(candle)
    output = []
    for day, session in sorted(by_day.items()):
        observations: tuple[dict[str, Any], ...] = ()
        path = Path(results_dir) / ("replay_" + day + ".json")
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8-sig"))
            if data.get("research_only") is not True or data.get("live_orders_enabled") is not False:
                raise ValueError("UNSAFE_OR_UNKNOWN_REPLAY: " + str(path))
            if data.get("observed_bars") != len(session):
                raise ValueError("REPLAY_SESSION_LENGTH_MISMATCH: " + str(path))
            found = data.get("observations", [])
            if not isinstance(found, list):
                raise ValueError("INVALID_REPLAY_OBSERVATIONS")
            for item in found:
                if not isinstance(item, dict) or not item.get("timestamp", "").startswith(day):
                    raise ValueError("CROSS_SESSION_REPLAY_OBSERVATION")
            observations = tuple(found)
        continuations = tuple(x.as_dict(session) for x in
                              detect_continuation_observations(session))
        output.append(SessionView(day, tuple(session), observations, continuations))
    return tuple(output)


def summary_for_session(view: SessionView) -> dict[str, Any]:
    """Summary is deliberately not trade performance or option P&L."""
    terminal_causes: dict[str, int] = {}
    for obs in view.observations:
        cause = obs.get("terminal_cause") or (obs.get("diagnostics") or {}).get("entry_reason")
        cause = cause or "UNKNOWN"
        terminal_causes[cause] = terminal_causes.get(cause, 0) + 1
    return {
        "session": view.date,
        "bars": len(view.candles),
        "open": view.candles[0].open,
        "high": max(c.high for c in view.candles),
        "low": min(c.low for c in view.candles),
        "close": view.candles[-1].close,
        "observations": len(view.observations),
        "continuation_research": len(view.continuations),
        "terminal_causes": terminal_causes,
        "research_only": True,
    }


def launch(csv_path: str | Path, results_dir: str | Path) -> None:
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk

    root = tk.Tk()
    root.title("SMC Terminal | Offline Research Viewer")
    root.geometry("1230x790")
    root.minsize(870, 600)
    root.configure(bg="#101828")
    state: dict[str, Any] = {"sessions": (), "current": None, "selected": None, "focus": None}

    header = tk.Frame(root, bg="#101828", padx=18, pady=13)
    header.pack(fill="x")
    tk.Label(header, text="SMC  /  HISTORICAL RESEARCH", bg="#101828",
             fg="#f8fafc", font=("Segoe UI", 19, "bold")).pack(side="left")
    tk.Label(header, text="OFFLINE  |  NO LIVE ORDERS", bg="#101828",
             fg="#fbbf24", font=("Segoe UI", 10, "bold")).pack(side="right")

    toolbar = tk.Frame(root, bg="#1c2940", padx=14, pady=10)
    toolbar.pack(fill="x")
    tk.Label(toolbar, text="Trading session", bg="#1c2940", fg="#dbeafe").pack(side="left")
    selected_day = tk.StringVar()
    session_picker = ttk.Combobox(toolbar, state="readonly", width=16, textvariable=selected_day)
    session_picker.pack(side="left", padx=10)
    summary_text = tk.StringVar(value="Select a session to inspect historical OHLC")
    tk.Label(toolbar, textvariable=summary_text, bg="#1c2940",
             fg="#dbeafe", font=("Consolas", 10)).pack(side="left", padx=12)

    main = tk.PanedWindow(root, orient=tk.VERTICAL, bg="#101828",
                          sashwidth=7, sashrelief="flat")
    main.pack(fill="both", expand=True, padx=14, pady=12)
    top = tk.Frame(main, bg="#182337")
    chart = tk.Canvas(top, bg="#182337", highlightthickness=0)
    chart.pack(fill="both", expand=True)
    main.add(top, height=440, minsize=180)
    bottom = tk.Frame(main, bg="#111c2e")
    main.add(bottom, minsize=150)
    tk.Label(bottom, text="REVERSAL + CONTINUATION RESEARCH / NO TRADE SIGNALS",
             bg="#111c2e", fg="#fbbf24", anchor="w",
             font=("Segoe UI", 10, "bold")).pack(fill="x", padx=10, pady=6)
    columns = ("time", "direction", "status", "stage", "cause")
    tree = ttk.Treeview(bottom, columns=columns, show="headings", height=7)
    for col, width in (("time", 145), ("direction", 95), ("status", 95),
                       ("stage", 220), ("cause", 280)):
        tree.heading(col, text=col.upper())
        tree.column(col, width=width, anchor="w", stretch=True)
    tree.pack(fill="both", expand=True, padx=10)
    detail = tk.StringVar(value="Select a terminal event to inspect its evidence")
    tk.Label(bottom, textvariable=detail, bg="#111c2e", fg="#e2e8f0",
             font=("Consolas", 10), anchor="w", justify="left",
             wraplength=1120).pack(fill="x", padx=10, pady=9)

    def draw(event=None):
        chart.delete("all")
        view: SessionView | None = state["current"]
        if view is None:
            chart.create_text(30, 40, anchor="w", fill="#f8fafc",
                              text="Load validated candles and optional replay JSON.")
            return
        focus = state["focus"]
        if focus is None:
            bars = view.candles[-min(100, len(view.candles)):]
        else:
            start = max(0, min(focus - 50, max(0, len(view.candles) - 100)))
            bars = view.candles[start:start + 100]
        w = max(chart.winfo_width(), 400)
        h = max(chart.winfo_height(), 180)
        left, right, top_y, bottom_y = 70, 80, 36, 42
        ph = max(10, h - top_y - bottom_y)
        pw = max(20, w - left - right)
        hi = max(c.high for c in bars)
        lo = min(c.low for c in bars)
        extent = max(hi - lo, 0.01)
        margin = extent * 0.06
        hi, lo = hi + margin, lo - margin
        def y(price):
            return top_y + (hi - price) / (hi - lo) * ph
        for step in range(6):
            value = lo + (hi - lo) * step / 5
            yp = y(value)
            chart.create_line(left, yp, w - right, yp, fill="#273951")
            chart.create_text(left - 8, yp, text=f"{value:,.1f}",
                              fill="#94a3b8", anchor="e", font=("Consolas", 9))
        dx = pw / len(bars)
        candle_width = max(2, min(10, dx * 0.65))
        for i, candle in enumerate(bars):
            x = left + (i + 0.5) * dx
            color = "#22c55e" if candle.close >= candle.open else "#fb7185"
            chart.create_line(x, y(candle.high), x, y(candle.low), fill=color, width=1)
            a, b = y(candle.open), y(candle.close)
            chart.create_rectangle(x - candle_width / 2, min(a, b),
                                   x + candle_width / 2, max(a + 1, b),
                                   fill=color, outline=color)
        # Only plot events belonging to the visible 100-bar window.
        first = bars[0].timestamp
        event_by_time = {c.timestamp.isoformat(): i for i, c in enumerate(bars)}
        for obs in (*view.observations, *view.continuations):
            index = event_by_time.get(obs.get("timestamp"))
            if index is None:
                continue
            x = left + (index + 0.5) * dx
            color = "#38bdf8" if obs.get("source") == "CONTINUATION_RESEARCH" else "#eab308"
            chart.create_line(x, top_y, x, top_y + ph, fill=color, dash=(3, 4))
        chart.create_text(left, 13, anchor="w", fill="#f8fafc",
                          font=("Segoe UI", 11, "bold"),
                          text=f"NIFTY  |  {view.date}  |  Last {len(bars)} × 1m CLOSED candles")
        chart.create_text(w - 10, 13, anchor="e", fill="#fbbf24",
                          text="Yellow = reversal | Blue = continuation research (no orders)")
        chart.create_text(left, h - 14, anchor="w", fill="#94a3b8",
                          text=first.strftime("%H:%M"))
        chart.create_text(w - right, h - 14, anchor="e", fill="#94a3b8",
                          text=bars[-1].timestamp.strftime("%H:%M"))

    def choose_session(event=None):
        date = selected_day.get()
        view = next((s for s in state["sessions"] if s.date == date), None)
        state["current"] = view
        state["focus"] = None
        tree.delete(*tree.get_children())
        state["visible_events"] = ()
        if view is None:
            draw()
            return
        s = summary_for_session(view)
        summary_text.set(
            f"O {s['open']:.1f}  H {s['high']:.1f}  L {s['low']:.1f}  "
            f"C {s['close']:.1f}  |  {s['observations']} reversal / "
            f"{s['continuation_research']} continuation")
        state["visible_events"] = tuple(sorted(
            (*view.observations, *view.continuations),
            key=lambda o: o.get("timestamp", "")))
        for idx, obs in enumerate(state["visible_events"]):
            tree.insert("", "end", iid=str(idx),
                        values=(obs.get("timestamp", "")[11:19],
                                obs.get("direction") or "—",
                                obs.get("status") or "—",
                                obs.get("reason") or "—",
                                obs.get("terminal_cause") or "—"))
        detail.set("Select an event. All observations are research-only; no trade execution.")
        draw()

    def select_event(event=None):
        view = state["current"]
        selection = tree.selection()
        if view is None or not selection:
            return
        obs = state["visible_events"][int(selection[0])
        at = obs.get("timestamp")
        state["focus"] = next((i for i, c in enumerate(view.candles)
                               if c.timestamp.isoformat() == at), None)
        draw()
        diag = obs.get("diagnostics") or {}
        detail.set(
            f"Event {obs.get('timestamp', '')} | "
            f"Entry state: {diag.get('entry_state', 'UNVERIFIED')} | "
            f"Cause: {obs.get('terminal_cause') or diag.get('entry_reason') or 'UNKNOWN'} | "
            f"HTF: {diag.get('htf_alignment', 'UNVERIFIED')} | "
            f"Target: {diag.get('nearest_target_reason', 'UNVERIFIED')} | "
            f"Pending: {', '.join(diag.get('pending_stages') or []) or 'none'}")
    tree.bind("<<TreeviewSelect>>", select_event)
    session_picker.bind("<<ComboboxSelected>>", choose_session)
    chart.bind("<Configure>", draw)

    def load():
        try:
            sessions = load_research_sessions(csv_path, results_dir)
        except (OSError, ValueError, json.JSONDecodeError) as error:
            messagebox.showerror("Historical data rejected", str(error))
            return
        state["sessions"] = sessions
        session_picker["values"] = [s.date for s in sessions]
        if sessions:
            selected_day.set(sessions[-1].date)
            choose_session()

    def show_close():
        state["focus"] = None
        draw()

    tk.Button(toolbar, text="Latest candles", command=show_close, bg="#475569",
              fg="#ffffff", relief="flat", padx=12).pack(side="right", padx=6)
    tk.Button(toolbar, text="Reload", command=load, bg="#2563eb",
              fg="#ffffff", relief="flat", padx=12).pack(side="right")
    load()
    root.mainloop()


def main():
    p = argparse.ArgumentParser(description="Offline, research-only SMC desktop dashboard")
    p.add_argument("--ltf", default="data/nifty_multi_regular_1m.csv",
                   help="Verified timestamped 1m CSV")
    p.add_argument("--results-dir", default="results/v38_sessions",
                   help="Folder with replay_YYYY-MM-DD.json files")
    args = p.parse_args()
    launch(args.ltf, args.results_dir)


if __name__ == "__main__":
    main()
