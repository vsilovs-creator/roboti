# Long-history (2015-2025) fixed-strategy comparison -- outcome report

**Final status (same day, continued session): Part A COMPLETE --
`šajā fiksēto stratēģiju atlasē kandidāts nav atrasts` (no candidate was
found in this fixed-strategy selection).** `DATA_DOWNLOAD_NOT_RUN` no
longer applies: this session's own network environment never became
reachable to HistData/Dukascopy/etc. (see the "Original finding" section
below, kept intact and unedited as the historical record), but the
account owner supplied the real 2015-2025 EURUSD+GBPUSD M1 data directly
(chat upload, then a direct push of the full 22-file set to `data/raw/`
on `main`), bypassing this session's network restriction entirely via a
channel this session COULD already reach (git). All 24 of section 5.A's
continuous-account runs (2015-2022, S1-S8 x C1-C3) were executed and
are EVERY ONE net negative -- see "Part A results" below for the full
table, the exact numbers, and a structural finding about WHY every
variant converges to a similar loss (a fixed 9200 USD floor + a
deliberately conservative pre-trade gate, not a simulator bug). Section
5.B (192 fixed-year-start diagnostic runs) was NOT run -- it needs a new
simulator capability (isolated per-year indicator warm-up) that does not
exist yet and was not rushed into place; see that section for exactly
what is needed next. No candidate reached section 7's holdout; 2023-2025
data remains unopened for any P/L purpose.

---

## Original finding (kept for the record; superseded above for data availability, not for the source-evaluation evidence itself)

No S1-S8 long-history P/L number existed anywhere in this document or
that round's commit, for any variant, scenario, or period, AT THE TIME
this section was written. It documents exactly what was tried, what the
evidence showed, what code was built and tested instead of real data,
and the one precise command for someone with real network access to
finish the job the way this session's OWN network could not. See
`docs/LONG_HISTORY_EXPERIMENT_PLAN.md` for the full pre-registered plan
this round's work follows.

## What this round actually did

1. Read `docs/FULL_REPORT.md`, `docs/AUDIT_2026-09-18.md`,
   `docs/EXPERIMENT_PLAN_2026-09-18.md`, and
   `docs/CODEX_RESPONSE_ROUND2_2026-09-18.md`; confirmed the starting
   commit (`e95743b`).
2. Attempted to reach every free/public M1 EURUSD/GBPUSD historical-data
   source this session could identify -- 12 distinct hosts/repos, listed
   with exact results in the experiment plan's section 2.1.
3. Confirmed, with a REAL invocation (not a guess), that the actual
   mechanics needed to download from HistData.com are simple and
   CAPTCHA-free (a token-based form POST) -- the published `histdata`
   PyPI package does exactly this, correctly, and its ONLY failure in
   this session is a network-level block from this session's own proxy.
4. Built and unit-tested (against synthetic fixtures, never against
   unverified real data) the two pieces of infrastructure a real
   download would need next: a HistData-format M1 parser with a
   data-quality report, and a resumable, retrying downloader with a
   JSON manifest.
5. Did NOT fetch, look at, or compute anything from 2023-2025 data (none
   was fetched at all) -- the holdout-blindness rule in section 3/7 of
   the plan is trivially satisfied since there is no data to have
   peeked at.
6. Did NOT change any S1-S8 strategy parameter, risk floor, cap, or
   sizing rule. Did NOT touch any MQL4 file -- MQL4 remains exactly
   `NOT_RUN`. Did NOT run anything against a live or demo account.

## Evidence: every source tried, with the exact command and result

All of the following were run directly in this session (not asserted
from memory). Full commentary is in the experiment plan's section 2.1;
this section is the raw evidence backing that table.

```
$ curl -sS -o /dev/null -w "HTTP %{http_code}\n" --max-time 15 "https://www.histdata.com/download-free-forex-historical-data/"
curl: (56) CONNECT tunnel failed, response 403
HTTP 000

$ curl -sS http://127.0.0.1:42045/__agentproxy/status
...
"recentRelayFailures": [{"kind": "connect_rejected",
  "detail": "gateway answered 403 to CONNECT (policy denial or upstream failure)",
  "host": "www.histdata.com:443"}]
```

