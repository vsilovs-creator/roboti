#!/usr/bin/env python3
"""NOT a strategy-selection tool. This sweeps EMA-crossover parameters
across a grid and reports how many combinations come out "positive" on the
one fixed ~2-month sample -- to make the multiple-comparisons/overfitting
risk concrete rather than just asserting it. Spec section 8/10 explicitly
warns against wide optimization on this little data, and the account owner
has confirmed no further historical data will be supplied, so there is no
held-out window left to validate any "winning" combination against. A
config that looks positive here is not evidence it will make money live --
with 81 combinations tried on 40-ish trading days, finding a few "positive"
ones by chance is close to guaranteed even for a strategy with zero real
edge. See README.md's "Multiple-comparisons demo" section for the reading
of this output; nothing found here should be adopted as the new active
strategy without being clear that this is exactly what it is.

Usage:
    python3 scripts/sweep_overfitting_demo.py \
        --config ../config/config.example.json \
        --eurusd ../data/raw/EURUSD1.csv \
        --gbpusd ../data/raw/GBPUSD1.csv \
        --out ../reports/run_005_overfitting_sweep_demo/sweep_results.csv
"""
from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ftmo_sim.bars import load_m1_csv
from ftmo_sim.config import load_config
from ftmo_sim.simulator_ema_cross import run_h1_signal_simulation
from ftmo_sim.strategy_ema_cross import EmaCrossEngine

FAST_PERIODS = [10, 20, 30]
SLOW_PERIODS = [40, 50, 100]
ATR_SL_MULTIPLES = [1.0, 1.5, 2.0]
TP_R_MULTIPLES = [1.5, 2.0, 3.0]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    ap.add_argument("--eurusd", required=True)
    ap.add_argument("--gbpusd", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    cfg = load_config(Path(args.config))
    m1 = {
        "EURUSD": load_m1_csv(Path(args.eurusd), cfg.server_time_model),
        "GBPUSD": load_m1_csv(Path(args.gbpusd), cfg.server_time_model),
    }

    rows = []
    for fast in FAST_PERIODS:
        for slow in SLOW_PERIODS:
            if fast >= slow:
                continue
            for atr_mult in ATR_SL_MULTIPLES:
                for tp_mult in TP_R_MULTIPLES:
                    factory = lambda s, f=fast, sl=slow, am=atr_mult, tm=tp_mult: EmaCrossEngine(
                        s, fast_period=f, slow_period=sl, atr_period=14,
                        atr_sl_multiple=am, tp_r_multiple=tm,
                    )
                    result = run_h1_signal_simulation(cfg, m1, engine_factory=factory)
                    net = result.final_balance - cfg.initial_balance
                    rows.append((fast, slow, atr_mult, tp_mult, len(result.closed_trades), net))

    rows.sort(key=lambda r: -r[5])
    positive = [r for r in rows if r[5] > 0]

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["fast_period", "slow_period", "atr_sl_multiple", "tp_r_multiple", "trades", "net_usd"])
        for r in rows:
            w.writerow(r)

    print(f"Swept {len(rows)} combinations. {len(positive)} ({100*len(positive)/len(rows):.0f}%) came out positive.")
    print("\nTop 5 by net USD (NOT a recommendation -- see this script's docstring):")
    for r in rows[:5]:
        print(f"  fast={r[0]} slow={r[1]} atr_sl={r[2]} tp_r={r[3]} trades={r[4]} net={r[5]:+.2f}")
    print(f"\nBottom 5 by net USD:")
    for r in rows[-5:]:
        print(f"  fast={r[0]} slow={r[1]} atr_sl={r[2]} tp_r={r[3]} trades={r[4]} net={r[5]:+.2f}")
    print(f"\nWrote full grid to {out_path}")


if __name__ == "__main__":
    main()
