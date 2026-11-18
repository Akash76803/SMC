"""Read-only adapters from recorded research tapes to independent strategies."""
import json
from bisect import bisect_right
from datetime import datetime, timezone, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from .strategy_snr_vwap import scan_snr_signals
from .strategy_orb import evaluate_orb_15m
from .strategy_oi_trap import evaluate_oi_trap
from .option_strike_engine import select_strikes

IST = ZoneInfo('Asia/Kolkata')

# Configured research heuristics, not fitted target-time distributions or
# guarantees that an option position is safe to hold for this duration.
TIMING_DEFAULTS = {
    'snr_vwap': (10, 20, 25, 'If no momentum after 25m, exit near cost to avoid theta decay.'),
    'orb': (15, 30, 40, 'Trend continuation expected; exit if price re-enters range after 40m.'),
    'oi_trap': (10, 25, 30, 'Fast short-covering spike; exit if momentum halts after 30m.'),
}


def _timing_fields(strategy):
    minimum, maximum, hold, note = TIMING_DEFAULTS[strategy]
    fields = dict(expected_duration_min=minimum, expected_duration_max=maximum,
                  max_safe_holding_minutes=hold, time_stop_note=note)
    return {**fields, 'timing': {**fields, 'expected_duration': f'{minimum} - {maximum} mins',
                               'max_hold': f'{hold} mins', 'advice': note,
                               'basis': 'CONFIGURED_RESEARCH_HEURISTIC'}}


def _rows(path):
    """Bound polling IO to the last 8 MiB; discard a partial leading record."""
    try:
        with Path(path).open('rb') as stream:
            size = stream.seek(0, 2)
            stream.seek(max(0, size-8*1024*1024))
            if size > 8*1024*1024:
                stream.readline()
            lines = stream.read().decode('utf-8').splitlines()
        rows = []
        for line in lines:
            try:
                row = json.loads(line)
                if isinstance(row, dict):
                    rows.append(row)
            except ValueError:
                pass
        return rows
    except (OSError, UnicodeError):
        return []


