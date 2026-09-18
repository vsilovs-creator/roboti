# FTMO 2-Step Swing MT4 robot -- full project report

**Purpose of this document:** a complete, self-contained handoff so a
different AI system or researcher (the account owner asked for this to be
prepared for another model, referred to as "GPT-6 astra") can pick up this
project with full context and continue it. Read this whole document before
acting on it. Everything below was actually run and verified in this
project's Python sessions unless explicitly marked otherwise; MQL4 is
NOT_RUN throughout, explained in section 7.

Repository: `https://github.com/vsilovs-creator/roboti`, path
`ftmo-swing-mt4/`. This document repeats the key facts and numbers inline
so it stands alone, but the repo has the full code, tests, raw data, and
per-run artifacts (trade/equity/signal CSVs, machine-readable summaries).

**Updated 2026-09-18 (second session, same day)** after a follow-up
independent audit found and fixed two more real bugs beyond the first
audit round (a cross-symbol same-tick causality leak, and an end-of-run
equity/balance mismatch), closed the remaining MQL4 risk-parity items
structurally, folded commission into the sizing budget on both the Python
and MQL4 sides, and then ran a NEW, pre-registered, fixed-parameter
(no grid search) comparison of **eight** strategy variants across
**three** cost-stress scenarios -- 24 total runs. This report's section 5
is a full rewrite to cover that; sections 1-4 and 7 are updated in place;
see `docs/AUDIT_2026-09-18.md` (both rounds) and
`docs/STRATEGY_RESEARCH_2026-09-18.md` for the complete detail behind
every number quoted here.

---

## 1. What this project is

An MT4/MQL4 trading-robot prototype for an **FTMO 2-Step Swing** account
(USD, 10,000 USD starting balance), trading **EURUSD + GBPUSD**, built
under a hard, tested, account-wide risk-management engine. The original
task specification (in Latvian, summarized throughout this report)
required: independently re-auditing the supplied price data, implementing
and testing the risk-limit logic before any strategy work, implementing a
fixed baseline strategy, running it honestly (including reporting a loss
if that's the result), and being explicit at every step about what is a
confirmed fact, what is a design choice, and what remains unknown. This
report follows that same discipline.

**Status: EXPLORATORY.** Nothing in this project is authorized to trade a
real account, and nothing in this report changes that. The Python side
(data audit, risk engine, eight strategies, portfolio simulators, 98
passing tests) actually ran. The MQL4/MT4 side has never been compiled or
executed -- no MetaEditor/MT4 was available in any session so far; it is a
structurally complete, uncompiled translation of the tested Python risk
logic (for the two strategies ported so far), marked **NOT_RUN**
everywhere it appears, with a concrete test sequence in `README.md` for
whoever gets real MT4 access.

## 2. Confirmed facts (from the account owner)

| Fact | Value | Where it's encoded |
|---|---|---|
| Server clock | GMT+2 winter/standard, GMT+3 summer/DST, same transition dates as the EU | `ServerTimeModel(mode="zone_like", hypothesis_zone_name="Europe/Bucharest", verified=True)` in Python; `ServerUTCOffsetHours=2.0, ServerObservesEUDST=true` in MQL4 `Config.mqh` |
| Commission | 2.50 USD per lot per side = 5.00 USD round-turn total | `commission_round_turn_usd_per_lot: 5.0` in `config/config.example.json`, folded directly into every strategy's 25 USD risk-per-idea sizing budget (Python `symbol_spec.lots_for_risk`, MQL4 `SymbolSpec.mqh`'s `LotsForRisk`) |
| Further historical data | **None will be supplied. This is permanent.** | -- |
| Instrument specs (both EURUSD, GBPUSD) | Digits=5, floating spread, stops level=0, contract size=100000, min/max lot 0.01/50.00, lot step 0.01, swap long/short EURUSD -11.06/+0.59 GBPUSD -6.78/-3.76, triple-swap Wednesday | From instrument-specification screenshots, matches `config/config.example.json` exactly |

