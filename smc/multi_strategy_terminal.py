"""Read-only adapters from recorded research tapes to independent strategies."""
import json
import logging
from concurrent.futures import ThreadPoolExecutor
from collections import Counter
from bisect import bisect_right
from datetime import datetime, timezone, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from .strategy_snr_vwap import scan_snr_signals
from .strategy_orb import evaluate_orb_15m
from .strategy_oi_trap import evaluate_oi_trap
from .strategy_candlestick import scan_candlestick_signals
from .option_strike_engine import select_strikes

from .independent_signals import build_signal
from .smc_module_sweep import scan_smc_sweep
from .smc_module_mss import scan_smc_mss
from .smc_module_fvg import scan_smc_fvg
from .smc_module_ob import scan_smc_ob
from .smc_module_fibonacci import scan_smc_fibonacci
from .strategy_pdh_pdl import scan_pdh_pdl

log = logging.getLogger(__name__)

IST = ZoneInfo('Asia/Kolkata')

# Configured research heuristics, not fitted target-time distributions or
# guarantees that an option position is safe to hold for this duration.
TIMING_DEFAULTS = {
    'snr_vwap': (10, 20, 25, 'If no momentum after 25m, exit near cost to avoid theta decay.'),
    'orb': (15, 30, 40, 'Trend continuation expected; exit if price re-enters range after 40m.'),
    'oi_trap': (10, 25, 30, 'Fast short-covering spike; exit if momentum halts after 30m.'),
    'candlestick': (5, 15, 20, 'Price action momentum scalp; exit if no expansion within 20m.'),
    'smc_fib': (15, 30, 45, 'Fibonacci OTE pullback setup; exit if no expansion from golden zone.'),
}


def _parse_dt(val):
    if isinstance(val, datetime):
        return val.astimezone(IST) if val.tzinfo else val.replace(tzinfo=IST)
    if isinstance(val, str):
        try:
            dt = datetime.fromisoformat(val)
            return dt.astimezone(IST) if dt.tzinfo else dt.replace(tzinfo=IST)
        except Exception:
            return None
    return None


def evaluate_signal_outcome(signal, bars, closed=False):
    """Evaluate whether an index signal reached target or hit stop-loss in subsequent candles."""
    sig_time = _parse_dt(signal.get('timestamp'))
    if not sig_time:
        return {'status': 'UNKNOWN', 'label': 'PENDING', 'pnl_pts': 0.0, 'color': 'neutral'}

    sign = 1 if signal.get('direction') == 'BULLISH' else -1
    try:
        entry = float(signal.get('entry', 0))
        stop = float(signal.get('stop_loss', 0))
        target = float(signal.get('target', 0))
    except (ValueError, TypeError):
        return {'status': 'UNKNOWN', 'label': 'PENDING', 'pnl_pts': 0.0, 'color': 'neutral'}

    if not entry or not stop or not target:
        return {'status': 'UNKNOWN', 'label': 'PENDING', 'pnl_pts': 0.0, 'color': 'neutral'}

    subsequent_bars = []
    for b in bars:
        bt = _parse_dt(b.get('timestamp'))
        if bt and bt > sig_time:
            subsequent_bars.append(b)

    if not subsequent_bars:
        return {'status': 'ACTIVE', 'label': 'ACTIVE', 'exit_at': None, 'pnl_pts': 0.0, 'color': 'yellow'}

    for b in subsequent_bars:
        hit_stop = b['low'] <= stop if sign == 1 else b['high'] >= stop
        hit_target = b['high'] >= target if sign == 1 else b['low'] <= target
        bt = _parse_dt(b.get('timestamp'))
        dur_min = max(1, round((bt - sig_time).total_seconds() / 60)) if (bt and sig_time) else 1

        if hit_stop and hit_target:
            pnl = sign * (stop - entry)
            return {'status': 'SL_HIT', 'label': f'SL HIT ({pnl:+.1f} pts)', 'exit_price': stop,
                    'pnl_pts': round(pnl, 2), 'color': 'red', 'duration_min': dur_min,
                    'duration_label': f'{dur_min}m'}
        if hit_stop:
            pnl = sign * (stop - entry)
            return {'status': 'SL_HIT', 'label': f'SL HIT ({pnl:+.1f} pts)', 'exit_price': stop,
                    'pnl_pts': round(pnl, 2), 'color': 'red', 'duration_min': dur_min,
                    'duration_label': f'{dur_min}m'}
        if hit_target:
            pnl = sign * (target - entry)
            return {'status': 'TARGET_ACHIEVED', 'label': f'TARGET HIT (+{pnl:.1f} pts)', 'exit_price': target,
                    'pnl_pts': round(pnl, 2), 'color': 'green', 'duration_min': dur_min,
                    'duration_label': f'{dur_min}m'}

    last_b = subsequent_bars[-1]
    last_bt = _parse_dt(last_b.get('timestamp'))
    elapsed_min = max(1, round((last_bt - sig_time).total_seconds() / 60)) if (last_bt and sig_time) else 1
    curr_pts = sign * (last_b['close'] - entry)
    if closed:
        return {'status': 'EOD_EXIT', 'label': f'EOD ({curr_pts:+.1f} pts)', 'exit_price': last_b['close'],
                'pnl_pts': round(curr_pts, 2), 'color': 'green' if curr_pts > 0 else 'red',
                'duration_min': elapsed_min, 'duration_label': f'{elapsed_min}m'}

    est_target_min = max(2, 12 - elapsed_min)
    return {'status': 'ACTIVE', 'label': f'ACTIVE ({curr_pts:+.1f} pts)', 'exit_price': last_b['close'],
            'pnl_pts': round(curr_pts, 2), 'color': 'yellow', 'duration_min': elapsed_min,
            'elapsed_min': elapsed_min, 'est_target_min': est_target_min,
            'duration_label': f'Active {elapsed_min}m (Est. target ~{est_target_min}m)'}


