"""M1 CSV loading and gap-aware resampling to M5/H1.

A bar is only ever emitted for a bucket that actually has at least one M1 row
-- missing buckets are skipped, never synthesized (per spec section 8: "Neaizpildi
trūkstošās sveces ar izdomātām cenām"). Each emitted bar carries the count of
M1 rows it was built from and its expected count, so downstream consumers
(the range-coverage check in signals.py, the audit report) can tell a
complete bar from a thin one instead of treating every emitted bar as
equally trustworthy.
"""
from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from .signals import Candle
from .time_utils import ServerTimeModel


@dataclass(frozen=True)
class RichCandle(Candle):
    m1_row_count: int = 1
    expected_m1_rows: int = 1

    @property
    def is_complete(self) -> bool:
        return self.m1_row_count >= self.expected_m1_rows


def load_m1_csv(path: Path, server_time_model: ServerTimeModel) -> list[RichCandle]:
    rows: list[RichCandle] = []
    with Path(path).open(newline="") as f:
        reader = csv.reader(f)
        for row in reader:
            if not row:
                continue
            date_s, time_s, o_s, h_s, l_s, c_s, _vol_s = row[0], row[1], row[2], row[3], row[4], row[5], row[6]
            naive_dt = datetime.strptime(f"{date_s} {time_s}", "%Y.%m.%d %H:%M")
            utc_dt = server_time_model.to_utc(naive_dt)
            rows.append(
                RichCandle(
                    open_time_utc=utc_dt,
                    open=float(o_s),
                    high=float(h_s),
                    low=float(l_s),
                    close=float(c_s),
                    m1_row_count=1,
                    expected_m1_rows=1,
                )
            )
    rows.sort(key=lambda c: c.open_time_utc)
    return rows


def resample(m1_candles: list[RichCandle], period_minutes: int) -> list[RichCandle]:
    """Aggregate M1 candles into `period_minutes` buckets aligned to epoch
    (so M5 buckets fall on :00/:05/:10..., H1 buckets fall on the hour)."""
    buckets: dict[datetime, list[RichCandle]] = {}
    period = timedelta(minutes=period_minutes)
    for c in m1_candles:
        epoch_minutes = int(c.open_time_utc.timestamp() // 60)
        bucket_start_minutes = (epoch_minutes // period_minutes) * period_minutes
        bucket_start = c.open_time_utc.replace(second=0, microsecond=0) - timedelta(
            minutes=(epoch_minutes - bucket_start_minutes)
        )
        buckets.setdefault(bucket_start, []).append(c)

    out: list[RichCandle] = []
    for bucket_start in sorted(buckets):
        members = buckets[bucket_start]
        members.sort(key=lambda c: c.open_time_utc)
        out.append(
            RichCandle(
                open_time_utc=bucket_start,
                open=members[0].open,
                high=max(m.high for m in members),
                low=min(m.low for m in members),
                close=members[-1].close,
                m1_row_count=len(members),
                expected_m1_rows=period_minutes,
            )
        )
    return out
