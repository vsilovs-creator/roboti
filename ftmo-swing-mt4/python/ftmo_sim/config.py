"""Config loading + typed accessors shared by the simulator and tests."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from .account_risk import CorrelatedGroupLimits, FtmoLimitsConfig
from .symbol_spec import SymbolSpec
from .time_utils import ServerTimeModel


@dataclass
class RunConfig:
    raw: dict
    initial_balance: float
    ftmo_limits: FtmoLimitsConfig
    risk_per_idea_usd: float
    max_concurrent_risk_usd: float
    correlated_group_max_risk_usd: float
    correlated_groups: dict
    execution_buffer_usd: float
    server_time_model: ServerTimeModel
    symbols: dict
    commission_round_turn_usd_per_lot: float | None
    spread_points_hypothetical: dict
    strategy: dict

    @property
    def correlation_limits(self) -> CorrelatedGroupLimits:
        return CorrelatedGroupLimits(
            max_concurrent_risk_usd=self.max_concurrent_risk_usd,
            correlated_group_max_risk_usd=self.correlated_group_max_risk_usd,
            groups=self.correlated_groups,
        )

    @property
    def commission_is_confirmed(self) -> bool:
        return self.commission_round_turn_usd_per_lot is not None


def load_config(path: Path) -> RunConfig:
    raw = json.loads(Path(path).read_text())

    ftmo_limits = FtmoLimitsConfig(
        initial_balance=raw["account"]["initial_balance"],
        daily_equity_floor_offset_usd=raw["ftmo_limits"]["daily_equity_floor_offset_usd"],
        total_equity_floor_usd=raw["ftmo_limits"]["total_equity_floor_usd"],
        robot_daily_working_buffer_offset_usd=raw["robot_limits"]["daily_working_buffer_offset_usd"],
        robot_total_working_floor_usd=raw["robot_limits"]["total_working_floor_usd"],
    )

    tz_cfg = raw["timezones"]["server_time_model"]
    mode = tz_cfg["mode"]
    if mode == "UNVERIFIED":
        # No confirmed server clock model exists yet. Default to assume_utc
        # for structural runs; every report generated this way must carry the
        # EXPLORATORY / unverified-timezone label (see report.py).
        server_time_model = ServerTimeModel(mode="assume_utc")
    else:
        server_time_model = ServerTimeModel(
            mode=mode,
            server_utc_offset_hours=tz_cfg.get("fixed_offset_hours"),
            hypothesis_zone_name=tz_cfg.get("zone_like_hypothesis"),
        )

    symbols = {
        name: SymbolSpec.from_config(name, cfg) for name, cfg in raw["symbols"].items()
    }

    return RunConfig(
        raw=raw,
        initial_balance=raw["account"]["initial_balance"],
        ftmo_limits=ftmo_limits,
        risk_per_idea_usd=raw["risk"]["risk_per_idea_usd"],
        max_concurrent_risk_usd=raw["risk"]["max_concurrent_risk_usd"],
        correlated_group_max_risk_usd=raw["risk"]["correlated_group_max_risk_usd"],
        correlated_groups=raw["risk"]["correlated_groups"],
        execution_buffer_usd=raw["risk"]["execution_buffer_usd"],
        server_time_model=server_time_model,
        symbols=symbols,
        commission_round_turn_usd_per_lot=raw["costs"]["commission_round_turn_usd_per_lot"],
        spread_points_hypothetical=raw["costs"]["spread_points_hypothetical"],
        strategy=raw["strategy"],
    )
