"""Persisted stop-state machine: daily stop vs. total stop, day rollover,
restart recovery, and the single-controller instance guard.

This mirrors what the MQL4 side must do with a state file / GlobalVariables
(see mql4/Include/FTMO/Persistence.mqh) closely enough that the same test
vectors in tests/test_risk_state.py describe both implementations' intended
behavior, even though only the Python side is actually executed here.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import date
from pathlib import Path

from .account_risk import (
    FtmoLimitsConfig,
    is_floor_breached,
    robot_daily_working_floor,
)


class InstanceConflictError(RuntimeError):
    """Raised when the persisted state is bound to a different account,
    server, or config version than the one asking to use it -- prevents a
    second EA instance (or a config change) from silently sharing/corrupting
    another instance's stop state."""


@dataclass
class RiskState:
    account_number: int | None = None
    server_name: str | None = None
    config_version: str | None = None

    current_ftmo_day: str | None = None  # ISO date string
    balance_at_midnight: float | None = None

    daily_stop_active: bool = False
    total_stop_active: bool = False
    total_stop_reason: str | None = None

    # date-string -> list of symbols that already used their one entry that day
    entries_used_by_day: dict = field(default_factory=dict)

    # True once a human/process has confirmed full history is available and
    # reconciled after a restart; entries stay blocked until this is set.
    history_reconciled: bool = True

    @classmethod
    def load_or_init(
        cls,
        path: Path,
        account_number: int,
        server_name: str,
        config_version: str,
    ) -> "RiskState":
        if path.exists():
            data = json.loads(path.read_text())
            state = cls(**data)
            state._check_instance_guard(account_number, server_name, config_version)
            return state
        state = cls(
            account_number=account_number,
            server_name=server_name,
            config_version=config_version,
        )
        return state

    def _check_instance_guard(self, account_number: int, server_name: str, config_version: str) -> None:
        if self.account_number is None:
            self.account_number = account_number
            self.server_name = server_name
            self.config_version = config_version
            return
        if (self.account_number, self.server_name) != (account_number, server_name):
            raise InstanceConflictError(
                f"persisted state is bound to account={self.account_number} "
                f"server={self.server_name!r}; refusing to bind account={account_number} "
                f"server={server_name!r} -- looks like a second controller instance"
            )
        # A config_version mismatch is not fatal (the caller may be
        # deliberately upgrading config) but must not silently reset stops.
        self.config_version = config_version

    def save(self, path: Path) -> None:
        path.write_text(json.dumps(asdict(self), indent=2, sort_keys=True))

    # -- restart recovery -------------------------------------------------

    def recover_from_restart(self, reconstructed_balance_at_midnight: float | None, history_reconciled: bool) -> None:
        """Call once at EA/process startup, before evaluating any new tick.

        `reconstructed_balance_at_midnight` must come from a persisted
        snapshot and/or a verified full account history reconstruction, never
        from "current balance" (which may already reflect today's trading).
        If it cannot be reconstructed, entries stay blocked
        (history_reconciled=False) while existing stops/positions are still
        protected.
        """
        self.history_reconciled = history_reconciled
        if reconstructed_balance_at_midnight is not None:
            self.balance_at_midnight = reconstructed_balance_at_midnight
        # total_stop_active is intentionally left untouched: a restart must
        # never clear it. daily_stop_active is also left untouched here; it
        # is only cleared by rollover_if_needed() below, and only into a
        # correctly reconstructed new day.

    # -- day rollover -------------------------------------------------

    def rollover_if_needed(self, ftmo_day_today: date, balance_now: float) -> bool:
        """Call on every tick with the current FTMO trading day. On the
        first observation of a new day, snapshot balance_at_midnight and,
        if a daily stop was active, clear it -- but never clear a total
        stop this way. Returns True if a rollover happened."""
        today_str = ftmo_day_today.isoformat()
        if self.current_ftmo_day == today_str:
            return False
        self.current_ftmo_day = today_str
        self.balance_at_midnight = balance_now
        if self.daily_stop_active:
            self.daily_stop_active = False
        return True

    # -- stop evaluation -------------------------------------------------

    def evaluate(self, equity: float, cfg: FtmoLimitsConfig) -> None:
        """Update daily_stop_active / total_stop_active from the current
        equity, checking BOTH floors directly and independently (rather than
        only the tighter max() of the two) so that reaching the static 9200
        total floor always sets the sticky total stop even in a challenge
        phase where the daily floor (B0-300) is currently the looser of the
        pair -- e.g. B0=9400 means the daily floor alone is 9100, but the
        static total floor (9200) must still bind first, at 9200, not 9100
        (spec test 2: "must not use the remaining 100 USD headroom below
        it"). Total stop dominates and is sticky: once set it is only ever
        cleared by an explicit manual review (clear_total_stop_manually),
        never automatically."""
        if self.balance_at_midnight is None:
            raise RuntimeError("rollover_if_needed() must run before evaluate()")
        daily_floor = robot_daily_working_floor(self.balance_at_midnight, cfg)
        if is_floor_breached(equity, daily_floor):
            self.daily_stop_active = True
        if is_floor_breached(equity, cfg.robot_total_working_floor_usd):
            self.total_stop_active = True
            self.total_stop_reason = self.total_stop_reason or (
                f"equity {equity} <= total floor {cfg.robot_total_working_floor_usd} on {self.current_ftmo_day}"
            )

    def clear_total_stop_manually(self, operator_note: str) -> None:
        self.total_stop_active = False
        self.total_stop_reason = f"manually cleared: {operator_note}"

    def stop_active(self) -> bool:
        return self.daily_stop_active or self.total_stop_active

    # -- one entry per symbol per FTMO day -------------------------------

    def can_open_new_entry(self, symbol: str, ftmo_day_today: date) -> bool:
        if not self.history_reconciled:
            return False
        if self.stop_active():
            return False
        used = self.entries_used_by_day.get(ftmo_day_today.isoformat(), [])
        return symbol not in used

    def register_entry(self, symbol: str, ftmo_day_today: date) -> None:
        key = ftmo_day_today.isoformat()
        used = self.entries_used_by_day.setdefault(key, [])
        if symbol not in used:
            used.append(symbol)
