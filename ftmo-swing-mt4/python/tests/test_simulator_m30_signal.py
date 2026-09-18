"""Integration tests for S7 through the full M30 runner --
docs/EXPERIMENT_PLAN_2026-09-18.md section 2/4."""
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from ftmo_sim.bars import RichCandle
from ftmo_sim.config import load_config
from ftmo_sim.simulator_m30_signal import run_m30_signal_simulation
from ftmo_sim.strategy_false_breakout_m30 import FalseBreakoutM30Engine

CONFIG_PATH = Path(__file__).parent.parent.parent / "config" / "config.example.json"
BASE = datetime(2026, 1, 5, 0, 0, tzinfo=timezone.utc)


def _m30_bucket_m1(bucket_index: int, open_, high_, low_, close_) -> list[RichCandle]:
    t = BASE + timedelta(minutes=30 * bucket_index)
    bars = [RichCandle(open_time_utc=t, open=open_, high=open_, low=open_, close=open_)]
    bars.append(RichCandle(open_time_utc=t + timedelta(minutes=1), open=open_, high=high_, low=low_, close=close_))
    for m in range(2, 30):
        bars.append(RichCandle(open_time_utc=t + timedelta(minutes=m), open=close_, high=close_, low=close_, close=close_))
    return bars


def _flat_m30_buckets(price: float, start: int, count: int) -> list[RichCandle]:
    out = []
    for i in range(start, start + count):
        out += _m30_bucket_m1(i, price, price, price, price)
    return out


def _inert_engine_factory():
    return lambda s: FalseBreakoutM30Engine(s, range_period=999, atr_period=1)


def test_false_breakout_entry_timing_price_and_fixed_tp():
    cfg = load_config(CONFIG_PATH)
    engine_factory = lambda s: (
        FalseBreakoutM30Engine(s, range_period=3, atr_period=1, sl_atr_buffer_multiple=0.1)
        if s == "EURUSD" else FalseBreakoutM30Engine(s, range_period=999, atr_period=1)
    )

    eur_m1 = []
    eur_m1 += _m30_bucket_m1(0, 1.10000, 1.10030, 1.09980, 1.10000)
    eur_m1 += _m30_bucket_m1(1, 1.10000, 1.10020, 1.09990, 1.10000)
    eur_m1 += _m30_bucket_m1(2, 1.10000, 1.10010, 1.09985, 1.10000)
    # U3=1.10030, L3=1.09980. High breaks U3, closes back inside -> SELL.
    eur_m1 += _m30_bucket_m1(3, 1.10010, 1.10060, 1.10000, 1.10020)
    # Fill bucket -- flat, between the SL (~1.10066) and TP (mid=1.10005).
    eur_m1 += _flat_m30_buckets(1.10020, start=4, count=14)

    m1 = {"EURUSD": eur_m1, "GBPUSD": _flat_m30_buckets(1.30000, start=0, count=18)}
    result = run_m30_signal_simulation(
        cfg, m1, engine_factory=engine_factory, timeout_m30_candles=8,
    )

    # Should have opened, then closed by TIMEOUT (see next test for the
    # exact timing) -- here just check the fill itself was correct.
    trade = result.closed_trades[0]
    assert trade.position.direction == "SELL"
    assert trade.position.entry_time_utc == BASE + timedelta(minutes=30 * 4)
    assert trade.position.entry_price == pytest.approx(1.10020)  # SELL transacts at Bid, no spread
    assert trade.position.tp == pytest.approx((1.10030 + 1.09980) / 2.0)


def test_timeout_exit_fires_after_8_full_candles_excluding_entry_candle():
    cfg = load_config(CONFIG_PATH)
    engine_factory = lambda s: (
        FalseBreakoutM30Engine(s, range_period=3, atr_period=1, sl_atr_buffer_multiple=0.1)
        if s == "EURUSD" else FalseBreakoutM30Engine(s, range_period=999, atr_period=1)
    )

    eur_m1 = []
    eur_m1 += _m30_bucket_m1(0, 1.10000, 1.10030, 1.09980, 1.10000)
    eur_m1 += _m30_bucket_m1(1, 1.10000, 1.10020, 1.09990, 1.10000)
    eur_m1 += _m30_bucket_m1(2, 1.10000, 1.10010, 1.09985, 1.10000)
    eur_m1 += _m30_bucket_m1(3, 1.10010, 1.10060, 1.10000, 1.10020)  # SELL signal, fills at bucket 4
    # Entry candle (bucket 4) + 8 counted candles (5..12) = buckets 4..12
    # flat, well between SL and TP -- neither triggers. Timeout fires at
    # bucket 13's M1 open.
    eur_m1 += _flat_m30_buckets(1.10020, start=4, count=10)

    m1 = {"EURUSD": eur_m1, "GBPUSD": _flat_m30_buckets(1.30000, start=0, count=14)}
    result = run_m30_signal_simulation(
        cfg, m1, engine_factory=engine_factory, timeout_m30_candles=8,
    )

    assert result.open_positions_at_end == {}
    assert len(result.closed_trades) == 1
    trade = result.closed_trades[0]
    assert trade.exit_reason == "TIMEOUT_EXIT"
    assert trade.exit_time_utc == BASE + timedelta(minutes=30 * 13)
    # A SELL position closes by BUYING BACK at Ask = open + spread.
    assert trade.exit_price == pytest.approx(1.10020 + cfg.symbols["EURUSD"].point_size * 10)


