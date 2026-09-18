"""EMA(20/50) H1 trend-following crossover -- a second, independent, widely
known baseline requested explicitly by the account owner ("meklē peļņu ar
jebkuru tev zināmo stratēģiju") to compare against the fixed London Range
Breakout + Retest v1 result on the same ~2-month sample.

This is NOT a parameter search over the breakout strategy (spec section 8
explicitly warns against wide optimization on this short a dataset, and nine
weeks of H1 data is nowhere near enough to fit anything trustworthy either).
It is one additional, complete, hand-picked, well-known strategy, run once
with textbook-standard parameters (20/50 EMA, 1.5x ATR stop, 3R target),
report side by side with the baseline, both labeled EXPLORATORY.

Unlike the London strategy, this one is a swing/trend design: it holds
positions across the session-close boundary that intraday strategy enforces,
which is arguably a better fit for an FTMO *Swing* account in the first
place. It still runs under the exact same account-wide risk engine
(account_risk.py / risk_state.py) and the exact same order-execution model
(order_exec.py: spread once per round trip, SL-first same-bar ambiguity,
gap fills at the open) as the baseline.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from .bars import Candle


class Ema:
    def __init__(self, period: int):
        self.period = period
        self.alpha = 2.0 / (period + 1)
        self.value: float | None = None
        self._sum = 0.0
        self._count = 0

    def update(self, close: float) -> float | None:
        self._count += 1
        if self.value is None:
            self._sum += close
            if self._count >= self.period:
                self.value = self._sum / self.period
        else:
            self.value = self.value + self.alpha * (close - self.value)
        return self.value

    @property
    def ready(self) -> bool:
        return self.value is not None


class WilderAtr:
    def __init__(self, period: int):
        self.period = period
        self.value: float | None = None
        self._prev_close: float | None = None
        self._sum = 0.0
        self._count = 0

    def update(self, candle: Candle) -> float | None:
        if self._prev_close is None:
            tr = candle.high - candle.low
        else:
            tr = max(
                candle.high - candle.low,
                abs(candle.high - self._prev_close),
                abs(candle.low - self._prev_close),
            )
        self._prev_close = candle.close
        self._count += 1
        if self.value is None:
            self._sum += tr
            if self._count >= self.period:
                self.value = self._sum / self.period
        else:
            self.value = (self.value * (self.period - 1) + tr) / self.period
        return self.value

    @property
    def ready(self) -> bool:
        return self.value is not None


@dataclass
class EmaCrossSignal:
    symbol: str
    direction: str  # "BUY" | "SELL"
    signal_close_time_utc: object
    sl_price: float | None  # None means "use sl_distance_price from the actual fill" (see below)
    tp_price: float | None  # None means "no fixed TP" (S6 Donchian) -- never a fabricated sentinel price
    fast_ema: float
    slow_ema: float
    atr_h1: float
    # Added for S6 (Donchian): when sl_price is None, the runner computes
    # the real SL level as (actual fill price -/+ sl_distance_price)
    # instead of a signal-candle-close-derived absolute level -- "from the
    # actual fill price", per docs/EXPERIMENT_PLAN_2026-09-18.md section 2.
    # None/unused for every engine that already sets an absolute sl_price
    # (S2/S3/S4/S5).
    sl_distance_price: float | None = None


class EmaCrossEngine:
    """One instance per symbol. Feed closed H1 candles via on_h1_candle().
    Emits at most one signal per crossover event; the caller (simulator) is
    responsible for not opening a second position while one is already
    open -- this engine does not track position state itself, only the
    crossover condition, since "is a position open" is portfolio/account
    state that belongs to the simulator, not the signal engine.
    """

    def __init__(self, symbol: str, fast_period: int = 20, slow_period: int = 50,
                 atr_period: int = 14, atr_sl_multiple: float = 1.5, tp_r_multiple: float = 3.0):
        self.symbol = symbol
        self.fast = Ema(fast_period)
        self.slow = Ema(slow_period)
        self.atr = WilderAtr(atr_period)
        self.atr_sl_multiple = atr_sl_multiple
        self.tp_r_multiple = tp_r_multiple
        self._prev_fast: float | None = None
        self._prev_slow: float | None = None

    def on_h1_candle(self, candle: Candle) -> EmaCrossSignal | None:
        fast = self.fast.update(candle.close)
        slow = self.slow.update(candle.close)
        atr = self.atr.update(candle)

        signal = None
        if (self._prev_fast is not None and self._prev_slow is not None
                and self.fast.ready and self.slow.ready and self.atr.ready):
            crossed_up = self._prev_fast <= self._prev_slow and fast > slow
            crossed_down = self._prev_fast >= self._prev_slow and fast < slow
            if crossed_up or crossed_down:
                direction = "BUY" if crossed_up else "SELL"
                buffer = self.atr_sl_multiple * atr
                if direction == "BUY":
                    sl = candle.close - buffer
                    tp = candle.close + self.tp_r_multiple * buffer
                else:
                    sl = candle.close + buffer
                    tp = candle.close - self.tp_r_multiple * buffer
                signal = EmaCrossSignal(
                    symbol=self.symbol, direction=direction,
                    signal_close_time_utc=candle.open_time_utc,
                    sl_price=sl, tp_price=tp,
                    fast_ema=fast, slow_ema=slow, atr_h1=atr,
                )

        self._prev_fast = fast
        self._prev_slow = slow
        return signal
