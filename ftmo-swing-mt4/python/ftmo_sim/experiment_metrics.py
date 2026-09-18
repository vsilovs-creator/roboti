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


def daily_floor_analysis(
    equity_curve: list[tuple],
    initial_balance: float,
    balance_at_midnight_by_day: dict | None = None,
    daily_working_buffer_offset_usd: float | None = None,
    static_total_working_floor_usd: float | None = None,
) -> list[dict]:
    """FIXED 2026-09-18 (Codex F3): per FTMO-calendar-day (Europe/Prague),
    using that day's OWN B0 (balance_at_midnight, from the simulator's
    persisted per-day ledger -- not the previous day's END equity, which
    is a different quantity FTMO's daily floor is never measured
    against), the day's LOWEST observed equity (not just its last point --
    the old worst_ftmo_day() compared end-of-day-to-end-of-day settled
    equity, which misses an intraday dip that fully recovers by the day's
    last observed point) and, from those two, an INDEPENDENTLY
    recomputed daily-floor and static-total-floor breach flag -- distinct
    from (and a cross-check on) whatever DAILY_STOP/TOTAL_STOP events the
    simulator itself happened to emit, per the plan's own reasoning that
    "0 events alone does not prove 0 breaches."

    `balance_at_midnight_by_day` should be the simulator result's own
    `balance_at_midnight_by_day` ledger (ISO date string -> USD); if not
    supplied (e.g. a standalone/test curve with no ledger), every day's
    B0 falls back to `initial_balance`, which is only exact for the FIRST
    day. `daily_working_buffer_offset_usd`/`static_total_working_floor_usd`
    default to this project's own confirmed 300/9200 USD robot limits if
    not supplied, so a caller that only has the raw curve (no config) can
    still get a meaningful analysis rather than an error."""
    if not equity_curve:
        return []
    buffer_offset = 300.0 if daily_working_buffer_offset_usd is None else daily_working_buffer_offset_usd
    static_floor = 9200.0 if static_total_working_floor_usd is None else static_total_working_floor_usd
    ledger = balance_at_midnight_by_day or {}

    by_day_values: dict = defaultdict(list)
    for t, eq, _bal in equity_curve:
        by_day_values[ftmo_trading_day(t)].append(eq)

    out = []
    for d in sorted(by_day_values.keys()):
        b0 = ledger.get(d.isoformat(), initial_balance)
        lowest = min(by_day_values[d])
        daily_floor = b0 - buffer_offset
        applicable_floor = max(daily_floor, static_floor)
        out.append({
            "day": d.isoformat(),
            "balance_at_midnight_usd": b0,
            "lowest_equity_that_day_usd": lowest,
            "worst_move_from_b0_usd": lowest - b0,
            "daily_working_floor_usd": daily_floor,
            "static_total_working_floor_usd": static_floor,
            "margin_to_applicable_floor_usd": lowest - applicable_floor,
            "daily_floor_breached": lowest <= daily_floor,
            "static_total_floor_breached": lowest <= static_floor,
        })
    return out


def worst_ftmo_day(
    equity_curve: list[tuple],
    initial_balance: float,
    balance_at_midnight_by_day: dict | None = None,
    daily_working_buffer_offset_usd: float | None = None,
    static_total_working_floor_usd: float | None = None,
) -> dict:
    """The FTMO-calendar-day (Europe/Prague) with the most negative move
    from that day's OWN B0 to its LOWEST observed equity that day (Codex
    F3) -- not an end-of-day-to-end-of-day SETTLED equity change, which
    misses an intraday dip that recovers by the day's last observed
    point. See daily_floor_analysis() for the full per-day breakdown this
    is derived from (including independently recomputed floor breaches)."""
    analysis = daily_floor_analysis(
        equity_curve, initial_balance, balance_at_midnight_by_day,
        daily_working_buffer_offset_usd, static_total_working_floor_usd,
    )
    if not analysis:
        return {"day": None, "net_change_usd": 0.0}
    worst = min(analysis, key=lambda d: d["worst_move_from_b0_usd"])
    return {"day": worst["day"], "net_change_usd": worst["worst_move_from_b0_usd"]}


def _months_between(first_day, last_day) -> list[tuple]:
    """Every (year, month) from first_day's month to last_day's month,
    inclusive -- so a month with zero trades and zero equity change still
    gets a row instead of silently disappearing (Codex F4)."""
    months = []
    y, m = first_day.year, first_day.month
    while (y, m) <= (last_day.year, last_day.month):
        months.append((y, m))
        m += 1
        if m > 12:
            m = 1
            y += 1
    return months


