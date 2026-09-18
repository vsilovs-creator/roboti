# Strategy comparison -- EXPLORATORY, same data/costs/risk engine

Confirmed inputs used in this run: server clock GMT+2 winter / GMT+3 summer (EU DST dates), 5 USD/lot round-turn commission. Sample: ~2 months (2026-07-15/16 to 2026-09-17), one full calendar month (August 2026). **None of these results are evidence of a repeatable monthly result** -- see docs/UNKNOWNS.md and spec section 10.

| Strategy | Trades | Win rate | Net USD | Net % | Profit factor | Max DD USD | Lowest equity | Swap USD | Open at end |
|---|---|---|---|---|---|---|---|---|---|
| London Range Breakout + Retest v1 (baseline) | 20 | 20.0% | -446.71 | -4.47% | 0.19 | 446.71 | 9553.29 | +0.00 | 0 |
| EMA(20/50) H1 crossover | 25 | 16.0% | -296.65 | -2.97% | 0.48 | 365.16 | 9703.35 | -23.27 | 0 |
| Bollinger(20,2) H1 mean-reversion | 84 | 21.4% | -784.45 | -7.84% | 0.57 | 867.73 | 9215.55 | -52.42 | 0 |

## Monthly net USD by strategy
| Year-Month | London Range Breakout + Retest v1 (baseline) | EMA(20/50) H1 crossover | Bollinger(20,2) H1 mean-reversion |
|---|---|---|---|
| 2026-07 | -75.60 | +26.65 | -267.52 |
| 2026-08 | -272.88 | -175.29 | -464.51 |
| 2026-09 | -98.23 | -124.74 | 0.00 |

**Conclusion: all three lose money on this exact sample after real costs.** This is a comparison across distinct known strategies at standard parameters, not a parameter search -- no attempt was made to tune any of them to turn this specific 2-month window profitable, since doing so on 40-ish trading days would be curve-fitting, not a finding. See README.md for the interpretation and next-step recommendation.

**Risk observation:** the Bollinger mean-reversion run's lowest equity (9215.55 USD) came within 15.55 USD of the static 9200 total working floor -- no breach occurred, but its combination of high trade frequency (84 trades) and negative expectancy is the riskiest of the three by a wide margin, independent of its net P/L number.