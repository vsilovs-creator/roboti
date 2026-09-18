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