The SAME `connect_rejected` / 403 pattern, individually confirmed, for:
`www.dukascopy.com`, `datafeed.dukascopy.com`, `www.kaggle.com`,
`drive.google.com`, `docs.google.com`, `candledata.fxcorporate.com`,
`zenodo.org`, `figshare.com`, `archive.org`, `data.gov`, `osf.io`,
`truefx.com`, `www.forexite.com`, `forextester.com`, `stooq.com`,
`static.stooq.com`, `api.exchangerate.host`, and (as a sanity check that
this is a general policy, not something specific to finance sites)
`example.com`, `en.wikipedia.org`, `www.google.com`. Every one of these
returned the identical `connect_rejected`/403 signature -- this is this
session's own network egress allowlist (effectively: package registries,
`api.anthropic.com`, and GitHub's code-hosting domains only), not a
per-site failure.

The one thing that DID work -- proving the actual HistData request
mechanics are sound and the block is purely network-level, not a bug or
a CAPTCHA:

```
$ pip install histdata
Successfully installed histdata-1.1

$ python3 -c "
from histdata import download_hist_data as dl
from histdata.api import Platform as P, TimeFrame as TF
dl(year='2015', pair='eurusd', platform=P.GENERIC_ASCII, time_frame=TF.ONE_MINUTE, output_directory='/tmp/histdata_test')
"
https://www.histdata.com/download-free-forex-historical-data/?/ascii/1-minute-bar-quotes/eurusd/2015
FAILED: ProxyError HTTPSConnectionPool(host='www.histdata.com', port=443): Max retries
exceeded with url: /download-free-forex-historical-data/?/ascii/1-minute-bar-quotes/eurusd/2015
(Caused by ProxyError('Unable to connect to proxy', OSError('Tunnel connection failed: 403 Forbidden')))
```

The exact same `ProxyError`/403 was reproduced by
`python/scripts/download_long_history.py` itself (this round's own
downloader, described below), confirming the wiring end-to-end:

```
$ python scripts/download_long_history.py --pairs eurusd --start-year 2015 --end-year 2015 \
    --out-dir /tmp/long_history_smoketest --manifest /tmp/long_history_smoketest/manifest.json \
    --max-retries 1 --rate-limit-seconds 0 --backoff-base-seconds 0
0/1 jobs OK, 1 failed.
  FAILED eurusd 2015: ProxyError: ... Tunnel connection failed: 403 Forbidden ...
```

GitHub itself (git clone / `raw.githubusercontent.com`) is the ONE class
of host reachable from this session. That is how the licensing findings
in the plan's section 2.1 rows 7-9 were obtained (`add_repo` + shallow
`git clone` of each candidate mirror, then read directly) -- and also
why none of them could be adopted as a reported result: reachability and
license/coverage are two separate questions, and only GitHub cleared the
first for any real M1 multi-year data.

## What was built and tested instead

