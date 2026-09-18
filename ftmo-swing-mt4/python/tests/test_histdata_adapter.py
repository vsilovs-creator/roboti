"""Unit tests for ftmo_sim.histdata_adapter -- the long-history
(2015-2025) data adapter, docs/LONG_HISTORY_EXPERIMENT_PLAN.md.

Fixtures here are hand-written, in HistData's own documented "Generic
ASCII" format (semicolon-separated, EST-without-DST), never a real
downloaded file -- this project's own established rule
("Neaizstāj reālos datus ar sintētisku 'backtestu'") is about not
presenting SYNTHETIC data as if it were a real strategy result, not
about banning a synthetic fixture for testing a PARSER's correctness,
which is what these tests do.
"""
from __future__ import annotations

import zipfile
from datetime import datetime, timezone

from ftmo_sim.histdata_adapter import (
    parse_histdata_generic_ascii_m1,
    parse_histdata_m1,
    parse_histdata_mt_platform_m1,
)


def _write(tmp_path, name: str, lines: list[str]):
    p = tmp_path / name
    p.write_text("\n".join(lines) + "\n")
    return p


def test_est_without_dst_offset_applied_in_both_winter_and_summer(tmp_path):
    """HistData's own documented convention is a FIXED EST (UTC-5)
    offset, even in a summer month where EDT (UTC-4) would otherwise
    apply -- confirms this adapter does NOT accidentally apply a
    DST-aware conversion."""
    p = _write(tmp_path, "winter_and_summer.csv", [
        "20150102 000000;1.10000;1.10010;1.09990;1.10005;0",
        "20150701 000000;1.11000;1.11010;1.10990;1.11005;0",
    ])
    rows, report = parse_histdata_generic_ascii_m1(p)
    assert rows[0].open_time_utc == datetime(2015, 1, 2, 5, 0, tzinfo=timezone.utc)
    assert rows[1].open_time_utc == datetime(2015, 7, 1, 5, 0, tzinfo=timezone.utc)
    assert report.row_count_raw == 2
    assert report.row_count_after_dedup == 2


def test_duplicate_timestamp_is_counted_and_first_copy_kept(tmp_path):
    p = _write(tmp_path, "dup.csv", [
        "20150102 000000;1.10000;1.10010;1.09990;1.10005;0",
        "20150102 000000;1.20000;1.20010;1.19990;1.20005;0",
        "20150102 000100;1.10005;1.10015;1.09995;1.10010;0",
    ])
    rows, report = parse_histdata_generic_ascii_m1(p)
    assert report.duplicate_timestamp_count == 1
    assert len(rows) == 2
    assert rows[0].open == 1.10000, "the FIRST occurrence of a duplicated timestamp must survive"


def test_non_monotonic_row_is_counted_and_dropped(tmp_path):
    p = _write(tmp_path, "nonmono.csv", [
        "20150102 000100;1.10000;1.10010;1.09990;1.10005;0",
        "20150102 000000;1.20000;1.20010;1.19990;1.20005;0",  # goes BACKWARDS in time
        "20150102 000200;1.10005;1.10015;1.09995;1.10010;0",
    ])
    rows, report = parse_histdata_generic_ascii_m1(p)
    assert report.non_monotonic_count == 1
    assert [r.open for r in rows] == [1.10000, 1.10005]


def test_ohlc_sanity_violation_is_counted_not_silently_fixed(tmp_path):
    p = _write(tmp_path, "badohlc.csv", [
        # high (1.0999) is below open/close -- physically impossible, but
        # the adapter must count it and pass the row through UNCHANGED,
        # never clamp it into looking sane.
        "20150102 000000;1.10000;1.09990;1.09980;1.10005;0",
    ])
    rows, report = parse_histdata_generic_ascii_m1(p)
    assert report.ohlc_sanity_violation_count == 1
    assert rows[0].high == 1.09990, "a bad row is reported, never silently corrected"


def test_weekday_row_count_and_sha256_are_reported(tmp_path):
    p = _write(tmp_path, "sha.csv", [
        "20150103 000000;1.10000;1.10010;1.09990;1.10005;0",  # 2015-01-03 is a Saturday
    ])
    rows, report = parse_histdata_generic_ascii_m1(p)
    assert report.weekend_row_count == 1
    assert len(report.source_sha256) == 64
    assert len(report.normalized_sha256) == 64
    assert report.first_timestamp_utc == rows[0].open_time_utc.isoformat()
    assert report.last_timestamp_utc == rows[-1].open_time_utc.isoformat()


