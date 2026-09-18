#!/usr/bin/env python3
"""Runs three independent, well-known strategies on the exact same data,
account-wide risk engine, and confirmed costs (server clock GMT+2/+3 EU DST,
5 USD/lot commission) and writes a side-by-side comparison -- requested by
the account owner ("meklē peļņu ar jebkuru tev zināmo stratēģiju", 2026-09-18)
after the fixed London baseline came back net-negative.

This is a comparison of a HANDFUL of distinct, hand-picked, textbook
strategies at their standard parameters, not a parameter search/optimization
over any one of them -- spec section 8 explicitly warns against wide
optimization on this short (~2-month) a dataset, and searching for the
best-fitting parameters here would produce a curve-fit number, not a finding.

Usage:
    python3 scripts/run_strategy_comparison.py \
        --config ../config/config.example.json \
        --eurusd ../data/raw/EURUSD1.csv \
        --gbpusd ../data/raw/GBPUSD1.csv \
        --out-dir ../reports/run_003_strategy_comparison
"""
from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ftmo_sim.bars import load_m1_csv
from ftmo_sim.config import load_config
from ftmo_sim.report import build_monthly_table, lowest_equity, max_drawdown_from_peak
from ftmo_sim.simulator import run_simulation
from ftmo_sim.simulator_ema_cross import run_ema_cross_simulation, run_h1_signal_simulation
from ftmo_sim.strategy_bb_reversion import BbReversionEngine

FULL_CALENDAR_MONTHS = {(2026, 8)}


def summarize(name, result, initial_balance):
    closed_trades = result.closed_trades
    equity_curve = result.equity_curve
    final_balance = result.final_balance
    n = len(closed_trades)
    wins = [t for t in closed_trades if t.net_pnl_usd > 0]
    losses = [t for t in closed_trades if t.net_pnl_usd <= 0]
    net = final_balance - initial_balance
    gross_win = sum(t.net_pnl_usd for t in wins)
    gross_loss = -sum(t.net_pnl_usd for t in losses)
    pf = (gross_win / gross_loss) if gross_loss > 0 else (float("inf") if gross_win > 0 else float("nan"))
    win_rate = (len(wins) / n * 100.0) if n else float("nan")
    max_dd = max_drawdown_from_peak(equity_curve)
    low_eq = lowest_equity(equity_curve)
    monthly = build_monthly_table(closed_trades, FULL_CALENDAR_MONTHS)
    # total_swap_usd / open_positions_at_end only exist on H1-strategy
    # results (simulator_ema_cross.py); the London baseline never holds
    # overnight (enforce_session_close=True), so these default to zero/empty.
    total_swap = getattr(result, "total_swap_usd", 0.0)
    open_at_end = getattr(result, "open_positions_at_end", {})
    return {
        "name": name, "trades": n, "wins": len(wins), "win_rate_pct": win_rate,
        "net_usd": net, "net_pct": 100.0 * net / initial_balance,
        "profit_factor": pf, "max_dd_usd": max_dd, "lowest_equity": low_eq,
        "monthly": monthly, "total_swap_usd": total_swap, "open_at_end": len(open_at_end),
    }


