#!/usr/bin/env python3
"""One reproducible entry point for the S1-S8 x C1-C3 comparison --
docs/EXPERIMENT_PLAN_2026-09-18.md section 4/deliverables.

Usage:
    python3 scripts/run_experiment_2026-09-18.py \
        --config ../config/config.example.json \
        --eurusd ../data/raw/EURUSD1.csv --gbpusd ../data/raw/GBPUSD1.csv \
        --out-dir ../reports/experiment_2026-09-18 \
        [--variant S6] [--scenario C2]   # omit both for all 24 runs

For each (variant, scenario) this writes, under
<out-dir>/<variant>_<scenario>/:
  - trades.csv        every CLOSED trade
  - equity.csv        the full M1-resolution equity curve
  - signals.csv       every REJECTED signal (with its reason) and every
                       ACCEPTED signal (its fill, direction, and whether
                       it was still open at the end of the sample) -- see
                       the module docstring below for why "accepted" is
                       logged at its FILL instant, not the earlier
                       raw-signal-detection instant.
  - summary.json      the full machine-readable metrics from
                       experiment_metrics.full_metrics(), plus the run's
                       config content hash and the code's git SHA.

Also writes <out-dir>/experiment_summary.json, a single file collecting
every requested run's summary.json for convenient cross-run comparison
(used by docs/STRATEGY_RESEARCH_2026-09-18.md).

No grid search: every parameter comes straight from
config/config.example.json's strategies.* blocks and the three fixed C1/
C2/C3 cost scenarios below, exactly as pre-registered in
docs/EXPERIMENT_PLAN_2026-09-18.md.
"""
from __future__ import annotations

import argparse
import csv
import json
import hashlib
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ftmo_sim.bars import load_m1_csv
from ftmo_sim.config import load_config
from ftmo_sim.experiment_metrics import full_metrics
from ftmo_sim.simulator import run_simulation
from ftmo_sim.simulator_ema_cross import run_donchian_simulation, run_ema_cross_simulation, run_h1_signal_simulation
from ftmo_sim.simulator_m30_signal import run_false_breakout_m30_simulation, run_rsi2_pullback_m30_simulation
from ftmo_sim.strategy_bb_reversion import BbReversionEngine

FULL_CALENDAR_MONTHS = {(2026, 8)}
VARIANTS = ["S1", "S2", "S3", "S4", "S5", "S6", "S7", "S8"]
SCENARIOS = ["C1", "C2", "C3"]

# Section 3 of the plan: spread in POINTS (10 points = 1 pip on a 5-digit
# quote), slippage in raw PRICE units (0.5 pip = 0.00005).
SCENARIO_SPREAD_POINTS = {
    "C1": {"EURUSD": 10.0, "GBPUSD": 15.0},
    "C2": {"EURUSD": 20.0, "GBPUSD": 30.0},
    "C3": {"EURUSD": 30.0, "GBPUSD": 45.0},
}
SCENARIO_SLIPPAGE_PRICE = {"C1": 0.0, "C2": 0.00005, "C3": 0.00010}


def _git_sha() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=Path(__file__).resolve().parent, text=True,
        ).strip()
    except Exception as exc:  # pragma: no cover -- environmental, never fabricate a SHA
        return f"UNKNOWN ({exc})"


def _config_hash(config_path: Path) -> str:
    return hashlib.sha256(config_path.read_bytes()).hexdigest()


