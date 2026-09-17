"""Spec section 9, tests 1-4 and part of 6: account-level floor arithmetic
and the pre-trade worst-case projected equity check. Every expected value
below is computed independently from the spec's own formulas, not copied
from any prior run's output.
"""
from ftmo_sim.account_risk import (
    CorrelatedGroupLimits,
    FtmoLimitsConfig,
    OpenPositionRiskView,
    applicable_robot_floor,
    ftmo_daily_floor,
    is_floor_breached,
    new_entry_allowed,
    new_idea_within_risk_caps,
    next_day_robot_daily_floor,
    robot_daily_working_floor,
    would_breach_next_day,
)

CFG = FtmoLimitsConfig(initial_balance=10000.0)


def test_scenario_1_b0_10000():
    # spec test 1: B0=10000 -> daily working floor 9700, total floor 9200,
    # applicable = 9700 (the tighter one), and breach triggers AT 9700, not
    # only strictly below it.
    floor = applicable_robot_floor(10000.0, CFG)
    assert floor == 9700.0
    assert ftmo_daily_floor(10000.0, CFG) == 9500.0
    assert is_floor_breached(9700.0, floor) is True
    assert is_floor_breached(9700.01, floor) is False


def test_scenario_2_b0_9400():
    # spec test 2: B0=9400 -> daily working floor 9100, but the applicable
    # floor stays 9200 (the static total floor wins the max()); the extra
    # 100 USD of headroom the daily floor alone would offer must NOT be used.
    floor = applicable_robot_floor(9400.0, CFG)
    assert floor == 9200.0
    assert robot_daily_working_floor(9400.0, CFG) == 9100.0


def test_scenario_3_b0_10500():
    # spec test 3: B0=10500 -> daily working floor 10200; applicable floor is
    # still 10200 (the daily floor is tighter here), and definitely not a
    # trailing 9700 and not the bare static 9200.
    floor = applicable_robot_floor(10500.0, CFG)
    assert floor == 10200.0
    assert floor != 9700.0
    assert floor != CFG.robot_total_working_floor_usd


def test_scenario_4_no_double_counting_floating_loss():
    # spec test 4: equity=9730 already reflects today's floating loss.
    # Adding a new 40 USD risk order must be rejected under the 9700 floor,
    # and the check must use current equity directly rather than re-deriving
    # (and thereby double-subtracting) the floating loss from B0.
    floor = applicable_robot_floor(10000.0, CFG)  # 9700
    assert new_entry_allowed(
        current_equity=9730.0,
        floor_usd=floor,
        open_positions=[],
        pending_worst_case_usd=0.0,
        new_order_risk_usd=40.0,
        unaccounted_costs_usd=0.0,
        execution_buffer_usd=0.0,
    ) is False
    # Sanity: the same 40 USD risk is allowed with more headroom.
    assert new_entry_allowed(
        current_equity=9760.0,
        floor_usd=floor,
        open_positions=[],
        pending_worst_case_usd=0.0,
        new_order_risk_usd=40.0,
        unaccounted_costs_usd=0.0,
        execution_buffer_usd=0.0,
    ) is True


def test_scenario_4b_remaining_risk_not_full_original_risk():
    # An open position that has already lost part of its risk (reflected in
    # equity) must only contribute its REMAINING move-to-SL, not its full
    # original risk, or the loss gets counted twice.
    floor = applicable_robot_floor(10000.0, CFG)  # 9700
    open_positions = [OpenPositionRiskView("EURUSD", remaining_risk_to_sl_usd=10.0, direction_usd_bucket="SHORT_USD")]
    projected_ok = new_entry_allowed(
        current_equity=9730.0, floor_usd=floor, open_positions=open_positions,
        pending_worst_case_usd=0.0, new_order_risk_usd=15.0,
        unaccounted_costs_usd=0.0, execution_buffer_usd=0.0,
    )
    # 9730 - 10 (remaining) - 15 (new) = 9705 > 9700 -> allowed
    assert projected_ok is True
    # If the (buggy) implementation instead re-subtracted a full original
    # risk of, say, 25 for that same position, 9730-25-15=9690 <= 9700 would
    # wrongly reject it -- this test guards against that regression.


def test_scenario_5_next_day_floor_forces_early_action():
    # spec test 5: pre-midnight balance=10200, equity=9850 -> tomorrow's
    # daily floor is 9900; carrying today's equity into tomorrow would
    # already sit below it, so risk must be trimmed BEFORE rollover.
    next_floor = next_day_robot_daily_floor(10200.0, CFG)
    assert next_floor == 9900.0
    assert would_breach_next_day(9850.0, next_floor) is True
    assert would_breach_next_day(9950.0, next_floor) is False


def test_correlated_group_cap_blocks_same_direction_pair():
    limits = CorrelatedGroupLimits(
        max_concurrent_risk_usd=100.0,
        correlated_group_max_risk_usd=50.0,
        groups={"USD_MAJORS": ["EURUSD", "GBPUSD"]},
    )
    open_risk_by_idea = {"idea-1": 30.0}
    idea_symbol = {"idea-1": "EURUSD"}
    idea_bucket = {"idea-1": "SHORT_USD"}  # BUY EURUSD == short USD

    # A second same-direction (also short-USD) idea in the correlated group
    # pushing group risk to 30+25=55 > 50 cap must be rejected.
    assert new_idea_within_risk_caps(
        "GBPUSD", "SHORT_USD", 25.0, open_risk_by_idea, idea_symbol, idea_bucket, limits,
    ) is False

    # An opposite-direction (long-USD) idea in the same pair group is not
    # summed with the short-USD bucket, so it is allowed under the group cap
    # (still subject to the overall portfolio cap).
    assert new_idea_within_risk_caps(
        "GBPUSD", "LONG_USD", 25.0, open_risk_by_idea, idea_symbol, idea_bucket, limits,
    ) is True


def test_portfolio_cap_blocks_regardless_of_grouping():
    limits = CorrelatedGroupLimits(
        max_concurrent_risk_usd=100.0,
        correlated_group_max_risk_usd=50.0,
        groups={},
    )
    open_risk_by_idea = {"idea-1": 80.0}
    idea_symbol = {"idea-1": "EURUSD"}
    idea_bucket = {"idea-1": "SHORT_USD"}
    assert new_idea_within_risk_caps(
        "GBPUSD", "LONG_USD", 25.0, open_risk_by_idea, idea_symbol, idea_bucket, limits,
    ) is False  # 80 + 25 = 105 > 100 portfolio cap
