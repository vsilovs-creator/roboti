"""Regression test for the same P0 event-ordering bug fixed in
simulator_ema_cross.py (see test_simulator_ema_cross_regressions.py),
independently confirmed to also exist in simulator.py (the London breakout
baseline) by an code audit (2026-09-18): a position opened at a bar's open
was never checked against that SAME bar's own high/low, so a same-bar SL
touch was silently skipped and only caught, far worse, as a "gap" exit on
the FOLLOWING bar's open.

This uses the real supplied data (skipped if unavailable) as a whole-sample
invariant check rather than a hand-built fixture, because simulator.py
builds its LondonBreakoutRetestEngine instances internally (no injectable
engine_factory the way simulator_ema_cross.py has), which makes a small
synthetic repro impractical without an intrusive refactor.
"""
from pathlib import Path

import pytest

from ftmo_sim.bars import load_m1_csv
from ftmo_sim.config import load_config
from ftmo_sim.order_exec import spread_price
from ftmo_sim.simulator import run_simulation

CONFIG_PATH = Path(__file__).parent.parent.parent / "config" / "config.example.json"
DATA_RAW = Path(__file__).parent.parent.parent / "data" / "raw"


@pytest.mark.skipif(
    not (DATA_RAW / "EURUSD1.csv").exists() or not (DATA_RAW / "GBPUSD1.csv").exists(),
    reason="raw CSVs not present in this checkout",
)
def test_no_trade_exits_via_gap_when_entry_bar_itself_breached_sl():
    cfg = load_config(CONFIG_PATH)
    m1 = {
        "EURUSD": load_m1_csv(DATA_RAW / "EURUSD1.csv", cfg.server_time_model),
        "GBPUSD": load_m1_csv(DATA_RAW / "GBPUSD1.csv", cfg.server_time_model),
    }
    result = run_simulation(cfg, m1)
    assert len(result.closed_trades) > 0  # sanity: the fixture still produces trades at all

    entry_bar_by_symbol_time = {
        s: {c.open_time_utc: c for c in m1[s]} for s in m1
    }
    spreads = {s: spread_price(s, cfg.symbols[s], cfg.spread_points_hypothetical) for s in m1}
    for trade in result.closed_trades:
        pos = trade.position
        entry_bar = entry_bar_by_symbol_time[pos.symbol].get(pos.entry_time_utc)
        if entry_bar is None:
            continue
        # Only the "the price actually used for the exit check was already
        # fine at open, but the bar's own low/high crosses the SL intrabar"
        # case is unambiguous -- when that same exit-side price (bid for a
        # BUY, ask for a SELL -- see order_exec.py's _check_bar) already
        # sits at/through the SL right at open, a "gap" exit there is
        # correct, not a sign of the entry-bar-skipped bug.
        if pos.direction == "BUY":
            open_already_past_sl = entry_bar.open <= pos.sl
            entry_bar_breaches_sl = entry_bar.low <= pos.sl
        else:
            ask_open = entry_bar.open + spreads[pos.symbol]
            open_already_past_sl = ask_open >= pos.sl
            entry_bar_breaches_sl = (entry_bar.high + spreads[pos.symbol]) >= pos.sl
        if entry_bar_breaches_sl and not open_already_past_sl:
            # The fix requires this to close on the ENTRY bar itself, not a
            # later bar via a "gap" exit that skipped the entry bar's own
            # intrabar move.
            assert trade.exit_time_utc == pos.entry_time_utc
            assert trade.exit_reason == "SL"
