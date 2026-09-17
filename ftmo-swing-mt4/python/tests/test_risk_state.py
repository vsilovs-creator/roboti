"""Spec section 9 test 8: restart after daily/total stop, second-instance
guard, incomplete history, unreconciled balance correction."""
from datetime import date

import pytest

from ftmo_sim.account_risk import FtmoLimitsConfig
from ftmo_sim.risk_state import InstanceConflictError, RiskState

CFG = FtmoLimitsConfig(initial_balance=10000.0)


def test_rollover_snapshots_balance_and_clears_daily_stop_only():
    # B0=9400 -> daily floor 9100, static total floor 9200 (the tighter of
    # the two here). equity=9050 breaches BOTH.
    state = RiskState(account_number=1, server_name="Broker-Demo", config_version="v1")
    state.rollover_if_needed(date(2026, 8, 10), balance_now=9400.0)
    state.evaluate(equity=9050.0, cfg=CFG)
    assert state.daily_stop_active is True
    assert state.total_stop_active is True

    # Next day: daily stop clears, total stop must NOT auto-clear.
    state.rollover_if_needed(date(2026, 8, 11), balance_now=9050.0)
    assert state.daily_stop_active is False
    assert state.total_stop_active is True


def test_daily_only_breach_does_not_set_sticky_total_stop():
    # B0=10000 -> daily floor 9700 (tighter than the static 9200 total floor
    # this early in a challenge). Breaching 9700 alone must not trip the
    # sticky total stop; that is exactly what lets the daily stop clear
    # cleanly the next FTMO day.
    state = RiskState(account_number=1, server_name="Broker-Demo", config_version="v1")
    state.rollover_if_needed(date(2026, 8, 10), balance_now=10000.0)
    state.evaluate(equity=9650.0, cfg=CFG)
    assert state.daily_stop_active is True
    assert state.total_stop_active is False


def test_total_stop_never_cleared_by_restart_or_rollover():
    state = RiskState(account_number=1, server_name="Broker-Demo", config_version="v1")
    state.rollover_if_needed(date(2026, 8, 1), balance_now=10000.0)
    state.total_stop_active = True
    state.total_stop_reason = "equity breach on 2026-08-01"

    # simulate restart
    state.recover_from_restart(reconstructed_balance_at_midnight=10000.0, history_reconciled=True)
    assert state.total_stop_active is True

    for d in range(2, 10):
        state.rollover_if_needed(date(2026, 8, d), balance_now=9800.0)
    assert state.total_stop_active is True

    state.clear_total_stop_manually("reviewed, no further breach found")
    assert state.total_stop_active is False


def test_second_instance_guard_rejects_conflicting_account():
    state = RiskState(account_number=555, server_name="Broker-Live", config_version="v1")
    with pytest.raises(InstanceConflictError):
        state._check_instance_guard(account_number=999, server_name="Broker-Live", config_version="v1")


def test_unreconciled_history_blocks_new_entries_but_not_protection():
    state = RiskState(account_number=1, server_name="Broker-Demo", config_version="v1")
    state.rollover_if_needed(date(2026, 8, 1), balance_now=10000.0)
    state.recover_from_restart(reconstructed_balance_at_midnight=None, history_reconciled=False)
    assert state.can_open_new_entry("EURUSD", date(2026, 8, 1)) is False
    # Stop evaluation itself must still function even while unreconciled.
    state.evaluate(equity=9000.0, cfg=CFG)
    assert state.total_stop_active is True


def test_one_entry_per_symbol_per_day():
    state = RiskState(account_number=1, server_name="Broker-Demo", config_version="v1")
    state.rollover_if_needed(date(2026, 8, 1), balance_now=10000.0)
    day = date(2026, 8, 1)
    assert state.can_open_new_entry("EURUSD", day) is True
    state.register_entry("EURUSD", day)
    assert state.can_open_new_entry("EURUSD", day) is False
    assert state.can_open_new_entry("GBPUSD", day) is True
