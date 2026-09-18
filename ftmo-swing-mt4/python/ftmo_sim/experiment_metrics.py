"""Full per-run metrics for the S1-S8 x C1-C3 comparison --
docs/EXPERIMENT_PLAN_2026-09-18.md section 4/deliverables.

Kept separate from report.py, which serves the existing single-run S1/S2/S3
baseline Markdown reports: this module's metric set is broader (an EXACT
commission/spread/slippage/swap cost breakdown, a worst-FTMO-calendar-day
figure, a monthly table splitting realized vs. still-open floating P/L,
R-multiple expectancy) and is written to work uniformly across every
result "shape" this project has (SimulationResult / EmaCrossResult /
M30SimulationResult) via duck typing on their common fields
(closed_trades, skipped_signals, equity_curve, risk_stop_events,
final_balance, final_equity, open_positions_at_end, and optionally
total_swap_usd).

Every number here is either an EXACT figure (derived from the same
formulas order_exec.py/account_risk.py already use to build the trade in
the first place, not re-estimated) or explicitly labeled as an
approximation with the reasoning stated -- never a plausible-looking
number invented for a gap in the data.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from .time_utils import ftmo_trading_day


def _per_unit_per_lot(spec) -> float:
    return spec.contract_size  # USD-quoted pairs only, matching symbol_spec.py


def trade_cost_breakdown(trade, spec, spread_price: float, slippage_price: float) -> dict:
    """EXACT commission/spread/slippage cost for one closed trade, derived
    from the same rules order_exec.py used to build entry_price/exit_price
    in the first place (not re-estimated from the net P/L):
    - spread: charged once per round trip on every trade, always (see
      order_exec.py's module docstring).
    - slippage: applied on the ENTRY fill always, and on the EXIT fill
      only if it was SL-triggered ("SL"/"SL_GAP") -- see
      docs/EXPERIMENT_PLAN_2026-09-18.md section 3 and
      order_exec._check_bar/force_close's slippage_price parameter.
    - commission: trade.commission_usd is already exact.
    """
    per_unit = _per_unit_per_lot(spec)
    spread_cost = spread_price * per_unit * trade.position.lots
    slippage_legs = 1 + (1 if trade.exit_reason in ("SL", "SL_GAP") else 0)
    slippage_cost = slippage_price * per_unit * trade.position.lots * slippage_legs
    return {
        "commission_usd": trade.commission_usd,
        "spread_cost_usd": spread_cost,
        "slippage_cost_usd": slippage_cost,
    }


def worst_ftmo_day(equity_curve: list[tuple], initial_balance: float) -> dict:
    """The FTMO-calendar-day (Europe/Prague) with the most negative
    end-of-day-minus-start-of-day SETTLED equity change -- the same
    quantity the daily working floor is measured against (balance/equity
    at the Prague-midnight boundary), not a true intraday minimum (this
    project's own M1-resolution equity curve makes an exact intraday
    minimum computable too, but the daily-floor-relevant quantity is the
    day's net change, which is what is reported here)."""
    if not equity_curve:
        return {"day": None, "net_change_usd": 0.0}
    by_day_last_point: dict = {}
    for t, eq, _bal in equity_curve:
        by_day_last_point[ftmo_trading_day(t)] = eq
    days = sorted(by_day_last_point.keys())
    prev_eq = initial_balance
    worst_day = None
    worst_change = None
    for d in days:
        end_eq = by_day_last_point[d]
        change = end_eq - prev_eq
        if worst_change is None or change < worst_change:
            worst_change = change
            worst_day = d
        prev_eq = end_eq
    return {"day": worst_day.isoformat() if worst_day else None, "net_change_usd": worst_change or 0.0}


def monthly_realized_vs_floating(
    result, initial_balance: float, full_calendar_months: set,
) -> list[dict]:
    """Monthly table split by Europe/Prague calendar month, separately
    showing REALIZED P/L (closed trades whose exit fell in that month) and
    the month-END floating P/L of anything still open at the very end of
    the whole run (only attributed to the LAST month in the sample, since
    that is the only month-end this project's fixed sample actually has --
    an interior month's positions were, by definition, already closed by
    the time that month ended, or this run would show them in a LATER
    month's realized total instead). Never marks a partial month as full;
    never annualizes."""
    by_month_realized: dict = defaultdict(float)
    by_month_trades: dict = defaultdict(int)
    for t in result.closed_trades:
        d = ftmo_trading_day(t.exit_time_utc)
        k = (d.year, d.month)
        by_month_realized[k] += t.net_pnl_usd
        by_month_trades[k] += 1

    # Attribute end-of-sample floating P/L (still-open positions) to the
    # LAST month actually present in the equity curve.
    floating_by_month: dict = defaultdict(float)
    if result.equity_curve and result.open_positions_at_end:
        last_t = result.equity_curve[-1][0]
        last_key = (ftmo_trading_day(last_t).year, ftmo_trading_day(last_t).month)
        floating_at_end = result.final_equity - result.final_balance
        floating_by_month[last_key] += floating_at_end

    all_months = sorted(set(by_month_realized) | set(floating_by_month))
    out = []
    month_start_equity = initial_balance
    equity_by_ftmo_day = {ftmo_trading_day(t): eq for t, eq, _ in result.equity_curve} if result.equity_curve else {}
    for (y, m) in all_months:
        realized = by_month_realized.get((y, m), 0.0)
        floating = floating_by_month.get((y, m), 0.0)
        is_full = (y, m) in full_calendar_months
        out.append({
            "year": y, "month": m, "is_full_calendar_month": is_full,
            "realized_usd": realized, "floating_at_sample_end_usd": floating,
            "trade_count": by_month_trades.get((y, m), 0),
            "realized_pct_of_initial_balance": 100.0 * realized / initial_balance,
            # month_start_equity below is a running approximation carried
            # from the previous month's end -- exact only if every prior
            # month's floating component (if any) is itself exact, which
            # it is here since only the LAST month can carry one.
            "realized_pct_of_month_start_equity": (100.0 * realized / month_start_equity) if month_start_equity else float("nan"),
        })
        month_start_equity += realized + floating
    return out


def full_metrics(
    result, config, variant: str, scenario: str,
    spread_price_by_symbol: dict, slippage_price: float,
    full_calendar_months: set,
) -> dict:
    initial_balance = config.initial_balance
    trades = result.closed_trades
    n = len(trades)
    wins = [t for t in trades if t.net_pnl_usd > 0]
    losses = [t for t in trades if t.net_pnl_usd <= 0]

    net_balance_usd = result.final_balance - initial_balance
    net_equity_usd = result.final_equity - initial_balance
    gross_win = sum(t.net_pnl_usd for t in wins)
    gross_loss = -sum(t.net_pnl_usd for t in losses)
    profit_factor = (gross_win / gross_loss) if gross_loss > 0 else (float("inf") if gross_win > 0 else float("nan"))
    win_rate_pct = (100.0 * len(wins) / n) if n else float("nan")
    avg_win_usd = (gross_win / len(wins)) if wins else float("nan")
    avg_loss_usd = (-gross_loss / len(losses)) if losses else float("nan")
    expectancy_usd = (sum(t.net_pnl_usd for t in trades) / n) if n else float("nan")
    r_values = [t.r_multiple_net for t in trades if t.r_multiple_net is not None]
    expectancy_r = (sum(r_values) / len(r_values)) if r_values else float("nan")

    cost_totals = defaultdict(float)
    for t in trades:
        spec = config.symbols[t.position.symbol]
        breakdown = trade_cost_breakdown(t, spec, spread_price_by_symbol[t.position.symbol], slippage_price)
        for k, v in breakdown.items():
            cost_totals[k] += v
    swap_total = getattr(result, "total_swap_usd", 0.0)

    holding_hours = [
        (t.exit_time_utc - t.position.entry_time_utc).total_seconds() / 3600.0 for t in trades
    ]
    avg_holding_hours = (sum(holding_hours) / len(holding_hours)) if holding_hours else float("nan")

    skip_reasons: dict = defaultdict(int)
    for sk in result.skipped_signals:
        skip_reasons[sk.reason] += 1

    risk_stop_breaches = [e for e in result.risk_stop_events if e[1] in ("DAILY_STOP", "TOTAL_STOP")]
    ambiguous = sum(1 for t in trades if t.same_bar_ambiguous)
    gap_fills = sum(1 for t in trades if t.exit_reason.endswith("_GAP"))

    from .report import lowest_equity, max_drawdown_from_peak

    return {
        "variant": variant,
        "scenario": scenario,
        "initial_balance_usd": initial_balance,
        "net_balance_change_usd": net_balance_usd,
        "net_balance_change_pct": 100.0 * net_balance_usd / initial_balance,
        "net_equity_change_usd": net_equity_usd,
        "net_equity_change_pct": 100.0 * net_equity_usd / initial_balance,
        "open_positions_at_end": {
            sym: {"direction": p.direction, "lots": p.lots, "entry_price": p.entry_price}
            for sym, p in result.open_positions_at_end.items()
        },
        "cost_breakdown_usd": {
            "commission": cost_totals["commission_usd"],
            "spread": cost_totals["spread_cost_usd"],
            "slippage": cost_totals["slippage_cost_usd"],
            "swap": swap_total,
        },
        "trade_count": n,
        "win_rate_pct": win_rate_pct,
        "avg_win_usd": avg_win_usd,
        "avg_loss_usd": avg_loss_usd,
        "expectancy_usd_per_trade": expectancy_usd,
        "expectancy_r_per_trade": expectancy_r,
        "profit_factor": profit_factor,
        "max_drawdown_from_peak_usd": max_drawdown_from_peak(result.equity_curve),
        "lowest_equity_usd": lowest_equity(result.equity_curve),
        "worst_ftmo_day": worst_ftmo_day(result.equity_curve, initial_balance),
        "working_floor_breach_count": len(risk_stop_breaches),
        "same_bar_sl_tp_ambiguous_count": ambiguous,
        "gap_fill_count": gap_fills,
        "avg_holding_time_hours": avg_holding_hours,
        "rejected_signal_counts_by_reason": dict(sorted(skip_reasons.items())),
        "monthly": monthly_realized_vs_floating(result, initial_balance, full_calendar_months),
    }
