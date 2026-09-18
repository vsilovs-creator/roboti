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
                enforce_session_close=enforce_session_close,
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
            open_risk_by_idea: dict[str, float] = {}
            idea_symbol: dict[str, str] = {}
            idea_bucket: dict[str, str] = {}
            for other_symbol, pos in open_positions.items():
                bar = last_seen.get(other_symbol)
                mark = bar.close if pos.direction == "BUY" else bar.close + spreads[other_symbol]
                remaining = abs(mark - pos.sl) * pos.lots * config.symbols[other_symbol].contract_size
                bucket = _direction_bucket(pos.direction)
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
                sig.sl_price, sig.tp_price, fill_bar.open_time_utc, spreads[sig.symbol], actual_risk,
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
                enforce_session_close=enforce_session_close,
            )
            if trade is not None:
                balance += trade.net_pnl_usd
                result.closed_trades.append(trade)
                del open_positions[s]

    result.final_balance = balance
    result.open_positions_at_end = dict(open_positions)
    result.final_equity = result.equity_curve[-1][1] if result.equity_curve else balance
    return result


def run_ema_cross_simulation(config: RunConfig, m1_by_symbol: dict[str, list[RichCandle]]) -> EmaCrossResult:
    """Runs the EMA(20/50) H1 crossover using config['strategies']['ema_cross_v1']
    -- the CHOSEN strategy going forward (2026-09-18, see config.example.json's
    `strategies.active`), rather than the strategy_ema_cross.py hardcoded
    defaults, so changing the config actually changes the run."""
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
    )
