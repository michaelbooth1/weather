# Agent report 2026-08-25 — `high_so_far` population census

## Verdict

**`M6_unexplained` is 20 / 906 B events and 4 / 1,284 C events: 24 / 2,190 =
1.10%.** The residual is small, but not zero. The fixed evidence classes account for 98.90% of
all decreases.

The predeclared expectation splits sharply by stratum:

- **C matches it:** `M2_empty_history` is 1,278 / 1,284 = 99.53%, and 1,049 / 1,284 =
  81.70% of events are pre-dawn.
- **B falsifies it:** `M5_cutoff_change` is 658 / 906 = 72.63%; only 218 / 906 = 24.06% are
  pre-dawn, while 368 / 906 = 40.62% land in the peak-heating or remaining settlement window.

This is therefore **not** the clean null in which the defect is only a narrow pre-dawn fallback.
C is that narrow fallback population; B is spread over the model's main decision path. The two
previously traced mechanisms alone account for 1,424 / 2,190 = 65.02%, not the population. Three
additional measured classes account for 742 events, leaving the 24-event residual above.

There is also train/serve skew on this live feature. Recorded serve-time `high_so_far` differs from
the archive-rebuilt training value on 2,112 / 21,676 comparable B snapshots (9.74%) and
45,849 / 48,922 comparable C snapshots (93.72%). Magnitudes below are separated by native unit;
no Celsius and Fahrenheit magnitudes are pooled for interpretation.

This mission measured only. It changed no feature, floor, collection, replay, scoring, or serving
behavior.

## Exact population

The tracked `-09-67a` settlement roster and admitted `features_long.csv` rows reproduce the handoff
exactly. An admitted snapshot has both `high_so_far` and `current_temp`; an event is a strict
decrease from the immediately preceding admitted row in the same market-day, ordered by
`captured_at_utc` with original file order as the stable tie-break.

| Quantity | B | C |
| --- | ---: | ---: |
| Raw feature rows | 33,032 | 52,637 |
| Blank `high_so_far` or `current_temp` | 4,656 | 3,604 |
| Admitted snapshots | **28,376** | **49,033** |
| Below running maximum of prior `current_temp` values already seen | **5,283 (18.62%)** | **14,995 (30.58%)** |
| Market-days | 204 | 320 |
| Market-days with a decrease | **125 (61.27%)** | **292 (91.25%)** |
| Decrease events | **906** | **1,284** |

The emitted CSV has exactly 2,190 data rows and no duplicate emitted
`(stratum, market_id, target_date, snapshot_id)` join key. Snapshot IDs were not reformatted.
Internally, the harness joins replay with `(snapshot_id, captured_at_utc)` because retained feature
files contain 52 excess duplicate snapshot IDs in B and one in C. B also has two exact duplicate
capture-key rows. Those retained facts are measured, not silently deduplicated.

This is an exact finite-population census, not a sample. No interval, bootstrap, power calculation,
alpha, or multiple-testing adjustment applies. B and C remain separate on opposite sides of the
`2026-07-31` boundary throughout.

## Mechanism split

| Mechanism | B | B rate | C | C rate |
| --- | ---: | ---: | ---: | ---: |
| `M1_restatement` | 2 | 0.22% | 0 | 0.00% |
| `M2_empty_history` | 144 | 15.89% | 1,278 | 99.53% |
| `M3_rows_dropped` | 78 | 8.61% | 0 | 0.00% |
| `M4_source_switch` | 4 | 0.44% | 0 | 0.00% |
| `M5_cutoff_change` | 658 | 72.63% | 2 | 0.16% |
| **`M6_unexplained`** | **20** | **2.21%** | **4** | **0.31%** |
| **Total** | **906** | **100%** | **1,284** | **100%** |

The frozen precedence is `M2`, `M4`, `M1`, `M5`, `M3`, then `M6`. Precedence is necessary because
the discriminants overlap; it is part of the seed, not an after-the-fact choice. Raw discriminant
counts make the overlap visible:

