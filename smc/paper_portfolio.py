# -*- coding: utf-8 -*-
"""Autonomous Paper Trading Portfolio & Passbook Simulator for Intraday Research.

Purely virtual simulation: orders_enabled is ALWAYS False, research_only is ALWAYS True.
No real orders, no brokerage routes. Tracks virtual capital, real-time MTM, and persistent journal.
"""
from __future__ import annotations
import json
from datetime import datetime, time, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")

DEFAULT_LOT_SIZES = {
    'NIFTY': 25,
    'SENSEX': 10,
    'BANKNIFTY': 15,
}

INITIAL_CAPITAL = 100000.0  # ₹1,00,000 Starting Virtual Capital


def _load_ledger(ledger_path: Path, market: str) -> dict:
    if ledger_path.exists():
        try:
            with open(ledger_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                if isinstance(data, dict) and data.get('market') == market:
                    return data
        except Exception:
            pass
    return {
        'market': market,
        'initial_capital': INITIAL_CAPITAL,
        'current_balance': INITIAL_CAPITAL,
        'realized_pnl': 0.0,
        'unrealized_mtm': 0.0,
        'total_trades': 0,
        'wins': 0,
        'losses': 0,
        'win_rate': '0.0%',
        'open_position': None,
        'trade_history': [],
        'orders_enabled': False,
        'research_only': True,
        'last_updated': datetime.now(timezone.utc).isoformat(),
    }


def _save_ledger(ledger_path: Path, ledger: dict) -> None:
    try:
        ledger_path.parent.mkdir(parents=True, exist_ok=True)
        with open(ledger_path, 'w', encoding='utf-8') as f:
            json.dump(ledger, f, indent=2, ensure_ascii=False)
    except Exception:
        pass


def update_paper_portfolio(root: str | Path, market: str, hero_setup: dict | None,
                           quotes: dict | None, *, now: datetime | None = None) -> dict:
    """Evaluate and update the paper trading portfolio based on live hero setups and quotes."""
    r = Path(root)
    market = market.upper()
    ledger_path = r / f'paper_portfolio_{market.lower()}.json'
    ledger = _load_ledger(ledger_path, market)

    if now is None:
        now = datetime.now(timezone.utc)
    local_now = now.astimezone(IST)
    lot_size = DEFAULT_LOT_SIZES.get(market, 25)

    open_pos = ledger.get('open_position')

    # 1. Update Open Position MTM and Check Exit Conditions
    if open_pos:
        contract = open_pos.get('contract')
        side = open_pos.get('side', 'CE')
        entry_price = float(open_pos.get('entry_price', 0))
        target_1 = float(open_pos.get('target_1', 0))
        target_2 = float(open_pos.get('target_2', 0))
        stop_loss = float(open_pos.get('stop_loss', 0))
        lots = int(open_pos.get('lots', 1))
        pos_lot_size = int(open_pos.get('lot_size', lot_size))
        qty = lots * pos_lot_size

        # Fetch current live quote
        curr_ltp = None
        if quotes and contract in quotes:
            q = quotes[contract]
            curr_ltp = float(q.get('ltp', q.get('last_price', 0)) or 0)
        elif hero_setup and hero_setup.get('contract') == contract and hero_setup.get('ltp'):
            curr_ltp = float(hero_setup.get('ltp', 0))

        if curr_ltp and curr_ltp > 0:
            open_pos['current_ltp'] = curr_ltp
            pnl_pts = (curr_ltp - entry_price) if side == 'CE' else (entry_price - curr_ltp)
            unrealized_pnl = round(pnl_pts * qty, 2)
            open_pos['unrealized_pnl'] = unrealized_pnl
            open_pos['pnl_percent'] = round((pnl_pts / entry_price) * 100, 2) if entry_price > 0 else 0.0

            # Check Exit Conditions
            exit_triggered = False
            exit_reason = None
            exit_price = curr_ltp

            # Target 1 Hit
            if target_1 > 0 and ((side == 'CE' and curr_ltp >= target_1) or (side == 'PE' and curr_ltp <= target_1)):
                exit_triggered = True
                exit_reason = 'TARGET_1_HIT'
                exit_price = target_1
            # Stop Loss Hit
            elif stop_loss > 0 and ((side == 'CE' and curr_ltp <= stop_loss) or (side == 'PE' and curr_ltp >= stop_loss)):
                exit_triggered = True
                exit_reason = 'STOP_LOSS_HIT'
                exit_price = stop_loss
            # End of Day Cut-off (15:15 IST)
            elif local_now.time() >= time(15, 15):
                exit_triggered = True
                exit_reason = 'EOD_AUTO_SQUAREOFF'
                exit_price = curr_ltp

            if exit_triggered:
                realized_pts = (exit_price - entry_price) if side == 'CE' else (entry_price - exit_price)
                realized_cash = round(realized_pts * qty, 2)
                closed_trade = {
                    'trade_id': open_pos.get('trade_id'),
                    'contract': contract,
                    'strategy': open_pos.get('strategy'),
                    'pattern': open_pos.get('pattern'),
                    'side': side,
                    'lots': lots,
                    'qty': qty,
                    'entry_time': open_pos.get('entry_time'),
                    'exit_time': local_now.isoformat(),
                    'entry_price': entry_price,
                    'exit_price': round(exit_price, 2),
                    'pnl_pts': round(realized_pts, 2),
                    'realized_pnl': realized_cash,
                    'exit_reason': exit_reason,
                    'is_win': realized_cash > 0,
                }
                ledger['trade_history'].append(closed_trade)
                ledger['current_balance'] = round(ledger['current_balance'] + realized_cash, 2)
                ledger['realized_pnl'] = round(ledger['realized_pnl'] + realized_cash, 2)
                ledger['total_trades'] = len(ledger['trade_history'])
                ledger['wins'] = sum(1 for t in ledger['trade_history'] if t['is_win'])
                ledger['losses'] = sum(1 for t in ledger['trade_history'] if not t['is_win'])
                win_pct = (ledger['wins'] / ledger['total_trades'] * 100) if ledger['total_trades'] > 0 else 0
                ledger['win_rate'] = f"{win_pct:.1f}%"
                ledger['open_position'] = None
                open_pos = None

    # 2. Check for New Virtual Position Entry from Active Hero Setup
    if not open_pos and hero_setup and hero_setup.get('status') == 'ACTIVE':
        # Only take trade if before 15:00 IST
        if local_now.time() < time(15, 0):
            contract = hero_setup.get('contract')
            entry_price = float(hero_setup.get('ltp', 0) or 0)
            # If contract was already traded recently and exited with SL today, avoid immediate re-entry loop
            recent_exits = [t for t in ledger['trade_history'] if t.get('contract') == contract]
            re_entry_blocked = False
            if recent_exits:
                last_exit = recent_exits[-1]
                # Block re-entry on same contract if closed in last 10 minutes
                last_exit_time = datetime.fromisoformat(last_exit['exit_time'])
                if (local_now - last_exit_time).total_seconds() < 600:
                    re_entry_blocked = True

            if entry_price > 0 and contract and not re_entry_blocked:
                trade_id = f"PAPER_{market}_{local_now.strftime('%H%M%S')}"
                open_pos = {
                    'trade_id': trade_id,
                    'contract': contract,
                    'strategy': hero_setup.get('strategy', 'SMC Multi-Strategy'),
                    'pattern': hero_setup.get('pattern', 'A+ Setup'),
                    'side': hero_setup.get('side', 'CE'),
                    'lots': 1,
                    'lot_size': lot_size,
                    'qty': 1 * lot_size,
                    'entry_time': local_now.isoformat(),
                    'entry_price': entry_price,
                    'current_ltp': entry_price,
                    'stop_loss': float(hero_setup.get('stop_loss', 0)),
                    'target_1': float(hero_setup.get('target_1', 0)),
                    'target_2': float(hero_setup.get('target_2', 0)),
                    'unrealized_pnl': 0.0,
                    'pnl_percent': 0.0,
                }
                ledger['open_position'] = open_pos

    # 3. Compute Totals
    unrealized_sum = open_pos.get('unrealized_pnl', 0.0) if open_pos else 0.0
    ledger['unrealized_mtm'] = unrealized_sum
    ledger['net_equity'] = round(ledger['current_balance'] + unrealized_sum, 2)
    ledger['last_updated'] = local_now.isoformat()

    _save_ledger(ledger_path, ledger)
    return ledger
