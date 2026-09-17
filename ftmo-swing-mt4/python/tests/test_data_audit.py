"""Data audit correctness on a small synthetic fixture (never used as a
trading/backtest fixture, only to exercise the audit arithmetic), plus a
regression check against the real supplied CSVs pinning down the exact
numbers reported in the task spec's own audit table."""
from pathlib import Path

import pytest

from ftmo_sim.data_audit import audit_csv

FIXTURES = Path(__file__).parent / "fixtures"
DATA_RAW = Path(__file__).parent.parent.parent / "data" / "raw"


def test_synthetic_fixture_audit():
    result = audit_csv(FIXTURES / "synthetic_audit_sample.csv")
    assert result.row_count == 7
    assert result.duplicate_timestamps == 1
    assert result.invalid_ohlc_rows == 1
    assert result.non_monotonic_rows == 1
    assert len(result.gaps_over_1min) == 1
    assert result.gaps_over_1min[0].classification == "SUSPECTED_INTRADAY_GAP"


@pytest.mark.skipif(not (DATA_RAW / "EURUSD1.csv").exists(), reason="raw EURUSD1.csv not present in this checkout")
def test_real_eurusd_matches_task_spec_audit_table():
    result = audit_csv(DATA_RAW / "EURUSD1.csv")
    assert result.sha256 == "5f97acdd75114b27db880ecc74fdc1f73087dc8c56b91b168ded3ff310494ad2"
    assert result.row_count == 65126
    assert result.distinct_calendar_days == 46
    assert result.duplicate_timestamps == 0
    assert result.invalid_ohlc_rows == 0
    assert result.non_monotonic_rows == 0
    assert len(result.gaps_over_1min) == 364
    assert result.largest_gap_minutes == 2891


@pytest.mark.skipif(not (DATA_RAW / "GBPUSD1.csv").exists(), reason="raw GBPUSD1.csv not present in this checkout")
def test_real_gbpusd_matches_task_spec_audit_table():
    result = audit_csv(DATA_RAW / "GBPUSD1.csv")
    assert result.sha256 == "367290d4be0bb6ee0c8f0333dd95fac349e27e41a65194b5dd97290e6453d393"
    assert result.row_count == 65352
    assert result.distinct_calendar_days == 47
    assert result.duplicate_timestamps == 0
    assert result.invalid_ohlc_rows == 0
    assert result.non_monotonic_rows == 0
    assert len(result.gaps_over_1min) == 271
    assert result.largest_gap_minutes == 2891
