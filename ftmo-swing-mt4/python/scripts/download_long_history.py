#!/usr/bin/env python3
"""Resumable downloader for the long-history (2015-2025) M1 EURUSD/GBPUSD
comparison, docs/LONG_HISTORY_EXPERIMENT_PLAN.md.

Wraps the real, already-published `histdata` PyPI package
(https://pypi.org/project/histdata/) rather than reimplementing
HistData.com's own request mechanics -- that package's
`download_hist_data()` was read directly in this session (its actual
source, not a guess) and confirmed to do a plain two-step
GET-token/POST-form request against histdata.com with no CAPTCHA
involved; this script only adds retry/backoff, a resumable JSON
manifest, and rate limiting around it, matching this project's own
established "verify before trusting, never fabricate a plausible-
looking mechanism" discipline.

KNOWN LIMITATION, confirmed in THIS session's own sandboxed environment
(see docs/LONG_HISTORY_EXPERIMENT_PLAN.md's source-evaluation section
for the full evidence): outbound network access to www.histdata.com (and
every alternative source tried) is blocked by this session's own network
egress policy -- `pip install histdata` succeeds (PyPI is reachable),
but the package's actual HTTP request to histdata.com fails with a 403
from this session's own proxy, NOT from HistData. This script is
real, runnable code -- it has simply not been able to actually run to
completion inside THIS session. Run it in an unrestricted environment
to perform the real download; see the module-level `EXACT_COMMAND`
string below for the single reproducible command.

Usage:
    python3 download_long_history.py \\
        --pairs eurusd,gbpusd --start-year 2015 --end-year 2025 \\
        --out-dir ../data/raw/long_history \\
        --manifest ../data/raw/long_history/manifest.json

Respects HistData's own access pattern: one request per (pair, year), a
`--rate-limit-seconds` pause between distinct jobs (default 5s, polite
rather than aggressive), and up to `--max-retries` attempts per job with
exponential backoff -- never a hammering retry loop. Never attempts to
defeat a CAPTCHA or authentication wall; if HistData's site presents
either, this script (and the underlying `histdata` package) simply fails
that job and moves on, exactly as it already does for a network-level
block.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

EXACT_COMMAND = (
    "pip install histdata && "
    "python3 scripts/download_long_history.py "
    "--pairs eurusd,gbpusd --start-year 2015 --end-year 2025 "
    "--out-dir ../data/raw/long_history --manifest ../data/raw/long_history/manifest.json"
)


@dataclass
class JobResult:
    pair: str
    year: int
    status: str  # "SUCCESS" | "FAILED" | "SKIPPED_ALREADY_DONE"
    output_path: str | None
    sha256: str | None
    attempts: int
    error: str | None
    finished_at_utc: str


def _expected_output_filename(pair: str, year: int) -> str:
    # Matches histdata.download_hist_data()'s own naming convention for a
    # month=None (whole-year, "past years") request, read directly from
    # its installed source in this session -- not guessed.
    return f"DAT_ASCII_{pair.upper()}_M1_{year}.zip"


def _sha256_of_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _default_fetch_one(pair: str, year: int, out_dir: Path) -> Path:
    """The REAL fetch, wrapping histdata's own download_hist_data(). Kept
    as a separate, injectable function (see `fetch_one` param of
    `run_downloads`) so the retry/backoff/manifest logic below can be
    unit-tested without any real network access."""
    from histdata import download_hist_data
    from histdata.api import Platform, TimeFrame

    download_hist_data(
        year=str(year), month=None, pair=pair.lower(),
        platform=Platform.GENERIC_ASCII, time_frame=TimeFrame.ONE_MINUTE,
        output_directory=str(out_dir), verbose=False,
    )
    expected = out_dir / _expected_output_filename(pair, year)
    if not expected.exists():
        raise FileNotFoundError(f"histdata reported success but {expected} was not created")
    return expected


def load_manifest(manifest_path: Path) -> dict:
    if manifest_path.exists():
        return json.loads(manifest_path.read_text())
    return {"jobs": {}}


def save_manifest(manifest_path: Path, manifest: dict) -> None:
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True))


def run_downloads(
    pairs: list[str],
    years: list[int],
    out_dir: Path,
    manifest_path: Path,
    max_retries: int = 4,
    backoff_base_seconds: float = 2.0,
    rate_limit_seconds: float = 5.0,
    fetch_one: Callable[[str, int, Path], Path] = _default_fetch_one,
    sleep_fn: Callable[[float], None] = time.sleep,
) -> list[JobResult]:
    """Resumable: a job already recorded SUCCESS in the manifest (with a
    matching expected output filename that still exists on disk) is
    skipped, so re-running this script after an interruption continues
    where it left off rather than re-downloading everything. Every job's
    outcome is written to the manifest IMMEDIATELY (not batched at the
    end), so a crash mid-run loses at most the one in-flight job's
    progress."""
    out_dir.mkdir(parents=True, exist_ok=True)
    manifest = load_manifest(manifest_path)
    results: list[JobResult] = []

    for pair in pairs:
        for year in years:
            key = f"{pair.lower()}_{year}"
            existing = manifest["jobs"].get(key)
            expected_path = out_dir / _expected_output_filename(pair, year)
            if existing and existing.get("status") == "SUCCESS" and expected_path.exists():
                results.append(JobResult(
                    pair=pair, year=year, status="SKIPPED_ALREADY_DONE",
                    output_path=str(expected_path), sha256=existing.get("sha256"),
                    attempts=0, error=None, finished_at_utc=datetime.now(timezone.utc).isoformat(),
                ))
                continue

            attempts = 0
            last_error: str | None = None
            output_path: Path | None = None
            while attempts < max_retries:
                attempts += 1
                try:
                    output_path = fetch_one(pair, year, out_dir)
                    last_error = None
                    break
                except Exception as exc:  # noqa: BLE001 -- a job failure must never abort the whole run
                    last_error = f"{type(exc).__name__}: {exc}"
                    if attempts < max_retries:
                        sleep_fn(backoff_base_seconds * (2 ** (attempts - 1)))

            if output_path is not None and last_error is None:
                sha = _sha256_of_file(output_path)
                result = JobResult(
                    pair=pair, year=year, status="SUCCESS", output_path=str(output_path),
                    sha256=sha, attempts=attempts, error=None,
                    finished_at_utc=datetime.now(timezone.utc).isoformat(),
                )
            else:
                result = JobResult(
                    pair=pair, year=year, status="FAILED", output_path=None, sha256=None,
                    attempts=attempts, error=last_error,
                    finished_at_utc=datetime.now(timezone.utc).isoformat(),
                )

            manifest["jobs"][key] = asdict(result)
            save_manifest(manifest_path, manifest)
            results.append(result)
            sleep_fn(rate_limit_seconds)

    return results


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--pairs", default="eurusd,gbpusd")
    ap.add_argument("--start-year", type=int, default=2015)
    ap.add_argument("--end-year", type=int, default=2025)
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--manifest", required=True)
    ap.add_argument("--max-retries", type=int, default=4)
    ap.add_argument("--backoff-base-seconds", type=float, default=2.0)
    ap.add_argument("--rate-limit-seconds", type=float, default=5.0)
    args = ap.parse_args()

    pairs = [p.strip() for p in args.pairs.split(",") if p.strip()]
    years = list(range(args.start_year, args.end_year + 1))

    results = run_downloads(
        pairs=pairs, years=years, out_dir=Path(args.out_dir), manifest_path=Path(args.manifest),
        max_retries=args.max_retries, backoff_base_seconds=args.backoff_base_seconds,
        rate_limit_seconds=args.rate_limit_seconds,
    )
    ok = sum(1 for r in results if r.status in ("SUCCESS", "SKIPPED_ALREADY_DONE"))
    failed = [r for r in results if r.status == "FAILED"]
    print(f"\n{ok}/{len(results)} jobs OK, {len(failed)} failed.")
    for r in failed:
        print(f"  FAILED {r.pair} {r.year}: {r.error}")
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
