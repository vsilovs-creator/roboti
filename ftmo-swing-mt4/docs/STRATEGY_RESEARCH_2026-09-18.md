# Strategy research -- S1-S8 x C1-C3 comparison (2026-09-18)

**Status: EXPLORATORY.** Every number below comes from the SAME ~2-month
M1 sample every prior round in this project has used (no further
historical data exists or will be supplied). Testing eight variants on one
short, already-partially-seen sample cannot produce a "validated"
strategy -- see the verdict section for exactly what this experiment does
and does not establish, and `docs/EXPERIMENT_PLAN_2026-09-18.md` for the
pre-registered parameters (fixed before any of this code was written, no
grid search anywhere).

## Reproducibility

- Plan: `docs/EXPERIMENT_PLAN_2026-09-18.md` (SHA256 of its own content
  recorded inside the file).
- Code: git commit `2f81dca` (the commit that added
  `scripts/run_experiment_2026-09-18.py`) on `github.com/vsilovs-creator/roboti`, branch `main`.
- Config: `config/config.example.json`, SHA256 recorded in every run's
  `summary.json` (`run_metadata.config_sha256`).
- One command reproduces all 24 runs:
  ```
  python3 scripts/run_experiment_2026-09-18.py \
      --config ../config/config.example.json \
      --eurusd ../data/raw/EURUSD1.csv --gbpusd ../data/raw/GBPUSD1.csv \
      --out-dir ../reports/experiment_2026-09-18
  ```
- Per-run artifacts (`reports/experiment_2026-09-18/<variant>_<scenario>/`):
  `trades.csv`, `equity.csv` (hourly-downsampled; every metric below is
  computed from the full M1-resolution curve in memory, not this file),
  `signals.csv` (every rejected signal with its reason, every accepted
  signal at its fill instant), `summary.json` (the full machine-readable
  metrics). `experiment_summary.json` collects all 24 summaries.

## Sources (inspiration only -- never treated as validation)

- MQL5 "Trading with Donchian Channels" (S6). Never copied as MQL4; this
  project's engine is an independent Python implementation of the
  20/10/2xATR rule stated in the task, not a port of that article's code.
- WH SelfInvest "Turtle Soup" forex adaptation (S7's false-breakout idea).
  This project's version (M30, 20-closed-candle range, 0.1xATR buffer,
  fixed TP at the range midpoint, 8-candle timeout) differs from theirs;
  their published win-rate/backtest is explicitly NOT treated as
  independent validation of this version.
- MQL5 "Day Trading Larry Connors RSI2 Mean-Reversion" (S8). That article
  was tested on the US500 CFD, not forex -- the M30/H1-EMA200-filter
  adaptation here to EURUSD/GBPUSD is unverified.
- Moskowitz/Ooi/Pedersen, "Time Series Momentum" (S6's inspiration for a
  trend/breakout approach). Futures, multi-month-horizon evidence; applying
  it to H1 forex is a hypothesis, not a transferred result.
- FTMO Trading Objectives / Swing FAQ. The exact 2-Step Swing rules already
  confirmed in earlier rounds (daily floor `balance_at_midnight-500`,
  static total floor `9000`, robot's own tighter working floors
  `balance_at_midnight-300` / `9200`) are unchanged and reused as-is; Swing
  accounts may hold overnight/weekend/through news, which is exactly what
  S2/S4/S5/S6 do by design (`enforce_session_close=false`).

## Assumptions carried into this round (see `docs/UNKNOWNS.md` for the full list)

- Server clock GMT+2/GMT+3 (EU DST) -- confirmed by the account owner,
  unchanged.
- Commission 5.00 USD/lot round-turn -- confirmed, unchanged, folded into
  every variant's 25 USD sizing budget (`extra_cost_usd_per_lot`).
- Spread is a fixed hypothetical per scenario (C1/C2/C3 below), NOT a real
  historical spread feed -- no such feed was ever supplied. Ask is
  reconstructed from Bid OHLC via this fixed spread; long exits are
  checked against Bid, short exits against Ask (`order_exec.py`).
- Slippage (C2/C3) is a stress assumption applied only to market entry
  fills and SL-triggered exits (never to TP or a time/discretionary exit),
  per `docs/EXPERIMENT_PLAN_2026-09-18.md` section 3 -- not a claim about
  real fill behaviour.
