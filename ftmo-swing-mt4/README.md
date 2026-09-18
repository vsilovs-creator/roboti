# FTMO 2-Step Swing -- MT4 robot prototype (v1)

**Status: EXPLORATORY offline research.** Signal-only / dry-run by default.
Nothing here is authorized to trade a real FTMO account, and no MQL4 file
has been compiled or run in MT4/MetaEditor -- no MetaEditor/MT4 was
available in this environment. Every claim below says explicitly whether it
was actually executed (Python) or is an uncompiled translation offered for
review (MQL4, marked **NOT_RUN**).

Account: FTMO 2-Step Swing, USD, 10 000 USD starting balance. Instruments:
EURUSD + GBPUSD.

**2026-09-18: an independent code audit found two P0 bugs in the offline
simulators that affected every number below through an earlier version of
this README.** Both are fixed, all affected results recomputed, and this
document reflects the corrected numbers. See `docs/AUDIT_2026-09-18.md` for
what was found, how it was independently reproduced, and what changed.

## Chosen strategy going forward: EMA(20/50) H1 crossover

Per the account owner's instruction (2026-09-18, "turpinam to strategiju ar
kuru ir lielaka pelna" -- continue with whichever strategy has the biggest
profit) and the fact that **no further historical data will be supplied**:
of the three strategies compared below, EMA(20/50) H1 crossover had the
smallest loss (-296.65 USD / -2.97%) on the only available ~2-month sample.
It is now `strategies.active` in `config/config.example.json`, has its own
runner (`python/scripts/run_ema_cross.py`), and has been ported to MQL4
(`mql4/Experts/FTMO_Swing_EA_EmaCross.mq4`, NOT_RUN).

**This is "least-bad of three on one short sample," not "validated" or
"expected profitable."** It still lost money on the only data that exists,
and with no more data coming, that result can never be re-checked
out-of-sample. See "Interpretation" and "Multiple-comparisons demo" below
before treating this as more than it is.

## Confirmed facts (account owner, 2026-09-18)

- **Server clock:** FTMO's MT4 server runs GMT+2 in winter/standard time,
  GMT+3 in summer/DST, on the same transition dates as the EU.
- **Commission:** FTMO's forex/exotics commission is 2.50 USD per lot per
  side, i.e. 5.00 USD total per round-turn lot.
- **No further historical data will be supplied.** The ~2-month sample
  (2026-07-15/16 to 2026-09-17, one full calendar month) is final; every
  result in this repo is now permanently limited to that window and cannot
  be walk-forward validated against fresh data.

Applying the clock and commission to the baseline changed the result
materially, and fixing the two P0 simulator bugs (see
`docs/AUDIT_2026-09-18.md`) changed it again. See `reports/README.md` for
the full history: `run_001` and `run_002_confirmed_tz_commission` are both
superseded; `run_006_baseline_corrected` is current.

## What was actually run here

- **Data audit** (`python/ftmo_sim/data_audit.py`) against the real,
  SHA-256-verified `data/raw/EURUSD1.csv` / `GBPUSD1.csv` -- independently
  reproduces the task's own audit table exactly. See `docs/DATA_AUDIT.md`.
- **60 pytest tests**, all passing, covering the account-risk floors, the
  pre-trade projected-equity check, the daily/total stop state machine
  (restart, second-instance guard, history reconciliation), confirmed
  timezone/DST handling, symbol/lot-sizing math, all three strategies'
  signal state machines, order execution (same-bar SL/TP collision, gap
  fills, spread/commission accounting, session-close on/off), swap
  accrual, and the two P0 simulator bugs found by the 2026-09-18 audit
  (regression tests pin both fixes down). See `docs/RISK_SPEC.md` for the
  mapping to the spec's 11 mandated test scenarios (10 of 11 -- everything
  except the MT4-only OrderSend-timeout scenario, which needs a real
  terminal).
