"""Regression tests for two P0 bugs found by an independent code audit
(2026-09-18, see docs/AUDIT_2026-09-18.md) in run_h1_signal_simulation:

1. A newly-opened position's own entry candle was never checked for
   SL/TP -- the exit-processing block ran BEFORE the position existed, so
   its own bar's intrabar move was silently skipped, turning what should
   have been a same-bar SL hit into a much worse "gap" exit on the
   following bar's open.
2. `new_idea_within_risk_caps` (the configured portfolio/correlated-group
   caps) was never called at all in this H1 simulator -- only the
   account-floor check ran, so `max_concurrent_risk_usd` and
   `correlated_group_max_risk_usd` had no effect regardless of value.

Both are fixed in simulator_ema_cross.py; these tests pin the fix down so
they can't silently regress.
"""
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from ftmo_sim.bars import RichCandle
from ftmo_sim.config import load_config
from ftmo_sim.order_exec import Position
from ftmo_sim.simulator_ema_cross import _swap_usd_for_one_night, run_h1_signal_simulation
from ftmo_sim.strategy_ema_cross import EmaCrossSignal
from ftmo_sim.symbol_spec import SymbolSpec

CONFIG_PATH = Path(__file__).parent.parent.parent / "config" / "config.example.json"

BASE = datetime(2026, 1, 5, 0, 0, tzinfo=timezone.utc)


def _flat_m1(symbol_price: float, hours: int = 12, kinks: dict | None = None) -> list[RichCandle]:
    kinks = kinks or {}
    bars = []
    t = BASE
    for _ in range(hours * 60):
        o = h = l = c = symbol_price
        if t in kinks:
            o, h, l, c = kinks[t]
        bars.append(RichCandle(open_time_utc=t, open=o, high=h, low=l, close=c))
        t += timedelta(minutes=1)
    return bars


class _OneShotSignalEngine:
    """Fires exactly one hand-crafted signal at a fixed H1 candle time."""

    def __init__(self, symbol, fire_at, direction="BUY", sl=1.09900, tp=1.20000):
        self.symbol = symbol
        self.fire_at = fire_at
        self.direction = direction
        self.sl = sl
        self.tp = tp
        self.fired = False

    def on_h1_candle(self, candle):
        if not self.fired and candle.open_time_utc == self.fire_at:
            self.fired = True
            return EmaCrossSignal(
                symbol=self.symbol, direction=self.direction, signal_close_time_utc=candle.open_time_utc,
                sl_price=self.sl, tp_price=self.tp, fast_ema=0, slow_ema=0, atr_h1=0,
            )
        return None


def test_entry_bar_sl_checked_not_skipped_to_next_bar_gap():
    cfg = load_config(CONFIG_PATH)
    entry_candle_time = BASE + timedelta(hours=11)
    kinks = {
        entry_candle_time: (1.10000, 1.10000, 1.09000, 1.09000),  # low breaches SL intrabar
        entry_candle_time + timedelta(minutes=1): (1.09000, 1.09000, 1.09000, 1.09000),
    }
    m1 = {
        "EURUSD": _flat_m1(1.10000, kinks=kinks),
        "GBPUSD": _flat_m1(1.30000),
    }
    engine_factory = lambda s: _OneShotSignalEngine(
        "EURUSD", fire_at=BASE + timedelta(hours=10),
    ) if s == "EURUSD" else _OneShotSignalEngine("GBPUSD", fire_at=BASE + timedelta(days=999))

    result = run_h1_signal_simulation(cfg, m1, engine_factory=engine_factory)
    assert len(result.closed_trades) == 1
    trade = result.closed_trades[0]
    # Fixed behavior: exits at the SL level, within the entry candle itself.
    assert trade.exit_reason == "SL"
    assert trade.exit_price == 1.09900
    # Loss should be close to the configured 25 USD risk budget, not the
    # ~223 USD a next-bar gap exit would produce.
    assert -30.0 < trade.net_pnl_usd < -20.0


def test_portfolio_cap_zero_blocks_all_entries():
    import json
    import tempfile

    raw = json.loads(CONFIG_PATH.read_text())
    raw["risk"]["max_concurrent_risk_usd"] = 0.0
    raw["risk"]["correlated_group_max_risk_usd"] = 0.0
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as tmp:
        json.dump(raw, tmp)
        tmp_path = Path(tmp.name)
    try:
        cfg = load_config(tmp_path)
        m1 = {"EURUSD": _flat_m1(1.10000), "GBPUSD": _flat_m1(1.30000)}
        engine_factory = lambda s: _OneShotSignalEngine(s, fire_at=BASE + timedelta(hours=10))
        result = run_h1_signal_simulation(cfg, m1, engine_factory=engine_factory)
        assert len(result.closed_trades) == 0
        assert any(sk.reason == "CORRELATED_OR_PORTFOLIO_RISK_CAP" for sk in result.skipped_signals)
    finally:
        tmp_path.unlink()


