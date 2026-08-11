# Agent report 2026-08-26 — cutoff direction and producer trace

## Verdict

**`B_M5_NARROWS_658_OF_658; ROOT_CAUSE_WU_SERIES_REGRESSION; NO_SERVING_CHANGE`.**

The load-bearing B result survives. All **658 / 658** B events frozen as
`M5_cutoff_change` narrow: `-1` hour in 655 events, `-2` in 2, and `-4` in 1. None
widens. B's frozen `M6` residual therefore remains **20 / 906 = 2.21%**, not roughly
75%.

The causal name needs refinement. `cutoff_hour` in the captured B feature rows is not the
capture hour. The live model derived it from the latest WU-history observation minute, capped by
the wall-clock cutoff. The raw WU series lost rows and its latest minute regressed in **658 / 658**
B M5 events; that regression was upstream of the narrower cutoff. On the current payload held
fixed, narrowing independently lowered the WU-window maximum in only **48 / 658 = 7.29%** of M5
events. Raw-series loss lowered the old-cutoff maximum in **636 / 658 = 96.66%**. Thus M5 is
directionally correct for B, but it is usually a symptom of a non-append-only WU series rather
than an independent root cause.

C is different and remains separate. Its two frozen M5 events both **widen** by `+1`; widening
cannot explain either decrease. Both are station/METAR-series regressions. The historical M5 label
is therefore misnamed for C, but no C residual is being reassigned and no frozen precedence was
changed.

This mission measured and traced only. It changed no feature, floor, producer, replay, collection,
scoring, or serving behavior.

## Direction census and -09-70a reconciliation

The corrected CSV retains one row per one of the 2,190 decrease events and adds the requested
previous/current cutoff, signed delta, previous/current capture minute, and rows lost from the
cutoff-filtered WU window.

| Stratum / population | Narrowed | Widened | Signed distribution |
| --- | ---: | ---: | --- |
| B, all raw cutoff changes | **658 / 660** | 2 / 660 | `-4: 1`, `-2: 2`, `-1: 655`, `+1: 2` |
| B, frozen M5 | **658 / 658** | **0 / 658** | `-4: 1`, `-2: 2`, `-1: 655` |
| C, all raw cutoff changes | 0 / 60 | **60 / 60** | `+1: 60` |
| C, frozen M5 | 0 / 2 | **2 / 2** | `+1: 2` |

The prior mechanism split reproduces exactly:

| Mechanism | B | C |
| --- | ---: | ---: |
| `M1_restatement` | 2 | 0 |
| `M2_empty_history` | 144 | 1,278 |
| `M3_rows_dropped` | 78 | 0 |
| `M4_source_switch` | 4 | 0 |
| `M5_cutoff_change` | **658** | **2** |
| `M6_unexplained` | 20 | 4 |
| **Total** | **906** | **1,284** |

This reconciles the handoff's **658 / 2** M5 split and -09-70a's **660 / 60** raw
cutoff-change split without changing classification precedence.

## Which producer actually wrote `cutoff_hour`

The lead in `replay_backtest.py:460` and `tape_scoring.py:216` is not the producer of the retained
`features_long.csv`. Those functions derive analysis/scoring rows from captured time and put
`capture_minute` beside `cutoff_hour = minute // 60`; neither appends the feature tape.

The actual captured path, bound to the historical source rather than inferred from today's tree,
is:

1. Both Atlanta replay records retain the same model identity, including
   `src/model_distribution.py` SHA-256
   `88d27524f2f57a8d3f048920fa1c0f5a4fca228beeab90a6f7ff48b430c27e55`.
   Git object `815d7594:src/model_distribution.py` reproduces that digest byte for byte.
2. In that exact file, `effective_intraday_cutoff_hour()` at lines **1010-1023** obtains the
   wall cutoff from `now`, finds the maximum minute among WU-history rows, and returns the greatest
   configured cutoff no later than both. The latest observation minute therefore caps the wall
   clock.
3. `815d7594:src/toronto_model.py:144-153` calls that function with
   `sources["wu_history"]["rows"]`, then passes the result to `live_feature_record()`.
4. `815d7594:src/feature_store.py:59-73` stores that value as `"cutoff_hour"` and separately
   stores `captured_at_local`. It does not derive the cutoff from the capture minute.
5. `815d7594:src/snapshot_tracker.py:577-586` builds the model and passes it to
   `SnapshotStore.maybe_write()`. `SnapshotStore.write()` at lines **224-237** reads the model's
   `feature_vector`, overlays capture metadata through `audit_row`, and appends the resulting row to
   `self.features_long_path`.

Current `origin/master` has since moved these owners under `src/weather/` and added settlement-print
minute aliasing. The historical hash matters: replaying today's line numbers would not be a trace of
what wrote the June rows.

## Atlanta end-to-end trace

Atlanta target `2026-06-13` proves the whole chain on captured evidence:

| Captured feature row | Previous | Current |
| --- | ---: | ---: |
| Snapshot | `20260613T112144-0400` | `20260613T113204-0400` |
| `captured_at_local` | `11:21:44.421726` | `11:32:03.518392` |
| Derived capture minute | **681** | **692** |
| Wall-clock cutoff hour | 11 | 11 |
| Raw WU rows | 11 | 10 |
| Latest WU row | `10:52`, 87°F | `09:52`, 84°F |
| Recorded `cutoff_hour` | **10** | **9** |
| Raw WU-history maximum | 87°F | 84°F |
| Cutoff-aligned WU maximum / served `high_so_far` | **84°F** | **81°F** |

The raw response dropped the 10:52 row, so the latest observation regressed from minute 652 to
592 while capture advanced. Under the captured producer, those minutes yield cutoffs 10 and 9.
At cutoff 10 the 09:52 row is admitted and the window maximum is 84°F; at cutoff 9 it is excluded
and the 08:52 row sets the 81°F maximum. `rows_lost_within_window = 1` on this pair. The capture
clock never went backward; the observation series did.

This also settles direction of causality: **raw series regression is upstream; the cutoff narrows
because it reads the regressed latest observation.**

## Is cutoff narrowing itself the whole B mechanism?

No. Holding each current raw WU payload fixed, the harness recomputed its maximum under the old and
new cutoffs. Separately, it compared the previous raw payload with the current raw payload at the
old cutoff.

| B M5 effect path | Events | Share of 658 |
| --- | ---: | ---: |
| Raw-series loss lowers the maximum; cutoff adds nothing | **610** | 92.71% |
| Cutoff narrowing lowers the maximum; raw-series loss does not | 22 | 3.34% |
| Both raw-series loss and cutoff narrowing lower it | 26 | 3.95% |

All 658 lost at least one raw WU row, all 658 regressed in latest observation minute, and all 658
lost at least one row from the old served window. A same-timestamp raw row survived but moved outside
the narrower boundary in 68 events; in 48 events that incremental boundary change lowered the
maximum.

So `M5`, `M3`, and `M1` are not three unrelated data sources:

- M5 is removal of latest rows severe enough to drag the derived cutoff backward.
- M3 is row removal that leaves the derived cutoff unchanged.
- M1 is temperature restatement at existing positions with stable row count/latest time.

They are three symptoms of one upstream property — **the captured WU observation series is not
append-only** — though removal and value restatement are distinct operations within that defect
class. This is a model-input finding, not evidence that changing the producer improves Brier.

## Every widened event has another explanation

### B: two widened events, both M1 restatements

The only B widenings are San Francisco and Seattle on `2026-06-09`, both `+1`. Row count and
latest timestamp stay fixed while one positional row temperature changes. The frozen precedence
correctly keeps both in `M1_restatement`; widening contributes no decrease.

### C: 58 M2 fallbacks and two station regressions

All 60 C cutoff changes widen by `+1`. Fifty-eight are already `M2_empty_history`: WU history is
empty and the current fallback declines. The two frozen M5 cases also have empty WU history, but
fail M2's `high_so_far == current_temp` identity. Their captured station path supplies the cause:

| C case (native °F) | Capture | Cutoff | METAR rows / latest | Station max / `high_so_far` |
| --- | --- | --- | --- | --- |
| Austin `2026-07-26` | `09:57:49 -> 10:00:34` | `9 -> 10` | `13 @ 10:00 -> 11 @ 09:00` | `84.02 -> 80.60` |
| Chicago `2026-07-18` | `13:54:56 -> 14:00:36` | `13 -> 14` | `15 @ 14:00 -> 13 @ 12:00` | `87.08 -> 86.00` |

Both METAR series regress while wall time advances; `station_observations.max_since_7am_native`
and served `high_so_far` fall with them. The widening cutoff cannot lower either maximum. These two
rows are **station-series regression**, not cutoff regression. The frozen CSV retains M5 solely to
reconcile -09-70a's declared precedence.

## Naming the B M6 fingerprint

The 19-row signature is **`first_print_history_takeover`**:

- WU history expands `0 -> 1` row in **19 / 20** B M6 events;
- `latest` changes, source kind and cutoff stay fixed, and no raw row is lost;
- current `high_so_far` equals the new WU-history maximum in all 19.

This is a sibling of M2, not scatter. M2 is the empty-history side of the authority boundary, where
the current fallback supplies the feature. `first_print_history_takeover` is the opposite edge:
the first WU history print arrives and takes authority even when its maximum is lower than the
previous fallback-backed high.

The twentieth B M6 event is separate: San Francisco `2026-06-09`, snapshot
`20260609T141618-0400`, expands `15 -> 16` WU rows while one existing positional temperature is
restated; latest changes, cutoff stays 11, and served high falls 67 -> 66. It is an
append-plus-restatement hybrid, M1-like but outside M1's frozen equal-row-count/equal-latest rule.

Thus the named fingerprint reduces the genuinely unnamed B residue to **1 / 906 = 0.11%** without
editing the frozen M6 label. The four C M6 events remain separate: WU history stays `0 -> 0`, source
is station, and no WU latest value changes.

## Support, integrity, and campaign boundary