def multi_strategy_payload(root, market, *, now=None):
    """Current signals during market hours; today's observations after close.

    Accept raw OHLCV JSONL or existing sampled_live_candles envelopes. Never
    manufacture volume or OI. Cash-index price-only signals are supported.
    Quotes are deduplicated by expiry/side/strike and must be <=20 seconds
    old at evaluation time. Evening review reconstructs setup-time quotes
    without using later prices or labelling historical observations as live.
    """
    if market not in ('NIFTY', 'SENSEX'):
        raise ValueError('INVALID_MARKET_SYMBOL')
    passed_now = now is not None
    now = now or datetime.now(timezone.utc)
    local = now.astimezone(IST)
    root = Path(root)
    rows = _rows(root/f'live_{market.lower()}.jsonl')
    if not passed_now and rows:
        last_item = rows[-1]
        last_str = last_item.get('timestamp') or last_item.get('last_candle_close_at')
        if last_str:
            try:
                last_dt = datetime.fromisoformat(last_str)
                if last_dt.tzinfo is not None and last_dt.astimezone(IST).date() != local.date():
                    now = last_dt
                    local = now.astimezone(IST)
            except (ValueError, TypeError):
                pass
    strategies = {key: dict(status='NEUTRAL' if key == 'oi_trap' else 'WAITING',
                            direction='NEUTRAL', signal=None, strikes={}, reason='NO_CANDLES',
                            **_timing_fields(key))
                  for key in ('snr_vwap', 'orb', 'oi_trap')}
    strategies['orb']['range'] = {}
    strategies['oi_trap'].update(pcr=None, walls={})
    result = dict(market=market, timestamp=now.isoformat(), strategies=strategies,
                  research_only=True, orders_enabled=False)
    candles, quality = {}, {}
    for row in rows:
        if row.get('symbol', row.get('market', market)) != market:
            continue
        if 'stream_quality' in row:
            quality = row['stream_quality'] if isinstance(row['stream_quality'], dict) else {'quality_blocked': True}
        source = row.get('sampled_live_candles', [row] if 'open' in row else [])
        for bar in source if isinstance(source, list) else []:
            try:
                if not isinstance(bar, dict) or bar.get('symbol', bar.get('market', market)) != market:
                    continue
                at = datetime.fromisoformat(bar['timestamp'])
                if at.tzinfo is None or at.astimezone(IST).date() != local.date():
                    continue
                if not time(9, 15) < at.astimezone(IST).time() <= time(15, 30):
                    continue
                candles[at] = {**bar, 'volume': bar.get('volume', 0)}
            except (KeyError, TypeError, ValueError):
                continue
    bars = [candles[t] for t in sorted(candles)]
    if not bars:
        return result
    interval = 1
    if len(bars) >= 2:
        interval = int((sorted(candles)[-1]-sorted(candles)[-2]).total_seconds()/60)
    if interval not in (1, 5):
        for state in strategies.values():
            state['reason'] = 'UNSUPPORTED_OR_GAPPED_INTERVAL'
        return result
    closed = local.time() > time(15, 30)
    evaluation_at = max(candles) if closed else now
    fresh = (0 <= (now-max(candles)).total_seconds() <= 20
             and time(9, 15) < local.time() <= time(15, 30)
             and not quality.get('quality_blocked', False))
    quote_history = []
    for row in _rows(root/f'live_{market.lower()}_option_quotes.jsonl'):
        try:
            at = datetime.fromisoformat(row['quote_at'])
            if (at.tzinfo is None or row.get('market') != market or at > now
                or at.astimezone(IST).date() != local.date()):
                continue
            quote_history.append((at, row))
        except (KeyError, TypeError, ValueError):
            continue
    quote_history.sort(key=lambda item: item[0])
    quote_times = [item[0] for item in quote_history]

    def quotes_at(at):
        latest = {}
        end = bisect_right(quote_times, at)
        begin = bisect_right(quote_times, at-timedelta(seconds=20), hi=end)
        # Include quotes exactly twenty seconds old.
        while begin > 0 and quote_times[begin-1] == at-timedelta(seconds=20):
            begin -= 1
        for _, row in reversed(quote_history[begin:end]):
            try:
                key = (row['expiry'], row['side'], row['strike'])
                if key not in latest:
                    latest[key] = row
            except (KeyError, TypeError):
                continue
        return list(latest.values())

    quotes = quotes_at(evaluation_at)
    for name, state in strategies.items():
        try:
            if name == 'snr_vwap':
                signals = scan_snr_signals(bars, symbol=market, quotes=[] if closed else quotes, now=evaluation_at)
                reason = 'NO_REJECTION'
            elif name == 'orb':
                orb = evaluate_orb_15m(bars, symbol=market, interval_minutes=interval, quotes=[] if closed else quotes, now=evaluation_at)
                state['range'] = {k: orb.get(k) for k in ('orb_high', 'orb_low', 'orb_midpoint', 'range_span')}
                signals, reason = orb['signals'], orb['status']
            else:
                oi = evaluate_oi_trap(bars[-1]['close'], bars, quotes, symbol=market,
                                      interval_minutes=interval, now=evaluation_at)
                if closed:
                    # Find the latest confirmed observation using only data then available.
                    for end in range(len(bars), 0, -1):
                        observed_at = datetime.fromisoformat(bars[end-1]['timestamp'])
                        snapshot = quotes_at(observed_at)
                        if not snapshot:
                            continue
                        candidate = evaluate_oi_trap(bars[end-1]['close'], bars[:end], snapshot,
                                                     symbol=market, interval_minutes=interval, now=observed_at)
                        if candidate['signals']:
                            oi = candidate
                            break
                state.update(pcr=oi['pcr_oi'], activity_basis=oi['activity_basis'],
                             walls={k: oi[k] for k in ('max_call_oi_strike', 'max_put_oi_strike')})
                signals, reason = oi['signals'], oi['status']
            signal = signals[-1] if signals else None
            # ORB/S&R scanners return history; never promote an old setup.
            active = fresh and signal is not None and (name == 'oi_trap' or
                     datetime.fromisoformat(signal['timestamp']) == max(candles))
            state['reason'] = reason if fresh or closed else 'STALE_OR_BLOCKED_DATA'
            if closed and signal is not None:
                observed_at = datetime.fromisoformat(signal['timestamp'])
                signal['strikes'] = select_strikes(signal['entry'], signal['direction'],
                    signal['index_sl_pts'], signal['index_target_pts'], symbol=market,
                    quotes=quotes_at(observed_at), now=observed_at,
                    expiry=oi['expiry'] if name == 'oi_trap' else None)
                state.update(status='SESSION_CLOSED_OBSERVATION', signal=signal,
                             strikes=signal['strikes'], direction=signal['direction'],
                             reason='HISTORICAL_RESEARCH_OBSERVATION', observed_at=signal['timestamp'])
            elif active:
                state.update(signal=signal, strikes=signal['strikes'], direction=signal['direction'])
                state['status'] = ('ACTIVE_SIGNAL' if name == 'snr_vwap' else 'BREAKOUT_OBSERVED'
                                   if name == 'orb' else 'SHORT_COVERING'
                                   if signal['direction'] == 'BULLISH' else 'LONG_UNWINDING')
                state['reason'] = 'RESEARCH_OBSERVATION'
            if name == 'oi_trap' and state.get('activity_basis') not in ('OI', 'UNAVAILABLE'):
                state['reason'] += ' · '+state['activity_basis']
            if state['signal'] is not None:
                state['signal'].update(_timing_fields(name))
                for strike in state['strikes'].values():
                    strike['timing'] = _timing_fields(name)['timing']
        except (ValueError, KeyError, TypeError, OverflowError):
            state['reason'] = 'INVALID_OR_INCOMPLETE_DATA'
    return result
