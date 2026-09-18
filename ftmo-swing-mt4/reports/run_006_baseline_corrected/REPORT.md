# EXPLORATORY baseline run -- London Range Breakout + Retest v1

**Status: EXPLORATORY, not a validated FTMO result.** Sample is ~2 months with exactly one full calendar month; see docs/UNKNOWNS.md and spec section 10.

## Headline
- Net: -446.71 USD (-4.47%)
- Trades: 20
- Win rate: 20.0%
- Avg win R (net): 1.06
- Avg loss R (net): -1.38
- Expectancy: -22.34 USD/trade
- Profit factor: 0.19

## Drawdown / breach
- Max equity drawdown from peak: 446.71 USD
- Lowest equity observed: 9553.29 USD (vs. 9200.00 static total floor, margin +353.29)
- Daily/total working-floor breaches: 0
- Trades with SL/TP both reachable in one M1 candle (resolved SL-first, conservative): 1/20
- Trades filled via a gap past the stop level rather than at the exact level: 3/20

## Signals skipped by risk control
- none

## Monthly table
| Year-Month | Full calendar month? | Net USD | Trades | >=2000 USD target met |
|---|---|---|---|---|
| 2026-07 | no (partial) | -75.60 | 1 | N/A (partial month) |
| 2026-08 | yes | -272.88 | 13 | no |
| 2026-09 | no (partial) | -98.23 | 6 | N/A (partial month) |

- Worst full calendar month: 2026-08 net -272.88 USD
- Full calendar months meeting the >=2000 USD / 20% target: 0/1
