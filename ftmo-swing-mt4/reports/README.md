# Reports index

All EXPLORATORY -- see `../docs/UNKNOWNS.md` and `../docs/RISK_SPEC.md`.

- **run_001/** -- SUPERSEDED. First baseline run, made before the server
  clock and commission were confirmed (assumed UTC, commission=0). Kept for
  transparency only; do not use its numbers.
- **run_002_confirmed_tz_commission/** -- London Range Breakout + Retest v1
  baseline, re-run with the account owner's confirmed values (server clock
  GMT+2 winter/GMT+3 summer on EU DST dates, 5 USD/lot commission). This is
  the current baseline result: 20 trades, net -485.99 USD (-4.86%).
- **run_003_strategy_comparison/** -- Same confirmed inputs, three
  independent well-known strategies side by side (the baseline plus an
  EMA(20/50) H1 crossover trend-follower and a Bollinger(20,2) H1
  mean-reversion fade), run once each at standard textbook parameters, not
  optimized. All three are net-negative on this ~2-month sample; see
  `COMPARISON.md` in that folder and `../README.md` for the interpretation.
- **run_004_ema_cross_chosen/** -- CURRENT / chosen strategy. EMA(20/50) H1
  crossover, picked (2026-09-18) as the smallest-loss of the three compared
  in run_003 after the account owner confirmed no further historical data
  will be supplied. -257.98 USD (-2.58%), 28 trades. Still a loss, not a
  validated result -- see `../README.md`.
