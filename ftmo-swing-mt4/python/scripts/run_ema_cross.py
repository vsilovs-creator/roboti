#!/usr/bin/env python3
"""Runs the CHOSEN strategy going forward (2026-09-18, see
config/config.example.json's `strategies.active`): EMA(20/50) H1 crossover,
the smallest-loss of the three strategies compared in
reports/run_003_strategy_comparison/ on the only available ~2-month sample.

No further historical data will be supplied (account owner, 2026-09-18), so
this result cannot be re-validated against a fresh out-of-sample window --
"least-bad of three on one short sample" is not the same claim as
"validated" or "expected profitable". See README.md and docs/UNKNOWNS.md.

Usage:
    python3 scripts/run_ema_cross.py \
        --config ../config/config.example.json \
        --eurusd ../data/raw/EURUSD1.csv \
        --gbpusd ../data/raw/GBPUSD1.csv \
        --out-dir ../reports/run_004_ema_cross_chosen
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
from ftmo_sim.simulator_ema_cross import run_ema_cross_simulation

FULL_CALENDAR_MONTHS = {(2026, 8)}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    ap.add_argument("--eurusd", required=True)
    ap.add_argument("--gbpusd", required=True)
    ap.add_argument("--out-dir", required=True)
    args = ap.parse_args()

    cfg = load_config(Path(args.config))
    if cfg.active_strategy != "ema_cross_v1":
        print(f"NOTE: config['strategies']['active'] is {cfg.active_strategy!r}, not 'ema_cross_v1' -- "
              f"running the EMA crossover anyway since that is what this script does.")

    m1 = {
        "EURUSD": load_m1_csv(Path(args.eurusd), cfg.server_time_model),
        "GBPUSD": load_m1_csv(Path(args.gbpusd), cfg.server_time_model),
    }
    result = run_ema_cross_simulation(cfg, m1)

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    with (out_dir / "trades.csv").open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["symbol", "direction", "lots", "entry_time_utc", "entry_price",
                    "sl", "tp", "exit_time_utc", "exit_price", "exit_reason",
                    "risk_usd_at_entry", "gross_pnl_usd", "commission_usd",
                    "net_pnl_usd", "r_multiple_net"])
        for t in result.closed_trades:
            p = t.position
            w.writerow([p.symbol, p.direction, p.lots, p.entry_time_utc, p.entry_price,
                        p.sl, p.tp, t.exit_time_utc, t.exit_price, t.exit_reason,
                        round(p.risk_usd_at_entry, 4), round(t.gross_pnl_usd, 4),
                        round(t.commission_usd, 4), round(t.net_pnl_usd, 4),
                        round(t.r_multiple_net, 4) if t.r_multiple_net is not None else ""])

    with (out_dir / "skipped_signals.csv").open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["symbol", "direction", "signal_close_time_utc", "reason"])
        for sk in result.skipped_signals:
            s = sk.signal
            w.writerow([s.symbol, s.direction, s.signal_close_time_utc, sk.reason])

    with (out_dir / "risk_events.csv").open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["utc_time", "kind", "detail"])
        for e in result.risk_stop_events:
            w.writerow(list(e))

    n = len(result.closed_trades)
    wins = [t for t in result.closed_trades if t.net_pnl_usd > 0]
    losses = [t for t in result.closed_trades if t.net_pnl_usd <= 0]
    net = result.final_balance - cfg.initial_balance
    gross_win = sum(t.net_pnl_usd for t in wins)
    gross_loss = -sum(t.net_pnl_usd for t in losses)
    pf = (gross_win / gross_loss) if gross_loss > 0 else (float("inf") if gross_win > 0 else float("nan"))

    lines = [
        "# EMA(20/50) H1 crossover -- CHOSEN strategy going forward, EXPLORATORY",
        "",
        "**Status: EXPLORATORY, not a validated result.** Chosen as the "
        "smallest-loss of three strategies compared on the only available "
        "~2-month sample; no further historical data will be supplied, so "
        "this cannot be re-validated out-of-sample. See docs/UNKNOWNS.md.",
        "",
        f"- Net: {net:+.2f} USD ({100*net/cfg.initial_balance:+.2f}%)",
        f"- Trades: {n}, wins: {len(wins)} ({100*len(wins)/n:.1f}%)" if n else "- Trades: 0",
        f"- Profit factor: {pf:.2f}" if n else "- Profit factor: N/A",
        f"- Max drawdown from peak: {max_drawdown_from_peak(result.equity_curve):.2f} USD",
        f"- Lowest equity: {lowest_equity(result.equity_curve):.2f} USD (static total floor: "
        f"{cfg.ftmo_limits.robot_total_working_floor_usd:.2f})",
        f"- Daily/total risk-floor breaches: {len([e for e in result.risk_stop_events if e[1] in ('DAILY_STOP', 'TOTAL_STOP')])}",
        "",
        "## Monthly",
        "| Year-Month | Full month? | Net USD | Trades |",
        "|---|---|---|---|",
    ]
    for m in build_monthly_table(result.closed_trades, FULL_CALENDAR_MONTHS):
        lines.append(f"| {m.year}-{m.month:02d} | {'yes' if m.is_full_calendar_month else 'no (partial)'} | {m.net_usd:+.2f} | {m.trade_count} |")

    report_md = "\n".join(lines) + "\n"
    (out_dir / "REPORT.md").write_text(report_md)
    print(report_md)
    print(f"Wrote trades.csv, skipped_signals.csv, risk_events.csv, REPORT.md to {out_dir}")


if __name__ == "__main__":
    main()
