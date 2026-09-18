"""Regression test for a latent bug found while building
scripts/run_long_history_experiment.py: write_signals_csv() (in
scripts/run_experiment_2026-09-18.py, reused verbatim by the long-history
runner) assumed every skipped signal's own object has a
`signal_close_time_utc` field -- true for S2-S8's EmaCrossSignal, but
S1's own SignalEvent (signals.py) names the same concept
`retest_close_time_utc` instead. This never crashed on the ~2-month 2026
sample because S1 happened to have zero rejected signals there
(`rejected_signal_counts_by_reason: {}` in every existing S1 report),
but a real 8-year run DOES reject S1 signals and crashed immediately.
"""
from __future__ import annotations

import csv
import importlib.util
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from types import SimpleNamespace as NS


def _load_script():
    script_path = Path(__file__).parent.parent / "scripts" / "run_experiment_2026-09-18.py"
    spec = importlib.util.spec_from_file_location("run_experiment_signal_csv_check", script_path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def test_write_signals_csv_handles_s1s_signal_event_shape(tmp_path):
    mod = _load_script()
    from ftmo_sim.signals import SignalEvent

    s1_signal = SignalEvent(
        symbol="EURUSD", london_day=date(2020, 3, 2), direction="BUY",
        retest_close_time_utc=datetime(2020, 3, 2, 8, 0, tzinfo=timezone.utc),
        range_high=1.1, range_low=1.09, sl_price=1.089, tp_price=1.12,
        atr_m5_at_retest=0.001, h1_ema200_at_retest=1.095,
    )
    result = NS(
        skipped_signals=[NS(signal=s1_signal, reason="PRE_TRADE_PROJECTED_EQUITY_BREACH")],
        closed_trades=[], open_positions_at_end={},
    )
    out = tmp_path / "signals.csv"
    mod.write_signals_csv(out, result)  # must not raise

    rows = list(csv.reader(out.open()))
    assert rows[1][0] == "REJECTED"
    assert rows[1][3] == "2020-03-02 08:00:00+00:00"
    assert rows[1][5] == "PRE_TRADE_PROJECTED_EQUITY_BREACH"


def test_write_signals_csv_still_handles_ema_cross_signal_shape(tmp_path):
    """Confirms the fix didn't break the OTHER (S2-S8) shape it already
    handled correctly."""
    mod = _load_script()
    from ftmo_sim.strategy_ema_cross import EmaCrossSignal

    ema_signal = EmaCrossSignal(
        symbol="GBPUSD", direction="SELL",
        signal_close_time_utc=datetime(2021, 5, 1, 9, 0, tzinfo=timezone.utc),
        sl_price=1.4, tp_price=1.35, fast_ema=1.38, slow_ema=1.39, atr_h1=0.002,
    )
    result = NS(
        skipped_signals=[NS(signal=ema_signal, reason="RISK_STOP_ACTIVE_OR_UNRECONCILED")],
        closed_trades=[], open_positions_at_end={},
    )
    out = tmp_path / "signals.csv"
    mod.write_signals_csv(out, result)

    rows = list(csv.reader(out.open()))
    assert rows[1][3] == "2021-05-01 09:00:00+00:00"
    assert rows[1][5] == "RISK_STOP_ACTIVE_OR_UNRECONCILED"
