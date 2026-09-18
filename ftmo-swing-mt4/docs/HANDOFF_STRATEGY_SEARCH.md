# Handoff: find a strategy with genuine (not overfit) positive expectancy

> **Use `docs/FULL_REPORT.md` instead -- it supersedes this file.** This
> file's numbers and its "38% = exactly what chance would produce" framing
> both predate an independent code audit (2026-09-18, see
> `docs/AUDIT_2026-09-18.md`): two P0 simulator bugs changed the underlying
> results, and the audit correctly pushed back on that framing as
> overstated (there was no null model behind it). FULL_REPORT.md has the
> corrected numbers and the corrected framing. This file is kept only as a
> record of the earlier, narrower version -- do not treat anything below
> as current.

Self-contained brief for a different model/agent to continue this search.
Read this whole file before doing anything -- it exists specifically
because a naive continuation (try more parameters, keep tuning until
something is positive) has already been shown, on this exact project, to
produce meaningless "positive" results. Do not repeat that mistake.

## Repository

`https://github.com/vsilovs-creator/roboti`, path `ftmo-swing-mt4/`. Clone
it; `README.md` there has full project context, `docs/UNKNOWNS.md` and
`docs/RISK_SPEC.md` have the confirmed facts and risk-model detail. The
Python code (`python/ftmo_sim/`) is the tested, working part; the MQL4 code
(`mql4/`) has never been compiled (no MT4/MetaEditor available).

## What this project actually is

An FTMO 2-Step Swing (USD, 10 000 USD) MT4 robot prototype trading
EURUSD+GBPUSD, under a hard account-wide risk engine (daily working floor
`B0-300`, static total working floor `9200`, both independently checked;
25 USD risk per idea, 100 USD portfolio cap, 50 USD correlated-group cap --
see `docs/RISK_SPEC.md`). That risk engine is fixed and tested (54 passing
pytest tests) and should not be changed by strategy work; only the signal
layer (`python/ftmo_sim/strategy_*.py`, `signals.py`) is in scope for a new
strategy attempt.

## The data (this is the hard constraint)

- `data/raw/EURUSD1.csv`, `data/raw/GBPUSD1.csv`: M1 OHLC, no header,
  `YYYY.MM.DD,HH:MM,O,H,L,C,V`. SHA-256-verified, audited in
  `docs/DATA_AUDIT.md`.
- Window: 2026-07-15/16 through 2026-09-17. **~2 months, exactly one full
  calendar month (August 2026).**
- **The account owner has confirmed (2026-09-18) that no further historical
  data will be supplied.** This is permanent. Any approach that requires
  more data than this to be trustworthy cannot be validated in this
  project, full stop -- say so rather than pretending otherwise.
- Confirmed costs: 5.00 USD commission per round-turn lot (2.50 USD/lot/
  side), server clock GMT+2 winter / GMT+3 summer on EU DST dates. Both
  already wired into `config/config.example.json` and the simulator.

## What has already been tried (do not just repeat this)

Three independent, well-known strategies at standard textbook parameters,
run through the same account-wide risk engine and confirmed costs
(`python/scripts/run_strategy_comparison.py`,
`reports/run_003_strategy_comparison/COMPARISON.md`):

| Strategy | Trades | Net USD | Profit factor |
|---|---|---|---|
| London Range Breakout + Retest (spec-mandated baseline) | 20 | -485.99 | 0.18 |
| EMA(20/50) H1 crossover | 28 | -257.98 | 0.55 |
| Bollinger(20,2) H1 mean-reversion | 118 | -780.79 | 0.66 |

All three lost money. EMA crossover (smallest loss) was adopted as the
"least-bad of three" per the account owner's instruction, not because it
showed a real edge (`python/scripts/run_ema_cross.py`,
`reports/run_004_ema_cross_chosen/`).

**Then a parameter sweep was run** to check whether tuning could find
something better (`python/scripts/sweep_overfitting_demo.py`): 81
combinations of EMA(fast/slow) x ATR-SL-multiple x TP-R-multiple. **31 of 81
(38%) came out net positive**, up to +397 USD (+3.97%) for one specific
combination (fast=30, slow=100, atr_sl=2.0, tp_r=3.0).

