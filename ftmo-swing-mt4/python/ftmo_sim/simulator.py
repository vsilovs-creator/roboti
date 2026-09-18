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
from .order_exec import ClosedTrade, Position, force_close, open_position, simulate_exit, spread_price
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

        rolled = risk_state.rollover_if_needed(ftmo_trading_day(t), balance)
        if rolled:
            result.risk_stop_events.append((t, "ROLLOVER", f"balance_at_midnight={balance:.2f}"))

        # -- position exits (SL/TP/session close) --
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
                balance += trade.net_pnl_usd
                result.closed_trades.append(trade)
                del open_positions[s]

        # -- mark-to-market equity + risk stop evaluation --
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

        # PRE-entry equity, for gating this timestamp's entries/risk-stop
        # only -- NOT the recorded equity-curve point. See the matching,
        # longer comment in simulator_ema_cross.py (FIXED 2026-09-18,
        # follow-up audit) for why the curve point must be recorded AFTER
        # this timestamp's own entries/same-bar closures (as "settled"
        # below), not here.
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

        # -- new entries from queued signals whose fill bar has arrived --
        # FIXED 2026-09-18 (independent code audit): a position opened below
        # at this bar's open was never checked against THIS SAME bar's own
        # high/low -- the exit-processing block above already ran, before
        # this position existed, so its own intrabar move was silently
        # skipped and only caught (as a much worse "gap" exit) on the
        # FOLLOWING bar. newly_opened tracks anything opened this timestamp
        # so it can be checked against its own entry bar immediately below,
        # before moving to the next timestamp.
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
                    bar = last_seen.get(other_symbol)
                    mark = bar.close if pos.direction == "BUY" else bar.close + spreads[other_symbol]
                    remaining = abs(mark - pos.sl) * pos.lots * config.symbols[other_symbol].contract_size
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
            )
            open_positions[sig.symbol] = pos
            newly_opened[sig.symbol] = fill_bar

        # Same-bar SL/TP check for anything just opened above.
        for s, fill_bar in newly_opened.items():
            pos = open_positions.get(s)
            if pos is None:
                continue
            trade = simulate_exit(
                pos, [fill_bar], config.symbols[s], config.raw["account"]["currency"],
                spreads[s], config.commission_round_turn_usd_per_lot, slippage_price=slippage_price,
            )
            if trade is not None:
                balance += trade.net_pnl_usd
                result.closed_trades.append(trade)
                del open_positions[s]

        settled_equity = balance + _floating_pnl()
        result.equity_curve.append((t, settled_equity, balance))

    result.final_balance = balance
    result.day_outcomes_by_symbol = {s: engines[s].day_outcomes for s in symbols}
    result.open_positions_at_end = dict(open_positions)
    result.final_equity = result.equity_curve[-1][1] if result.equity_curve else balance
    return result
