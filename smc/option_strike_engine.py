"""Advisory strike selection and fixed-delta estimates; never submits orders.

Premium distances are estimates in rupees, rounded to a Rs 0.05 tick.
Actual exit prices depend on volatility, time decay and market liquidity.
"""
from __future__ import annotations

import json
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
from zoneinfo import ZoneInfo


def _number(value, name, *, zero=False):
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise ValueError(f"Invalid {name}") from None
    if not result.is_finite() or result < 0 or (not zero and result == 0):
        raise ValueError(f"Invalid {name}")
    return result


def _tick(value):
    return float((value / Decimal('0.05')).quantize(Decimal('1'), rounding=ROUND_HALF_UP) * Decimal('0.05'))


def read_quote_tape(path):
    """Read JSONL rows, tolerating incomplete lines during concurrent recording."""
    rows = []
    try:
        with Path(path).open(encoding='utf-8') as stream:
            for line in stream:
                try:
                    row = json.loads(line)
                except (ValueError, TypeError):
                    continue
                if isinstance(row, dict):
                    rows.append(row)
    except OSError:
        pass
    return rows


def select_strikes(spot, direction, index_sl_pts, index_target_pts, *,
                   symbol='NIFTY', quotes=None, quote_path=None, expiry=None,
                   now=None, max_quote_age=20):
    """Return ATM/ITM/OTM long-option cards for BULLISH (CE) or BEARISH (PE).

    ``premium_sl_pts`` and ``premium_target_pts`` are delta-scaled distances;
    ``premium_sl`` and ``premium_target`` are absolute prices from the ask.
    Missing, stale, future or invalid quotes yield None prices. Quote expiry
    is selected once across all three cards to avoid mixing contracts.
    """
    spot = _number(spot, 'spot')
    risk = _number(index_sl_pts, 'index_sl_pts')
    reward = _number(index_target_pts, 'index_target_pts')
    age_limit = _number(max_quote_age, 'max_quote_age', zero=True)
    symbol = str(symbol).upper()
    direction = str(direction).upper()
    if symbol not in ('NIFTY', 'SENSEX') or direction not in ('BULLISH', 'BEARISH'):
        raise ValueError('Expected NIFTY/SENSEX and BULLISH/BEARISH')
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError('now must be timezone-aware')
    today = now.astimezone(ZoneInfo('Asia/Kolkata')).date()
    requested_expiry = date.fromisoformat(expiry) if expiry is not None else None
    step = Decimal(50 if symbol == 'NIFTY' else 100)
    atm = (spot / step).quantize(Decimal(1), rounding=ROUND_HALF_UP) * step
    side = 'CE' if direction == 'BULLISH' else 'PE'
    rows = list(quotes or [])
    if quote_path is not None:
        rows.extend(read_quote_tape(quote_path))
    eligible = []
    for row in rows:
        try:
            if not isinstance(row, dict):
                continue
            if row.get('market', row.get('index')) != symbol or row.get('side') != side:
                continue
            if row.get('research_only') is not True or row.get('orders_enabled') is not False:
                continue
            exp = date.fromisoformat(row['expiry'])
            at = datetime.fromisoformat(row['quote_at'])
            if at.tzinfo is None or not 0 <= (now - at).total_seconds() <= float(age_limit):
                continue
            bid = _number(row['bid'], 'bid')
            ask = _number(row['ask'], 'ask')
            strike = _number(row['strike'], 'strike')
            if bid > ask or exp < today or (requested_expiry and exp != requested_expiry):
                continue
            eligible.append((exp, at, strike, ask, row))
        except (ValueError, TypeError, KeyError, OverflowError):
            continue
    selected_expiry = requested_expiry or min((r[0] for r in eligible), default=None)
    result = {}
    sign = 1 if side == 'CE' else -1
    for kind, offset, delta in [('ATM', 0, '0.50'), ('ITM', -sign, '0.65'), ('OTM', sign, '0.35')]:
        strike = atm + offset * step
        matches = [r for r in eligible if r[0] == selected_expiry and r[2] == strike]
        quote = max(matches, key=lambda r: r[1]) if matches else None
        sl_distance, target_distance = risk * Decimal(delta), reward * Decimal(delta)
        entry = Decimal(str(_tick(quote[3]))) if quote else None
        result[kind] = {
            'strike': float(strike), 'side': side, 'symbol': symbol,
            'expiry': selected_expiry.isoformat() if selected_expiry else None,
            'delta': float(delta), 'premium_sl_pts': _tick(sl_distance),
            'premium_target_pts': _tick(target_distance),
            'premium_entry': float(entry) if entry is not None else None,
            'premium_sl': _tick(max(Decimal(0), entry - sl_distance)) if entry is not None else None,
            'premium_target': _tick(entry + target_distance) if entry is not None else None,
            'trading_symbol': quote[4].get('trading_symbol') if quote else None,
            'quote_at': quote[4]['quote_at'] if quote else None,
            'status': 'ESTIMATED' if quote else 'QUOTE_UNAVAILABLE',
            'research_only': True, 'orders_enabled': False,
            'premium_exit_prices_verified': False,
        }
    return result
