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

from .account_risk import OpenPositionRiskView, new_entry_allowed
from .bars import RichCandle, resample
from .config import RunConfig
from .order_exec import ClosedTrade, Position, force_close, open_position, simulate_exit, spread_price
from .risk_state import RiskState
from .strategy_ema_cross import EmaCrossEngine, EmaCrossSignal
from .symbol_spec import lots_for_risk, risk_usd_for_lots
from .time_utils import ftmo_trading_day


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
    final_balance: float = 0.0


def run_h1_signal_simulation(
    config: RunConfig,
    m1_by_symbol: dict[str, list[RichCandle]],
    engine_factory: Callable[[str], object] = EmaCrossEngine,
    account_number: int = 900000002,
    server_name: str = "OFFLINE-SIM-H1",
) -> EmaCrossResult:
    symbols = list(m1_by_symbol.keys())
    h1_by_symbol = {s: resample(m1_by_symbol[s], 60) for s in symbols}
    engines = {s: engine_factory(s) for s in symbols}

    all_signals: list[EmaCrossSignal] = []
    for s in symbols:
        for candle in h1_by_symbol[s]:
            sig = engines[s].on_h1_candle(candle)
            if sig is not None:
                all_signals.append(sig)
    all_signals.sort(key=lambda e: e.signal_close_time_utc)

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
    spreads = {s: spread_price(s, config.symbols[s], config.spread_points_hypothetical) for s in symbols}

    for t in all_times:
        for s in symbols:
            bar = bar_by_symbol_by_time[s].get(t)
            if bar is not None:
                last_seen[s] = bar

        rolled = risk_state.rollover_if_needed(ftmo_trading_day(t), balance)
        if rolled:
            result.risk_stop_events.append((t, "ROLLOVER", f"balance_at_midnight={balance:.2f}"))

        for s in list(open_positions.keys()):
            bar = bar_by_symbol_by_time[s].get(t)
            if bar is None:
                continue
            pos = open_positions[s]
            trade = simulate_exit(
                pos, [bar], config.symbols[s], config.raw["account"]["currency"],
                spreads[s], config.commission_round_turn_usd_per_lot,
                enforce_session_close=False,
            )
            if trade is not None:
                balance += trade.net_pnl_usd
                result.closed_trades.append(trade)
                del open_positions[s]

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
        equity = balance + floating
        result.equity_curve.append((t, equity, balance))

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
                    config.commission_round_turn_usd_per_lot,
                )
                balance += trade.net_pnl_usd
                result.closed_trades.append(trade)
                del open_positions[s]

        while signal_ptr < len(all_signals) and all_signals[signal_ptr].signal_close_time_utc + H1 <= t:
            sig = all_signals[signal_ptr]
            signal_ptr += 1
            if sig.symbol in open_positions:
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

            transacted_entry = fill_bar.open + spreads[sig.symbol] if sig.direction == "BUY" else fill_bar.open
            sl_distance = (transacted_entry - sig.sl_price) if sig.direction == "BUY" else (sig.sl_price - transacted_entry)
            if sl_distance <= 0:
                result.skipped_signals.append(SkippedEmaSignal(sig, "EXECUTION_PRICE_INVALIDATED_SL"))
                continue
            lots = lots_for_risk(config.risk_per_idea_usd, sl_distance, spec, config.raw["account"]["currency"])
            if lots == 0.0:
                result.skipped_signals.append(SkippedEmaSignal(sig, "MIN_LOT_EXCEEDS_RISK_BUDGET"))
                continue
            actual_risk = risk_usd_for_lots(lots, sl_distance, spec, config.raw["account"]["currency"])

            open_risk_views = []
            for other_symbol, pos in open_positions.items():
                bar = last_seen.get(other_symbol)
                mark = bar.close if pos.direction == "BUY" else bar.close + spreads[other_symbol]
                remaining = abs(mark - pos.sl) * pos.lots * config.symbols[other_symbol].contract_size
                open_risk_views.append(OpenPositionRiskView(other_symbol, remaining, "n/a"))

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

            idea_counter += 1
            pos = open_position(
                f"ema-idea-{idea_counter}", sig.symbol, sig.direction, lots, fill_bar.open,
                sig.sl_price, sig.tp_price, fill_bar.open_time_utc, spreads[sig.symbol], actual_risk,
            )
            open_positions[sig.symbol] = pos

    result.final_balance = balance
    return result


def run_ema_cross_simulation(config: RunConfig, m1_by_symbol: dict[str, list[RichCandle]]) -> EmaCrossResult:
    return run_h1_signal_simulation(config, m1_by_symbol, engine_factory=EmaCrossEngine)
