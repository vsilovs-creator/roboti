"""Donchian H1 20/10 with an ATR stop -- S6 in
docs/EXPERIMENT_PLAN_2026-09-18.md section 2. Inspiration only (the cited
MQL5 "Trading with Donchian Channels" article), never proof of
profitability: this specific 20/10/2.0xATR parameterization is taken
directly from the task instructions, not fitted to this project's data.

Entry: BUY if close[t] > max(high[t-20..t-1]); SELL if close[t] <
min(low[t-20..t-1]) -- the prior 20 CLOSED H1 bars, excluding t itself.
Initial SL = 2.0 x ATR14(H1, Wilder) from the ACTUAL fill price (not the
signal candle's close) -- see EmaCrossSignal.sl_distance_price, resolved by
the runner once the real fill price is known, so lot-step rounding can only
ever round the realized risk DOWN, never above budget. No fixed TP.

Exit: close long when H1 close[t] < min(low[t-10..t-1]); close short when
H1 close[t] > max(high[t-10..t-1]) -- the prior 10 CLOSED H1 bars, excluding
t. This is a discretionary condition, independent of whether a position
happens to be open -- the runner
(simulator_ema_cross.run_h1_signal_simulation) reads it off
`engine.last_exit_flags` right after calling on_h1_candle() for each closed
H1 candle, and only acts on it for a symbol that actually has a
matching-direction open position from this run. No pyramiding, no
trailing-stop adjustment, no auto-reverse: the exit just flattens; a new
position only opens from a subsequent, independently generated entry
signal, never the same H1 bar that generated the currently-open position's
own entry signal (structurally true here since entry and exit windows are
each read BEFORE this candle is appended, so a single candle cannot both
open and immediately re-trigger its own exit condition from the SAME
window state).
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass

from .bars import Candle
from .strategy_ema_cross import EmaCrossSignal, WilderAtr


@dataclass
class DonchianExitFlags:
    close_long: bool
    close_short: bool


class DonchianAtrEngine:
    """One instance per symbol. Feed closed H1 candles via on_h1_candle();
    read `self.last_exit_flags` (a DonchianExitFlags, or None before
    warm-up) immediately after each call for the discretionary-exit
    condition evaluated off that SAME candle."""

    def __init__(self, symbol: str, entry_period: int = 20, exit_period: int = 10,
                 atr_period: int = 14, atr_sl_multiple: float = 2.0):
        self.symbol = symbol
        self.entry_period = entry_period
        self.exit_period = exit_period
        self.atr_sl_multiple = atr_sl_multiple
        self.atr = WilderAtr(atr_period)
        # Each window holds exactly the prior N closed bars once primed --
        # read BEFORE this candle is appended below, so t is always
        # excluded from its own entry/exit threshold, per spec.
        self._entry_highs: deque = deque(maxlen=entry_period)
        self._entry_lows: deque = deque(maxlen=entry_period)
        self._exit_highs: deque = deque(maxlen=exit_period)
        self._exit_lows: deque = deque(maxlen=exit_period)
        self.last_exit_flags: DonchianExitFlags | None = None

    def on_h1_candle(self, candle: Candle) -> EmaCrossSignal | None:
        atr = self.atr.update(candle)

        entry_signal = None
        if self.atr.ready and len(self._entry_highs) >= self.entry_period:
            u20 = max(self._entry_highs)
            l20 = min(self._entry_lows)
            sl_distance = self.atr_sl_multiple * atr
            if candle.close > u20:
                entry_signal = EmaCrossSignal(
                    symbol=self.symbol, direction="BUY", signal_close_time_utc=candle.open_time_utc,
                    sl_price=None, tp_price=None, fast_ema=u20, slow_ema=l20, atr_h1=atr,
                    sl_distance_price=sl_distance,
                )
            elif candle.close < l20:
                entry_signal = EmaCrossSignal(
                    symbol=self.symbol, direction="SELL", signal_close_time_utc=candle.open_time_utc,
                    sl_price=None, tp_price=None, fast_ema=u20, slow_ema=l20, atr_h1=atr,
                    sl_distance_price=sl_distance,
                )

        if len(self._exit_highs) >= self.exit_period:
            exit_u10 = max(self._exit_highs)
            exit_l10 = min(self._exit_lows)
            self.last_exit_flags = DonchianExitFlags(
                close_long=candle.close < exit_l10,
                close_short=candle.close > exit_u10,
            )
        else:
            self.last_exit_flags = None

        self._entry_highs.append(candle.high)
        self._entry_lows.append(candle.low)
        self._exit_highs.append(candle.high)
        self._exit_lows.append(candle.low)
        return entry_signal
