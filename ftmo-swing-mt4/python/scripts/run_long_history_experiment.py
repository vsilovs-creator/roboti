#!/usr/bin/env python3
"""Part A of docs/LONG_HISTORY_EXPERIMENT_PLAN.md section 5: the
CONTINUOUS-account selection-period comparison -- S1-S8 x C1-C3, one
continuous 10,000 USD account per (variant, scenario) from 2015-01-01
through 2022-12-31, both EURUSD and GBPUSD on the SAME account (never
summed from two independent single-pair backtests), using the real
HistData MetaTrader-platform M1 data at data/raw/DAT_MT_{SYMBOL}_M1_{YEAR}.csv.

Reuses run_experiment_2026-09-18.py's exact scenario/cost-application
logic (apply_scenario_to_config, SCENARIO_SPREAD_POINTS,
SCENARIO_SLIPPAGE_PRICE) and report-writing functions verbatim, imported
directly rather than duplicated, so this round can never silently drift
from the already-audited (F1-F5, R1-R2) scenario/cost/report behavior --
the ONLY difference from that script is the data SOURCE (multi-year
HistData CSVs, concatenated, instead of the single 2026 MT4-exported
sample) and the resulting full_calendar_months set.

Usage:
    python3 scripts/run_long_history_experiment.py \
        --config ../config/config.example.json \
        --raw-dir ../data/raw --start-year 2015 --end-year 2022 \
        --out-dir ../reports/long_history_selection_2015_2022 \
        [--variant S6] [--scenario C2]   # omit both for all 24 runs

Loads each symbol's data ONCE (all requested years, concatenated and
verified strictly increasing) and reuses it across every (variant,
scenario) combination -- loading 8 years x 2 symbols from HistData CSVs
takes real time (M1 resolution over ~3M rows/symbol/8yr), so it must not
be repeated per run.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ftmo_sim.config import load_config
from ftmo_sim.experiment_metrics import full_metrics
from ftmo_sim.histdata_adapter import parse_histdata_m1
from ftmo_sim.simulator import run_simulation
from ftmo_sim.simulator_ema_cross import run_donchian_simulation, run_ema_cross_simulation, run_h1_signal_simulation
from ftmo_sim.simulator_m30_signal import run_false_breakout_m30_simulation, run_rsi2_pullback_m30_simulation
from ftmo_sim.strategy_bb_reversion import BbReversionEngine

# Reuse the 2026-sample script's scenario/cost logic and CSV writers
# verbatim (see module docstring) -- loaded by path since scripts/ is not
# a package.
_spec = importlib.util.spec_from_file_location(
    "run_experiment_2026_09_18", Path(__file__).resolve().parent / "run_experiment_2026-09-18.py",
)
_base = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = _base
_spec.loader.exec_module(_base)

VARIANTS = _base.VARIANTS
SCENARIOS = _base.SCENARIOS
apply_scenario_to_config = _base.apply_scenario_to_config
write_trades_csv = _base.write_trades_csv
write_equity_csv = _base.write_equity_csv
write_signals_csv = _base.write_signals_csv


def _git_sha() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=Path(__file__).resolve().parent, text=True,
        ).strip()
    except Exception as exc:  # pragma: no cover -- environmental, never fabricate a SHA
        return f"UNKNOWN ({exc})"


def load_long_history_m1(symbol: str, start_year: int, end_year: int, raw_dir: Path):
    """Concatenates every requested year's HistData MT-platform CSV for
    `symbol`, in order, and verifies the RESULT is still strictly
    increasing with no duplicate timestamps across a year boundary (each
    individual year's file is already deduped/verified monotonic by
    `parse_histdata_m1` itself; this is an extra check on the SEAM
    between consecutive years, which no single file's own check can
    see). Raises rather than silently proceeding if that seam check
    fails -- never trust a multi-file concatenation without verifying it."""
    all_rows = []
    quality_reports = {}
    for year in range(start_year, end_year + 1):
        path = raw_dir / f"DAT_MT_{symbol}_M1_{year}.csv"
        if not path.exists():
            raise FileNotFoundError(f"missing {path} for the requested {start_year}-{end_year} range")
        rows, report = parse_histdata_m1(path)
        quality_reports[year] = report.as_dict()
        all_rows.extend(rows)
    all_rows.sort(key=lambda c: c.open_time_utc)
    for i in range(1, len(all_rows)):
        if all_rows[i].open_time_utc <= all_rows[i - 1].open_time_utc:
            raise ValueError(
                f"{symbol}: non-increasing timestamp across the concatenated series at index {i} "
                f"({all_rows[i - 1].open_time_utc} -> {all_rows[i].open_time_utc}) -- a year-boundary "
                f"overlap this loader's per-file checks could not see"
            )
    return all_rows, quality_reports


def full_calendar_months_for(m1_by_symbol: dict) -> set:
    """Every (year, month) covered by the data EXCEPT the sample's own
    first and last calendar month (always partial -- the data starts/
    ends mid-week, never exactly at a calendar month boundary), matching
    the exact convention `docs/STRATEGY_RESEARCH_2026-09-18.md` already
    established for the 2026 sample ("Only 2026-08 is a full calendar
    month... 2026-07 and 2026-09 are partial")."""
    from ftmo_sim.time_utils import ftmo_trading_day

    first_t = min(rows[0].open_time_utc for rows in m1_by_symbol.values())
    last_t = max(rows[-1].open_time_utc for rows in m1_by_symbol.values())
    first_day = ftmo_trading_day(first_t)
    last_day = ftmo_trading_day(last_t)
    months = []
    y, m = first_day.year, first_day.month
    while (y, m) <= (last_day.year, last_day.month):
        months.append((y, m))
        m += 1
        if m > 12:
            m = 1
            y += 1
    return set(months[1:-1]) if len(months) > 2 else set()


def run_one(variant: str, scenario: str, cfg, m1_by_symbol: dict) -> tuple:
    slippage = _base.SCENARIO_SLIPPAGE_PRICE[scenario]
    spread_price_by_symbol = {
        s: cfg.spread_points_hypothetical[s] * cfg.symbols[s].point_size for s in cfg.symbols
    }
    if variant == "S1":
        result = run_simulation(cfg, m1_by_symbol, slippage_price=slippage)
    elif variant == "S2":
        result = run_ema_cross_simulation(cfg, m1_by_symbol, on_opposite_signal="skip", slippage_price=slippage)
    elif variant == "S3":
        result = run_h1_signal_simulation(
            cfg, m1_by_symbol, engine_factory=BbReversionEngine,
            account_number=900000003, server_name="OFFLINE-SIM-BB", slippage_price=slippage,
        )
    elif variant == "S4":
        result = run_ema_cross_simulation(cfg, m1_by_symbol, on_opposite_signal="close_only", slippage_price=slippage)
    elif variant == "S5":
        result = run_ema_cross_simulation(cfg, m1_by_symbol, on_opposite_signal="close_and_reverse", slippage_price=slippage)
    elif variant == "S6":
        result = run_donchian_simulation(cfg, m1_by_symbol, slippage_price=slippage)
    elif variant == "S7":
        result = run_false_breakout_m30_simulation(cfg, m1_by_symbol, slippage_price=slippage)
    elif variant == "S8":
        result = run_rsi2_pullback_m30_simulation(cfg, m1_by_symbol, slippage_price=slippage)
    else:
        raise ValueError(f"unknown variant {variant!r}")
    return result, spread_price_by_symbol, slippage


def run_all(args) -> None:
    config_path = Path(args.config)
    raw_dir = Path(args.raw_dir)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    t0 = time.time()
    m1_by_symbol = {}
    data_quality = {}
    for symbol in ["EURUSD", "GBPUSD"]:
        rows, reports = load_long_history_m1(symbol, args.start_year, args.end_year, raw_dir)
        m1_by_symbol[symbol] = rows
        data_quality[symbol] = reports
        print(f"loaded {symbol}: {len(rows)} rows, {args.start_year}-{args.end_year} "
              f"({time.time() - t0:.1f}s elapsed)", flush=True)

    full_calendar_months = full_calendar_months_for(m1_by_symbol)
    (out_dir / "data_quality_report.json").write_text(json.dumps(data_quality, indent=2))

    variants = [args.variant] if args.variant else VARIANTS
    scenarios = [args.scenario] if args.scenario else SCENARIOS
    git_sha = _git_sha()
    config_sha = hashlib.sha256(config_path.read_bytes()).hexdigest()

    all_summaries = []
    for scenario in scenarios:
        for variant in variants:
            t1 = time.time()
            cfg = load_config(config_path)
            effective_config_sha = apply_scenario_to_config(cfg, scenario)
            result, spread_price_by_symbol, slippage = run_one(variant, scenario, cfg, m1_by_symbol)

            run_dir = out_dir / f"{variant}_{scenario}"
            run_dir.mkdir(parents=True, exist_ok=True)
            write_trades_csv(run_dir / "trades.csv", result)
            write_equity_csv(run_dir / "equity.csv", result, downsample_every_n=1440)
            write_signals_csv(run_dir / "signals.csv", result)

            metrics = full_metrics(
                result, cfg, variant, scenario, spread_price_by_symbol, slippage, full_calendar_months,
            )
            metrics["run_metadata"] = {
                "git_sha": git_sha,
                "config_sha256": config_sha,
                "effective_scenario_config_sha256": effective_config_sha,
                "config_path": str(config_path),
                "scenario_spread_points": dict(cfg.spread_points_hypothetical),
                "scenario_slippage_price": slippage,
                "commission_round_turn_usd_per_lot": cfg.commission_round_turn_usd_per_lot,
                "data_source": "HistData MetaTrader-platform M1, user-supplied download",
                "period": f"{args.start_year}-01-01 to {args.end_year}-12-31",
            }
            (run_dir / "summary.json").write_text(json.dumps(metrics, indent=2, default=str))
            all_summaries.append(metrics)
            print(f"{variant} {scenario}: net_balance={metrics['net_balance_change_usd']:+.2f} USD "
                  f"trades={metrics['trade_count']} pf={metrics['profit_factor']:.2f} "
                  f"stop={metrics['working_floor_breach_count']} "
                  f"({time.time() - t1:.1f}s)", flush=True)

    (out_dir / "experiment_summary.json").write_text(json.dumps(all_summaries, indent=2, default=str))
    print(f"\nWrote {len(all_summaries)} run(s) under {out_dir} ({time.time() - t0:.1f}s total)")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    ap.add_argument("--raw-dir", required=True)
    ap.add_argument("--start-year", type=int, default=2015)
    ap.add_argument("--end-year", type=int, default=2022)
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--variant", choices=VARIANTS, default=None, help="omit for all 8")
    ap.add_argument("--scenario", choices=SCENARIOS, default=None, help="omit for all 3")
    args = ap.parse_args()
    run_all(args)


if __name__ == "__main__":
    main()