def test_zip_file_is_parsed_transparently_without_manual_unzipping(tmp_path):
    """HistData's own download is a .zip (one CSV + one status-report
    text file inside) -- this adapter must accept that .zip directly, so
    a user dropping the raw downloaded file into the data folder doesn't
    need an extra manual unzip step."""
    csv_lines = [
        "20150102 000000;1.10000;1.10010;1.09990;1.10005;0",
        "20150102 000100;1.10005;1.10015;1.09995;1.10010;0",
    ]
    zip_path = tmp_path / "DAT_ASCII_EURUSD_M1_2015.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("DAT_ASCII_EURUSD_M1_2015.csv", "\n".join(csv_lines) + "\n")
        zf.writestr("DAT_ASCII_EURUSD_M1_2015_status.txt", "some status/gap report, not CSV data")

    rows, report = parse_histdata_generic_ascii_m1(zip_path)
    assert len(rows) == 2
    assert rows[0].open_time_utc == datetime(2015, 1, 2, 5, 0, tzinfo=timezone.utc)
    assert report.row_count_raw == 2
    assert report.source_path == str(zip_path)


def test_zip_with_no_or_multiple_csv_members_raises_instead_of_guessing(tmp_path):
    zip_path = tmp_path / "ambiguous.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("a.csv", "20150102 000000;1.1;1.1;1.1;1.1;0\n")
        zf.writestr("b.csv", "20150102 000000;1.2;1.2;1.2;1.2;0\n")

    try:
        parse_histdata_generic_ascii_m1(zip_path)
        assert False, "expected a ValueError for an ambiguous ZIP, not a silent guess"
    except ValueError as exc:
        assert "a.csv" in str(exc) and "b.csv" in str(exc)


# ---------------------------------------------------------------------------
# MetaTrader platform export (`DAT_MT_*`) -- comma-separated,
# `YYYY.MM.DD,HH:MM,O,H,L,C,V`, confirmed from a real HistData MT-platform
# download in this session (a user-supplied
# HISTDATA_COM_MT_GBPUSD_M12019.zip). Same EST-without-DST convention as
# Generic ASCII -- NOT this project's own FTMO GMT+2/+3 model, even
# though the column syntax happens to match bars.load_m1_csv's.
# ---------------------------------------------------------------------------

def test_mt_platform_est_without_dst_offset_applied(tmp_path):
    p = _write(tmp_path, "mt_winter_and_summer.csv", [
        "2019.01.02,00:00,1.274590,1.274590,1.272500,1.272500,0",
        "2019.07.01,00:00,1.274590,1.274590,1.272500,1.272500,0",
    ])
    rows, report = parse_histdata_mt_platform_m1(p)
    assert rows[0].open_time_utc == datetime(2019, 1, 2, 5, 0, tzinfo=timezone.utc)
    assert rows[1].open_time_utc == datetime(2019, 7, 1, 5, 0, tzinfo=timezone.utc)
    assert report.row_count_raw == 2


def test_mt_platform_dedup_and_ohlc_checks_are_shared_with_ascii(tmp_path):
    p = _write(tmp_path, "mt_checks.csv", [
        "2019.01.02,00:00,1.10000,1.09990,1.09980,1.10005,0",  # bad OHLC: high < open/close
        "2019.01.02,00:00,1.20000,1.20010,1.19990,1.20005,0",  # duplicate timestamp
        "2019.01.02,00:01,1.10005,1.10015,1.09995,1.10010,0",
    ])
    rows, report = parse_histdata_mt_platform_m1(p)
    assert report.ohlc_sanity_violation_count == 1
    assert report.duplicate_timestamp_count == 1
    assert len(rows) == 2


def test_auto_detect_dispatches_by_zip_member_name(tmp_path):
    """A real HISTDATA_COM_MT_GBPUSD_M12019.zip-shaped file: the ZIP's
    OWN member name (`DAT_MT_GBPUSD_M1_2019.csv`) is what identifies the
    platform, per HistData's own naming convention -- exactly as
    observed in a real user-supplied download."""
    zip_path = tmp_path / "HISTDATA_COM_MT_GBPUSD_M12019.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("DAT_MT_GBPUSD_M1_2019.csv", "2019.01.02,00:00,1.27459,1.27459,1.27250,1.27250,0\n")
        zf.writestr("DAT_MT_GBPUSD_M1_2019.txt", "status report, not CSV data")

    rows, report = parse_histdata_m1(zip_path)
    assert len(rows) == 1
    assert rows[0].open_time_utc == datetime(2019, 1, 2, 5, 0, tzinfo=timezone.utc)


def test_auto_detect_dispatches_generic_ascii_too(tmp_path):
    p = _write(tmp_path, "DAT_ASCII_EURUSD_M1_2015.csv", [
        "20150102 000000;1.10000;1.10010;1.09990;1.10005;0",
    ])
    rows, report = parse_histdata_m1(p)
    assert rows[0].open_time_utc == datetime(2015, 1, 2, 5, 0, tzinfo=timezone.utc)


def test_auto_detect_falls_back_to_content_sniffing_for_an_unhinted_name(tmp_path):
    p = _write(tmp_path, "renamed_export.csv", [
        "2019.01.02,00:00,1.27459,1.27459,1.27250,1.27250,0",
    ])
    rows, report = parse_histdata_m1(p)
    assert rows[0].open_time_utc == datetime(2019, 1, 2, 5, 0, tzinfo=timezone.utc)