Still **unconfirmed** (never silently assumed, always labeled): actual
leverage/margin call behavior (no variant in this project models margin
at all), historical spread/slippage distribution (CSVs are Bid-only M1
OHLC, no tick Bid/Ask -- every spread/slippage number in this project is a
labeled hypothetical stress assumption, see section 5), freeze level,
historical swap-rate changes, the real MT4 swap-rollover hour (this
project applies swap once per Prague-FTMO-day boundary as an
approximation -- flagged as a specific open item for the one candidate,
S6, where it is a material fraction of the result), and whether MT4's
built-in indicator numerics match this project's hand-rolled Python
warmup exactly (a parity test needs real MT4).

## 3. Data

`data/raw/EURUSD1.csv` and `data/raw/GBPUSD1.csv`: M1 OHLC, no header,
`YYYY.MM.DD,HH:MM,Open,High,Low,Close,Volume`. Independently re-audited
(`python/ftmo_sim/data_audit.py`):

| Check | EURUSD1.csv | GBPUSD1.csv |
|---|---|---|
| SHA-256 | `5f97acdd75114b27db880ecc74fdc1f73087dc8c56b91b168ded3ff310494ad2` | `367290d4be0bb6ee0c8f0333dd95fac349e27e41a65194b5dd97290e6453d393` |
| Row count | 65126 | 65352 |
| First / last timestamp (file-local) | 2026-07-16 00:36 / 2026-09-17 23:05 | 2026-07-15 21:57 / 2026-09-17 23:06 |
| Distinct calendar days | 46 | 47 |
| Duplicate / invalid / non-monotonic rows | 0 / 0 / 0 | 0 / 0 / 0 |
| Gaps >1 min (weekend / suspected intraday) | 364 (9 / 355) | 271 (9 / 262) |

**~2 months, exactly one full calendar month (August 2026). This is the
single hardest constraint on everything in this report:** it is not
enough data to distinguish a real trading edge from noise for any
technical strategy, and it will never be extended. Every one of the eight
strategy variants in section 5 was tested on this SAME window -- none of
them is out-of-sample relative to any other.

## 4. Risk engine (tested, fixed twice now -- out of scope for strategy work)

All amounts USD, `B0` = balance at 00:00 Europe/Prague ("FTMO day"):

