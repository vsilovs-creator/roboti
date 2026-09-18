# Long-history (2015-2025) fixed-strategy comparison -- pre-registered plan

**Status update (same day, continued session): data received, section
5.A running.** This plan's hash (below) was fixed BEFORE the account
owner supplied the real 2015-2025 M1 data (delivered directly via git
push to `data/raw/` on `main`, since this session's own network could
not reach any of the sources evaluated in section 2.1) and before any
run in section 5 or 7 started -- the pre-registration discipline this
document exists for was honored in the actual order it required, not
retrofitted after the fact. See `docs/LONG_HISTORY_REPORT.md`'s "Real
data received and verified" / "Part A results" sections for the
independent quality audit and the actual run status. No S1-S8 parameter,
threshold, or risk limit has been changed anywhere in this round.

Original status note (kept for the record): **PLAN WRITTEN,
DATA_DOWNLOAD_NOT_RUN.** No properly licensed, sufficiently-covering
2015-2025 M1 EURUSD/GBPUSD data source could be reached from THIS
SESSION'S OWN network environment (section 2.1's full evidence) -- this
plan was committed as-is at that time so whoever next had real network
or data access could execute it exactly as written, without re-deciding
anything under the influence of having already seen a result. That is
exactly what then happened, later the same session.

Starting commit for this round: `e95743b` (the commit that closed the
Codex R1/R2 follow-up round). No strategy parameter, risk floor, cap, or
sizing rule from that commit is changed anywhere in this document or in
the code committed alongside it.

## 1. Context and boundaries (unchanged from the project's own prior rounds)

- FTMO 2-Step Swing, 10,000 USD simulated initial capital, EURUSD and
  GBPUSD on ONE shared account (never summed from two independent
  single-pair backtests -- same rule as every prior round).
- The existing ~2-month 2026 sample (`data/raw/EURUSD1.csv` /
  `GBPUSD1.csv`) remains EXPLORATORY and is NOT a holdout for this
  round -- it is kept only as a regression/comparison reference (does a
  candidate's long-history behavior look qualitatively consistent with
  what it did on the short sample?), never as evidence for or against
  a candidate in its own right here.
- The prior 24-run S1-S8 x C1-C3 result on that 2026 sample was all
  negative. That does NOT mean every variant will always lose, and is
  NOT a reason to pick the smallest prior loser as "the" candidate here
  -- this round's own qualification criteria (section 6) are the only
  basis for a candidate decision.
- No user-side historical file search was requested; per the task's own
  instruction, this session was to obtain the data itself from an
  available public source. Section 2 documents exactly what was tried
  and why none qualified.
- The +2000 USD/full-month target is unchanged, not guaranteed, and is
  never approached by raising risk.
- No ninth strategy, no parameter optimization, no active-recovery/grid/
  martingale logic is introduced this round. S5 (close-and-reverse)
  remains one of the eight compared variants, unchanged.
- Nothing in this round runs against a live or demo account. MQL4
  remains exactly `NOT_RUN` -- untouched by this round's work, which is
  entirely Python data-infrastructure and (once data exists) Python
  simulation.

## 2. Data period and source

Target: **2015-01-01 to 2025-12-31**, both instruments, M1, plus
2014-12 for indicator warm-up only (never traded).

### 2.1 Source evaluation (tried in this session, in the order attempted)

Every row below was independently verified in THIS session (a direct
`curl`/`WebFetch` connectivity test, or an actual `pip install histdata`
+ real invocation) -- not assumed from training knowledge. See
`docs/LONG_HISTORY_REPORT.md` for the exact commands and raw output.

