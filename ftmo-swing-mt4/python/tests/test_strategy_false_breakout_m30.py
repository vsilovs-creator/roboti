"""S7 (M30 false-breakout-and-return) -- docs/EXPERIMENT_PLAN_2026-09-18.md
section 2. Small range_period/atr_period so thresholds are hand-verifiable."""
from datetime import datetime, timedelta, timezone

from ftmo_sim.bars import Candle
from ftmo_sim.strategy_false_breakout_m30 import FalseBreakoutM30Engine

BASE = datetime(2026, 1, 5, 0, 0, tzinfo=timezone.utc)


def c(i, o, h, l, cl):
    return Candle(open_time_utc=BASE + timedelta(minutes=30 * i), open=o, high=h, low=l, close=cl)


def _warm(eng, n=3, level=1.00):
    for i in range(n):
        eng.on_m30_candle(c(i, level, level, level, level))


def test_no_signal_before_warmup():
    eng = FalseBreakoutM30Engine("EURUSD", range_period=3, atr_period=1)
    assert eng.on_m30_candle(c(0, 1.0, 1.10, 0.90, 1.00)) is None
    assert eng.on_m30_candle(c(1, 1.0, 1.05, 0.95, 1.00)) is None


def test_sell_on_false_breakout_above_range_that_closes_back_inside():
    eng = FalseBreakoutM30Engine("EURUSD", range_period=3, atr_period=1, sl_atr_buffer_multiple=0.1)
    _warm(eng, n=3, level=1.00)  # U3=L3=1.00 after warmup (flat range)
    # Widen the range a bit first so U/L aren't degenerate.
    eng2 = FalseBreakoutM30Engine("EURUSD", range_period=3, atr_period=1, sl_atr_buffer_multiple=0.1)
    eng2.on_m30_candle(c(0, 1.00, 1.10, 0.95, 1.00))
    eng2.on_m30_candle(c(1, 1.00, 1.05, 0.96, 1.00))
    eng2.on_m30_candle(c(2, 1.00, 1.08, 0.97, 1.00))
    # U3 = max(1.10,1.05,1.08) = 1.10; L3 = min(0.95,0.96,0.97) = 0.95.
    # high breaks 1.10, close back inside (0.95, 1.10) -> SELL.
    sig = eng2.on_m30_candle(c(3, 1.05, 1.12, 1.04, 1.08))
    assert sig is not None
    assert sig.direction == "SELL"
    assert sig.tp_price == (1.10 + 0.95) / 2.0
    assert sig.sl_price > 1.12  # high + a positive ATR buffer


def test_buy_on_false_breakout_below_range_that_closes_back_inside():
    eng = FalseBreakoutM30Engine("EURUSD", range_period=3, atr_period=1, sl_atr_buffer_multiple=0.1)
    eng.on_m30_candle(c(0, 1.00, 1.10, 0.95, 1.00))
    eng.on_m30_candle(c(1, 1.00, 1.05, 0.96, 1.00))
    eng.on_m30_candle(c(2, 1.00, 1.08, 0.97, 1.00))
    # low breaks below L3=0.95, close back inside -> BUY.
    sig = eng.on_m30_candle(c(3, 0.96, 0.99, 0.93, 0.97))
    assert sig is not None
    assert sig.direction == "BUY"
    assert sig.sl_price < 0.93  # low - a positive ATR buffer


def test_no_trade_when_both_boundaries_breached_same_candle():
    eng = FalseBreakoutM30Engine("EURUSD", range_period=3, atr_period=1, sl_atr_buffer_multiple=0.1)
    eng.on_m30_candle(c(0, 1.00, 1.10, 0.95, 1.00))
    eng.on_m30_candle(c(1, 1.00, 1.05, 0.96, 1.00))
    eng.on_m30_candle(c(2, 1.00, 1.08, 0.97, 1.00))
    sig = eng.on_m30_candle(c(3, 1.00, 1.15, 0.90, 1.00))  # breaches both 1.10 high and 0.95 low
    assert sig is None


def test_no_trade_on_equal_to_boundary():
    eng = FalseBreakoutM30Engine("EURUSD", range_period=3, atr_period=1, sl_atr_buffer_multiple=0.1)
    eng.on_m30_candle(c(0, 1.00, 1.10, 0.95, 1.00))
    eng.on_m30_candle(c(1, 1.00, 1.05, 0.96, 1.00))
    eng.on_m30_candle(c(2, 1.00, 1.08, 0.97, 1.00))
    sig = eng.on_m30_candle(c(3, 1.00, 1.10, 0.97, 1.00))  # high == U3 exactly -- not a breakout
    assert sig is None


def test_breakout_that_closes_outside_range_is_not_a_signal():
    # Breaks the upper boundary but does NOT close back inside -- this is
    # a genuine breakout continuation, not the false-breakout-and-return
    # pattern S7 looks for.
    eng = FalseBreakoutM30Engine("EURUSD", range_period=3, atr_period=1, sl_atr_buffer_multiple=0.1)
    eng.on_m30_candle(c(0, 1.00, 1.10, 0.95, 1.00))
    eng.on_m30_candle(c(1, 1.00, 1.05, 0.96, 1.00))
    eng.on_m30_candle(c(2, 1.00, 1.08, 0.97, 1.00))
    sig = eng.on_m30_candle(c(3, 1.05, 1.15, 1.04, 1.12))  # closes at 1.12, still above U3=1.10
    assert sig is None
