"""S6 (Donchian H1 20/10 with an ATR stop) -- docs/EXPERIMENT_PLAN_2026-09-18.md
section 2. Uses small entry_period/exit_period/atr_period so the expected
thresholds can be hand-verified, not the real 20/10/14 production values
(those are exercised end-to-end via run_donchian_simulation elsewhere)."""
from datetime import datetime, timedelta, timezone

from ftmo_sim.bars import Candle
from ftmo_sim.strategy_donchian import DonchianAtrEngine

BASE = datetime(2026, 1, 5, 0, 0, tzinfo=timezone.utc)


def c(i, o, h, l, cl):
    return Candle(open_time_utc=BASE + timedelta(hours=i), open=o, high=h, low=l, close=cl)


def test_no_signal_before_warmup():
    eng = DonchianAtrEngine("EURUSD", entry_period=3, exit_period=2, atr_period=1, atr_sl_multiple=2.0)
    # Only 2 candles fed -- entry_period=3 not yet satisfied.
    assert eng.on_h1_candle(c(0, 1.0, 1.10, 0.90, 1.00)) is None
    assert eng.on_h1_candle(c(1, 1.0, 1.05, 0.95, 1.00)) is None


def test_buy_signal_when_close_breaks_above_prior_high_window():
    eng = DonchianAtrEngine("EURUSD", entry_period=3, exit_period=2, atr_period=1, atr_sl_multiple=2.0)
    eng.on_h1_candle(c(0, 1.0, 1.10, 0.95, 1.00))
    eng.on_h1_candle(c(1, 1.0, 1.11, 0.94, 1.00))
    eng.on_h1_candle(c(2, 1.0, 1.09, 0.96, 1.00))
    # Prior 3 highs = {1.10, 1.11, 1.09} -> u3 = 1.11. Close 1.12 breaks it.
    sig = eng.on_h1_candle(c(3, 1.05, 1.13, 1.04, 1.12))
    assert sig is not None
    assert sig.direction == "BUY"
    assert sig.sl_price is None  # anchored to actual fill, not signal close
    assert sig.tp_price is None  # no fixed TP
    assert sig.sl_distance_price is not None and sig.sl_distance_price > 0


def test_sell_signal_when_close_breaks_below_prior_low_window():
    eng = DonchianAtrEngine("EURUSD", entry_period=3, exit_period=2, atr_period=1, atr_sl_multiple=2.0)
    eng.on_h1_candle(c(0, 1.0, 1.10, 0.95, 1.00))
    eng.on_h1_candle(c(1, 1.0, 1.11, 0.94, 1.00))
    eng.on_h1_candle(c(2, 1.0, 1.09, 0.96, 1.00))
    # Prior 3 lows = {0.95, 0.94, 0.96} -> l3 = 0.94. Close 0.93 breaks it.
    sig = eng.on_h1_candle(c(3, 0.97, 0.98, 0.92, 0.93))
    assert sig is not None
    assert sig.direction == "SELL"


def test_no_trade_on_equal_to_boundary_touch():
    # Equal-to-boundary is not a breakout for the entry rule either
    # (strict > / < only, matching the spec's convention for S7 -- applied
    # here too since Donchian's own spec text also uses strict >/<).
    eng = DonchianAtrEngine("EURUSD", entry_period=3, exit_period=2, atr_period=1, atr_sl_multiple=2.0)
    eng.on_h1_candle(c(0, 1.0, 1.10, 0.95, 1.00))
    eng.on_h1_candle(c(1, 1.0, 1.11, 0.94, 1.00))
    eng.on_h1_candle(c(2, 1.0, 1.09, 0.96, 1.00))
    sig = eng.on_h1_candle(c(3, 1.0, 1.11, 0.96, 1.11))  # close == u3 exactly
    assert sig is None


def test_exit_flags_use_prior_window_excluding_current_candle():
    eng = DonchianAtrEngine("EURUSD", entry_period=3, exit_period=2, atr_period=1, atr_sl_multiple=2.0)
    eng.on_h1_candle(c(0, 1.0, 1.10, 0.95, 1.00))
    eng.on_h1_candle(c(1, 1.0, 1.05, 0.90, 1.00))  # exit window after 2 candles: highs{1.10,1.05} lows{0.95,0.90}
    # exit_period=2 satisfied now -- next candle's flags are evaluated
    # against {1.10,1.05}/{0.95,0.90}, excluding this candle's own bar.
    eng.on_h1_candle(c(2, 1.0, 1.02, 0.80, 0.85))  # close 0.85 < min(0.95,0.90)=0.90 -> close_long
    assert eng.last_exit_flags is not None
    assert eng.last_exit_flags.close_long is True
    assert eng.last_exit_flags.close_short is False


def test_exit_flags_close_short_symmetric():
    eng = DonchianAtrEngine("EURUSD", entry_period=3, exit_period=2, atr_period=1, atr_sl_multiple=2.0)
    eng.on_h1_candle(c(0, 1.0, 1.10, 0.95, 1.00))
    eng.on_h1_candle(c(1, 1.0, 1.05, 0.90, 1.00))
    eng.on_h1_candle(c(2, 1.0, 1.20, 1.15, 1.16))  # close 1.16 > max(1.10,1.05)=1.10 -> close_short
    assert eng.last_exit_flags.close_short is True
    assert eng.last_exit_flags.close_long is False
