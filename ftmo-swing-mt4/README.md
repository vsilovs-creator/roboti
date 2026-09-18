# FTMO 2-Step Swing -- MT4 robot prototype (v1)

**Status: EXPLORATORY offline research.** Signal-only / dry-run by default.
Nothing here is authorized to trade a real FTMO account, and no MQL4 file
has been compiled or run in MT4/MetaEditor -- no MetaEditor/MT4 was
available in this environment. Every claim below says explicitly whether it
was actually executed (Python) or is an uncompiled translation offered for
review (MQL4, marked **NOT_RUN**).

Account: FTMO 2-Step Swing, USD, 10 000 USD starting balance. Instruments:
EURUSD + GBPUSD.

## Confirmed facts (account owner, 2026-09-18)

- **Server clock:** FTMO's MT4 server runs GMT+2 in winter/standard time,
  GMT+3 in summer/DST, on the same transition dates as the EU.
- **Commission:** 5 USD per lot (taken as round-turn; see `docs/UNKNOWNS.md`).

Applying these two facts to the baseline **changed the result materially**
-- the corrected clock shifts which candles fall inside the London
range/entry windows, and the previously-unmodeled commission adds a real
cost on every trade. See `reports/run_001/` (superseded, pre-correction) vs.
`reports/run_002_confirmed_tz_commission/` (current).

## What was actually run here

- **Data audit** (`python/ftmo_sim/data_audit.py`) against the real,
  SHA-256-verified `data/raw/EURUSD1.csv` / `GBPUSD1.csv` -- independently
  reproduces the task's own audit table exactly. See `docs/DATA_AUDIT.md`.
- **54 pytest tests**, all passing, covering the account-risk floors, the
  pre-trade projected-equity check, the daily/total stop state machine
  (restart, second-instance guard, history reconciliation), confirmed
  timezone/DST handling, symbol/lot-sizing math, all three strategies'
  signal state machines, and order execution (same-bar SL/TP collision, gap
  fills, spread/commission accounting, session-close on/off). See
  `docs/RISK_SPEC.md` for the mapping to the spec's 11 mandated test
  scenarios (10 of 11 -- everything except the MT4-only OrderSend-timeout
  scenario, which needs a real terminal).
- **A search for a profitable strategy on this sample**, per the account
  owner's explicit request ("meklē peļņu ar jebkuru tev zināmo stratēģiju").
  Three independent, well-known strategies at standard textbook parameters
  were run on the exact same data, account-wide risk engine, and confirmed
  costs -- see `reports/run_003_strategy_comparison/COMPARISON.md`:

  | Strategy | Trades | Win rate | Net USD | Profit factor |
  |---|---|---|---|---|
  | London Range Breakout + Retest v1 | 20 | 25.0% | -485.99 | 0.18 |
  | EMA(20/50) H1 crossover (trend) | 28 | 17.9% | -257.98 | 0.55 |
  | Bollinger(20,2) H1 mean-reversion | 118 | 23.7% | -780.79 | 0.66 |

  **All three lose money on this exact ~2-month sample after real costs.**
  This was a comparison across distinct known strategies at standard
  parameters, not a parameter search/optimization over any one of them --
  spec section 8 explicitly warns against wide optimization on this short a
  dataset, and hunting for a locally profitable parameter combination on
  ~40 trading days would produce a curve-fit number, not a finding. See
  "Interpretation" below.
  - **Risk observation:** the Bollinger mean-reversion run's lowest equity
    (9219.21 USD) came within 19.21 USD of the static 9200 total working
    floor -- no breach occurred, but its high trade frequency (118 trades)
    combined with negative expectancy makes it the riskiest of the three by
    a wide margin, independent of its net P/L.

## Interpretation -- why "no profitable strategy found" is itself the honest result here

- The sample is genuinely short: ~2 months, one full calendar month. Both a
  breakout-retest and a trend-following approach can easily lose on any
  single 2-month window even if they have long-run positive expectancy --
  this is not strong evidence against either approach, just evidence that
  40 trading days is not enough to tell.
