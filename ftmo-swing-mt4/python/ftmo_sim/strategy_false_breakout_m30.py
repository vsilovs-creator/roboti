"""M30 false-breakout-and-return -- S7 in
docs/EXPERIMENT_PLAN_2026-09-18.md section 2. Inspiration only (the WH
SelfInvest "Turtle Soup" forex adaptation); this 20-bar M30 version differs
from theirs and their published win-rate/backtest is not treated as
independent validation. This is a hypothesis about false breakouts
reverting, not proof of real order-book liquidity or stop-hunting.

Before signal candle t: U20 = max(high of the prior 20 CLOSED M30 candles),
L20 = min(low of the prior 20 CLOSED M30 candles), M = (U20+L20)/2 -- all
excluding t itself.

SELL if high[t] > U20 AND L20 < close[t] < U20 (breaks the upper boundary
intrabar, closes back inside the range). BUY if low[t] < L20 AND L20 <
close[t] < U20 (breaks the lower boundary, closes back inside). A candle
breaching BOTH boundaries is ambiguous -- no trade. Equal-to-boundary is
NOT a breakout (strict >/< throughout).

SL: SELL SL = high[t] + 0.1xATR14(M30, Wilder); BUY SL = low[t] -
0.1xATR14(M30, Wilder). TP fixed at M for both directions. The runner
additionally validates, once the actual fill price is known, that TP sits
on the profit side and SL on the loss side of that fill -- if a scenario's
wider spread/slippage breaks that ordering, the signal is skipped rather
than sent inverted or zero-distance.

Exit: SL/TP as normal, OR -- if neither is hit -- a fixed 8-full-M30-candle
timeout counted from entry, closed at the next executable open. This
timeout is a pure function of entry time (see
simulator_m30_signal.run_m30_signal_simulation), not computed by this
engine.
"""
from __future__ import annotations

from collections import deque

from .bars import Candle
from .strategy_ema_cross import EmaCrossSignal, WilderAtr


class FalseBreakoutM30Engine:
    """One instance per symbol. Feed closed M30 candles via
    on_m30_candle()."""

    def __init__(self, symbol: str, range_period: int = 20, atr_period: int = 14,
                 sl_atr_buffer_multiple: float = 0.1):
        self.symbol = symbol
        self.range_period = range_period
        self.sl_atr_buffer_multiple = sl_atr_buffer_multiple
        self.atr = WilderAtr(atr_period)
        self._highs: deque = deque(maxlen=range_period)
        self._lows: deque = deque(maxlen=range_period)

    def on_m30_candle(self, candle: Candle) -> EmaCrossSignal | None:
        atr = self.atr.update(candle)
        signal = None
        if self.atr.ready and len(self._highs) >= self.range_period:
            u20 = max(self._highs)
            l20 = min(self._lows)
            breached_up = candle.high > u20
            breached_down = candle.low < l20
            closed_inside = l20 < candle.close < u20
            if breached_up and breached_down:
                pass  # both boundaries breached in one candle -- ambiguous, no trade
            elif breached_up and closed_inside:
                mid = (u20 + l20) / 2.0
                sl = candle.high + self.sl_atr_buffer_multiple * atr
                signal = EmaCrossSignal(
                    symbol=self.symbol, direction="SELL", signal_close_time_utc=candle.open_time_utc,
                    sl_price=sl, tp_price=mid, fast_ema=u20, slow_ema=l20, atr_h1=atr,
                )
            elif breached_down and closed_inside:
                mid = (u20 + l20) / 2.0
                sl = candle.low - self.sl_atr_buffer_multiple * atr
                signal = EmaCrossSignal(
                    symbol=self.symbol, direction="BUY", signal_close_time_utc=candle.open_time_utc,
                    sl_price=sl, tp_price=mid, fast_ema=u20, slow_ema=l20, atr_h1=atr,
                )
        self._highs.append(candle.high)
        self._lows.append(candle.low)
        return signal