| Raw event discriminant | B | C |
| --- | ---: | ---: |
| Empty-history fallback | 144 | 1,278 |
| Source kind changed | 4 | 0 |
| Restatement pattern | 2 | 0 |
| Cutoff hour changed | 660 | 60 |
| Series row count dropped | 740 | 0 |
| At least one positional row temperature changed | 5 | 0 |
| `latest.datetime` changed | 762 | 0 |

Thus 658 B events with both a cutoff change and fewer rows are classified `M5`, not `M3`. In C,
58 of the 60 cutoff changes are also current empty-history fallbacks and remain `M2`; only two are
`M5`. The San Francisco positive control widened its cutoff 13 -> 14, but its unchanged row count,
unchanged `latest`, and changed row temperature put it in the more specific `M1` class.

The 24 `M6` events are not a single hidden version of the known mechanism. Nineteen of the 20 B
residuals have one current WU row, a changed `latest`, the same source and cutoff, and no row loss;
the remaining B residual has 16 current rows. The four C residuals have empty WU history but resolve
as `station` and do not satisfy the required `high_so_far == current_temp` fallback identity.

### End-to-end class traces

Every nonempty class has a replay-backed predecessor/current trace in the manifest:

1. **M1 — restatement.** San Francisco `2026-06-09`,
   `20260609T170137-0400 -> 20260609T171152-0400`: served `68 -> 67`, 18 WU rows in both,
   `rows_changed=1`, no row loss, unchanged `latest`, source `wu`, and cutoff `13 -> 14`.
   `wu_history.max` stayed `67 -> 67`; the WU-current maximum changed `68 -> 67`. Settlement was
   67. This reproduces the traced positive control.
2. **M2 — empty history.** Chicago `2026-06-14`,
   `20260614T011002-0400 -> 20260614T011808-0400`: rows stayed zero,
   `wu_history.max=None`, and both `high_so_far` and `current_temp` fell `70 -> 68`. Cutoff and
   source did not change; the captured WU-current maximum remained 83. Settlement was 69.
3. **M3 — rows dropped.** Atlanta `2026-06-19`,
   `20260619T040230-0400 -> 20260619T040329-0400`: served and WU-history maximum both fell
   `73 -> 72`, rows fell `4 -> 3`, `latest` changed, cutoff stayed 7, source stayed `wu`, and the
   WU-current maximum stayed 86.
4. **M4 — source switch.** Toronto `2026-06-15`,
   `20260615T000530-0400 -> 20260615T000821-0400`: served fell `17 -> 13`, rows changed
   `0 -> 1`, source changed `other -> wu`, cutoff stayed 7, and WU-history maximum changed
   `None -> 13`.
5. **M5 — cutoff change.** Atlanta `2026-06-13`,
   `20260613T112144-0400 -> 20260613T113204-0400`: served fell `84 -> 81`, cutoff narrowed
   `10 -> 9`, rows fell `11 -> 10`, source stayed `wu`, WU-history maximum fell `87 -> 84`, and
   WU-current maximum rose `87 -> 88`. Precedence assigns this overlapping event to `M5`.
6. **M6 — unexplained.** Atlanta `2026-06-21`,
   `20260621T005502-0400 -> 20260621T005603-0400`: served fell `74 -> 73`, rows changed
   `0 -> 1`, WU-history maximum changed `None -> 73`, source stayed `wu`, cutoff stayed 7, and
   `latest` changed. Current history is nonempty, so it is not `M2`; there is no source switch,
   restatement, cutoff change, or row loss. It remains visible as `M6`.

## Magnitude and local-time placement

All magnitudes remain in each market's native settlement unit. Toronto is reported in Celsius;
the other markets are reported in Fahrenheit.

| Stratum / unit | Events | Adjacent drop p50 / p90 / p95 / p99 / max | Deficit from prior daily running max p50 / p90 / p95 / p99 / max |
| --- | ---: | --- | --- |
| B / F | 837 | 1 / 3 / 4 / 7 / **19°F** | 2 / 3 / 5 / 7 / **20°F** |
| B / C | 69 | 1 / 2 / 2 / 4 / **11°C** | 1 / 2 / 3 / 11 / **11°C** |
| C / F | 1,160 | 1.08 / 3.06 / 3.96 / 7.56 / **14.94°F** | 2.88 / 7.02 / 8.10 / 10.98 / **15.12°F** |
| C / C | 124 | 0.50 / 1.20 / 1.80 / 2.20 / **2.70°C** | 1.60 / 3.40 / 3.60 / 4.30 / **5.20°C** |