- Swap uses the confirmed current swap-points rates applied retroactively
  across the whole sample -- an approximation; see the swap section below
  for exactly how much this affects each candidate, and the one
  sensitivity test this round did **not** get to (documented as an open
  item, not silently skipped).
- Leverage/margin: not modeled by any variant in this project; still needs
  checking against real account data before any MT4 use.
- M1 OHLC has no true tick path: exact tick-level certification of
  intrabar risk-floor crossings or same-bar SL/TP order is impossible and
  is not claimed anywhere in this document.

## Cost scenarios

| | EURUSD spread | GBPUSD spread | Adverse slippage (entry + SL-exit only) |
|---|---|---|---|
| C1 (base) | 1.0 pip | 1.5 pip | 0.0 |
| C2 (stress) | 2.0 pip | 3.0 pip | 0.5 pip |
| C3 (stronger stress) | 3.0 pip | 4.5 pip | 1.0 pip |

Commission 5.00 USD/lot round-turn in all three. Lots are resized fresh
per scenario from the same fixed 25 USD planned risk each time (a wider
C2/C3 spread+slippage widens the realized SL distance, which mechanically
shrinks the sized lot count -- shown explicitly in the per-scenario
`trades.csv` lot sizes, not just asserted).

## Full results -- all 24 runs

Net figures are realized-balance change from the 10,000 USD starting
balance; every run ended each scenario with an independent account (never
summed). "DD" = max equity drawdown from peak. "R" = expectancy in R
(R = 25 USD). Full per-run detail (win rate, avg win/loss, cost breakdown,
monthly table, rejected-signal counts) is in each run's `summary.json`.

| Variant | C1 net USD (%) | C2 net USD (%) | C3 net USD (%) | Trades (C1) | PF (C1) | Expectancy R (C1) | Max DD (C1) | Worst FTMO-day (C1) |
|---|---|---|---|---|---|---|---|---|
| S1 London breakout | -319.38 (-3.19%) | -382.57 (-3.83%) | -431.93 (-4.32%) | 20 | 0.23 | -0.641 | 319.38 | 2026-08-05 (-49.70) |
| S2 EMA(20/50) cross | -281.89 (-2.82%) | -304.16 (-3.04%) | -330.47 (-3.30%) | 25 | 0.49 | -0.424 | 352.13 | 2026-09-10 (-93.24) |
| S3 Bollinger(20,2) | -781.70 (-7.82%) | -775.74 (-7.76%) | -794.56 (-7.95%) | 102 | 0.63 | -0.289 | 842.53 | 2026-08-19 (-285.22) |
| S4 EMA exit-on-opposite | -299.75 (-3.00%) | -324.84 (-3.25%) | -349.19 (-3.49%) | 26 | 0.42 | -0.433 | 357.07 | 2026-09-10 (-93.24) |
| S5 S4 + reverse | -145.79 (-1.46%) | -176.99 (-1.77%) | -234.03 (-2.34%) | 27 | 0.72 | -0.188 | 203.12 | 2026-09-10 (-93.24) |
| S6 Donchian 20/10+ATR | -142.56 (-1.43%) | -216.12 (-2.16%) | -385.93 (-3.86%) | 52 | 0.86 | -0.080 | 389.67 | 2026-09-08 (-78.21) |
| S7 False-breakout M30 | -780.27 (-7.80%) | -776.91 (-7.77%) | -792.53 (-7.93%) | 62 | 0.32 | -0.508 | 784.17 | 2026-07-21 (-265.68) |
| S8 RSI2 pullback M30 | -269.07 (-2.69%) | -377.43 (-3.77%) | -542.51 (-5.43%) | 78 | 0.64 | -0.140 | 326.43 | 2026-07-29 (-82.85) |

**No variant is positive in ANY scenario, let alone in both C1 AND C2.**
S6 (C1 only) and S5 are the two smallest losers; S6's advantage erodes
fastest under stress (C1 -142.56 -> C3 -385.93, the largest relative
degradation of the eight), while S5 degrades more gently (C1 -145.79 ->
C3 -234.03). Neither is close to breakeven in any scenario.

