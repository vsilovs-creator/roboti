"""Adapter for HistData.com's 1-minute bar export formats, for the
long-history (2015-2025) S1-S8 comparison
(docs/LONG_HISTORY_EXPERIMENT_PLAN.md).

Kept separate from bars.py's `load_m1_csv`: that loader is for the
project's existing 2026 MT4-exported sample (date/time split into two
columns, unknown server-clock offset resolved via `ServerTimeModel`'s
confirmed GMT+2/+3 EU-DST convention) -- a DIFFERENT source with a
DIFFERENT, already-confirmed timezone assumption. Reusing that model for
HistData data would silently apply the wrong offset; per the task's own
instruction ("Neizmanto esošo FTMO GMT+2/+3 konvertēšanu jaunajiem
datiem automātiski"), this module applies ONLY HistData's own documented
convention instead -- to EVERY HistData export platform, not just one,
since the underlying M1 series and its EST-without-DST timestamp
convention is the same data regardless of which file syntax ("platform")
it is exported in; only the column layout differs.

Two HistData export "platforms" are supported, auto-detected from the
file/ZIP-member name (falling back to sniffing the first data line if
that is inconclusive):

- **Generic ASCII** (`DAT_ASCII_*`): one semicolon-separated row per M1
  bar, `YYYYMMDD HHMMSS;OPEN;HIGH;LOW;CLOSE;VOLUME` -- documented in the
  `histdata` PyPI package's own README (read directly in this session).
- **MetaTrader** (`DAT_MT_*`): one comma-separated row per M1 bar,
  `YYYY.MM.DD,HH:MM,OPEN,HIGH,LOW,CLOSE,VOLUME` -- confirmed directly
  from a real HistData MT-platform download in this session (its
  column layout happens to be syntactically identical to this
  project's OWN existing MT4-exported 2026 sample that `bars.load_m1_csv`
  reads -- but the TIMEZONE is NOT the same, see above, so that loader
  is still never reused here).

Both platforms use the SAME Eastern Standard Time (EST), *WITHOUT*
Daylight Saving adjustment -- i.e. a FIXED UTC-5 offset year-round,
never UTC-4, even in summer. This is HistData's own stated convention
for their underlying data, not an assumption this project is making up;
it is applied here as a constant `timedelta(hours=5)` added to the
naive timestamp to reach UTC. Volume is documented as "always 0" and is
ignored (this project's M1 bars carry no volume field).
"""
from __future__ import annotations

import hashlib
import zipfile
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .bars import RichCandle

# HistData's own documented convention (see module docstring): a FIXED
# EST offset, never adjusted for daylight saving -- applies to every
# platform this module supports.
_HISTDATA_EST_TO_UTC = timedelta(hours=5)


@dataclass
class DataQualityReport:
    """Machine-readable integrity report for one parsed HistData ASCII
    file -- FTMO_2-Step_Swing_MT4's established "never silently trust a
    row" discipline (docs/AUDIT_2026-09-18.md), applied to a brand-new
    data source instead of the existing sample."""

    source_path: str
    source_sha256: str
    row_count_raw: int
    row_count_after_dedup: int
    duplicate_timestamp_count: int
    non_monotonic_count: int
    ohlc_sanity_violation_count: int
    first_timestamp_utc: str | None
    last_timestamp_utc: str | None
    weekend_row_count: int
    normalized_sha256: str

    def as_dict(self) -> dict:
        return {
            "source_path": self.source_path,
            "source_sha256": self.source_sha256,
            "row_count_raw": self.row_count_raw,
            "row_count_after_dedup": self.row_count_after_dedup,
            "duplicate_timestamp_count": self.duplicate_timestamp_count,
            "non_monotonic_count": self.non_monotonic_count,
            "ohlc_sanity_violation_count": self.ohlc_sanity_violation_count,
            "first_timestamp_utc": self.first_timestamp_utc,
            "last_timestamp_utc": self.last_timestamp_utc,
            "weekend_row_count": self.weekend_row_count,
            "normalized_sha256": self.normalized_sha256,
        }


def _sha256_of_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _sha256_of_rows(rows: list[RichCandle]) -> str:
    h = hashlib.sha256()
    for c in rows:
        h.update(f"{c.open_time_utc.isoformat()};{c.open};{c.high};{c.low};{c.close}\n".encode())
    return h.hexdigest()


