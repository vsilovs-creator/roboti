# EXPLORATORY baseline run -- London Range Breakout + Retest v1

**Status: EXPLORATORY, not a validated FTMO result.** Commission is UNCONFIRMED (treated as 0 in this run). Server clock / DST model is UNVERIFIED (naive CSV timestamps assumed already UTC). Sample is ~2 months with exactly one full calendar month; see docs/UNKNOWNS.md and spec section 10.

## Headline
- Net: -147.75 USD (-1.48%)
- Trades: 14
- Win rate: 35.7%
- Avg win R (net): 1.02
- Avg loss R (net): -1.23
- Expectancy: -10.55 USD/trade
- Profit factor: 0.46

## Drawdown / breach
- Max equity drawdown from peak: 147.75 USD
- Lowest equity observed: 9852.25 USD (vs. 9200.00 static total floor, margin +652.25)
- Daily/total working-floor breaches: 0
- Trades with SL/TP both reachable in one M1 candle (resolved SL-first, conservative): 0/14
- Trades filled via a gap past the stop level rather than at the exact level: 3/14

## Signals skipped by risk control
- none

## Monthly table
| Year-Month | Full calendar month? | Net USD | Trades | >=2000 USD target met |
|---|---|---|---|---|
| 2026-08 | yes | -61.17 | 6 | no |
| 2026-09 | no (partial) | -86.58 | 8 | N/A (partial month) |

- Worst full calendar month: 2026-08 net -61.17 USD
- Full calendar months meeting the >=2000 USD / 20% target: 0/1
