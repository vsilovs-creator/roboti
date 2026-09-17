"""London Range Breakout + Retest state machine -- spec section 7 rules and
section 9 test 11 (H1 warmup, EMA filter, 11:00 entry cutoff, one setup per
day). Small ATR/EMA periods are used here (vs. the 14/200 production
defaults) purely to keep fixtures short; the state-machine code paths
exercised are identical."""
from datetime import datetime, timezone

import pytest

from ftmo_sim.signals import Candle, LondonBreakoutRetestEngine, SeededEMA, WilderATR


def c(y, mo, d, h, mi, o, hi, lo, cl):
    return Candle(open_time_utc=datetime(y, mo, d, h, mi, tzinfo=timezone.utc), open=o, high=hi, low=lo, close=cl)


def _fresh_engine(**overrides):
    kwargs = dict(symbol="TEST", retest_max_bars=3, sl_atr_buffer_multiple=0.10, atr_period=3, ema_period=3, tp_r_multiple=2.0, min_range_coverage_ratio=0.0)
    kwargs.update(overrides)
    return LondonBreakoutRetestEngine(**kwargs)


def _feed_h1_warmup(engine, closes, start_hour_utc_day_before=21):
    for i, close in enumerate(closes):
        engine.on_h1_candle(c(2026, 1, 4, start_hour_utc_day_before + i, 0, close, close + 0.0002, close - 0.0002, close))


def test_wilder_atr_hand_computed():
    atr = WilderATR(period=2)
    a = c(2026, 1, 1, 0, 0, 1.0, 1.10, 0.95, 1.05)  # TR1 = 0.15 (no prev close)
    b = c(2026, 1, 1, 0, 5, 1.05, 1.20, 1.00, 1.10)  # TR2 = max(0.20, |1.20-1.05|=0.15, |1.00-1.05|=0.05) = 0.20
    atr.update(a)
    assert atr.value is None
    atr.update(b)
    assert atr.value == pytest.approx((0.15 + 0.20) / 2)


def test_seeded_ema_matches_simple_average_at_seed_point():
    ema = SeededEMA(period=3)
    for close in (1.10, 1.11, 1.12):
        val = ema.update(close)
    assert val == pytest.approx((1.10 + 1.11 + 1.12) / 3)


def test_happy_path_buy_signal():
    engine = _fresh_engine()
    _feed_h1_warmup(engine, [1.0990, 1.0995, 1.1000])  # last close 1.1000 > ema ~1.0995

    engine.on_m5_candle(c(2026, 1, 5, 0, 0, 1.1010, 1.1050, 1.1005, 1.1020))
    engine.on_m5_candle(c(2026, 1, 5, 0, 5, 1.1020, 1.1030, 1.1000, 1.1010))  # range: H=1.1050 L=1.1000
    engine.on_m5_candle(c(2026, 1, 5, 7, 5, 1.1015, 1.1020, 1.1010, 1.1015))  # ATR warmup filler, post-range pre-entry

    breakout = c(2026, 1, 5, 8, 5, 1.1040, 1.1070, 1.1035, 1.1060)  # close 1.1060 > H
    assert engine.on_m5_candle(breakout) is None
    assert engine.state.name == "AWAITING_RETEST"

    retest = c(2026, 1, 5, 8, 10, 1.1055, 1.1058, 1.1045, 1.1052)  # low<=H, close>H
    event = engine.on_m5_candle(retest)

    assert event is not None
    assert event.direction == "BUY"
    assert event.range_high == 1.1050 and event.range_low == 1.1000
    expected_sl = retest.low - 0.10 * event.atr_m5_at_retest
    assert event.sl_price == pytest.approx(expected_sl)
    expected_tp = retest.close + 2.0 * (retest.close - expected_sl)
    assert event.tp_price == pytest.approx(expected_tp)
    assert engine.state.name == "DONE_FOR_DAY"


def test_opposite_boundary_invalidates_setup_but_day_continues():
    engine = _fresh_engine()
    _feed_h1_warmup(engine, [1.0990, 1.0995, 1.1000])
    engine.on_m5_candle(c(2026, 1, 5, 0, 0, 1.1010, 1.1050, 1.1005, 1.1020))
    engine.on_m5_candle(c(2026, 1, 5, 0, 5, 1.1020, 1.1030, 1.1000, 1.1010))
    engine.on_m5_candle(c(2026, 1, 5, 7, 5, 1.1015, 1.1020, 1.1010, 1.1015))

    engine.on_m5_candle(c(2026, 1, 5, 8, 5, 1.1040, 1.1070, 1.1035, 1.1060))  # BUY breakout
    assert engine.state.name == "AWAITING_RETEST"

    # Price falls back through the opposite (low) boundary before retesting.
    invalidator = c(2026, 1, 5, 8, 10, 1.1030, 1.1035, 1.0995, 1.1000)
    assert engine.on_m5_candle(invalidator) is None
    assert engine.state.name == "WAITING_BREAKOUT"  # ready for a fresh setup, not DONE_FOR_DAY