def _read_lines(path: Path) -> tuple[list[str], str]:
    """Returns (raw CSV lines, a name hint for platform auto-detection)
    for one HistData export -- transparently unzips a `.zip` (HistData's
    own download format: one ZIP per pair/year, containing exactly one
    CSV plus a status report text file, per the `histdata` PyPI
    package's own documented behavior) or reads a `.csv` directly if it
    was already extracted. The hint is the ZIP member's own name (e.g.
    `DAT_MT_GBPUSD_M1_2019.csv`) for a ZIP, or `path.name` otherwise --
    HistData's own naming convention names the actual export platform,
    which is more reliable than sniffing content alone. Never guesses
    which member is the data file: a ZIP with zero or more than one
    `.csv` member raises immediately rather than silently picking one."""
    if path.suffix.lower() == ".zip":
        with zipfile.ZipFile(path) as zf:
            csv_members = [n for n in zf.namelist() if n.lower().endswith(".csv")]
            if len(csv_members) != 1:
                raise ValueError(
                    f"{path}: expected exactly one .csv member in the ZIP, found {csv_members!r}"
                )
            with zf.open(csv_members[0]) as f:
                return f.read().decode("utf-8").splitlines(), csv_members[0]
    with path.open(newline="") as f:
        return f.read().splitlines(), path.name


def _parse_generic_ascii_line(line: str) -> tuple[datetime, float, float, float, float]:
    date_time_s, o_s, h_s, l_s, c_s, _v_s = line.split(";")
    naive = datetime.strptime(date_time_s, "%Y%m%d %H%M%S")
    return naive, float(o_s), float(h_s), float(l_s), float(c_s)


def _parse_mt_platform_line(line: str) -> tuple[datetime, float, float, float, float]:
    date_s, time_s, o_s, h_s, l_s, c_s, _v_s = line.split(",")
    naive = datetime.strptime(f"{date_s} {time_s}", "%Y.%m.%d %H:%M")
    return naive, float(o_s), float(h_s), float(l_s), float(c_s)


def _detect_platform(lines: list[str], name_hint: str) -> str:
    """`"ascii"` or `"mt"`, from HistData's own file-naming convention
    first (`DAT_ASCII_*` / `DAT_MT_*`), falling back to sniffing the
    first non-empty data line's separator if the name is inconclusive
    (e.g. a renamed file) -- never silently defaults to one platform
    without evidence."""
    upper = name_hint.upper()
    if "DAT_ASCII_" in upper or "_ASCII_" in upper:
        return "ascii"
    if "DAT_MT_" in upper or "_MT_" in upper:
        return "mt"
    for line in lines:
        line = line.strip()
        if not line:
            continue
        if ";" in line:
            return "ascii"
        if "," in line:
            return "mt"
        raise ValueError(f"could not detect HistData platform from {name_hint!r} or its content")
    raise ValueError(f"{name_hint!r} has no data lines to detect a platform from")


def _parse_histdata_lines(
    lines: list[str], line_parser,
) -> tuple[list[tuple[datetime, float, float, float, float]], int]:
    """Shared row-level parsing: applies `line_parser` (one of the two
    per-platform functions above) to every non-blank line, converts EST
    to UTC, and counts (never clamps) an OHLC sanity violation. Returns
    the raw (UTC) rows plus the violation count; deduplication/
    monotonicity/reporting is shared further, in `_build_result`."""
    raw_rows: list[tuple[datetime, float, float, float, float]] = []
    ohlc_violations = 0
    for line in lines:
        line = line.strip()
        if not line:
            continue
        naive, o, h, l, c = line_parser(line)
        utc_dt = (naive + _HISTDATA_EST_TO_UTC).replace(tzinfo=timezone.utc)
        if not (l <= min(o, c) <= max(o, c) <= h):
            ohlc_violations += 1
        raw_rows.append((utc_dt, o, h, l, c))
    return raw_rows, ohlc_violations


