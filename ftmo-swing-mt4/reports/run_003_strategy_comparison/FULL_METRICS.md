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


---

# EXPLORATORY baseline run -- EMA(20/50) H1 crossover

**Status: EXPLORATORY, not a validated FTMO result.** Sample is ~2 months with exactly one full calendar month; see docs/UNKNOWNS.md and spec section 10.

## Headline
- Net: -257.98 USD (-2.58%)
- Trades: 28
- Win rate: 17.9%
- Avg win R (net): 2.65
- Avg loss R (net): -1.04
- Expectancy: -9.21 USD/trade
- Profit factor: 0.55

## Drawdown / breach
- Max equity drawdown from peak: 366.25 USD
- Lowest equity observed: 9742.02 USD (vs. 9200.00 static total floor, margin +542.02)
- Daily/total working-floor breaches: 0
- Trades with SL/TP both reachable in one M1 candle (resolved SL-first, conservative): 0/28
- Trades filled via a gap past the stop level rather than at the exact level: 0/28

## Signals skipped by risk control
- SYMBOL_ALREADY_HAS_OPEN_POSITION: 6

## Monthly table
| Year-Month | Full calendar month? | Net USD | Trades | >=2000 USD target met |
|---|---|---|---|---|
| 2026-07 | no (partial) | +26.65 | 6 | N/A (partial month) |
| 2026-08 | yes | -136.51 | 16 | no |
| 2026-09 | no (partial) | -148.11 | 6 | N/A (partial month) |

- Worst full calendar month: 2026-08 net -136.51 USD
- Full calendar months meeting the >=2000 USD / 20% target: 0/1


---

# EXPLORATORY baseline run -- Bollinger(20,2) H1 mean-reversion

**Status: EXPLORATORY, not a validated FTMO result.** Sample is ~2 months with exactly one full calendar month; see docs/UNKNOWNS.md and spec section 10.

## Headline
- Net: -780.79 USD (-7.81%)
- Trades: 118
- Win rate: 23.7%
- Avg win R (net): 2.26
- Avg loss R (net): -1.06
- Expectancy: -6.62 USD/trade
- Profit factor: 0.66

## Drawdown / breach
- Max equity drawdown from peak: 871.97 USD
- Lowest equity observed: 9219.21 USD (vs. 9200.00 static total floor, margin +19.21)
- Daily/total working-floor breaches: 0
- Trades with SL/TP both reachable in one M1 candle (resolved SL-first, conservative): 1/118
- Trades filled via a gap past the stop level rather than at the exact level: 4/118

## Signals skipped by risk control
- PRE_TRADE_PROJECTED_EQUITY_BREACH: 105
- SYMBOL_ALREADY_HAS_OPEN_POSITION: 71

## Monthly table
| Year-Month | Full calendar month? | Net USD | Trades | >=2000 USD target met |
|---|---|---|---|---|
| 2026-07 | no (partial) | -336.37 | 43 | N/A (partial month) |
| 2026-08 | yes | -444.43 | 75 | no |

- Worst full calendar month: 2026-08 net -444.43 USD
- Full calendar months meeting the >=2000 USD / 20% target: 0/1


---

