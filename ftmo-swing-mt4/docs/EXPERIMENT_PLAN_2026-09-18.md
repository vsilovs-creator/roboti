# Experiment plan -- 8-variant strategy comparison x 3 cost scenarios

Written and hashed BEFORE any S4-S8 code was written or run, per the task's
explicit instruction ("Pirms jaunajiem rezultatiem saglaba ... planu un
SHA256"). This file is the pre-registration: if a later result does not
match what is described here, that is itself a finding to report, not
something to quietly edit away in this file.

- Starting commit for this experiment: `cde13f6` (the commit that closed
  section 4.1/4.3/4.4/4.5/4.6 of the follow-up audit).
- Repository: `github.com/vsilovs-creator/roboti`, branch `main`.
- No grid search, no parameter optimization anywhere in this plan. Every
  parameter below is fixed before any run and is either a textbook default,
  the already-adopted S1/S2/S3 parameter, or a value taken directly from the
  task instructions. If a result is negative, the parameter is NOT tuned to
  try to fix it -- see docs/STRATEGY_RESEARCH_2026-09-18.md's verdict
  section for what happens instead.

## 1. Fixed universe

- Symbols: EURUSD + GBPUSD, one shared account-wide risk controller (not two
  independent single-pair backtests summed together) -- exactly the existing
  `simulator.py` / `simulator_ema_cross.py` design.
- Account: USD 10,000 initial balance, FTMO 2-Step Swing limits as already
  confirmed (daily working floor balance_at_midnight-300, static total floor
  9200, both evaluated independently).
- Risk per idea: 25 USD, portfolio cap 100 USD, correlated-group cap 50 USD
  (EURUSD+GBPUSD same USD-direction bucket) -- unchanged from S1/S2/S3.
- Data: the same, only, ~2-month M1 sample already loaded for S1-S3. No new
  historical data exists or will be supplied (repeated from every prior
  round's docs) -- S6/S7/S8 are tested on the SAME sample the account owner
  has already seen S1-S3 fail to clear the "hindsight-selected sample"
  problem this task's own "no candidate found" wording exists to guard
  against.
- **8 separate simulated 10,000 USD accounts**, one per variant (S1..S8),
  each with its own independent balance/equity/risk-state -- never 8
  strategies sharing one account's risk budget, and never summed as if they
  were 8 sub-accounts of one bigger account.
- **24 total runs** = 8 variants x 3 cost scenarios (C1/C2/C3 below), each
  variant re-run fresh under each scenario (lot sizes differ per scenario,
  see section 3).

## 2. The 8 variants -- exact parameters, no tuning

### S1 -- London Range Breakout + Retest v1 (existing, unchanged)
Exactly `config/config.example.json`'s `london_breakout_retest_v1` block and
`strategy.py`/`simulator.py` as already committed. Reference/baseline only.

### S2 -- EMA(20/50) H1 crossover (existing, unchanged) -- the comparison baseline
Exactly `config/config.example.json`'s `ema_cross_v1` block
(fast=20, slow=50, ATR14 H1 x1.5 SL, 3R TP, `enforce_session_close=false`)
and `strategy_ema_cross.py`/`simulator_ema_cross.py` as already committed.
S4/S5/S6 are all built as variations ON TOP of this exact engine/config, so
S2 is also the direct comparison point for all three (spec section 8.3).

### S3 -- Bollinger(20,2) H1 mean-reversion (existing, unchanged)
Exactly as already committed in `strategy_bb_reversion.py`.

### S4 -- S2 + full exit on opposite EMA cross only
Same engine/config as S2 (`EmaCrossEngine`, identical parameters). Because
`EmaCrossEngine.on_h1_candle` only fires on an actual fast/slow crossover,
two consecutive signals for the same symbol can never share a direction --
a same-direction re-cross is structurally impossible without an opposite
cross firing first. So "exit on opposite cross only, no same-event
re-entry" reduces to one precise rule at the point where S2's engine would
currently emit `SYMBOL_ALREADY_HAS_OPEN_POSITION` and skip the signal: S4
instead closes the open position (at that signal's normal fill bar/price)
and consumes the signal -- it does NOT open a new position from that same
signal event. The position that opens next is a genuinely new entry from
the FOLLOWING signal event, sized/checked exactly like any S2 entry.
Implementation: a new `on_opposite_signal` mode parameter on the shared H1
runner (see section 4), value `"close_only"`, vs. S2's existing implicit
`"skip"` behaviour.

### S5 -- S4's exit + one independent reverse idea
Same engine/config as S2/S4. On every new H1 signal:
1. If a position is open (necessarily opposite direction, per S4's
   reasoning above), close it exactly as S4 does.
2. Then -- same event, same signal, re-checking equity/day-floor/total-floor
   AND the portfolio (100 USD) AND correlated-group (50 USD) caps AND costs
   from scratch, exactly as any fresh S2 entry would be checked -- attempt
   to open ONE new idea in the signal's direction, same S2 SL/TP style
   (ATRx1.5 SL, 3R TP), sized at the normal 25 USD budget.
   - No lot doubling, no larger size to "recover" step 1's loss: sizing
     uses the same `lots_for_risk(25 USD, ...)` call S2 uses, ignoring the
     just-closed trade's result entirely.
   - No forced-recovery logic of any kind; if the cap/floor check in step 2
     fails, the account is simply flat after step 1's close (a normal S2/S4
     skip), never retried later for "the same" signal.
   - At most one such reverse per new H1 signal (this is structural: step 2
     runs once per signal event, not in a loop).
   - Does NOT reset or special-case the daily/total stop or the day's
     entries-used bookkeeping in any way.
Implementation: `on_opposite_signal="close_and_reverse"` on the same shared
runner mode parameter as S4.

### S6 -- Donchian H1 20/10 with ATR stop
- Entry (H1, using only fully-closed bars, excluding the signal bar itself):
  `U20[t] = max(high[t-20..t-1])`, `L20[t] = min(low[t-20..t-1])`.
  BUY if `close[t] > U20[t]`; SELL if `close[t] < L20[t]`.
- Initial SL = entry_price -/+ 2.0 x ATR14(H1, Wilder) from the ACTUAL fill
  price (not the signal candle's close) -- lot sizing then derives from
  that actual SL distance, so rounding (lot-step floor) can only ever
  round risk DOWN, never above the 25 USD budget.
- No fixed TP.
- Exit: close long when `H1 close[t] < min(low[t-10..t-1])` (10 prior closed
  H1 bars, excluding t); close short when `H1 close[t] > max(high[t-10..t-1])`.
  Checked on every newly-closed H1 candle while a position from this engine
  is open.
- Execution at the next M1 open (both entry and this discretionary exit) --
  identical fill-timing convention to S2's entries.
- Initial SL is always live (checked intrabar every M1 bar, same
  `simulate_exit` mechanism as S1/S2/S3) from the moment of entry.
- No pyramiding, no trailing-stop adjustment, no auto-reverse on the exit
  signal (the exit just flattens; a new position only opens on a
  subsequent, independently-generated entry signal), no re-entry from the
  same H1 bar that generated the entry signal that is currently open.
- Parameters: Donchian entry window 20, exit window 10, ATR period 14
  (Wilder), SL multiple 2.0 -- all taken directly from the task's own
  specification text, not fitted.

### S7 -- M30 false-breakout-and-return (20-closed-candle range)
- Timeframe: M30. Before signal candle `t`: `U20 = max(high of the prior 20
  CLOSED M30 candles)`, `L20 = min(low of the prior 20 CLOSED M30 candles)`,
  `M = (U20+L20)/2`.
- SELL signal if `high[t] > U20` AND `L20 < close[t] < U20` (breaks the
  upper boundary intrabar, closes back inside the range).
- BUY signal if `low[t] < L20` AND `L20 < close[t] < U20` (breaks the lower
  boundary intrabar, closes back inside the range).
- If candle `t` breaches BOTH boundaries: no trade (ambiguous, explicitly
  excluded).
- Equal-to-boundary (`high[t] == U20` etc.) is NOT a breakout -- strict `>`/`<`
  only, per the task's explicit instruction.
- SL: SELL SL = `high[t] + 0.1 x ATR14(M30, Wilder)`; BUY SL = `low[t] - 0.1
  x ATR14(M30, Wilder)`. TP fixed at `M` for both directions.
- Bid/Ask convention (documented once here, applied consistently): all of
  `U20/L20/M/high[t]/low[t]/close[t]` above are read from the Bid-only M30
  OHLC exactly as stored. The SL/TP levels computed from them are then
  interpreted per direction the same way every other engine in this project
  already does at the order_exec layer -- SELL positions transact and are
  monitored against Ask, BUY positions against Bid (`order_exec.py`'s
  existing `_check_bar`) -- i.e. the signal-detection arithmetic runs on Bid
  prices throughout (matching how U20/L20 were built from Bid OHLC), and
  only the fill/exit-monitoring step re-expresses SL/TP against the side the
  position actually trades on, exactly like S1-S6. This is a stress
  assumption about which side's data defines the range, not a claim about
  real order-book liquidity at that level.
- Before sending the order: confirm TP is on the profit side and SL on the
  loss side of the ACTUAL fill price (post spread/slippage); if not (a
  scenario's wider spread can push the fill past `M` or past the SL already),
  skip the trade rather than send an inverted or zero-distance order.
- Timeout: if neither SL nor TP is hit, close after 8 full M30 candles have
  closed since entry (the first M30 candle counted is the first one that
  BEGINS after entry), at the next executable open.
- No SL widening, no adding to the position, no re-entry on the same M30
  candle's signal.
- Explicitly labeled a hypothesis test of "false breakout reverts," not
  evidence of real order-book liquidity or stop-hunting behaviour -- the
  cited MQL5 Donchian article and the WH SelfInvest "Turtle Soup" piece are
  inspiration only; this 20-bar M30 version differs from the WH SelfInvest
  parameters and their published win-rate is not treated as validation of
  this version.

### S8 -- RSI(2) M30 pullback with H1 EMA200 trend filter
- M30 `RSI2` computed from Bid close, Wilder-smoothed average gain/loss
  (seed: first 2 bars' raw up/down moves, then Wilder recursive smoothing
  exactly like the existing `WilderAtr` pattern in `strategy_ema_cross.py`,
  applied to gains/losses instead of true range). Edge cases fixed up front:
  a zero-movement bar contributes 0 to both the gain and loss sums (never
  divides by zero); if the smoothed average loss is exactly 0, RSI is
  defined as 100 (not NaN/undefined); if the smoothed average gain is
  exactly 0 and loss is also 0 (only possible pre-warmup or on a fully flat
  window), RSI is defined as 50 (neutral) rather than raising. Warm-up: RSI2
  is not considered ready (no signal possible) until the Wilder average has
  seen at least `period+1=3` closed M30 bars, mirroring the existing
  `WilderAtr.ready` convention.
- H1 filter: the last H1 candle FULLY CLOSED as of the M30 signal candle's
  own close time (i.e. `h1_candle.open_time_utc + 1h <= m30_signal_close_time`),
  and its EMA200 (same `Ema` class already used for S2, seeded the same
  simple-average way).
- BUY if `RSI2[t] < 5` AND `RSI2[t-1] >= 5` AND `H1 close > H1 EMA200`.
  SELL if `RSI2[t] > 95` AND `RSI2[t-1] <= 95` AND `H1 close < H1 EMA200`.
  (0/100 edge values are valid RSI2 outputs per the formula above and
  compare normally against the 5/95 thresholds -- no special-casing needed
  beyond the divide-by-zero fixes already listed.)
- SL = 1.5 x ATR14(M30, Wilder) from the actual fill price. No fixed TP.
- Exit (checked starting with the first M30 candle that closes AFTER entry,
  earliest of the three wins):
  1. `M30 close` crosses back through `SMA5` against the position (long:
     `close < SMA5`; short: `close > SMA5`) -- SMA5 seeded once 5 closed M30
     bars are available, no signal considered before that.
  2. 10 full M30 candles have closed since entry.
  3. A CLOSED H1 candle's close breaches EMA200 against the position (long:
     `H1 close < H1 EMA200`; short: `H1 close > H1 EMA200`).
  Execution at the next M1 open, same convention as every other engine here.
- No reverse on exit. Re-entry needs a fresh RSI2 threshold crossing (the
  `RSI2[t-1]` comparison above already prevents re-firing on consecutive
  bars that are all `<5` or all `>95` without a crossing back through the
  threshold first).
- Explicitly labeled an untested adaptation: the cited MQL5 RSI2
  mean-reversion article was tested on the US500 CFD, not forex, and the
  Moskowitz/Ooi/Pedersen time-series-momentum paper is futures/multi-month
  horizon evidence being applied here, as a hypothesis only, to H1/M30
  forex.

## 3. Cost scenarios -- C1/C2/C3, all three run for all 8 variants

| | EURUSD spread | GBPUSD spread | Adverse slippage |
|---|---|---|---|
| C1 (base) | 1.0 pip (0.00010) | 1.5 pip (0.00015) | 0.0 |
| C2 (stress) | 2.0 pip (0.00020) | 3.0 pip (0.00030) | 0.5 pip (0.00005) per market/stop fill |
| C3 (stronger stress) | 3.0 pip (0.00030) | 4.5 pip (0.00045) | 1.0 pip (0.00010) per market/stop fill |

- Commission: 5.00 USD per round-turn lot in ALL three scenarios (confirmed
  value, not varied) -- deducted once, at the closing leg, exactly as
  `order_exec._finalize` already does; never double-deducted against both
  legs.
- "Per market/stop fill" = every ENTRY fill (all are market fills in this
  project) and every SL-triggered exit (including a gapped SL), applied
  ADVERSE to the position (worse for the account) at that fill. TP fills
  and time/discretionary-exit fills (S6's Donchian-cross exit, S7's 8-bar
  timeout, S8's SMA5/EMA200/10-bar exit) are NOT slippage-adjusted -- they
  are modeled as executable at the bar's open/level directly, consistent
  with how this project has always treated a non-stop exit. This asymmetry
  (only adverse fills get slippage) is itself the stress assumption, stated
  explicitly rather than silently applied.
- C1's spread numbers are unchanged from the values already hardcoded in
  `config/config.example.json` (`spread_points_hypothetical`); C2/C3 are new
  scenario configs the runner builds, not edits to the shared example
  config.
- Swap: included in all three scenarios using the existing
  `_swap_usd_for_one_night` model (current confirmed swap-points rates
  applied for the whole historical period -- an approximation, since a rate
  snapshot is being applied retroactively). The run report states exactly
  how many trades/how much total USD this affects (count of overnight holds
  and their summed swap USD) for every S/C combination that holds anything
  overnight. Any swap-sensitive result (a candidate whose sign flips once
  swap is included, or whose total swap USD exceeds a material fraction of
  its net P/L) is additionally re-tested against an alternative rollover
  assumption (swap applied at 21:00 UTC / 23:00 UTC broker-local close
  convention instead of the Prague-FTMO-day boundary already used) as a
  named sensitivity test, reported separately, never silently substituted
  for the primary result.
- Recomputing lots per scenario: sizing already derives from the ACTUAL
  transacted entry price (`fill_bar.open +/- spread`, extended in this
  round to also include the scenario's slippage on entry fills -- see
  section 4), so a wider C2/C3 spread+slippage mechanically widens the
  realized SL distance and therefore changes the sized lot count through
  the existing `lots_for_risk` call, with no separate "reserve" line item
  needed. The per-S-per-C results table reports the realized lot size(s)
  actually used so this effect is visible, not just asserted.
- A scenario's total-working-stop, once triggered, halts that (S,C) run for
  the remainder of the sample -- never cancelled or reset to "finish" the
  equity curve. Crossing a risk floor is evaluated using the same
  intrabar-aware bar-by-bar walk already used for SL/TP (not just at bar
  close), with the same explicit caveat as always: M1 OHLC has no true
  tick path, so exact tick-level floor-crossing certification is impossible
  and is not claimed.
- Leverage/margin: not modeled (no margin-call/stop-out simulation exists
  in this project for any variant) -- explicitly out of scope here too, and
  flagged again in the results doc as something that must be checked
  against real account data before any MT4 run, per every prior round's
  docs/UNKNOWNS.md.

## 4. Implementation architecture (fixed before coding, so no exploratory API drift)

- S4/S5: a new `on_opposite_signal: Literal["skip", "close_only",
  "close_and_reverse"]` parameter on `simulator_ema_cross.run_h1_signal_simulation`.
  `"skip"` reproduces S2's current behaviour byte-for-byte (regression
  tested against the already-committed S2 numbers before any new scenario
  is run).
- S6: `EmaCrossEngine`-shaped entry engine (new `DonchianAtrEngine` in a new
  `strategy_donchian.py`) plus an optional duck-typed
  `check_exit(candle, position) -> bool` hook the runner calls once per
  newly-closed H1 candle for any symbol with an open position from this
  run; closing at the next M1 open exactly like an entry fill. TP-less
  positions are represented with `tp=None` handled explicitly through
  `order_exec` (never a fabricated huge/sentinel TP price).
- S7/S8: new `strategy_false_breakout_m30.py` / `strategy_rsi2_pullback_m30.py`
  engines and a new `simulator_m30_signal.py` runner -- kept SEPARATE from
  `simulator_ema_cross.py` rather than forcing M30 timeframe, time-boxed
  exits, and (for S8) a secondary H1 filter feed through the H1-only runner,
  for the same reason `simulator_ema_cross.py`'s own docstring gives for not
  merging into `simulator.py`: forcing unlike shapes through one interface
  would obscure all of them. The account-wide risk engine
  (`account_risk.py`/`risk_state.py`) and order-execution primitives
  (`order_exec.py`) are reused as-is, not reimplemented.
- Slippage: a new `slippage_price` argument threaded through
  `open_position`/`simulate_exit`/`force_close` (or an equivalent
  scenario-level wrapper), applied adverse-only on entry and SL-triggered
  fills as defined in section 3, added in `order_exec.py` behind a default
  of `0.0` so every existing S1/S2/S3 call site is unaffected unless a
  scenario explicitly passes a non-zero value.
- One reproducible entry point: `scripts/run_experiment_2026-09-18.py
  --variant {S1..S8} --scenario {C1,C2,C3}` (or `--all` for all 24), writing
  per-run `trades.csv`, `equity.csv`, `signals.csv` (accepted AND rejected,
  with reasons), and a machine-readable `summary.json` under
  `reports/run_0XX_<variant>_<scenario>/`, plus the run's config, code
  version (git SHA), and a run ID, matching the existing report folder
  convention.

## Plan hash

SHA256 of everything ABOVE this section (sections 1-4 plus the title/intro),
i.e. the parameters/architecture actually being committed to before any
S4-S8 code was written. Self-referential hashing (a hash of a file
including its own hash) is not meaningful, so this is scoped to exclude
this section itself; reproduce with:

```
sed '/^## Plan hash/,$d' docs/EXPERIMENT_PLAN_2026-09-18.md | sha256sum
```

```
97609bf8ed9418c857621aba9bb884317eafc4c4a4a4485324f15baeb6a6c3fb
```