`drop_degrees` in the CSV is the specified deficit from `prev_running_max`; this is why its B/F
maximum is 20°F while the largest adjacent fall is 19°F.

Window categories are disjoint with precedence pre-dawn (`00:00-06:59`), peak heating
(`14:00-16:59`), remaining settlement (`12:00-13:59` and `17:00-17:59`), then other.

| Window | B | B rate | C | C rate |
| --- | ---: | ---: | ---: | ---: |
| Pre-dawn | 218 | 24.06% | 1,049 | 81.70% |
| Peak heating | 163 | 17.99% | 40 | 3.12% |
| Remaining settlement | 205 | 22.63% | 40 | 3.12% |
| Other | 320 | 35.32% | 155 | 12.07% |
| **Peak + settlement** | **368** | **40.62%** | **80** | **6.23%** |

Times are market-local. The handoff's Chicago `01:10` and San Francisco `17:01` labels are the
Eastern-time snapshot-ID clocks; their market-local decision times are `00:10` Central and `14:01`
Pacific respectively.

## Captured counterfactual candidates

`max_rows_served_path` is the captured served path: maximum of admitted WU rows when present and
the captured fallback otherwise. Legacy field names ending in `_c` do not change the native-unit
contract.

| Stratum | Candidate | Available snapshots | Within-day decreases | Available event pairs | Candidate fell on `high_so_far` event | Above settlement: all snapshots / event rows |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| B | Served max/rows path | 28,376 | 906 | 906 | 906 | 7 / 0 |
| B | `wu_history.max` | 27,380 | 748 | 739 | 729 | 1 / 0 |
| B | `wu_current.max_since_7am` | 28,178 | 1,088 | 901 | 30 | 5,603 / 81 |
| C | Served max/rows path | 49,033 | 1,284 | 1,284 | 1,284 | 7,851 / 0 |
| C | `wu_history.max` | **0** | not measurable | 0 | not measurable | not measurable |
| C | `wu_current.max_since_7am` | **0** | not measurable | 0 | not measurable | not measurable |

No B candidate is monotone within the market-day: each has observed decreases. None also has zero
all-snapshot settlement exceedances. The WU-current maximum is especially unsafe as a floor
counterfactual: it exceeds settlement on 5,603 B snapshots, including 81 decrease-event rows.

The handoff assumed three candidates would be held at every event. Captured C replay does not hold
either WU summary candidate on any admitted C row, so their C monotonicity and floor safety cannot
be measured from this evidence. They are reported unavailable rather than imputed. The served path
is complete in C and exceeds settlement on 7,851 snapshots, although not on the current row of any
decrease event.

The two blocking rows are:

| Row | Served max/rows | `wu_history.max` | `wu_current.max_since_7am` | Settled high |
| --- | ---: | ---: | ---: | ---: |
| Chicago `20260614T011002-0400` | 70 | unavailable | 83 | 69 |
| San Francisco `20260609T170137-0400` | 68 | 67 | 68 | 67 |

These are measurements, not serving recommendations. No candidate was nominated or fit.

## Train/serve comparison

For each snapshot cutoff, the harness rebuilds the training value as the maximum archived
native-unit row temperature with `minute_of_day <= cutoff_hour * 60`, matching the training call
site. It compares that value with the recorded serve-time feature. The archive has hourly rows for
487 panel market-days; 482 satisfy the retained daily-summary minimum of 20 rows. Delta below is
`archive training value - recorded served value`.

