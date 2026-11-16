"""Conservative self-learning *research* on actual historical option bid/ask.

Chronological train/test split. Only training results choose parameters; an
untouched validation period can reject the candidate. No online self-editing,
no order routes, no guaranteed returns, no fake premium fills.
"""
from __future__ import annotations
from dataclasses import asdict
from datetime import datetime
from itertools import product

from .phase6_premium import Quote, Signal, Settings, replay

POLICIES = tuple((target,stop,hold) for target,stop,hold in
                 product((15.,25.,40.), (5.,8.,12.), (12,24))
                 if (target-1.)/(stop+1.) >= 2.0)


def metrics(trades) -> dict:
    numbers=[t.net_per_unit for t in trades]
    wins=sum(v>0 for v in numbers)
    gains=sum(v for v in numbers if v>0)
    losses=-sum(v for v in numbers if v<0)
    equity=peak=drawdown=0.0
    for value in numbers:
        equity+=value
        peak=max(peak,equity)
        drawdown=max(drawdown,peak-equity)
    return {
        "trades":len(numbers),
        "win_rate":round(wins/len(numbers),4) if numbers else None,
        "net_premium_points_per_unit":round(sum(numbers),4),
        "expectancy_per_unit":round(sum(numbers)/len(numbers),4) if numbers else None,
        "profit_factor":round(gains/losses,4) if losses else None,
        "max_drawdown_premium_points":round(drawdown,4),
    }


def evaluate_walk_forward(signals: list[Signal], quotes: list[Quote], *,
                          min_train_days: int = 20,
                          min_validation_days: int = 10,
                          min_train_trades: int = 15,
                          min_validation_trades: int = 8) -> dict:
    if min(min_train_days,min_validation_days,min_train_trades,min_validation_trades)<1:
        raise ValueError("INVALID_RESEARCH_SAMPLE_REQUIREMENTS")
    if any(s.timestamp.tzinfo is None for s in signals):
        raise ValueError("SIGNALS_NEED_TIMEZONE")
    days=sorted({s.timestamp.date() for s in signals})
    base={
        "research_only":True,"orders_enabled":False,
        "mode":"OBSERVED_QUOTE_WALK_FORWARD_NOT_REAL_FILLS",
        "status":"INSUFFICIENT_EVIDENCE","selected":None,
        "train":None,"validation":None,
        "train_days":0,"validation_days":0,
        "promotion_allowed":False,
        "reason":"NOT_ENOUGH_INDEPENDENT_SESSIONS",
    }
    if len(days)<min_train_days+min_validation_days:
        return base
    split=len(days)-min_validation_days
    train_set=set(days[:split])
    test_set=set(days[split:])
    training=[s for s in signals if s.timestamp.date() in train_set]
    validation=[s for s in signals if s.timestamp.date() in test_set]
    train_quotes=[q for q in quotes if q.timestamp.date() in train_set]
    test_quotes=[q for q in quotes if q.timestamp.date() in test_set]
    choices=[]
    for target,stop,hold in POLICIES:
        settings=Settings(target_points=target,stop_points=stop,
                          cost_per_unit=1.,max_holding_minutes=hold)
        trades,_=replay(training,train_quotes,settings)
        summary=metrics(trades)
        if summary["trades"]<min_train_trades:
            continue
        # Selection strictly on TRAIN set; net costs already deducted.
        choices.append((summary["expectancy_per_unit"],
                        -summary["max_drawdown_premium_points"],
                        target,stop,hold,settings,summary))
    if not choices:
        return {**base,"train_days":len(train_set),
                "validation_days":len(test_set),
                "reason":"INSUFFICIENT_TRAIN_QUOTE_FILLS"}
    best=max(choices,key=lambda c:c[:5])
    train_metrics=best[-1]
    chosen=best[-2]
    out_trades,skips=replay(validation,test_quotes,chosen)
    validation_metrics=metrics(out_trades)
    enough=validation_metrics["trades"]>=min_validation_trades
    # This cannot independently prove profitability; requires real forward
    # paper data, stable behavior and fee/slippage assumptions.
    promising=(enough and train_metrics["expectancy_per_unit"]>0
               and validation_metrics["expectancy_per_unit"]>0
               and validation_metrics["max_drawdown_premium_points"] <
                   max(10.,validation_metrics["net_premium_points_per_unit"]*3))
    return {**base,
        "status":"PAPER_RESEARCH_CANDIDATE" if promising else
                 "INSUFFICIENT_EVIDENCE" if not enough else "REJECTED_HOLDOUT",
        "reason":"OUT_OF_SAMPLE_POSITIVE_NOT_LIVE_VALIDATED" if promising else
                 "VALIDATION_SAMPLE_TOO_SMALL" if not enough else
                 "OUT_OF_SAMPLE_PERFORMANCE_DID_NOT_PASS",
        "selected":{
            "target_premium_points":chosen.target_points,
            "stop_premium_points":chosen.stop_points,
            "holding_minutes":chosen.max_holding_minutes,
            "cost_per_unit":chosen.cost_per_unit,
        },
        "train":train_metrics,
        "validation":validation_metrics,
        "train_days":len(train_set),
        "validation_days":len(test_set),
        "validation_skip_reasons":skips,
        "promotion_allowed":False,
        "production_settings_modified":False,
        "realized_broker_pnl":False,
        "remaining_gates":[
            "FORWARD_PAPER_TRADING","LIVE_EXCHANGE_QUOTES",
            "REAL_FEE_AND_SLIPPAGE_MODEL","NO_AUTO_ORDER_APPROVAL"
        ],
    }