- **A search for a profitable strategy on this sample**, per the account
  owner's explicit request ("meklē peļņu ar jebkuru tev zināmo stratēģiju").
  Three independent, well-known strategies at standard textbook parameters
  were run on the exact same data, account-wide risk engine, and confirmed
  costs -- see `reports/run_008_strategy_comparison_corrected/COMPARISON.md`:

  | Strategy | Trades | Win rate | Net USD | Profit factor |
  |---|---|---|---|---|
  | London Range Breakout + Retest v1 | 20 | 20.0% | -446.71 | 0.19 |
  | **EMA(20/50) H1 crossover (chosen)** | 25 | 16.0% | **-296.65** | 0.48 |
  | Bollinger(20,2) H1 mean-reversion | 84 | 21.4% | -784.45 | 0.57 |

  **All three lose money on this exact ~2-month sample after real costs.**
  This was a comparison across distinct known strategies at standard
  parameters, not a parameter search/optimization over any one of them --
  spec section 8 explicitly warns against wide optimization on this short a
  dataset, and hunting for a locally profitable parameter combination on
  ~40 trading days would produce a curve-fit number, not a finding.
  - **Risk observation:** the Bollinger mean-reversion run's lowest equity
    (9215.55 USD) came within 15.55 USD of the static 9200 total working
    floor -- no breach occurred, but its high trade frequency (84 trades)
    combined with negative expectancy made it the riskiest of the three by
    a wide margin, independent of its net P/L.

## Interpretation -- why picking a "winner" here is not the same as finding a profitable strategy

- The sample is genuinely short: ~2 months, one full calendar month, and now
  final -- no more data is coming. Any of the three strategies could easily
  lose on this single window even with long-run positive expectancy; that
  is not strong evidence against any of them individually, but it does mean
  none of them can be shown to work with the data on hand.
- 5 USD/lot commission is a real, meaningful drag relative to the 25 USD
  risk-per-idea budget (roughly 20% of a typical loss, and a comparable
  bite out of small wins) -- it disproportionately hurts higher-frequency
  strategies (compare the Bollinger strategy's 84 trades vs. the
  breakout's 20; EMA crossover's lower frequency, 25 trades, is part of why
  it lost the least). EMA crossover also now carries a modeled swap cost
  (-23.27 USD over 26 nights held, since it holds positions overnight) that
  the other two strategies don't -- see `docs/AUDIT_2026-09-18.md` P1-5.
- Choosing EMA crossover to carry forward is a reasonable, honest use of
  the only comparison available (least-bad of three), not a claim that it
  is expected to be profitable going forward.

## Multiple-comparisons demo -- why "search harder for a positive one" doesn't work here

The account owner separately asked for a strategy that comes out positive,
and to hand the search off to another model/agent if this one couldn't
produce one. Before doing either, `python/scripts/sweep_overfitting_demo.py`
ran 81 EMA-crossover parameter combinations (fast/slow period x ATR-SL
multiple x TP-R multiple) against the exact same fixed sample --
**21 of 81 (26%) came out net positive**, up to +385.95 USD (+3.86%) for one
specific combination (fast=30, slow=100, atr_sl=2.0, tp_r=3.0). Full grid:
`reports/run_009_overfitting_sweep_corrected/sweep_results.csv`.

**None of these 21 "positive" results are being adopted.** A quarter of
arbitrary parameter combinations coming out positive on a fixed
~40-trading-day sample is a real reason for caution -- with enough tries,
something is likely to look positive regardless of whether there's a real
edge underneath. That is not the same claim as "this proves the positive
results are noise": there is no formal null model or dependency-aware
significance test behind that 26% figure (a fair critique this project
received and accepts -- see `docs/AUDIT_2026-09-18.md` P1-8), and the short
sample doesn't prove the strategy family can't work either. What the sweep
does support is: picking the top of this grid and calling it "the
strategy" would be reporting an unvalidated, cherry-picked number as a
finding, which is precisely what the original task spec (section 8/10) and
this project's own approach throughout have tried not to do.

