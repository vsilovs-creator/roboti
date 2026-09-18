"""S8 (RSI2 M30 pullback + H1 EMA200 filter) -- docs/EXPERIMENT_PLAN_2026-09-18.md
section 2, including the RSI edge cases the plan explicitly calls out."""
from datetime import datetime, timedelta, timezone

from ftmo_sim.bars import Candle
from ftmo_sim.strategy_rsi2_pullback_m30 import Rsi2PullbackM30Engine, WilderRsi

BASE = datetime(2026, 1, 5, 0, 0, tzinfo=timezone.utc)


def m30(i, o, h, l, cl):
    return Candle(open_time_utc=BASE + timedelta(minutes=30 * i), open=o, high=h, low=l, close=cl)


def h1(i, o, h, l, cl):
    return Candle(open_time_utc=BASE + timedelta(hours=i), open=o, high=h, low=l, close=cl)


def test_wilder_rsi_not_ready_before_warmup():
    rsi = WilderRsi(period=2)
    assert rsi.update(1.0) is None  # first call only seeds prev_close
    assert rsi.ready is False
    rsi.update(1.01)
    assert rsi.ready is False  # only 1 change observed, period=2 needs 2
    rsi.update(1.02)
    assert rsi.ready is True


def test_wilder_rsi_zero_movement_bar_contributes_zero_to_both_sums():
    rsi = WilderRsi(period=2)
    rsi.update(1.00)
    rsi.update(1.00)  # zero movement -- gain=0, loss=0
    rsi.update(1.00)
    assert rsi.ready is True
    # avg_gain == avg_loss == 0 on a fully flat window -> defined as 50.
    assert rsi.value == 50.0


def test_wilder_rsi_all_gains_no_losses_is_100_not_infinite():
    rsi = WilderRsi(period=2)
    rsi.update(1.00)
    rsi.update(1.01)  # +0.01
    rsi.update(1.02)  # +0.01
    assert rsi.ready is True
    assert rsi.avg_loss == 0.0
    assert rsi.value == 100.0  # never a ZeroDivisionError / inf / NaN


def test_wilder_rsi_all_losses_no_gains_is_zero():
    rsi = WilderRsi(period=2)
    rsi.update(1.02)
    rsi.update(1.01)
    rsi.update(1.00)
    assert rsi.ready is True
    assert rsi.avg_gain == 0.0
    assert rsi.value == 0.0


def _warm_h1_uptrend(eng, n=3):
    for i in range(n):
        eng.on_h1_candle(h1(i, 1.0, 1.01, 0.99, 1.0 + 0.01 * (i + 1)))


M30_CLOSES_INTO_OVERSOLD = [1.00, 1.02, 1.04, 1.01, 0.96, 0.91, 0.86]
# WilderRsi(period=2) on this exact sequence (verified numerically):
# [None, None, 100.0, 40.0, 13.33, 5.71, 2.67] -- >=5 through index 5,
# <5 for the first time at index 6 -- a genuine fresh crossing there.


def test_buy_signal_requires_fresh_rsi_crossing_and_h1_filter():
    eng = Rsi2PullbackM30Engine(
        "EURUSD", rsi_period=2, atr_period=1, atr_sl_multiple=1.5, sma_period=2,
        h1_ema_period=2, rsi_buy_threshold=5.0, rsi_sell_threshold=95.0,
    )
    # Feed H1 candles so EMA200(period=2 here) is ready and H1 close > EMA.
    eng.on_h1_candle(h1(0, 1.0, 1.0, 1.0, 1.00))
    eng.on_h1_candle(h1(1, 1.0, 1.0, 1.0, 1.02))
    assert eng.h1_ema200.ready
    assert eng.h1_close > eng.h1_ema200.value

    sig = None
    for i, close in enumerate(M30_CLOSES_INTO_OVERSOLD):
        sig = eng.on_m30_candle(m30(i, close, close, close, close))
    assert sig is not None  # only the LAST candle (the fresh crossing) fires
    assert sig.direction == "BUY"
    assert sig.sl_price is None
    assert sig.tp_price is None
    assert sig.sl_distance_price > 0


def test_no_buy_signal_when_h1_filter_disagrees():
    eng = Rsi2PullbackM30Engine(
        "EURUSD", rsi_period=2, atr_period=1, atr_sl_multiple=1.5, sma_period=2,
        h1_ema_period=2, rsi_buy_threshold=5.0, rsi_sell_threshold=95.0,
    )
    # H1 close BELOW EMA -- downtrend filter -- must block a BUY even with
    # the same RSI2 oversold crossing.
    eng.on_h1_candle(h1(0, 1.0, 1.0, 1.0, 1.02))
    eng.on_h1_candle(h1(1, 1.0, 1.0, 1.0, 1.00))
    assert eng.h1_close < eng.h1_ema200.value

    sig = None
    for i, close in enumerate(M30_CLOSES_INTO_OVERSOLD):
        sig = eng.on_m30_candle(m30(i, close, close, close, close))
    assert sig is None


def test_h1_exit_flags_flip_on_ema_breach():
    eng = Rsi2PullbackM30Engine("EURUSD", h1_ema_period=2)
    eng.on_h1_candle(h1(0, 1.0, 1.0, 1.0, 1.00))
    eng.on_h1_candle(h1(1, 1.0, 1.0, 1.0, 1.02))  # close 1.02, ema ~ (1.00+1.02)/2-ish, close>ema
    assert eng.last_h1_exit_flags.close_long is False  # close is above ema -- long not invalidated
    eng.on_h1_candle(h1(2, 1.0, 1.0, 1.0, 0.80))  # sharp drop -- close now well below ema
    assert eng.last_h1_exit_flags.close_long is True
    assert eng.last_h1_exit_flags.close_short is False
