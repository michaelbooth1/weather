# Workstation report 2026-08-09 — restart the MM countable-day clock

## Verdict

**The maker is not scheduled against an intrinsically inadequate capture cadence.** Healthy
runtime has model and book ages well inside the existing gates. The failure is intermittent
producer starvation: the daily starter and minute supervisor can both decide to launch before
either writes `daily_roll_status.json`, so the second PID replaces the first and leaves an
untracked maker worker. Production proved this mechanism on 2026-08-07: two maker workers began
47 seconds apart, the survivor held 431 MB, capture then recorded 430 memory-admission refusals
and two active-window gaps of 24 and 41 minutes.

Implementation commit
`15ee5945a2f8257f169c89d8da44ccebea637393` serializes the complete direct-start and
supervisor-ensure lifecycle decision under one process-safe lock. It does not change the 900 s
model threshold, the 120 s book threshold, the CLOB whole-day continuity audit, capture cadence,
or any trading permission.

The historical gain is **not powered as a point estimate**. The defensible freshness-only range
is **7–20 countable days of 55 (12.7%–36.4%)**: 7 is observed; 20 is the optimistic ceiling if
every `model_freshness` and `clob_freshness` failure had disappeared while every other blocker
remained. Even that ceiling is below the 22-day minimum, so this fix would not have made the gate
decidable by 2026-08-08. It prevents a proved forward-day killer; new production days must measure
the actual yield.

## Evidence boundary

- Branch: `codex/workstation-restart-the-mm-countable-day-clock-2026-09-45a`
- Base: `origin/master` at `7f79beaaef4a3999c950e3fbd2cbc86f7ef85920`
- Workstation mirror: 54 dated folders, 2026-06-15 through 2026-08-07. It does not yet contain the
  production-only 2026-08-08 folder, so production's authoritative baseline remains 7/55.
- Age population: 326 canonical plus quarantined quote tapes, deduplicated from band rows to
  86,649 `(run, generated_at_utc, market_id)` observations. Only target-date ticks inside
  07:00–20:00 America/Toronto are included. Duplicate workers remain distinct runs because both
  consumed runtime resources.
- Age quantiles use rows where the age is present. Fresh percentages use all decision ticks, so a
  missing age correctly fails freshness. The canonical-top-level-only sensitivity cut has 62,529
  ticks and reaches the same conclusion (model 91.7%, book 87.4%, both 81.3% fresh).
- This is a read-only historical diagnosis. No maker, capture loop, settlement process, exchange
  adapter, task registration, or production-state writer was run.

## P0 — the two freshness blockers

### Configured contracts

`src/weather/market/mm_policy.py` owns both defaults:

| Gate | Threshold | Enforcement |
| --- | ---: | --- |
| `model_freshness` | 900 s | `market_making_run_support.preflight_market`: latest model capture age must be `<= max_model_age_seconds` |
| `clob_freshness` | 120 s base | trailing book age and every counted active-day inter-capture gap are audited through `preflight_book_audit` |

The CLOB continuity threshold is fail-closed but cadence-aware: the effective gap allowance is the
larger of 120 s and measured fleet-loop elapsed time plus sleep plus the existing 60 s buffer. The
audit still checks the whole active day. Neither contract changed on this branch.

### Actual ages by market

All values are seconds except the fresh columns.

| Market | Ticks | Model p50 | Model p95 | Model fresh | Book p50 | Book p95 | Book fresh |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Atlanta | 7,220 | 272.6 | 873.9 | 92.8% | 14.8 | 107.7 | 90.8% |
| Austin | 7,223 | 269.5 | 862.2 | 93.1% | 16.7 | 94.5 | 90.9% |
| Chicago | 7,223 | 276.1 | 939.5 | 92.1% | 18.8 | 91.7 | 91.0% |
| Dallas | 7,223 | 270.7 | 909.6 | 92.7% | 16.0 | 91.7 | 90.8% |
| Denver | 7,220 | 255.6 | 845.2 | 93.5% | 19.3 | 103.2 | 90.4% |
| Houston | 7,220 | 272.3 | 938.0 | 91.8% | 17.1 | 98.7 | 90.9% |
| Los Angeles | 7,220 | 280.7 | 1,015.9 | 90.8% | 17.5 | 100.6 | 90.6% |
| Miami | 7,220 | 259.7 | 918.7 | 92.6% | 17.2 | 99.4 | 90.8% |
| NYC | 7,220 | 281.6 | 903.3 | 92.2% | 16.7 | 84.1 | 91.3% |
| San Francisco | 7,220 | 260.5 | 972.3 | 92.1% | 17.6 | 131.0 | 89.6% |
| Seattle | 7,220 | 250.4 | 928.2 | 92.6% | 16.6 | 123.8 | 89.8% |
| Toronto | 7,220 | 271.6 | 872.1 | 92.8% | 14.8 | 83.9 | 91.9% |

