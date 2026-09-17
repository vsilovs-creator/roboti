"""London Range Breakout + Retest -- deterministic setup state machine.

Implements spec section 7 exactly as written, with every place the spec left
an ambiguity resolved to a conservative, explicitly documented choice (see the
docstrings below marked "Interpretation:"). This module only classifies M5/H1
closed candles into signal events; it does not know about spreads, lots, or
account risk (that is symbol_spec.py / account_risk.py) and does not decide
the fill price (that is the simulator's order-execution step, since a single
OHLC bar has no intrabar path).

No indicator or filter beyond what section 7 specifies has been added.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time
from enum import Enum, auto

from .time_utils import in_half_open_window, london_date, london_time_of_day

RANGE_START = time(0, 0)
RANGE_END = time(7, 0)
ENTRY_START = time(8, 0)
ENTRY_END = time(11, 0)
SESSION_CLOSE = time(16, 0)


@dataclass(frozen=True)
class Candle:
    open_time_utc: datetime
    open: float
    high: float
    low: float
    close: float


class WilderATR:
    """Wilder's ATR, simple-average seeded over the first `period` true
    ranges. This is the standard textbook definition; MetaTrader's iATR
    warmup/rounding may differ in the first few bars -- a paritātes (parity)
    test against the live MT4 indicator is required before relying on exact
    values near the warmup boundary (spec section 8)."""

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


class SeededEMA:
    """EMA seeded with a simple average over the first `period` closes, same
    caveat as WilderATR regarding exact parity with MT4's iMA(MODE_EMA)."""

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


class SetupState(Enum):
    WAITING_RANGE = auto()
    WAITING_BREAKOUT = auto()
    AWAITING_RETEST = auto()
    DONE_FOR_DAY = auto()
    DAY_SKIPPED = auto()


@dataclass
class DayOutcome:
    london_day: date
    reason: str
    detail: str = ""


@dataclass
class SignalEvent:
    symbol: str
    london_day: date
    direction: str  # "BUY" | "SELL"
    retest_close_time_utc: datetime
    range_high: float
    range_low: float
    sl_price: float
    tp_price: float
    atr_m5_at_retest: float
    h1_ema200_at_retest: float
    entry_reference: str = "next available quote after retest M5 candle close"


@dataclass
class _PendingSetup:
    direction: str
    bars_waited: int = 0


