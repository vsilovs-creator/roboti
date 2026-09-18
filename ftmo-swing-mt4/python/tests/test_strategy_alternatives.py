"""Unit tests for the two additional well-known strategies tried per the
account owner's explicit request to search for profit with any known
approach (2026-09-18): EMA(20/50) H1 crossover and Bollinger(20,2) H1
mean-reversion. Small periods are used here to keep fixtures short, same as
test_signals.py."""
from datetime import datetime, timezone

import pytest

from ftmo_sim.strategy_bb_reversion import BbReversionEngine
from ftmo_sim.strategy_ema_cross import EmaCrossEngine


def c(h, o, hi, lo, cl):
    from ftmo_sim.signals import Candle
    return Candle(open_time_utc=datetime(2026, 1, 5, h, 0, tzinfo=timezone.utc), open=o, high=hi, low=lo, close=cl)


def test_ema_cross_fires_on_crossover_not_every_bar():
    engine = EmaCrossEngine("TEST", fast_period=2, slow_period=3, atr_period=2, atr_sl_multiple=1.0, tp_r_multiple=2.0)
    closes = [1.00, 1.00, 1.00, 1.01, 1.05, 1.10]  # flat then a clean upmove
    signals = []
    for i, close in enumerate(closes):
        sig = engine.on_h1_candle(c(i, close, close + 0.001, close - 0.001, close))
        if sig is not None:
            signals.append(sig)
    assert len(signals) >= 1
    assert signals[0].direction == "BUY"
    assert signals[0].sl_price < signals[0].tp_price  # BUY: SL below entry, TP above


def test_ema_cross_requires_both_emas_ready_before_first_signal():
    engine = EmaCrossEngine("TEST", fast_period=5, slow_period=10, atr_period=5)
    # Fewer bars than slow_period -- must never emit a signal from partial state.
    for i in range(4):
        assert engine.on_h1_candle(c(i, 1.10, 1.101, 1.099, 1.10)) is None


def test_bb_reversion_fires_buy_below_lower_band():
    # period=10 rather than something smaller: with a very short period and
    # an otherwise-flat window, a single outlier's own contribution to the
    # stddev widens the band just enough to almost always contain itself --
    # a real, if counterintuitive, property of population-stddev Bollinger
    # Bands with few points, not a bug. period=10 avoids that edge case.
    engine = BbReversionEngine("TEST", period=10, num_std=2.0, atr_period=3)
    signal = None
    for i, close in enumerate([1.1000] * 9 + [1.0500]):
        signal = engine.on_h1_candle(c(i, close, close + 0.0005, close - 0.0005, close))
    assert signal is not None
    assert signal.direction == "BUY"
    assert signal.tp_price > signal.sl_price


def test_bb_reversion_no_signal_inside_bands():
    # Natural jitter across ALL points, not "n-1 identical + 1 outlier": with
    # only one differing point, that point's z-score is fixed by n alone
    # (not by how large the difference is), so it can spuriously sit exactly
    # at the band boundary regardless of magnitude -- realistic jitter avoids
    # that degenerate case and keeps the last close inside the band.
    engine = BbReversionEngine("TEST", period=10, num_std=2.0, atr_period=3)
    closes = [1.1000, 1.1003, 1.0998, 1.1002, 1.0999, 1.1001, 1.0997, 1.1004, 1.1000, 1.1002]
    signal = None
    for i, close in enumerate(closes):
        signal = engine.on_h1_candle(c(i, close, close + 0.0005, close - 0.0005, close))
    assert signal is None