Fleet-wide, model age is p50 **268.6 s**, p95 **916.0 s**, max **21,966.2 s**, with
**92.4%** fresh. Book age is present for 81,951/86,649 ticks: p50 **16.8 s**, p95 **97.5 s**,
max **8,339.7 s**, with **90.7%** of all ticks fresh. Both inputs are fresh on **84.8%** of
ticks. The extreme tails, not the normal cadence, produce the headline failures.

### Actual ages by Toronto hour

| Hour | Ticks | Model p50 | Model p95 | Model fresh | Book p50 | Book p95 | Book fresh |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 07 | 5,784 | 274.2 | 706.5 | 95.9% | 29.9 | 56.9 | 88.1% |
| 08 | 5,964 | 262.5 | 664.4 | 95.9% | 29.6 | 57.0 | 88.3% |
| 09 | 5,664 | 260.5 | 849.5 | 93.7% | 31.8 | 57.7 | 87.9% |
| 10 | 6,120 | 244.1 | 583.9 | 96.8% | 28.3 | 61.0 | 88.7% |
| 11 | 6,672 | 273.1 | 908.6 | 90.7% | 29.2 | 59.4 | 89.8% |
| 12 | 6,768 | 279.5 | 1,164.5 | 89.7% | 24.9 | 67.8 | 89.5% |
| 13 | 6,396 | 256.9 | 784.3 | 94.2% | 27.5 | 82.7 | 93.7% |
| 14 | 6,384 | 260.6 | 973.4 | 92.1% | 25.2 | 106.3 | 94.8% |
| 15 | 6,099 | 266.2 | 939.7 | 91.8% | 9.7 | 184.5 | 90.4% |
| 16 | 6,054 | 278.2 | 1,019.5 | 90.0% | 10.0 | 166.2 | 92.8% |
| 17 | 5,592 | 285.9 | 1,005.3 | 89.8% | 10.4 | 172.9 | 93.7% |
| 18 | 5,904 | 285.5 | 1,003.7 | 89.3% | 10.8 | 209.8 | 91.5% |
| 19 | 13,248 | 269.3 | 1,084.5 | 92.4% | 11.7 | 238.1 | 90.5% |

The hour cut rules out a single bad schedule boundary: ordinary medians stay far below both
thresholds in every hour, while intermittent tails worsen from midday onward as host pressure
accumulates.

### Model freshness root cause

The latest model snapshot is normally 4–5 minutes old, not 15 minutes old. The 08-07 sample's
1,135.5 s age and the 21,966 s historical tail occur when the snapshot producer stops completing
useful work. Production commit `a1d67c3d` traced the 08-07 stop to memory admission, not the
network: a duplicate maker worker contributed to 430 refused capture workers. Therefore the maker
schedule is not at fault and a higher cadence is not required to satisfy the existing 900 s gate
during healthy operation.

### CLOB freshness root cause

Trailing book age is normally tens of seconds, but the gate also rejects a market if any counted
gap across its active day exceeds the effective threshold. The canonical remediation evidence
contains `clob_book_tape_gap_over_threshold` on **17 days / 131 market-run incidents**. Thus a
fresh trailing row cannot repair an earlier gap. The fix must prevent capture gaps; shifting maker
ticks or checking only the latest row would silently weaken continuity and is rejected.

## Regression trace and fix

The unsafe check/launch/write sequence originated with `start_for_date` in `90434a85` on
2026-06-16. It did not become a two-parent race until `f25cf7c6` added the every-minute
`WeatherMarketMakingDailyRollSupervisor` on 2026-06-25 while deliberately retaining the direct
daily starter. Both parents read the same status, both can observe no live PID, both launch, and
only the later PID is persisted. Subsequent stop/restart logic can reap only that persisted PID.

This is a traced exposure point, not a claim that every stale day has one cause. Counted days
continued through 06-27 and the mirror cannot reconstruct old process tables, so the race is
episodic and causal attribution across all 55 days is not powered. What is proved is the exact
08-07 chain and the same orphan class recorded for taker workers on 06-30 and 07-04.

The implementation places the same lock beside `daily_roll_status.json` around:

