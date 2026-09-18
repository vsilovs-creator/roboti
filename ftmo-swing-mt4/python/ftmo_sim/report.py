"""Turns a SimulationResult into the metrics table spec section 10 requires.

Every metric that needs data the ~2-month sample does not have (e.g. any
month other than August 2026 is a partial month) is reported as `N/A`, never
as a silently-computed number that looks validated. The whole report is
labeled EXPLORATORY: commission is unconfirmed, the server clock/DST model is
unverified, and two partial months plus one full month is not evidence of a
repeatable monthly result -- see docs/UNKNOWNS.md and spec section 10.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from .simulator import SimulationResult


@dataclass
class MonthStat:
    year: int
    month: int
    is_full_calendar_month: bool
    net_usd: float
    trade_count: int


def _month_key(dt):
    return (dt.year, dt.month)


def build_monthly_table(closed_trades: list, full_months: set) -> list[MonthStat]:
    by_month: dict = defaultdict(lambda: [0.0, 0])
    for t in closed_trades:
        k = _month_key(t.exit_time_utc)
        by_month[k][0] += t.net_pnl_usd
        by_month[k][1] += 1
    out = []
    for (y, m), (net, n) in sorted(by_month.items()):
        out.append(MonthStat(y, m, (y, m) in full_months, net, n))
    return out


def max_drawdown_from_peak(equity_curve: list[tuple]) -> float:
    if not equity_curve:
        return 0.0
    peak = equity_curve[0][1]
    max_dd = 0.0
    for _, eq, _ in equity_curve:
        peak = max(peak, eq)
        max_dd = max(max_dd, peak - eq)
    return max_dd


def lowest_equity(equity_curve: list[tuple]) -> float:
    return min((eq for _, eq, _ in equity_curve), default=float("nan"))


def build_report(
    result: SimulationResult,
    initial_balance: float,
    total_working_floor: float,
    full_calendar_months: set,
    commission_confirmed: bool,
    server_time_verified: bool,
) -> str:
    trades = result.closed_trades
    n = len(trades)
    wins = [t for t in trades if t.net_pnl_usd > 0]
    losses = [t for t in trades if t.net_pnl_usd <= 0]
    net_usd = result.final_balance - initial_balance
    net_pct = 100.0 * net_usd / initial_balance

    win_rate = (len(wins) / n * 100.0) if n else float("nan")
    avg_win_r = (sum(t.r_multiple_net for t in wins) / len(wins)) if wins else float("nan")
    avg_loss_r = (sum(t.r_multiple_net for t in losses) / len(losses)) if losses else float("nan")
    gross_win = sum(t.net_pnl_usd for t in wins)
    gross_loss = -sum(t.net_pnl_usd for t in losses)
    profit_factor = (gross_win / gross_loss) if gross_loss > 0 else float("inf") if gross_win > 0 else float("nan")
    expectancy_usd = (net_usd / n) if n else float("nan")

    max_dd = max_drawdown_from_peak(result.equity_curve)
    low_eq = lowest_equity(result.equity_curve)
    dist_to_total_floor = low_eq - total_working_floor

    ambiguous = sum(1 for t in trades if t.same_bar_ambiguous)
    gap_fills = sum(1 for t in trades if t.exit_reason.endswith("_GAP"))
    risk_stop_breaches = [e for e in result.risk_stop_events if e[1] in ("DAILY_STOP", "TOTAL_STOP")]
    skip_reasons: dict = defaultdict(int)
    for sk in result.skipped_signals:
        skip_reasons[sk.reason] += 1

    monthly = build_monthly_table(result.closed_trades, full_calendar_months)
    full_months = [m for m in monthly if m.is_full_calendar_month]
    worst_full_month = min(full_months, key=lambda m: m.net_usd) if full_months else None
    months_meeting_target = [m for m in full_months if m.net_usd >= 0.20 * initial_balance or m.net_usd >= 2000]
    share_meeting_target = (
        f"{len(months_meeting_target)}/{len(full_months)}" if full_months else "N/A (no full calendar month in sample)"
    )

    lines = []
    lines.append("# EXPLORATORY baseline run -- London Range Breakout + Retest v1")
    lines.append("")
    lines.append(
        "**Status: EXPLORATORY, not a validated FTMO result.** "
        + ("Commission is UNCONFIRMED (treated as 0 in this run). " if not commission_confirmed else "")
        + ("Server clock / DST model is UNVERIFIED (naive CSV timestamps assumed already UTC). " if not server_time_verified else "")
        + "Sample is ~2 months with exactly one full calendar month; see docs/UNKNOWNS.md and spec section 10."
    )
    lines.append("")
    lines.append("## Headline")
    lines.append(f"- Net: {net_usd:+.2f} USD ({net_pct:+.2f}%)")
    lines.append(f"- Trades: {n}")
    lines.append(f"- Win rate: {win_rate:.1f}%" if n else "- Win rate: N/A (0 trades)")
    lines.append(f"- Avg win R (net): {avg_win_r:.2f}" if wins else "- Avg win R: N/A (0 winning trades)")
    lines.append(f"- Avg loss R (net): {avg_loss_r:.2f}" if losses else "- Avg loss R: N/A (0 losing trades)")
    lines.append(f"- Expectancy: {expectancy_usd:+.2f} USD/trade" if n else "- Expectancy: N/A (0 trades)")
    lines.append(f"- Profit factor: {profit_factor:.2f}" if n else "- Profit factor: N/A (0 trades)")
    lines.append("")
    lines.append("## Drawdown / breach")
    lines.append(f"- Max equity drawdown from peak: {max_dd:.2f} USD")
    lines.append(f"- Lowest equity observed: {low_eq:.2f} USD (vs. {total_working_floor:.2f} static total floor, margin {dist_to_total_floor:+.2f})")
    lines.append(f"- Daily/total working-floor breaches: {len(risk_stop_breaches)}")
    lines.append(
        f"- Trades with SL/TP both reachable in one M1 candle (resolved SL-first, conservative): {ambiguous}/{n}"
        if n else "- Same-bar SL/TP ambiguity: N/A (0 trades)"
    )
    lines.append(f"- Trades filled via a gap past the stop level rather than at the exact level: {gap_fills}/{n}" if n else "- Gap fills: N/A")
    lines.append("")
    lines.append("## Signals skipped by risk control")
    if skip_reasons:
        for reason, count in sorted(skip_reasons.items()):
            lines.append(f"- {reason}: {count}")
    else:
        lines.append("- none")
    lines.append("")
    lines.append("## Monthly table")
    lines.append("| Year-Month | Full calendar month? | Net USD | Trades | >=2000 USD target met |")
    lines.append("|---|---|---|---|---|")
    for m in monthly:
        met = "yes" if (m.is_full_calendar_month and (m.net_usd >= 2000 or m.net_usd >= 0.20 * initial_balance)) else ("N/A (partial month)" if not m.is_full_calendar_month else "no")
        lines.append(f"| {m.year}-{m.month:02d} | {'yes' if m.is_full_calendar_month else 'no (partial)'} | {m.net_usd:+.2f} | {m.trade_count} | {met} |")
    lines.append("")
    lines.append(
        f"- Worst full calendar month: {worst_full_month.year}-{worst_full_month.month:02d} net {worst_full_month.net_usd:+.2f} USD"
        if worst_full_month else "- Worst full calendar month: N/A (no full calendar month in sample)"
    )
    lines.append(f"- Full calendar months meeting the >=2000 USD / 20% target: {share_meeting_target}")
    lines.append("")
    return "\n".join(lines)