This is also the honest answer to "if you can't find one yourself, hand it
to another model": **`docs/FULL_REPORT.md`** is a complete, self-contained
project report and handoff brief for a different AI/agent (or a human
researcher) to continue this search properly -- full background, confirmed
facts, data audit, risk engine, full metrics for all three strategies, this
same sweep result, and more statistically disciplined ways to actually look
for a real edge (a proper permutation/null-model test against the existing
results, a strategy with a rationale independent of this dataset, or a
forward/demo-test plan to generate the new data this project will
otherwise never have). Copy that file's contents into whatever other tool
or model you want to try next. (`docs/HANDOFF_STRATEGY_SEARCH.md` is an
earlier, narrower version of the same brief, kept for reference.)

## What was NOT run

- `mql4/Experts/FTMO_Swing_EA_EmaCross.mq4` and
  `mql4/Include/FTMO/Signals_EmaCross.mqh` (the chosen strategy, NOT_RUN)
  and `mql4/Experts/FTMO_Swing_EA.mq4` (the London breakout, kept as
  reference only) were never opened in MetaEditor and never compiled. Both
  are structurally complete, line-by-line mirrors of their tested Python
  counterparts, offered for someone with MT4 access to compile, review, and
  test against the MT4 Strategy Tester (see `docs/RISK_SPEC.md` test 10 and
  test 6/7/9's MQL4-specific halves). The Bollinger mean-reversion strategy
  was NOT ported to MQL4 -- it was not the chosen strategy. The 2026-09-18
  audit found and structurally fixed real bugs in this MQL4 code (a
  persisted-state read bug that would have broken every EA restart, and an
  unprotected-position / stop-retry gap) -- see `docs/AUDIT_2026-09-18.md`
  P0-3/P0-4 -- but none of it has actually been compiled or run.
- **Only one of the two MQL4 Experts may be attached to a given account at a
  time.** Both share one account-scoped risk-state file by design (single
  controller per account, spec section 5); running both simultaneously would
  have two processes racing to write the same file. See the header comment
  in `FTMO_Swing_EA_EmaCross.mq4`.
- No parity test between the Python offline engine and the MQL4/MT4
  Strategy Tester has been run (needs MT4). Both engines implement the same
  rules but the ATR/EMA warmup numerics are expected to differ slightly
  near the edges (documented in `python/ftmo_sim/signals.py` and the
  `Signals_*.mqh` files).

## Layout

```
config/config.example.json   Every parameter; confirmed values (timezone, commission) labeled as such;
                              strategies.active picks the chosen strategy
data/raw/EURUSD1.csv         Raw M1 data, unchanged, SHA-256 verified
data/raw/GBPUSD1.csv
docs/UNKNOWNS.md             Confirmed vs. still-unknown parameters
docs/DATA_AUDIT.md           Independently reproduced data audit
docs/RISK_SPEC.md            Risk formulas + mapping to the 11 mandated tests
docs/AUDIT_2026-09-18.md     Independent code audit findings and fixes (P0 simulator bugs, MQL4 gaps)
docs/FULL_REPORT.md          Complete, self-contained project report + handoff brief for another AI/agent
docs/HANDOFF_STRATEGY_SEARCH.md  Earlier, narrower version of the same handoff brief (kept for reference)
python/ftmo_sim/             Tested: time/symbol/risk/signal/execution/simulator/report modules,
                              plus strategy_ema_cross.py (chosen) and strategy_bb_reversion.py (tried, not chosen)
python/tests/                60 passing pytest tests
python/scripts/run_baseline.py             Runs the London breakout baseline (reference) end to end
python/scripts/run_ema_cross.py            Runs the CHOSEN strategy end to end
python/scripts/run_strategy_comparison.py  Runs all three strategies side by side
python/scripts/sweep_overfitting_demo.py   Parameter sweep demonstrating the multiple-comparisons risk (not a tuning tool)
reports/                      See reports/README.md for what each run_NNN/ is, which are superseded, and which are current
mql4/Include/FTMO/            NOT_RUN: Config/TimeUtils/SymbolSpec/AccountRisk/
                               OrderExec/Persistence/Logging (shared), plus
                               Signals_EmaCross.mqh (chosen) and
                               Signals_LondonBreakoutRetest.mqh (reference)
mql4/Experts/FTMO_Swing_EA_EmaCross.mq4  NOT_RUN: chosen strategy's EA
mql4/Experts/FTMO_Swing_EA.mq4           NOT_RUN: London breakout EA (reference only)
```

## Exact commands

```bash
cd python

# Re-run the data audit (reproduces docs/DATA_AUDIT.md)
python3 -m ftmo_sim.data_audit ../data/raw/EURUSD1.csv ../data/raw/GBPUSD1.csv

# Run the test suite (60 tests, no dependencies beyond pytest)
pip install -r requirements-dev.txt
python3 -m pytest -q

# Run the CHOSEN strategy (EMA crossover) over the supplied data
python3 scripts/run_ema_cross.py \
    --config ../config/config.example.json \
    --eurusd ../data/raw/EURUSD1.csv \
    --gbpusd ../data/raw/GBPUSD1.csv \
    --out-dir ../reports/run_007_ema_cross_corrected

# Run the London breakout baseline (reference only)
python3 scripts/run_baseline.py \
    --config ../config/config.example.json \
    --eurusd ../data/raw/EURUSD1.csv \
    --gbpusd ../data/raw/GBPUSD1.csv \
    --out-dir ../reports/run_006_baseline_corrected

# Run all three strategies side by side
python3 scripts/run_strategy_comparison.py \
    --config ../config/config.example.json \
    --eurusd ../data/raw/EURUSD1.csv \
    --gbpusd ../data/raw/GBPUSD1.csv \
    --out-dir ../reports/run_008_strategy_comparison_corrected
```

## Risk policy summary (see `docs/RISK_SPEC.md` for the full detail + tests)

- Robot daily working floor `B0 - 300`; robot static total working floor
  `9200` (both FTMO's own looser 500/9000 limits are tracked separately as
  reference). Both checked directly and independently against equity; the
  total floor is sticky (manual-review-only clear), the daily floor clears
  automatically the next correctly-reconstructed FTMO day.
- Account-wide: every open position on the account is scanned, not just
  this EA's MagicNumber; an unknown-risk foreign position blocks new
  entries. The account-wide risk-STOP closure action (not just the scan)
  is also account-wide, not filtered by MagicNumber, as of the 2026-09-18
  audit fix -- see `docs/AUDIT_2026-09-18.md` P0-4.
- 25 USD risk per idea (50 USD alt scenario, both config-only, not FTMO
  rules), 100 USD max concurrent, 50 USD correlated-group cap for
  same-direction EURUSD+GBPUSD ideas. All three strategies searched above
  run under this exact same risk engine; the 2026-09-18 audit found and
  fixed a gap where the H1 simulator (EMA crossover / Bollinger reversion)
  never actually enforced the 100/50 USD caps -- see
  `docs/AUDIT_2026-09-18.md` P0-2.
- No martingale, no grid, no adding to losers, no increasing risk to chase
  the monthly target or recover a loss.

## Strategies tried (spec section 7 baseline + 2 additional per the profit search)

1. **EMA(20/50) H1 crossover** (`strategy_ema_cross.py` / `Signals_EmaCross.mqh`)
   -- **CHOSEN going forward**: standard trend crossover, SL = 1.5x
   ATR14(H1), TP = 3R, holds across the session-close boundary (a
   swing-style design, arguably a better fit for a Swing account than an
   intraday one). Config: `strategies.ema_cross_v1`.
2. **London Range Breakout + Retest v1** (fixed baseline, spec section 7,
   kept as reference): range = [00:00,07:00) London; entries only in
   [08:00,11:00); breakout on a closed M5 candle; retest confirmation
   within the next 6 M5 candles; H1 EMA200 direction filter; SL = retest
   extreme +/- 0.10*ATR14(M5); TP = 2R; one trade per instrument per London
   day; force-close at 16:00 London. Config: `strategies.london_breakout_retest_v1`.
3. **Bollinger(20,2) H1 mean-reversion** (`strategy_bb_reversion.py`, tried,
   not chosen, not ported to MQL4): fade a close outside the 20-period/
   2-stddev band back toward the middle band, SL = 0.5x ATR14(H1) beyond
   the breached band.

No indicators or filters beyond what each strategy's own definition
specifies were added to any of the three.

## MQL4 test instructions (STATIC_REVIEW only -- not yet executed)

None of the MQL4 code in this repo has been compiled or run; every claim
about it is a structural/static review, not a verified test. If MetaEditor/
MT4 becomes available, this is the minimum concrete sequence to move any
item from STATIC_REVIEW to EXECUTED (do this on a DEMO account only,
`EnableLiveTrading=false`):

1. Copy `mql4/Include/FTMO/*.mqh` into `<terminal data folder>/MQL4/Include/FTMO/`
   and `mql4/Experts/*.mq4` into `<terminal data folder>/MQL4/Experts/`.
2. Open both `.mq4` files in MetaEditor and compile (F7). Fix any syntax
   error MetaEditor reports -- this alone would already upgrade the "brace/
   paren-balance-only" check done in this environment to a real compile
   check.
3. Attach `FTMO_Swing_EA_EmaCross.mq4` to an EURUSD chart on a DEMO account
   with `EnableLiveTrading=false` (the default). Confirm in the Experts log:
   a) `AcquireInstanceLock` succeeds (no FATAL on OnInit); b) attaching a
   SECOND copy of either EA to the same account in the same terminal FAILS
   OnInit with the lock message -- this is the concrete test for the
   section-4.6 instance-lock fix.
