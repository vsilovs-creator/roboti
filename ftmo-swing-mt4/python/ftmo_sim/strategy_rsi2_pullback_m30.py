"""RSI(2) M30 pullback with an H1 EMA200 trend filter -- S8 in
docs/EXPERIMENT_PLAN_2026-09-18.md section 2. Adapted (unverified for
forex) from the MQL5 "Day Trading Larry Connors RSI2 Mean-Reversion"
article, which was tested on the US500 CFD, not forex, and from
Moskowitz/Ooi/Pedersen's futures/multi-month time-series-momentum evidence
being applied here, as a hypothesis only, to H1/M30 forex.

BUY if M30 RSI2[t]<5, RSI2[t-1]>=5 (a fresh threshold crossing, not a
repeat), AND H1 close > H1 EMA200 (the last H1 candle fully closed as of
this M30 signal candle's own close). SELL is the mirror: RSI2[t]>95,
RSI2[t-1]<=95, H1 close < H1 EMA200.

SL = 1.5xATR14(M30, Wilder) from the ACTUAL fill price (sl_distance_price,
same "anchor to fill" convention as S6). No fixed TP.

Exit (earliest of, all via `last_exit_flags`/the M30 runner's timeout,
starting only from the first M30 candle CLOSED after entry):
  1. M30 close crosses back through SMA5 with the reversion completing
     favorably (long: close > SMA5; short: close < SMA5).
  2. 10 full M30 candles closed since entry (handled by the runner's
     generic timeout, not this engine).
  3. A CLOSED H1 candle's close breaches EMA200 against the position
     (long: H1 close < H1 EMA200; short: H1 close > H1 EMA200) -- exposed
     via `last_h1_exit_flags`, read by the runner on the H1 cadence.

RSI2 edge cases (Wilder-smoothed average gain/loss, mirroring
strategy_ema_cross.WilderAtr's smoothing pattern applied to gains/losses
instead of true range):
  - A zero-movement bar contributes 0 to both the gain and loss sums.
  - avg_loss == 0 and avg_gain > 0 -> RSI = 100 (defined, not infinite).
  - avg_gain == 0 and avg_loss == 0 (only possible pre-warmup or on a
    fully flat window) -> RSI = 50 (neutral), never a division by zero.
  - Warm-up: not ready until `period+1` closed M30 bars have been seen
    (period=2 -> 3 bars), mirroring WilderAtr.ready's convention.
"""
from __future__ import annotations

from collections import deque

from .bars import Candle
from .strategy_donchian import DonchianExitFlags
from .strategy_ema_cross import Ema, EmaCrossSignal, WilderAtr


class WilderRsi:
    def __init__(self, period: int = 2):
        self.period = period
        self.avg_gain: float | None = None
        self.avg_loss: float | None = None
        self._prev_close: float | None = None
        self._gain_sum = 0.0
        self._loss_sum = 0.0
        self._count = 0

    def update(self, close: float) -> float | None:
        if self._prev_close is None:
            self._prev_close = close
            return None
        change = close - self._prev_close
        self._prev_close = close
        gain = max(change, 0.0)
        loss = max(-change, 0.0)
        self._count += 1
        if self.avg_gain is None:
            self._gain_sum += gain
            self._loss_sum += loss
            if self._count >= self.period:
                self.avg_gain = self._gain_sum / self.period
                self.avg_loss = self._loss_sum / self.period
        else:
            self.avg_gain = (self.avg_gain * (self.period - 1) + gain) / self.period
            self.avg_loss = (self.avg_loss * (self.period - 1) + loss) / self.period
        return self.value

    @property
    def ready(self) -> bool:
        return self.avg_gain is not None

    @property
    def value(self) -> float | None:
        if self.avg_gain is None:
            return None
        if self.avg_gain == 0.0 and self.avg_loss == 0.0:
            return 50.0
        if self.avg_loss == 0.0:
            return 100.0
        rs = self.avg_gain / self.avg_loss
        return 100.0 - (100.0 / (1.0 + rs))


