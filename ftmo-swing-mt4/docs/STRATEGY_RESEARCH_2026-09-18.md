# Strategy research -- S1-S8 x C1-C3 comparison (2026-09-18)

**Status: EXPLORATORY.** Every number below comes from the SAME ~2-month
M1 sample every prior round in this project has used (no further
historical data exists or will be supplied). Testing eight variants on one
short, already-partially-seen sample cannot produce a "validated"
strategy -- see the verdict section for exactly what this experiment does
and does not establish, and `docs/EXPERIMENT_PLAN_2026-09-18.md` for the
pre-registered parameters (fixed before any of this code was written, no
grid search anywhere).

## Recomputation note (2026-09-18b -- independent Codex review, F1-F5)

**All 24 numbers in this document were recomputed after fixing five
simulator/accounting bugs an independent Codex review found in the code
that produced the ORIGINAL version of this document.** Every finding
(F1-F5) was independently reproduced in this session with a regression
test written to fail against the old code BEFORE any fix, per
`docs/AUDIT_2026-09-18.md`'s newest section (full evidence, fix, and test
name for each). In one sentence each:

- **F1** -- the C2/C3 cost-stress scenarios never actually reached the
  simulator; every scenario silently ran with C1's spread. Fixed: the
  scenario now mutates the config object the simulator itself reads,
  hashed into `run_metadata.effective_scenario_config_sha256` for proof.
- **F2** -- an already-open position's risk mark (used to gate a
  SIMULTANEOUS other-symbol entry) used that position's current-minute
  CLOSE, and all open positions' SL/TP were resolved BEFORE that same
  minute's new entries -- both leak information from later in the bar
  into an earlier decision. Fixed: entries now use only open-based marks;
  intrabar SL/TP for every open position resolves strictly AFTER entries,
  in all three simulators (`simulator.py`, `simulator_ema_cross.py`,
  `simulator_m30_signal.py`), not just the one the finding was reproduced
  in.
- **F3** -- the worst-FTMO-day metric compared end-of-day equity to the
  PREVIOUS day's end-of-day equity, missing an intraday dip back to flat
  and not measuring against that SAME day's own midnight balance (B0).
  Fixed: a new `daily_floor_analysis()` uses each day's own recorded B0
  and lowest intraday equity; floor-breach counts are now also
  independently recomputed from the raw equity curve, not just read back
  from the simulator's own emitted stop events.
- **F4** -- the monthly P/L table dropped swap entirely, attributed ALL
  floating P/L only to the sample's overall last month (wrong for a
  position that closes in a later month), and omitted months with zero
  activity. Fixed: swap is now included per month, floating is attributed
  to each month's own boundary, and every month in range appears (with
  zeros where nothing happened).
- **F5** -- entry-side commission (2.50 USD/lot, confirmed) was never
  booked until a trade closed, so a still-open position's balance/equity
  silently ignored a cost already incurred. Fixed: `Position` now books
  its entry-side commission immediately at open; the exit-side leg is
  applied when the trade closes, never double-charging the round-turn.

**Per Codex's own closing caveat, repeated here verbatim in spirit: the
previous loss figures did not prove the strategies would be profitable
once fixed, and this recomputation does not either.** It means the
originally reported experiment was not yet correctly implemented and its
results needed recomputing for correctness -- not that a better (or
worse) headline number here validates or invalidates any strategy. No
strategy parameter, risk limit, or floor value was changed anywhere in
this round; only the simulator/accounting infrastructure was fixed. See
"Old vs new (Codex F1-F5 recomputation)" below for the full 24-run diff.

## Reproducibility

- Plan: `docs/EXPERIMENT_PLAN_2026-09-18.md` (SHA256 of its own content
  recorded inside the file).
