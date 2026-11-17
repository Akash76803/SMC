"""Closed-candle-only live research coordinator for streamed Indian indices.

No live trading signals. Renders structural snapshots only after a causal
1-minute candle closes and contiguous session evidence is present.
"""
from __future__ import annotations
from math import isfinite

from .angel_stream_v312 import ValidatedTick, StreamDataError
from .live_candles_v312 import LiveCandleBuilder
from .phase2 import scan
from .continuation_v3 import detect_continuation_observations
from .market_context_v310 import analyze_mtf, closed_timeframes
from .engine import confirmed_pivots
from .ict_lifecycle_v316 import scan_ict_lifecycles
from .live_bracket_v318 import research_bracket
from .models import IndexSetup, Side
from .risk import validate_index_setup


def _select_htf_context(mtf, spot):
    """Prefer confirmed hourly extremes; use confirmed 15m extremes otherwise."""
    for name in ("1h", "15m"):
        snapshot = (mtf or {}).get("timeframes", {}).get(name, {})
        high, low = snapshot.get("confirmed_high"), snapshot.get("confirmed_low")
        if not all(isinstance(v, (int, float)) and isfinite(v) and v > 0 for v in (high, low)) or high <= low:
            continue
        eq = (high+low)/2
        return dict(timeframe=name, high=high, low=low, equilibrium=eq,
                    position="PREMIUM" if spot > eq else "DISCOUNT" if spot < eq else "EQUILIBRIUM",
                    source=f"{name.upper()}_CONFIRMED_PIVOTS")
    return None


def _htf_context_history(candles):
    """Resolve HTF extremes at their actual confirmation time, never earlier."""
    frames = closed_timeframes(candles, as_of=candles[-1].timestamp)
    pivots = {name: confirmed_pivots(frames[name], k=2) for name in ("1h", "15m")}
    history = []
    for bar in frames['15m']:
        snapshots = {}
        for name in ("1h", "15m"):
            known = [p for p in pivots[name] if frames[name][p.confirmed_at].timestamp <= bar.timestamp]
            high = next((p.price for p in reversed(known) if p.kind == 'HIGH'), None)
            low = next((p.price for p in reversed(known) if p.kind == 'LOW'), None)
            snapshots[name] = dict(confirmed_high=high, confirmed_low=low)
        context = _select_htf_context({'timeframes': snapshots}, bar.close)
        if context:
            history.append({**context, 'available_at': bar.timestamp.isoformat()})
    return history


def _classified_bracket(symbol, candles, lifecycle):
    """Apply classified target caps through the unchanged index risk policy."""
    bracket = research_bracket(symbol=symbol, candles=candles, lifecycle=lifecycle)
    if lifecycle.get('confluence_model') != 'GWAIDIER_V1':
        return bracket
    target, entry, stop = (lifecycle.get('target_reference'), bracket.get('entry_close_reference'), bracket.get('stop_reference'))
    empty = {**bracket, 'status': 'NO_VERIFIED_INDEX_BRACKET', 'targets': [],
             'target_t1': None, 'index_rr_reference': None}
    if not lifecycle.get('poi_valid') or lifecycle.get('setup_type') not in ('PRO_TREND', 'COUNTER_PULLBACK'):
        return {**empty, 'reason': 'HTF_POI_UNVERIFIED'}
    if any(not isinstance(v, (int, float)) or not isfinite(v) for v in (target, entry, stop)):
        return {**empty, 'reason': 'CLASSIFIED_TARGET_UNAVAILABLE'}
    # A stopped/expired baseline bracket must never be revived by a target change.
    if bracket.get('reason') in ('STRUCTURAL_STOP_BREACHED', 'RETEST_NOT_RECENT', 'INVALID_STRUCTURAL_STOP_PROXY'):
        return empty
    bullish = lifecycle['direction'] == 'BULLISH'
    if not (stop < entry < target if bullish else target < entry < stop):
        return {**empty, 'reason': 'CLASSIFIED_TARGET_WRONG_DIRECTION'}
    result = validate_index_setup(IndexSetup(symbol, Side.CE if bullish else Side.PE,
        entry, stop, target, True, 'SMC_RETEST_REFERENCE'),
        min_target_points=bracket.get('min_target_required') or (50 if symbol == 'NIFTY' else 100))
    passed = result.accepted and result.index_rr >= lifecycle.get('target_rr_min', 2)
    return {**bracket, 'status': 'RESEARCH_INDEX_BRACKET_PASSES' if passed else 'NO_VERIFIED_INDEX_BRACKET',
            'target_t1': target, 'targets': [{'price': target, 'kind': lifecycle['target_kind'], 'strength': 1}],
            'index_rr_reference': result.index_rr, 'setup_id': lifecycle['setup_id'],
            'setup_type': lifecycle['setup_type'], 'target_kind': lifecycle['target_kind'],
            'reason': 'CLASSIFIED_INDEX_POLICY_PASSES' if passed else 'CLASSIFIED_TARGET_FAILS_EXISTING_RISK_POLICY'}