Working-floor breach count: **0 in all 24 runs** -- no variant/scenario
combination ever actually breached the daily or static-total floor on
this sample; every result above is the account simply losing money
gradually, never getting stopped out by the risk controller.

## Cost breakdown (C1)

| Variant | Commission | Spread | Slippage | Swap |
|---|---|---|---|---|
| S1 | 86.80 | 230.15 | 0.00 | 0.00 |
| S2 | 20.75 | 48.35 | 0.00 | -22.66 |
| S3 | 139.15 | 335.15 | 0.00 | -62.85 |
| S4 | 21.50 | 50.60 | 0.00 | -23.95 |
| S5 | 22.90 | 52.55 | 0.00 | -21.37 |
| S6 | 30.80 | 73.40 | 0.00 | -44.69 |
| S7 | 140.95 | 348.50 | 0.00 | -5.98 |
| S8 | 90.85 | 220.15 | 0.00 | -1.15 |

**Swap materiality check** (swap USD as a fraction of that variant's C1
net loss): S1 0%, S2 8%, S3 8%, S4 8%, S5 15%, **S6 31%**, S7 1%, S8 0.4%.
S6 is the one candidate where swap is a material fraction of the result
(it holds the longest on average -- see holding time below -- and has no
fixed TP to cut a hold short). **This round did NOT run the promised
alternative-rollover-time sensitivity test for S6** (applying swap at a
different assumed broker rollover hour instead of the Prague-FTMO-day
boundary) -- flagged here as an explicit open item for the next session,
not silently skipped. Every other candidate's swap fraction is small
enough that this gap does not change any of this round's comparisons.

## Average holding time (C1)

S1: 0.5h -- S2: 28.7h -- S3: 10.1h -- S4: 28.3h -- S5: 27.0h -- S6: 27.9h
-- S7: 0.9h -- S8: 1.6h.

The three M30 timeout-bounded strategies (S1 is M5/intraday by design; S7
times out after 8 M30 candles = 4h max; S8 after 10 M30 candles = 5h max)
hold far shorter than the H1 swing-style strategies (S2/S4/S5/S6, which
hold overnight by design and average over a full day).

## S4/S5 vs S2 (the direct comparison the task requires)

| | S2 | S4 (exit-on-opposite) | S5 (S4 + reverse) |
|---|---|---|---|
| C1 net USD | -281.89 | -299.75 | **-145.79** |
| C2 net USD | -304.16 | -324.84 | **-176.99** |
| C3 net USD | -330.47 | -349.19 | **-234.03** |
| Trades (C1) | 25 | 26 | 27 |
| Profit factor (C1) | 0.49 | 0.42 | **0.72** |
| Expectancy R (C1) | -0.424 | -0.433 | **-0.188** |
| Max DD (C1) | 352.13 | 357.07 | **203.12** |
| Max losing streak (C1) | 12 | 12 | **5** |
| Commission+spread (C1) | 69.10 | 72.10 | 75.45 |

