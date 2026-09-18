"""Order execution / position-lifecycle model for the offline simulator.

Single-price (Bid-only) M1 data has no intrabar path, so when both SL and TP
are reachable within one M1 candle this model always resolves it SL-first
(the conservative assumption spec section 8 requires) and flags the trade as
`same_bar_ambiguous=True` so the report can surface how many trades this
affects rather than silently picking the flattering (TP-first) outcome.

Long entries transact at Ask (Bid + spread), exits at Bid. Short entries
transact at Bid, exits at Ask. This charges the spread exactly once per
round trip, on whichever leg the direction implies, never both.

A price gap that jumps straight past a stop level is filled at the next
available price (the bar's open), never assumed to fill exactly at the SL/TP
level -- spec section 8 explicitly forbids "gaps guaranteed at SL".
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import time, timedelta

from .bars import RichCandle
from .symbol_spec import SymbolSpec, value_per_price_unit_per_lot
from .time_utils import london_time_of_day

SESSION_CLOSE_LONDON = time(16, 0)


@dataclass
class Position:
    idea_id: str
    symbol: str
    direction: str  # "BUY" | "SELL"
    lots: float
    entry_price: float
    sl: float
    tp: float | None  # None = no fixed TP (S6 Donchian) -- never a fabricated sentinel price
    entry_time_utc: object
    risk_usd_at_entry: float


@dataclass
class ClosedTrade:
    position: Position
    exit_price: float
    exit_time_utc: object
    exit_reason: str  # "SL" | "TP" | "SL_GAP" | "TP_GAP" | "SESSION_CLOSE" | "RISK_STOP"
    same_bar_ambiguous: bool
    gross_pnl_usd: float
    commission_usd: float
    net_pnl_usd: float
    r_multiple_net: float | None


def spread_price(symbol: str, spec: SymbolSpec, spread_points_hypothetical: dict) -> float:
    points = spread_points_hypothetical[symbol]
    return points * spec.point_size


def open_position(
    idea_id: str,
    symbol: str,
    direction: str,
    lots: float,
    bid_fill_price: float,
    sl: float,
    tp: float | None,
    entry_time_utc,
    spread: float,
    risk_usd_at_entry: float,
    slippage_price: float = 0.0,
) -> Position:
    """`slippage_price` (>= 0.0) models a scenario's adverse execution
    slippage on this MARKET entry fill -- section 3 of
    docs/EXPERIMENT_PLAN_2026-09-18.md's C2/C3 stress scenarios. Applied
    against the account on top of the spread already in `bid_fill_price`'s
    BUY leg: a BUY pays MORE (entry_price higher), a SELL receives LESS
    (entry_price lower). Defaults to 0.0 so every existing C1-shaped call
    site is unaffected unless a scenario explicitly passes a non-zero
    value."""
    entry_price = (
        bid_fill_price + spread + slippage_price if direction == "BUY"
        else bid_fill_price - slippage_price
    )
    return Position(
        idea_id=idea_id, symbol=symbol, direction=direction, lots=lots,
        entry_price=entry_price, sl=sl, tp=tp, entry_time_utc=entry_time_utc,
        risk_usd_at_entry=risk_usd_at_entry,
    )


def _check_bar(position: Position, bar: RichCandle, spread: float,
                slippage_price: float = 0.0) -> tuple[str, float, bool, bool] | None:
    """Returns (reason, exit_price, ambiguous, gapped) if this bar closes the
    position, else None. `reason` is "SL" or "TP" (gap suffix applied by the
    caller); `gapped` means the bar's open already lay beyond the level, so
    the fill is the open price rather than the exact SL/TP level.

    `slippage_price` (>=0.0) is a scenario's adverse execution slippage,
    applied ONLY to SL-triggered fills (a stop-out is a market fill; a TP
    fill is modeled as achievable exactly, per
    docs/EXPERIMENT_PLAN_2026-09-18.md section 3) -- worse for the account
    in every case: a BUY's SL fills LOWER, a SELL's SL fills HIGHER.

    `position.tp is None` (S6 Donchian -- no fixed TP) simply disables every
    TP check below; never a fabricated huge/sentinel TP price."""
    has_tp = position.tp is not None
    if position.direction == "BUY":
        bid_open, bid_high, bid_low = bar.open, bar.high, bar.low
        gapped_past_sl = bid_open <= position.sl
        gapped_past_tp = has_tp and bid_open >= position.tp
        if gapped_past_sl:
            return ("SL", bid_open - slippage_price, gapped_past_tp, True)
        if gapped_past_tp:
            return ("TP", bid_open, False, True)
        sl_hit = bid_low <= position.sl
        tp_hit = has_tp and bid_high >= position.tp
        if sl_hit and tp_hit:
            return ("SL", position.sl - slippage_price, True, False)
        if sl_hit:
            return ("SL", position.sl - slippage_price, False, False)
        if tp_hit:
            return ("TP", position.tp, False, False)
        return None
    else:
        ask_open = bar.open + spread
        ask_high = bar.high + spread
        ask_low = bar.low + spread
        gapped_past_sl = ask_open >= position.sl
        gapped_past_tp = has_tp and ask_open <= position.tp
        if gapped_past_sl:
            return ("SL", ask_open + slippage_price, gapped_past_tp, True)
        if gapped_past_tp:
            return ("TP", ask_open, False, True)
        sl_hit = ask_high >= position.sl
        tp_hit = has_tp and ask_low <= position.tp
        if sl_hit and tp_hit:
            return ("SL", position.sl + slippage_price, True, False)
        if sl_hit:
            return ("SL", position.sl + slippage_price, False, False)
        if tp_hit:
            return ("TP", position.tp, False, False)
        return None


def simulate_exit(
    position: Position,
    m1_bars_after_entry: list[RichCandle],
    spec: SymbolSpec,
    account_currency: str,
    spread: float,
    commission_round_turn_usd_per_lot: float | None,
    enforce_session_close: bool = True,
    slippage_price: float = 0.0,
) -> ClosedTrade | None:
    """Walk forward bar by bar from entry looking for SL/TP/session-close.
    Returns None if the position is still open after m1_bars_after_entry is
    exhausted (caller must keep feeding bars on the next call as more data
    arrives, or treat it as still-open at the end of the run).

    enforce_session_close=False is for a swing/trend strategy that is meant
    to hold positions overnight (spec section 6: Swing accounts are not
    required to flatten daily/weekly) -- the 16:00 London force-close is a
    design choice specific to the intraday London Range Breakout baseline,
    not a universal rule."""
    per_unit_per_lot = value_per_price_unit_per_lot(spec, account_currency)
    for bar in m1_bars_after_entry:
        tod = london_time_of_day(bar.open_time_utc)
        if enforce_session_close and tod >= SESSION_CLOSE_LONDON:
            exit_price = bar.open if position.direction == "BUY" else bar.open + spread
            return _finalize(position, exit_price, bar.open_time_utc, "SESSION_CLOSE", False, per_unit_per_lot, commission_round_turn_usd_per_lot)

        result = _check_bar(position, bar, spread, slippage_price)
        if result is not None:
            reason, exit_price, ambiguous, gapped = result
            final_reason = f"{reason}_GAP" if gapped else reason
            return _finalize(position, exit_price, bar.open_time_utc, final_reason, ambiguous, per_unit_per_lot, commission_round_turn_usd_per_lot)
    return None


def force_close(
    position: Position,
    fill_price_bid_or_ask_adjusted: float,
    time_utc,
    reason: str,
    spec: SymbolSpec,
    account_currency: str,
    commission_round_turn_usd_per_lot: float | None,
    slippage_price: float = 0.0,
) -> ClosedTrade:
    """A forced flatten (RISK_STOP) is a market order like any other --
    `slippage_price` (>=0.0) applies the same adverse convention as a
    stop-out in `_check_bar`: worse for the account regardless of
    direction. The caller still supplies the already spread-adjusted
    bid/ask price; this only adds the extra adverse slippage on top."""
    fill_price = (
        fill_price_bid_or_ask_adjusted - slippage_price if position.direction == "BUY"
        else fill_price_bid_or_ask_adjusted + slippage_price
    )
    per_unit_per_lot = value_per_price_unit_per_lot(spec, account_currency)
    return _finalize(
        position, fill_price, time_utc, reason, False,
        per_unit_per_lot, commission_round_turn_usd_per_lot,
    )


def _finalize(position, exit_price, exit_time, reason, ambiguous, per_unit_per_lot, commission_round_turn_usd_per_lot) -> ClosedTrade:
    if position.direction == "BUY":
        gross = (exit_price - position.entry_price) * per_unit_per_lot * position.lots
    else:
        gross = (position.entry_price - exit_price) * per_unit_per_lot * position.lots
    commission = 0.0
    if commission_round_turn_usd_per_lot is not None:
        commission = commission_round_turn_usd_per_lot * position.lots
    net = gross - commission
    r_multiple = net / position.risk_usd_at_entry if position.risk_usd_at_entry else None
    return ClosedTrade(
        position=position, exit_price=exit_price, exit_time_utc=exit_time,
        exit_reason=reason, same_bar_ambiguous=ambiguous,
        gross_pnl_usd=gross, commission_usd=commission, net_pnl_usd=net,
        r_multiple_net=r_multiple,
    )