class _RecorderEngine:
    """Records the exact order on_h1_candle()/on_m30_candle() are called
    in -- used to pin down the H1/M30 merge timing S8 depends on (an H1
    candle's close must be fed to the engine no later than an M30 candle
    that closes at or after it, and strictly before one that closes
    before it)."""

    def __init__(self, symbol):
        self.symbol = symbol
        self.calls = []

    def on_h1_candle(self, candle):
        self.calls.append(("H1_CLOSE", candle.open_time_utc + timedelta(hours=1)))

    def on_m30_candle(self, candle):
        self.calls.append(("M30_CLOSE", candle.open_time_utc + timedelta(minutes=30)))
        return None


def test_h1_and_m30_are_merged_by_their_own_close_time_not_m30_open_time():
    """Regression: an earlier version of the merge sorted M30 candles by
    OPEN time instead of close time, which fed each M30 candle to the
    engine one whole M30 period too early relative to an H1 close landing
    on that exact M30 boundary -- e.g. bucket1 (closing at t=60, the SAME
    instant H1 candle0 also closes) would have been processed at t=30,
    before H1 candle0's close was known, instead of after it as required."""
    cfg = load_config(CONFIG_PATH)
    recorder = _RecorderEngine("EURUSD")
    engine_factory = lambda s: recorder if s == "EURUSD" else FalseBreakoutM30Engine(s, range_period=999, atr_period=1)

    m1 = {
        "EURUSD": _flat_m30_buckets(1.10000, start=0, count=4),  # 2 full H1 candles (buckets 0-1, 2-3)
        "GBPUSD": _flat_m30_buckets(1.30000, start=0, count=4),
    }
    run_m30_signal_simulation(cfg, m1, engine_factory=engine_factory, timeout_m30_candles=8)

    kinds_and_times = recorder.calls
    # Every event's own close time, in the order they were fed to the engine.
    times_in_call_order = [t for _, t in kinds_and_times]
    assert times_in_call_order == sorted(times_in_call_order)
    # The H1 close at t=60 must appear on or before the M30 close for
    # bucket1 (also t=60) -- and strictly before bucket2's close (t=90).
    h1_close_60 = BASE + timedelta(minutes=60)
    idx_h1 = kinds_and_times.index(("H1_CLOSE", h1_close_60))
    idx_bucket1_m30 = kinds_and_times.index(("M30_CLOSE", h1_close_60))
    idx_bucket2_m30 = kinds_and_times.index(("M30_CLOSE", BASE + timedelta(minutes=90)))
    assert idx_h1 < idx_bucket2_m30
    assert idx_h1 <= idx_bucket1_m30  # tie -- H1 processed first, per convention


def test_tp_not_on_profit_side_of_fill_is_skipped_not_sent_inverted():
    """A large adverse slippage on entry can push the fill past the fixed
    TP -- the entry must be skipped, never sent with an inverted or
    zero-distance TP."""
    cfg = load_config(CONFIG_PATH)
    engine_factory = lambda s: (
        FalseBreakoutM30Engine(s, range_period=3, atr_period=1, sl_atr_buffer_multiple=0.1)
        if s == "EURUSD" else FalseBreakoutM30Engine(s, range_period=999, atr_period=1)
    )

    eur_m1 = []
    eur_m1 += _m30_bucket_m1(0, 1.10000, 1.10030, 1.09980, 1.10000)
    eur_m1 += _m30_bucket_m1(1, 1.10000, 1.10020, 1.09990, 1.10000)
    eur_m1 += _m30_bucket_m1(2, 1.10000, 1.10010, 1.09985, 1.10000)
    eur_m1 += _m30_bucket_m1(3, 1.10010, 1.10060, 1.10000, 1.10020)  # SELL, TP = mid = 1.10005
    eur_m1 += _flat_m30_buckets(1.10020, start=4, count=10)

    m1 = {"EURUSD": eur_m1, "GBPUSD": _flat_m30_buckets(1.30000, start=0, count=14)}
    # A SELL fills at Bid with no spread but IS slippage-adjusted adverse
    # (receives LESS) -- a big enough slippage pushes the fill price below
    # the fixed TP=1.10005, inverting the TP side for a SELL.
    result = run_m30_signal_simulation(
        cfg, m1, engine_factory=engine_factory, timeout_m30_candles=8,
        slippage_price=0.00020,
    )
    assert len(result.closed_trades) == 0
    assert any(sk.reason == "TP_NOT_ON_PROFIT_SIDE_OF_FILL" for sk in result.skipped_signals)