- 5 USD/lot commission is a real, meaningful drag relative to the 25 USD
  risk-per-idea budget (roughly 20% of a typical loss, and a comparable
  bite out of small wins) -- it disproportionately hurts higher-frequency
  strategies (compare the Bollinger strategy's 118 trades vs. the
  breakout's 20).
- No attempt was made to re-tune any of the three strategies' parameters to
  make this specific window profitable. Doing so would be reporting an
  overfit result as a "finding," which spec section 8/10 explicitly warns
  against and which this deliverable will not do.

## What was NOT run

- The MQL4 EA and Include files (`mql4/`) were never opened in MetaEditor
  and never compiled. They mirror the (confirmed) London breakout baseline
  only, not the two additional strategies tried in the search above --
  porting a strategy to MQL4 was out of scope until one is chosen to pursue
  further. Offered for someone with MT4 access to compile, review, and test
  against the MT4 Strategy Tester (see `docs/RISK_SPEC.md` test 10 and test
  6/7/9's MQL4-specific halves).
- No parity test between the Python offline engine and the MQL4/MT4
  Strategy Tester has been run (needs MT4). Both engines implement the same
  rules but the ATR/EMA warmup numerics are expected to differ slightly
  near the edges (documented in `python/ftmo_sim/signals.py` and
  `mql4/Include/FTMO/Signals_LondonBreakoutRetest.mqh`).

## Layout

```
config/config.example.json   Every parameter; confirmed values (timezone, commission) labeled as such
data/raw/EURUSD1.csv         Raw M1 data, unchanged, SHA-256 verified
data/raw/GBPUSD1.csv
docs/UNKNOWNS.md             Confirmed vs. still-unknown parameters
docs/DATA_AUDIT.md           Independently reproduced data audit
docs/RISK_SPEC.md            Risk formulas + mapping to the 11 mandated tests
python/ftmo_sim/             Tested: time/symbol/risk/signal/execution/simulator/report modules,
                              plus strategy_ema_cross.py and strategy_bb_reversion.py (search candidates)
python/tests/                54 passing pytest tests
python/scripts/run_baseline.py             Runs the fixed London breakout baseline end to end
python/scripts/run_strategy_comparison.py  Runs all three strategies side by side
reports/                      See reports/README.md for what each run_NNN/ is and which is current
mql4/Include/FTMO/            NOT_RUN: Config/TimeUtils/SymbolSpec/AccountRisk/
                               Signals/OrderExec/Persistence/Logging
mql4/Experts/FTMO_Swing_EA.mq4  NOT_RUN: single-account EA wiring the above (London breakout only)
```

## Exact commands

```bash
cd python

# Re-run the data audit (reproduces docs/DATA_AUDIT.md)
python3 -m ftmo_sim.data_audit ../data/raw/EURUSD1.csv ../data/raw/GBPUSD1.csv

# Run the test suite (54 tests, no dependencies beyond pytest)
pip install -r requirements-dev.txt
python3 -m pytest -q

# Run the fixed London breakout baseline over the supplied data
python3 scripts/run_baseline.py \
    --config ../config/config.example.json \
    --eurusd ../data/raw/EURUSD1.csv \
    --gbpusd ../data/raw/GBPUSD1.csv \
    --out-dir ../reports/run_002_confirmed_tz_commission

# Run all three strategies side by side
python3 scripts/run_strategy_comparison.py \
    --config ../config/config.example.json \
    --eurusd ../data/raw/EURUSD1.csv \
    --gbpusd ../data/raw/GBPUSD1.csv \
    --out-dir ../reports/run_003_strategy_comparison
```

## Risk policy summary (see `docs/RISK_SPEC.md` for the full detail + tests)

- Robot daily working floor `B0 - 300`; robot static total working floor
  `9200` (both FTMO's own looser 500/9000 limits are tracked separately as
  reference). Both checked directly and independently against equity; the
  total floor is sticky (manual-review-only clear), the daily floor clears
  automatically the next correctly-reconstructed FTMO day.
- Account-wide: every open position on the account is scanned, not just
  this EA's MagicNumber; an unknown-risk foreign position blocks new
  entries.
- 25 USD risk per idea (50 USD alt scenario, both config-only, not FTMO
  rules), 100 USD max concurrent, 50 USD correlated-group cap for
  same-direction EURUSD+GBPUSD ideas. All three strategies searched above
  run under this exact same risk engine.
- No martingale, no grid, no adding to losers, no increasing risk to chase
  the monthly target or recover a loss.

## Strategies tried (spec section 7 baseline + 2 additional per the profit search)

1. **London Range Breakout + Retest v1** (fixed baseline, spec section 7):
   range = [00:00,07:00) London; entries only in [08:00,11:00); breakout on
   a closed M5 candle; retest confirmation within the next 6 M5 candles; H1
   EMA200 direction filter; SL = retest extreme +/- 0.10*ATR14(M5); TP = 2R;
   one trade per instrument per London day; force-close at 16:00 London.
2. **EMA(20/50) H1 crossover** (`strategy_ema_cross.py`): standard trend
   crossover, SL = 1.5x ATR14(H1), TP = 3R, holds across the session-close
   boundary (a swing-style design, arguably a better fit for a Swing
   account than an intraday one).
3. **Bollinger(20,2) H1 mean-reversion** (`strategy_bb_reversion.py`): fade
   a close outside the 20-period/2-stddev band back toward the middle band,
   SL = 0.5x ATR14(H1) beyond the breached band.

No indicators or filters beyond what each strategy's own definition
specifies were added to any of the three.

## Open questions for the account owner

1. Given all three tried strategies lost money on this exact sample -- is
   the priority (a) more historical data (ideally spanning a mix of
   trending and ranging regimes, since this window skewed choppy), (b) a
   fourth candidate strategy, or (c) accepting one of these three as a
   starting point and iterating on it with proper walk-forward validation
   once more data exists?
2. Is "5 USD per lot" a round-turn total or per side? The config currently
   assumes round-turn; if it is actually per side, real costs are roughly
   double what these reports show.
3. Should the next MQL4 porting effort target the London breakout baseline
   (already ported, NOT_RUN) or one of the two newly-compared strategies
   instead, given none of the three has yet shown a profitable result on
   available data?
