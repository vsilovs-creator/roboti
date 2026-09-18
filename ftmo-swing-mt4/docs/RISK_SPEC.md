# Risk specification (implemented + tested)

Source of truth: `python/ftmo_sim/account_risk.py`, `risk_state.py`,
`symbol_spec.py`. The MQL4 mirrors are in `mql4/Include/FTMO/AccountRisk.mqh`
and `Persistence.mqh` (NOT_RUN, see `README.md`).

## Floors (account currency, USD; `I = 10000`, `B0` = balance at 00:00 Europe/Prague)

| Floor | Formula |
|---|---|
| FTMO daily equity floor (reference only, looser than the robot's) | `B0 - 500` |
| Robot daily working floor | `B0 - 300` |
| FTMO static total equity floor (reference) | `9000` |
| Robot static total working floor | `9200` |
| Applicable robot floor (tighter of the two, used for the pre-trade projection) | `max(B0 - 300, 9200)` |

**Both floors are evaluated directly and independently** against equity
(`risk_state.RiskState.evaluate`), not only via the `max()` above:

- `equity <= (B0 - 300)` -> `daily_stop_active = True` (cleared automatically
  on the next correctly-reconstructed FTMO day, never mid-day).
- `equity <= 9200` -> `total_stop_active = True`, **sticky**: only cleared by
  an explicit manual review (`clear_total_stop_manually`), never by a
  restart or a day rollover.

This dual, independent check matters early in a challenge: at `B0 = 9400`,
the daily floor alone is `9100`, but the static total floor (`9200`) must
still bind first -- an account must not be allowed to trade down to `9100`
using the "spare" 100 USD the daily formula alone would suggest.

## Pre-trade worst-case projected equity

```
projected = equity
            - sum(remaining_risk_to_SL for every OTHER open position, account-wide)
            - pending_worst_case
            - new_order_risk
            - unaccounted_costs
            - execution_buffer
allowed = projected > applicable_floor
```

`remaining_risk_to_SL` is the move from the position's **current
mark-to-market price** to its SL -- never its full original risk, which
would double-count the portion already reflected in equity via floating
P/L. A foreign position with no SL contributes unbounded risk and blocks
new entries outright.

## Position sizing

`lots = floor_to_lot_step(risk_usd / (sl_distance * contract_size))`,
clamped to `[0, max_lot]`; `0` (skip the trade) if even the minimum lot
would exceed the risk budget. `sl_distance` is computed from the **actual
transacted price** (Ask for BUY, Bid for SELL), not the raw quote -- an
earlier draft of the simulator used the raw bid price here and silently
understated risk by the spread on every trade (worst on the tightest SLs);
`python/tests/test_symbol_spec.py` and the simulator's inline comment both
call this out.

## Correlated-group cap

EURUSD and GBPUSD ideas in the **same USD direction** (both effectively
long-USD or both short-USD) share one `correlated_group_max_risk_usd` cap
(default 50 USD); opposite-direction ideas in the same pair are not summed
together. A separate, always-checked `max_concurrent_risk_usd` (default 100
USD) caps total open risk regardless of grouping.

## Mapping to spec section 9's 11 mandated test scenarios

| # | Scenario | Test |
|---|---|---|
| 1 | B0=10000, floors 9700/9200, triggers at 9700 | `test_account_risk.py::test_scenario_1_b0_10000` |
| 2 | B0=9400, static 9200 wins over daily 9100 | `test_scenario_2_b0_9400` |
| 3 | B0=10500, daily 10200 (not trailing 9700) | `test_scenario_3_b0_10500` |
| 4 | equity=9730, +40 USD rejected, no double count | `test_scenario_4_no_double_counting_floating_loss`, `test_scenario_4b_remaining_risk_not_full_original_risk` |
| 5 | pre-midnight balance=10200, equity=9850 -> next-day floor 9900 | `test_scenario_5_next_day_floor_forces_early_action` |
| 6 | commission/swap/foreign position/pending activation/correlated pairs | `test_account_risk.py::test_correlated_group_cap_*`, `test_portfolio_cap_blocks_regardless_of_grouping`, `order_exec` commission test; commission is now CONFIRMED at 5 USD/lot round-turn (see `docs/UNKNOWNS.md`) |
| 7 | lot rounding, min lot > budget, invalid tick value, freeze level, SL refusal | `test_symbol_spec.py` (Python); `OpenMarketOrderWithRetry`'s post-fill SL/stops-level re-check (MQL4, NOT_RUN) |
| 8 | restart after daily/total stop, 2nd instance, incomplete history | `test_risk_state.py` (all 5 tests) |
| 9 | DST transitions, alt server-DST hypothesis, weekend with no midnight tick | `test_time_utils.py` |
| 10 | OrderSend timeout/partial close/stale price/reconnect | MQL4-only (`OrderExec.mqh` retry/idempotency logic) -- **NOT_RUN**, no MT4 available; see `README.md` for the manual test harness this needs |
| 11 | future-data unavailability, single-candle SL/TP collision, incomplete H1, EMA warmup, 11:00 cutoff | `test_signals.py` (warmup/cutoff/one-per-day), `test_order_exec.py` (same-bar collision) |

Test 10 is the one scenario this environment could not execute at all (no
MT4/MetaEditor); everything else has an independently-computed expected
value and a passing test (`cd python && python3 -m pytest -q`).
