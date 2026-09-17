#!/usr/bin/env python3
"""Run the fixed London Range Breakout + Retest v1 baseline on the supplied
EURUSD1.csv / GBPUSD1.csv over the shared, single-account portfolio
simulator, and write a trade log + EXPLORATORY report.

Usage:
    python3 scripts/run_baseline.py \
        --config ../config/config.example.json \
        --eurusd ../data/raw/EURUSD1.csv \
        --gbpusd ../data/raw/GBPUSD1.csv \
        --out-dir ../reports/run_001

This is EXPLORATORY research output only -- see the printed report header
and docs/UNKNOWNS.md before drawing any conclusion from it.
"""
from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ftmo_sim.bars import load_m1_csv
from ftmo_sim.config import load_config
from ftmo_sim.report import build_report
from ftmo_sim.simulator import run_simulation


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
    result = run_simulation(cfg, m1)

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    with (out_dir / "trades.csv").open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow([
            "symbol", "direction", "lots", "entry_time_utc", "entry_price",
            "sl", "tp", "exit_time_utc", "exit_price", "exit_reason",
            "same_bar_ambiguous", "risk_usd_at_entry", "gross_pnl_usd",
            "commission_usd", "net_pnl_usd", "r_multiple_net",
        ])
        for t in result.closed_trades:
            p = t.position
            w.writerow([
                p.symbol, p.direction, p.lots, p.entry_time_utc, p.entry_price,
                p.sl, p.tp, t.exit_time_utc, t.exit_price, t.exit_reason,
                t.same_bar_ambiguous, round(p.risk_usd_at_entry, 4),
                round(t.gross_pnl_usd, 4), round(t.commission_usd, 4),
                round(t.net_pnl_usd, 4), round(t.r_multiple_net, 4) if t.r_multiple_net is not None else "",
            ])

    with (out_dir / "skipped_signals.csv").open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["symbol", "london_day", "direction", "retest_close_time_utc", "reason"])
        for sk in result.skipped_signals:
            s = sk.signal
            w.writerow([s.symbol, s.london_day, s.direction, s.retest_close_time_utc, sk.reason])

    with (out_dir / "day_outcomes.csv").open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["symbol", "london_day", "reason", "detail"])
        for symbol, outcomes in result.day_outcomes_by_symbol.items():
            for o in outcomes:
                w.writerow([symbol, o.london_day, o.reason, o.detail])

    with (out_dir / "risk_events.csv").open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["utc_time", "kind", "detail"])
        for e in result.risk_stop_events:
            w.writerow(list(e))

    # The only genuinely full calendar month covered by the ~2-month sample.
    full_calendar_months = {(2026, 8)}
    report_md = build_report(
        result,
        initial_balance=cfg.initial_balance,
        total_working_floor=cfg.ftmo_limits.robot_total_working_floor_usd,
        full_calendar_months=full_calendar_months,
        commission_confirmed=cfg.commission_is_confirmed,
        server_time_verified=cfg.server_time_model.is_verified,
    )
    (out_dir / "REPORT.md").write_text(report_md)
    print(report_md)
    print(f"\nWrote trades.csv, skipped_signals.csv, day_outcomes.csv, risk_events.csv, REPORT.md to {out_dir}")


if __name__ == "__main__":
    main()
