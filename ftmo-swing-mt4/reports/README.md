# Reports index

All EXPLORATORY -- see `../docs/UNKNOWNS.md` and `../docs/RISK_SPEC.md`.

**2026-09-18: an independent code audit found two P0 bugs in the offline
simulators (entry-candle SL/TP silently skipped; configured risk caps not
enforced in the H1 simulator) that affected every run below through
run_005. Both are fixed -- see `../docs/AUDIT_2026-09-18.md`.
run_006/007/008/009 are the corrected re-runs; run_001 through run_005 are
SUPERSEDED and kept only for transparency about what changed and why.**

## Superseded (pre-audit-fix)

- **run_001/** -- SUPERSEDED (also pre-dates confirmed server clock/commission).
- **run_002_confirmed_tz_commission/** -- SUPERSEDED. London breakout with
  confirmed clock/commission, but before the P0 simulator fixes. Was
  -485.99 USD; see run_006 for the corrected number.
- **run_003_strategy_comparison/** -- SUPERSEDED. Three-strategy comparison
  before the P0 fixes. See run_008 for the corrected comparison.
- **run_004_ema_cross_chosen/** -- SUPERSEDED. Was -257.98 USD (28 trades);
  see run_007 for the corrected number.
- **run_005_overfitting_sweep_demo/** -- SUPERSEDED. Was 38% (31/81)
  positive; see run_009 for the corrected sweep.

## Current (post-audit-fix, 2026-09-18)

- **run_006_baseline_corrected/** -- London Range Breakout + Retest v1,
  same confirmed inputs as run_002, re-run after the P0 fixes: **20 trades,
  net -446.71 USD (-4.47%)**.
- **run_007_ema_cross_corrected/** -- CURRENT / chosen strategy. EMA(20/50)
  H1 crossover, re-run after the P0 fixes and with swap now modeled:
  **25 trades, net -296.65 USD (-2.97%)**, including -23.27 USD swap over
  26 nights held. Still the smallest loss of the three, still not a
  validated result -- see `../README.md`.
- **run_008_strategy_comparison_corrected/** -- Corrected three-strategy
  comparison. All three still net-negative; see `COMPARISON.md` in that
  folder and `../docs/AUDIT_2026-09-18.md` for the before/after table.
- **run_009_overfitting_sweep_corrected/** -- Corrected 81-combination
  sweep: **26% (21/81)** came out net positive (down from the pre-fix 38%,
  same qualitative conclusion: still not adopted, still evidence for
  `../docs/HANDOFF_STRATEGY_SEARCH.md` / `../docs/FULL_REPORT.md`'s
  argument against naive parameter searching on this sample, worded more
  carefully post-audit -- see `../docs/AUDIT_2026-09-18.md` point P1-8).
