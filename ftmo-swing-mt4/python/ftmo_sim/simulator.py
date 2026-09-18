"""Offline, single-timeline, two-instrument portfolio simulator.

This is the offline research engine referenced in spec section 8: it runs
EURUSD and GBPUSD on one shared account and one shared clock, so the account
risk floors, the correlated-group cap, and the daily/total stop state machine
are exercised exactly as they would be by a single EA account controller --
summing two independently-tested single-pair equity curves after the fact
would not exercise any of that shared-risk logic and is explicitly rejected
by the spec.

Everything here works from real M1 data when supplied and never fabricates a
missing candle. Where an input is genuinely unknown (commission, the server
clock's real UTC/DST offset), the run is labeled EXPLORATORY end to end
rather than silently defaulting to a validated-looking number.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta

from .account_risk import (
    OpenPositionRiskView,
    new_entry_allowed,
    new_idea_within_risk_caps,
    pre_trade_projected_equity,
)
from .bars import RichCandle, resample
from .config import RunConfig
from .order_exec import ClosedTrade, Position, force_close, open_position, resolve_gap_fill, simulate_exit, spread_price
from .risk_state import RiskState
from .signals import LondonBreakoutRetestEngine, SignalEvent
from .symbol_spec import lots_for_risk, risk_usd_for_lots
from .time_utils import ftmo_trading_day

M5 = timedelta(minutes=5)
H1 = timedelta(hours=1)


@dataclass
class SkippedSignal:
    signal: SignalEvent
    reason: str


@dataclass
class SimulationResult:
    closed_trades: list[ClosedTrade] = field(default_factory=list)
    skipped_signals: list[SkippedSignal] = field(default_factory=list)
    equity_curve: list[tuple] = field(default_factory=list)  # (utc_time, equity, balance)
    day_outcomes_by_symbol: dict = field(default_factory=dict)
    risk_stop_events: list[tuple] = field(default_factory=list)  # (utc_time, kind, reason)
    final_balance: float = 0.0
    account_number: int = 900000001
    server_name: str = "OFFLINE-SIM"
    # Positions still open when the sample ran out -- final_balance is
    # REALIZED balance only and does not include these; see final_equity.
    open_positions_at_end: dict = field(default_factory=dict)
    final_equity: float = 0.0
    # ADDED 2026-09-18 (Codex F3): balance_at_midnight (B0) per FTMO day
    # (ISO date string -> USD), so a day's own floor
    # (B0 - robot_daily_working_buffer_offset_usd) can be independently
    # recomputed from the raw equity curve, rather than trusting only the
    # simulator's own DAILY_STOP/TOTAL_STOP risk_stop_events.
    balance_at_midnight_by_day: dict = field(default_factory=dict)


def _merge_signal_feed(m5_by_symbol: dict[str, list[RichCandle]], h1_by_symbol: dict[str, list[RichCandle]], symbol: str):
    events = []
    for c in h1_by_symbol[symbol]:
        events.append((c.open_time_utc + H1, 0, "H1", c))
    for c in m5_by_symbol[symbol]:
        events.append((c.open_time_utc + M5, 1, "M5", c))
    events.sort(key=lambda e: (e[0], e[1]))
    return events


def _direction_bucket(direction: str) -> str:
    # BUY EURUSD/GBPUSD = long the pair = short USD; SELL = long USD.
    return "LONG_USD" if direction == "SELL" else "SHORT_USD"


def run_simulation(
    config: RunConfig, m1_by_symbol: dict[str, list[RichCandle]], slippage_price: float = 0.0,
) -> SimulationResult:
    """`slippage_price` (>=0.0): a scenario's adverse execution slippage,
    threaded through every fill in this function (entries and
    SL-triggered exits/forced closes) -- see
    docs/EXPERIMENT_PLAN_2026-09-18.md section 3. Defaults to 0.0, matching
    every call site before this parameter existed."""
    symbols = list(m1_by_symbol.keys())
    m5_by_symbol = {s: resample(m1_by_symbol[s], 5) for s in symbols}
    h1_by_symbol = {s: resample(m1_by_symbol[s], 60) for s in symbols}

    strat_cfg = config.strategy
    engines = {
        s: LondonBreakoutRetestEngine(
            symbol=s,
            retest_max_bars=strat_cfg["retest_max_bars_m5"],
            sl_atr_buffer_multiple=strat_cfg["sl_atr_buffer_multiple"],
            atr_period=strat_cfg["atr_period_m5"],
            ema_period=strat_cfg["ema_period_h1"],
            tp_r_multiple=strat_cfg["tp_r_multiple"],
        )
        for s in symbols
    }

    # -- Phase 1: generate raw signal events per symbol from M5/H1 candles.
    all_signals: list[SignalEvent] = []
    for s in symbols:
        for _, _, kind, candle in _merge_signal_feed(m5_by_symbol, h1_by_symbol, s):
            if kind == "H1":
                engines[s].on_h1_candle(candle)
            else:
                event = engines[s].on_m5_candle(candle)
                if event is not None:
                    all_signals.append(event)
    all_signals.sort(key=lambda e: e.retest_close_time_utc)

    # index M1 bars by symbol for O(1)-ish forward scanning
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

    # -- Phase 2: merged M1 timeline across both symbols for account state.
    all_times = sorted({c.open_time_utc for s in symbols for c in m1_by_symbol[s]})
    bar_by_symbol_by_time: dict = {s: {c.open_time_utc: c for c in m1_by_symbol[s]} for s in symbols}

    result = SimulationResult()
    risk_state = RiskState(account_number=result.account_number, server_name=result.server_name, config_version="sim")
    balance = config.initial_balance
    open_positions: dict[str, Position] = {}
    last_seen: dict[str, RichCandle] = {}
    idea_counter = 0
    signal_ptr = 0
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

        # FIXED 2026-09-18 (Codex F2, follow-up-follow-up audit): exit
        # processing for pre-existing positions used to run HERE, using
        # THIS bar's intrabar high/low/close before this bar's entries were
        # decided -- letting risk freed by a same-bar-LATER exit be used by
        # an entry decided at the bar's OPEN, before that risk had actually
        # been freed. The PURE INTRABAR (high/low) part of that check is
        # deferred to a unified pass after entries (below). A GAP-through
        # of an already-open position's SL/TP is knowable IMMEDIATELY at
        # this bar's open -- a mechanical stop/limit-order fill, not a
        # decision -- so it is resolved right here, before the risk-stop
        # check and this tick's entries (FIXED 2026-09-18, Codex R1,
        # follow-up-follow-up-follow-up audit; see the matching comment in
        # simulator_ema_cross.py for the exact repro this guards against).
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

        # -- mark-to-market equity + risk stop evaluation --
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

        # PRE-entry equity, for gating this timestamp's entries/risk-stop
        # only -- NOT the recorded equity-curve point. Marked from this
        # bar's OPEN (use_close=False): the close is not knowable yet at
        # the instant these decisions are made (Codex F2). See "settled"
        # below for the close-based, post-entry/post-intrabar point that
        # IS the recorded equity-curve value.
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
                # FIXED 2026-09-18 (Codex F5): net_pnl_usd already deducts
                # the FULL round-turn commission; the entry-side half was
                # already deducted from balance at open time (below), so
                # it is added back here to avoid double-charging it --
                # the two legs together still sum to exactly net_pnl_usd.
                balance += trade.net_pnl_usd + trade.position.entry_commission_usd
                result.closed_trades.append(trade)
                del open_positions[s]

        # -- new entries from queued signals whose fill bar has arrived --
        newly_opened: dict[str, RichCandle] = {}

        while signal_ptr < len(all_signals) and all_signals[signal_ptr].retest_close_time_utc + M5 <= t:
            sig = all_signals[signal_ptr]
            signal_ptr += 1
            if sig.symbol in open_positions:
                result.skipped_signals.append(SkippedSignal(sig, "SYMBOL_ALREADY_HAS_OPEN_POSITION"))
                continue
            if risk_state.stop_active() or not risk_state.history_reconciled:
                result.skipped_signals.append(SkippedSignal(sig, "RISK_STOP_ACTIVE_OR_UNRECONCILED"))
                continue
            fill_idx = first_bar_at_or_after(sig.symbol, sig.retest_close_time_utc + M5)
            if fill_idx is None or m1_index[sig.symbol][fill_idx].open_time_utc != t:
                continue  # not this tick's turn yet, or no data at all -- reschedule not needed, loop will catch it next matching t
            fill_bar = m1_index[sig.symbol][fill_idx]
            spec = config.symbols[sig.symbol]

            # Size and validate the SL from the actual transacted price (Ask
            # for BUY, Bid for SELL), not the raw bid quote -- spec section 4/9
            # requires risk to be recomputed from the real execution price,
            # since ignoring the spread here would understate the true risk
            # by exactly the spread on every trade (worse the tighter the SL).
            transacted_entry = (
                fill_bar.open + spreads[sig.symbol] + slippage_price if sig.direction == "BUY"
                else fill_bar.open - slippage_price
            )
            sl_distance = (transacted_entry - sig.sl_price) if sig.direction == "BUY" else (sig.sl_price - transacted_entry)
            if sl_distance <= 0:
                result.skipped_signals.append(SkippedSignal(sig, "EXECUTION_PRICE_INVALIDATED_SL"))
                continue
            commission_per_lot = config.commission_round_turn_usd_per_lot or 0.0
            lots = lots_for_risk(
                config.risk_per_idea_usd, sl_distance, spec, config.raw["account"]["currency"],
                extra_cost_usd_per_lot=commission_per_lot,
            )
            if lots == 0.0:
                result.skipped_signals.append(SkippedSignal(sig, "MIN_LOT_EXCEEDS_RISK_BUDGET"))
                continue
            actual_risk = risk_usd_for_lots(
                lots, sl_distance, spec, config.raw["account"]["currency"],
                extra_cost_usd_per_lot=commission_per_lot,
            )

            open_risk_views = []
            for other_symbol, pos in open_positions.items():
                if other_symbol in newly_opened:
                    # FIXED 2026-09-18 (follow-up audit) -- see the matching
                    # comment in simulator_ema_cross.py: this position was
                    # opened THIS SAME timestamp, so its "remaining risk
                    # right now" is its full originally-sized risk, not a
                    # mark derived from this same bar's close (which leaks
                    # later-in-the-bar information into another symbol's
                    # simultaneous entry decision).
                    remaining = pos.risk_usd_at_entry
                else:
                    # FIXED 2026-09-18 (Codex F2): mark from this bar's
                    # OPEN, not its close -- see the matching comment in
                    # simulator_ema_cross.py.
                    mark = _mark_price(other_symbol, pos.direction, use_close=False)
                    remaining = abs(mark - pos.sl) * pos.lots * config.symbols[other_symbol].contract_size if mark is not None else pos.risk_usd_at_entry
                open_risk_views.append(OpenPositionRiskView(other_symbol, remaining, _direction_bucket(pos.direction)))

            floor = risk_state.balance_at_midnight - config.ftmo_limits.robot_daily_working_buffer_offset_usd
            floor = max(floor, config.ftmo_limits.robot_total_working_floor_usd)
            allowed = new_entry_allowed(
                equity, floor, open_risk_views, 0.0, actual_risk, 0.0, config.execution_buffer_usd,
            )
            if not allowed:
                result.skipped_signals.append(SkippedSignal(sig, "PRE_TRADE_PROJECTED_EQUITY_BREACH"))
                continue

            open_risk_by_idea = {
                other: v.remaining_risk_to_sl_usd for other, v in zip(open_positions.keys(), open_risk_views)
            }
            idea_symbol = {other: other for other in open_positions.keys()}
            idea_bucket = {other: _direction_bucket(open_positions[other].direction) for other in open_positions.keys()}
            if not new_idea_within_risk_caps(
                sig.symbol, _direction_bucket(sig.direction), actual_risk,
                open_risk_by_idea, idea_symbol, idea_bucket, config.correlation_limits,
            ):
                result.skipped_signals.append(SkippedSignal(sig, "CORRELATED_OR_PORTFOLIO_RISK_CAP"))
                continue

            idea_counter += 1
            pos = open_position(
                f"idea-{idea_counter}", sig.symbol, sig.direction, lots, fill_bar.open,
                sig.sl_price, sig.tp_price, fill_bar.open_time_utc, spreads[sig.symbol], actual_risk,
                slippage_price=slippage_price,
                commission_round_turn_usd_per_lot=config.commission_round_turn_usd_per_lot,
            )
            # FIXED 2026-09-18 (Codex F5): book the entry-side commission
            # (2.50 USD/lot/side, confirmed) immediately, not only once
            # this position eventually closes -- a still-open position's
            # balance/equity must already reflect it.
            balance -= pos.entry_commission_usd
            open_positions[sig.symbol] = pos
            newly_opened[sig.symbol] = fill_bar

        # Intrabar SL/TP for EVERY position still open at this point --
        # pre-existing survivors AND anything just opened by this tick's
        # own entries alike, checked against this SAME bar in one unified
        # pass, strictly AFTER entries (Codex F2 -- see the matching
        # comment near the top of this timestep for the reasoning).
        for s in list(open_positions.keys()):
            bar = bar_by_symbol_by_time[s].get(t)
            if bar is None:
                continue
            pos = open_positions[s]
            trade = simulate_exit(
                pos, [bar], config.symbols[s], config.raw["account"]["currency"],
                spreads[s], config.commission_round_turn_usd_per_lot, slippage_price=slippage_price,
            )
            if trade is not None:
                balance += trade.net_pnl_usd + trade.position.entry_commission_usd
                result.closed_trades.append(trade)
                del open_positions[s]

        settled_equity = balance + _floating_pnl(use_close=True)
        result.equity_curve.append((t, settled_equity, balance))

    result.final_balance = balance
    result.day_outcomes_by_symbol = {s: engines[s].day_outcomes for s in symbols}
    result.open_positions_at_end = dict(open_positions)
    result.final_equity = result.equity_curve[-1][1] if result.equity_curve else balance
    return result