def test_correlated_group_cap_blocks_second_same_direction_symbol():
    import json
    import tempfile

    raw = json.loads(CONFIG_PATH.read_text())
    raw["risk"]["risk_per_idea_usd"] = 30.0  # 30+30=60 > 50 correlated cap
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as tmp:
        json.dump(raw, tmp)
        tmp_path = Path(tmp.name)
    try:
        cfg = load_config(tmp_path)
        fire_at = BASE + timedelta(hours=10)
        m1 = {"EURUSD": _flat_m1(1.10000), "GBPUSD": _flat_m1(1.30000)}
        sl_by_symbol = {"EURUSD": (1.09900, 1.20000), "GBPUSD": (1.29900, 1.40000)}
        engine_factory = lambda s: _OneShotSignalEngine(
            s, fire_at=fire_at, direction="BUY", sl=sl_by_symbol[s][0], tp=sl_by_symbol[s][1],
        )
        result = run_h1_signal_simulation(cfg, m1, engine_factory=engine_factory)
        # Both fire at the same H1 candle, same direction (both short-USD).
        # EURUSD is processed first and allowed (never appears in
        # skipped_signals; price is flat so it just stays open, hence not in
        # closed_trades either). GBPUSD must be blocked by the group cap.
        assert not any(sk.signal.symbol == "EURUSD" for sk in result.skipped_signals)
        gbp_skips = [sk for sk in result.skipped_signals if sk.signal.symbol == "GBPUSD"]
        assert len(gbp_skips) == 1
        assert gbp_skips[0].reason == "CORRELATED_OR_PORTFOLIO_RISK_CAP"
    finally:
        tmp_path.unlink()


EURUSD_SPEC = SymbolSpec(
    name="EURUSD", digits=5, contract_size=100000, min_lot=0.01, max_lot=50.0,
    lot_step=0.01, swap_long_points=-11.06, swap_short_points=0.59,
    triple_swap_weekday=2, quote_currency="USD",
)


def test_swap_usd_matches_hand_computed_value():
    pos = Position(
        idea_id="i1", symbol="EURUSD", direction="BUY", lots=2.0, entry_price=1.1000,
        sl=1.0950, tp=1.1100, entry_time_utc=None, risk_usd_at_entry=25.0,
    )
    # -11.06 points * 0.00001 point size * 100000 contract size * 2 lots = -22.12
    assert _swap_usd_for_one_night(pos, EURUSD_SPEC, night_starting_weekday=0) == pytest.approx(-22.12)
    # Same night but starting on the triple-swap weekday (Wednesday=2): x3.
    assert _swap_usd_for_one_night(pos, EURUSD_SPEC, night_starting_weekday=2) == pytest.approx(-66.36)


def test_swap_accrues_once_per_night_held_and_triples_on_wednesday():
    # 2026-01-05 is a Monday. A position opened that day and held flat
    # through the window crosses 4 FTMO-day rollovers: into Tue (normal),
    # into Wed (normal), into Thu (the night starting Wednesday -- tripled),
    # into Fri (normal). Total = 1 + 1 + 3 + 1 = 6 night-units.
    cfg = load_config(CONFIG_PATH)
    m1 = {
        "EURUSD": _flat_m1(1.10000, hours=4 * 24),
        "GBPUSD": _flat_m1(1.30000, hours=4 * 24),
    }
    engine_factory = lambda s: _OneShotSignalEngine(
        "EURUSD", fire_at=BASE + timedelta(hours=1),
    ) if s == "EURUSD" else _OneShotSignalEngine("GBPUSD", fire_at=BASE + timedelta(days=999))

    result = run_h1_signal_simulation(cfg, m1, engine_factory=engine_factory)
    assert len(result.closed_trades) == 0  # flat price, never hits SL/TP -- still open
    assert len(result.swap_ledger) == 4

    one_night = _swap_usd_for_one_night(
        Position(idea_id="x", symbol="EURUSD", direction="BUY", lots=result.swap_ledger[0][3],
                  entry_price=0, sl=0, tp=0, entry_time_utc=None, risk_usd_at_entry=0),
        cfg.symbols["EURUSD"], night_starting_weekday=0,
    )
    assert result.total_swap_usd == pytest.approx(6 * one_night)
    assert result.final_balance == pytest.approx(cfg.initial_balance + result.total_swap_usd)