def _build_result(
    path: Path, raw_rows: list[tuple[datetime, float, float, float, float]], ohlc_violations: int,
) -> tuple[list[RichCandle], DataQualityReport]:
    """Shared post-processing (dedup, monotonicity, weekend count,
    report assembly) for both HistData platforms -- see
    `parse_histdata_generic_ascii_m1`'s docstring for the exact rules;
    identical regardless of which platform's syntax produced `raw_rows`."""
    source_sha256 = _sha256_of_file(path)
    row_count_raw = len(raw_rows)
    seen_times: set = set()
    duplicate_count = 0
    deduped: list[tuple[datetime, float, float, float, float]] = []
    for row in raw_rows:
        t = row[0]
        if t in seen_times:
            duplicate_count += 1
            continue
        seen_times.add(t)
        deduped.append(row)

    non_monotonic_count = 0
    kept: list[tuple[datetime, float, float, float, float]] = []
    prev_t: datetime | None = None
    for row in deduped:
        t = row[0]
        if prev_t is not None and t <= prev_t:
            non_monotonic_count += 1
            continue
        kept.append(row)
        prev_t = t

    weekend_count = sum(1 for row in kept if row[0].weekday() >= 5)

    out = [
        RichCandle(open_time_utc=t, open=o, high=h, low=l, close=c, m1_row_count=1, expected_m1_rows=1)
        for (t, o, h, l, c) in kept
    ]
    report = DataQualityReport(
        source_path=str(path),
        source_sha256=source_sha256,
        row_count_raw=row_count_raw,
        row_count_after_dedup=len(kept),
        duplicate_timestamp_count=duplicate_count,
        non_monotonic_count=non_monotonic_count,
        ohlc_sanity_violation_count=ohlc_violations,
        first_timestamp_utc=out[0].open_time_utc.isoformat() if out else None,
        last_timestamp_utc=out[-1].open_time_utc.isoformat() if out else None,
        weekend_row_count=weekend_count,
        normalized_sha256=_sha256_of_rows(out),
    )
    return out, report


def parse_histdata_generic_ascii_m1(path: Path) -> tuple[list[RichCandle], DataQualityReport]:
    """Parses one HistData "Generic ASCII" M1 export (semicolon-separated,
    `YYYYMMDD HHMMSS;O;H;L;C;V`, EST-without-DST) into UTC `RichCandle`
    rows, PLUS a `DataQualityReport` -- never silently drops/normalizes a
    problem row without counting it. `path` may be either the extracted
    `.csv` directly, OR the original `.zip` exactly as HistData serves it
    (unzipped transparently in-memory, never written back to disk) --
    the raw HistData download need not be unpacked first. A trailing/
    leading blank line is skipped; anything else that fails to parse
    raises (never silently skipped -- a malformed HistData export is a
    reason to stop, not to quietly lose rows).

    Row handling, in order:
    1. Parse timestamp (EST fixed offset -> UTC) and OHLC floats.
    2. OHLC sanity check (low <= min(open,close) <= max(open,close) <=
       high) -- a violation is COUNTED, never fixed by clamping (the
       original row's OHLC is trusted verbatim otherwise; a violation
       always means the raw source data itself is wrong, not this
       adapter, and is surfaced for the caller to decide whether that
       makes the whole file unusable).
    3. Duplicate exact timestamps -- COUNTED, and only the FIRST
       occurrence is kept (arbitrary but deterministic; a real duplicate
       in HistData's own export is undocumented and unexpected, so
       counting it loudly matters more than which copy survives).
    4. Non-monotonic timestamps (this row's UTC time <= the previous
       KEPT row's) -- COUNTED and the offending row is dropped, since
       every simulator in this project assumes a strictly increasing M1
       timeline.
    """
    lines, _hint = _read_lines(path)
    raw_rows, ohlc_violations = _parse_histdata_lines(lines, _parse_generic_ascii_line)
    return _build_result(path, raw_rows, ohlc_violations)


def parse_histdata_mt_platform_m1(path: Path) -> tuple[list[RichCandle], DataQualityReport]:
    """Same as `parse_histdata_generic_ascii_m1`, for HistData's
    "MetaTrader" export platform instead (comma-separated,
    `YYYY.MM.DD,HH:MM,O,H,L,C,V`, SAME EST-without-DST convention --
    see the module docstring). `path` may be the `.zip` or an already-
    extracted `.csv`, same as the Generic ASCII function."""
    lines, _hint = _read_lines(path)
    raw_rows, ohlc_violations = _parse_histdata_lines(lines, _parse_mt_platform_line)
    return _build_result(path, raw_rows, ohlc_violations)


def parse_histdata_m1(path: Path) -> tuple[list[RichCandle], DataQualityReport]:
    """Auto-detects which HistData export platform `path` is (Generic
    ASCII or MetaTrader -- see `_detect_platform`) and parses it
    accordingly. Prefer calling this directly unless the platform is
    already known for certain; it is not itself a third format, just a
    dispatcher over the two functions above."""
    lines, name_hint = _read_lines(path)
    platform = _detect_platform(lines, name_hint)
    line_parser = _parse_generic_ascii_line if platform == "ascii" else _parse_mt_platform_line
    raw_rows, ohlc_violations = _parse_histdata_lines(lines, line_parser)
    return _build_result(path, raw_rows, ohlc_violations)
