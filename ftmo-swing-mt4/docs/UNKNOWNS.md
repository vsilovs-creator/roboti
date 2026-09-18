# Unknowns and confirmed values

Every item below is either **CONFIRMED** (with source) or **UNKNOWN**
(never silently assumed to be zero/neutral anywhere in this codebase).

See also `docs/AUDIT_2026-09-18.md` for an independent code audit's
findings (two P0 simulator bugs, since fixed, plus several items now
reflected below) and `reports/README.md` for which report numbers are
superseded by that fix.

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

## Confirmed by the account owner (2026-09-18)

- **Server clock:** FTMO's MT4 server runs GMT+2 in winter/standard time and
  GMT+3 in summer/DST, transitioning on the same dates as the EU. Encoded as
  `ServerTimeModel(mode="zone_like", hypothesis_zone_name="Europe/Bucharest",
  verified=True)` (Python) / `ServerUTCOffsetHours=2.0,
  ServerObservesEUDST=true` (MQL4 `Config.mqh`) -- "Europe/Bucharest" is used
  purely as the zoneinfo database entry with exactly this GMT+2/+3-with-
  EU-DST pattern, not a claim about the broker's physical location. This
  changed the baseline result materially: re-running with the corrected
  clock shifted which candles fall inside the London range/entry windows,
  producing 20 trades instead of 14 (see `reports/run_002_confirmed_tz_commission/`
  vs. the now-superseded `reports/run_001/`).
- **Commission:** FTMO's forex/exotics commission is 2.50 USD per lot per
  side, i.e. 5.00 USD total per round-turn lot (confirmed 2026-09-18,
  matches FTMO's commission structure update). Encoded as
  `commission_round_turn_usd_per_lot: 5.0` (round-turn total) in
  `config/config.example.json`.

## Still UNKNOWN -- must be confirmed before this leaves EXPLORATORY status

1. **Leverage / actual margin requirement.** "Margin percentage 100%" is not
   the same as 1:100 leverage; the true leverage/margin call behavior was
   not in scope of the screenshots provided and is not modeled (this
   prototype never modes margin calls, only the FTMO/robot equity floors).
2. **Historical spread and slippage distribution.** The CSVs are Bid-only
   M1 OHLC with no tick-level Bid/Ask. `spread_points_hypothetical` in the
   config is a labeled placeholder for EXPLORATORY runs only.
3. **Freeze level.** Not in the provided screenshots; `MODE_STOPLEVEL` shows
   0, but freeze level is a distinct MT4 constant (`MODE_FREEZELEVEL`) that
   must be read live and was not captured.
4. **Historical swap-rate changes.** Only the current snapshot is known;
   swap points are not assumed constant over a multi-month/year backtest.
5. **The real swap-application hour/timing.** `simulator_ema_cross.py` now
   accrues swap once per FTMO-day (Prague) rollover, tripled on the night
   starting Wednesday (added 2026-09-18, see `docs/AUDIT_2026-09-18.md`
   P1-5) -- a materially better approximation than the previous silent
   zero, but not a confirmed model. Real MT4 posts swap at a specific
   server-local rollover hour that may not line up with the Prague-day
   boundary used here.
6. **The exact MT4 iATR/iMA(EMA) warmup numerics.** The Python engine
   hand-rolls a simple-average-seeded Wilder ATR / EMA (documented in
   `python/ftmo_sim/signals.py`) because it has no indicator history to draw
   on; MT4's built-ins read full history. A parity test between the two
   (spec section 8) is required before assuming they agree bar-for-bar,
   especially near the warmup boundary.
7. **FTMO's current published rules.** This design is pinned to the
   2026-09-17 conversation snapshot (spec section 12). Re-check the live
   FTMO agreement before any operational use; if it has changed, surface the
   conflict rather than silently keeping the 300/9200 USD robot limits.
8. **The single-controller instance guard is weaker than it may sound.**
   `RiskState`'s (Python) / `Persistence.mqh`'s (MQL4) account/server match
   check accepts a legitimate restart of the same controller and a second
   concurrent instance identically -- both present the same account/server.
   UPDATE 2026-09-18 (follow-up audit): `Persistence.mqh` now also has
   `AcquireInstanceLock()`/`ReleaseInstanceLock()`, an exclusive-open lock
   file (`FTMO_InstanceLock_<account>.lock`, opened without `FILE_SHARE_*`
   and held open for the EA's whole lifetime) called from both EAs'
   `OnInit`/`OnDeinit`, which DOES block a second EA instance attached in
   the SAME terminal/data-folder to the same account (the actual scenario
   this project's own two EA files could otherwise race on). This remains
   NOT_RUN/STATIC_REVIEW -- exclusivity here is a documented MQL4 file-open
   semantic, not something this environment could verify against a real
   terminal. It STILL does not, and cannot, stop a second MT4 TERMINAL
   INSTALLATION (a separate data folder, e.g. a copied/portable install on
   another machine) from independently acquiring its own lock in its own
   `MQL4/Files` directory and trading the same broker account unopposed --
   that would need a server-side/broker-side control outside this
   prototype's reach. Originally flagged by the 2026-09-18 audit
   (`docs/AUDIT_2026-09-18.md` P1-6); partially closed by the above, with
   the cross-terminal gap still open and tracked here.