1. direct `start_for_date`: status read, liveness check, disk preflight, child launch, and PID write;
2. supervisor `ensure_for_date`: status/identity health decision, stop/restart, launch, status
   annotation, and superseded-run finalization.

That second scope matters: locking only the child launch would still allow the supervisor to make
a stale `force=True` decision before a direct starter writes the new PID. Dead lock owners are
reclaimed by the repository's existing PID-aware file-lock primitive. A live lock is waited on for
10 seconds and then fails closed rather than launching without serialization. A concurrency test
holds the direct launcher open, starts `ensure` in parallel, and proves one child launch plus a
supervisor `noop` after the lock releases.

## P1 — counterfactual yield

| Scenario | Mirrored countable days | Production-equivalent assumption | Gate minimum reached? |
| --- | ---: | ---: | :---: |
| Observed | 7/54 (13.0%) | 7/55 (12.7%) | no |
| Every model + CLOB freshness blocker repaired; all else unchanged | 20/54 (37.0%) | 20/55 (36.4%); 08-08 remains missing evidence | no |
| Every freshness + producer-useful-write/loop blocker repaired | 30/54 (55.6%) | not defensible as a causal estimate | yes, theoretical only |

The branch's measured claim is therefore **7–20/55 for the freshness-only historical
counterfactual**. The upper endpoint intentionally attributes every freshness failure to the fixed
mechanism and is generous. The lower endpoint reflects that only 08-07 has complete causal process
evidence and that repairing a blocker on one run does not necessarily clear every other blocker on
that day. No effect size, comparative power, or forward yield can honestly be estimated before the
fixed lifecycle runs on production.

## P2 — missing-remediation observability

The reported 39 missing files across 27 days included **24 `_quarantine` containers falsely
counted as run directories**. The post-mortem now uses the same canonical top-level run selection
as daily-roll operations and ignores quarantine/hidden lifecycle scaffolding. On the workstation
mirror this changes the hole to **13 runs across 10 days**, while countable days remain 7/54.

Of those 13 real runs, nine directories are empty, three contain only `run_config.json`, and one
06-15 legacy run has other artifacts but predates the stable remediation write. The 12 empty or
config-only runs terminated before their first preflight tick. The launch mutex can prevent the
race-created subset, but the evidence does not support claiming it explains all 12. Production
must rerun the corrected report to add the missing 08-08 folder and establish the authoritative
post-fix number.

## Reproduction

From the production repository root, with no maker or capture process started:

```powershell
.\venv\Scripts\python.exe -m weather.reporting.market.mm_input_age_postmortem `
  --runs-root data\mm_runs --include-quarantine

.\venv\Scripts\python.exe -m weather.reporting.market.mm_countability_postmortem `
  --runs-root data\mm_runs `
  --counterfactual-repair-gate model_freshness `
  --counterfactual-repair-gate clob_freshness

.\venv\Scripts\python.exe -m pytest -q `
  tests\operations\test_market_making_daily_roll.py `
  tests\market\test_mm_countability_postmortem.py `
  tests\market\test_mm_input_age_postmortem.py
```

The age report prints JSON and the countability report prints Markdown to stdout unless an explicit
output path is supplied. Both are read-only over `data\mm_runs` in the commands above.

## Verification and handback

- Focused tests: **32 passed**.
- `compileall` on changed Python modules/tests: **PASS**.
- `python -m weather.operations.agent_docs_audit`: **PASS** (18 agent files, 717 Markdown files).
- Full-suite attempt: **environment-blocked during collection**. The checked-in venv points to the
  removed `C:\Users\Michael\AppData\Local\Programs\Python\Python311\python.exe`; the available
  bundled Python is 3.12 and cannot load the venv's CPython 3.11 binary extensions for sklearn,
  scipy, matplotlib, and pyarrow. The changed slices run with bundled 3.12 packages plus the venv's
  pure-Python pytest.
- Strict schema audit has two unchanged baseline findings already present on `origin/master`:
  `mm_countability_postmortem_v1` and `severe_tail_ex_ante_casebook_v0.1`. The new age report uses
  an integer `report_version`, so it introduces no schema-registry finding or runtime import.
- Repository-owned roll verdict on the exact branch head: **ROLL-FREE**. It classified all three
  importable changed files as free:
  - `src/weather/operations/market_making_daily_roll.py` — free
  - `src/weather/reporting/market/mm_countability_postmortem.py` — free
  - `src/weather/reporting/market/mm_input_age_postmortem.py` — free
  The dormant `clob_enrichment` closure was 295.4 hours old but mechanically **SUBSUMED**: all 21
  files in it are covered by a live closure, so dormancy does not affect the verdict.