| # | Source | Format/coverage | Access result in this session | License/terms |
|---|---|---|---|---|
| 1 | **histdata.com** (primary, per this task) | Generic ASCII M1, 2000-present, EURUSD+GBPUSD | **BLOCKED.** `curl`/`WebFetch` to `www.histdata.com` return HTTP 403 from this session's own network egress proxy (`connect_rejected`, "organization policy"), not from HistData. The real, published `histdata` PyPI package (v1.1) was installed successfully (PyPI is reachable) and its actual `download_hist_data()` call was invoked -- it performs a plain two-step GET-token/POST-form request (no CAPTCHA in this flow, confirmed by reading its installed source directly) and fails with the SAME proxy-level 403. | HistData's own stated terms could not be read directly (site blocked) to confirm redistribution rights; only DIRECT download from their own site was ever attempted here, never a redistribution. |
| 2 | **Dukascopy** (alternative, per this task) | Historical Data Feed, tick/M1, AWS Requester-Pays option documented | **BLOCKED.** `www.dukascopy.com` and `datafeed.dukascopy.com`: HTTP 403, same proxy policy denial. AWS Requester-Pays was never activated (would need explicit user billing authorization, per the task's own instruction, and is moot -- the endpoint itself is unreachable). | Not evaluated (unreachable). |
| 3 | Kaggle dataset ("EURUSD 1-Minute Forex Candlestick Data 2015-2025") | Unknown (page unreachable) | **BLOCKED.** `www.kaggle.com`: HTTP 403. | Not evaluated (unreachable; Kaggle datasets also typically require an API key/auth this session does not have). |
| 4 | Google Drive (philipperemy/FX-1-Minute-Data's pre-packaged 3GB "All instruments - 1Minute - 2000/2024" mirror of HistData) | Unknown (unreachable) | **BLOCKED.** `drive.google.com`/`docs.google.com`: HTTP 403. | Not evaluated (unreachable). |
| 5 | **FXCM `candledata.fxcorporate.com`** -- the ONE source found with an official, broker-published, explicitly licensed ("for personal use, abides by our EULA"), documented, non-authenticated URL pattern (`https://candledata.fxcorporate.com/m1/{PAIR}/{year}/{week}.csv.gz`, UTC timestamps, no DST ambiguity) | M1/H1/D1, 2017-2020 only, EURUSD+GBPUSD included | **BLOCKED.** `candledata.fxcorporate.com`: HTTP 403, same proxy policy. This was the MOST attractive source found (clear license, UTC timestamps, no scraping/token mechanics needed) and it is still unreachable from this session. | EULA, personal use -- see `github.com/fxcm/MarketData`'s own README (read directly in this session). Would only cover 2017-2020 of the requested 2015-2025 span even if reachable. |
| 6 | Zenodo / Figshare / archive.org / OSF / data.gov | N/A | **BLOCKED**, all HTTP 403, same proxy policy -- checked as a general "is ANY non-code-hosting external site reachable" probe, not because a specific FX dataset was found there. | N/A |
| 7 | `github.com/asiertrades/hisdata-eurusd` -- a public GitHub repo with HistData-format M1 CSVs committed directly into git (`DAT_ASCII_EURUSD_M1_<year>.csv`, 2000-2025) | EURUSD ONLY (no GBPUSD sibling found), matches HistData's exact ASCII format | **REACHABLE** (git clone via this session's GitHub read proxy; `raw.githubusercontent.com`/git-over-HTTPS to public GitHub repos is NOT blocked by this session's egress policy, unlike every site above). | **License field literally reads "[Especifica según corresponda]"** ("[Specify as applicable]") -- i.e. UNSPECIFIED. An individual's personal repo (mixed with unrelated trading-strategy scripts), re-publishing what is almost certainly HistData's own data under HistData's own file-naming convention, with no stated permission to redistribute and no independent verification of data integrity. **NOT adopted for any reported result in this round** -- see decision below. |
| 8 | `github.com/FX-Data/FX-Data-{EURUSD,GBPUSD}-DS` -- an automated-scraper org, per-year GIT BRANCHES (not files in `main`), generated by a "Fetch" GitHub Action | GBPUSD branches only go up to 2018 (no 2019-2025); EURUSD's branch list not fully enumerated once the licensing problem was already clear | **REACHABLE** (same git-clone path as #7). | **No LICENSE file at all** (default copyright, i.e. NOT freely licensed) -- an unattributed automated re-publication of HistData's data as GitHub branches. Also incomplete coverage. **NOT adopted.** |
| 9 | `github.com/ejtraderLabs/historical-data` | M15/M30/H1/H4/D1 (**no M1 at all**), EURUSD 2012-2022, GBPUSD included, Apache-2.0 licensed | **REACHABLE.** Properly licensed (Apache-2.0) -- the ONE candidate with unambiguous licensing. | **Rejected on coverage, not license:** no M1 timeframe (the project's whole simulator architecture -- intrabar SL/TP resolution via bar high/low, F2's event-order fix, etc. -- assumes M1 as the finest resolution; M15 would be a materially coarser, less defensible approximation of intrabar risk than even this project's existing "M1 has no true tick path" caveat already accepts), and does not reach 2025. |

### 2.2 Decision

**No source found in this session is both (a) technically reachable from
this sandboxed environment's network AND (b) clearly, verifiably
licensed for redistribution/use AND (c) covering the full requested
2015-2025 span for both EURUSD and GBPUSD at M1 resolution.** Per this
project's own established rule (never present an unverified assumption
as validated -- e.g. `docs/AUDIT_2026-09-18.md`'s entire history of
flagging exactly this kind of gap rather than silently working around
it), this session does NOT adopt any of the reachable-but-unlicensed
GitHub mirrors (#7, #8) as the basis for a reported S1-S8 result, and
does NOT substitute the properly-licensed-but-wrong-resolution mirror
(#9). **Status: `DATA_DOWNLOAD_NOT_RUN`** for the actual 2015-2025
dataset. `docs/LONG_HISTORY_REPORT.md` gives the exact, verified-mechanically-
correct command (`pip install histdata` + a short script, already built
and committed as `python/scripts/download_long_history.py`) for someone
with real network access to run instead.

The `histdata_adapter.py` module (parsing HistData's own "Generic
ASCII" M1 format, EST-without-DST per HistData's own documented
convention) and its data-quality-report logic ARE built and tested this
round (`python/ftmo_sim/histdata_adapter.py`,
`python/tests/test_histdata_adapter.py`) against hand-written synthetic
fixtures in that exact format -- never against a real downloaded file,
since none was obtainable, and never presented as a strategy result.

### 2.3 Format/timezone/license specification (for whoever runs the download)

- **Format:** two HistData export "platforms" are both supported by
  `histdata_adapter.py`, auto-detected (`parse_histdata_m1()`) from the
  file/ZIP-member name or, failing that, the first data line's
  separator:
  - **Generic ASCII** (`DAT_ASCII_*`), semicolon-separated:
    `YYYYMMDD HHMMSS;OPEN;HIGH;LOW;CLOSE;VOLUME`.
  - **MetaTrader** (`DAT_MT_*`), comma-separated:
    `YYYY.MM.DD,HH:MM,OPEN,HIGH,LOW,CLOSE,VOLUME` -- confirmed directly
    from a real user-supplied download in this session
    (`HISTDATA_COM_MT_GBPUSD_M12019.zip`, 372,396 raw M1 rows, 60
    duplicate timestamps counted and deduplicated, 0 non-monotonic, 0
    OHLC-sanity violations -- the adapter's own quality report on that
    real file, not a synthetic one).
  Both are Bid-only; Volume is documented as always 0 in both.
- **Timezone:** Eastern Standard Time, **WITHOUT** Daylight Saving
  adjustment -- i.e. a fixed UTC-5 offset year-round, confirmed from
  HistData's own documentation (quoted via the `histdata` PyPI package's
  README, read directly in this session) -- and applied identically to
  BOTH platforms above, since it is a property of HistData's underlying
  data, not of the export file syntax. This is emphatically NOT this
  project's existing FTMO GMT+2/+3 EU-DST server-clock convention, even
  though the MetaTrader platform's column syntax happens to be identical
  to the project's own existing 2026-sample CSVs -- `histdata_adapter.py`
  applies ONLY the fixed EST offset, never the other model, per this
  task's own explicit instruction.
- **License:** HistData.com's own terms could not be read directly in
  this session (site blocked) -- whoever downloads the real data should
  confirm HistData's current terms of use directly on their site before
  redistributing (not merely re-downloading for this project's own
  private use) any of it.

## 3. Experiment plan (selection vs. holdout)

| Part | Period | Use |
|---|---|---|
| Selection | 2015-2022 | All S1-S8 x C1-C3 comparison, parameters unchanged |
| Holdout | 2023-2025 | ONE previously-selected candidate only; opened ONLY after selection |
| Prior sample | existing 2026 M1 data | Regression/comparison reference only, never a holdout |

2023-2025 data MAY be technically fetched and audited (format/gap/
integrity checks) alongside 2015-2022 -- but per this plan, **no S1-S8
P/L, signal performance, or selection-influencing view of 2023-2025 may
be computed before a candidate is chosen from the 2015-2022 selection
period.** This is a RESERVED validation period, not a prospective
forward test -- if 2023-2025 data is ever looked at for ANY variant
before a candidate is chosen, that fact must be disclosed and the
period can no longer be called untouched, regardless of which folder it
lives in.

If coverage turns out insufficient once data exists, any plan
adjustment (e.g. shortening either period) must be documented as an
explicit, dated correction BEFORE any P/L is computed under the
adjusted plan -- never shortened or shifted after seeing a worse-than-
hoped result.

## 4. Risk and cost model (unchanged, restated for this round's config hash)

- Initial balance 10,000 USD; 25 USD max planned risk per idea; 100 USD
  total concurrent risk cap; 50 USD correlated-group (EURUSD+GBPUSD same
  USD direction) cap.
- B0 = Europe/Prague midnight balance. Robot's own (tighter) daily
  working floor `B0-300`; robot's own static total working floor 9200.
  FTMO's own raw limits (`B0-500`, 9000) are the underlying reference,
  unchanged; the project's 200 USD buffer between the two is a safety
  margin, never a trading budget.
- Commission 2.50 USD/lot per side, booked at each side's own execution
  instant (F5's fix, unchanged).
- C1: 1.0/1.5 pip EURUSD/GBPUSD spread, 0 slippage. C2: 2.0/3.0 pip,
  0.5 pip slippage. C3: 3.0/4.5 pip, 1.0 pip slippage. Scenario config is
  applied to the ACTUAL simulator config object, not just a reported
  cost breakdown (F1's fix, unchanged) -- verified per-run via
  `run_metadata.effective_scenario_config_sha256`, exactly as the
  existing 2026-sample runs already do. Slippage applies to market entry
  fills and SL-triggered exits only (never TP, never a
  discretionary/timeout exit), unchanged.
- Gap-through-SL/TP for an already-open position is resolved BEFORE any
  discretionary/timeout exit or new entry that tick (R1's fix,
  unchanged); the entry minute's own SL/TP is still checked immediately
  after entry; account-wide portfolio/correlated-cap enforcement and the
  monthly balance/equity reconciliation (`balance_change_usd`, R2's fix)
  are unchanged and apply identically to any long-history run.
- If the long-history data adapter or its volume of data ever requires a
  simulator change, that change must be regression-tested against the
  EXISTING 2026 sample first (same 24 numbers must still reproduce
  exactly) before being trusted on the new data -- a silent behavior
  change "for the new data" is exactly the kind of bug this project's
  last three audit rounds exist to catch.

## 5. Selection-period runs (2015-2022) -- PLANNED, NOT_RUN

Both instruments trade on ONE 10,000 USD account per run -- never summed
from two independent single-pair accounts, same as every existing run
in this project.

### 5.A Continuous account -- 24 planned runs

S1-S8 x C1-C3, one continuous account per (variant, scenario) from
2015-01-01 through 2022-12-31. The account-wide stop, once triggered,
stays active for the rest of that run (no restart on a month/year
boundary); zero-activity months after a stop still appear in the
monthly table with zeros (per the existing F4 fix, unchanged), so the
report never silently truncates at the last real trade's date. No
automatic withdrawal/reinvestment or risk escalation.

### 5.B Fixed-year-start diagnostic -- 192 planned runs

8 years (2015-2022) x 8 variants x 3 scenarios, EACH its own completely
independent 10,000 USD account starting flat (no carried-over position)
at that year's first tradable instant and ending at that year's last
instant. Indicators are warmed up from the preceding year's data (2014
data for the 2015 diagnostic run, 2015 data for the 2016 run, etc.);
warm-up bars are never traded. A year with insufficient warm-up data
available must be reported as a documented limitation for that specific
run, not silently run with a short/absent warm-up.

This is a start-year-sensitivity diagnostic, not a single account's
equity curve -- the 8 years' results for one (variant, scenario) are
NEVER summed as if they were one continuous 10,000 USD investment's
return. No restart after a within-year stop; that year's run simply
continues reporting zero activity for its own remainder, same rule as
5.A.

**Total planned: 216 runs** (24 + 192). Checkpointed/incrementally
saved, matching the existing single-run report-folder convention (own
config/data hash, exact period, run command, event log, machine-readable
summary per run) -- never held entirely in memory if M1-resolution data
for 8 years x 2 symbols makes that impractical; a per-year or per-run
streaming/chunked pass is preferred once real data exists.

## 6. Pre-defined candidate qualification (practical filter, not a significance claim)

A variant QUALIFIES as a candidate only if ALL of:

1. **5.A's continuous run**, both C1 AND C2, completes the FULL period
   with NO total-working-floor stop, and a positive final net equity
   change after modeled costs.
2. **5.B's fixed-year-start diagnostic**, at least 5 of 8 years show a
   positive final equity change in BOTH C1 AND C2 (counting the full
   year's own period even after any within-year stop -- a year that
   stops out and then sits flat for the rest of the year is that year's
   own negative result, not excluded from the count).
3. **5.A's C2 run has at least 100 closed trades** -- a practical
   minimum-sample filter, never treated as proof of an edge by itself.
4. **No open simulator bug that could change the selection.** Every fix
   from the three prior audit rounds (F1-F5, R1-R2) applies unchanged;
   intrabar/broker-execution-fidelity limitations (Bid-only M1, no true
   tick path) remain explicitly stated, never silently assumed resolved.

If MULTIPLE variants qualify: pick the ONE with the highest median C2
per-year equity return across 5.B's diagnostic years; tie-break by the
smaller max C2 drawdown in the same set of runs, then by the lower S
number. C3 is always shown as additional stress information for every
variant, qualifying or not -- an unfavorable C3 result is never hidden.

**If no variant qualifies:** the required wording is "šajā fiksēto
stratēģiju atlasē kandidāts nav atrasts" (no candidate was found in this
fixed-strategy selection). Do not pick the smallest loser. Do not open
2023-2025 data. Hand off the completed infrastructure and data (once
obtained) for a separately-formulated hypothesis, per the task's own
instruction. Filters are never adjusted after seeing a result.

## 7. Holdout runs (2023-2025) -- for ONE selected candidate only, NOT YET OPENED

Before opening: fix the candidate's ID, its exact config hash, and the
selection rationale (which qualification numbers made it win) in
writing.

Then, in one pre-declared test batch:

- 3 continuous 2023-2025 runs, one per C1/C2/C3.
- 9 fixed-year-start runs: 2023, 2024, 2025 x C1/C2/C3.

No other variant's holdout P/L may be opened "just to compare" after
seeing the chosen candidate's holdout result. Once opened, this period
can never again be called untouched for any variant, including ones not
chosen.

**Positive holdout result requires ALL of:** continuous C1 AND C2 both
end with positive net equity and no total-working-floor stop, AND at
least 2 of the 3 fixed-year-starts (2023/2024/2025) are positive in EACH
of C1 and C2. Even meeting this bar means only "worth a broker-specific/
forward test next," never live-trading readiness. Insufficient trade
count or major data gaps must be reported as insufficient evidence, not
glossed over.

## 8. Reporting requirements (for whenever data exists and runs actually happen)

Every run (planned or eventually real) must record: code/config/data
hash, exact period, execution status (never marked EXECUTED for code
that only exists, per this task's own explicit instruction), starting
state, scenario, the exact command used, the full account event log,
and a machine-readable summary -- mirroring `experiment_metrics.py`'s
existing `full_metrics()` output shape (already includes
`balance_change_usd` reconciliation, `daily_floor_analysis`,
`independently_recomputed_floor_breach_days`,
`intrabar_stress_evaluated: False` / `floor_breach_detection_basis`, the
monthly table, and `run_metadata`) -- reused as-is for the long-history
runs rather than re-invented, since nothing about a longer period
changes what any of those fields mean.

Additional requirements specific to this round: distinguish `R=25 USD`
(requested) from `risk_usd_at_entry` (actual, per R3's existing
labeling) explicitly in any written report; monthly balance/equity
identities must hold exactly for an account with no external cash flows
(same `balance_change_usd` reconciliation as the existing 2026-sample
runs, R2); full months with equity growth >=2000 USD are counted and
reported as a FRACTION of all full months observed, with zero-activity
months included, never silently dropped; every candidate/scenario is
shown, not only the best; the 5.B fixed-year-start runs are explicitly
labeled as NOT an independent-observations sample (overlapping/adjacent
market regimes across years), so choosing among 8 variants x this
diagnostic is a real multiple-comparisons exposure, same caution as the
existing 8-variants-x-3-scenarios exposure already documented in
`docs/STRATEGY_RESEARCH_2026-09-18.md`.

## Plan hash

SHA256 of everything ABOVE this section, reproduced with:
```
sed '/^## Plan hash/,$d' docs/LONG_HISTORY_EXPERIMENT_PLAN.md | sha256sum
```

Original hash, fixed at the time this plan was first written (before
any download attempt in section 2 was made, and before
`histdata_adapter.py` / `download_long_history.py` were written):
```
86fa140c3df7b45c73b0e0b233c2b44b7f6f1b392b6f43f52635a61f7f8928be
```

Second hash, after a real user-supplied HistData download
(`HISTDATA_COM_MT_GBPUSD_M12019.zip`) revealed that HistData's
"MetaTrader" export platform (comma-separated, `DAT_MT_*`) also needed
supporting alongside "Generic ASCII" -- section 2.3's format
specification corrected to document both, per section 3's own rule that
a data-availability correction must be dated and made BEFORE any P/L is
computed (no run in section 5/7 had happened at either hash):
```
8abf07875b03018b38747389610df4cc4ffb27e7a27afc08dce751bd851b3ea9
```

Third hash, after the account owner supplied the full real 2015-2025
dataset and this document's own top status note was updated to record
that. Section 5.A's 24-run batch was already launched in the background
by this point (started right after the data passed its quality audit,
before this specific status-note edit), but NO result from it had been
read/observed by anyone when this hash was computed -- the substantive
guarantee (no result influences the plan) holds even though the launch
and this edit are not in the strict order the second hash's note might
suggest; stated plainly here rather than glossed over:
```
a233a62d3a83d60ec62e3c249eeb10145c63343a557a2d99fca5ea170109cca9
```
