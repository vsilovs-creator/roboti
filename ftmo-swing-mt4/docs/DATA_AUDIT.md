# Data audit (independently re-derived)

Regenerate with:

```
cd python
python3 -m ftmo_sim.data_audit ../data/raw/EURUSD1.csv ../data/raw/GBPUSD1.csv
```

## Result (matches the task's own claimed audit table exactly)

| Check | EURUSD1.csv | GBPUSD1.csv |
|---|---|---|
| SHA-256 | `5f97acdd75114b27db880ecc74fdc1f73087dc8c56b91b168ded3ff310494ad2` | `367290d4be0bb6ee0c8f0333dd95fac349e27e41a65194b5dd97290e6453d393` |
| Row count | 65126 | 65352 |
| First timestamp (file-local, tz unconfirmed) | 2026-07-16 00:36 | 2026-07-15 21:57 |
| Last timestamp (file-local, tz unconfirmed) | 2026-09-17 23:05 | 2026-09-17 23:06 |
| Distinct calendar days in file | 46 | 47 |
| Duplicate timestamps | 0 | 0 |
| Invalid OHLC geometry rows | 0 | 0 |
| Non-monotonic timestamp rows | 0 | 0 |
| Rows preceded by a >1 minute gap | 364 (9 weekend, 355 suspected intraday) | 271 (9 weekend, 262 suspected intraday) |
| Largest gap | 2891 minutes (a weekend close) | 2891 minutes (a weekend close) |

This was re-derived from the actual files, not copied from the task text --
`python/tests/test_data_audit.py::test_real_eurusd_matches_task_spec_audit_table`
and its GBPUSD counterpart pin these exact numbers down as a regression test
against the SHA-256-verified raw files in `data/raw/`.

## What the gaps are

- **Weekend gaps (9 each):** the large ~2891-minute closes from Friday
  23:5x to Monday 00:0x (file-local time), consistent with a Friday
  23:55-close / weekend-closed pattern. Classified by a documented
  heuristic (Friday >=21:00 -> Monday <=03:00), not an FTMO/broker-confirmed
  session boundary.
- **Suspected intraday gaps (355 / 262):** everything else over 1 minute --
  most are short (a minute or few with no tick), some cluster right after
  the weekend re-open (see the Monday `INSUFFICIENT_RANGE_COVERAGE`
  day-skips in the baseline run's `day_outcomes.csv`, where the market
  appears to take roughly an hour to start producing bars each Monday in
  this sample, in server-local time). None are fabricated or filled in; the
  simulator and MQL4 signal engine both skip a day outright rather than
  guess a missing candle's price.

## Data sufficiency

~2 calendar months (2026-07-15/16 through 2026-09-17), with **exactly one**
full calendar month (August 2026). This is enough for a technical/parity
check and a first EXPLORATORY run, and not enough to say anything about a
repeatable monthly result -- see spec section 10 and `docs/UNKNOWNS.md`.
