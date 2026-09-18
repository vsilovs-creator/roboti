"""Time-zone handling for the FTMO Swing prototype.

Three distinct clocks are in play and must never be conflated:

1. FTMO trading day boundary -- Europe/Prague (CET/CEST).
2. Strategy session windows (range / entry / session close) -- Europe/London (GMT/BST).
3. The CSV / broker server clock -- unknown offset and unknown DST regime.

All internal computation uses timezone-aware UTC ``datetime`` objects. Conversion
to/from the broker's naive server timestamps goes exclusively through
``ServerTimeModel``, so the assumption is isolated, labeled, and swappable
instead of silently baked into a fixed UTC offset.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

PRAGUE_TZ = ZoneInfo("Europe/Prague")
LONDON_TZ = ZoneInfo("Europe/London")


def ftmo_trading_day(dt_utc: datetime) -> date:
    """Calendar date (Europe/Prague) that a UTC instant belongs to."""
    _require_aware_utc(dt_utc)
    return dt_utc.astimezone(PRAGUE_TZ).date()


def ftmo_day_boundaries_utc(day: date) -> tuple[datetime, datetime]:
    """UTC [start, end) instants of one FTMO trading day (Prague midnight to midnight).

    Correctly spans 23h/25h on DST transition days because the boundary is
    computed in Europe/Prague wall-clock time and only converted to UTC last.
    """
    start_local = datetime(day.year, day.month, day.day, tzinfo=PRAGUE_TZ)
    end_local = start_local + timedelta(days=1)
    return start_local.astimezone(timezone.utc), end_local.astimezone(timezone.utc)


def london_time_of_day(dt_utc: datetime) -> time:
    _require_aware_utc(dt_utc)
    return dt_utc.astimezone(LONDON_TZ).timetz().replace(tzinfo=None)


def london_date(dt_utc: datetime) -> date:
    _require_aware_utc(dt_utc)
    return dt_utc.astimezone(LONDON_TZ).date()


def in_half_open_window(t: time, start: time, end: time) -> bool:
    """True if start <= t < end. Windows here never wrap past midnight."""
    if start > end:
        raise ValueError("windows in this project are same-day and non-wrapping")
    return start <= t < end


def _require_aware_utc(dt: datetime) -> None:
    if dt.tzinfo is None:
        raise ValueError("naive datetime passed where a timezone-aware UTC datetime was required")
    if dt.utcoffset() != timedelta(0):
        raise ValueError("datetime must be normalized to UTC before calling this function")


@dataclass(frozen=True)
class ServerTimeModel:
    """Converts naive broker/server timestamps (as read from the CSV files) to
    timezone-aware UTC. The server offset and DST calendar are now CONFIRMED
    (see docs/UNKNOWNS.md) but this class still exists so that assumption is
    a single, explicit, swappable, and testable place instead of a hardcoded
    UTC offset scattered through the codebase -- and so an unverified/
    sensitivity scenario stays clearly distinguishable from the confirmed one.

    mode:
      - "assume_utc": server timestamps are treated as already UTC (no shift,
        no DST). This is the most conservative default for structural tests;
        it is NOT claimed to be correct for the real broker feed.
      - "fixed_offset": server_utc_offset_hours is a constant offset from UTC
        with no DST (e.g. a broker that never shifts its own clock).
      - "zone_like": the server clock follows the DST rules of
        `hypothesis_zone_name` while remaining a distinct clock from
        Prague/London. CONFIRMED (2026-09-18, account owner): this broker's
        MT4 server runs GMT+2 in winter / GMT+3 in summer (DST), on the same
        transition dates as the EU. "Europe/Bucharest" is used as the
        zoneinfo stand-in for exactly that GMT+2/+3-with-EU-DST pattern
        (zoneinfo has no generic "fixed EET-like, non-Romanian" zone; the
        offsets and transition dates are what matter here, not the label).
        Pass verified=True once a mode is actually confirmed like this one
        is; leave verified=False for a labeled sensitivity/what-if scenario.

    verified: True once a human has confirmed this is the real server clock
        (not merely a structural placeholder or a sensitivity hypothesis).
        Callers that produce anything claiming to be a validated (non
        EXPLORATORY) result must check this and refuse/label accordingly.
    """

    mode: str
    server_utc_offset_hours: float | None = None
    hypothesis_zone_name: str | None = None
    verified: bool = False

    def __post_init__(self) -> None:
        if self.mode == "fixed_offset" and self.server_utc_offset_hours is None:
            raise ValueError("fixed_offset mode requires server_utc_offset_hours")
        if self.mode == "zone_like" and not self.hypothesis_zone_name:
            raise ValueError("zone_like mode requires hypothesis_zone_name")
        if self.mode not in ("assume_utc", "fixed_offset", "zone_like"):
            raise ValueError(f"unknown ServerTimeModel mode: {self.mode!r}")

    def to_utc(self, naive_server_dt: datetime) -> datetime:
        if naive_server_dt.tzinfo is not None:
            raise ValueError("expected a naive server-local datetime")
        if self.mode == "assume_utc":
            return naive_server_dt.replace(tzinfo=timezone.utc)
        if self.mode == "fixed_offset":
            offset = timedelta(hours=self.server_utc_offset_hours)
            return (naive_server_dt - offset).replace(tzinfo=timezone.utc)
        # zone_like
        zone = ZoneInfo(self.hypothesis_zone_name)
        localized = naive_server_dt.replace(tzinfo=zone)
        return localized.astimezone(timezone.utc)

    @property
    def is_verified(self) -> bool:
        return self.verified