class LiveResearchEngine:
    def __init__(self, symbol: str):
        self.builder = LiveCandleBuilder(symbol)
        self.last_report: dict | None = None

    def on_tick(self, tick: ValidatedTick) -> dict | None:
        closed = self.builder.ingest(tick)
        if closed is None:
            return None
        candles = self.builder.completed
        # Mid-session joins are quality_blocked because we missed ticks since
        # 09:15.  After 12 consecutive gapless candles we have enough observed
        # context for structural analysis — auto-unblock so the dashboard shows
        # live data.  quality_blocked stays True only when gaps > 0 (packet
        # loss / reconnect mid-stream) which would corrupt OHLC continuity.
        if self.builder.quality_blocked and self.builder.gaps == 0 and len(candles) >= 12:
            self.builder.quality_blocked = False
        if self.builder.quality_blocked:
            return self._report(closed, "WAIT", "UNVERIFIED_STREAM_CONTINUITY")
        # Intraday 1m bars must be contiguous from 09:16 close.
        if len(candles) < 12:
            return self._report(closed, "WAIT", "STRUCTURE_WARMUP")
        structure = scan(candles)
        continuation = detect_continuation_observations(candles)
        # analyze_mtf requires candles starting from 09:16; mid-session joins
        # won't satisfy this — catch gracefully so the stream keeps running.
        try:
            mtf = analyze_mtf(candles, as_of=closed.timestamp)
        except (ValueError, TypeError):
            mtf = None
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
        dealing_range = _select_htf_context(mtf, candles[-1].close)
        if dealing_range:
            # A newly confirmed HTF pivot cannot reclassify earlier LTF shifts.
            dealing_range['history'] = _htf_context_history(candles)
        lifecycles = scan_ict_lifecycles(candles, dealing_range=dealing_range, allow_counter=True)
        report["ict_active_lifecycles"] = [
            x for x in lifecycles
            if x["state"] in ("WAITING_FOR_RETEST", "RETEST_CONFIRMED_RESEARCH")
        ][-10:]
        report["ict_last_lifecycle"] = lifecycles[-1] if lifecycles else None
        report["ict_dealing_range"] = dealing_range  # Premium/Discount context (Gwaidier L11)
        report["htf_context"] = {k: v for k, v in dealing_range.items() if k != 'history'} if dealing_range else None
        report["setup_type"] = lifecycles[-1].get('setup_type') if lifecycles else None
        retested=[x for x in lifecycles
                  if x["state"]=="RETEST_CONFIRMED_RESEARCH"]
        report["index_bracket_research"]=(
            _classified_bracket(self.builder.symbol, candles, retested[-1])
            if retested else None)
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
        # Exchange-time ticks sampled by SmartAPI; OHLC is *not*
        # authenticated full-exchange historical candle coverage.
        report["sampled_live_candles"] = [
            {"timestamp": c.timestamp.isoformat(), "open": c.open,
             "high": c.high, "low": c.low, "close": c.close}
            for c in self.builder.completed[-100:]
        ]
        report["live_candle_source"] = "TICK_SAMPLED_UNVERIFIED_FULL_COVERAGE"
        self.last_report = report
        return report

    def on_disconnect(self) -> None:
        # A reconnect cannot continue an in-flight minute as though no
        # packets were lost; sequence guards reset so the first tick of
        # the new sub-stream does not trip NONMONOTONIC checks, but
        # completed candles and quality_blocked are preserved.
        self.builder.quality_blocked = True
        self.builder.reset_sequence()
        self.last_report = None