def monthly_realized_vs_floating(
    result, initial_balance: float, full_calendar_months: set,
) -> list[dict]:
    """FIXED 2026-09-18 (Codex F4): monthly table split by Europe/Prague
    calendar month, now:
    1. Includes swap (previously invisible in this table entirely --
       swap posts directly to balance, never to a ClosedTrade, so it was
       silently dropped; sum(monthly realized) used to differ from the
       actual net balance change by exactly the total swap).
    2. Attributes floating P/L at EVERY month's own last observed point
       (`floating_at_month_end_usd = that point's equity - balance`), not
       only the sample's overall LAST month -- an interior month whose
       still-open position later closes in a SUBSEQUENT month previously
       had its own real month-end floating P/L silently zeroed (the old
       comment's reasoning -- "an interior month's positions would
       already show up as realized" -- was simply wrong: they show up as
       realized in whichever month they actually CLOSE, which reveals
       nothing about what they were worth at an EARLIER month's own
       boundary).
    3. Includes every month between the sample's first and last observed
       point, even ones with zero trades and zero swap (a fully idle
       month, or every month after a working stop that closed everything).
    Never marks a partial month as full; never annualizes. Realized here
    includes both trade P/L and swap; the two are also reported
    separately for anyone who wants only one."""
    if not result.equity_curve:
        return []

    last_point_by_month: dict = {}
    for t, eq, bal in result.equity_curve:
        d = ftmo_trading_day(t)
        last_point_by_month[(d.year, d.month)] = (eq, bal)  # curve is chronological -> ends up as that month's LAST point

    by_month_trade_realized: dict = defaultdict(float)
    by_month_trades: dict = defaultdict(int)
    for tr in result.closed_trades:
        d = ftmo_trading_day(tr.exit_time_utc)
        k = (d.year, d.month)
        by_month_trade_realized[k] += tr.net_pnl_usd
        by_month_trades[k] += 1

    by_month_swap: dict = defaultdict(float)
    for entry in getattr(result, "swap_ledger", []):
        d = ftmo_trading_day(entry[0])
        by_month_swap[(d.year, d.month)] += entry[4]

    first_day = ftmo_trading_day(result.equity_curve[0][0])
    last_day = ftmo_trading_day(result.equity_curve[-1][0])

    out = []
    month_start_equity = initial_balance
    prev_floating = 0.0  # nothing was open before the sample started
    for (y, m) in _months_between(first_day, last_day):
        trade_realized = by_month_trade_realized.get((y, m), 0.0)
        swap_realized = by_month_swap.get((y, m), 0.0)
        realized = trade_realized + swap_realized
        point = last_point_by_month.get((y, m))
        floating_at_month_end = (point[0] - point[1]) if point is not None else prev_floating
        month_end_equity = point[0] if point is not None else (month_start_equity + realized)
        out.append({
            "year": y, "month": m,
            "is_full_calendar_month": (y, m) in full_calendar_months,
            "realized_usd": realized,
            "realized_trade_usd": trade_realized,
            "realized_swap_usd": swap_realized,
            "floating_at_month_end_usd": floating_at_month_end,
            "trade_count": by_month_trades.get((y, m), 0),
            "realized_pct_of_initial_balance": 100.0 * realized / initial_balance,
            "realized_pct_of_month_start_equity": (100.0 * realized / month_start_equity) if month_start_equity else float("nan"),
        })
        month_start_equity = month_end_equity
        prev_floating = floating_at_month_end
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

    balance_at_midnight_by_day = getattr(result, "balance_at_midnight_by_day", {})
    daily_analysis = daily_floor_analysis(
        result.equity_curve, initial_balance, balance_at_midnight_by_day,
        config.ftmo_limits.robot_daily_working_buffer_offset_usd,
        config.ftmo_limits.robot_total_working_floor_usd,
    )
    independently_recomputed_breach_count = sum(
        1 for d in daily_analysis if d["daily_floor_breached"] or d["static_total_floor_breached"]
    )

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
        "worst_ftmo_day": worst_ftmo_day(
            result.equity_curve, initial_balance, balance_at_midnight_by_day,
            config.ftmo_limits.robot_daily_working_buffer_offset_usd,
            config.ftmo_limits.robot_total_working_floor_usd,
        ),
        "daily_floor_analysis": daily_analysis,
        # FIXED 2026-09-18 (Codex F3): the simulator's own emitted
        # DAILY_STOP/TOTAL_STOP count is kept for reference, but is NOT
        # the authoritative breach count -- see
        # independently_recomputed_floor_breach_days below, recomputed
        # directly from the raw equity curve and each day's own B0,
        # which a report must prefer.
        "working_floor_breach_count": len(risk_stop_breaches),
        "independently_recomputed_floor_breach_days": independently_recomputed_breach_count,
        "same_bar_sl_tp_ambiguous_count": ambiguous,
        "gap_fill_count": gap_fills,
        "avg_holding_time_hours": avg_holding_hours,
        "rejected_signal_counts_by_reason": dict(sorted(skip_reasons.items())),
        "monthly": monthly_realized_vs_floating(result, initial_balance, full_calendar_months),
    }