def test_retest_expires_after_max_bars():
    engine = _fresh_engine(retest_max_bars=2)
    _feed_h1_warmup(engine, [1.0990, 1.0995, 1.1000])
    engine.on_m5_candle(c(2026, 1, 5, 0, 0, 1.1010, 1.1050, 1.1005, 1.1020))
    engine.on_m5_candle(c(2026, 1, 5, 0, 5, 1.1020, 1.1030, 1.1000, 1.1010))
    engine.on_m5_candle(c(2026, 1, 5, 7, 5, 1.1015, 1.1020, 1.1010, 1.1015))
    engine.on_m5_candle(c(2026, 1, 5, 8, 5, 1.1040, 1.1070, 1.1035, 1.1060))  # breakout

    # Two bars that neither confirm nor invalidate.
    engine.on_m5_candle(c(2026, 1, 5, 8, 10, 1.1060, 1.1065, 1.1055, 1.1058))
    assert engine.state.name == "AWAITING_RETEST"
    engine.on_m5_candle(c(2026, 1, 5, 8, 15, 1.1058, 1.1062, 1.1053, 1.1056))
    assert engine.state.name == "WAITING_BREAKOUT"  # expired after retest_max_bars


def test_ema_filter_blocks_signal_when_h1_disagrees():
    engine = _fresh_engine()
    # Downtrend H1 closes: last close BELOW ema -> blocks a BUY setup.
    _feed_h1_warmup(engine, [1.1010, 1.1005, 1.1000])
    engine.on_m5_candle(c(2026, 1, 5, 0, 0, 1.1010, 1.1050, 1.1005, 1.1020))
    engine.on_m5_candle(c(2026, 1, 5, 0, 5, 1.1020, 1.1030, 1.1000, 1.1010))
    engine.on_m5_candle(c(2026, 1, 5, 7, 5, 1.1015, 1.1020, 1.1010, 1.1015))
    engine.on_m5_candle(c(2026, 1, 5, 8, 5, 1.1040, 1.1070, 1.1035, 1.1060))
    retest = c(2026, 1, 5, 8, 10, 1.1055, 1.1058, 1.1045, 1.1052)
    event = engine.on_m5_candle(retest)
    assert event is None


def test_insufficient_h1_warmup_means_no_signal():
    engine = _fresh_engine()
    _feed_h1_warmup(engine, [1.0990, 1.0995])  # only 2 of 3 required -- EMA not ready
    engine.on_m5_candle(c(2026, 1, 5, 0, 0, 1.1010, 1.1050, 1.1005, 1.1020))
    engine.on_m5_candle(c(2026, 1, 5, 0, 5, 1.1020, 1.1030, 1.1000, 1.1010))
    engine.on_m5_candle(c(2026, 1, 5, 7, 5, 1.1015, 1.1020, 1.1010, 1.1015))
    engine.on_m5_candle(c(2026, 1, 5, 8, 5, 1.1040, 1.1070, 1.1035, 1.1060))
    retest = c(2026, 1, 5, 8, 10, 1.1055, 1.1058, 1.1045, 1.1052)
    assert engine.on_m5_candle(retest) is None


def test_retest_confirmed_after_1100_is_dropped_not_entered():
    engine = _fresh_engine(retest_max_bars=40)
    _feed_h1_warmup(engine, [1.0990, 1.0995, 1.1000])
    engine.on_m5_candle(c(2026, 1, 5, 0, 0, 1.1010, 1.1050, 1.1005, 1.1020))
    engine.on_m5_candle(c(2026, 1, 5, 0, 5, 1.1020, 1.1030, 1.1000, 1.1010))
    engine.on_m5_candle(c(2026, 1, 5, 7, 5, 1.1015, 1.1020, 1.1010, 1.1015))
    engine.on_m5_candle(c(2026, 1, 5, 10, 58, 1.1040, 1.1070, 1.1035, 1.1060))  # breakout just before 11:00
    # Retest only confirms once the window has already passed.
    retest = c(2026, 1, 5, 11, 5, 1.1055, 1.1058, 1.1045, 1.1052)
    assert engine.on_m5_candle(retest) is None


def test_only_one_signal_per_symbol_per_london_day():
    engine = _fresh_engine()
    _feed_h1_warmup(engine, [1.0990, 1.0995, 1.1000])
    engine.on_m5_candle(c(2026, 1, 5, 0, 0, 1.1010, 1.1050, 1.1005, 1.1020))
    engine.on_m5_candle(c(2026, 1, 5, 0, 5, 1.1020, 1.1030, 1.1000, 1.1010))
    engine.on_m5_candle(c(2026, 1, 5, 7, 5, 1.1015, 1.1020, 1.1010, 1.1015))
    engine.on_m5_candle(c(2026, 1, 5, 8, 5, 1.1040, 1.1070, 1.1035, 1.1060))
    event = engine.on_m5_candle(c(2026, 1, 5, 8, 10, 1.1055, 1.1058, 1.1045, 1.1052))
    assert event is not None

    # A second, otherwise-valid breakout later the same day must not fire.
    second = engine.on_m5_candle(c(2026, 1, 5, 9, 0, 1.1060, 1.1090, 1.1055, 1.1085))
    assert second is None
    assert engine.state.name == "DONE_FOR_DAY"


def test_day_with_zero_range_candles_is_skipped_not_fabricated():
    engine = _fresh_engine()
    _feed_h1_warmup(engine, [1.0990, 1.0995, 1.1000])
    # First M5 candle of the day arrives only at 08:00 -- no range data at all.
    engine.on_m5_candle(c(2026, 1, 5, 8, 0, 1.1010, 1.1015, 1.1005, 1.1010))
    assert engine.state.name == "DAY_SKIPPED"
    assert engine.day_outcomes[-1].reason == "NO_RANGE_DATA"
