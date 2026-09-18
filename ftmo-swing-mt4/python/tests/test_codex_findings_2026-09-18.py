"""Regression tests for the five discrepancies an independent Codex review
found after reading FULL_REPORT.md / STRATEGY_RESEARCH_2026-09-18.md
(docs/CODEX_FINDINGS_2026-09-18.md, delivered as an uploaded file, not
committed to the repo by Codex itself). Each test is written to FAIL
against the pre-fix code and PASS once the corresponding fix lands --
run with `git stash` around the fix commit to confirm the fail/pass flip
if you need to re-verify after the fact.
"""
from __future__ import annotations

import importlib.util
import json
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from ftmo_sim.bars import RichCandle
from ftmo_sim.config import load_config
from ftmo_sim.experiment_metrics import full_metrics, monthly_realized_vs_floating, worst_ftmo_day
from ftmo_sim.order_exec import ClosedTrade, Position, open_position
from ftmo_sim.simulator_ema_cross import run_h1_signal_simulation
from ftmo_sim.strategy_ema_cross import EmaCrossSignal
from ftmo_sim.symbol_spec import SymbolSpec

CONFIG_PATH = Path(__file__).parent.parent.parent / "config" / "config.example.json"
BASE = datetime(2026, 8, 3, 7, 0, tzinfo=timezone.utc)

EURUSD_SPEC = SymbolSpec(
    name="EURUSD", digits=5, contract_size=100000, min_lot=0.01, max_lot=50.0,
    lot_step=0.01, swap_long_points=-11.06, swap_short_points=0.59,
    triple_swap_weekday=2, quote_currency="USD",
)


