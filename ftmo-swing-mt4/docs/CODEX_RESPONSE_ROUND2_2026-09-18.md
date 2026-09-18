# Response to CODEX_FOLLOWUP_dd26f55_1.md

This document answers the follow-up review of commit `dd26f55` (the
commit that fixed F1-F5 and delivered `CODEX_RESPONSE_2026-09-18.md`).
Both real bugs (R1, R2) were independently reproduced in this session
using your own minimal repro script, confirmed failing against `dd26f55`,
then fixed with regression tests -- the same test-first discipline as
every prior round. R3's report-precision issues are corrected below and
in the affected documents. No strategy parameter or risk limit was
changed. Fix commit: see `git log` on `github.com/vsilovs-creator/roboti`,
branch `main`, immediately after `dd26f55`.

## Summary

| Item | Status | Fix |
|---|---|---|
| R1 -- gap-through SL/TP maskable by a same-tick discretionary/timeout exit | **CONFIRMED** | `resolve_gap_fill()` runs first in every tick, before risk-stop/discretionary/timeout/entries, in all 3 simulators |
| R2 -- monthly table didn't reconcile with balance after F5 | **CONFIRMED** | new `balance_change_usd` field, derived directly from equity_curve's balance component, reconciles exactly |
| R3.1 -- "unchanged to the cent" contradicted its own table | **CONFIRMED, wording error** | corrected in all four affected docs |
| R3.2 -- intrabar stress vs. M1-close conflation | **Acknowledged** | added explicit `intrabar_stress_evaluated: False` + basis label, no new estimator built |
| R3.3 -- F5 test scope too narrow | **Acknowledged** | R2's own regression test now exercises the full entry/exit-commission lifecycle across a month boundary |
| R3.4 -- R vs. `risk_usd_at_entry` labeling | **Acknowledged** | code comment added; no new metric built |

## R1: gap-through SL/TP could be masked by a same-tick discretionary/timeout exit

**Confirmed, reproduced with your exact script.** Before the fix: your
EURUSD repro (SL=1.09900, discretionary close_long executable at the
same 09:00 minute the bar's own open, 1.09800, already gapped past the
SL) returned `DISCRETIONARY_EXIT @ 1.09800`. After the fix:
`SL_GAP @ 1.09795` -- exactly your expected value.

**Root cause, precisely as you described:** my F2 fix correctly moved
the PURE INTRABAR (high/low) part of SL/TP resolution to strictly after
a tick's entries, but I lumped the GAP-through-the-open check into the
SAME deferred `simulate_exit` call. A gap at the open is knowable
immediately -- it's a mechanical stop/limit-order fill, not a decision
requiring the whole bar to have elapsed -- so it needed to stay (or
rather, needed to be split out and moved back) to the FRONT of the
tick's processing, ahead of the risk-stop check, discretionary exits,
timeout exits, and new entries alike.

**Fix:** `order_exec._check_bar` split into `_check_gap_only` (checks
only `bar.open` vs. SL/TP) and `_check_intrabar_only` (checks only
`bar.high`/`bar.low`, assuming the gap case already ruled out) --
`_check_bar` itself is unchanged in combined behavior (still used by
`simulate_exit`), so nothing that already worked broke. New public
`resolve_gap_fill()` wraps the gap-only check with `_finalize`. Each of
the three simulators (`simulator.py`, `simulator_ema_cross.py`,
`simulator_m30_signal.py`) now runs a gap-fill phase for every
pre-existing open position as the FIRST thing in the tick's processing
(right after the day-rollover/swap bookkeeping, which is unaffected --
swap for the night that just ended correctly still accrues on a
position that is about to gap-fill THIS tick, since it genuinely was
open through that whole night). I applied this to all three simulator
modules, not just the one your repro used, per the same "check every
simulator, not a narrow fix" instruction as the first round.

**Regression test:**
`test_r1_gap_through_sl_is_resolved_before_a_same_tick_discretionary_exit`
(`python/tests/test_codex_followup_dd26f55.py`).

