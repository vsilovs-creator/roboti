"""Portfolio simulator for any H1-signal strategy shaped like
strategy_ema_cross.EmaCrossSignal (symbol/direction/signal_close_time_utc/
sl_price/tp_price) -- structurally the same account-wide risk engine and
order-execution model as simulator.py (the London breakout baseline), just
swapping the signal source and allowing positions to hold across the 16:00
London boundary (see order_exec.simulate_exit's enforce_session_close).

Both strategy_ema_cross.EmaCrossEngine and strategy_bb_reversion.BbReversionEngine
plug into this via `engine_factory`; that is the whole point of sharing this
module between them instead of forking it a second time.

Kept as a separate module rather than folding into simulator.py because the
London strategy differs in shape (M5+H1, session windows, one-trade-per-
London-day rule, correlated-group direction bucketing) -- forcing everything
through one generic interface would have obscured all three rather than
clarified any of them.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta
from typing import Callable

from .account_risk import OpenPositionRiskView, new_entry_allowed, new_idea_within_risk_caps
from .bars import RichCandle, resample
from .config import RunConfig
from .order_exec import ClosedTrade, Position, force_close, open_position, simulate_exit, spread_price
from .risk_state import RiskState
from .strategy_ema_cross import EmaCrossEngine, EmaCrossSignal
from .symbol_spec import SymbolSpec, lots_for_risk, risk_usd_for_lots
from .time_utils import ftmo_trading_day


def _swap_usd_for_one_night(position: Position, spec: SymbolSpec, night_starting_weekday: int) -> float:
    """USD swap cost/credit for one night an open position is held, per the
    confirmed instrument spec ('swap type: in points'). Approximation, not a
    confirmed model: real MT4 posts swap at a specific server-local rollover
    hour (unconfirmed here, see docs/UNKNOWNS.md); this applies it once per
    FTMO-day (Prague) rollover instead, tripled on the night starting on
    spec.triple_swap_weekday (Wednesday, per the confirmed instrument spec)
    -- close enough to be a real cost rather than the previously-silent
    zero, but not claimed to match the exact broker timing."""
    points = spec.swap_long_points if position.direction == "BUY" else spec.swap_short_points
    usd_per_lot_per_night = points * spec.point_size * spec.contract_size
    multiplier = 3.0 if night_starting_weekday == spec.triple_swap_weekday else 1.0
    return usd_per_lot_per_night * position.lots * multiplier


def _direction_bucket(direction: str) -> str:
    # BUY EURUSD/GBPUSD = long the pair = short USD; SELL = long USD.
    # Same convention as simulator.py's private helper of the same name --
    # duplicated rather than imported to keep this module independent
    # (see the module docstring for why it isn't folded into simulator.py).
    return "LONG_USD" if direction == "SELL" else "SHORT_USD"


@dataclass
class SkippedEmaSignal:
    signal: EmaCrossSignal
    reason: str


@dataclass
class EmaCrossResult:
    closed_trades: list[ClosedTrade] = field(default_factory=list)
    skipped_signals: list[SkippedEmaSignal] = field(default_factory=list)
    equity_curve: list[tuple] = field(default_factory=list)
    risk_stop_events: list[tuple] = field(default_factory=list)
    swap_ledger: list[tuple] = field(default_factory=list)  # (utc_time, symbol, direction, lots, swap_usd)
    final_balance: float = 0.0
    # Positions still open when the sample ran out -- final_balance is
    # REALIZED balance only and does not include these; see final_equity.
    open_positions_at_end: dict = field(default_factory=dict)
    final_equity: float = 0.0

    @property
    def total_swap_usd(self) -> float:
        return sum(entry[4] for entry in self.swap_ledger)


def run_h1_signal_simulation(
    config: RunConfig,
    m1_by_symbol: dict[str, list[RichCandle]],
    engine_factory: Callable[[str], object] = EmaCrossEngine,
    account_number: int = 900000002,
    server_name: str = "OFFLINE-SIM-H1",
    enforce_session_close: bool = False,
    on_opposite_signal: str = "skip",
    slippage_price: float = 0.0,
) -> EmaCrossResult:
    """`on_opposite_signal` (docs/EXPERIMENT_PLAN_2026-09-18.md section 4):
    what to do when a new signal arrives for a symbol that already has an
    open position (necessarily the OPPOSITE direction -- a same-direction
    re-cross cannot happen without an opposite cross firing first, since
    every engine here only emits a signal on an actual crossing/threshold
    event). "skip" (S2/S3's existing behaviour, UNCHANGED code path below,
    not just unchanged output) leaves the open position alone and drops the
    new signal. "close_only" (S4) closes the open position at this signal's
    own fill and consumes the signal -- no new position opens from that same
    event. "close_and_reverse" (S5) does the same close, then re-runs the
    exact same entry checks (floors/caps/costs, sized fresh at
    config.risk_per_idea_usd, no relation to the just-closed trade's size or
    result) to possibly open one new idea in the new signal's direction.

    `slippage_price` (>=0.0) is a scenario's adverse execution slippage,
    threaded through to every fill in this function (entries, SL-triggered
    exits, forced/risk-stop closes, and this opposite-signal close) -- see
    docs/EXPERIMENT_PLAN_2026-09-18.md section 3. Defaults to 0.0 (C1-shaped,
    matching every call site before this parameter existed)."""
    if on_opposite_signal not in ("skip", "close_only", "close_and_reverse"):
        raise ValueError(f"unknown on_opposite_signal mode: {on_opposite_signal!r}")
    symbols = list(m1_by_symbol.keys())
    h1_by_symbol = {s: resample(m1_by_symbol[s], 60) for s in symbols}
    engines = {s: engine_factory(s) for s in symbols}

    all_signals: list[EmaCrossSignal] = []
    # (symbol, exit_flags_close_time_utc, DonchianExitFlags) -- S6's
    # discretionary exit, opportunistically read off `engine.last_exit_flags`
    # right after on_h1_candle() for engines that set it (duck-typed: every
    # existing engine that never sets this attribute simply contributes
    # nothing here, unaffected).
    all_exit_checks: list[tuple] = []
    for s in symbols:
        for candle in h1_by_symbol[s]:
            sig = engines[s].on_h1_candle(candle)
            if sig is not None:
                all_signals.append(sig)
            exit_flags = getattr(engines[s], "last_exit_flags", None)
            if exit_flags is not None:
                all_exit_checks.append((s, candle.open_time_utc, exit_flags))
    all_signals.sort(key=lambda e: e.signal_close_time_utc)
    all_exit_checks.sort(key=lambda e: e[1])

    m1_index = {s: m1_by_symbol[s] for s in symbols}

    def first_bar_at_or_after(symbol: str, t) -> int | None:
        bars = m1_index[symbol]
        lo, hi = 0, len(bars)
        while lo < hi:
            mid = (lo + hi) // 2
            if bars[mid].open_time_utc < t:
                lo = mid + 1
            else:
                hi = mid
        return lo if lo < len(bars) else None

    all_times = sorted({c.open_time_utc for s in symbols for c in m1_by_symbol[s]})
    bar_by_symbol_by_time = {s: {c.open_time_utc: c for c in m1_by_symbol[s]} for s in symbols}
    H1 = timedelta(hours=1)

    result = EmaCrossResult()
    risk_state = RiskState(account_number=account_number, server_name=server_name, config_version="sim-h1")
    balance = config.initial_balance
    open_positions: dict[str, Position] = {}
    last_seen: dict[str, RichCandle] = {}
    idea_counter = 0
    signal_ptr = 0
    exit_check_ptr = 0
    spreads = {s: spread_price(s, config.symbols[s], config.spread_points_hypothetical) for s in symbols}

    for t in all_times:
        for s in symbols:
            bar = bar_by_symbol_by_time[s].get(t)
            if bar is not None:
                last_seen[s] = bar

        today = ftmo_trading_day(t)
        rolled = risk_state.rollover_if_needed(today, balance)
        if rolled:
            result.risk_stop_events.append((t, "ROLLOVER", f"balance_at_midnight={balance:.2f}"))
            night_starting_weekday = (today - timedelta(days=1)).weekday()
            for s, pos in open_positions.items():
                swap_usd = _swap_usd_for_one_night(pos, config.symbols[s], night_starting_weekday)
                if swap_usd != 0.0:
                    balance += swap_usd
                    result.swap_ledger.append((t, s, pos.direction, pos.lots, swap_usd))

        for s in list(open_positions.keys()):
            bar = bar_by_symbol_by_time[s].get(t)
            if bar is None:
                continue
            pos = open_positions[s]
            trade = simulate_exit(
                pos, [bar], config.symbols[s], config.raw["account"]["currency"],
                spreads[s], config.commission_round_turn_usd_per_lot,
                enforce_session_close=enforce_session_close, slippage_price=slippage_price,
            )
            if trade is not None:
                balance += trade.net_pnl_usd
                result.closed_trades.append(trade)
                del open_positions[s]

        def _floating_pnl() -> float:
            floating = 0.0
            for s, pos in open_positions.items():
                bar = last_seen.get(s)
                if bar is None:
                    continue
                mark_bid = bar.close
                mark_ask = mark_bid + spreads[s]
                price = mark_bid if pos.direction == "BUY" else mark_ask
                sign = 1 if pos.direction == "BUY" else -1
                floating += sign * (price - pos.entry_price) * pos.lots * config.symbols[s].contract_size
            return floating

        # This is the PRE-entry equity: used to gate this timestamp's new
        # entries and to evaluate the risk stop, using only what's already
        # known before any of this timestamp's own entries/closures happen
        # (spec: decide entries from already-known events only). It is NOT
        # the recorded equity-curve point for time t -- see "settled" below,
        # computed once this timestamp's entries and same-bar closures have
        # actually happened, which is the correct point to report/re-use as
        # final_equity. FIXED 2026-09-18 (follow-up audit): the equity-curve
        # point used to be recorded HERE, before that timestamp's own
        # entries/closures, so a trade opened and closed within the very
        # last timestamp of the run updated final_balance but not the
        # already-recorded last equity-curve point -- final_equity could
        # come back stale (e.g. still the untouched initial balance) while
        # final_balance correctly reflected the loss.
        equity = balance + _floating_pnl()

        was_stopped = risk_state.stop_active()
        risk_state.evaluate(equity, config.ftmo_limits)
        if risk_state.stop_active() and not was_stopped:
            reason = "TOTAL_STOP" if risk_state.total_stop_active else "DAILY_STOP"
            result.risk_stop_events.append((t, reason, f"equity={equity:.2f}"))
            for s in list(open_positions.keys()):
                bar = last_seen.get(s)
                if bar is None:
                    continue
                fill = bar.close if open_positions[s].direction == "BUY" else bar.close + spreads[s]
                trade = force_close(
                    open_positions[s], fill, t, "RISK_STOP",
                    config.symbols[s], config.raw["account"]["currency"],
                    config.commission_round_turn_usd_per_lot, slippage_price=slippage_price,
                )
                balance += trade.net_pnl_usd
                result.closed_trades.append(trade)
                del open_positions[s]

        # S6's discretionary exit (Donchian 10-bar-extreme crossing): a
        # "prior-candle signal exit" per docs/EXPERIMENT_PLAN_2026-09-18.md
        # section 4's causality ordering -- decided from CLOSED H1 bars
        # strictly before this instant, so it is processed here, BEFORE
        # this timestamp's entries, exactly like the risk-stop block above.
        # Only acts if the currently open position's direction matches the
        # flag (a flag with no matching open position is simply irrelevant,
        # not logged as a skip -- it was never a signal to act on, unlike an
        # entry). Fill uses the bar's OPEN (known at this instant), never
        # its close, and is NOT slippage-adjusted (a discretionary exit is
        # neither a market entry nor an SL-triggered stop-out, per section 3).
        while exit_check_ptr < len(all_exit_checks) and all_exit_checks[exit_check_ptr][1] + H1 <= t:
            exit_symbol, exit_close_time, exit_flags = all_exit_checks[exit_check_ptr]
            exit_check_ptr += 1
            pos = open_positions.get(exit_symbol)
            if pos is None:
                continue
            should_close = (
                (pos.direction == "BUY" and exit_flags.close_long)
                or (pos.direction == "SELL" and exit_flags.close_short)
            )
            if not should_close:
                continue
            fill_idx = first_bar_at_or_after(exit_symbol, exit_close_time + H1)
            if fill_idx is None or m1_index[exit_symbol][fill_idx].open_time_utc != t:
                continue
            fill_bar = m1_index[exit_symbol][fill_idx]
            exit_price = fill_bar.open if pos.direction == "BUY" else fill_bar.open + spreads[exit_symbol]
            trade = force_close(
                pos, exit_price, fill_bar.open_time_utc, "DISCRETIONARY_EXIT",
                config.symbols[exit_symbol], config.raw["account"]["currency"],
                config.commission_round_turn_usd_per_lot, slippage_price=0.0,
            )
            balance += trade.net_pnl_usd
            result.closed_trades.append(trade)
            del open_positions[exit_symbol]

        # Positions opened THIS timestamp -- checked against their own entry
        # bar's high/low immediately below, before the loop moves to the
        # next timestamp. Without this, a position opened at this bar's
        # open was never tested against this same bar's own intrabar move:
        # the exit-processing block above already ran (before this position
        # existed) and the next exit check would only see the FOLLOWING
        # bar, silently skipping this bar's own SL/TP and turning a same-bar
        # stop into a much worse "gap" exit on the next bar's open instead.
        newly_opened: dict[str, RichCandle] = {}

        while signal_ptr < len(all_signals) and all_signals[signal_ptr].signal_close_time_utc + H1 <= t:
            sig = all_signals[signal_ptr]
            signal_ptr += 1

            if sig.symbol in open_positions and on_opposite_signal == "skip":
                # S2/S3's ORIGINAL, UNCHANGED code path -- deliberately not
                # touched by the close_only/close_and_reverse branch below,
                # so this mode's output is byte-for-byte what it always was
                # (see docs/EXPERIMENT_PLAN_2026-09-18.md section 4).
                result.skipped_signals.append(SkippedEmaSignal(sig, "SYMBOL_ALREADY_HAS_OPEN_POSITION"))
                continue
            if risk_state.stop_active() or not risk_state.history_reconciled:
                result.skipped_signals.append(SkippedEmaSignal(sig, "RISK_STOP_ACTIVE_OR_UNRECONCILED"))
                continue
            fill_idx = first_bar_at_or_after(sig.symbol, sig.signal_close_time_utc + H1)
            if fill_idx is None or m1_index[sig.symbol][fill_idx].open_time_utc != t:
                continue
            fill_bar = m1_index[sig.symbol][fill_idx]
            spec = config.symbols[sig.symbol]

            if sig.symbol in open_positions:
                # on_opposite_signal in ("close_only", "close_and_reverse"):
                # this signal is necessarily opposite-direction to the open
                # position (see the function docstring) -- close it at THIS
                # signal's own fill bar/price and consume the signal.
                existing = open_positions[sig.symbol]
                exit_price = fill_bar.open if existing.direction == "BUY" else fill_bar.open + spreads[sig.symbol]
                close_trade = force_close(
                    existing, exit_price, fill_bar.open_time_utc, "OPPOSITE_SIGNAL_EXIT",
                    spec, config.raw["account"]["currency"], config.commission_round_turn_usd_per_lot,
                    slippage_price=slippage_price,
                )
                balance += close_trade.net_pnl_usd
                result.closed_trades.append(close_trade)
                del open_positions[sig.symbol]
                if on_opposite_signal == "close_only":
                    result.skipped_signals.append(SkippedEmaSignal(sig, "OPPOSITE_SIGNAL_CONSUMED_CLOSE_ONLY"))
                    continue
                # close_and_reverse: fall through to the normal entry logic
                # below using this SAME signal, exactly as if it had arrived
                # while flat -- same sizing call, same floor/cap checks, no
                # relation whatsoever to the trade just closed above. Per
                # the plan, equity is re-derived HERE (this closure realized
                # a known P/L at a known instant -- fill_bar.open, not a
                # bar-close-derived mark, so this is not the section-4.1
                # causality leak) so the reverse-entry check below sees the
                # just-closed trade's effect, not the stale pre-close value.
                equity = balance + _floating_pnl()

            transacted_entry = (
                fill_bar.open + spreads[sig.symbol] + slippage_price if sig.direction == "BUY"
                else fill_bar.open - slippage_price
            )
            if sig.sl_price is not None:
                sl_price = sig.sl_price
            else:
                # S6 (Donchian): SL is anchored to the ACTUAL fill price,
                # not the signal candle's close -- see
                # docs/EXPERIMENT_PLAN_2026-09-18.md section 2 and
                # strategy_donchian.py's module docstring.
                sl_price = (
                    transacted_entry - sig.sl_distance_price if sig.direction == "BUY"
                    else transacted_entry + sig.sl_distance_price
                )
            tp_price = sig.tp_price  # may be None (no fixed TP) -- S6
            sl_distance = (transacted_entry - sl_price) if sig.direction == "BUY" else (sl_price - transacted_entry)
            if sl_distance <= 0:
                result.skipped_signals.append(SkippedEmaSignal(sig, "EXECUTION_PRICE_INVALIDATED_SL"))
                continue
            commission_per_lot = config.commission_round_turn_usd_per_lot or 0.0
            lots = lots_for_risk(
                config.risk_per_idea_usd, sl_distance, spec, config.raw["account"]["currency"],
                extra_cost_usd_per_lot=commission_per_lot,
            )
            if lots == 0.0:
                result.skipped_signals.append(SkippedEmaSignal(sig, "MIN_LOT_EXCEEDS_RISK_BUDGET"))
                continue
            actual_risk = risk_usd_for_lots(
                lots, sl_distance, spec, config.raw["account"]["currency"],
                extra_cost_usd_per_lot=commission_per_lot,
            )

            open_risk_views = []
            open_risk_by_idea: dict[str, float] = {}
            idea_symbol: dict[str, str] = {}
            idea_bucket: dict[str, str] = {}
            for other_symbol, pos in open_positions.items():
                bucket = _direction_bucket(pos.direction)
                if other_symbol in newly_opened:
                    # FIXED 2026-09-18 (follow-up audit): this position was
                    # opened THIS SAME timestamp, at this bar's open -- using
                    # this same bar's CLOSE (a value only known later within
                    # the bar) to mark it would leak intrabar/end-of-minute
                    # information into another symbol's entry decision at
                    # the identical instant. At the open, no move has
                    # happened yet, so its "remaining risk right now" is
                    # simply its full originally-sized risk.
                    remaining = pos.risk_usd_at_entry
                else:
                    bar = last_seen.get(other_symbol)
                    mark = bar.close if pos.direction == "BUY" else bar.close + spreads[other_symbol]
                    remaining = abs(mark - pos.sl) * pos.lots * config.symbols[other_symbol].contract_size
                open_risk_views.append(OpenPositionRiskView(other_symbol, remaining, bucket))
                open_risk_by_idea[other_symbol] = remaining
                idea_symbol[other_symbol] = other_symbol
                idea_bucket[other_symbol] = bucket

            floor = max(
                risk_state.balance_at_midnight - config.ftmo_limits.robot_daily_working_buffer_offset_usd,
                config.ftmo_limits.robot_total_working_floor_usd,
            )
            allowed = new_entry_allowed(
                equity, floor, open_risk_views, 0.0, actual_risk, 0.0, config.execution_buffer_usd,
            )
            if not allowed:
                result.skipped_signals.append(SkippedEmaSignal(sig, "PRE_TRADE_PROJECTED_EQUITY_BREACH"))
                continue
            if not new_idea_within_risk_caps(
                sig.symbol, _direction_bucket(sig.direction), actual_risk,
                open_risk_by_idea, idea_symbol, idea_bucket, config.correlation_limits,
            ):
                result.skipped_signals.append(SkippedEmaSignal(sig, "CORRELATED_OR_PORTFOLIO_RISK_CAP"))
                continue

            idea_counter += 1
            pos = open_position(
                f"ema-idea-{idea_counter}", sig.symbol, sig.direction, lots, fill_bar.open,
                sl_price, tp_price, fill_bar.open_time_utc, spreads[sig.symbol], actual_risk,
                slippage_price=slippage_price,
            )
            open_positions[sig.symbol] = pos
            newly_opened[sig.symbol] = fill_bar

        # Same-bar SL/TP check for anything just opened above (see comment
        # at the top of this timestamp's block).
        for s, fill_bar in newly_opened.items():
            pos = open_positions.get(s)
            if pos is None:
                continue
            trade = simulate_exit(
                pos, [fill_bar], config.symbols[s], config.raw["account"]["currency"],
                spreads[s], config.commission_round_turn_usd_per_lot,
                enforce_session_close=enforce_session_close, slippage_price=slippage_price,
            )
            if trade is not None:
                balance += trade.net_pnl_usd
                result.closed_trades.append(trade)
                del open_positions[s]

        # Settled equity: AFTER this timestamp's own entries and same-bar
        # closures, so the recorded point actually reflects everything that
        # happened at time t (see the long comment above `equity =` for why
        # the earlier, pre-entry value must not be the one recorded here).
        settled_equity = balance + _floating_pnl()
        result.equity_curve.append((t, settled_equity, balance))

    result.final_balance = balance
    result.open_positions_at_end = dict(open_positions)
    result.final_equity = result.equity_curve[-1][1] if result.equity_curve else balance
    return result


def run_ema_cross_simulation(
    config: RunConfig, m1_by_symbol: dict[str, list[RichCandle]],
    on_opposite_signal: str = "skip", slippage_price: float = 0.0,
) -> EmaCrossResult:
    """Runs the EMA(20/50) H1 crossover using config['strategies']['ema_cross_v1']
    -- the CHOSEN strategy going forward (2026-09-18, see config.example.json's
    `strategies.active`), rather than the strategy_ema_cross.py hardcoded
    defaults, so changing the config actually changes the run.

    `on_opposite_signal`/`slippage_price` default to S2's original
    behaviour (skip, no slippage); pass "close_only"/"close_and_reverse"
    for S4/S5 (same engine/config, only this mode differs) and a scenario's
    slippage for the C2/C3 cost comparison -- see
    docs/EXPERIMENT_PLAN_2026-09-18.md sections 2/3."""
    p = config.ema_cross_strategy
    engine_factory = lambda symbol: EmaCrossEngine(
        symbol,
        fast_period=p["fast_period_h1"],
        slow_period=p["slow_period_h1"],
        atr_period=p["atr_period_h1"],
        atr_sl_multiple=p["atr_sl_multiple"],
        tp_r_multiple=p["tp_r_multiple"],
    )
    return run_h1_signal_simulation(
        config, m1_by_symbol, engine_factory=engine_factory,
        enforce_session_close=p.get("enforce_session_close", False),
        on_opposite_signal=on_opposite_signal, slippage_price=slippage_price,
    )


def run_donchian_simulation(
    config: RunConfig, m1_by_symbol: dict[str, list[RichCandle]],
    slippage_price: float = 0.0,
) -> EmaCrossResult:
    """Runs S6 (Donchian H1 20/10 with an ATR stop) using
    config.raw['strategies']['donchian_v1'] -- see
    docs/EXPERIMENT_PLAN_2026-09-18.md section 2. No fixed TP, no
    on_opposite_signal mode of its own (an "opposite" entry signal while a
    position is open would only ever skip here -- the exit is entirely the
    separate discretionary 10-bar-extreme check, per spec "no auto-reverse
    on the exit signal")."""
    from .strategy_donchian import DonchianAtrEngine

    p = config.raw["strategies"]["donchian_v1"]
    engine_factory = lambda symbol: DonchianAtrEngine(
        symbol,
        entry_period=p["entry_period_h1"],
        exit_period=p["exit_period_h1"],
        atr_period=p["atr_period_h1"],
        atr_sl_multiple=p["atr_sl_multiple"],
    )
    return run_h1_signal_simulation(
        config, m1_by_symbol, engine_factory=engine_factory,
        enforce_session_close=False, on_opposite_signal="skip",
        slippage_price=slippage_price,
    )