| Stratum / unit | Market-days | Snapshots | Comparable | Equal | Training higher | Training lower | Unavailable | Days with difference |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| B / F | 184 | 25,642 | 19,409 | 17,485 | 1,784 | 140 | 6,233 | 102 (55.43%) |
| B / C | 20 | 2,734 | 2,267 | 2,079 | 181 | 7 | 467 | 8 (40.00%) |
| C / F | 293 | 44,660 | 44,549 | 2,870 | 25,880 | 15,799 | 111 | 278 (94.88%) |
| C / C | 27 | 4,373 | 4,373 | 203 | 3,242 | 928 | 0 | 25 (92.59%) |

Mismatch rates among comparable snapshots are 9.91% (B/F), 8.29% (B/C), 93.56% (C/F), and
95.36% (C/C). Both signs occur in every stratum/unit cell; this is not a constant offset.

| Stratum / unit | Nonzero absolute delta p50 / p90 / p95 / p99 / max | Market-day maximum absolute delta p50 / p90 / p95 / p99 / max |
| --- | --- | --- |
| B / F | 2 / 4 / 5 / 58 / **68°F** | 2 / 63 / 65 / 68 / **68°F** |
| B / C | 3 / 4 / 4 / 6 / **10°C** | 1 / 7 / 7 / 10 / **10°C** |
| C / F | 0.08 / 3.04 / 4.08 / 7.06 / **24.68°F** | 4.02 / 7.98 / 9.98 / 13.80 / **24.68°F** |
| C / C | 0.40 / 2.50 / 3.00 / 4.10 / **5.20°C** | 2.80 / 3.90 / 4.50 / 5.20 / **5.20°C** |

Representative extrema show why sign matters:

- B/F Dallas `2026-06-12`, `20260612T010304-0400`, cutoff 7: served 17°F versus archive
  85°F, delta **+68°F**.
- B/C Toronto `2026-06-15`, `20260615T104352-0400`, cutoff 10: served 24°C versus archive
  14°C, delta **-10°C**.
- C/F Denver target `2026-07-09`, `20260710T020143860181-0400`, cutoff 7: served 90.68°F
  versus archive 66°F, delta **-24.68°F**.
- C/F Seattle `2026-07-30`, `20260730T190220092038-0400`, cutoff 16: served 60.08°F versus
  archive 75°F, delta **+14.92°F**.

This is systematic train/serve skew on a live feature, especially in C, but it is not a candidate,
endpoint, or performance result. It licenses no serving change.

## Support, integrity, and campaign boundary

The standard-library-only harness read 1,085 input files totaling 31,990,228,718 bytes. The
canonical receipt-list digest is
`5324e6e942d236d43c7bfccd980d59f2d69c78b37fc2957e2a6b1053bf1a8873`. It scanned 85,538
replay lines / 31,850,348,940 replay bytes. All 4,360 distinct event/predecessor payload rows have
captured replay support. There are 131 admitted non-event feature rows without a replay match; they
affect candidate availability counts but no mechanism classification.

| Committed evidence | SHA-256 |
| --- | --- |
| CSV, 2,190 rows / 289,817 bytes | `2e83dffba271ae3f30aa5e1884f99a1c46d8529b12c59af133aa5f26f493af67` |
| Manifest | `4d97f925b2b51d3a4a46447dee1be46917c5d51d5718e8bd525bb361a9396c00` |
| Harness | `e50beb7a9edf4bfd6e4185105aec8192764f6aa36f0b3c1d892cef7d5b641a20` |
| Frozen seed | `20f6278a4e72909375e18abf9009b03f29f8f2ddeedba583c774c6e93757b956` |
| Tracked settlement roster | `73501415ea8dd31db8816c3fb4b5e8db92eb0d5448b8b5f48e7c57b6c44597cd` |

C was read only as an input-integrity instrument census, on the expressly permitted basis that
there is no candidate, fitted parameter, endpoint comparison, or accept rule. Alpha remains
**7 of 20 spent, 13 available**. This mission allocated zero alpha. Decision 10 remains
**CLOSED UNUSED** and was not reopened, reassigned, or spent.

## Verification and reproduction

Two complete runs over the 31.99 GB receipt set reproduced the CSV and manifest byte for byte.
Runtime was bundled Codex Python 3.12; nothing was installed and no provider, exchange, or other
network endpoint was called.

On the workstation holding the ignored captured evidence:

```powershell
$repo = 'C:\Users\Michael\Documents\github\weather'
$worktree = "$repo\scratch\w\high-so-far-09-70a"
$python = 'C:\Users\Michael\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'

Set-Location $worktree
& $python .\tools\research\measure_high_so_far_population_09_70a.py `
  --repo-root $worktree `
  --evidence-root $repo
Get-FileHash -Algorithm SHA256 `
  .\docs\roadmap\high-so-far-decreases-2026-09-70a.csv, `
  .\docs\roadmap\high-so-far-decreases-2026-09-70a-manifest.json
```

Expected exit is 0, verdict `HIGH_SO_FAR_POPULATION_MEASURED`, 906 B events, 1,284 C events,
24 total `M6` events, CSV SHA-256 `2e83dffb...af67`, and manifest SHA-256
`4d97f925...6c00`.

Production-host acceptance uses committed paths only; ignored workstation evidence is not claimed
to exist there:

```powershell
$repo = 'C:\Users\micha\Desktop\github\weather'
Set-Location $repo
git fetch origin
$branch = 'origin/codex/workstation-measure-the-high-so-far-population-2026-09-70a'
$report = 'docs/roadmap/agent-report-2026-08-25-workstation-high-so-far-population.md'

git rev-parse $branch
git show "${branch}:$report"
git show "${branch}:docs/roadmap/high-so-far-decreases-2026-09-70a.sha256"
git show "${branch}:docs/roadmap/high-so-far-decreases-2026-09-70a-manifest.json"
git show "${branch}:tools/research/measure_high_so_far_population_09_70a.py"
git show "${branch}:tools/research/measure_high_so_far_population_09_70a_seed.json"
git diff --name-status origin/master...$branch
git diff --check origin/master...$branch
.\venv\Scripts\python.exe -m weather.operations.agent_docs_audit
powershell.exe -NoProfile -ExecutionPolicy Bypass -File `
  .\scripts\ops\roll_verdict.ps1 -Branch $branch
```

## Branch and roll verdict

Base: `a9ba4e3df6c1a3db0e129d821df4afe0d3dfeebd` (`origin/master`).

Branch: `codex/workstation-measure-the-high-so-far-population-2026-09-70a`.

Analysis artifact/script commit: `c841b683`.

Initial report commit: `66c53192`.

After that report commit, the authoritative repository command from the fresh worktree returned exit 0
and **`VERDICT: ROLL-FREE`**. It mechanically corrected the 47-commit-stale local `master` to
`origin/master (a9ba4e3d)` and evaluated exactly six changed files with zero importable files. The
363.2-hour-old dormant `clob_enrichment` closure was fully subsumed by live closure evidence and
could not affect the verdict.

| Changed file at verdict | Verdict |
| --- | --- |
| `docs/roadmap/agent-report-2026-08-25-workstation-high-so-far-population.md` | Roll-free Markdown report |
| `docs/roadmap/high-so-far-decreases-2026-09-70a.csv` | Roll-free tracked evidence |
| `docs/roadmap/high-so-far-decreases-2026-09-70a-manifest.json` | Roll-free manifest |
| `docs/roadmap/high-so-far-decreases-2026-09-70a.sha256` | Roll-free checksum |
| `tools/research/measure_high_so_far_population_09_70a.py` | Roll-free one-off research tool |
| `tools/research/measure_high_so_far_population_09_70a_seed.json` | Roll-free research seed |

A final confirmation after this verdict-only report update returned the same six-file,
zero-importable, `ROLL-FREE` result.

## Explicitly not done

- No alpha, candidate, fitting, parameter, C endpoint, endpoint comparison, score, accept rule,
  model selection, or performance claim was created. Decision 10 was untouched.
- No `high_so_far`, serving floor, collection, replay, scoring, feature, model, calibration,
  settlement, or production source was changed. The serving floor was not weakened.
- No production `data/`, tape, ledger, artifact, scheduled task, collector, supervisor, process,
  release, or trading state was written, registered, started, restarted, promoted, or activated.
- No PR, merge, master update, production checkout change, order, or trade was performed.
