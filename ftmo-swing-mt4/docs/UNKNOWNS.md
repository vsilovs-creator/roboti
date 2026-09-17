# Unknowns and confirmed values

Every item below is either **CONFIRMED** (with source) or **UNKNOWN**
(never silently assumed to be zero/neutral anywhere in this codebase).

## Confirmed from the instrument-specification screenshots (this session)

| Field | EURUSD | GBPUSD |
|---|---|---|
| Spread | floating | floating |
| Digits | 5 | 5 |
| Stops level | 0 | 0 |
| Contract size | 100000 | 100000 |
| Margin currency | EUR | GBP |
| Profit / margin calc mode | Forex / Forex | Forex / Forex |
| Margin hedge | 100000.00 | 100000.00 |
| Margin percentage | 100% | 100% |
| Trade / execution | Full access / Market | Full access / Market |
| GTC mode | Pendings are good till cancel | same |
| Min / max volume | 0.01 / 50.00 | 0.01 / 50.00 |
| Volume step | 0.01 | 0.01 |
| Swap type | in points | in points |
| Swap long / short | -11.06 / +0.59 | -6.78 / -3.76 |
| 3-day swap | Wednesday | Wednesday |
| Sessions (quotes) Mon-Fri | 00:00-23:55 | 00:00-23:55 |
| Sessions (trade) Mon-Fri | 00:05-23:55 | 00:05-23:55 |
| Sessions Sat/Sun | none (blank) | none (blank) |

These are already encoded in `config/config.example.json`. They are still a
**snapshot**, not a guaranteed historical constant -- swap points, in
particular, are known to change over time at any broker.

## Confirmed from the raw M1 CSVs (independently re-audited, see `docs/DATA_AUDIT.md`)

- SHA-256 hashes, row counts, first/last timestamps, distinct calendar days,
  zero duplicate timestamps, zero invalid OHLC rows, zero non-monotonic
  timestamps, and the >1-minute gap count all match the task's own claimed
  audit table exactly (re-derived independently by
  `python/ftmo_sim/data_audit.py`, not copied).
- Sample window: 2026-07-15/16 through 2026-09-17, ~2 months, with **exactly
  one** full calendar month (August 2026).

## Still UNKNOWN -- must be confirmed before this leaves EXPLORATORY status

1. **Server clock UTC offset and its own DST calendar.** The CSV timestamps
   carry no timezone marker. `time_utils.ServerTimeModel` (Python) /
   `ServerUTCOffsetHours` + `ServerObservesEUDST` (MQL4 `Config.mqh`) default
   to `assume_utc` / `0.0, false` purely so the code runs deterministically;
   this is **not** claimed to be the real broker clock. Confirm via the
   terminal (`TimeCurrent()` vs `TimeGMT()`, and watch it across a DST
   transition) before trusting any wall-clock-sensitive result.
2. **Commission.** Never read from the terminal in this environment.
   `commission_round_turn_usd_per_lot` is `null` in the example config, and
   every report generated without it set is labeled EXPLORATORY. Must be
   filled from `AccountInfoDouble`/broker terms before a validated run.
3. **Leverage / actual margin requirement.** "Margin percentage 100%" is not
   the same as 1:100 leverage; the true leverage/margin call behavior was
   not in scope of the screenshots provided and is not modeled (this
   prototype never modes margin calls, only the FTMO/robot equity floors).
4. **Historical spread and slippage distribution.** The CSVs are Bid-only
   M1 OHLC with no tick-level Bid/Ask. `spread_points_hypothetical` in the
   config is a labeled placeholder for EXPLORATORY runs only.
5. **Freeze level.** Not in the provided screenshots; `MODE_STOPLEVEL` shows
   0, but freeze level is a distinct MT4 constant (`MODE_FREEZELEVEL`) that
   must be read live and was not captured.
6. **Historical swap-rate changes.** Only the current snapshot is known;
   swap points are not assumed constant over a multi-month/year backtest.
7. **The exact MT4 iATR/iMA(EMA) warmup numerics.** The Python engine
   hand-rolls a simple-average-seeded Wilder ATR / EMA (documented in
   `python/ftmo_sim/signals.py`) because it has no indicator history to draw
   on; MT4's built-ins read full history. A parity test between the two
   (spec section 8) is required before assuming they agree bar-for-bar,
   especially near the warmup boundary.
8. **FTMO's current published rules.** This design is pinned to the
   2026-09-17 conversation snapshot (spec section 12). Re-check the live
   FTMO agreement before any operational use; if it has changed, surface the
   conflict rather than silently keeping the 300/9200 USD robot limits.