def apply_scenario_to_config(cfg, scenario: str) -> str:
    """FIXED 2026-09-18 (Codex F1): build the scenario's EFFECTIVE config by
    actually overriding the spread the simulators read
    (`cfg.spread_points_hypothetical`, the typed field every
    simulator.py/simulator_ema_cross.py/simulator_m30_signal.py call site
    uses -- `cfg.raw['costs']['spread_points_hypothetical']` kept in sync
    too, since it is the same data by a different path). Previously
    `run_one` only used the scenario's spread to build
    `spread_price_by_symbol` for the REPORTED cost breakdown -- the `cfg`
    object actually handed to the simulator kept the config file's
    original (C1) spread regardless of scenario, so C2/C3 differed from
    C1 only by slippage, never by spread, even though the plan and every
    report claimed otherwise. Mutates `cfg` in place (each call site loads
    a fresh RunConfig per run, so no cross-run state leaks) and returns a
    SHA256 of the effective (post-override) spread config for the run's
    reproducibility metadata."""
    spreads = SCENARIO_SPREAD_POINTS[scenario]
    for symbol, points in spreads.items():
        cfg.spread_points_hypothetical[symbol] = points
        cfg.raw["costs"]["spread_points_hypothetical"][symbol] = points
    effective = {
        "spread_points_hypothetical": dict(cfg.spread_points_hypothetical),
        "slippage_price": SCENARIO_SLIPPAGE_PRICE[scenario],
        "commission_round_turn_usd_per_lot": cfg.commission_round_turn_usd_per_lot,
    }
    return hashlib.sha256(json.dumps(effective, sort_keys=True).encode()).hexdigest()


def run_one(variant: str, scenario: str, cfg, m1_by_symbol: dict) -> tuple:
    """Returns (result, spread_price_by_symbol, slippage_price).
    `cfg` must already have had apply_scenario_to_config() applied by the
    caller -- this function no longer computes the scenario's spread
    itself, only reads it back off `cfg` so the reported
    spread_price_by_symbol is guaranteed to match what the simulator
    actually used (they are now, structurally, the same value)."""
    slippage = SCENARIO_SLIPPAGE_PRICE[scenario]
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


def write_trades_csv(path: Path, result) -> None:
    with path.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow([
            "idea_id", "symbol", "direction", "lots", "entry_time_utc", "entry_price",
            "sl", "tp", "exit_time_utc", "exit_price", "exit_reason", "same_bar_ambiguous",
            "gross_pnl_usd", "commission_usd", "net_pnl_usd", "r_multiple_net",
        ])
        for t in result.closed_trades:
            p = t.position
            w.writerow([
                p.idea_id, p.symbol, p.direction, p.lots, p.entry_time_utc, p.entry_price,
                p.sl, p.tp, t.exit_time_utc, t.exit_price, t.exit_reason, t.same_bar_ambiguous,
                f"{t.gross_pnl_usd:.4f}", f"{t.commission_usd:.4f}", f"{t.net_pnl_usd:.4f}",
                f"{t.r_multiple_net:.4f}" if t.r_multiple_net is not None else "",
            ])


def write_equity_csv(path: Path, result, downsample_every_n: int = 60) -> None:
    """Downsampled to every `downsample_every_n`-th M1 point (default: one
    row per hour) to keep the written artifact a reasonable size across
    24 runs -- every metric in summary.json (drawdown, lowest equity,
    worst FTMO day) is computed from the FULL M1-resolution curve in
    memory, not from this downsampled file; this file is for visual/
    traceability purposes. The very first and last point are always kept
    exactly, whether or not they land on a sampled index."""
    curve = result.equity_curve
    with path.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["utc_time", "equity", "balance"])
        for i, (t, eq, bal) in enumerate(curve):
            if i % downsample_every_n == 0 or i == len(curve) - 1:
                w.writerow([t, f"{eq:.4f}", f"{bal:.4f}"])


def _signal_close_time(signal) -> object:
    """FIXED 2026-09-18 (found while building the long-history runner):
    S1's SignalEvent (signals.py) names this field
    `retest_close_time_utc`; every other variant's EmaCrossSignal
    (strategy_ema_cross.py, used by S2-S8) names it
    `signal_close_time_utc` -- two shapes, same meaning. This never
    crashed on the ~2-month 2026 sample because S1 happened to have zero
    rejected signals there (`rejected_signal_counts_by_reason: {}`), but
    is a real AttributeError waiting to happen on any run where S1 DOES
    reject a signal (confirmed: it does, on the 2015-2022 long-history
    data) -- never silently skip a signal's row instead of fixing the
    field-name mismatch."""
    t = getattr(signal, "signal_close_time_utc", None)
    return t if t is not None else getattr(signal, "retest_close_time_utc")