- **`python/ftmo_sim/histdata_adapter.py`** -- parses HistData's
  documented M1 export formats into this project's existing
  `RichCandle`/UTC shape, plus a `DataQualityReport` (duplicate/
  non-monotonic/OHLC-sanity counts, weekend-row count, first/last
  timestamp, source and normalized SHA256). Supports BOTH HistData
  export "platforms" (auto-detected by `parse_histdata_m1()` from the
  file/ZIP-member name, falling back to content sniffing): "Generic
  ASCII" (`YYYYMMDD HHMMSS;O;H;L;C;V`) and "MetaTrader"
  (`YYYY.MM.DD,HH:MM,O,H,L,C,V`) -- both on the SAME fixed
  EST-without-DST offset, confirmed from the `histdata` package's own
  README. The MetaTrader-platform support was added after the user
  supplied a REAL HistData download in this session
  (`HISTDATA_COM_MT_GBPUSD_M12019.zip`) that turned out to be that
  platform, not the one this module originally supported -- run through
  the adapter directly (no manual unzip needed): 372,396 raw M1 rows,
  60 duplicate timestamps counted and deduplicated, 0 non-monotonic
  rows, 0 OHLC-sanity violations, full 2019-01-01 to 2019-12-31 UTC
  coverage. This is the only real (non-synthetic) file the adapter has
  been run against; it was NOT used to compute any strategy result,
  only to confirm the parser/quality-report logic on real data. Accepts
  HistData's raw `.zip` download directly (unzips the one CSV member
  in-memory) as well as an already-extracted `.csv`. The 12 automated
  tests in `python/tests/test_histdata_adapter.py` are all synthetic
  fixtures (never the real uploaded file itself, which is not committed
  to the repo per this plan's own "no large raw files in git" rule);
  the real-file numbers above came from a one-off manual run in this
  session, not a checked-in test. Deliberately NOT tested against any
  of the license-unverified GitHub mirrors found in section 2.1, to
  avoid even incidentally treating that data as trustworthy.
- **`python/scripts/download_long_history.py`** -- wraps the real
  `histdata` package with retry/exponential-backoff, a resumable JSON
  manifest (a job already recorded `SUCCESS` with its output file still
  on disk is skipped on re-run), and a rate-limit pause between distinct
  (pair, year) jobs. Tested with 4 unit tests
  (`python/tests/test_download_long_history.py`) against an injected
  fake fetch function -- no real network involved in the tests
  themselves -- covering: success+checksum recorded, transient-failure
  retry-then-succeed, retries-exhausted-records-FAILED-and-continues,
  and resume-skips-an-already-done-job.
- **`docs/LONG_HISTORY_EXPERIMENT_PLAN.md`** -- the full pre-registered
  plan (data period, source evaluation, selection/holdout split, risk/
  cost model restated unchanged, the 216 planned selection-period runs,
  the pre-defined qualification criteria, the holdout structure, and
  reporting requirements), hashed per this project's established
  convention.
- **`python/requirements-long-history.txt`** -- the one extra dependency
  (`histdata==1.1`) needed for the downloader, kept separate from the
  core project's zero-dependency `requirements.txt` so nobody has to
  install a scraping library just to run the existing simulators/tests.

Full test suite: **122 passed** (up from 106), the 16 new tests above
plus everything from every prior round, unaffected.

## The one exact command for someone with real network access

```
pip install -r python/requirements-long-history.txt
python3 python/scripts/download_long_history.py \
    --pairs eurusd,gbpusd --start-year 2015 --end-year 2025 \
    --out-dir data/raw/long_history --manifest data/raw/long_history/manifest.json
```

This downloads 22 ZIP files (2 pairs x 11 years) directly from
histdata.com into `data/raw/long_history/`, with a manifest recording
each file's SHA256 and status, resumable if interrupted. After that:
run each ZIP directly through
`ftmo_sim.histdata_adapter.parse_histdata_generic_ascii_m1()` (it
unzips in-memory and reads HistData's one CSV member itself -- no
manual unzip step needed; it also accepts an already-extracted `.csv`
if one exists) to get UTC `RichCandle` rows plus a quality report,
confirm both instruments' 2015-2025 coverage overlaps as the plan's
section 2 requires, and only THEN proceed to section 5's 216
selection-period runs. **Large raw/ZIP
files must not be committed to this GitHub repository** (per the task's
own instruction) -- keep them local or in whatever storage the next
session has, and commit only the code, the plan, the manifests, and the
eventual compact per-run results.

## What this means for the 2000 USD/month target (as of the original finding above)

Nothing -- no data, no runs, no evidence either way, AT THAT POINT. See
below for what changed once real data arrived.

---

## Real data received and verified (same day, continued session)

The account owner supplied the real HistData "MetaTrader"-platform M1
download directly: first one file via chat upload
(`HISTDATA_COM_MT_GBPUSD_M12019.zip`, which is what drove adding
MT-platform support to `histdata_adapter.py` -- see that commit), then
the FULL 2015-2025 set (22 files: EURUSD+GBPUSD x 11 years, `.csv` +
HistData's own `.txt` status report per file, ~437MB) pushed directly to
`data/raw/` on `main`. Not committed by this session -- the account
owner's own git push, merged into this round's branch.

**Independent quality audit** (`ftmo_sim.histdata_adapter.parse_histdata_m1`
run against all 22 files, not just spot-checked):

| Pair | Years | Total rows (deduped) | Duplicate timestamps | Non-monotonic | OHLC violations |
|---|---|---|---|---|---|
| EURUSD | 2015-2025 | 4,043,104 | 360 (all deduped, first copy kept) | 0 | 0 |
| GBPUSD | 2015-2025 | 4,041,766 | 420 (all deduped, first copy kept) | 0 | 0 |

All 22 (pair, year) combinations present, no missing files. **0 OHLC
sanity violations and 0 non-monotonic timestamps across 8,084,870 total
rows** -- the strongest integrity signal this project has ever had for
any data source, including its own original 2026 sample. 2023 shows a
visibly lower row count for both pairs (~322,500 vs ~372,000 for other
years) -- investigated directly: every gap larger than 50 hours in
2023's EURUSD file is an ordinary weekend (Friday close to Sunday open),
not a missing block; 2023 simply has more numerous/larger normal
mid-week gaps than 2022/2024 (measured: ~169,000 cumulative gap-minutes
in 2023 vs ~150,000/~155,000 in 2022/2024) -- a genuine, if modest, data
density difference in HistData's own feed for that year, not a parsing
bug or a missing chunk. Documented here rather than silently accepted or
silently "fixed."

**A real bug found while building the runner, not in the data:**
`scripts/run_experiment_2026-09-18.py`'s `write_signals_csv()` assumed
every skipped signal exposes `signal_close_time_utc` -- true for S2-S8's
`EmaCrossSignal` but not S1's own `SignalEvent`
(`retest_close_time_utc`). Never crashed on the 2026 sample because S1
had zero rejected signals there; crashed immediately on the real 8-year
data, where it does. Fixed with a shape-agnostic accessor, 2 new
regression tests added, and the ORIGINAL 24-run 2026-sample experiment
re-run afterward to confirm every number is byte-identical (only the
`git_sha` metadata field differed) -- a pure no-op for that report, a
real fix for this one.

## Part A results (continuous account, 2015-2022, 24 runs) -- COMPLETE

All 24 runs (`scripts/run_long_history_experiment.py`, ~16 minutes
total) finished successfully, no crash, no partial run. Full
machine-readable output in
`reports/long_history_selection_2015_2022/<variant>_<scenario>/`.

| Variant | C1 net USD | C1 trades | C1 PF | C2 net USD | C3 net USD | Lowest equity (C1) | Last month with any trade (C1) |
|---|---|---|---|---|---|---|---|
| S1 | -798.97 | 111 | 0.59 | -777.70 | -791.05 | 9201.03 | 2015-09 |
| S2 | -794.08 | 105 | 0.62 | -793.81 | -785.89 | 9205.92 | 2016-06 |
| S3 | -785.05 | 358 | 0.88 | -785.49 | -784.42 | 9209.22 | 2016-07 |
| S4 | -779.71 | 102 | 0.60 | -784.30 | -793.45 | 9214.66 | 2016-01 |
| S5 | -781.88 | 110 | 0.62 | -795.08 | -784.77 | 9218.12 | 2015-07 |
| S6 | -784.63 | 1298 | 0.98 | -794.87 | -794.90 | 9212.46 | 2019-10 |
| S7 | -791.60 | 405 | 0.88 | -787.84 | -792.98 | 9208.40 | 2022-02 |
| S8 | -785.42 | 1356 | 0.93 | -782.96 | -795.35 | 9214.58 | 2017-02 |

**Every one of the 24 runs is net negative, in every scenario.**
`working_floor_breach_count` and `independently_recomputed_floor_breach_days`
are BOTH 0 for all 24 runs -- the static total working floor (9200) was
never actually breached by any variant, in the strict sense of the
account being stopped out.

### A structural finding that changes what this result actually means

Look at the "lowest equity" column: **every single variant's lowest
observed equity sits within about 20 USD of the 9200 static total
working floor** (9201.03 to 9218.12 -- a spread of only 17 USD across
eight structurally different strategies). And look at the "last month
with any trade" column: most variants stop trading ENTIRELY within 1-2
years of the 8-year window and never resume -- S1's last trade is
2015-09 (month 9 of 96), S5's is 2015-07 (month 7), S4's is 2016-01
(month 13); even the two most active variants (S6, S8, both with
1000+ trades) go silent by 2019-10 and 2017-02 respectively, leaving
years of the remaining sample with zero activity. Directly confirmed
from every run's own `rejected_signal_counts_by_reason`: S1 rejected
1,312 signals, S7 rejected 20,798, purely for
`PRE_TRADE_PROJECTED_EQUITY_BREACH` -- the pre-trade worst-case-equity
gate (deliberately MORE conservative than the actual floor, by design,
per `docs/FULL_REPORT.md` section 4) keeps blocking every new entry
once the account sits this close to the floor, even though the account
never actually gets stopped out.

**What this means:** with a SINGLE continuous 10,000 USD account and
the project's confirmed 9200 static floor (only an 800 USD / 8% buffer
from the starting balance), EVERY ONE of these eight strategies drifts
down to within ~20 USD of that floor early in the 8-year window and
then gets effectively frozen by the pre-trade gate for most of the
remaining years -- this is the SAME failure mode
`docs/STRATEGY_RESEARCH_2026-09-18.md` already documented for S7 alone
on the ~2-month 2026 sample ("S7's headline loss is effectively a
ONE-MONTH result"), now observed for ALL EIGHT variants at 8-year
scale. The practical consequence: **these 24 numbers are not a clean
measurement of "how good is this strategy over 8 years" -- they are
dominated by how fast each account statistically walked itself down
near a tight, fixed floor, after which the test effectively stopped
measuring anything.** A strategy that might have a genuinely different
long-run edge than another could still land at a similar final number
here purely because both hit the same floor-and-freeze wall, just at
different speeds. This is not a simulator bug (the floor logic,
pre-trade gate, and account accounting are all the same
already-audited, regression-tested code as every prior round -- F1-F5,
R1-R2 apply unchanged) -- it is a genuine property of testing eight
persistently-negative-expectancy strategies against a tight fixed floor
over a long continuous window, and it is reported here rather than
smoothed over.

**No strategy parameter, risk floor, or cap was loosened to avoid this
outcome or to produce a better-looking number** -- per the task's
explicit instruction, the existing floors/caps are used exactly as
confirmed, not adjusted because this round's result is unfavorable.

### Verdict for Part A, per section 6's qualification criteria

Criterion 1 ("nepārtrauktajā... gan C1, gan C2 pabeidz periodu bez
kopējā darba stop un ar pozitīvu gala neto equity izmaiņu") requires a
POSITIVE net equity change in both C1 and C2. **Every one of the eight
variants fails this criterion in every scenario** -- there is no
variant left that criteria 2-4 could still qualify, since qualification
requires ALL FOUR criteria together. Per the plan's own required
wording: **šajā fiksēto stratēģiju atlasē kandidāts nav atrasts** (no
candidate was found in this fixed-strategy selection). No variant is
picked as a "least-bad" placeholder. 2023-2025 data has NOT been opened
for any strategy P/L purpose (per section 3's holdout-blindness rule)
and remains untouched for that purpose.

### Part B (192 fixed-year-start runs) -- NOT RUN this round, and why

Section 5.B requires each year's own run to warm up its indicators from
the PRECEDING year's data WITHOUT trading during warm-up
("warm-up netirgo"). The existing simulators
(`simulator.py`/`simulator_ema_cross.py`/`simulator_m30_signal.py`) have
NO built-in mechanism to feed a strategy engine prior-year bars for pure
indicator priming while suppressing entries during that priming window
-- every simulator's per-tick loop treats every bar in its input as a
potential trading instant from the very first timestamp. Building this
properly (a real `warmup_m1_by_symbol` parameter, verified with its own
regression test showing a warm-up bar produces indicator state but never
a trade) is a genuine new capability, not a config flag -- rushing an
approximate version in the same sitting that already produced Part A's
result risked exactly the kind of quietly-wrong shortcut this project's
audit history (F1-F5, R1-R2) exists to catch. It is the clear, well-
defined next task, not silently skipped: **DATA is ready (same verified
2015-2025 files), the account-level logic is unchanged from Part A's
already-run code, and only the warm-up-isolation feature is missing.**
Given Part A already establishes "no candidate found" on its own
(section 6 requires criterion 1 from Part A to hold, which it does not,
for any variant), Part B's results could not change that verdict, but
they remain useful diagnostic information (year-by-year sensitivity, per
section 8's own reporting requirements) worth building properly in a
follow-up round.

## What this means for the 2000 USD/month target (real data, final)

**Still unconfirmed -- and now more strongly contradicted than before.**
None of the eight strategies reaches a positive net result over the
FULL real 2015-2022 continuous window, let alone +2000 USD in any full
calendar month; most variants stop generating any trades at all within
1-3 years of an 8-year window (see the structural finding above), so
the great majority of the sample's calendar months show zero activity,
not a target-missing-by-a-little result. This is real 8-year evidence,
not the ~2-month 2026 sample's thinner base -- and it points the same
direction that sample already did.

## Handoff note (for Codex, or whoever reviews this round next)

- **Commit:** this round's commits on `github.com/vsilovs-creator/roboti`,
  branch `long-history-data-infra` (see `git log`), starting from
  `e95743b`, merged with the account owner's own direct push of the real
  2015-2025 data to `main`.
- **What changed (code/infra):** `python/ftmo_sim/histdata_adapter.py`
  (new -- HistData Generic-ASCII AND MetaTrader platform parsing,
  auto-detected, ZIP-transparent), `python/scripts/download_long_history.py`
  (new, unused in the end since data arrived via a different channel, kept
  for future reproducibility), `python/scripts/run_long_history_experiment.py`
  (new -- Part A's actual runner), `python/requirements-long-history.txt`
  (new), 4 new/updated test files (23 new tests total: 12 adapter, 4
  downloader, 2 signal-CSV-shape, 2 for the write_signals_csv fix's own
  regression coverage, plus the fix itself in
  `scripts/run_experiment_2026-09-18.py`). No existing SIMULATOR,
  METRICS, or ORDER-EXECUTION file was touched -- every F1-F5/R1-R2 fix
  from prior rounds applies completely unchanged to this round's runs.
- **What changed (data):** `data/raw/DAT_MT_{EURUSD,GBPUSD}_M1_{2015..2025}.csv`
  (+ HistData's own `.txt` status reports), 22 files, ~437MB, pushed
  directly by the account owner to `main` (not by this session).
- **What changed (results):** `reports/long_history_selection_2015_2022/`
  -- all 24 of section 5.A's runs, full machine-readable output per run.
- **Actually executed this round:** the source-reachability tests (all
  real, exact commands/output shown), 23 new unit tests (all real, all
  passing), the full 124-test suite (real, all passing), the independent
  data-quality audit of all 22 real files (real, 8,084,870 rows, 0 OHLC
  violations, 0 non-monotonic), **all 24 of section 5.A's continuous-
  account runs (real, ~16 minutes, all 24 net negative)**.
- **NOT executed this round:** section 5.B's 192 fixed-year-start runs
  (needs new warm-up-isolation simulator support, not built -- see "Part
  B" above for exactly what), any section 7 holdout run (correctly --
  5.A already disqualifies every variant, so no candidate exists to open
  2023-2025 for), any candidate selection (none qualified), any MQL4
  compile/run.
- **Known limitation carried forward:** even with real HistData/
  Dukascopy-shaped data now in hand, the same Bid-only-M1/no-true-tick-
  path caveat this project has stated since its first audit round still
  applies -- a longer sample changes the STATISTICAL power of the
  comparison, not the INTRABAR-execution-fidelity ceiling.
- **New limitation this round surfaced (the floor-freeze structural
  finding):** a single long continuous account against a tight fixed
  floor structurally caps how much a multi-year test can actually
  distinguish between negative-expectancy strategies -- worth
  accounting for in any future long-history experiment design (e.g. the
  still-unbuilt Part B, which resets per year and would not share this
  exact failure mode).
- **2000 USD/month target:** still unconfirmed, now more strongly
  contradicted by real 8-year evidence (see above) than by the original
  ~2-month sample alone.
