# EXPLORATORY baseline run -- London Range Breakout + Retest v1

**Status: EXPLORATORY, not a validated FTMO result.** Sample is ~2 months with exactly one full calendar month; see docs/UNKNOWNS.md and spec section 10.

## Headline
- Net: -485.99 USD (-4.86%)
- Trades: 20
- Win rate: 25.0%
- Avg win R (net): 0.87
- Avg loss R (net): -1.59
- Expectancy: -24.30 USD/trade
- Profit factor: 0.18

## Drawdown / breach
- Max equity drawdown from peak: 485.99 USD
- Lowest equity observed: 9514.01 USD (vs. 9200.00 static total floor, margin +314.01)
- Daily/total working-floor breaches: 0
- Trades with SL/TP both reachable in one M1 candle (resolved SL-first, conservative): 0/20
- Trades filled via a gap past the stop level rather than at the exact level: 7/20

## Signals skipped by risk control
- none

## Monthly table
| Year-Month | Full calendar month? | Net USD | Trades | >=2000 USD target met |
|---|---|---|---|---|
| 2026-07 | no (partial) | -86.94 | 1 | N/A (partial month) |
| 2026-08 | yes | -288.28 | 13 | no |
| 2026-09 | no (partial) | -110.78 | 6 | N/A (partial month) |

- Worst full calendar month: 2026-08 net -288.28 USD
- Full calendar months meeting the >=2000 USD / 20% target: 0/1
