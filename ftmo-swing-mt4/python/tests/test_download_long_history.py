"""Unit tests for scripts/download_long_history.py's retry/backoff/
manifest/resumability logic -- exercised via an injected fake fetch
function, so no real network access is needed (or possible, in this
session's own sandboxed environment -- see
docs/LONG_HISTORY_EXPERIMENT_PLAN.md for why)."""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


def _load_module():
    script_path = Path(__file__).parent.parent / "scripts" / "download_long_history.py"
    spec = importlib.util.spec_from_file_location("download_long_history_check", script_path)
    mod = importlib.util.module_from_spec(spec)
    # Must be registered in sys.modules BEFORE exec_module: the script's
    # @dataclass JobResult (combined with `from __future__ import
    # annotations`) needs to resolve its own module by name while being
    # defined, which the dataclasses stdlib module does via
    # sys.modules[cls.__module__].
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def test_successful_job_is_recorded_in_manifest_with_sha256(tmp_path):
    mod = _load_module()
    out_dir = tmp_path / "out"

    def fake_fetch(pair, year, out_dir_arg):
        out_dir_arg.mkdir(parents=True, exist_ok=True)
        p = out_dir_arg / f"DAT_ASCII_{pair.upper()}_M1_{year}.zip"
        p.write_bytes(b"fake zip contents")
        return p

    manifest_path = tmp_path / "manifest.json"
    results = mod.run_downloads(
        pairs=["eurusd"], years=[2015], out_dir=out_dir, manifest_path=manifest_path,
        fetch_one=fake_fetch, sleep_fn=lambda s: None,
    )
    assert len(results) == 1
    assert results[0].status == "SUCCESS"
    assert results[0].sha256 is not None

    manifest = json.loads(manifest_path.read_text())
    assert manifest["jobs"]["eurusd_2015"]["status"] == "SUCCESS"


def test_transient_failures_retry_with_backoff_then_succeed(tmp_path):
    mod = _load_module()
    out_dir = tmp_path / "out"
    call_count = {"n": 0}
    sleeps: list[float] = []

    def flaky_fetch(pair, year, out_dir_arg):
        call_count["n"] += 1
        if call_count["n"] < 3:
            raise ConnectionError("simulated transient failure")
        out_dir_arg.mkdir(parents=True, exist_ok=True)
        p = out_dir_arg / f"DAT_ASCII_{pair.upper()}_M1_{year}.zip"
        p.write_bytes(b"ok")
        return p

    manifest_path = tmp_path / "manifest.json"
    results = mod.run_downloads(
        pairs=["gbpusd"], years=[2016], out_dir=out_dir, manifest_path=manifest_path,
        max_retries=5, backoff_base_seconds=1.0, fetch_one=flaky_fetch,
        sleep_fn=lambda s: sleeps.append(s),
    )
    assert results[0].status == "SUCCESS"
    assert results[0].attempts == 3
    # exponential backoff between the two failed attempts (1.0, 2.0), plus
    # the rate-limit sleep after the job succeeds.
    assert sleeps[:2] == [1.0, 2.0]


def test_exhausted_retries_records_failed_and_continues_to_next_job(tmp_path):
    mod = _load_module()
    out_dir = tmp_path / "out"

    def always_fails(pair, year, out_dir_arg):
        raise ConnectionError("simulated permanent block (e.g. this session's own egress policy)")

    manifest_path = tmp_path / "manifest.json"
    results = mod.run_downloads(
        pairs=["eurusd"], years=[2015, 2016], out_dir=out_dir, manifest_path=manifest_path,
        max_retries=2, backoff_base_seconds=0.01, fetch_one=always_fails, sleep_fn=lambda s: None,
    )
    assert [r.status for r in results] == ["FAILED", "FAILED"]
    assert results[0].attempts == 2
    assert "simulated permanent block" in results[0].error


def test_a_job_already_marked_success_on_disk_is_skipped_on_rerun(tmp_path):
    mod = _load_module()
    out_dir = tmp_path / "out"
    calls = {"n": 0}

    def counting_fetch(pair, year, out_dir_arg):
        calls["n"] += 1
        out_dir_arg.mkdir(parents=True, exist_ok=True)
        p = out_dir_arg / f"DAT_ASCII_{pair.upper()}_M1_{year}.zip"
        p.write_bytes(b"ok")
        return p

    manifest_path = tmp_path / "manifest.json"
    mod.run_downloads(
        pairs=["eurusd"], years=[2015], out_dir=out_dir, manifest_path=manifest_path,
        fetch_one=counting_fetch, sleep_fn=lambda s: None,
    )
    assert calls["n"] == 1

    # Simulating a re-run after an interruption: the manifest + output
    # file both already exist, so the job must be skipped, not re-fetched.
    results = mod.run_downloads(
        pairs=["eurusd"], years=[2015], out_dir=out_dir, manifest_path=manifest_path,
        fetch_one=counting_fetch, sleep_fn=lambda s: None,
    )
    assert calls["n"] == 1, "a re-run must not re-fetch a job the manifest already marks SUCCESS"
    assert results[0].status == "SKIPPED_ALREADY_DONE"
