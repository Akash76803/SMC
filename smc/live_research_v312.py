"""Closed-candle-only live research coordinator for streamed Indian indices.

No live trading signals. Renders structural snapshots only after a causal
1-minute candle closes and contiguous session evidence is present.
"""
from __future__ import annotations

from .angel_stream_v312 import ValidatedTick, StreamDataError
from .live_candles_v312 import LiveCandleBuilder
from .phase2 import scan
from .continuation_v3 import detect_continuation_observations
from .market_context_v310 import analyze_mtf
from .ict_lifecycle_v316 import scan_ict_lifecycles


class LiveResearchEngine:
    def __init__(self, symbol: str):
        self.builder = LiveCandleBuilder(symbol)
        self.last_report: dict | None = None

    def on_tick(self, tick: ValidatedTick) -> dict | None:
        closed = self.builder.ingest(tick)
        if closed is None:
            return None
        candles = self.builder.completed
        if self.builder.quality_blocked:
            return self._report(closed, "WAIT", "UNVERIFIED_STREAM_CONTINUITY")
        # Intraday 1m bars must be contiguous from 09:16 close.
        if len(candles) < 12:
            return self._report(closed, "WAIT", "STRUCTURE_WARMUP")
        structure = scan(candles)
        continuation = detect_continuation_observations(candles)
        mtf = analyze_mtf(candles, as_of=closed.timestamp)
        latest = [event.as_dict(candles) for event in continuation
                  if event.confirm_index == len(candles)-1]
        report = self._report(closed, "RESEARCH_ONLY", "CLOSED_CANDLE_ANALYSIS")
        report["structures"] = [
            {"kind": x.kind, "direction": x.direction, "tier": x.tier,
             "at": candles[x.candle_index].timestamp.isoformat()}
            for x in structure.structure_events[-8:]
        ]
        report["latest_continuation_observations"] = latest
        report["intraday_mtf"] = mtf
        lifecycles = scan_ict_lifecycles(candles)
        report["ict_active_lifecycles"] = [
            x for x in lifecycles
            if x["state"] in ("WAITING_FOR_RETEST", "RETEST_CONFIRMED_RESEARCH")
        ][-10:]
        report["ict_last_lifecycle"] = lifecycles[-1] if lifecycles else None
        report["ict_order_eligible"] = False
        self.last_report = report
        return report

    def _report(self, closed, status, reason) -> dict:
        report = {
            "symbol": self.builder.symbol,
            "last_candle_close_at": closed.timestamp.isoformat(),
            "last_candle_close": closed.close,
            "status": status,
            "reason": reason,
            "stream_quality": self.builder.state(),
            "entry": None, "stop": None, "target": None,
            "orders_enabled": False, "research_only": True,
        }
        self.last_report = report
        return report

    def on_disconnect(self) -> None:
        # A reconnect cannot continue an in-flight minute as though no
        # packets were lost; new instance required for clean observation.
        self.builder.quality_blocked = True
        self.last_report = None
