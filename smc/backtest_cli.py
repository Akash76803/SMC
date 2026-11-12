"""Synthetic demonstration only; no broker or historical market data."""
from datetime import datetime, timedelta, timezone
import json

from .backtest import BacktestConfig, Signal, walk_forward_backtest
from .models import Candle, IndexSetup, Side


def main():
    t = datetime(2026, 1, 1, tzinfo=timezone.utc)
    prices = [
        (26000,26010,25990,26000),
        (26000,26015,25995,26010),
        (26012,26090,26002,26075),
        (26075,26095,26065,26082),
        (26080,26100,26070,26090)
    ]
    bars = [Candle(t+timedelta(minutes=i),*p) for i,p in enumerate(prices)]
    def research_signal(prefix):
        if len(prefix)==2:
            return Signal(IndexSetup("NIFTY",Side.CE,26010,25980,26080,
                                     True,"SYNTHETIC_RESEARCH"),1)
        return None
    report=walk_forward_backtest(bars,research_signal,
                                 BacktestConfig(round_trip_cost_points=1))
    print(json.dumps({
        "mode":report.mode,
        "trades":len(report.trades),
        "total_net_index_points":report.total_net_index_points,
        "win_rate":report.win_rate,
        "max_drawdown_points":report.max_drawdown_points,
        "note":"SYNTHETIC TEST DATA — NOT A LIVE TRADE OR OPTION PNL"
    },indent=2))


if __name__=="__main__":
    main()