4. Let it run for a few closed H1 bars and diff the `DRYRUN`/`SIGNAL` log
   lines' lot sizes and skip reasons against `python/run_ema_cross.py`'s
   output for the same symbol/period, to sanity-check the commission-folded
   lot sizing (`LotsForRisk` with `extraCostUsdPerLot`) and the portfolio/
   correlated-cap check (`NewIdeaWithinRiskCaps`) agree with the Python side
   bar-for-bar.
5. To test the section-4.4 unprotected-position path without a real broker
   failure, temporarily force `OrderModify` and `OrderClose` to fail (e.g.
   comment out the real calls and return `false`) in a scratch copy, confirm
   `MarkUnprotected`+`SaveRiskState` fires, restart the terminal, and confirm
   `ReconcileUnprotectedPosition` still retries the SAME ticket after
   restart (proving persistence survived, not just in-memory retry) before
   restoring the real calls.

## Open questions for the account owner

1. Given the multiple-comparisons demo above (26% of arbitrary parameter
   combinations looked "positive" on this sample) -- do you want (a) one of
   those 21 combinations adopted anyway, with this overfitting risk
   explicitly accepted, (b) `docs/FULL_REPORT.md` handed to
   another model/researcher to pursue a statistically sound answer, (c) a
   demo-account forward test to start generating the new data this project
   will otherwise never have, or (d) accept EMA crossover as-is (the
   current default) and move on?
2. Should `FTMO_Swing_EA.mq4` (London breakout) be removed from the repo
   now that it is not the chosen path, or kept as reference/history? It is
   currently kept but clearly marked as reference-only in this README and
   in `Config.mqh`.
3. Confirming the MQL4 side actually runs (compiling in MetaEditor,
   sanity-checking `EnableLiveTrading=false` dry-run output against the
   Python `run_ema_cross.py` output for a few real ticks) is the largest
   remaining gap before this can be trusted even at the "compiles and
   behaves as designed" level -- is MT4/MetaEditor access something you can
   provide, or should the next session attempt this a different way?
4. UPDATE 2026-09-18 (follow-up audit): the instance-guard critique
   (`docs/AUDIT_2026-09-18.md` P1-6) is now partially closed --
   `Persistence.mqh` has a real exclusive-open lock file
   (`AcquireInstanceLock`/`ReleaseInstanceLock`) that blocks a second EA
   instance in the SAME terminal/account. It still cannot stop a second
   MT4 TERMINAL INSTALLATION (different data folder/machine) from trading
   the same account unopposed -- see `docs/UNKNOWNS.md` item 8. Worth a
   dedicated pass (or a broker-side control) before any live/demo use.
