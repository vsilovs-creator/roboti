"""Bollinger Band (20, 2.0) H1 mean-reversion -- a THIRD well-known,
hand-picked strategy, tried because the EMA-crossover trend-follower lost to
whipsaw on this sample, which is itself evidence the ~2-month window was
more range-bound than trending. Same textbook parameters (20-period SMA/
stddev, 2.0 multiple), same account-wide risk engine and order-execution
model as the other two. Emits a signal shaped exactly like
strategy_ema_cross.EmaCrossSignal so simulator_ema_cross.run_ema_cross_simulation
can drive either engine without changes (see its `engine_factory` param).
"""
from __future__ import annotations

import math
from collections import deque

from .bars import Candle
from .strategy_ema_cross import EmaCrossSignal, WilderAtr


class RollingBollinger:
    def __init__(self, period: int, num_std: float):
        self.period = period
        self.num_std = num_std
        self._closes: deque = deque(maxlen=period)

    def update(self, close: float) -> tuple[float, float, float] | None:
        self._closes.append(close)
        if len(self._closes) < self.period:
            return None
        mean = sum(self._closes) / self.period
        variance = sum((x - mean) ** 2 for x in self._closes) / self.period
        std = math.sqrt(variance)
        return mean - self.num_std * std, mean, mean + self.num_std * std

    @property
    def ready(self) -> bool:
        return len(self._closes) >= self.period


class BbReversionEngine:
    """One instance per symbol. Feed closed H1 candles via on_h1_candle().
    BUY when a candle closes below the lower band (expecting reversion up);
    SELL when it closes above the upper band. SL is placed beyond the
    breached band by an ATR buffer (a further extension against the fade is
    the failure mode this strategy is exposed to); TP at the middle band
    (the SMA) -- a fixed target rather than "wait for the band to
    recapture it", to stay inside this project's fixed-SL/TP order-exec
    model (see order_exec.py)."""

    def __init__(self, symbol: str, period: int = 20, num_std: float = 2.0,
                 atr_period: int = 14, atr_sl_buffer_multiple: float = 0.5):
        self.symbol = symbol
        self.bb = RollingBollinger(period, num_std)
        self.atr = WilderAtr(atr_period)
        self.atr_sl_buffer_multiple = atr_sl_buffer_multiple

    def on_h1_candle(self, candle: Candle) -> EmaCrossSignal | None:
        bands = self.bb.update(candle.close)
        atr = self.atr.update(candle)
        if bands is None or not self.atr.ready:
            return None
        lower, mid, upper = bands

        if candle.close < lower:
            sl = candle.low - self.atr_sl_buffer_multiple * atr
            return EmaCrossSignal(
                symbol=self.symbol, direction="BUY", signal_close_time_utc=candle.open_time_utc,
                sl_price=sl, tp_price=mid, fast_ema=lower, slow_ema=mid, atr_h1=atr,
            )
        if candle.close > upper:
            sl = candle.high + self.atr_sl_buffer_multiple * atr
            return EmaCrossSignal(
                symbol=self.symbol, direction="SELL", signal_close_time_utc=candle.open_time_utc,
                sl_price=sl, tp_price=mid, fast_ema=upper, slow_ema=mid, atr_h1=atr,
            )
        return None
