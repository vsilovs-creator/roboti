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


---

# EXPLORATORY baseline run -- EMA(20/50) H1 crossover

**Status: EXPLORATORY, not a validated FTMO result.** Sample is ~2 months with exactly one full calendar month; see docs/UNKNOWNS.md and spec section 10.

## Headline
- Net: -296.65 USD (-2.97%)
- Trades: 25
- Win rate: 16.0%
- Avg win R (net): 2.67
- Avg loss R (net): -1.04
- Expectancy: -11.87 USD/trade
- Profit factor: 0.48

## Drawdown / breach
- Max equity drawdown from peak: 365.16 USD
- Lowest equity observed: 9703.35 USD (vs. 9200.00 static total floor, margin +503.35)
- Daily/total working-floor breaches: 0
- Trades with SL/TP both reachable in one M1 candle (resolved SL-first, conservative): 0/25
- Trades filled via a gap past the stop level rather than at the exact level: 0/25

## Signals skipped by risk control
- CORRELATED_OR_PORTFOLIO_RISK_CAP: 3
- SYMBOL_ALREADY_HAS_OPEN_POSITION: 6

## Monthly table
| Year-Month | Full calendar month? | Net USD | Trades | >=2000 USD target met |
|---|---|---|---|---|
| 2026-07 | no (partial) | +26.65 | 6 | N/A (partial month) |
| 2026-08 | yes | -175.29 | 14 | no |
| 2026-09 | no (partial) | -124.74 | 5 | N/A (partial month) |

- Worst full calendar month: 2026-08 net -175.29 USD
- Full calendar months meeting the >=2000 USD / 20% target: 0/1


---

# EXPLORATORY baseline run -- Bollinger(20,2) H1 mean-reversion

**Status: EXPLORATORY, not a validated FTMO result.** Sample is ~2 months with exactly one full calendar month; see docs/UNKNOWNS.md and spec section 10.

## Headline
- Net: -784.45 USD (-7.84%)
- Trades: 84
- Win rate: 21.4%
- Avg win R (net): 2.21
- Avg loss R (net): -1.06
- Expectancy: -9.34 USD/trade
- Profit factor: 0.57

## Drawdown / breach
- Max equity drawdown from peak: 867.73 USD
- Lowest equity observed: 9215.55 USD (vs. 9200.00 static total floor, margin +15.55)
- Daily/total working-floor breaches: 0
- Trades with SL/TP both reachable in one M1 candle (resolved SL-first, conservative): 0/84
- Trades filled via a gap past the stop level rather than at the exact level: 1/84

## Signals skipped by risk control
- CORRELATED_OR_PORTFOLIO_RISK_CAP: 21
- PRE_TRADE_PROJECTED_EQUITY_BREACH: 130
- SYMBOL_ALREADY_HAS_OPEN_POSITION: 59

## Monthly table
| Year-Month | Full calendar month? | Net USD | Trades | >=2000 USD target met |
|---|---|---|---|---|
| 2026-07 | no (partial) | -267.52 | 36 | N/A (partial month) |
| 2026-08 | yes | -464.51 | 48 | no |

- Worst full calendar month: 2026-08 net -464.51 USD
- Full calendar months meeting the >=2000 USD / 20% target: 0/1


---