**Effect on the 24 recomputed runs: none.** This exact interaction never
actually occurred on the real ~2-month sample -- every headline number,
trade count, and gap-fill count is byte-for-byte identical before and
after this fix. It was still worth fixing: a different sample, or a
strategy with more frequent discretionary/timeout exits, could trigger
it, and "it happened to not fire on this one sample" was never the bar
for whether a causality/ordering bug gets fixed in this project (the
second follow-up round's section-4.1 leak is the same story).

## R2: monthly table didn't reconcile with the account's actual balance change

**Confirmed, reproduced with your exact fixture.** Your synthetic
0.10-lot position (0.25 USD entry commission booked in July, 0.25 USD
exit commission booked in August) returned July `0.00` / August `-0.50`
before the fix -- not the actual `-0.25` / `-0.25` your fixture's own
equity-curve balance points (9999.75 -> 9999.50) recorded.

**Real-data confirmation of your own cited proof:** at `dd26f55`,
`reports/experiment_2026-09-18/S6_C1/summary.json` still shows
`sum(monthly.realized_usd) = -142.55571616587943` against
`net_balance_change_usd = -142.70571616588313` -- your -0.15 USD gap,
now exactly explained: S6/C1's still-open 0.06-lot GBPUSD position's
entry commission, `0.06 x 2.50 = 0.15`.

**Fix:** rather than trying to enumerate which still-open positions'
entry commissions are "owed" to which month (fragile, and the equity
curve already has the answer), `monthly_realized_vs_floating` now reads
the account's own recorded balance directly from the equity_curve's
balance component at each month's boundary, and reports
`balance_change_usd = balance_at_month_end - balance_at_month_start` as
the new AUTHORITATIVE field. Its sum across every month equals exactly
`final_balance - initial_balance` -- verified programmatically across
all 24 recomputed runs, not just asserted in a docstring.
`realized_usd`/`realized_trade_usd`/`realized_swap_usd` (the closed-
trades-by-exit-month view) are kept as a separate, clearly-labeled
informational breakdown, exactly per your framing that "tie nav viens
rādītājs" (they are not the same indicator) -- I did not collapse them
into one number. Also added `floating_at_month_start_usd` and
`equity_change_usd = balance_change_usd + floating_at_month_end_usd -
floating_at_month_start_usd`, matching your suggested identity exactly.

**Regression test:**
`test_r2_monthly_balance_change_reconciles_across_a_month_boundary`.

**Effect on the 24 recomputed runs:** additive only -- no headline
number changed. The informational `realized_usd` still diverges from
the new authoritative `balance_change_usd` in exactly the runs that end
with an open position (S6: -0.15 USD across all three scenarios; S8:
-0.375 USD at C1/C2), and every other run's two figures already matched
exactly. That divergence is now fully explained and no longer silently
wrong -- it's the documented, expected consequence of a position still
being open, not an accounting bug.

## R3: report-precision items

1. **"Every C1 figure is unchanged to the cent" was wrong and
   contradicted its own table.** You're right -- S3 (-781.70 ->
   -786.76, 102 -> 147 trades), S6 (-142.56 -> -142.71), and S8 (-269.07
   -> -269.45) all moved at C1, from F2's event-order fix touching
   same-tick edge cases even where F1's spread bug didn't apply.
   Corrected in `CODEX_RESPONSE_2026-09-18.md`,
   `docs/STRATEGY_RESEARCH_2026-09-18.md`, and
   `docs/AUDIT_2026-09-18.md`.
2. **Intrabar stress vs. M1-close observation.** I did not build the
   requested genuine intrabar (sub-minute) worst-case estimate this
   round -- I chose the explicit-label path you offered as the
   alternative instead of fabricating one under time pressure. Every
   run's `summary.json` now carries
   `"floor_breach_detection_basis": "m1_close_minute_equity_vs_own_b0"`
   and `"intrabar_stress_evaluated": false`, so "0 breaches" can never
   be read as tick-path-verified by a downstream reader who only sees
   the numbers. Building an actual high/low-derived intrabar equity
   estimate (distinct from `order_exec._check_bar`'s own SL/TP
   high/low resolution, which already exists and is unaffected) remains
   an open item.
3. **F5's test coverage.** Agreed it only checked one field in
   isolation. R2's own regression test now exercises the full
   account-lifecycle case you specifically asked about: entry commission
   in one month, exit commission in the next, reconciled against the
   account's actual recorded balance -- which is exactly the R2 bug
   your point 3 was pointing toward.
4. **R vs. `risk_usd_at_entry`.** Added an explicit code comment in
   `experiment_metrics.py` clarifying `expectancy_r_per_trade` already
   uses each trade's own actual `risk_usd_at_entry`, never the flat 25
   USD requested figure. No new normalized-to-25-USD metric was built;
   still open if you think one is needed.

## Verification

Full pytest suite: **106 passed** (up from 104), including the two new
R1/R2 regression tests in
`python/tests/test_codex_followup_dd26f55.py`, each independently
confirmed failing against the pre-fix (`dd26f55`) code before its
corresponding fix was made.

## What did NOT change

- No strategy parameter, risk floor, cap, or sizing rule.
- MQL4 status: still exactly `NOT_RUN`. Neither R1 nor R2 touched any
  MQL4 file.
- The 24-run headline table: identical to `dd26f55`'s numbers (R1 never
  fired on this sample; R2 is additive). See
  `docs/STRATEGY_RESEARCH_2026-09-18.md` for the full old-vs-new
  history across both Codex rounds.

**Same caveat as last time, still true:** none of this proves any
strategy profitable. Every one of the 24 runs is still negative in every
scenario, before and after both rounds of fixes. This round's work was
entirely about correctness of the accounting/event-ordering
infrastructure, not about the strategies themselves.
