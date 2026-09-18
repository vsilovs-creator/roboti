# FTMO 2-Step Swing MT4 robot -- full project report

**Purpose of this document:** a complete, self-contained handoff so a
different AI system or researcher (the account owner asked for this to be
prepared for another model, referred to as "GPT-6 astra") can pick up this
project with full context and continue it -- specifically the search for a
trading approach with genuine (not overfit) positive expectancy, but also
everything else needed to understand or extend the project. Read this whole
document before acting on it. Everything below was actually run and
verified in this session unless explicitly marked otherwise.

Repository: `https://github.com/vsilovs-creator/roboti`, path
`ftmo-swing-mt4/`. This document repeats the key facts and numbers inline so
it stands alone, but the repo has the full code, tests, and raw data.

**Updated 2026-09-18 after an independent code audit** found two P0 bugs
in the offline simulators (an entry candle's own SL/TP was never checked;
configured portfolio/correlated-group risk caps were not enforced in one
of the two simulators) that affected every number in an earlier version of
this report. Both are fixed, independently reproduced before and after the
fix, and every number below is from the corrected code. See
`docs/AUDIT_2026-09-18.md` for the full detail -- this section only exists
so a reader of an older copy of this report knows it's stale.

---

## 1. What this project is

An MT4/MQL4 trading-robot prototype for an **FTMO 2-Step Swing** account
(USD, 10 000 USD starting balance), trading **EURUSD + GBPUSD**, built
under a hard, tested, account-wide risk-management engine. The original
task specification (in Latvian, ~5000 words, summarized throughout this
report) required: independently re-auditing the supplied price data,
implementing and testing the risk-limit logic before any strategy work,
implementing one fixed baseline strategy, running it honestly (including
reporting a loss if that's the result), and being explicit at every step
about what is a confirmed fact, what is a design choice, and what remains
unknown. This report follows that same discipline.

**Status: EXPLORATORY.** Nothing in this project is authorized to trade a
real account. The Python side (data audit, risk engine, strategies,
simulator, 54 passing tests) actually ran in this session. The MQL4/MT4
side has never been compiled or executed -- no MetaEditor/MT4 was available
in this environment; it is a structurally complete, uncompiled translation
of the tested Python logic, marked **NOT_RUN** everywhere it appears.

## 2. Confirmed facts (from the account owner, this session)

| Fact | Value | Where it's encoded |
|---|---|---|
| Server clock | GMT+2 winter/standard, GMT+3 summer/DST, same transition dates as the EU | `ServerTimeModel(mode="zone_like", hypothesis_zone_name="Europe/Bucharest", verified=True)` in Python; `ServerUTCOffsetHours=2.0, ServerObservesEUDST=true` in MQL4 `Config.mqh` |
| Commission | 2.50 USD per lot per side = 5.00 USD round-turn total | `commission_round_turn_usd_per_lot: 5.0` in `config/config.example.json` |
| Further historical data | **None will be supplied. This is permanent.** | -- |
| Instrument specs (both EURUSD, GBPUSD) | Digits=5, floating spread, stops level=0, contract size=100000, min/max lot 0.01/50.00, lot step 0.01, swap long/short EURUSD -11.06/+0.59 GBPUSD -6.78/-3.76, triple-swap Wednesday, sessions Mon-Fri 00:00-23:55 quotes / 00:05-23:55 trade, none Sat/Sun | From instrument-specification screenshots, matches `config/config.example.json` exactly |

Still **unconfirmed** (never silently assumed, always labeled): actual
leverage/margin call behavior, historical spread/slippage distribution
(CSVs are Bid-only M1 OHLC, no tick Bid/Ask), freeze level, historical
swap-rate changes, whether MT4's built-in iATR/iMA numerics match this
project's hand-rolled Python warmup exactly (a parity test needs real MT4).

## 3. Data

`data/raw/EURUSD1.csv` and `data/raw/GBPUSD1.csv`: M1 OHLC, no header,
`YYYY.MM.DD,HH:MM,Open,High,Low,Close,Volume`. Independently re-audited
(`python/ftmo_sim/data_audit.py`) -- results match the task's own claimed
audit table exactly:

| Check | EURUSD1.csv | GBPUSD1.csv |
|---|---|---|
| SHA-256 | `5f97acdd75114b27db880ecc74fdc1f73087dc8c56b91b168ded3ff310494ad2` | `367290d4be0bb6ee0c8f0333dd95fac349e27e41a65194b5dd97290e6453d393` |
| Row count | 65126 | 65352 |
| First / last timestamp (file-local) | 2026-07-16 00:36 / 2026-09-17 23:05 | 2026-07-15 21:57 / 2026-09-17 23:06 |
| Distinct calendar days | 46 | 47 |
| Duplicate / invalid / non-monotonic rows | 0 / 0 / 0 | 0 / 0 / 0 |
| Gaps >1 min (weekend / suspected intraday) | 364 (9 / 355) | 271 (9 / 262) |

**~2 months, exactly one full calendar month (August 2026).** This is the
single hardest constraint on everything below: it is not enough data to
distinguish a real trading edge from noise for any technical strategy, and
it will never be extended.

## 4. Risk engine (tested, fixed -- not in scope for strategy work)

All amounts USD, `B0` = balance at 00:00 Europe/Prague ("FTMO day"):

- Robot daily working floor: `B0 - 300`. Robot static total working floor:
  `9200` (tighter than FTMO's own raw 500/9000 limits, tracked separately
  as reference). **Both checked directly and independently** against
  equity every tick -- not only via `max()` of the two -- so reaching the
  static 9200 floor always sets the sticky total stop even when the daily
  floor alone is currently looser (e.g. early in a challenge). Daily stop
  clears automatically the next correctly-reconstructed FTMO day; total
  stop is sticky, cleared only by explicit manual review.
- Pre-trade check before any new entry: projected worst-case equity (current
  equity minus every other open position's *remaining* risk to its own SL,
  minus the new order's full risk, minus an execution buffer) must stay
  strictly above the applicable floor. Uses current equity directly (never
  re-derives balance minus floating loss, which would double-count).
- Account-wide: scans **every** open position on the account, not just this
  EA's positions; an unknown/unbounded-risk foreign position (no SL) blocks
  new entries outright.
- Position sizing: 25 USD risk per idea, floored to the symbol's lot step,
  sized from the **actual transacted price** (including spread), not the
  raw quote -- an earlier draft used the raw quote and understated risk by
  the spread on every trade, worst on the tightest stops; this is fixed and
  tested. 100 USD max concurrent portfolio risk, 50 USD cap for correlated
  (same-USD-direction) EURUSD+GBPUSD ideas.
- No martingale, no grid, no adding to losers, no increasing risk to chase
  a target or recover a loss.

54 pytest tests cover this (`python/tests/`), including 10 of the 11
mandated risk/execution scenarios from the original task spec (the 11th --
OrderSend timeout handling -- is MQL4-only and needs a real MT4 terminal to
test).

## 5. Strategies tried and their full results

All three ran through the identical account-wide risk engine, the same
confirmed costs (5 USD/lot commission, confirmed server clock), and the
same ~2-month sample. **All three lost money.**

### 5a. London Range Breakout + Retest v1 (the spec-mandated fixed baseline)

Range = [00:00,07:00) London; entries only [08:00,11:00); breakout on a
closed M5 candle; retest confirmation within next 6 M5 candles; H1 EMA200
direction filter; SL = retest extreme +/- 0.10*ATR14(M5); TP = 2R; one trade
per instrument per London day; force-close at 16:00 London.

- Net: **-446.71 USD (-4.47%)**. Trades: 20. Win rate: 20.0%.
- Avg win R: 1.06. Avg loss R: -1.38. Expectancy: -22.34 USD/trade. Profit factor: 0.19.
- Max drawdown from peak: 446.71 USD. Lowest equity: 9553.29 (margin to 9200 floor: +353.29).
- 0 risk-floor breaches. 1/20 same-bar SL/TP ambiguity. 3/20 gap fills.
- Monthly: Jul (partial) -75.60/1 trade, **Aug (full month) -272.88/13 trades**, Sep (partial) -98.23/6 trades.
- 0/1 full calendar months met the >=2000 USD / 20% target.

### 5b. EMA(20/50) H1 crossover (chosen as "least-bad of three", NOT validated)

Standard trend crossover; SL = 1.5x ATR14(H1); TP = 3R; holds positions
overnight/across the 16:00 London boundary (swing-style).

- Net: **-296.65 USD (-2.97%)**, including **-23.27 USD swap** accrued
  over 26 nights held (see `docs/AUDIT_2026-09-18.md` P1-5 -- an
  approximation, not a confirmed swap-timing model). Trades: 25. Win rate: 16.0%.
- Avg win R: 2.67. Avg loss R: -1.04. Expectancy: -11.87 USD/trade. Profit factor: 0.48.
- Max drawdown from peak: 365.16 USD. Lowest equity: 9703.35 (margin to 9200 floor: +503.35).
- 0 risk-floor breaches. 0/25 same-bar ambiguity. 0/25 gap fills. 0 positions
  still open at the end of the sample.
- 6 signals skipped (symbol already had an open position), 3 skipped by the
  correlated-group/portfolio risk cap.
- Monthly: Jul (partial) **+26.65/6 trades**, Aug (full month) -175.29/14 trades, Sep (partial) -124.74/5 trades.
- 0/1 full calendar months met target.
- This is the strategy currently marked `strategies.active` in the config
  and ported to MQL4 (`mql4/Experts/FTMO_Swing_EA_EmaCross.mq4`, NOT_RUN),
  chosen only because it lost the least of the three -- **not** because it
  showed a real edge.

### 5c. Bollinger(20,2) H1 mean-reversion (tried, not chosen, not ported to MQL4)

Fade a close outside the 20-period/2-stddev band toward the middle band; SL
= 0.5x ATR14(H1) beyond the breached band.

- Net: **-784.45 USD (-7.84%)**, including -52.42 USD swap. Trades: 84
  (much higher frequency than the other two). Win rate: 21.4%.
- Avg win R: 2.21. Avg loss R: -1.06. Expectancy: -9.34 USD/trade. Profit factor: 0.57.
- Max drawdown from peak: 867.73 USD. **Lowest equity: 9215.55 -- only 15.55
  USD above the static 9200 total floor.** No breach occurred, but this is
  the riskiest of the three by a wide margin (high frequency x negative
  expectancy), independent of its net P/L.
- 0/84 same-bar ambiguity. 1/84 gap fills.
- 130 signals skipped by the pre-trade projected-equity check, 59 skipped
  because a position was already open, 21 skipped by the correlated-group/
  portfolio risk cap -- this strategy's frequency runs into the risk
  engine's own limits constantly.
- Monthly: Jul (partial) -267.52/36 trades, Aug (full month) -464.51/48 trades. (No Sep trades survived the September partial window in this run.)
- 0/1 full calendar months met target.

## 6. The multiple-comparisons / overfitting demonstration

After all three lost money, the account owner asked to search harder for a
positive result. Before doing an unprincipled parameter search, one was run
**deliberately as a demonstration**, and the result is the single most
important finding in this report for whoever continues the work:

`python/scripts/sweep_overfitting_demo.py` ran **81 parameter combinations**
of the EMA-crossover strategy (fast period in {10,20,30}, slow period in
{40,50,100}, ATR-SL multiple in {1.0,1.5,2.0}, TP-R multiple in
{1.5,2.0,3.0}) against the exact same fixed sample.

**Result: 21 of 81 (26%) came out net positive.** The best:
`fast=30, slow=100, atr_sl=2.0, tp_r=3.0` -> +385.95 USD (+3.86%), 10
trades. The worst: `fast=10, slow=50, atr_sl=1.0, tp_r=2.0` -> -597.16 USD.
Full grid: `reports/run_009_overfitting_sweep_corrected/sweep_results.csv`.

**Conclusion, stated no more strongly than the evidence supports (revised
after this report's own independent code audit -- see
`docs/AUDIT_2026-09-18.md` P1-8, which correctly pointed out an earlier
version overstated this):** a quarter of arbitrary parameter combinations
coming out positive on a fixed ~40-trading-day sample is a real reason for
caution about any single "positive" result from this family of strategies
on this sample -- with enough tries, something is likely to look positive
whether or not there's a real edge underneath. That is *not* a formal
proof that the positive results are noise (there is no null model or
dependency-aware significance test behind the 26% figure), and the short
sample doesn't prove the strategy family can't work either. None of these
21 "positive" results have been or should be adopted on this evidence
alone. **Any continuation of this search that just tries more parameters
or more strategies and reports the best-looking number without addressing
that caveat will produce an equally uninterpretable result -- see section 8
for what a rigorous version of this test would need.**

## 7. MQL4 status (all NOT_RUN)

The 2026-09-18 audit found and structurally fixed two real bugs here (a
persisted-state read bug that would have broken every EA restart, and an
unprotected-position/stop-retry gap) -- see `docs/AUDIT_2026-09-18.md`
P0-3/P0-4. Neither the bugs nor the fixes have been compiled or run; this
whole section remains NOT_RUN.

- `mql4/Include/FTMO/`: `Config.mqh`, `TimeUtils.mqh`, `SymbolSpec.mqh`,
  `AccountRisk.mqh`, `OrderExec.mqh`, `Persistence.mqh`, `Logging.mqh`
  (shared by both EAs below), plus `Signals_EmaCross.mqh` (chosen strategy)
  and `Signals_LondonBreakoutRetest.mqh` (reference strategy).
- `mql4/Experts/FTMO_Swing_EA_EmaCross.mq4` -- the chosen strategy's EA.
- `mql4/Experts/FTMO_Swing_EA.mq4` -- the London breakout EA, kept as
  reference only.
- **Only one of these two EAs may be attached to a given account at a
  time** -- both share one account-scoped risk-state file by design (one
  controller per account, per the original spec), so running both at once
  would have two processes racing to write the same file.
- None of this has been opened in MetaEditor or compiled. No parity test
  against the Python engine has been run (needs MT4). The Bollinger
  mean-reversion strategy was never ported to MQL4 (not chosen).

## 8. What is actually being asked of you (the receiving model/researcher)

The account owner's instruction, translated: *"Search for a strategy that
is positive; if you [the current assistant] can't, hand the task to
another model."* Given section 6 above, "just find something positive" is
not a real answer here -- it's demonstrably too easy to do by accident. The
actual problem is:

> Find (or make a well-argued case that there is no honest way to find,
> within this project's fixed ~2-month, no-more-data constraint) a trading
> approach for EURUSD+GBPUSD on this FTMO Swing account whose positive
> backtest result would be credible evidence of a real edge -- not an
> artifact of having tried enough things.

Concrete paths, roughly in order of how likely they are to produce
something trustworthy rather than a bigger version of the section-6 trap:

1. **A statistically disciplined test of what's already been tried** --
   e.g. a permutation/Monte Carlo test (with block resampling that respects
   day/instrument dependence, not naive shuffling) asking whether any of
   the three strategies' actual results are distinguishable from a random
   entry rule with the same risk management, on this same data. This needs
   no new data and directly answers the overfitting concern.
2. **A strategy with an economic/structural rationale statable without
   reference to this specific dataset** (a documented microstructure,
   liquidity, or intermarket effect; a volatility-regime filter with a
   reason independent of this window) -- backtest only to check it isn't
   immediately contradicted, not to search for the best-fitting variant.
3. **A forward/demo-test plan** -- since no more historical data is coming,
   propose what a demo-account forward test should log and for how long to
   generate genuinely new evidence, which this project currently has no
   other way to obtain.
4. **The honest null result**: conclude that 2 months of 1-pair-at-a-time
   M1 data is simply insufficient for any technical strategy here, matching
   what the original task specification itself anticipated (it named
   "5+ years of tick Bid/Ask coverage" as what would actually be needed for
   a validated monthly-return claim). This is a legitimate and useful
   deliverable, not a failure to answer the question.
5. If more strategies or parameters are tried anyway, **pre-register how
   many and report all of them**, exactly as section 6 does (26% positive
   rate stated up front, not just the +386 USD headline) -- never report
   only the best result from a search. Better still, pair it with an actual
   significance test (a block-resampled permutation test against this same
   grid, for instance) rather than reporting the raw hit rate alone --
   section 6's own audit critique (P1-8) applies here too.

### Explicit do-nots

- Do not tune parameters against this fixed sample and present the best
  result as "the" answer.
- Do not fabricate additional historical data or treat synthetic price
  paths as if real.
- Do not weaken or bypass the account-wide risk engine (section 4) to make
  a strategy look better -- it is fixed, tested, and out of scope for
  strategy work.
- Do not claim the MQL4 side compiles or was tested in MT4 unless you
  actually have MetaEditor/MT4 access and did so.

### Deliverable expected back

Either (a) a new strategy/filter implemented the same way as the existing
ones (`python/ftmo_sim/strategy_ema_cross.py` /
`strategy_bb_reversion.py` are the templates -- a small engine class
plugging into `simulator_ema_cross.run_h1_signal_simulation`'s
`engine_factory`), with a rationale independent of this dataset and honest,
fully-reported backtest numbers; or (b) the permutation-test analysis from
path 1 above, with a clear conclusion; or (c) a well-argued version of path
4, the honest null result, with a recommendation for what would actually
be needed (more/different data, a different problem framing, live forward
testing) to make progress from here.