class RollingSma:
    def __init__(self, period: int):
        self.period = period
        self._values: deque = deque(maxlen=period)

    def update(self, value: float) -> float | None:
        self._values.append(value)
        if len(self._values) < self.period:
            return None
        return sum(self._values) / self.period

    @property
    def ready(self) -> bool:
        return len(self._values) >= self.period


class Rsi2PullbackM30Engine:
    """One instance per symbol. Feed closed H1 candles via on_h1_candle()
    (updates the EMA200 filter/exit state only -- no entry signal from H1)
    and closed M30 candles via on_m30_candle() (RSI2 entries; SMA5 exit via
    `last_exit_flags`). Read `last_h1_exit_flags` right after on_h1_candle()
    for the H1-EMA200-breach exit condition."""

    def __init__(self, symbol: str, rsi_period: int = 2, atr_period: int = 14,
                 atr_sl_multiple: float = 1.5, sma_period: int = 5, h1_ema_period: int = 200,
                 rsi_buy_threshold: float = 5.0, rsi_sell_threshold: float = 95.0):
        self.symbol = symbol
        self.rsi_buy_threshold = rsi_buy_threshold
        self.rsi_sell_threshold = rsi_sell_threshold
        self.rsi = WilderRsi(rsi_period)
        self.atr = WilderAtr(atr_period)
        self.atr_sl_multiple = atr_sl_multiple
        self.sma = RollingSma(sma_period)
        self.h1_ema200 = Ema(h1_ema_period)
        self._prev_rsi: float | None = None
        self.h1_close: float | None = None
        self.last_exit_flags: DonchianExitFlags | None = None
        self.last_h1_exit_flags: DonchianExitFlags | None = None

    def on_h1_candle(self, candle: Candle) -> None:
        self.h1_ema200.update(candle.close)
        self.h1_close = candle.close
        if self.h1_ema200.ready:
            self.last_h1_exit_flags = DonchianExitFlags(
                close_long=self.h1_close < self.h1_ema200.value,
                close_short=self.h1_close > self.h1_ema200.value,
            )
        else:
            self.last_h1_exit_flags = None

    def on_m30_candle(self, candle: Candle) -> EmaCrossSignal | None:
        atr = self.atr.update(candle)
        rsi = self.rsi.update(candle.close)
        # SMA and the exit flags derived from it must reflect the state
        # BEFORE this candle's own close is folded in -- read the rolling
        # value first, THEN update, exactly like Donchian's window
        # convention (t is excluded from its own threshold).
        sma_ready_before = self.sma.ready
        sma_before = (sum(self.sma._values) / self.sma.period) if sma_ready_before else None

        signal = None
        if (
            rsi is not None and self._prev_rsi is not None and self.atr.ready
            and self.h1_ema200.ready
        ):
            crossed_into_oversold = rsi < self.rsi_buy_threshold and self._prev_rsi >= self.rsi_buy_threshold
            crossed_into_overbought = rsi > self.rsi_sell_threshold and self._prev_rsi <= self.rsi_sell_threshold
            if crossed_into_oversold and self.h1_close > self.h1_ema200.value:
                signal = EmaCrossSignal(
                    symbol=self.symbol, direction="BUY", signal_close_time_utc=candle.open_time_utc,
                    sl_price=None, tp_price=None, fast_ema=rsi, slow_ema=self.h1_ema200.value, atr_h1=atr,
                    sl_distance_price=self.atr_sl_multiple * atr,
                )
            elif crossed_into_overbought and self.h1_close < self.h1_ema200.value:
                signal = EmaCrossSignal(
                    symbol=self.symbol, direction="SELL", signal_close_time_utc=candle.open_time_utc,
                    sl_price=None, tp_price=None, fast_ema=rsi, slow_ema=self.h1_ema200.value, atr_h1=atr,
                    sl_distance_price=self.atr_sl_multiple * atr,
                )

        if sma_ready_before:
            self.last_exit_flags = DonchianExitFlags(
                close_long=candle.close > sma_before,
                close_short=candle.close < sma_before,
            )
        else:
            self.last_exit_flags = None

        self.sma.update(candle.close)
        self._prev_rsi = rsi
        return signal
