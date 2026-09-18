"""Regression tests for the two discrepancies an independent Codex review
found IN THE FIX COMMIT for the first round of Codex findings (commit
dd26f55), delivered as CODEX_FOLLOWUP_dd26f55_1.md (uploaded file, not
committed to the repo by Codex itself). Each test is written to FAIL
against the dd26f55 code and PASS once the corresponding fix lands.

R1: a pre-existing open position that gaps through its own SL/TP at this
bar's OPEN was checked in the SAME unified pass as a pure intrabar (high/
low) touch, deferred to AFTER discretionary/timeout exits and new
entries -- so a same-tick discretionary/timeout exit could fire FIRST and
mask the gap entirely, giving the wrong exit reason/price (and no
slippage on the exit leg, since a discretionary exit is never
slippage-adjusted).

R2: the monthly P/L table's `realized_usd` is still only the sum of
CLOSED trades' net P/L by exit month plus swap -- after the F5 fix
(entry-side commission booked immediately at open), a position that
OPENS in one month and stays open (or closes in a LATER month) causes a
real balance change in the month it opened that the old monthly table
never reflects, so summing the monthly table no longer reconciles with
the account's actual balance change.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace as NS

import pytest

from ftmo_sim.bars import RichCandle
from ftmo_sim.config import load_config
from ftmo_sim.experiment_metrics import monthly_realized_vs_floating
from ftmo_sim.simulator_ema_cross import run_h1_signal_simulation
from ftmo_sim.strategy_ema_cross import EmaCrossSignal

CONFIG_PATH = Path(__file__).parent.parent.parent / "config" / "config.example.json"


# ---------------------------------------------------------------------------
# R1 -- a gap-through SL/TP at this bar's open must be resolved BEFORE any
# discretionary/timeout exit or new entry decided at this same instant,
# never masked by one of those firing first.
# ---------------------------------------------------------------------------

def test_r1_gap_through_sl_is_resolved_before_a_same_tick_discretionary_exit():
    """Exact reproduction from CODEX_FOLLOWUP_dd26f55_1.md's R1 section:
    EURUSD BUY fills at 08:00 from a 07:00 H1 signal (SL=1.09900); the
    08:00 H1 candle emits a discretionary close_long flag, executable at
    09:00; the 09:00 M1 bar's own OPEN (1.09800) has already gapped past
    the SL. The correct exit is the mechanical SL_GAP fill at
    1.09800 - slippage = 1.09795, NOT the discretionary exit at the raw
    open (1.09800, no slippage) -- a stop-order fill takes priority over
    a discretionary decision at the same instant."""
    start = datetime(2026, 8, 3, 7, tzinfo=timezone.utc)

    class ExitEngine:
        def __init__(self, symbol):
            self.symbol = symbol
            self.last_exit_flags = None

        def on_h1_candle(self, candle):
            self.last_exit_flags = (
                NS(close_long=True, close_short=False)
                if candle.open_time_utc == start + timedelta(hours=1) else None
            )
            if candle.open_time_utc == start:
                return EmaCrossSignal(self.symbol, "BUY", candle.open_time_utc, 1.099, 1.12, 0, 0, 0.001)

    data = {"EURUSD": [
        RichCandle(
            start + timedelta(minutes=i),
            1.1 if i < 120 else 1.098,
            1.1001 if i < 120 else 1.0981,
            1.0999 if i < 120 else 1.0979,
            1.1 if i < 120 else 1.098,
        )
        for i in range(121)
    ]}

    r = run_h1_signal_simulation(
        load_config(CONFIG_PATH), data, engine_factory=ExitEngine, slippage_price=0.00005,
    )
    assert len(r.closed_trades) == 1
    trade = r.closed_trades[0]
    assert trade.exit_reason == "SL_GAP", (
        f"a same-tick discretionary exit masked the gapped SL: got {trade.exit_reason!r} "
        f"@ {trade.exit_price} instead of the mechanical stop-order fill SL_GAP @ 1.09795"
    )
    assert trade.exit_price == pytest.approx(1.09795)


# ---------------------------------------------------------------------------
# R2 -- the monthly table must reconcile exactly with the account's actual
# balance change, including a position's entry-side commission booked in
# the month it OPENED even if it closes (or is still open) in a later
# month.
# ---------------------------------------------------------------------------

def test_r2_monthly_balance_change_reconciles_across_a_month_boundary():
    """Exact reproduction from CODEX_FOLLOWUP_dd26f55_1.md's R2 section: a
    0.10-lot position with no price P/L, 0.25 USD entry commission booked
    in July, 0.25 USD exit commission booked in August (round-trip net
    P/L -0.50 USD, closed in August). The account's ACTUAL balance change
    is -0.25 USD in July and -0.25 USD in August (from the equity_curve's
    own balance component) -- not 0.00/-0.50, which is what summing
    closed-trade net P/L by exit month alone would give."""
    r = NS(
        closed_trades=[NS(exit_time_utc=datetime(2026, 8, 1, 10, tzinfo=timezone.utc), net_pnl_usd=-0.5)],
        swap_ledger=[],
        equity_curve=[
            (datetime(2026, 7, 31, 20, tzinfo=timezone.utc), 9999.75, 9999.75),
            (datetime(2026, 8, 1, 10, tzinfo=timezone.utc), 9999.5, 9999.5),
        ],
    )
    monthly = monthly_realized_vs_floating(r, 10000.0, set())
    by_month = {m["month"]: m for m in monthly}
    assert by_month[7]["balance_change_usd"] == pytest.approx(-0.25), (
        "July's own -0.25 USD balance change (the entry commission booked "
        "when the position opened) must show up for July, not be silently "
        "folded into August's figure just because the trade closes there"
    )
    assert by_month[8]["balance_change_usd"] == pytest.approx(-0.25)
    total = sum(m["balance_change_usd"] for m in monthly)
    assert total == pytest.approx(-0.5), "monthly balance changes must sum to the actual total balance change"