| Quantity | B | C |
| --- | ---: | ---: |
| Date clusters | 23 | 27 |
| Market clusters | 12 | 12 |
| Market-days | 204 | 320 |
| Admitted snapshots | 28,376 | 49,033 |
| Decrease events | 906 | 1,284 |

This is an exact finite-population census. No sampling interval, bootstrap, power calculation,
alpha, or multiple-testing adjustment applies. B and C are reported separately and never pooled
across the `2026-07-31` boundary.

The harness read 1,085 input files totaling 31,990,228,718 bytes. The canonical receipt-list digest
is `5324e6e942d236d43c7bfccd980d59f2d69c78b37fc2957e2a6b1053bf1a8873`.
All 4,360 event/predecessor rows retain replay support. Two complete runs with the final harness
reproduced both artifacts byte for byte.

| Committed evidence | SHA-256 |
| --- | --- |
| CSV, 2,190 rows / 326,360 bytes | `fee76c90ddca342257904901c73f57a0c63ac698102391b99b6fab9913ed9294` |
| Manifest | `2a384885026ffeff5836ff233679514a756742b52d2c08b4245be422582edad0` |
| Harness | `43093017c20ba6d52a855e45a6827f5f27dbfbbe04a4af8ec4b8fb3f2964dcc4` |
| Frozen seed | `010687e6a30cc336de7783760510eaad92ef41a602318a9a9d8fa00c73e58730` |

C was read only as the expressly permitted input-integrity census: there is no candidate, fitted
parameter, endpoint comparison, C endpoint, accept rule, or model selection. Alpha remains
**7 of 20 spent, 13 available**. This mission allocates and spends zero alpha. Decision 10 remains
**CLOSED UNUSED** and was not reopened or reassigned.

All temperature magnitudes remain in their market's native settlement unit. No Toronto Celsius
magnitude is pooled with a Fahrenheit market.

## Verification and reproduction

Full workstation reproduction on the host holding the ignored evidence:

```powershell
$repo = 'C:\Users\Michael\Documents\github\weather'
$worktree = "$repo\scratch\w\cutoff-direction-09-71a"
$python = 'C:\Users\Michael\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'

Set-Location $worktree
& $python .\tools\research\measure_high_so_far_population_09_70a.py `
  --repo-root $worktree `
  --evidence-root $repo
Get-FileHash -Algorithm SHA256 `
  .\docs\roadmap\high-so-far-cutoff-direction-2026-09-71a.csv, `
  .\docs\roadmap\high-so-far-cutoff-direction-2026-09-71a-manifest.json
```

Expected exit is 0, verdict `HIGH_SO_FAR_CUTOFF_DIRECTION_MEASURED`, B M5 signed distribution
`{-4: 1, -2: 2, -1: 655}`, C M5 `{+1: 2}`, CSV SHA-256 `fee76c90...9294`, and manifest
SHA-256 `2a384885...ad0`.

Production-host acceptance uses only committed paths; ignored workstation evidence is not claimed
to exist there:

```powershell
$repo = 'C:\Users\micha\Desktop\github\weather'
Set-Location $repo
git fetch origin
$branch = 'origin/codex/workstation-does-the-cutoff-narrow-2026-09-71a'
$report = 'docs/roadmap/agent-report-2026-08-26-workstation-cutoff-direction.md'

git rev-parse $branch
git show "${branch}:$report"
git show "${branch}:docs/roadmap/high-so-far-cutoff-direction-2026-09-71a.sha256"
git show "${branch}:docs/roadmap/high-so-far-cutoff-direction-2026-09-71a-manifest.json"
git show "${branch}:tools/research/measure_high_so_far_population_09_70a.py"
git show "${branch}:tools/research/measure_high_so_far_population_09_70a_seed.json"
git diff --name-status origin/master...$branch
git diff --check origin/master...$branch
.\venv\Scripts\python.exe -m weather.operations.agent_docs_audit
powershell.exe -NoProfile -ExecutionPolicy Bypass -File `
  .\scripts\ops\roll_verdict.ps1 -Branch $branch
```

## Branch and roll verdict

Base: `73c2fd6d135800c586f33fb573176004a5b99557` (`origin/master`).

Branch: `codex/workstation-does-the-cutoff-narrow-2026-09-71a`.

Analysis artifact/script commit: `6cc14058`.

The authoritative per-file roll verdict will be recorded after the report commit, using
`scripts\ops\roll_verdict.ps1`; it is not hand-derived.

## Explicitly not done

- No alpha, candidate, fitting, parameter, C endpoint, endpoint comparison, score, accept rule,
  model selection, or performance claim was created. Decision 10 was untouched.
- No `high_so_far`, `cutoff_hour`, serving floor, collection, replay, scoring, feature, model,
  calibration, settlement, or production source was changed. The serving floor was not weakened.
- No production `data/`, tape, ledger, artifact, scheduled task, collector, supervisor, process,
  release, or trading state was written, registered, started, restarted, promoted, or activated.
- No provider or exchange endpoint was called. Nothing was installed.
- No PR, merge, master update, production checkout change, order, or trade was performed.