def write_signals_csv(path: Path, result) -> None:
    """Every REJECTED signal (with its reason) and every ACCEPTED signal
    (logged at its FILL instant -- the position's entry_time_utc/price --
    not the earlier raw-signal-detection instant, which this project's
    result objects do not carry forward once a position is opened)."""
    with path.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["status", "symbol", "direction", "time_utc", "price_or_na", "reason_or_outcome"])
        for sk in result.skipped_signals:
            w.writerow(["REJECTED", sk.signal.symbol, sk.signal.direction, _signal_close_time(sk.signal), "", sk.reason])
        for t in result.closed_trades:
            p = t.position
            w.writerow(["ACCEPTED", p.symbol, p.direction, p.entry_time_utc, f"{p.entry_price:.5f}", f"CLOSED_{t.exit_reason}"])
        for sym, p in result.open_positions_at_end.items():
            w.writerow(["ACCEPTED", sym, p.direction, p.entry_time_utc, f"{p.entry_price:.5f}", "STILL_OPEN_AT_SAMPLE_END"])


def run_all(args) -> None:
    config_path = Path(args.config)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    m1_by_symbol = {
        "EURUSD": load_m1_csv(Path(args.eurusd), load_config(config_path).server_time_model),
        "GBPUSD": load_m1_csv(Path(args.gbpusd), load_config(config_path).server_time_model),
    }

    variants = [args.variant] if args.variant else VARIANTS
    scenarios = [args.scenario] if args.scenario else SCENARIOS

    git_sha = _git_sha()
    config_sha = _config_hash(config_path)

    all_summaries = []
    for scenario in scenarios:
        for variant in variants:
            cfg = load_config(config_path)  # fresh RunConfig per run -- no shared mutable state across runs
            effective_config_sha = apply_scenario_to_config(cfg, scenario)
            result, spread_price_by_symbol, slippage = run_one(variant, scenario, cfg, m1_by_symbol)

            run_dir = out_dir / f"{variant}_{scenario}"
            run_dir.mkdir(parents=True, exist_ok=True)
            write_trades_csv(run_dir / "trades.csv", result)
            write_equity_csv(run_dir / "equity.csv", result)
            write_signals_csv(run_dir / "signals.csv", result)

            metrics = full_metrics(
                result, cfg, variant, scenario, spread_price_by_symbol, slippage, FULL_CALENDAR_MONTHS,
            )
            metrics["run_metadata"] = {
                "git_sha": git_sha,
                "config_sha256": config_sha,
                "effective_scenario_config_sha256": effective_config_sha,
                "config_path": str(config_path),
                "scenario_spread_points": dict(cfg.spread_points_hypothetical),
                "scenario_slippage_price": slippage,
                "commission_round_turn_usd_per_lot": cfg.commission_round_turn_usd_per_lot,
            }
            (run_dir / "summary.json").write_text(json.dumps(metrics, indent=2, default=str))
            all_summaries.append(metrics)
            print(f"{variant} {scenario}: net_balance={metrics['net_balance_change_usd']:+.2f} USD "
                  f"trades={metrics['trade_count']} pf={metrics['profit_factor']:.2f}")

    (out_dir / "experiment_summary.json").write_text(json.dumps(all_summaries, indent=2, default=str))
    print(f"\nWrote {len(all_summaries)} run(s) under {out_dir}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    ap.add_argument("--eurusd", required=True)
    ap.add_argument("--gbpusd", required=True)
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--variant", choices=VARIANTS, default=None, help="omit for all 8")
    ap.add_argument("--scenario", choices=SCENARIOS, default=None, help="omit for all 3")
    args = ap.parse_args()
    run_all(args)


if __name__ == "__main__":
    main()