- Robot daily working floor: `B0 - 300`. Robot static total working floor:
  `9200` (tighter than FTMO's own raw 500/9000 limits). **Both checked
  directly and independently** against equity every tick, not only via
  `max()` of the two.
- Pre-trade check before any new entry: projected worst-case equity
  (current equity minus every other open position's *remaining* risk to
  its own SL, minus the new order's full risk, minus an execution buffer)
  must stay strictly above the applicable floor.
- Account-wide: scans **every** open position AND (as of this round)
  **every pending order** on the account, not just this EA's own -- an
  unknown/unbounded-risk foreign position or pending order (no SL) blocks
  new entries outright.
- Position sizing: 25 USD risk per idea, floored to the lot step, sized
  from the actual transacted price (spread AND, in the stress scenarios,
  slippage included), with the confirmed 5 USD/lot commission folded
  directly into the same 25 USD budget. 100 USD max concurrent portfolio
  risk, 50 USD cap for correlated (same-USD-direction) EURUSD+GBPUSD
  ideas.
- No martingale, no grid, no adding to losers, no increasing risk to chase
  a target or recover a loss -- checked explicitly for S5's "reverse"
  variant (section 5) and confirmed true by test.
- **Two bugs found and fixed since the first audit round** (see
  `docs/AUDIT_2026-09-18.md`'s follow-up section for full reproduction
  detail): (a) a same-tick cross-symbol causality leak, where one
  symbol's own entry-bar CLOSE could leak into a SIMULTANEOUS other-symbol
  entry decision that should only see information available at the bar's
  open; (b) an end-of-run equity/balance mismatch, where a trade opened
  and closed within the run's very last timestamp updated the realized
  balance but not the already-recorded last equity-curve point.
- 98 pytest tests cover this (`python/tests/`), including the originally
  mandated risk/execution scenarios plus new regressions for both bugs
  above, the commission-in-budget fix, adverse slippage's direction
  convention, and every new strategy engine's edge cases.

## 5. Eight strategy variants x three cost scenarios (the main new work)

All eight variants ran through the identical account-wide risk engine (one
shared risk state per variant per scenario -- never summed from two
independent single-pair backtests), the confirmed 5 USD/lot commission,
and the same ~2-month sample. **No grid search anywhere in this
section** -- every parameter was fixed in
`docs/EXPERIMENT_PLAN_2026-09-18.md` (written and SHA256'd BEFORE any of
this code was run) and taken directly from the task instructions or the
already-adopted S1/S2/S3 defaults.

### Cost scenarios (applied to every variant identically)

| | EURUSD spread | GBPUSD spread | Adverse slippage |
|---|---|---|---|
| C1 (base) | 1.0 pip | 1.5 pip | 0.0 |
| C2 (stress) | 2.0 pip | 3.0 pip | 0.5 pip |
| C3 (stronger stress) | 3.0 pip | 4.5 pip | 1.0 pip |

Slippage applies only to market entry fills and SL-triggered exits (never
TP or a time/discretionary exit) -- a stated stress assumption, not a
claim about real fill behavior. Lots are resized fresh per scenario from
the same fixed 25 USD budget each time (a wider C2/C3 spread+slippage
mechanically shrinks the sized lot count).

### The eight variants

- **S1 -- London Range Breakout + Retest v1.** The original spec-mandated
  fixed baseline: London-session range/retest/H1-EMA200 filter, one trade
  per instrument per day, forced flat at 16:00 London.
- **S2 -- EMA(20/50) H1 crossover.** Standard trend-follower, 1.5xATR SL,
  3R TP, holds overnight (swing-style). This is the strategy the account
  owner chose after the first round (smallest loss of the original
  three) and the comparison baseline for S4-S6.
- **S3 -- Bollinger(20,2) H1 mean-reversion.** Fades a close outside the
  band toward the middle band.
- **S4 -- S2 + full exit on the opposite EMA cross only.** Instead of
  ignoring a new opposite-direction signal while a position is open (S2's
  behavior), S4 closes the existing position and consumes that signal --
  no new position opens from the same event.
- **S5 -- S4's exit + one independent reverse idea.** Same close as S4,
  then a fresh, independently-sized (never doubled, no recovery logic)
  entry attempt in the new direction, re-checking every floor/cap/cost
  from scratch.
- **S6 -- Donchian H1 20/10 with an ATR stop.** Entry on a 20-bar
  breakout (prior CLOSED bars only), SL = 2xATR14(H1) anchored to the
  ACTUAL fill price (not the signal candle's close), no fixed TP, exit on
  a 10-bar-extreme reversal.
- **S7 -- M30 false-breakout-and-return.** A 20-closed-candle range;
  enters when price breaks a boundary intrabar but closes back inside it;
  fixed TP at the range midpoint; 8-M30-candle timeout if neither SL nor
  TP is hit.
- **S8 -- RSI(2) M30 pullback with an H1 EMA200 trend filter.** Enters on
  a fresh RSI2 threshold crossing filtered by the H1 trend; SL =
  1.5xATR14(M30) anchored to the actual fill; exits on an SMA5 reversion,
  a 10-candle timeout, or an H1 EMA200 breach, whichever is earliest.

Full rule text, exact parameters, and the implementation notes for each
(including two subtle bugs found and fixed WHILE building S8 -- an
H1/M30 event-merge ordering bug and a timeout off-by-one -- both with
regression tests that fail against the buggy code) are in
`docs/EXPERIMENT_PLAN_2026-09-18.md` and the corresponding
`python/ftmo_sim/strategy_*.py` files.

### Headline results -- all 24 runs

Net is realized-balance change from the 10,000 USD start; each
(variant, scenario) pair ran its own fully independent account.

| Variant | C1 net USD (%) | C2 net USD (%) | C3 net USD (%) | Trades (C1) | Profit factor (C1) | Expectancy R (C1) |
|---|---|---|---|---|---|---|
| S1 London breakout | -319.38 (-3.19%) | -382.57 (-3.83%) | -431.93 (-4.32%) | 20 | 0.23 | -0.641 |
| S2 EMA(20/50) cross | -281.89 (-2.82%) | -304.16 (-3.04%) | -330.47 (-3.30%) | 25 | 0.49 | -0.424 |
| S3 Bollinger(20,2) | -781.70 (-7.82%) | -775.74 (-7.76%) | -794.56 (-7.95%) | 102 | 0.63 | -0.289 |
| S4 EMA exit-on-opposite | -299.75 (-3.00%) | -324.84 (-3.25%) | -349.19 (-3.49%) | 26 | 0.42 | -0.433 |
| S5 S4 + reverse | -145.79 (-1.46%) | -176.99 (-1.77%) | -234.03 (-2.34%) | 27 | 0.72 | -0.188 |
| S6 Donchian 20/10+ATR | -142.56 (-1.43%) | -216.12 (-2.16%) | -385.93 (-3.86%) | 52 | 0.86 | -0.080 |
| S7 False-breakout M30 | -780.27 (-7.80%) | -776.91 (-7.77%) | -792.53 (-7.93%) | 62 | 0.32 | -0.508 |
| S8 RSI2 pullback M30 | -269.07 (-2.69%) | -377.43 (-3.77%) | -542.51 (-5.43%) | 78 | 0.64 | -0.140 |

**Every single one of the 24 runs is net negative. Working-floor breach
count is 0 for all 24 (nobody got stopped out -- every loss above is the
account simply losing money gradually).** The smallest losers are S5 and
S6 (both around -1.4% in C1), but neither is close to breakeven, and
neither stays the smallest loser under the stronger stress scenario --
S6's C1 advantage erodes fastest of the eight (C1 -142.56 -> C3 -385.93)
because it holds the longest on average (27.9h) with no fixed TP, while
S5 degrades more gently (C1 -145.79 -> C3 -234.03).

### S4/S5 vs S2 (the direct comparison specifically requested)

S4 alone is slightly WORSE than S2 on every metric (profit factor 0.42 vs
0.49, expectancy -0.433R vs -0.424R, drawdown 357 vs 352 USD) -- forcing
an exit on every opposite signal, instead of letting an existing position
ride to its own SL/TP, is a net-negative whipsaw cost on this sample by
itself. S5 (the same exit, PLUS one independent reverse idea) is the best
of the three by every metric, including a much shorter max losing streak
(5 vs 12 trades) and roughly half S2's drawdown -- not because S4's exit
was secretly good, but because catching the new direction's actual move
outweighed both the added whipsaw cost and exiting the first position
slightly early. Still a loss in every scenario.

### Cost breakdown (C1) -- commission / spread / slippage / swap, USD

| Variant | Commission | Spread | Swap |
|---|---|---|---|
| S1 | 86.80 | 230.15 | 0.00 |
| S2 | 20.75 | 48.35 | -22.66 |
| S3 | 139.15 | 335.15 | -62.85 |
| S4 | 21.50 | 50.60 | -23.95 |
| S5 | 22.90 | 52.55 | -21.37 |
| S6 | 30.80 | 73.40 | -44.69 |
| S7 | 140.95 | 348.50 | -5.98 |
| S8 | 90.85 | 220.15 | -1.15 |

(Slippage is 0.00 in C1 by construction; it is nonzero and material in
C2/C3 -- see the full `summary.json` per run.) Swap is 31% of S6's net C1
loss -- the one candidate where the swap-rollover-hour approximation
actually matters, and where the promised alternative-rollover-time
sensitivity test was **not run this round** (an explicit, tracked open
item, not a silent skip).

### One notable failure-mode finding: S7 is really a one-month result

62 of S7's 62 C1 trades closed within the FIRST month (July) of the
sample. After that, 421 signals were rejected for
`PRE_TRADE_PROJECTED_EQUITY_BREACH` across the rest of the sample -- the
pre-trade worst-case-equity gate (deliberately more conservative than the
actual floor) kept blocking new entries because the account never fully
recovered, even though the actual floor was never breached. S7's headline
loss is therefore weaker evidence than it looks: effectively a
single-month test, not a genuine two-month one.

### Monthly table (C1; Europe/Prague calendar months; only 2026-08 is full)

| Variant | 2026-07 (partial) | 2026-08 (FULL) | 2026-09 (partial) |
|---|---|---|---|
| S1 | -43.00 | -199.25 | -77.13 |
| S2 | +30.82 | -168.59 | -121.47 |
| S3 | -283.43 | -435.42 | N/A (0 trades) |
| S4 | +30.82 | -185.15 | -121.47 |
| S5 | +30.82 | **-33.78** | -121.47 |
| S6 | -106.50 | -48.77 | +57.41 |
| S7 | -774.28 | N/A (0 trades) | N/A (0 trades) |
| S8 | -112.43 | -95.51 | -59.98 |

No variant's full calendar month reaches anywhere near the FTMO-Swing-
account-owner's informally stated +2000 USD / +20% target -- the best
full-month result across all eight (S5, 2026-08) is still a loss. At the
fixed 25 USD risk-per-idea, that target implies roughly +80R net per
month; nothing here comes remotely close, and this project does not
propose raising the per-idea risk to manufacture that target artificially.

### Verdict

Per the priority order this project has always used (execution
correctness first, then cost robustness, then net expectancy, then loss
character, and ONLY THEN profit magnitude): **in this experiment, no
candidate was found** (the account owner's own required wording: "šajā
eksperimentā kandidāts nav atrasts"). This holds for all eight variants
under all three cost scenarios -- none is even positive in the friendliest
scenario (C1) alone, so the stricter "positive in C1 AND C2" bar is moot.
Full detail, including what this experiment does NOT establish (it does
not prove any of the eight is incapable of ever working -- only that none
worked on this specific sample, under these specific fixed parameters),
is in `docs/STRATEGY_RESEARCH_2026-09-18.md`.

## 6. The multiple-comparisons / overfitting problem (now worse, not better)

The first round of this project ran a **demonstration** sweep (81
parameter combinations of the EMA-crossover family) specifically to show
how easy it is to find an accidentally-positive result: **26% (21/81)
came out net positive** with no formal null model behind that figure --
a caution, not proof the positive ones are noise (see
`docs/AUDIT_2026-09-18.md`'s first-round P1-8 for the exact wording this
project settled on, after an earlier draft overstated it).

This round's 8-variant x 3-scenario experiment was explicitly designed
NOT to repeat that mistake -- every parameter was pre-registered before
any code was run, with no grid search. But **trying eight different
strategy FAMILIES is itself a multiple-comparisons exposure**, even
without tuning parameters within any one of them: if you try enough
different ideas, one of them looking "least bad" (S5/S6 here) is exactly
what you'd expect whether or not any of them has a real edge. This report
does not claim S5 or S6 is closer to a real edge than S1/S3/S7 for that
reason -- both are still losses, and no significance test has been run to
distinguish "S5 lost less because of a real property of the strategy"
from "S5 lost less by chance, on this one sample." **No permutation/
null-model test exists yet for either the original 81-combination sweep
or this round's 8-variant comparison.** This is the single most valuable
thing for a continuation to build, if the goal is to make the "least bad
of eight" conclusion actually mean something.

## 7. MQL4 status (all NOT_RUN, structurally more complete this round)

Two audit rounds have now found and structurally fixed real bugs here --
see `docs/AUDIT_2026-09-18.md` for both rounds' full detail. **None of it
has been compiled, loaded into a terminal, or run against a real or demo
account, in either round.** A concrete, short MetaEditor/terminal test
sequence is in `README.md`'s "MQL4 test instructions" section for whoever
gets real MT4 access.

- `mql4/Include/FTMO/`: `Config.mqh`, `TimeUtils.mqh`, `SymbolSpec.mqh`,
  `AccountRisk.mqh`, `OrderExec.mqh`, `Persistence.mqh`, `Logging.mqh`
  (shared), plus `Signals_EmaCross.mqh` (chosen strategy) and
  `Signals_LondonBreakoutRetest.mqh` (reference strategy). Only S1/S2 are
  ported to MQL4 so far -- S3-S8 exist only in Python, deliberately, per
  the task's own instruction to keep new-strategy work to an offline
  comparison first (section 5) rather than widen the unverified MQL4
  surface before S2 itself is even confirmed to compile.
- `mql4/Experts/FTMO_Swing_EA_EmaCross.mq4` -- the chosen strategy's EA.
- `mql4/Experts/FTMO_Swing_EA.mq4` -- the London breakout EA, reference only.
- This round added: portfolio/correlated-group risk caps (previously a
  documented no-op gap in both EA files), pending-order risk in the
  account-wide scan (previously skipped with an excuse this round
  explicitly rejects), a persisted "unprotected position" emergency state
  that keeps retrying protection/closure every tick including across a
  restart (previously just logged a warning), commission folded into
  MQL4's own lot sizing (matching the Python fix), and a real (though
  still terminal-scoped, not cross-terminal) exclusive instance lock.
- **Only one EA may be attached to a given account at a time** -- both
  share one account-scoped risk-state file by design.
- No parity test against the Python engine has been run (needs MT4).

## 8. What is actually being asked of you (the receiving model/researcher)

Section 5 above answers the ORIGINAL ask from the first round of this
project ("search for a strategy that is positive; if you can't, hand the
task to another model") about as thoroughly as this fixed dataset
permits: eight strategy families, three cost-stress scenarios, no grid
search, and the honest answer is that none of them works on this sample.
**Trying a ninth or tenth strategy variant on this SAME data is very
unlikely to produce a more meaningful answer** -- section 6 explains why.
The actual open problems now are:

1. **Build the missing significance test.** Take either the original
   81-combination sweep or this round's 8-variant comparison (or both)
   and run a block-resampling permutation/Monte Carlo test (respecting
   day/instrument dependence, not naive shuffling) asking whether the
   actual results are distinguishable from a random entry rule under the
   same risk management, on this same data. This needs no new data and
   directly closes section 6's gap.
2. **Run the swap-rollover sensitivity test that was pre-registered but
   not executed** for S6 (the one candidate where swap is a material,
   ~31%, fraction of its result) -- re-test it against an alternative
   assumed broker rollover hour instead of the Prague-FTMO-day boundary
   this project has always used, and report whether S6's ranking among
   the eight changes.
3. **Get real MT4/MetaEditor access** and work through `README.md`'s test
   sequence -- confirming the MQL4 side even compiles, and that its
   dry-run signal/lot-sizing output matches the Python engine bar-for-bar,
   is the largest remaining gap between "this project's logic is tested"
   and "this project's actual MT4 artifact is tested."
4. **A forward/demo-test plan.** Since no more historical data is coming,
   propose what a demo-account forward test should log and for how long
   to generate genuinely new evidence -- the only way any of S1-S8 could
   ever be re-evaluated out-of-sample.
5. **A strategy with a rationale statable without reference to this
   specific dataset**, if a ninth idea is tried at all -- backtested only
   to check it isn't immediately contradicted, not searched for the
   best-fitting variant. If tried, pre-register it in a new plan document
   the same way `docs/EXPERIMENT_PLAN_2026-09-18.md` did, before writing
   any code.

### Explicit do-nots

- Do not tune parameters (within any of S1-S8, or the cost scenarios)
  against this fixed sample and present the best result as "the" answer.
- Do not raise the 25 USD risk-per-idea to make the +2000 USD/month target
  look achievable -- that changes the risk profile, not the edge, and
  this project explicitly rejects doing that.
- Do not fabricate additional historical data or treat synthetic price
  paths as real.
- Do not weaken or bypass the account-wide risk engine (section 4) to
  make a strategy look better -- it is fixed, tested, and out of scope
  for strategy work.
- Do not claim the MQL4 side compiles or was tested in MT4 unless you
  actually have MetaEditor/MT4 access and did so.
- Do not present a partial calendar month's result (even a good-looking
  one, like S6's +57.41 in the 2026-09 partial) as if it were a full
  month, or extrapolate/annualize it.

### Deliverable expected back

Any of: (a) the permutation-test analysis from item 1, with a clear
conclusion about whether S1-S8's ranking is statistically meaningful; (b)
the swap-rollover sensitivity result from item 2; (c) a real MT4 test
report from item 3, with honest EXECUTED/STILL_NOT_RUN labeling per item
(never claim more than was actually verified); (d) a forward-test plan
from item 4; or (e) a ninth strategy, implemented the same way as the
existing ones (`python/ftmo_sim/strategy_*.py` are the templates, plugging
into `simulator_ema_cross.run_h1_signal_simulation` or
`simulator_m30_signal.run_m30_signal_simulation`'s `engine_factory`),
pre-registered before being coded, with a rationale independent of this
dataset and fully-reported (never cherry-picked) backtest numbers across
all three cost scenarios.
