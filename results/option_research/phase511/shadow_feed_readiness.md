# Shadow Market Feed Architecture & Readiness

## 1. Angel One SmartWebSocketV2 vs REST Polling
- **Streaming WebSocket Mode 3 (SnapQuote / Depth):** Delivers event-timestamped best 5 bid/ask depth in milliseconds. This is the preferred primary feed for live shadow recording to avoid ~15s polling latency.
- **REST Snapshots (`getMarketData('FULL')`):** Maintained as an automatic fallback when WebSocket reconnects or during network blips.

## 2. Session Cutoff Alignment
- Under the `REGULAR_360_RANGE` contract, the active intraday research session ends at **15:15:00 IST**.
- All intraday MIS square-offs occur between 15:15 and 15:20 IST.
- Quote tapes must record continuously until **15:30:00 IST** to capture EOD squaring-off spreads and auction dynamics, while new trade entries remain strictly cut off at 15:15:00 IST.