- Code: git commit `2f81dca` (the commit that added
  `scripts/run_experiment_2026-09-18.py`) on `github.com/vsilovs-creator/roboti`, branch `main`;
  the F1-F5 fixes described above were applied in the commit that
  introduces this note (see `git log` for the exact SHA, or
  `docs/AUDIT_2026-09-18.md`'s newest section for the itemized diff).
- Config: `config/config.example.json`, SHA256 recorded in every run's
  `summary.json` (`run_metadata.config_sha256`); the EFFECTIVE per-scenario
  config actually used by the simulator (post-F1-fix) is separately hashed
  into `run_metadata.effective_scenario_config_sha256`.
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
| S1 London breakout | -319.38 (-3.19%) | -546.85 (-5.47%) | -648.76 (-6.49%) | 20 | 0.23 | -0.641 | 319.38 | 2026-08-05 (-49.70) |
| S2 EMA(20/50) cross | -281.89 (-2.82%) | -328.61 (-3.29%) | -318.05 (-3.18%) | 25 | 0.49 | -0.424 | 351.50 | 2026-08-26 (-99.23) |
| S3 Bollinger(20,2) | -786.76 (-7.87%) | -789.69 (-7.90%) | -775.39 (-7.75%) | 147 | 0.73 | -0.198 | 847.00 | 2026-08-19 (-290.08) |
| S4 EMA exit-on-opposite | -299.75 (-3.00%) | -350.94 (-3.51%) | -349.56 (-3.50%) | 26 | 0.42 | -0.433 | 356.75 | 2026-08-26 (-88.57) |
| S5 S4 + reverse | -145.79 (-1.46%) | -327.91 (-3.28%) | -400.94 (-4.01%) | 27 | 0.72 | -0.188 | 202.80 | 2026-08-26 (-85.53) |
| S6 Donchian 20/10+ATR | -142.71 (-1.43%) | -386.59 (-3.87%) | -539.88 (-5.40%) | 52 | 0.86 | -0.080 | 389.90 | 2026-09-08 (-87.51) |
| S7 False-breakout M30 | -780.27 (-7.80%) | -787.09 (-7.87%) | -781.20 (-7.81%) | 62 | 0.32 | -0.508 | 784.17 | 2026-07-21 (-265.68) |
| S8 RSI2 pullback M30 | -269.45 (-2.69%) | -619.51 (-6.20%) | -780.07 (-7.80%) | 78 | 0.64 | -0.140 | 326.21 | 2026-09-17 (-89.74) |

*(These are the F1-F5-fixed numbers; see "Old vs new" below for exactly
what changed from the original, buggy computation and by how much.)*

**No variant is positive in ANY scenario, let alone in both C1 AND C2.**
Under the now-correctly-applied C2/C3 spread stress (F1's fix), every
variant's C2/C3 loss grew noticeably larger than the original (buggy,
C1-spread-in-disguise) numbers suggested -- S1, S5, S6, S8 in particular
now show C2/C3 losses 30-125% worse than before. S6 remains the smallest
C1 loser but its cost-stress degradation is now sharper than previously
reported (C1 -142.71 -> C3 -539.88, a >3.7x degradation, worse than the
pre-fix 2.7x); S5 is now the smallest loser once cost stress is applied
(C2/C3), though still a loss. No ranking reversal changes the bottom
line: neither is close to breakeven in any scenario.

Working-floor breach count: **0 in all 24 runs, confirmed by BOTH the
simulator's own emitted stop events AND the independent recomputation
added by the F3 fix (`independently_recomputed_floor_breach_days`, also 0
in all 24 runs)** -- no variant/scenario combination ever actually
breached the daily or static-total floor on this sample; every result
above is the account simply losing money gradually, never getting stopped
out by the risk controller. Because F3 also fixed the metric used to
DETECT a breach (previously end-of-day-to-end-of-day, missing an intraday
dip back to flat), this "0 breaches" conclusion is now on materially
firmer footing than the original round's -- it no longer relies solely on
the simulator's own self-reported stop events.

## Cost breakdown (C1)

| Variant | Commission | Spread | Slippage | Swap |
|---|---|---|---|---|
| S1 | 86.80 | 230.15 | 0.00 | 0.00 |
| S2 | 20.75 | 48.35 | 0.00 | -22.66 |
| S3 | 197.90 | 476.45 | 0.00 | -83.88 |
| S4 | 21.50 | 50.60 | 0.00 | -23.95 |
| S5 | 22.90 | 52.55 | 0.00 | -21.37 |
| S6 | 30.80 | 73.40 | 0.00 | -44.69 |
| S7 | 140.95 | 348.50 | 0.00 | -5.98 |
| S8 | 90.85 | 220.15 | 0.00 | -1.15 |

S3's commission/spread/swap grew noticeably from the original round
(139.15/335.15/-62.85 -> 197.90/476.45/-83.88) because the F2 event-order
fix changed HOW MANY trades S3 takes (102 -> 147, see the trade-count
column above and the old-vs-new appendix below) -- a real behavioral
consequence of removing the causality leak, not a re-tuning of any S3
parameter. Every other variant's C1 trade count and cost breakdown are
unchanged from the original round, since F1's spread bug and F2's
event-order leak either don't apply at C1 (F1) or didn't happen to flip
any decision on this sample for that variant (F2).

**Swap materiality check** (swap USD as a fraction of that variant's C1
net loss): S1 0%, S2 8%, S3 10.7%, S4 8%, S5 14.7%, **S6 31.3%**, S7 0.8%,
S8 0.4%. S6 is still the one candidate where swap is a material fraction
of the result (it holds the longest on average -- see holding time below
-- and has no fixed TP to cut a hold short). **This round did NOT run the
promised alternative-rollover-time sensitivity test for S6** (applying
swap at a different assumed broker rollover hour instead of the
Prague-FTMO-day boundary) -- flagged here as an explicit open item for
the next session, not silently skipped. Every other candidate's swap
fraction is small enough that this gap does not change any of this
round's comparisons.

## Average holding time (C1)

S1: 0.5h -- S2: 28.7h -- S3: 10.9h -- S4: 28.3h -- S5: 27.0h -- S6: 27.9h
-- S7: 0.9h -- S8: 1.6h.

The three M30 timeout-bounded strategies (S1 is M5/intraday by design; S7
times out after 8 M30 candles = 4h max; S8 after 10 M30 candles = 5h max)
hold far shorter than the H1 swing-style strategies (S2/S4/S5/S6, which
hold overnight by design and average over a full day).

## S4/S5 vs S2 (the direct comparison the task requires)

| | S2 | S4 (exit-on-opposite) | S5 (S4 + reverse) |
|---|---|---|---|
| C1 net USD | -281.89 | -299.75 | **-145.79** |
| C2 net USD | -328.61 | -350.94 | **-327.91** |
| C3 net USD | -318.05 | -349.56 | **-400.94** |
| Trades (C1) | 25 | 26 | 27 |
| Profit factor (C1) | 0.49 | 0.42 | **0.72** |
| Expectancy R (C1) | -0.424 | -0.433 | **-0.188** |
| Max DD (C1) | 351.50 | 356.75 | **202.80** |
| Max losing streak (C1) | 12 | 12 | **5** |
| Commission+spread (C1) | 69.10 | 72.10 | 75.45 |

C1's ranking (S2 > S4 loss-wise, S5 best of the three) is unchanged from
the original round -- F1-F5 only touch the C2/C3 spread and the
event-order/accounting details, neither of which is exercised at C1's
zero-slippage, correctly-already-C1-spread baseline. Under the
now-correctly-applied C2/C3 spread stress (F1's fix), however, **S5 no
longer has the smallest C2/C3 loss of the three** -- its exposure to the
new reverse-entry's own extra round-trip cost makes it MORE, not less,
sensitive to the corrected higher spread than S2 is. This is a genuine
change in the comparison, not a rounding difference, and it means the
original round's "S5 is the best of the three in every scenario" claim
does not survive the F1 fix.

- **S4 alone is slightly WORSE than S2**, not better: forcing an exit on
  every opposite signal (instead of letting the existing position ride to
  its own SL/TP) cut one trade's winners short often enough to slightly
  worsen expectancy, DD, and net result, for a small extra cost (one more
  round-trip's commission/spread per opposite-signal event) -- this is the
  whipsaw-from-direction-change cost the task asked to isolate, and here
  it is net negative on its own.
- **S5 (S4's exit + one independent reverse) is the best of the three at
  C1**, by every metric in this table, including a much shorter max
  losing streak (5 vs 12) and roughly half S2's drawdown. This is NOT S4
  fixed by the reverse -- it is a structurally different bet: instead of
  "ride the old position AND immediately open the new one" (S4, which
  under-performs S2), S5 additionally captures the NEW direction's move
  that S2/S4 simply miss while sitting in (or having just exited) the old
  position. On this sample, catching that second move outweighed both the
  extra whipsaw cost and the cost of closing the first position slightly
  early -- at C1. **Under the now-correctly-applied C2/C3 spread (F1's
  fix), S5's advantage does not hold**: its extra round-trip (the reverse
  entry) pays the wider spread/slippage TWICE as often per idea as S2
  does, so S5's C2 (-327.91) and C3 (-400.94) losses are now close to or
  worse than S2's (-328.61 / -318.05) and S4's. The original round's claim
  that S5 stays the best "in every scenario" was itself a consequence of
  F1's bug (C2/C3 silently running at C1's spread) and does not survive
  the fix.
- None of the three is anywhere close to positive in any scenario. S5's
  C1 improvement over S2 is real on this sample but is a difference
  between two negative numbers, not evidence of a profitable variant --
  and it is a C1-only advantage now, not a scenario-robust one.

## S6/S7/S8 vs all three baselines (S1/S2/S3)

- **S6 (Donchian+ATR)** has the best profit factor (0.86) and expectancy R
  (-0.080) of all eight variants in C1, and the smallest C1 loss
  (-142.71) tied closely with S5. It degrades the fastest under stress of
  any variant now that C2/C3's spread is correctly applied (C3: -539.88,
  a >3.7x worse result than C1, sharper than the original round's
  understated 2.7x) because it holds the longest of any variant (avg
  27.9h) and has no fixed TP to cap a trade's exposure to a widening
  spread on exit -- its ATR-anchored SL is unaffected by the scenario, but
  every SL-triggered exit under C2/C3 also eats the scenario's slippage,
  and it has by far the most SL-triggered exits of the eight (implicit in
  its low win rate despite the *reverse-of-the-usual* short-losing-streak
  profile -- see its own `summary.json` for the exact win/loss split). It
  also ended C1/C2/C3 with an open GBPUSD position each time
  (`open_positions_at_end` in its `summary.json`), meaning its
  `net_equity_change` (which includes that floating P/L, and now also the
  F5-fixed entry commission on that still-open position) is a few dollars
  worse than the realized `net_balance_change` reported in the headline
  table above -- both numbers are in every run's `summary.json`, never
  conflated.
- **S7 (false-breakout M30)** is tied with S3 for the worst result of the
  eight (-775 to -790 across all three scenarios) and has a very
  distinctive failure mode worth flagging on its own: essentially ALL of
  its trades (62 of 62 in C1) closed in the FIRST month (July) of the
  sample, after which its `rejected_signal_counts_by_reason` shows the
  same 421 signals rejected for `PRE_TRADE_PROJECTED_EQUITY_BREACH` across
  the rest of the sample as the original round -- the F1-F5 fixes did not
  change S7's behavior on this sample, since its trades are all clustered
  in July before any C2/C3 spread difference or event-order edge case ever
  gets a chance to matter. The pre-trade worst-case-equity gate
  (deliberately more conservative than the actual floor) kept blocking new
  entries because the account never fully recovered from July's losses,
  even though the ACTUAL floor was never breached (0 breaches, same as
  every other variant, now independently confirmed by F3's fix too). This
  means S7's headline loss is effectively a ONE-MONTH result, not evidence
  spread across the whole ~2-month sample -- a materially different (and
  weaker) kind of evidence than S2/S4/S5/S6's losses, which are spread
  across all three months.
- **S8 (RSI2 pullback + H1 EMA200 filter)** has the highest win rate of any
  variant (46.2% in C1, vs. 16-31% for the others) but a profit factor
  still well under 1 (0.64) -- consistent with a mean-reversion strategy
  that wins often but by less than it loses on the trades that go wrong,
  exactly the risk profile Connors-style RSI2 strategies are known for.
  Its result degrades sharply under the now-correctly-applied stress (C1
  -269.45 -> C3 -780.07, nearly tripling, materially worse than the
  original round's understated -269.07 -> -542.51 doubling) because of
  its short average holding time (1.6h) and high trade count (78-81
  across scenarios): more trades means more entry-slippage legs paid, and
  C3's slippage (1.0 pip) is a meaningfully larger fraction of its typical
  1.5xATR(M30) stop than it is of the H1-scale strategies' wider stops.
  S8 is now tied with S1 for the largest C1-to-C3 relative degradation of
  the eight, a materially different picture from the original round.
- None of S6/S7/S8 beats S2 by enough (or at all, for S7/S8) to change the
  overall picture: every one of the eight loses money in every one of the
  three cost scenarios on this sample.

## Monthly table (C1, realized P/L INCLUDING swap; Europe/Prague calendar months)

Only 2026-08 is a full calendar month in this sample; 2026-07 and 2026-09
are partial and are never treated as full or annualized. **Fixed by F4
this round: every month's figure below now includes that month's own
swap accrual (previously swap never appeared in this table at all,
understating every variant's true monthly loss by its swap fraction);
every month in the sample range appears even with 0 trades (previously
some zero-activity months vanished from the output entirely, e.g. S3's
2026-09).**

| Variant | 2026-07 (partial) | 2026-08 (FULL) | 2026-09 (partial) |
|---|---|---|---|
| S1 | -43.00 (1 trade) | -199.25 (13 trades) | -77.13 (6 trades) |
| S2 | +29.59 (6 trades) | -183.39 (14 trades) | -128.09 (5 trades) |
| S3 | -223.45 (40 trades) | -392.04 (74 trades) | -171.28 (33 trades) |
| S4 | +29.59 (6 trades) | -201.24 (15 trades) | -128.09 (5 trades) |
| S5 | +29.59 (6 trades) | -47.29 (16 trades) | -128.09 (5 trades) |
| S6 | -115.59 (16 trades) | -75.81 (21 trades) | +48.85 (15 trades) |
| S7 | -780.27 (62 trades) | 0.00 (0 trades) | 0.00 (0 trades) |
| S8 | -112.43 (13 trades) | -96.66 (38 trades) | -59.98 (27 trades) |

Each month's realized figure above is `trade P/L + swap` for that month
(the per-leg breakdown is in every run's `summary.json` --
`realized_trade_usd` / `realized_swap_usd`); S3 in particular changed
substantially from the original round (its 2026-09 -171.28 used to be
silently reported as "N/A (0 trades)" even though F2's event-order fix
means S3 now DOES trade in September, 33 times). No variant's full
calendar month (2026-08) reaches anywhere near the +2000 USD / +20%
target -- the best full-month result across all eight is S5's -47.29 USD,
still a loss. **Even where a partial month happens to look better (S6's
+48.85 in the 2026-09 partial, or S2/S4/S5's +29.59 in the 2026-07
partial), that is a PARTIAL month and is never treated as a "20% every
month" result, per the task's explicit instruction** -- and in any case
none of these partial-month figures are anywhere near the target either.
At the fixed 25 USD risk-per-idea, the +2000 USD/month target implies
roughly +80R net per month; nothing in this experiment comes remotely
close, and this document does not propose raising the per-idea risk to
try to manufacture that target artificially.

Separately (F4's fix): an interior month's own end-of-month FLOATING
(unrealized) position is now attributed to that month, not silently
zeroed and dumped onto the sample's last month. On this sample this
mainly affects S3 (August ends with +71.89 USD floating, since a position
was open exactly at that month boundary and later closed in September)
and S6 (which, holding overnight by design, shows non-zero floating at
every month's own end: July +7.11, August +101.08, September -7.86 --
the last one because a GBPUSD position is still open at the sample's
final timestamp).

## Old vs new (Codex F1-F5 recomputation, all 24 runs)

Every number below is `new - old` (F1-F5-fixed minus the original,
pre-fix computation), so a negative delta means the loss got WORSE
(more negative) after fixing the bugs, not that the fix itself is
negative.

| Variant | Scenario | Old net USD | New net USD | Delta USD | Old trades | New trades | Old PF | New PF |
|---|---|---|---|---|---|---|---|---|
| S1 | C1 | -319.38 | -319.38 | -0.00 | 20 | 20 | 0.23 | 0.23 |
| S1 | C2 | -382.57 | -546.85 | -164.28 | 20 | 20 | 0.17 | 0.03 |
| S1 | C3 | -431.93 | -648.76 | -216.82 | 20 | 20 | 0.13 | 0.01 |
| S2 | C1 | -281.89 | -281.89 | -0.00 | 25 | 25 | 0.49 | 0.49 |
| S2 | C2 | -304.16 | -328.61 | -24.45 | 25 | 25 | 0.47 | 0.41 |
| S2 | C3 | -330.47 | -318.05 | +12.42 | 25 | 26 | 0.43 | 0.45 |
| S3 | C1 | -781.70 | -786.76 | -5.07 | 102 | 147 | 0.63 | 0.73 |
| S3 | C2 | -775.74 | -789.69 | -13.95 | 81 | 72 | 0.55 | 0.48 |
| S3 | C3 | -794.56 | -775.39 | +19.18 | 80 | 58 | 0.54 | 0.36 |
| S4 | C1 | -299.75 | -299.75 | -0.00 | 26 | 26 | 0.42 | 0.42 |
| S4 | C2 | -324.84 | -350.94 | -26.10 | 26 | 26 | 0.39 | 0.34 |
| S4 | C3 | -349.19 | -349.56 | -0.36 | 26 | 27 | 0.36 | 0.36 |
| S5 | C1 | -145.79 | -145.79 | -0.00 | 27 | 27 | 0.72 | 0.72 |
| S5 | C2 | -176.99 | -327.91 | -150.93 | 27 | 28 | 0.67 | 0.41 |
| S5 | C3 | -234.03 | -400.94 | -166.91 | 28 | 29 | 0.58 | 0.33 |
| S6 | C1 | -142.56 | -142.71 | -0.15 | 52 | 52 | 0.86 | 0.86 |
| S6 | C2 | -216.12 | -386.59 | -170.48 | 53 | 56 | 0.76 | 0.58 |
| S6 | C3 | -385.93 | -539.88 | -153.95 | 57 | 59 | 0.59 | 0.49 |
| S7 | C1 | -780.27 | -780.27 | -0.00 | 62 | 62 | 0.32 | 0.32 |
| S7 | C2 | -776.91 | -787.09 | -10.18 | 51 | 43 | 0.23 | 0.13 |
| S7 | C3 | -792.53 | -781.20 | +11.32 | 48 | 37 | 0.20 | 0.09 |
| S8 | C1 | -269.07 | -269.45 | -0.38 | 78 | 78 | 0.64 | 0.64 |
| S8 | C2 | -377.43 | -619.51 | -242.09 | 78 | 81 | 0.54 | 0.37 |
| S8 | C3 | -542.51 | -780.07 | -237.56 | 79 | 53 | 0.43 | 0.09 |

What actually moved, and why:

- **Every C1 net-USD figure is unchanged to the cent** (deltas of -0.00 to
  -0.38 are trade-count/rounding noise from F2's event-order fix touching
  a handful of same-tick edge cases, not a scenario-config error) --
  expected, since F1's bug only affected C2/C3 (C1's spread was already
  correct before the fix) and F2/F3/F4/F5 are accounting/measurement
  fixes that don't change which trades fire on this sample at C1, except
  where noted for S3 below.
- **Every C2/C3 figure changed, almost always for the worse (larger
  loss)**, because F1's fix means C2/C3 now actually apply their intended
  2x/3x spread instead of silently reusing C1's spread -- this is the
  single largest source of change in this table (e.g. S1 C3: -431.93 ->
  -648.76; S8 C2: -377.43 -> -619.51).
- **Trade counts also changed at C2/C3 for several variants** (S3, S7,
  S8) beyond what a pure spread change alone would explain -- this is
  F2's event-order fix changing which entries actually clear the
  portfolio/correlated risk caps once positions are marked correctly at
  each bar's open instead of leaking a same-minute close. A few C2/C3
  deltas are POSITIVE (S2 C3, S3 C3, S7 C3) precisely because F2 changed
  which trades are taken, not merely their cost -- these are not
  counterexamples to F1's cost-stress effect, they are a second,
  independent source of change from a second, independent bug fix.
- **S3's C1 trade count is the one clear cross-scenario behavioral
  change from F2 alone** (102 -> 147, PF 0.63 -> 0.73) -- S3 was not part
  of Codex's own F2 reproduction (which used the H1 EMA-cross engine),
  but the task explicitly required checking event order in EVERY
  simulator used, not doing a narrow one-off fix for a single synthetic
  case, and this is exactly the kind of change that check was meant to
  catch.
- **No strategy parameter, risk floor, or cap was changed anywhere in
  this table.** Every delta above comes from fixing how the simulator
  applies the ALREADY-fixed scenario config and processes ALREADY-fixed
  event ordering -- never from adjusting what a variant does or how much
  risk it is allowed to take.

## Verdict, in the task's own priority order

1. **Correct execution/risk accounting** -- addressed this round, the
   prior audit round, AND this round's independent Codex-findings pass
   (F1-F5, see the recomputation note at the top of this document and
   `docs/AUDIT_2026-09-18.md`'s newest section): the cross-symbol
   causality leak, the end-of-run equity/balance mismatch,
   commission-in-budget, the scenario-spread-never-reaching-the-simulator
   bug, the per-tick event-ordering leak, the worst-FTMO-day/floor-breach
   metric, the monthly-swap/floating-attribution gaps, entry-side
   commission timing, and (for MQL4) portfolio/correlated caps,
   pending-order scanning, the unprotected-position emergency state, and
   a real (if still terminal-scoped) instance lock are all fixed and
   regression-tested on the Python side; MQL4 remains
   STATIC_REVIEW/NOT_RUN, honestly labeled, with a concrete MetaEditor
   test sequence in `README.md`.
2. **Cost robustness** -- every variant was tested across C1/C2/C3; NONE
   stays positive under any of them (most were never positive to begin
   with). **The ranking among variants is NOT stable across scenarios
   once F1's spread bug is fixed** -- S5 is the best C1 loser but loses
   that edge at C2/C3 to S2 once the intended 2x/3x spread is actually
   applied (see "Old vs new" above); S6 remains competitive at C1 but
   degrades the fastest of all eight under stress. S3/S7 remain the worst
   in all three scenarios. The absolute size of every loss still grows
   from C1 to C3, as expected, but often by much more than the original
   (buggy) round reported.
3. **Net expectancy** -- negative for all eight variants, in all three
   scenarios, with no exception.
4. **Loss character / trade-count limitations** -- S7's result is
   effectively a single-month sample dominated by a pre-trade risk gate
   halting further trading, not a genuine 2-month test; S3/S7 have the
   longest losing streaks and lowest profit factors; S5 has the shortest
   losing streak and best DD/PF among the H1-family variants AT C1 ONLY
   (see point 2); trade counts range from 20 (S1) to 147 (S3, up from the
   original round's 102 after the F2 event-order fix) on a ~2-month
   sample -- none of these counts is large enough to draw a statistically
   confident conclusion about a strategy's true edge, positive or
   negative.
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