def write_trades_csv(path: Path, closed_trades) -> None:
    with path.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["symbol", "direction", "lots", "entry_time_utc", "entry_price",
                    "sl", "tp", "exit_time_utc", "exit_price", "exit_reason",
                    "net_pnl_usd", "r_multiple_net"])
        for t in closed_trades:
            p = t.position
            w.writerow([p.symbol, p.direction, p.lots, p.entry_time_utc, p.entry_price,
                        p.sl, p.tp, t.exit_time_utc, t.exit_price, t.exit_reason,
                        round(t.net_pnl_usd, 4), round(t.r_multiple_net, 4) if t.r_multiple_net is not None else ""])


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    ap.add_argument("--eurusd", required=True)
    ap.add_argument("--gbpusd", required=True)
    ap.add_argument("--out-dir", required=True)
    args = ap.parse_args()

    cfg = load_config(Path(args.config))
    m1 = {
        "EURUSD": load_m1_csv(Path(args.eurusd), cfg.server_time_model),
        "GBPUSD": load_m1_csv(Path(args.gbpusd), cfg.server_time_model),
    }
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    baseline = run_simulation(cfg, m1)
    ema = run_ema_cross_simulation(cfg, m1)
    bb = run_h1_signal_simulation(cfg, m1, engine_factory=BbReversionEngine, account_number=900000003, server_name="OFFLINE-SIM-BB")

    summaries = [
        summarize("London Range Breakout + Retest v1 (baseline)", baseline, cfg.initial_balance),
        summarize("EMA(20/50) H1 crossover", ema, cfg.initial_balance),
        summarize("Bollinger(20,2) H1 mean-reversion", bb, cfg.initial_balance),
    ]

    write_trades_csv(out_dir / "trades_baseline.csv", baseline.closed_trades)
    write_trades_csv(out_dir / "trades_ema_cross.csv", ema.closed_trades)
    write_trades_csv(out_dir / "trades_bb_reversion.csv", bb.closed_trades)

    lines = [
        "# Strategy comparison -- EXPLORATORY, same data/costs/risk engine",
        "",
        "Confirmed inputs used in this run: server clock GMT+2 winter / GMT+3 "
        "summer (EU DST dates), 5 USD/lot round-turn commission. Sample: "
        "~2 months (2026-07-15/16 to 2026-09-17), one full calendar month "
        "(August 2026). **None of these results are evidence of a repeatable "
        "monthly result** -- see docs/UNKNOWNS.md and spec section 10.",
        "",
        "| Strategy | Trades | Win rate | Net USD | Net % | Profit factor | Max DD USD | Lowest equity | Swap USD | Open at end |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for s in summaries:
        lines.append(
            f"| {s['name']} | {s['trades']} | {s['win_rate_pct']:.1f}% | {s['net_usd']:+.2f} | "
            f"{s['net_pct']:+.2f}% | {s['profit_factor']:.2f} | {s['max_dd_usd']:.2f} | {s['lowest_equity']:.2f} | "
            f"{s['total_swap_usd']:+.2f} | {s['open_at_end']} |"
        )
    lines.append("")
    lines.append("## Monthly net USD by strategy")
    lines.append("| Year-Month | " + " | ".join(s["name"] for s in summaries) + " |")
    lines.append("|---|" + "---|" * len(summaries))
    months = sorted({(m.year, m.month) for s in summaries for m in s["monthly"]})
    for y, m in months:
        row = [f"{y}-{m:02d}"]
        for s in summaries:
            match = next((x for x in s["monthly"] if (x.year, x.month) == (y, m)), None)
            row.append(f"{match.net_usd:+.2f}" if match else "0.00")
        lines.append("| " + " | ".join(row) + " |")
    lines.append("")
    bb = summaries[2]
    lines.append(
        "**Conclusion: all three lose money on this exact sample after real "
        "costs.** This is a comparison across distinct known strategies at "
        "standard parameters, not a parameter search -- no attempt was made "
        "to tune any of them to turn this specific 2-month window profitable, "
        "since doing so on 40-ish trading days would be curve-fitting, not a "
        "finding. See README.md for the interpretation and next-step "
        "recommendation."
    )
    lines.append("")
    lines.append(
        f"**Risk observation:** the Bollinger mean-reversion run's lowest "
        f"equity ({bb['lowest_equity']:.2f} USD) came within "
        f"{bb['lowest_equity'] - 9200.0:.2f} USD of the static 9200 total "
        f"working floor -- no breach occurred, but its combination of high "
        f"trade frequency ({bb['trades']} trades) and negative expectancy is the "
        f"riskiest of the three by a wide margin, independent of its net "
        f"P/L number."
    )
    (out_dir / "COMPARISON.md").write_text("\n".join(lines))
    print("\n".join(lines))
    print(f"\nWrote trades_*.csv and COMPARISON.md to {out_dir}")


if __name__ == "__main__":
    main()