class LondonBreakoutRetestEngine:
    """One instance per symbol. Feed closed H1 candles via on_h1_candle() and
    closed M5 candles via on_m5_candle(), in correct chronological order.
    Interleaving must be correct: call on_h1_candle for an hour before
    calling on_m5_candle for any M5 bar opening after that hour has closed.
    """

    def __init__(
        self,
        symbol: str,
        retest_max_bars: int = 6,
        sl_atr_buffer_multiple: float = 0.10,
        atr_period: int = 14,
        ema_period: int = 200,
        tp_r_multiple: float = 2.0,
        min_range_coverage_ratio: float = 0.85,
    ):
        self.symbol = symbol
        self.retest_max_bars = retest_max_bars
        self.sl_atr_buffer_multiple = sl_atr_buffer_multiple
        self.tp_r_multiple = tp_r_multiple
        self.min_range_coverage_ratio = min_range_coverage_ratio
        # Expected M5 candles in a 7h window == 84.
        self._expected_range_candles = int(7 * 60 / 5)

        self.atr = WilderATR(atr_period)
        self.ema_h1 = SeededEMA(ema_period)

        self.state = SetupState.WAITING_RANGE
        self.current_day: date | None = None
        self.range_high: float | None = None
        self.range_low: float | None = None
        self.range_candle_count = 0
        self.prev_m5_close: float | None = None
        self.pending: _PendingSetup | None = None
        self.entry_taken_today = False
        self.last_closed_h1_close: float | None = None
        self.last_closed_h1_ema: float | None = None

        self.day_outcomes: list[DayOutcome] = []
        self.signals: list[SignalEvent] = []

    # -- H1 feed --------------------------------------------------------

    def on_h1_candle(self, candle: Candle) -> None:
        ema = self.ema_h1.update(candle.close)
        self.last_closed_h1_close = candle.close
        self.last_closed_h1_ema = ema

    # -- M5 feed ----------------------------------------------------------

    def on_m5_candle(self, candle: Candle) -> SignalEvent | None:
        self.atr.update(candle)
        day = london_date(candle.open_time_utc)
        tod = london_time_of_day(candle.open_time_utc)

        if day != self.current_day:
            self._start_new_day(day)

        if self.state == SetupState.DAY_SKIPPED:
            self.prev_m5_close = candle.close
            return None

        if in_half_open_window(tod, RANGE_START, RANGE_END):
            self._accumulate_range(candle)
            self.prev_m5_close = candle.close
            return None

        if self.state == SetupState.WAITING_RANGE:
            # Range window ended (or the first post-range candle arrived);
            # finalize the range now, once.
            self._finalize_range(day)

        if self.state == SetupState.DONE_FOR_DAY:
            self.prev_m5_close = candle.close
            return None

        event: SignalEvent | None = None
        in_entry_window = in_half_open_window(tod, ENTRY_START, ENTRY_END)

        if self.state == SetupState.WAITING_BREAKOUT:
            if in_entry_window and self.range_high is not None:
                direction = self._detect_breakout(candle)
                if direction is not None:
                    self.pending = _PendingSetup(direction=direction)
                    self.state = SetupState.AWAITING_RETEST
        elif self.state == SetupState.AWAITING_RETEST:
            event = self._process_retest(candle, tod)

        self.prev_m5_close = candle.close
        if event is not None:
            self.signals.append(event)
        return event

    # -- internals --------------------------------------------------------

    def _start_new_day(self, day: date) -> None:
        self.current_day = day
        self.state = SetupState.WAITING_RANGE
        self.range_high = None
        self.range_low = None
        self.range_candle_count = 0
        self.pending = None
        self.entry_taken_today = False

    def _accumulate_range(self, candle: Candle) -> None:
        self.range_candle_count += 1
        self.range_high = candle.high if self.range_high is None else max(self.range_high, candle.high)
        self.range_low = candle.low if self.range_low is None else min(self.range_low, candle.low)

    def _finalize_range(self, day: date) -> None:
        # No candles at all in the range window: cannot distinguish weekend
        # vs. a genuine data gap from here alone -- the caller (simulator)
        # tags weekends separately from data audit; here we record a neutral
        # reason and let the report layer combine it with the known calendar.
        if self.range_candle_count == 0:
            self.state = SetupState.DAY_SKIPPED
            self.day_outcomes.append(
                DayOutcome(day, "NO_RANGE_DATA", "zero M5 candles observed in [00:00,07:00) London")
            )
            return
        coverage = self.range_candle_count / self._expected_range_candles
        if coverage < self.min_range_coverage_ratio:
            self.state = SetupState.DAY_SKIPPED
            self.day_outcomes.append(
                DayOutcome(
                    day, "INSUFFICIENT_RANGE_COVERAGE",
                    f"{self.range_candle_count}/{self._expected_range_candles} M5 candles "
                    f"({coverage:.0%}) < required {self.min_range_coverage_ratio:.0%}",
                )
            )
            return
        self.state = SetupState.WAITING_BREAKOUT

    def _detect_breakout(self, candle: Candle) -> str | None:
        if self.prev_m5_close is None:
            return None
        h, l = self.range_high, self.range_low
        if candle.close > h and self.prev_m5_close <= h:
            return "BUY"
        if candle.close < l and self.prev_m5_close >= l:
            return "SELL"
        return None

    def _process_retest(self, candle: Candle, tod: time) -> SignalEvent | None:
        assert self.pending is not None
        self.pending.bars_waited += 1
        h, l = self.range_high, self.range_low

        if self.pending.direction == "BUY":
            if candle.high >= l and candle.low < l:
                # not applicable for BUY; guarded for symmetry only
                pass
            if candle.low < l:
                self._expire_setup()
                return None
            if candle.low <= h and candle.close > h:
                return self._confirm_retest(candle, tod, "BUY")
        else:
            if candle.high > h:
                self._expire_setup()
                return None
            if candle.high >= l and candle.close < l:
                return self._confirm_retest(candle, tod, "SELL")

        if self.pending.bars_waited >= self.retest_max_bars:
            self._expire_setup()
        return None

    def _expire_setup(self) -> None:
        self.pending = None
        self.state = SetupState.WAITING_BREAKOUT

    def _confirm_retest(self, candle: Candle, tod: time, direction: str) -> SignalEvent | None:
        if not in_half_open_window(tod, ENTRY_START, ENTRY_END):
            # Retest confirmed, but the allowed entry window already passed --
            # per spec rule 6, no entry is taken. Interpretation: the setup is
            # dropped rather than carried into the next day.
            self._expire_setup()
            return None
        if not self.atr.ready:
            self._expire_setup()
            return None
        if not self.ema_h1.ready or self.last_closed_h1_close is None:
            self._expire_setup()
            return None

        h1_close = self.last_closed_h1_close
        h1_ema = self.last_closed_h1_ema
        if direction == "BUY" and not (h1_close > h1_ema):
            self._expire_setup()
            return None
        if direction == "SELL" and not (h1_close < h1_ema):
            self._expire_setup()
            return None

        atr_buffer = self.sl_atr_buffer_multiple * self.atr.value
        if direction == "BUY":
            sl = candle.low - atr_buffer
            risk_distance = candle.close - sl  # placeholder; simulator recomputes from actual fill
        else:
            sl = candle.high + atr_buffer
            risk_distance = sl - candle.close

        if risk_distance <= 0:
            self._expire_setup()
            return None

        tp = candle.close + self.tp_r_multiple * risk_distance if direction == "BUY" else candle.close - self.tp_r_multiple * risk_distance

        event = SignalEvent(
            symbol=self.symbol,
            london_day=self.current_day,
            direction=direction,
            retest_close_time_utc=candle.open_time_utc,
            range_high=self.range_high,
            range_low=self.range_low,
            sl_price=sl,
            tp_price=tp,
            atr_m5_at_retest=self.atr.value,
            h1_ema200_at_retest=h1_ema,
        )
        self.entry_taken_today = True
        self.state = SetupState.DONE_FOR_DAY
        self.pending = None
        return event
