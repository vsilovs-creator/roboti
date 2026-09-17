# FTMO 2-Step Swing -- MT4 robot prototype (v1)

**Status: EXPLORATORY offline research.** Signal-only / dry-run by default.
Nothing here is authorized to trade a real FTMO account, and no MQL4 file
has been compiled or run in MT4/MetaEditor -- no MetaEditor/MT4 was
available in this environment. Every claim below says explicitly whether it
was actually executed (Python) or is an uncompiled translation offered for
review (MQL4, marked **NOT_RUN**).

Account: FTMO 2-Step Swing, USD, 10 000 USD starting balance. Instruments:
EURUSD + GBPUSD. Strategy: London Range Breakout + Retest v1 (spec section
7), one fixed baseline, not yet optimized.

## What was actually run here

- **Data audit** (`python/ftmo_sim/data_audit.py`) against the real,
  SHA-256-verified `data/raw/EURUSD1.csv` / `GBPUSD1.csv` -- independently
  reproduces the task's own audit table exactly. See `docs/DATA_AUDIT.md`.
- **48 pytest tests**, all passing, covering the account-risk floors, the
  pre-trade projected-equity check, the daily/total stop state machine
  (restart, second-instance guard, history reconciliation), timezone/DST
  handling, symbol/lot-sizing math, the signal state machine, and order
  execution (same-bar SL/TP collision, gap fills, spread/commission
  accounting). See `docs/RISK_SPEC.md` for the mapping to the spec's 11
  mandated test scenarios (10 of 11 -- everything except the MT4-only
  OrderSend-timeout scenario, which needs a real terminal).
- **One EXPLORATORY baseline backtest** over the ~2-month sample (one full
  calendar month, August 2026) on the shared two-instrument portfolio
  simulator. Result: 14 trades, net -147.75 USD (-1.48%), 0 risk-floor
  breaches. See `reports/run_001/REPORT.md` -- **this is not evidence of a
  repeatable monthly result**; see spec section 10 and `docs/UNKNOWNS.md`.

## What was NOT run

- The MQL4 EA and Include files (`mql4/`) were never opened in MetaEditor
  and never compiled. They are a structurally complete, line-by-line
  mirror of the tested Python logic, offered for someone with MT4 access to
  compile, review, and test against the MT4 Strategy Tester (see
  `docs/RISK_SPEC.md` test 10 and test 6/7/9's MQL4-specific halves).
- Commission and the real server clock/DST offset are unconfirmed (see
  `docs/UNKNOWNS.md`); every report generated from this codebase is labeled
  EXPLORATORY for exactly this reason among others.
- No parity test between the Python offline engine and the MQL4/MT4
  Strategy Tester has been run (needs MT4). Both engines implement the same
  rules but the ATR/EMA warmup numerics are expected to differ slightly
  near the edges (documented in `python/ftmo_sim/signals.py` and
  `mql4/Include/FTMO/Signals_LondonBreakoutRetest.mqh`).

## Layout

```
config/config.example.json   Every parameter, unconfirmed ones explicitly labeled
data/raw/EURUSD1.csv         Raw M1 data, unchanged, SHA-256 verified
data/raw/GBPUSD1.csv
docs/UNKNOWNS.md             Confirmed vs. still-unknown parameters
docs/DATA_AUDIT.md           Independently reproduced data audit
docs/RISK_SPEC.md            Risk formulas + mapping to the 11 mandated tests
python/ftmo_sim/             Tested: time/symbol/risk/signal/execution/simulator/report modules
python/tests/                48 passing pytest tests
python/scripts/run_baseline.py   Runs the fixed baseline end to end
reports/run_001/              Output of the one EXPLORATORY baseline run
mql4/Include/FTMO/            NOT_RUN: Config/TimeUtils/SymbolSpec/AccountRisk/
                               Signals/OrderExec/Persistence/Logging
mql4/Experts/FTMO_Swing_EA.mq4  NOT_RUN: single-account EA wiring the above
```

## Exact commands

```bash
cd python

# Re-run the data audit (reproduces docs/DATA_AUDIT.md)
python3 -m ftmo_sim.data_audit ../data/raw/EURUSD1.csv ../data/raw/GBPUSD1.csv

# Run the test suite (48 tests, no dependencies beyond pytest)
pip install -r requirements-dev.txt
python3 -m pytest -q

# Run the fixed baseline over the supplied data
python3 scripts/run_baseline.py \
    --config ../config/config.example.json \
    --eurusd ../data/raw/EURUSD1.csv \
    --gbpusd ../data/raw/GBPUSD1.csv \
    --out-dir ../reports/run_001
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
  same-direction EURUSD+GBPUSD ideas.
- No martingale, no grid, no adding to losers, no increasing risk to chase
  the monthly target or recover a loss.

## Strategy summary (fixed baseline v1, spec section 7)

London Range Breakout + Retest: range = [00:00,07:00) London; entries only
in [08:00,11:00); breakout on a closed M5 candle; retest confirmation
within the next 6 M5 candles; H1 EMA200 direction filter; SL = retest
extreme +/- 0.10*ATR14(M5); TP = 2R; one trade per instrument per London
day; force-close at 16:00 London. No indicators or filters beyond this were
added.

## Three open questions for the account owner

1. **Server clock**: what is the broker's actual server-time UTC offset and
   does it observe its own DST (and which calendar)? This gates every
   wall-clock-sensitive claim in `docs/UNKNOWNS.md` item 1.
2. **Commission**: what is the actual round-turn commission per lot for
   this account/symbol pair? Currently `null` (unconfirmed) in the config.
3. Given the baseline lost money (net -147.75 USD) over the only available
   sample, and the sample is far too short to judge a monthly-target
   strategy either way -- is the priority (a) more historical data, (b) a
   second candidate strategy (spec section 7 mentions a failed-breakout
   reversal as future work), or (c) parameter/config review of this same
   baseline first?
