"""Portfolio simulator for M30-timeframe signal strategies (S7 false-breakout,
S8 RSI2 pullback -- docs/EXPERIMENT_PLAN_2026-09-18.md section 2), sharing
the account-wide risk engine and order-execution model with
simulator.py/simulator_ema_cross.py but NOT folded into
simulator_ema_cross.py's H1-only runner: the M30 fill cadence, the
fixed-candle-count timeout exit, and (for S8) a secondary H1 filter feed are
different enough in shape that forcing them through the H1 runner would
obscure both, per that module's own stated reasoning for staying separate
from simulator.py.

Signal shape: reuses strategy_ema_cross.EmaCrossSignal exactly as
simulator_ema_cross.py's engines do (symbol/direction/signal_close_time_utc/
sl_price/tp_price, with sl_price=None + sl_distance_price meaning "anchor SL
to the actual fill price", tp_price=None meaning "no fixed TP" -- both
already supported by order_exec.py's Position/`_check_bar`).

Discretionary exit: an engine MAY set `self.last_exit_flags` to a
DonchianExitFlags-shaped object (close_long/close_short booleans) after
on_m30_candle() -- read the same way
simulator_ema_cross.run_h1_signal_simulation reads S6's Donchian engine.
S7's engine never sets it (pure timeout exit); S8's does (SMA5/EMA200
invalidation).

Timeout exit: every position closes after `timeout_m30_candles` full M30
candles have closed since its OWN entry_time_utc (which is already
M30-boundary-aligned, since fills happen at signal_close_time_utc + M30),
at the next executable M1 open -- a pure function of entry time, computed
here directly rather than by the engine, and identical in mechanism for
S7 (8 candles) and S8 (10 candles).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta
from typing import Callable

from .account_risk import OpenPositionRiskView, new_entry_allowed, new_idea_within_risk_caps
from .bars import RichCandle, resample
from .config import RunConfig
from .order_exec import ClosedTrade, Position, force_close, open_position, resolve_gap_fill, simulate_exit, spread_price
from .risk_state import RiskState
from .simulator_ema_cross import _swap_usd_for_one_night, _direction_bucket
from .strategy_ema_cross import EmaCrossSignal
from .symbol_spec import SymbolSpec, lots_for_risk, risk_usd_for_lots
from .time_utils import ftmo_trading_day

M30 = timedelta(minutes=30)
H1 = timedelta(hours=1)


@dataclass
class SkippedM30Signal:
    signal: EmaCrossSignal
    reason: str


@dataclass
class M30SimulationResult:
    closed_trades: list[ClosedTrade] = field(default_factory=list)
    skipped_signals: list[SkippedM30Signal] = field(default_factory=list)
    equity_curve: list[tuple] = field(default_factory=list)
    risk_stop_events: list[tuple] = field(default_factory=list)
    swap_ledger: list[tuple] = field(default_factory=list)
    final_balance: float = 0.0
    open_positions_at_end: dict = field(default_factory=dict)
    final_equity: float = 0.0
    # ADDED 2026-09-18 (Codex F3): see the matching field on
    # simulator.SimulationResult.
    balance_at_midnight_by_day: dict = field(default_factory=dict)

    @property
    def total_swap_usd(self) -> float:
        return sum(entry[4] for entry in self.swap_ledger)


def run_m30_signal_simulation(
    config: RunConfig,
    m1_by_symbol: dict[str, list[RichCandle]],
    engine_factory: Callable[[str], object],
    timeout_m30_candles: int,
    account_number: int = 900000003,
    server_name: str = "OFFLINE-SIM-M30",
    slippage_price: float = 0.0,
) -> M30SimulationResult:
    symbols = list(m1_by_symbol.keys())
    m30_by_symbol = {s: resample(m1_by_symbol[s], 30) for s in symbols}
    engines = {s: engine_factory(s) for s in symbols}

    all_signals: list[EmaCrossSignal] = []
    # (symbol, decision_time_utc, exit_flags, source_candle_open_time_utc)
    # -- decision_time_utc is already the candle's OWN close time (M30 or
    # H1, whichever produced the flag), so the runner's processing loop
    # below needs no further per-entry offset; it just waits for
    # decision_time_utc <= t. source_candle_open_time_utc is kept
    # separately so the loop can enforce "only from the first M30 candle
    # CLOSED AFTER entry" (excluding a check event sourced from a candle
    # that began at-or-before the position's own entry instant).
    all_exit_checks: list[tuple] = []
    for s in symbols:
        # S8's secondary H1 trend filter (on_h1_candle, duck-typed --
        # S7's engine has no such method): merge H1 and M30 candles in
        # true time order, an H1 candle feeding the engine's filter state
        # only once ITS OWN close time has passed, exactly mirroring
        # simulator.py's _merge_signal_feed for the London breakout's H1
        # EMA filter + M5 signal candles. On an exact tie (an M30 boundary
        # that coincides with an H1 close), the H1 update is applied
        # FIRST, so "the last H1 candle fully closed as of this M30
        # candle's own close" already includes it.
        if hasattr(engines[s], "on_h1_candle"):
            h1_candles = resample(m1_by_symbol[s], 60)
            # Both sorted by their OWN close time (not open time) -- an
            # M30 candle's engine-processing instant is when IT closes,
            # which is what must be compared against an H1 candle's own
            # close time to get the merge order right. Sorting M30 by
            # open time instead would process each M30 candle one whole
            # M30 period too early relative to H1 closes that land
            # exactly on an M30 boundary.
            events = [(c.open_time_utc + H1, 0, "H1", c) for c in h1_candles]
            events += [(c.open_time_utc + M30, 1, "M30", c) for c in m30_by_symbol[s]]
            events.sort(key=lambda e: (e[0], e[1]))
            for _, _, kind, candle in events:
                if kind == "H1":
                    engines[s].on_h1_candle(candle)
                    # S8's third exit condition ("a CLOSED H1 candle's
                    # close breaches EMA200 against the position") is a
                    # pure function of H1 price/indicator state -- read on
                    # the SAME H1 cadence as it is computed, not delayed
                    # to the next M30 boundary.
                    h1_exit_flags = getattr(engines[s], "last_h1_exit_flags", None)
                    if h1_exit_flags is not None:
                        all_exit_checks.append((s, candle.open_time_utc + H1, h1_exit_flags, candle.open_time_utc))
                    continue
                sig = engines[s].on_m30_candle(candle)
                if sig is not None:
                    all_signals.append(sig)
                exit_flags = getattr(engines[s], "last_exit_flags", None)
                if exit_flags is not None:
                    all_exit_checks.append((s, candle.open_time_utc + M30, exit_flags, candle.open_time_utc))
        else:
            for candle in m30_by_symbol[s]:
                sig = engines[s].on_m30_candle(candle)
                if sig is not None:
                    all_signals.append(sig)
                exit_flags = getattr(engines[s], "last_exit_flags", None)
                if exit_flags is not None:
                    all_exit_checks.append((s, candle.open_time_utc + M30, exit_flags, candle.open_time_utc))
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

    result = M30SimulationResult()
    risk_state = RiskState(account_number=account_number, server_name=server_name, config_version="sim-m30")
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
            result.balance_at_midnight_by_day[today.isoformat()] = balance
            night_starting_weekday = (today - timedelta(days=1)).weekday()
            for s, pos in open_positions.items():
                swap_usd = _swap_usd_for_one_night(pos, config.symbols[s], night_starting_weekday)
                if swap_usd != 0.0:
                    balance += swap_usd
                    result.swap_ledger.append((t, s, pos.direction, pos.lots, swap_usd))

        # FIXED 2026-09-18 (Codex F2): the intrabar SL/TP check for
        # pre-existing positions used to run HERE, before this bar's
        # entries -- see the matching comment in simulator_ema_cross.py.
        # The PURE INTRABAR (high/low) part is deferred to a unified pass
        # after entries (below). A GAP-through of an already-open
        # position's SL/TP is knowable IMMEDIATELY at this bar's open --
        # resolved right here, before the risk-stop check, the
        # timeout-exit check, and the discretionary-exit check below
        # (FIXED 2026-09-18, Codex R1, follow-up-follow-up-follow-up
        # audit): a mechanical stop/limit-order fill must never be masked
        # by a timeout or discretionary exit firing first just because it
        # happened to be checked earlier in the tick's code -- see the
        # exact repro in docs/AUDIT_2026-09-18.md's newest section
        # (reproduced there against simulator_ema_cross.py, but the same
        # ordering risk applies to every discretionary/timeout exit path
        # in this module too).
        for s in list(open_positions.keys()):
            bar = bar_by_symbol_by_time[s].get(t)
            if bar is None:
                continue
            trade = resolve_gap_fill(
                open_positions[s], bar, config.symbols[s], config.raw["account"]["currency"],
                spreads[s], config.commission_round_turn_usd_per_lot, slippage_price=slippage_price,
            )
            if trade is not None:
                balance += trade.net_pnl_usd + trade.position.entry_commission_usd
                result.closed_trades.append(trade)
                del open_positions[s]

        def _mark_price(symbol: str, direction: str, use_close: bool) -> float | None:
            bar = last_seen.get(symbol)
            if bar is None:
                return None
            raw = bar.close if use_close else bar.open
            return raw if direction == "BUY" else raw + spreads[symbol]

        def _floating_pnl(use_close: bool) -> float:
            floating = 0.0
            for s, pos in open_positions.items():
                price = _mark_price(s, pos.direction, use_close)
                if price is None:
                    continue
                sign = 1 if pos.direction == "BUY" else -1
                floating += sign * (price - pos.entry_price) * pos.lots * config.symbols[s].contract_size
            return floating

        # Pre-entry equity: gates this timestamp's entries/risk-stop using
        # only already-known information -- marked from this bar's OPEN,
        # never its close (Codex F2).
        equity = balance + _floating_pnl(use_close=False)

        was_stopped = risk_state.stop_active()
        risk_state.evaluate(equity, config.ftmo_limits)
        if risk_state.stop_active() and not was_stopped:
            reason = "TOTAL_STOP" if risk_state.total_stop_active else "DAILY_STOP"
            result.risk_stop_events.append((t, reason, f"equity={equity:.2f}"))
            for s in list(open_positions.keys()):
                fill = _mark_price(s, open_positions[s].direction, use_close=False)
                if fill is None:
                    continue
                trade = force_close(
                    open_positions[s], fill, t, "RISK_STOP",
                    config.symbols[s], config.raw["account"]["currency"],
                    config.commission_round_turn_usd_per_lot, slippage_price=slippage_price,
                )
                balance += trade.net_pnl_usd + trade.position.entry_commission_usd
                result.closed_trades.append(trade)
                del open_positions[s]

        # Fixed-candle-count timeout exit -- a pure function of each
        # position's own entry_time_utc, decided in advance (not
        # price-path-dependent), so processed here, before this
        # timestamp's entries, same causality tier as the risk-stop above.
        for s in list(open_positions.keys()):
            pos = open_positions[s]
            # entry_time_utc is always exactly M30-boundary-aligned (fills
            # happen at signal_close_time_utc + M30), coinciding with the
            # START of the candle in progress at entry -- that candle
            # "begins AT", not "after", entry, so it is NOT counted. The
            # first COUNTED candle begins one M30 later; after
            # timeout_m30_candles such full candles have closed, the next
            # executable open is (timeout_m30_candles + 1) M30-steps past
            # entry_time_utc.
            timeout_time = pos.entry_time_utc + (timeout_m30_candles + 1) * M30
            fill_idx = first_bar_at_or_after(s, timeout_time)
            if fill_idx is None or m1_index[s][fill_idx].open_time_utc != t:
                continue
            fill_bar = m1_index[s][fill_idx]
            exit_price = fill_bar.open if pos.direction == "BUY" else fill_bar.open + spreads[s]
            trade = force_close(
                pos, exit_price, fill_bar.open_time_utc, "TIMEOUT_EXIT",
                config.symbols[s], config.raw["account"]["currency"],
                config.commission_round_turn_usd_per_lot, slippage_price=0.0,
            )
            balance += trade.net_pnl_usd + trade.position.entry_commission_usd
            result.closed_trades.append(trade)
            del open_positions[s]

        # S8's discretionary exit (SMA5 cross / H1 EMA200 invalidation) --
        # a "prior-candle signal exit", same mechanism as S6's Donchian
        # exit in simulator_ema_cross.py. S7's engine never sets
        # last_exit_flags, so this loop is a no-op for S7.
        while exit_check_ptr < len(all_exit_checks) and all_exit_checks[exit_check_ptr][1] <= t:
            exit_symbol, exit_decision_time, exit_flags, source_candle_open_time = all_exit_checks[exit_check_ptr]
            exit_check_ptr += 1
            pos = open_positions.get(exit_symbol)
            if pos is None:
                continue
            if source_candle_open_time <= pos.entry_time_utc:
                # "Starting with the first M30 candle CLOSED AFTER entry"
                # -- a check sourced from the entry candle itself (or
                # anything at/before it) never counts, matching the
                # timeout exit's identical exclusion above.
                continue
            should_close = (
                (pos.direction == "BUY" and exit_flags.close_long)
                or (pos.direction == "SELL" and exit_flags.close_short)
            )
            if not should_close:
                continue
            fill_idx = first_bar_at_or_after(exit_symbol, exit_decision_time)
            if fill_idx is None or m1_index[exit_symbol][fill_idx].open_time_utc != t:
                continue
            fill_bar = m1_index[exit_symbol][fill_idx]
            exit_price = fill_bar.open if pos.direction == "BUY" else fill_bar.open + spreads[exit_symbol]
            trade = force_close(
                pos, exit_price, fill_bar.open_time_utc, "DISCRETIONARY_EXIT",
                config.symbols[exit_symbol], config.raw["account"]["currency"],
                config.commission_round_turn_usd_per_lot, slippage_price=0.0,
            )
            balance += trade.net_pnl_usd + trade.position.entry_commission_usd
            result.closed_trades.append(trade)
            del open_positions[exit_symbol]

        newly_opened: dict[str, RichCandle] = {}

        while signal_ptr < len(all_signals) and all_signals[signal_ptr].signal_close_time_utc + M30 <= t:
            sig = all_signals[signal_ptr]
            signal_ptr += 1

            if sig.symbol in open_positions:
                result.skipped_signals.append(SkippedM30Signal(sig, "SYMBOL_ALREADY_HAS_OPEN_POSITION"))
                continue
            if risk_state.stop_active() or not risk_state.history_reconciled:
                result.skipped_signals.append(SkippedM30Signal(sig, "RISK_STOP_ACTIVE_OR_UNRECONCILED"))
                continue
            fill_idx = first_bar_at_or_after(sig.symbol, sig.signal_close_time_utc + M30)
            if fill_idx is None or m1_index[sig.symbol][fill_idx].open_time_utc != t:
                continue
            fill_bar = m1_index[sig.symbol][fill_idx]
            spec = config.symbols[sig.symbol]

            transacted_entry = (
                fill_bar.open + spreads[sig.symbol] + slippage_price if sig.direction == "BUY"
                else fill_bar.open - slippage_price
            )
            if sig.sl_price is not None:
                sl_price = sig.sl_price
            else:
                # S8: SL anchored to the ACTUAL fill price, not the signal
                # candle's close -- same convention as S6.
                sl_price = (
                    transacted_entry - sig.sl_distance_price if sig.direction == "BUY"
                    else transacted_entry + sig.sl_distance_price
                )
            tp_price = sig.tp_price  # may be None (S8 has no fixed TP)
            sl_distance = (transacted_entry - sl_price) if sig.direction == "BUY" else (sl_price - transacted_entry)
            if sl_distance <= 0:
                result.skipped_signals.append(SkippedM30Signal(sig, "EXECUTION_PRICE_INVALIDATED_SL"))
                continue
            if tp_price is not None:
                # S7: before sending, confirm TP is on the profit side of
                # the ACTUAL fill (a scenario's wider spread/slippage can
                # push the fill past the fixed mid-range TP) -- skip rather
                # than send an inverted or zero-distance order.
                tp_ok = (tp_price > transacted_entry) if sig.direction == "BUY" else (tp_price < transacted_entry)
                if not tp_ok:
                    result.skipped_signals.append(SkippedM30Signal(sig, "TP_NOT_ON_PROFIT_SIDE_OF_FILL"))
                    continue

            commission_per_lot = config.commission_round_turn_usd_per_lot or 0.0
            lots = lots_for_risk(
                config.risk_per_idea_usd, sl_distance, spec, config.raw["account"]["currency"],
                extra_cost_usd_per_lot=commission_per_lot,
            )
            if lots == 0.0:
                result.skipped_signals.append(SkippedM30Signal(sig, "MIN_LOT_EXCEEDS_RISK_BUDGET"))
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
                    remaining = pos.risk_usd_at_entry
                else:
                    # FIXED 2026-09-18 (Codex F2): mark from this bar's
                    # OPEN, not its close.
                    mark = _mark_price(other_symbol, pos.direction, use_close=False)
                    remaining = abs(mark - pos.sl) * pos.lots * config.symbols[other_symbol].contract_size if mark is not None else pos.risk_usd_at_entry
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
                result.skipped_signals.append(SkippedM30Signal(sig, "PRE_TRADE_PROJECTED_EQUITY_BREACH"))
                continue
            if not new_idea_within_risk_caps(
                sig.symbol, _direction_bucket(sig.direction), actual_risk,
                open_risk_by_idea, idea_symbol, idea_bucket, config.correlation_limits,
            ):
                result.skipped_signals.append(SkippedM30Signal(sig, "CORRELATED_OR_PORTFOLIO_RISK_CAP"))
                continue

            idea_counter += 1
            pos = open_position(
                f"m30-idea-{idea_counter}", sig.symbol, sig.direction, lots, fill_bar.open,
                sl_price, tp_price, fill_bar.open_time_utc, spreads[sig.symbol], actual_risk,
                slippage_price=slippage_price,
                commission_round_turn_usd_per_lot=config.commission_round_turn_usd_per_lot,
            )
            # FIXED 2026-09-18 (Codex F5): book the entry-side commission now.
            balance -= pos.entry_commission_usd
            open_positions[sig.symbol] = pos
            newly_opened[sig.symbol] = fill_bar

        # Intrabar SL/TP for EVERY position still open at this point --
        # pre-existing survivors AND this tick's own new entries alike,
        # checked against this SAME bar in one unified pass, strictly
        # AFTER entries (Codex F2).
        for s in list(open_positions.keys()):
            bar = bar_by_symbol_by_time[s].get(t)
            if bar is None:
                continue
            pos = open_positions[s]
            trade = simulate_exit(
                pos, [bar], config.symbols[s], config.raw["account"]["currency"],
                spreads[s], config.commission_round_turn_usd_per_lot,
                enforce_session_close=False, slippage_price=slippage_price,
            )
            if trade is not None:
                balance += trade.net_pnl_usd + trade.position.entry_commission_usd
                result.closed_trades.append(trade)
                del open_positions[s]

        settled_equity = balance + _floating_pnl(use_close=True)
        result.equity_curve.append((t, settled_equity, balance))

    result.final_balance = balance
    result.open_positions_at_end = dict(open_positions)
    result.final_equity = result.equity_curve[-1][1] if result.equity_curve else balance
    return result


def run_false_breakout_m30_simulation(config: RunConfig, m1_by_symbol: dict[str, list[RichCandle]],
                                       slippage_price: float = 0.0) -> M30SimulationResult:
    """S7 -- see docs/EXPERIMENT_PLAN_2026-09-18.md section 2. Reads
    config.raw['strategies']['false_breakout_m30_v1']."""
    from .strategy_false_breakout_m30 import FalseBreakoutM30Engine

    p = config.raw["strategies"]["false_breakout_m30_v1"]
    engine_factory = lambda symbol: FalseBreakoutM30Engine(
        symbol,
        range_period=p["range_period_m30"],
        atr_period=p["atr_period_m30"],
        sl_atr_buffer_multiple=p["sl_atr_buffer_multiple"],
    )
    return run_m30_signal_simulation(
        config, m1_by_symbol, engine_factory=engine_factory,
        timeout_m30_candles=p["timeout_m30_candles"], slippage_price=slippage_price,
    )


def run_rsi2_pullback_m30_simulation(config: RunConfig, m1_by_symbol: dict[str, list[RichCandle]],
                                      slippage_price: float = 0.0) -> M30SimulationResult:
    """S8 -- see docs/EXPERIMENT_PLAN_2026-09-18.md section 2. Reads
    config.raw['strategies']['rsi2_pullback_m30_v1']."""
    from .strategy_rsi2_pullback_m30 import Rsi2PullbackM30Engine

    p = config.raw["strategies"]["rsi2_pullback_m30_v1"]
    engine_factory = lambda symbol: Rsi2PullbackM30Engine(
        symbol,
        rsi_period=p["rsi_period_m30"],
        atr_period=p["atr_period_m30"],
        atr_sl_multiple=p["atr_sl_multiple"],
        sma_period=p["sma_period_m30"],
        h1_ema_period=p["h1_ema_period"],
        rsi_buy_threshold=p["rsi_buy_threshold"],
        rsi_sell_threshold=p["rsi_sell_threshold"],
    )
    return run_m30_signal_simulation(
        config, m1_by_symbol, engine_factory=engine_factory,
        timeout_m30_candles=p["timeout_m30_candles"], slippage_price=slippage_price,
    )