def _load_experiment_script():
    script_path = Path(__file__).parent.parent / "scripts" / "run_experiment_2026-09-18.py"
    spec = importlib.util.spec_from_file_location("run_experiment_codex_check", script_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------------------
# F1 -- scenario spread never reaches the simulator's config, only the
# reported spread_price_by_symbol used for cost-breakdown labeling.
# ---------------------------------------------------------------------------

def test_f1_scenario_spread_actually_reaches_the_simulator_config():
    mod = _load_experiment_script()
    cfg = load_config(CONFIG_PATH)
    seen_points = {}

    def spy(config, m1_by_symbol, **kwargs):
        seen_points["value"] = dict(config.spread_points_hypothetical)
        return run_h1_signal_simulation(config, m1_by_symbol, engine_factory=lambda s: _NullEngine())

    mod.run_ema_cross_simulation = spy  # patch the name run_one actually calls
    for scenario, expected in [("C1", {"EURUSD": 10.0, "GBPUSD": 15.0}),
                                ("C2", {"EURUSD": 20.0, "GBPUSD": 30.0}),
                                ("C3", {"EURUSD": 30.0, "GBPUSD": 45.0})]:
        seen_points.clear()
        run_cfg = load_config(CONFIG_PATH)
        mod.apply_scenario_to_config(run_cfg, scenario)  # exactly what run_all() does before calling run_one()
        mod.run_one("S2", scenario, run_cfg, {"EURUSD": [], "GBPUSD": []})
        assert seen_points["value"] == expected, (
            f"{scenario}: simulator received spread points {seen_points['value']}, "
            f"expected the scenario's own {expected} -- the scenario's spread must "
            f"reach the config actually passed into the simulator, not just the "
            f"reported spread_price_by_symbol."
        )


class _NullEngine:
    def on_h1_candle(self, candle):
        return None


# ---------------------------------------------------------------------------
# F2 -- an existing open position's risk view (used to gate a SIMULTANEOUS
# other-symbol entry) is marked from THIS SAME MINUTE's close/intrabar
# state instead of only what is known at this minute's open.
# ---------------------------------------------------------------------------

class _ScriptedOnce:
    def __init__(self, symbol, fire_at, sl=1.099, tp=1.12):
        self.symbol = symbol
        self.fire_at = fire_at
        self.sl = sl
        self.tp = tp
        self._fired = False

    def on_h1_candle(self, candle):
        if not self._fired and candle.open_time_utc == self.fire_at:
            self._fired = True
            return EmaCrossSignal(
                symbol=self.symbol, direction="BUY", signal_close_time_utc=candle.open_time_utc,
                sl_price=self.sl, tp_price=self.tp, fast_ema=0, slow_ema=0, atr_h1=0.001,
            )
        return None


def _f2_data(eur_last_minute_close: float):
    """121 M1 bars per symbol, BASE..BASE+120min. EURUSD's BUY signal fires
    off the 07:00 H1 candle (fills 08:00); GBPUSD's off the 08:00 H1 candle
    (fills 09:00). Every bar is flat at 1.10000 except EURUSD's very last
    minute (09:00, its own entry-bar's LATER-forming close), whose CLOSE
    (and, to make the leak unmistakable, its high) is varied while its OPEN
    stays fixed."""
    data = {}
    for symbol in ("EURUSD", "GBPUSD"):
        bars = []
        for i in range(121):
            t = BASE + timedelta(minutes=i)
            if symbol == "EURUSD" and i == 120:
                o, c = 1.10000, eur_last_minute_close
                h, l = max(o, c, 1.10010), min(o, c, 1.09990)
            else:
                o = h = l = c = 1.10000
                h, l = 1.10010, 1.09990
            bars.append(RichCandle(open_time_utc=t, open=o, high=h, low=l, close=c))
        data[symbol] = bars
    return data


def test_f2_same_minute_close_must_not_change_a_different_symbols_entry_at_the_open():
    cfg = load_config(CONFIG_PATH)
    engine_factory = lambda s: _ScriptedOnce(
        s, fire_at=BASE if s == "EURUSD" else BASE + timedelta(hours=1),
    )

    outcomes = []
    for eur_close in (1.10000, 1.10200):
        data = _f2_data(eur_close)
        result = run_h1_signal_simulation(load_config(CONFIG_PATH), data, engine_factory=engine_factory)
        gbp_open = "GBPUSD" in result.open_positions_at_end
        gbp_skip = [sk.reason for sk in result.skipped_signals if sk.signal.symbol == "GBPUSD"]
        outcomes.append((gbp_open, gbp_skip))

    assert outcomes[0] == outcomes[1], (
        "GBPUSD's 09:00-open entry decision changed depending on EURUSD's "
        f"09:00 minute CLOSE (a value not known at 09:00's open): {outcomes}"
    )


# ---------------------------------------------------------------------------
# F3 -- worst_ftmo_day compares end-of-day-to-end-of-day equity, not the
# day's lowest equity relative to that day's own B0 (midnight balance).
# ---------------------------------------------------------------------------

def test_f3_worst_ftmo_day_catches_an_intraday_dip_back_to_flat():
    # One Prague day: equity dips to 9700 (exactly B0-300) mid-day, then
    # recovers to 10000 by day's last observed point. balance stays 10000
    # throughout (no realized trades) -- a pure intraday floating dip.
    curve = [
        (BASE, 9700.0, 10000.0),
        (BASE + timedelta(hours=1), 10000.0, 10000.0),
    ]
    result = worst_ftmo_day(curve, initial_balance=10000.0)
    # The old end-of-day-vs-previous-end-of-day metric reports 0.0 here
    # (only the LAST point of the day is looked at) -- the real worst move
    # that day relative to its own B0=10000 was -300.
    assert result["net_change_usd"] <= -300.0 + 1e-9, (
        f"worst_ftmo_day missed a real -300 USD intraday dip back to B0; got {result}"
    )


# ---------------------------------------------------------------------------
# F4 -- the monthly table misses swap, only attributes end-of-sample
# floating P/L to the LAST month (an interior month's own month-end
# floating position gets silently dropped if it closes in a later month),
# and omits months with zero activity.
# ---------------------------------------------------------------------------

class _FakeResult:
    pass


def _trade(net, exit_time, commission=5.0):
    pos = Position(idea_id="i", symbol="EURUSD", direction="BUY", lots=1.0, entry_price=1.10,
                    sl=1.09, tp=1.11, entry_time_utc=exit_time - timedelta(hours=1), risk_usd_at_entry=25.0)
    return ClosedTrade(position=pos, exit_price=1.105, exit_time_utc=exit_time, exit_reason="TP",
                        same_bar_ambiguous=False, gross_pnl_usd=net + commission, commission_usd=commission,
                        net_pnl_usd=net, r_multiple_net=net / 25.0)


def test_f4_monthly_table_includes_swap_and_zero_activity_months():
    r = _FakeResult()
    r.closed_trades = [_trade(50.0, datetime(2026, 7, 10, 10, tzinfo=timezone.utc))]
    r.swap_ledger = [(datetime(2026, 7, 20, 0, tzinfo=timezone.utc), "EURUSD", "BUY", 1.0, -10.0)]
    r.equity_curve = [
        (datetime(2026, 7, 10, 10, tzinfo=timezone.utc), 10040.0, 10040.0),
        (datetime(2026, 7, 31, 23, tzinfo=timezone.utc), 10030.0, 10030.0),
        (datetime(2026, 8, 15, 10, tzinfo=timezone.utc), 10030.0, 10030.0),  # August: zero trades, zero swap
        (datetime(2026, 8, 31, 23, tzinfo=timezone.utc), 10030.0, 10030.0),
    ]
    r.open_positions_at_end = {}
    r.final_equity = 10030.0
    r.final_balance = 10030.0

    monthly = monthly_realized_vs_floating(r, initial_balance=10000.0, full_calendar_months=set())
    months_present = {(m["year"], m["month"]) for m in monthly}
    assert (2026, 8) in months_present, "August had zero trades and zero floating change but must still be reported"

    total_realized = sum(m["realized_usd"] for m in monthly)
    # 50 (trade) - 10 (swap) = 40 must show up somewhere in "realized" once
    # swap is included -- the old code drops the swap entirely.
    assert total_realized == pytest.approx(40.0), (
        f"monthly realized total {total_realized} does not include the -10 USD swap"
    )


def test_f4_interior_month_end_floating_is_not_silently_dropped():
    # A position opens in July, is STILL open at July's own last observed
    # point (a real floating P/L at that month boundary), and only closes
    # in August. July's OWN month-end floating P/L must not be zero just
    # because the position eventually closes in a later month.
    r = _FakeResult()
    r.closed_trades = [_trade(-20.0, datetime(2026, 8, 5, 10, tzinfo=timezone.utc))]
    r.swap_ledger = []
    r.equity_curve = [
        (datetime(2026, 7, 15, 10, tzinfo=timezone.utc), 10030.0, 10000.0),  # +30 floating, still open
        (datetime(2026, 7, 31, 23, tzinfo=timezone.utc), 10030.0, 10000.0),  # July's own month-end: still +30 floating
        (datetime(2026, 8, 5, 10, tzinfo=timezone.utc), 9980.0, 9980.0),     # closed in August at a loss
    ]
    r.open_positions_at_end = {}
    r.final_equity = 9980.0
    r.final_balance = 9980.0

    monthly = monthly_realized_vs_floating(r, initial_balance=10000.0, full_calendar_months=set())
    by_month = {(m["year"], m["month"]): m for m in monthly}
    assert by_month[(2026, 7)]["floating_at_month_end_usd"] == pytest.approx(30.0), (
        "July's own +30 USD month-end floating P/L must be reported for July, "
        "not silently zeroed just because the position later closed in August"
    )


# ---------------------------------------------------------------------------
# F5 -- open_position() never books the entry-side commission; the full
# round-turn commission is charged only at close, so a STILL-OPEN
# position's balance/equity never reflects its already-incurred entry
# commission at all.
# ---------------------------------------------------------------------------

def test_f5_entry_commission_is_booked_immediately_at_open():
    pos = open_position(
        "i1", "EURUSD", "BUY", 2.0, 1.10000, sl=1.09000, tp=1.12000,
        entry_time_utc=BASE, spread=0.0001, risk_usd_at_entry=100.0,
        commission_round_turn_usd_per_lot=5.0,
    )
    # 2.50 USD/lot/side (confirmed fact) * 2 lots = 5.00 USD entry-side commission,
    # which the OLD open_position() has no parameter for and never computes.
    assert getattr(pos, "entry_commission_usd", 0.0) == pytest.approx(5.0), (
        "open_position() must compute and expose the entry-side commission "
        "(2.50 USD/lot/side * lots) so the caller can book it to balance "
        "immediately, not only once the position eventually closes"
    )