- **S4 alone is slightly WORSE than S2**, not better: forcing an exit on
  every opposite signal (instead of letting the existing position ride to
  its own SL/TP) cut one trade's winners short often enough to slightly
  worsen expectancy, DD, and net result, for a small extra cost (one more
  round-trip's commission/spread per opposite-signal event) -- this is the
  whipsaw-from-direction-change cost the task asked to isolate, and here
  it is net negative on its own.
- **S5 (S4's exit + one independent reverse) is the best of the three**,
  by every metric in this table, including a much shorter max losing
  streak (5 vs 12) and roughly half S2's drawdown. This is NOT S4 fixed by
  the reverse -- it is a structurally different bet: instead of "ride the
  old position AND immediately open the new one" (S4, which under-performs
  S2), S5 additionally captures the NEW direction's move that S2/S4 simply
  miss while sitting in (or having just exited) the old position. On this
  sample, catching that second move outweighed both the extra whipsaw cost
  and the cost of closing the first position slightly early.
- None of the three is anywhere close to positive. S5's improvement over
  S2 is real on this sample but is a difference between two negative
  numbers, not evidence of a profitable variant.

## S6/S7/S8 vs all three baselines (S1/S2/S3)

- **S6 (Donchian+ATR)** has the best profit factor (0.86) and expectancy R
  (-0.080) of all eight variants in C1, and the smallest C1 loss
  (-142.56) tied closely with S5. It degrades the fastest under stress
  (C3: -385.93, a >2.7x worse result than C1) because it holds the
  longest of any variant (avg 27.9h) and has no fixed TP to cap a trade's
  exposure to a widening spread on exit -- its ATR-anchored SL is
  unaffected by the scenario, but every SL-triggered exit under C2/C3 also
  eats the scenario's slippage, and it has by far the most SL-triggered
  exits of the eight (implicit in its low win rate despite the *reverse-of-
  the-usual* short-losing-streak profile -- see its own `summary.json` for
  the exact win/loss split). It also ended C1/C2/C3 with an open GBPUSD
  position each time (`open_positions_at_end` in its `summary.json`),
  meaning its `net_equity_change` (which includes that floating P/L) is a
  few dollars worse than the realized `net_balance_change` reported in
  the headline table above -- both numbers are in every run's
  `summary.json`, never conflated.
- **S7 (false-breakout M30)** is tied with S3 for the worst result of the
  eight (-780 to -795 across all three scenarios) and has a very
  distinctive failure mode worth flagging on its own: essentially ALL of
  its trades (62 of 62 in C1) closed in the FIRST month (July) of the
  sample, after which its `rejected_signal_counts_by_reason` shows 421
  signals rejected for `PRE_TRADE_PROJECTED_EQUITY_BREACH` across the rest
  of the sample -- the pre-trade worst-case-equity gate (which is
  deliberately more conservative than the actual floor) kept blocking new
  entries because the account never fully recovered from July's losses,
  even though the ACTUAL floor was never breached (0 breaches, same as
  every other variant). This means S7's headline loss is effectively a
  ONE-MONTH result, not evidence spread across the whole ~2-month sample --
  a materially different (and weaker) kind of evidence than S2/S4/S5/S6's
  losses, which are spread across all three months.
- **S8 (RSI2 pullback + H1 EMA200 filter)** has the highest win rate of any
  variant (46.2% in C1, vs. 16-31% for the others) but a profit factor
  still well under 1 (0.64) -- consistent with a mean-reversion strategy
  that wins often but by less than it loses on the trades that go wrong,
  exactly the risk profile Connors-style RSI2 strategies are known for.
  Its result degrades noticeably under stress (C1 -269 -> C3 -543,
  roughly doubling) because of its short average holding time (1.6h) and
  high trade count (78-79 across scenarios): more trades means more
  entry-slippage legs paid, and C3's slippage (1.0 pip) is a meaningfully
  larger fraction of its typical 1.5xATR(M30) stop than it is of the
  H1-scale strategies' wider stops.
- None of S6/S7/S8 beats S2 by enough (or at all, for S7/S8) to change the
  overall picture: every one of the eight loses money in every one of the
  three cost scenarios on this sample.

## Monthly table (C1, realized P/L; Europe/Prague calendar months)

Only 2026-08 is a full calendar month in this sample; 2026-07 and 2026-09
are partial and are never treated as full or annualized.

| Variant | 2026-07 (partial) | 2026-08 (FULL) | 2026-09 (partial) |
|---|---|---|---|
| S1 | -43.00 (1 trade) | -199.25 (13 trades) | -77.13 (6 trades) |
| S2 | +30.82 (6 trades) | -168.59 (14 trades) | -121.47 (5 trades) |
| S3 | -283.43 (37 trades) | -435.42 (65 trades) | N/A (0 trades) |
| S4 | +30.82 (6 trades) | -185.15 (15 trades) | -121.47 (5 trades) |
| S5 | +30.82 (6 trades) | -33.78 (16 trades) | -121.47 (5 trades) |
| S6 | -106.50 (16 trades) | -48.77 (21 trades) | +57.41 (15 trades) |
| S7 | -774.28 (62 trades) | N/A (0 trades) | N/A (0 trades) |
| S8 | -112.43 (13 trades) | -95.51 (38 trades) | -59.98 (27 trades) |

No variant's full calendar month (2026-08) reaches anywhere near the
+2000 USD / +20% target -- the best full-month result across all eight is
S5's -33.78 USD, still a loss. **Even where a partial month happens to
look better (S6's +57.41 in the 2026-09 partial, or S2/S4/S5's +30.82 in
the 2026-07 partial), that is a PARTIAL month and is never treated as a
"20% every month" result, per the task's explicit instruction** -- and in
any case none of these partial-month figures are anywhere near the target
either. At the fixed 25 USD risk-per-idea, the +2000 USD/month target
implies roughly +80R net per month; nothing in this experiment comes
remotely close, and this document does not propose raising the per-idea
risk to try to manufacture that target artificially.

## Verdict, in the task's own priority order

1. **Correct execution/risk accounting** -- addressed this round and the
   prior audit round: the cross-symbol causality leak, the end-of-run
   equity/balance mismatch, commission-in-budget, and (for MQL4)
   portfolio/correlated caps, pending-order scanning, the unprotected-
   position emergency state, and a real (if still terminal-scoped)
   instance lock are all fixed and regression-tested on the Python side;
   MQL4 remains STATIC_REVIEW/NOT_RUN, honestly labeled, with a concrete
   MetaEditor test sequence in `README.md`.
2. **Cost robustness** -- every variant was tested across C1/C2/C3; NONE
   stays positive under any of them (most were never positive to begin
   with). The ranking among variants (S5/S6 best, S3/S7 worst) is broadly
   stable across scenarios, but the absolute size of every loss grows from
   C1 to C3, as expected.
3. **Net expectancy** -- negative for all eight variants, in all three
   scenarios, with no exception.
4. **Loss character / trade-count limitations** -- S7's result is
   effectively a single-month sample dominated by a pre-trade risk gate
   halting further trading, not a genuine 2-month test; S3/S7 have the
   longest losing streaks and lowest profit factors; S5 has the shortest
   losing streak and best DD/PF among the H1-family variants; trade counts
   range from 20 (S1) to 102 (S3) on a ~2-month sample -- none of these
   counts is large enough to draw a statistically confident conclusion
   about a strategy's true edge, positive or negative.
5. **Profit magnitude** -- not reached, since no candidate is profitable
   at C1, let alone C1 AND C2.

**Per the task's own mandatory wording: šajā eksperimentā kandidāts nav
atrasts.** (In this experiment, no candidate was found.) This applies to
all eight variants under all three cost scenarios -- not one clears even
C1 alone with a positive net expectancy, so the stricter "positive in
C1 AND C2" bar is moot.

**The +2000 USD/month (20%) target remains UNCONFIRMED** for every
variant -- not merely "not yet proven," but actively contradicted by
every full-calendar-month result this experiment produced (the best,
S5's 2026-08, is still a loss). This conclusion holds regardless of
any single partial month's number, and does not change if a future
session gets a different partial month to look better -- one month,
partial or full, is never "every month."

## What this experiment does NOT establish

- That any of S1-S8 is *incapable* of ever being profitable -- only that
  none of them was, on this specific ~2-month sample, under three cost
  assumptions, with these specific fixed parameters.
- Any formal statistical significance for the ranking among the eight
  (S5/S6 "better" than S3/S7): with 20-102 trades each on overlapping/
  correlated market data, this is a descriptive comparison, not a
  hypothesis test, and no p-value or confidence interval is claimed
  anywhere in this document.
- Anything about MQL4 execution correctness beyond static code review --
  see `docs/AUDIT_2026-09-18.md`'s updated status table for exactly which
  items are EXECUTED vs STATIC_REVIEW vs NOT_RUN.

## Recommendation

No variant in this experiment has grounds for a next test on a real or
demo account: every one of the eight loses money on the only sample
available, under every cost assumption tried, including the friendliest
one (C1). The account owner's own next decision points (per prior
rounds' open questions, still open): accept this as the answer for now
and stop researching new strategies on this fixed sample, supply fresh
out-of-sample data (the only way to actually test any of S1-S8 rather
than re-fit to the same ~2 months again), or hand this document to
another researcher/model for a different angle (e.g. a genuinely
different data source, or a formal statistical framework for the
multiple-comparisons problem eight variants x three scenarios already
raises, which this document deliberately does not attempt to paper over
with an informal "least-bad" pick).
