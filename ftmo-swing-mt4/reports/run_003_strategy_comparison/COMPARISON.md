# Strategy comparison -- EXPLORATORY, same data/costs/risk engine

Confirmed inputs used in this run: server clock GMT+2 winter / GMT+3 summer (EU DST dates), 5 USD/lot round-turn commission. Sample: ~2 months (2026-07-15/16 to 2026-09-17), one full calendar month (August 2026). **None of these results are evidence of a repeatable monthly result** -- see docs/UNKNOWNS.md and spec section 10.

| Strategy | Trades | Win rate | Net USD | Net % | Profit factor | Max DD USD | Lowest equity |
|---|---|---|---|---|---|---|---|
| London Range Breakout + Retest v1 (baseline) | 20 | 25.0% | -485.99 | -4.86% | 0.18 | 485.99 | 9514.01 |
| EMA(20/50) H1 crossover | 28 | 17.9% | -257.98 | -2.58% | 0.55 | 366.25 | 9742.02 |
| Bollinger(20,2) H1 mean-reversion | 118 | 23.7% | -780.79 | -7.81% | 0.66 | 871.97 | 9219.21 |

## Monthly net USD by strategy
| Year-Month | London Range Breakout + Retest v1 (baseline) | EMA(20/50) H1 crossover | Bollinger(20,2) H1 mean-reversion |
|---|---|---|---|
| 2026-07 | -86.94 | +26.65 | -336.37 |
| 2026-08 | -288.28 | -136.51 | -444.43 |
| 2026-09 | -110.78 | -148.11 | 0.00 |

**Conclusion: all three lose money on this exact sample after real costs.** This is a comparison across distinct known strategies at standard parameters, not a parameter search -- no attempt was made to tune any of them to turn this specific 2-month window profitable, since doing so on 40-ish trading days would be curve-fitting, not a finding. See README.md for the interpretation and next-step recommendation.

**Risk observation:** the Bollinger mean-reversion run's lowest equity (9219.21 USD) came within 19.21 USD of the static 9200 total working floor -- no breach occurred, but its combination of high trade frequency (118 trades) and negative expectancy is the riskiest of the three by a wide margin, independent of its net P/L number.