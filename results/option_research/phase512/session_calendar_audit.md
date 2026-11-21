# Session Calendar Audit — Phase 5.1.2

Generated: 2026-11-21T17:50:48.194997+05:30

## Three Distinct Session Cutoffs

| Window | IST Start | IST End | Description |
|--------|-----------|---------|-------------|
| PRE_MARKET | 00:00 | 09:15 | Before market open |
| RESEARCH_ENTRY_WINDOW | 09:16 | 15:15 | ✅ Entries ALLOWED |
| POST_ENTRY_CUTOFF_MIS_SQUAREOFF_WINDOW | 15:15 | 15:20 | 🔶 MIS auto-squareoff; exits processed, NO new entries |
| POST_MIS_SQUAREOFF_CLOSING_AUCTION_WINDOW | 15:20 | 15:30 | 🔶 Closing auction; positions may be closing |
| POST_EXCHANGE_CLOSE | 15:30 | 24:00 | ❌ Exchange contract closed |

> [!IMPORTANT]
> Phase 5.1 and 5.1.1 classified ALL signals after 15:15 as `EXCLUDED_POST_1515_SESSION_CUTOFF`.
> This was overly conservative. Signals at 15:15–15:20 should be classified as
> `POST_ENTRY_CUTOFF_MIS_SQUAREOFF_WINDOW` (exits still valid).
> Signals at 15:20–15:30 are `POST_MIS_SQUAREOFF_CLOSING_AUCTION_WINDOW`.
> Only signals after 15:30 are truly POST_EXCHANGE_CLOSE.

## Signal Classification Examples

| Time (IST) | Zone | Entry Allowed? |
|------------|------|----------------|
| 09:15 | PRE_MARKET | NO |
| 09:16 | RESEARCH_ENTRY_WINDOW | YES |
| 12:30 | RESEARCH_ENTRY_WINDOW | YES |
| 15:15 | RESEARCH_ENTRY_WINDOW | YES |
| 15:16 | POST_ENTRY_CUTOFF_MIS_SQUAREOFF_WINDOW | NO |
| 15:20 | POST_ENTRY_CUTOFF_MIS_SQUAREOFF_WINDOW | NO |
| 15:21 | POST_MIS_SQUAREOFF_CLOSING_AUCTION_WINDOW | NO |
| 15:30 | POST_MIS_SQUAREOFF_CLOSING_AUCTION_WINDOW | NO |
| 15:31 | POST_EXCHANGE_CLOSE | NO |

## Specific Cases from Live Data

### SENSEX 2026-11-20 15:27–15:28 signal
- Previous classification: `EXCLUDED_POST_1515_SESSION_CUTOFF` ← correct (15:27 > 15:20)
- Revised classification: `POST_ENTRY_CUTOFF_MIS_SQUAREOFF_WINDOW` (15:15–15:20) or `POST_MIS_SQUAREOFF_CLOSING_AUCTION_WINDOW` (15:20+)
- 15:27 falls in `POST_MIS_SQUAREOFF_CLOSING_AUCTION_WINDOW` — **still not an entry signal**
- Classification is preserved as excluded; rationale is now more precise.

## Broker MIS Auto-Squareoff (Angel One)

Angel One MIS auto-squareoff typically begins at 15:15 IST for equity derivatives.
Exact time may vary by segment and market conditions. The 15:20 cutoff is conservative.

## Implications for Forward Shadow

- Record ALL signals with their zone classification.
- Only enter paper trades for signals in `RESEARCH_ENTRY_WINDOW`.
- Record but mark post-entry signals as `OBSERVED_ONLY_NO_ENTRY`.
