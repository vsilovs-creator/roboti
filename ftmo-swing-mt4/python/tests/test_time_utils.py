"""Spec section 9 test 9: DST transitions, an alternate server-DST-calendar
sensitivity scenario, and weekend handling (no midnight tick)."""
from datetime import datetime, timedelta, timezone

import pytest

from ftmo_sim.time_utils import (
    ServerTimeModel,
    ftmo_day_boundaries_utc,
    ftmo_trading_day,
    in_half_open_window,
    london_time_of_day,
)
from datetime import time


def test_ftmo_day_boundaries_normal_day():
    start, end = ftmo_day_boundaries_utc(datetime(2026, 8, 10).date())
    # Europe/Prague is CEST (UTC+2) in August.
    assert start == datetime(2026, 8, 9, 22, 0, tzinfo=timezone.utc)
    assert end == datetime(2026, 8, 10, 22, 0, tzinfo=timezone.utc)
    assert (end - start) == timedelta(hours=24)


def test_ftmo_day_boundaries_spans_23_hours_on_spring_forward():
    # EU clocks spring forward on the last Sunday of March 2026-03-29.
    start, end = ftmo_day_boundaries_utc(datetime(2026, 3, 29).date())
    assert (end - start) == timedelta(hours=23)


def test_ftmo_day_boundaries_spans_25_hours_on_fall_back():
    # EU clocks fall back on the last Sunday of October 2026-10-25.
    start, end = ftmo_day_boundaries_utc(datetime(2026, 10, 25).date())
    assert (end - start) == timedelta(hours=25)


def test_ftmo_trading_day_uses_prague_not_utc():
    # 23:30 UTC on 2026-08-10 is already 2026-08-11 01:30 in Prague (CEST).
    dt = datetime(2026, 8, 10, 23, 30, tzinfo=timezone.utc)
    assert ftmo_trading_day(dt) == datetime(2026, 8, 11).date()


def test_london_session_window_shifts_relative_to_utc_across_dst():
    # London range window is [00:00,07:00) London time. In BST (UTC+1,
    # e.g. August) that is [23:00 prev day, 06:00) UTC; in GMT (winter) it is
    # exactly [00:00,07:00) UTC. The *window itself* never changes; only its
    # UTC projection does -- this pins that projection down explicitly.
    summer = datetime(2026, 8, 10, 23, 30, tzinfo=timezone.utc)  # BST
    winter = datetime(2026, 1, 10, 23, 30, tzinfo=timezone.utc)  # GMT
    assert in_half_open_window(london_time_of_day(summer), time(0, 0), time(7, 0)) is True
    assert in_half_open_window(london_time_of_day(winter), time(0, 0), time(7, 0)) is False


def test_server_time_model_assume_utc():
    model = ServerTimeModel(mode="assume_utc")
    naive = datetime(2026, 8, 10, 12, 0)
    assert model.to_utc(naive) == datetime(2026, 8, 10, 12, 0, tzinfo=timezone.utc)
    assert model.is_verified is False


def test_server_time_model_fixed_offset():
    # A broker server running 2 hours ahead of UTC with no DST of its own.
    model = ServerTimeModel(mode="fixed_offset", server_utc_offset_hours=2.0)
    naive = datetime(2026, 8, 10, 14, 0)
    assert model.to_utc(naive) == datetime(2026, 8, 10, 12, 0, tzinfo=timezone.utc)


def test_server_time_model_zone_like_sensitivity_hypothesis():
    # Documented sensitivity scenario only: server clock hypothesized to
    # follow Europe/Bucharest's own DST calendar (EEST = UTC+3 in August).
    model = ServerTimeModel(mode="zone_like", hypothesis_zone_name="Europe/Bucharest")
    naive = datetime(2026, 8, 10, 15, 0)
    assert model.to_utc(naive) == datetime(2026, 8, 10, 12, 0, tzinfo=timezone.utc)
    assert model.is_verified is False


def test_server_time_model_rejects_aware_input():
    model = ServerTimeModel(mode="assume_utc")
    with pytest.raises(ValueError):
        model.to_utc(datetime(2026, 8, 10, 12, 0, tzinfo=timezone.utc))


def test_weekend_has_no_midnight_tick_but_day_boundary_still_defined():
    # No tick arriving over a weekend must not crash boundary computation;
    # the FTMO day for Saturday still resolves even though no trading
    # happens and no equity sample exists for it.
    saturday = datetime(2026, 8, 15).date()  # a Saturday
    start, end = ftmo_day_boundaries_utc(saturday)
    assert start < end