def _timing_fields(strategy):
    if strategy not in TIMING_DEFAULTS:
        return {}
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


def calculate_multi_timeframe_trend(bars, session_history=None):
    """Determine top-down trend across Daily, 4h, 1h, 45m, 30m, 15m, 5m."""
    all_bars = session_history if session_history else bars
    if not all_bars:
        return {
            'daily': 'NEUTRAL', '4h': 'NEUTRAL', '1h': 'NEUTRAL',
            '45m': 'NEUTRAL', '30m': 'NEUTRAL', '15m': 'NEUTRAL', '5m': 'NEUTRAL',
            'master_bias': 'NEUTRAL', 'action_permitted': 'HIGH CONFLUENCE ONLY',
            'score': '0/7 ALIGNED', 'bull_count': 0, 'bear_count': 0
        }

    def _resample(b_list, mins):
        grouped = {}
        for b in b_list:
            dt = _parse_dt(b.get('timestamp'))
            if not dt:
                continue
            bucket = dt.replace(minute=(dt.minute // mins) * mins, second=0, microsecond=0)
            grouped.setdefault(bucket, []).append(b)
        out = []
        for bucket, grp in sorted(grouped.items()):
            out.append({
                'timestamp': bucket.isoformat(),
                'open': grp[0]['open'],
                'high': max(x['high'] for x in grp),
                'low': min(x['low'] for x in grp),
                'close': grp[-1]['close'],
            })
        return out

    def _determine_trend(tf_bars):
        if not tf_bars:
            return 'NEUTRAL'
        c = tf_bars[-1]['close']
        o = tf_bars[0]['open']
        h = max(x['high'] for x in tf_bars)
        l = min(x['low'] for x in tf_bars)
        mid = (h + l) / 2.0
        slope = tf_bars[-1]['close'] - tf_bars[-min(len(tf_bars), 3)]['close']
        if c > mid and slope >= 0:
            return 'BULLISH'
        elif c < mid and slope <= 0:
            return 'BEARISH'
        elif c > o:
            return 'BULLISH'
        elif c < o:
            return 'BEARISH'
        return 'NEUTRAL'

    bars_5m = _resample(all_bars, 5)
    bars_15m = _resample(all_bars, 15)
    bars_30m = _resample(all_bars, 30)
    bars_45m = _resample(all_bars, 45)
    bars_1h = _resample(all_bars, 60)
    bars_4h = _resample(all_bars, 240)

    trend_5m = _determine_trend(bars_5m)
    trend_15m = _determine_trend(bars_15m)
    trend_30m = _determine_trend(bars_30m)
    trend_45m = _determine_trend(bars_45m)
    trend_1h = _determine_trend(bars_1h)
    trend_4h = _determine_trend(bars_4h)

    if bars:
        today_open = bars[0]['open']
        curr_close = bars[-1]['close']
        trend_daily = 'BULLISH' if curr_close >= today_open else 'BEARISH'
    else:
        trend_daily = 'NEUTRAL'

    tfs = [trend_daily, trend_4h, trend_1h, trend_45m, trend_30m, trend_15m, trend_5m]
    bull_count = sum(1 for t in tfs if t == 'BULLISH')
    bear_count = sum(1 for t in tfs if t == 'BEARISH')

    if bull_count >= 4 or (trend_daily == 'BULLISH' and trend_1h == 'BULLISH'):
        master_bias = 'BULLISH'
        action_permitted = 'CALL (CE) ONLY'
    elif bear_count >= 4 or (trend_daily == 'BEARISH' and trend_1h == 'BEARISH'):
        master_bias = 'BEARISH'
        action_permitted = 'PUT (PE) ONLY'
    else:
        master_bias = 'NEUTRAL'
        action_permitted = 'HIGH CONFLUENCE ONLY'

    return {
        'daily': trend_daily, '4h': trend_4h, '1h': trend_1h,
        '45m': trend_45m, '30m': trend_30m, '15m': trend_15m, '5m': trend_5m,
        'master_bias': master_bias, 'action_permitted': action_permitted,
        'score': f"{max(bull_count, bear_count)}/7 ALIGNED",
        'bull_count': bull_count, 'bear_count': bear_count
    }


STRATEGY_DISPLAY_NAMES = {
    'smc_sweep': 'SMC Liquidity Sweep',
    'smc_mss': 'SMC Market Structure Shift',
    'smc_fvg': 'SMC Fair Value Gap',
    'smc_ob': 'SMC Order Block Retest',
    'smc_fib': 'Fibonacci OTE Golden Pocket',
    'candlestick': 'Candlestick Price Action',
    'pdh_pdl': 'PDH / PDL Masterclass',
    'snr_vwap': 'SNR VWAP Pullback',
    'orb': 'Opening Range Breakout',
    'oi_trap': 'Option Chain OI Trap',
}


def build_confirmed_hero_setup(market, bars, quotes, mtf_trend, strategies, *, now=None, quote_history=None):
    """Build a single, unambiguous confirmed hero setup driven directly by live strategy calculations."""
    if not bars:
        return None

    priority_order = [
        'smc_fvg', 'smc_ob', 'smc_sweep', 'smc_mss', 'smc_fib',
        'orb', 'snr_vwap', 'oi_trap',
        'pdh_pdl', 'candlestick'
    ]

    all_cards = []
    for s_name, strat in strategies.items():
        for c in strat.get('cards', []):
            sig = c.get('signal', {})
            out = c.get('outcome', {})
            all_cards.append((s_name, c, sig, out))

    active_cards = [item for item in all_cards if item[3].get('status') == 'ACTIVE']
    chosen = None
    if active_cards:
        def active_rank(item):
            s_name, c, sig, out = item
            p_idx = priority_order.index(s_name) if s_name in priority_order else 99
            ts = sig.get('timestamp') or ''
            return (p_idx, ts)
        
        active_sorted = sorted(active_cards, key=lambda x: x[2].get('timestamp', ''), reverse=True)
        bull_active = [x for x in active_sorted if x[2].get('direction') == 'BULLISH']
        bear_active = [x for x in active_sorted if x[2].get('direction') == 'BEARISH']
        
        if len(bull_active) >= 2 and len(bull_active) >= len(bear_active):
            chosen = bull_active[0]
        elif len(bear_active) >= 2 and len(bear_active) > len(bull_active):
            chosen = bear_active[0]
        else:
            chosen = sorted(active_cards, key=active_rank)[0]
    elif all_cards:
        resolved = [item for item in all_cards if item[3].get('status') in ('TARGET_ACHIEVED', 'SL_HIT')]
        if resolved:
            chosen = sorted(resolved, key=lambda x: x[2].get('timestamp', ''), reverse=True)[0]
        else:
            chosen = sorted(all_cards, key=lambda x: x[2].get('timestamp', ''), reverse=True)[0]

    if not chosen:
        # Fallback when no strategy cards are found
        direction = mtf_trend.get('master_bias') or 'BULLISH'
        if direction not in ('BULLISH', 'BEARISH'):
            direction = 'BULLISH' if bars[-1]['close'] >= bars[0]['open'] else 'BEARISH'
        side = 'CE' if direction == 'BULLISH' else 'PE'
        curr_index = bars[-1]['close']
        step = 50 if market == 'NIFTY' else 100
        atm_strike = int(round(curr_index / step) * step)
        base_prem = 120.0 if market == 'NIFTY' else 180.0
        return {
            'stage': 'STAGE 2 (Live Scanning)',
            'stage_note': f"Actively monitoring 10 strategies for high-confluence {direction} entry setup.",
            'direction': direction,
            'side': side,
            'side_label': f"{side} ({'CALL' if side == 'CE' else 'PUT'})",
            'strategy': 'Scanner',
            'pattern': 'Monitoring',
            'status': 'SCANNING',
            'contract': f"{market} {atm_strike} {side}",
            'expiry': 'CURRENT_EXPIRY',
            'rr_ratio': '1:2.0',
            'ltp': base_prem,
            'entry_bracket': f"₹{base_prem - 5.0} — ₹{base_prem + 5.0}",
            'stop_loss': base_prem - 15.0,
            'target_1': base_prem + 30.0,
            'target_2': base_prem + 50.0,
            'target_3': base_prem + 80.0,
            'do_not_chase': base_prem + 15.0,
            'entry_condition': f"Wait for next strategy trigger aligned with {direction}.",
            'invalidating_condition': f"Do not enter against master trend.",
            'underlying_trigger': f"Current spot at ₹{curr_index:.1f}.",
            'holding_horizon': 'Intraday Session',
            'index_entry': curr_index,
            'index_sl': curr_index - 20.0 if direction == 'BULLISH' else curr_index + 20.0,
            'index_target': curr_index + 40.0 if direction == 'BULLISH' else curr_index - 40.0,
        }

    strat_key, card, sig, out = chosen
    strat_title = STRATEGY_DISPLAY_NAMES.get(strat_key, strat_key.replace('_', ' ').title())
    pattern = sig.get('pattern') or sig.get('setup_type') or sig.get('signal_type') or strat_title
    pattern_title = pattern.replace('_', ' ').title()

    direction = sig.get('direction') or 'BULLISH'
    side = 'CE' if direction == 'BULLISH' else 'PE'
    status = out.get('status', 'ACTIVE')
    
    curr_index = bars[-1]['close']
    index_entry = round(float(sig.get('entry', curr_index)), 1)
    index_sl = round(float(sig.get('stop_loss', curr_index)), 1)
    index_tgt = round(float(sig.get('target', curr_index)), 1)
    index_risk = max(5.0 if market == 'NIFTY' else 15.0, abs(index_entry - index_sl))
    index_reward = abs(index_tgt - index_entry)
    rr_val = round(index_reward / max(1.0, index_risk), 2)

    strikes = card.get('strikes') or {}
    atm_row = strikes.get('ATM') if isinstance(strikes, dict) else None
    step = 50 if market == 'NIFTY' else 100
    atm_strike = int(round(index_entry / step) * step)
    strike_val = atm_row.get('strike') if atm_row else atm_strike

    matching_q = None
    all_quotes_to_search = list(quotes or [])
    if quote_history:
        all_quotes_to_search = list(quote_history) + all_quotes_to_search
    
    for q in reversed(all_quotes_to_search):
        if isinstance(q, dict) and q.get('strike') == strike_val and q.get('side') == side:
            matching_q = q
            break

    contract_symbol = (atm_row.get('trading_symbol') if atm_row else None) or (matching_q.get('trading_symbol') if matching_q else None)
    expiry_val = (atm_row.get('expiry') if atm_row else None) or (matching_q.get('expiry') if matching_q else None) or "CURRENT_EXPIRY"

    if atm_row and atm_row.get('premium_entry'):
        p_entry = float(atm_row['premium_entry'])
        p_sl = float(atm_row.get('premium_sl') or round(max(0.5, p_entry - 0.5 * index_risk), 1))
        p_tgt = float(atm_row.get('premium_target') or round(p_entry + 0.5 * index_reward, 1))
        ltp = p_entry
    elif matching_q:
        bid = matching_q.get('bid')
        ask = matching_q.get('ask')
        ltp_val = (bid + ask) / 2 if (bid and ask) else (ask or bid or matching_q.get('ltp'))
        p_entry = round(float(ltp_val), 1) if ltp_val else (140.0 if market == 'NIFTY' else 180.0)
        p_sl = round(max(0.5, p_entry - 0.5 * index_risk), 1)
        p_tgt = round(p_entry + 0.5 * index_reward, 1)
        ltp = p_entry
    else:
        base_prem = 120.0 if market == 'NIFTY' else 180.0
        p_entry = base_prem
        p_sl = round(max(0.5, p_entry - 0.5 * index_risk), 1)
        p_tgt = round(p_entry + 0.5 * index_reward, 1)
        ltp = base_prem

    if not contract_symbol:
        contract_symbol = f"{market} {int(strike_val)} {side}"

    p_risk = max(3.0 if market == 'NIFTY' else 8.0, round(p_entry - p_sl, 1))
    entry_low = round(max(0.5, p_entry - 0.15 * p_risk), 1)
    entry_high = round(p_entry + 0.15 * p_risk, 1)
    target_1 = round(p_tgt, 1)
    target_2 = round(p_entry + 1.5 * (p_tgt - p_entry), 1)
    target_3 = round(p_entry + 2.0 * (p_tgt - p_entry), 1)
    do_not_chase = round(p_entry + 0.75 * p_risk, 1)

    now_dt = (now or datetime.now(timezone.utc)).astimezone(IST)
    if now_dt.time() < time(11, 30):
        horizon = "Morning Momentum Window (09:20 — 11:30 AM IST)"
    elif now_dt.time() < time(13, 30):
        horizon = "Midday Reversal / Range Window (11:30 AM — 01:30 PM IST)"
    else:
        horizon = "Afternoon Power Hour Window (01:30 — 03:30 PM IST)"

    dur_label = out.get('duration_label') or ''
    if status == 'ACTIVE':
        stage_title = "STAGE 2 (Live Confirmation)"
        stage_desc = f"Active in {horizon}. Strategy [{strat_title}] confirmed {side} setup on live candle. Monitored with live VWAP, multi-timeframe bias, and real-time option spread."
    elif status == 'TARGET_ACHIEVED':
        stage_title = "STAGE 3 (Target Achieved ✓)"
        stage_desc = f"Strategy [{strat_title}] achieved Target ₹{index_tgt} ({dur_label or 'Resolved'}). In-the-money profit secured; awaiting next setup."
    elif status == 'SL_HIT':
        stage_title = "STAGE 3 (Stop-Loss Invalidation)"
        stage_desc = f"Strategy [{strat_title}] hit strict SL ₹{index_sl}. Invalidation rule executed; capital protected."
    else:
        stage_title = "STAGE 2 (Live Setup)"
        stage_desc = f"Strategy [{strat_title}] setup observation recorded."

    entry_cond = f"Strategy [{strat_title}] confirmed {pattern_title} at index ₹{index_entry}. Enter {side} contract {contract_symbol} within ₹{entry_low} — ₹{entry_high} bracket."
    invalid_cond = f"Index crosses invalidation level ₹{index_sl} or option premium falls below strict stop-loss of ₹{p_sl}."
    underlying_trig = f"Index spot ₹{curr_index:.1f}. Underlying trigger: {pattern_title} confirmed on candle at {sig.get('timestamp', 'LIVE')}."

    return {
        'stage': stage_title,
        'stage_note': stage_desc,
        'direction': direction,
        'side': side,
        'side_label': f"{side} ({'CALL' if side == 'CE' else 'PUT'})",
        'strategy': strat_title,
        'pattern': pattern_title,
        'status': status,
        'contract': contract_symbol,
        'expiry': expiry_val,
        'rr_ratio': f"1:{rr_val}",
        'ltp': round(float(ltp), 1) if ltp else p_entry,
        'entry_bracket': f"₹{entry_low} — ₹{entry_high}",
        'stop_loss': p_sl,
        'target_1': target_1,
        'target_2': target_2,
        'target_3': target_3,
        'do_not_chase': do_not_chase,
        'entry_condition': entry_cond,
        'invalidating_condition': invalid_cond,
        'underlying_trigger': underlying_trig,
        'holding_horizon': horizon,
        'index_entry': index_entry,
        'index_sl': index_sl,
        'index_target': index_tgt,
    }


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
    independent = {
        'smc_sweep': scan_smc_sweep, 'smc_mss': scan_smc_mss,
        'smc_fvg': scan_smc_fvg, 'smc_ob': scan_smc_ob,
        'smc_fib': scan_smc_fibonacci, 'pdh_pdl': scan_pdh_pdl,
    }
    strategies = {key: dict(status='NEUTRAL' if key == 'oi_trap' else 'WAITING',
                            direction='NEUTRAL', signal=None, strikes={}, reason='NO_CANDLES',
                            **_timing_fields(key))
                  for key in ('snr_vwap', 'orb', 'candlestick', 'oi_trap', *independent)}
    strategies['orb']['range'] = {}
    strategies['oi_trap'].update(pcr=None, walls={})
    result = dict(market=market, timestamp=now.isoformat(), strategies=strategies,
                  research_only=True, orders_enabled=False,
                  signals={name: [] for name in strategies}, confluences=[])
    candles, history, quality = {}, {}, {}
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
                if at.tzinfo is None or at > now:
                    continue
                if not time(9, 15) < at.astimezone(IST).time() <= time(15, 30):
                    continue
                history[at] = {**bar, 'volume': bar.get('volume', 0)}
                if at.astimezone(IST).date() == local.date():
                    candles[at] = history[at]
            except (KeyError, TypeError, ValueError):
                continue
    bars = [candles[t] for t in sorted(candles)]
    if not bars:
        return result
    times = sorted(candles)
    cadence = Counter(
        int((right - left).total_seconds() / 60)
        for left, right in zip(times, times[1:])
        if (right - left).total_seconds() in (60, 300, 900)
    )
    interval = cadence.most_common(1)[0][0] if cadence else 1
    prior_dates = {at.astimezone(IST).date() for at in history if at not in candles}
    prior = max(prior_dates, default=None)
    session_history = [history[at] for at in sorted(history)
                       if at.astimezone(IST).date() in (prior, local.date())]
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
    def scan(name):
        state = strategies[name]
        trade_plans = {}
        try:
            if name in independent:
                options = {'trade_plans': trade_plans} if name == 'pdh_pdl' else {}
                signals = independent[name](session_history, symbol=market, now=evaluation_at,
                                            interval_minutes=interval, **options)
                reason = 'NO_SETUP'
            elif name == 'snr_vwap':
                signals = scan_snr_signals(bars, symbol=market, quotes=[] if closed else quotes, now=evaluation_at)
                reason = 'NO_REJECTION'
            elif name == 'orb':
                orb = evaluate_orb_15m(bars, symbol=market, interval_minutes=interval, quotes=[] if closed else quotes, now=evaluation_at)
                state['range'] = {k: orb.get(k) for k in ('orb_high', 'orb_low', 'orb_midpoint', 'range_span')}
                signals, reason = orb['signals'], orb['status']
            elif name == 'candlestick':
                signals = scan_candlestick_signals(bars, symbol=market, quotes=[] if closed else quotes, now=evaluation_at)
                reason = 'WAITING_FOR_PATTERN'
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
            today_signals = [signal for signal in signals
                             if datetime.fromisoformat(signal['timestamp']).astimezone(IST).date() == local.date()]
            state['reason'] = reason if fresh or closed else 'STALE_OR_BLOCKED_DATA'
            published = []
            cards = []
            for raw in today_signals:
                observed_at = datetime.fromisoformat(raw['timestamp'])
                snapshot = quotes_at(observed_at) if closed else quotes
                sign = 1 if raw['direction'] == 'BULLISH' else -1
                if name in independent:
                    signal = dict(raw)
                    strikes = select_strikes(raw['entry'], raw['direction'], raw['index_sl_pts'],
                                             raw['index_target_pts'], symbol=market,
                                             quotes=snapshot, now=observed_at if closed else evaluation_at)
                    signal['strikes'] = [
                        dict(strike=row['strike'], option_type=row['side'], premium_entry=row['premium_entry'],
                             premium_sl=row['premium_sl'], premium_target=row['premium_target'])
                        for row in strikes.values()
                    ]
                else:
                    pattern = (raw.get('pattern') or raw.get('signal_type') or raw.get('setup')
                               or 'LEVEL_REJECTION')
                    signal = build_signal(name.upper(), pattern, observed_at, market, sign,
                                          raw['entry'], raw['stop_loss'], raw['target'],
                                          15 if name == 'orb' else interval)
                    if signal is None:
                        continue
                    strikes = raw['strikes']
                    if closed:
                        strikes = select_strikes(raw['entry'], raw['direction'], raw['index_sl_pts'],
                                                 raw['index_target_pts'], symbol=market, quotes=snapshot,
                                                 now=observed_at, expiry=oi['expiry'] if name == 'oi_trap' else None)
                    for contract, row in zip(signal['strikes'], strikes.values()):
                        contract.update({key: row[key] for key in ('premium_entry', 'premium_sl', 'premium_target')})
                outcome = evaluate_signal_outcome(raw, bars, closed=closed)
                signal['outcome'] = outcome
                raw['outcome'] = outcome
                timing = _timing_fields(name)
                if timing:
                    for row in strikes.values():
                        row['timing'] = _timing_fields(name)['timing']
                is_fresh = closed or (name == 'oi_trap') or (datetime.fromisoformat(raw['timestamp']) == times[-1])
                if is_fresh:
                    published.append(signal)
                cards.append(dict(signal={**raw, **timing, 'strikes': strikes, 'outcome': outcome},
                                  strikes=strikes, trade_plan=trade_plans.get(raw.get('setup_id')),
                                  setup_id=signal['setup_id'], outcome=outcome))

            if cards:
                newest = cards[-1]
                is_fresh_newest = fresh and (name == 'oi_trap' or datetime.fromisoformat(newest['signal']['timestamp']) == times[-1])
                if closed:
                    state.update(signal=newest['signal'], strikes=newest['strikes'],
                                 direction=newest['signal']['direction'],
                                 status='SESSION_CLOSED_OBSERVATION',
                                 reason='HISTORICAL_RESEARCH_OBSERVATION',
                                 observed_at=newest['signal']['timestamp'])
                elif is_fresh_newest:
                    state.update(signal=newest['signal'], strikes=newest['strikes'],
                                 direction=newest['signal']['direction'])
                    state['status'] = ('BREAKOUT_OBSERVED' if name == 'orb' else
                                       ('SHORT_COVERING' if state['direction'] == 'BULLISH' else 'LONG_UNWINDING')
                                       if name == 'oi_trap' else 'ACTIVE_SIGNAL')
                    state['reason'] = 'RESEARCH_OBSERVATION'
                state['cards'] = cards if not closed else [newest]
            if name == 'oi_trap' and state.get('activity_basis') not in ('OI', 'UNAVAILABLE'):
                state['reason'] += ' · ' + state['activity_basis']
            return published if not closed else published[-1:]
        except Exception:
            log.exception('Research scanner failed: %s', name)
            state['reason'] = 'INVALID_OR_INCOMPLETE_DATA'
            return []

    with ThreadPoolExecutor(max_workers=len(strategies)) as executor:
        result['signals'] = dict(zip(strategies, executor.map(scan, strategies)))

    aligned = {}
    for name, signals in result['signals'].items():
        for signal in signals:
            key = (datetime.fromisoformat(signal['timestamp']).astimezone(IST).isoformat(),
                   signal['direction'])
            aligned.setdefault(key, {}).setdefault(name, []).append(signal['setup_id'])
    for (at, direction), engines in aligned.items():
        if len(engines) >= 2:
            result['confluences'].append(dict(
                timestamp=at, direction=direction, confluence_score='HIGH',
                engines=list(engines), setup_ids=[setup for ids in engines.values() for setup in ids],
            ))
    result['mtf_trend'] = calculate_multi_timeframe_trend(bars, session_history)
    result['confirmed_hero'] = build_confirmed_hero_setup(market, bars, quotes, result['mtf_trend'], result['strategies'],
                                                          now=evaluation_at, quote_history=[row for _, row in quote_history])
    return result
