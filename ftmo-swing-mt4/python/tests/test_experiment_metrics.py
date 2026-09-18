"""Unit tests for the harder derived metrics in experiment_metrics.py --
docs/EXPERIMENT_PLAN_2026-09-18.md section 4/deliverables."""
from datetime import datetime, timedelta, timezone

from ftmo_sim.experiment_metrics import monthly_realized_vs_floating, trade_cost_breakdown, worst_ftmo_day
from ftmo_sim.order_exec import ClosedTrade, Position
from ftmo_sim.symbol_spec import SymbolSpec

EURUSD = SymbolSpec(
    name="EURUSD", digits=5, contract_size=100000, min_lot=0.01, max_lot=50.0,
    lot_step=0.01, swap_long_points=-11.06, swap_short_points=0.59,
    triple_swap_weekday=2, quote_currency="USD",
)
BASE = datetime(2026, 1, 5, 10, 0, tzinfo=timezone.utc)


def _trade(exit_reason, lots=1.0, exit_time=None, entry_time=None, net=0.0, commission=5.0):
    pos = Position(
        idea_id="i1", symbol="EURUSD", direction="BUY", lots=lots, entry_price=1.10,
        sl=1.09, tp=1.11, entry_time_utc=entry_time or BASE, risk_usd_at_entry=25.0,
    )
    return ClosedTrade(
        position=pos, exit_price=1.105, exit_time_utc=exit_time or (BASE + timedelta(hours=2)),
        exit_reason=exit_reason, same_bar_ambiguous=False,
        gross_pnl_usd=net + commission, commission_usd=commission, net_pnl_usd=net,
        r_multiple_net=net / 25.0,
    )


def test_cost_breakdown_slippage_applies_to_entry_always_and_sl_exit_only():
    spread = 0.0001
    slippage = 0.00005
    sl_trade = _trade("SL", lots=2.0)
    breakdown_sl = trade_cost_breakdown(sl_trade, EURUSD, spread, slippage)
    assert breakdown_sl["spread_cost_usd"] == spread * EURUSD.contract_size * 2.0
    # entry (1 leg) + SL exit (1 leg) = 2 slippage legs.
    assert breakdown_sl["slippage_cost_usd"] == slippage * EURUSD.contract_size * 2.0 * 2

    tp_trade = _trade("TP", lots=2.0)
    breakdown_tp = trade_cost_breakdown(tp_trade, EURUSD, spread, slippage)
    # entry only (TP exit is not slippage-adjusted) = 1 leg.
    assert breakdown_tp["slippage_cost_usd"] == slippage * EURUSD.contract_size * 2.0 * 1


def test_worst_ftmo_day_picks_the_most_negative_daily_change():
    equity_curve = [
        (BASE, 10000.0, 10000.0),
        (BASE + timedelta(hours=12), 9950.0, 9950.0),  # day 1 ends down 50
        (BASE + timedelta(days=1, hours=1), 9900.0, 9900.0),  # day 2 opens, ends down another 50
        (BASE + timedelta(days=1, hours=12), 10100.0, 10100.0),  # day 2 recovers to +150 net for the day
        (BASE + timedelta(days=2, hours=1), 9500.0, 9500.0),  # day 3 -- a big -600 drop
    ]
    result = worst_ftmo_day(equity_curve, initial_balance=10000.0)
    from ftmo_sim.time_utils import ftmo_trading_day
    assert result["day"] == ftmo_trading_day(BASE + timedelta(days=2, hours=1)).isoformat()
    assert result["net_change_usd"] == 9500.0 - 10100.0


def test_monthly_realized_vs_floating_attributes_end_floating_to_last_month():
    class FakeResult:
        pass

    r = FakeResult()
    r.closed_trades = [
        _trade("TP", net=50.0, exit_time=datetime(2026, 8, 15, 10, tzinfo=timezone.utc)),
        _trade("SL", net=-30.0, exit_time=datetime(2026, 9, 3, 10, tzinfo=timezone.utc)),
    ]
    r.equity_curve = [
        (datetime(2026, 8, 15, 10, tzinfo=timezone.utc), 10050.0, 10050.0),
        (datetime(2026, 9, 10, 10, tzinfo=timezone.utc), 10040.0, 10020.0),  # still 20 USD floating open
    ]
    r.open_positions_at_end = {"EURUSD": object()}
    r.final_equity = 10040.0
    r.final_balance = 10020.0

    monthly = monthly_realized_vs_floating(r, initial_balance=10000.0, full_calendar_months={(2026, 8)})
    by_month = {(m["year"], m["month"]): m for m in monthly}
    assert by_month[(2026, 8)]["realized_usd"] == 50.0
    assert by_month[(2026, 8)]["is_full_calendar_month"] is True
    assert by_month[(2026, 8)]["floating_at_sample_end_usd"] == 0.0
    assert by_month[(2026, 9)]["realized_usd"] == -30.0
    assert by_month[(2026, 9)]["is_full_calendar_month"] is False
    assert by_month[(2026, 9)]["floating_at_sample_end_usd"] == 20.0