**This is the key finding, and it points away from more tuning, not toward
it:** on a fixed ~40-trading-day sample, over a third of arbitrary parameter
choices for one strategy came out "positive" by chance alone. A hit rate
that high from essentially random search is strong evidence that "positive
on this backtest" carries almost no information about future performance
here -- it is a classic multiple-comparisons / data-dredging result, not a
discovered edge. Picking the top of that grid (or of any wider grid, or
across more strategy families) and calling it "the strategy" would be
reporting noise as a finding. **Do not do this.** The full grid is in
`reports/run_005_overfitting_sweep_demo/sweep_results.csv` if you want to
verify this claim yourself before continuing.

## The actual problem to solve

Find (or make the case that there is no honest way to find, within this
project's constraints) a trading approach for this account/instrument pair
whose positive backtest result on the available ~2 months would still be
credible evidence of a real edge, not an artifact of trying enough things.
Approaches worth considering, roughly in order of how likely they are to
produce something trustworthy rather than a bigger version of the same
overfitting trap:

1. **Say plainly if 2 months of data is just not enough**, for any
   strategy, to distinguish real edge from noise -- this may be the
   correct, honest answer, and spec section 10 (in the original task,
   summarized in `docs/UNKNOWNS.md`) already anticipated this ("5+ years of
   tick Bid/Ask coverage" is named as what would actually be needed).
2. **A statistically disciplined test on the existing sample**, e.g. a
   permutation/Monte Carlo test on trade sequences (respecting day/
   instrument dependence -- block resampling, not naive shuffling, per
   spec section 10) to ask "is any candidate strategy's result
   distinguishable from what a random entry rule with the same risk
   management would produce on this same data?" This does not need new
   data and directly answers the overfitting concern instead of
   sidestepping it.
3. **A strategy with an economic/structural rationale independent of this
   specific 2-month window** (e.g. a documented market-microstructure or
   liquidity effect, a cross-asset or intermarket signal, a volatility
   regime filter) rather than another generic technical-indicator search --
   the rationale should be statable without reference to this dataset at
   all, with the backtest only checking it isn't immediately contradicted.
4. **Demo/forward paper-testing** as the actual source of new "data" the
   account owner said would not be supplied historically -- proposing a
   forward-test plan (what to log, how long, what would count as
   confirming or rejecting the strategy) may be more useful deliverable
   than another backtest number.
5. If you do try additional strategies or parameters, **pre-register how
   many you'll try and report all of them**, not just the best one -- the
   sweep above is the template for how to present this honestly (38%
   positive rate reported, not just the +397 USD headline).

## What NOT to do

- Do not tune parameters (of any strategy) against this fixed sample and
  present the best result as "the" answer -- the sweep above already shows
  what that produces and why it's meaningless here.
- Do not fabricate additional historical data, synthetic price paths used
  as if real, or claim access to data this project does not have.
- Do not weaken or bypass the account-wide risk engine to make a strategy
  look better (it is spec-mandated and tested; changing it is out of scope
  for a strategy search).
- Do not claim MQL4 compiles or was tested in MT4 unless you actually have
  MetaEditor/MT4 access and did so.

## Deliverable expected back

Either: (a) a specific new strategy or filter, implemented the same way as
`strategy_ema_cross.py`/`strategy_bb_reversion.py` (a small engine class
plugging into `simulator_ema_cross.run_h1_signal_simulation`'s
`engine_factory`), with a stated rationale independent of this dataset and
honest backtest numbers -- not cherry-picked from a sweep; or (b) a
rigorous statistical analysis (e.g. the permutation test above) of the
strategies already tried, concluding whether any of their results are
distinguishable from noise on this sample; or (c) a clear, well-argued case
for what would actually be needed (data, time, a different problem framing)
that this project's current constraints cannot supply -- which is also a
legitimate and useful answer.
