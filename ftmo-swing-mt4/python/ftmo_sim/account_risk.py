"""Account-wide risk floors and pre-trade risk budget checks.

Pure functions only -- no I/O, no MT4 calls -- so every rule in section 4/9
of the task spec can be pinned down with an independently computed expected
value. Persistence and day-rollover *state* (which needs to remember things
across ticks/restarts) lives in risk_state.py; this module is the stateless
arithmetic both the state machine and the simulator call into.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class FtmoLimitsConfig:
    initial_balance: float
    daily_equity_floor_offset_usd: float = 500.0
    total_equity_floor_usd: float = 9000.0
    robot_daily_working_buffer_offset_usd: float = 300.0
    robot_total_working_floor_usd: float = 9200.0


def ftmo_daily_floor(balance_at_midnight: float, cfg: FtmoLimitsConfig) -> float:
    """The raw FTMO daily equity floor. Reported for visibility; the robot
    does not wait for this looser limit -- see applicable_robot_floor()."""
    return balance_at_midnight - cfg.daily_equity_floor_offset_usd


def robot_daily_working_floor(balance_at_midnight: float, cfg: FtmoLimitsConfig) -> float:
    return balance_at_midnight - cfg.robot_daily_working_buffer_offset_usd


def applicable_robot_floor(balance_at_midnight: float, cfg: FtmoLimitsConfig) -> float:
    """max(daily working floor, static total working floor).

    This is a static 9200 total floor, NOT a trailing drawdown: it never
    moves down because of losses, a restart, or a new month. It only ever
    participates in the max() because the *daily* floor can be higher than
    it early in a challenge when the starting balance is well above 10000+300.
    """
    return max(
        robot_daily_working_floor(balance_at_midnight, cfg),
        cfg.robot_total_working_floor_usd,
    )


def is_floor_breached(equity: float, floor_usd: float) -> bool:
    """Trigger is E <= floor (inclusive), per spec test 1 ("iedarbojas pie
    9700, ne tikai zem tās")."""
    return equity <= floor_usd


@dataclass(frozen=True)
class OpenPositionRiskView:
    """Remaining potential loss for one already-open position, measured from
    the *current* mark price to its own SL -- NOT its full original risk.
    Using the full original risk here would double-count the portion already
    reflected in account equity via floating P/L (see spec test 4)."""

    symbol: str
    remaining_risk_to_sl_usd: float
    direction_usd_bucket: str  # e.g. "USD_LONG" / "USD_SHORT" for correlation grouping


def pre_trade_projected_equity(
    current_equity: float,
    open_positions: list[OpenPositionRiskView],
    pending_worst_case_usd: float,
    new_order_risk_usd: float,
    unaccounted_costs_usd: float,
    execution_buffer_usd: float,
) -> float:
    """Worst-case projected equity if every open position moved from its
    current mark price straight to its own SL, every pending order activated
    and then also hit its SL, the new order is opened and also hits its SL,
    plus unmodeled costs and an execution buffer.

    Equity already reflects floating P/L up to the current price, so only the
    *remaining* move to each SL is added here -- never the position's full
    original risk (that would subtract the already-included floating loss a
    second time).
    """
    remaining_open_risk = sum(p.remaining_risk_to_sl_usd for p in open_positions)
    return (
        current_equity
        - remaining_open_risk
        - pending_worst_case_usd
        - new_order_risk_usd
        - unaccounted_costs_usd
        - execution_buffer_usd
    )


def new_entry_allowed(
    current_equity: float,
    floor_usd: float,
    open_positions: list[OpenPositionRiskView],
    pending_worst_case_usd: float,
    new_order_risk_usd: float,
    unaccounted_costs_usd: float,
    execution_buffer_usd: float,
) -> bool:
    """A new entry is allowed only if the worst-case projected equity stays
    strictly above the applicable floor. Any unknown/unbounded existing risk
    (e.g. a foreign position with no SL) must be surfaced by the caller as an
    open_positions entry with a very large remaining_risk_to_sl_usd (or the
    caller blocks entries outright per spec section 4) -- this function does
    not special-case "unknown" itself, it only does the arithmetic."""
    projected = pre_trade_projected_equity(
        current_equity,
        open_positions,
        pending_worst_case_usd,
        new_order_risk_usd,
        unaccounted_costs_usd,
        execution_buffer_usd,
    )
    return projected > floor_usd


def next_day_robot_daily_floor(balance_before_midnight: float, cfg: FtmoLimitsConfig) -> float:
    """The daily working floor that will apply the instant the next FTMO day
    starts, computed from the balance the account will roll over with (i.e.
    balance at the upcoming Prague midnight, ignoring any further fills
    between now and midnight)."""
    return robot_daily_working_floor(balance_before_midnight, cfg)


def would_breach_next_day(current_equity: float, next_day_floor: float) -> bool:
    """True if carrying today's equity into tomorrow would already sit at or
    below tomorrow's (tighter, balance-reset) daily floor -- i.e. positions
    must be trimmed/closed before rollover rather than waiting for the
    breach to materialize after midnight."""
    return current_equity <= next_day_floor


@dataclass(frozen=True)
class CorrelatedGroupLimits:
    max_concurrent_risk_usd: float
    correlated_group_max_risk_usd: float
    groups: dict[str, list[str]] = field(default_factory=dict)


def group_for_symbol(symbol: str, groups: dict[str, list[str]]) -> str | None:
    for group_name, members in groups.items():
        if symbol in members:
            return group_name
    return None


def total_open_risk_usd(open_risk_by_idea: dict[str, float]) -> float:
    return sum(open_risk_by_idea.values())


def correlated_group_risk_usd(
    open_risk_by_idea: dict[str, float],
    idea_symbol: dict[str, str],
    idea_direction_bucket: dict[str, str],
    group_name: str,
    groups: dict[str, list[str]],
    direction_bucket: str,
) -> float:
    """Sum of open risk for ideas whose symbol is in `group_name` AND whose
    USD-direction bucket matches `direction_bucket` (same-direction EURUSD +
    GBPUSD ideas are not independent and must share one group cap; opposite
    directions in the two pairs are not summed together)."""
    members = set(groups.get(group_name, []))
    total = 0.0
    for idea_id, risk in open_risk_by_idea.items():
        if idea_symbol.get(idea_id) in members and idea_direction_bucket.get(idea_id) == direction_bucket:
            total += risk
    return total


def new_idea_within_risk_caps(
    new_idea_symbol: str,
    new_idea_direction_bucket: str,
    new_idea_risk_usd: float,
    open_risk_by_idea: dict[str, float],
    idea_symbol: dict[str, str],
    idea_direction_bucket: dict[str, str],
    limits: CorrelatedGroupLimits,
) -> bool:
    if total_open_risk_usd(open_risk_by_idea) + new_idea_risk_usd > limits.max_concurrent_risk_usd:
        return False
    group_name = group_for_symbol(new_idea_symbol, limits.groups)
    if group_name is not None:
        group_risk = correlated_group_risk_usd(
            open_risk_by_idea, idea_symbol, idea_direction_bucket,
            group_name, limits.groups, new_idea_direction_bucket,
        )
        if group_risk + new_idea_risk_usd > limits.correlated_group_max_risk_usd:
            return False
    return True
