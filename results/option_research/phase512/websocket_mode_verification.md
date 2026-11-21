# WebSocket Mode Verification — Phase 5.1.2

Generated: 2026-11-21T18:07:34.815529+05:30

## SDK Mode Constants (Verified from SmartApi/smartWebSocketV2.py)

| Constant Name | Value | Meaning |
|---------------|-------|---------|
| LTP_MODE      | 1 | Last Traded Price only |
| QUOTE         | 2 | Quote (OHLC + LTP) |
| SNAP_QUOTE    | 3 | ← **Used for option quotes** |
| DEPTH         | 4 | Full 20-level order book (NSE-CM only) |

Verified from actual SDK source: `True`  
Cross-check passed: `True`

## SNAP_QUOTE (Mode 3) — Fields Delivered

SNAP_QUOTE is the correct mode for option quote collection. It delivers:

```
subscription_mode        = 3
exchange_type            = 2 (NSE_FO) or 4 (BSE_FO)
token                    = instrument token string
sequence_number          = monotonic packet sequence
exchange_timestamp       = epoch milliseconds (IST source clock)
last_traded_price        = paise → ÷100 → ₹ price
last_traded_quantity
average_traded_price
volume_trade_for_the_day
total_buy_quantity
total_sell_quantity
open_price_of_the_day
high_price_of_the_day
low_price_of_the_day
closed_price
last_traded_timestamp
open_interest
open_interest_change_percentage
upper_circuit_limit
lower_circuit_limit
best_5_buy_data          → list of {flag, quantity, price, no_of_orders}
best_5_sell_data         → list of {flag, quantity, price, no_of_orders}
```

**Best bid = best_5_sell_data[0].price / 100**  
**Best ask = best_5_buy_data[0].price / 100**  
(SDK labels are swapped: buy_data contains sell orders, sell_data contains buy orders — verified in _parse_best_5_buy_and_sell_data)

## Exchange Type Mapping for Subscriptions

| Market  | Segment | exchangeType |
|---------|---------|--------------|
| NIFTY   | NSE_FO  | 2 |
| SENSEX  | BSE_FO  | 4 |

## DEPTH Mode (Mode 4) — Limitations

- Only supports NSE_CM (exchangeType=1) per SDK validation.
- Quota: maximum 50 tokens.
- **Not used for option collection** — SNAP_QUOTE (mode 3) is sufficient.

## Bug in angel_stream_v312.py

```
File:    smc/angel_stream_v312.py (line ~48)
Bug:     subscription_mode not in (1, 2, 3)  — excludes DEPTH=4
Impact:  NONE for current option collection (SNAP_QUOTE=3 is accepted)
Fix:     Change (1, 2, 3) to (1, 2, 3, 4) if DEPTH ever needed
```

## Subscription Configuration for Live Shadow

```python
# NIFTY options (NFO)
ws.subscribe(
    correlation_id="nifty_opts",
    mode=3,  # SNAP_QUOTE
    token_list=[{"exchangeType": 2, "tokens": [nifty_option_tokens...]}]
)

# SENSEX options (BFO)
ws.subscribe(
    correlation_id="sensex_opts",
    mode=3,  # SNAP_QUOTE
    token_list=[{"exchangeType": 4, "tokens": [sensex_option_tokens...]}]
)
```

> [!IMPORTANT]
> DEPTH=4 is NOT supported for BSE_FO. Never subscribe SENSEX options in DEPTH mode.
