"""Recomputes the raw-CSV data audit (row counts, timestamp integrity, OHLC
geometry, gap classification) independently of any number quoted elsewhere.
Never trust a previously-reported table without re-deriving it from the
actual file on disk -- this module is what re-derives it.

CSV format (no header, 7 fields): YYYY.MM.DD,HH:MM,Open,High,Low,Close,Volume
Timestamps are naive (no timezone marker in the file); this module reports
them as-is and does not assume a timezone. Volume semantics are unconfirmed
(see docs/UNKNOWNS.md) and are only surfaced here, never interpreted.
"""
from __future__ import annotations

import csv
import hashlib
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path


@dataclass
class GapRecord:
    prev_time: datetime
    next_time: datetime
    minutes: float
    classification: str  # "WEEKEND" | "SUSPECTED_INTRADAY_GAP"


@dataclass
class AuditResult:
    path: str
    sha256: str
    row_count: int
    first_time: datetime | None
    last_time: datetime | None
    distinct_calendar_days: int
    duplicate_timestamps: int
    invalid_ohlc_rows: int
    non_monotonic_rows: int
    gaps_over_1min: list[GapRecord] = field(default_factory=list)

    @property
    def weekend_gaps(self) -> int:
        return sum(1 for g in self.gaps_over_1min if g.classification == "WEEKEND")

    @property
    def suspected_intraday_gaps(self) -> int:
        return sum(1 for g in self.gaps_over_1min if g.classification == "SUSPECTED_INTRADAY_GAP")

    @property
    def largest_gap_minutes(self) -> float:
        return max((g.minutes for g in self.gaps_over_1min), default=0.0)


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _classify_gap(prev_dt: datetime, next_dt: datetime) -> str:
    """A gap that starts on/after Friday 21:00 and ends before Monday 03:00 is
    classified as a weekend close. This threshold is a documented heuristic
    (not an FTMO/broker-confirmed session boundary) chosen to be inside the
    observed Fri 23:5x -> Mon 00:0x pattern with margin; anything else over
    1 minute is a "suspected intraday gap" (daily server rollover pause,
    low-liquidity minute with no tick, holiday, or an actual data defect --
    this module does not further disambiguate those)."""
    if prev_dt.weekday() == 4 and prev_dt.hour >= 21 and next_dt.weekday() == 0 and next_dt.hour <= 3:
        return "WEEKEND"
    return "SUSPECTED_INTRADAY_GAP"


def audit_csv(path: Path) -> AuditResult:
    if not path.exists():
        raise FileNotFoundError(
            f"{path} not found -- the raw M1 CSV must be placed here before an audit can run "
            "(see docs/DATA_AUDIT.md for where this repo expects it)"
        )
    sha = _sha256(path)

    row_count = 0
    first_time = None
    last_time = None
    calendar_days: set = set()
    seen_timestamps: set = set()
    duplicate_timestamps = 0
    invalid_ohlc_rows = 0
    non_monotonic_rows = 0
    gaps: list[GapRecord] = []
    prev_dt: datetime | None = None

    with path.open(newline="") as f:
        reader = csv.reader(f)
        for row in reader:
            if not row:
                continue
            row_count += 1
            date_s, time_s, o_s, h_s, l_s, c_s, _vol_s = row[0], row[1], row[2], row[3], row[4], row[5], row[6]
            dt = datetime.strptime(f"{date_s} {time_s}", "%Y.%m.%d %H:%M")
            o, h, l, c = float(o_s), float(h_s), float(l_s), float(c_s)

            if first_time is None:
                first_time = dt
            last_time = dt
            calendar_days.add(dt.date())

            if dt in seen_timestamps:
                duplicate_timestamps += 1
            seen_timestamps.add(dt)

            if not (l <= o <= h and l <= c <= h and l <= h):
                invalid_ohlc_rows += 1

            if prev_dt is not None:
                if dt < prev_dt:
                    non_monotonic_rows += 1
                else:
                    delta_min = (dt - prev_dt).total_seconds() / 60.0
                    if delta_min > 1:
                        gaps.append(GapRecord(prev_dt, dt, delta_min, _classify_gap(prev_dt, dt)))
            prev_dt = dt

    return AuditResult(
        path=str(path),
        sha256=sha,
        row_count=row_count,
        first_time=first_time,
        last_time=last_time,
        distinct_calendar_days=len(calendar_days),
        duplicate_timestamps=duplicate_timestamps,
        invalid_ohlc_rows=invalid_ohlc_rows,
        non_monotonic_rows=non_monotonic_rows,
        gaps_over_1min=gaps,
    )


def format_audit_report(result: AuditResult) -> str:
    lines = [
        f"# Data audit: {result.path}",
        "",
        f"- SHA-256: `{result.sha256}`",
        f"- Row count: {result.row_count}",
        f"- First timestamp (file-local, tz unconfirmed): {result.first_time}",
        f"- Last timestamp (file-local, tz unconfirmed): {result.last_time}",
        f"- Distinct calendar days in file: {result.distinct_calendar_days}",
        f"- Duplicate timestamps: {result.duplicate_timestamps}",
        f"- Invalid OHLC geometry rows: {result.invalid_ohlc_rows}",
        f"- Non-monotonic timestamp rows: {result.non_monotonic_rows}",
        f"- Rows preceded by a >1 minute gap: {len(result.gaps_over_1min)}"
        f" (weekend: {result.weekend_gaps}, suspected intraday: {result.suspected_intraday_gaps})",
        f"- Largest gap: {result.largest_gap_minutes:.0f} minutes",
    ]
    return "\n".join(lines)


if __name__ == "__main__":
    import sys

    for arg in sys.argv[1:]:
        result = audit_csv(Path(arg))
        print(format_audit_report(result))
        print()
