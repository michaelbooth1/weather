# Agent report 2026-10-03 — pull-opportunity cap precheck

**Verdict: YES, the bound can fail. At 88a-faithful density it holds with margin (D = 12, full-day windows: 206,640
candidates against `max_events` 1,048,576, ratio 0.197). It fails before the look (an operational,
non-consuming refusal at `engine_preflight`) in three cases: the day's union of captured bands is about 4x or more the
instantaneously selected universe (about 2.5x at the least favourable power-of-two rounding); the panel universe
outgrows the calibration universe by a similar factor; or a calibration day lacks per-band reward clocks (ratio 1.58
at D = 12). An unsigned [Clarification 4 draft](../research/maker-replay-clarification-4-draft.md) proposes
`engine_events = max(heap pops, opportunity candidates)`. The read-only `tools/exam_pull_cap_precheck.py` measures the
real ratio on production bundles; run it on the calibration bundles right after the ceiling rehearsal.**

Side finding, outside this question but larger: rehearsal cost scales as heap pops x conditions. One full-day
rehearsal at D = 12 took **373 s**, 68% of Clarification 2's ~546 s per-date budget. It peaked **2.57 GB above
baseline**, against the ~546 MiB budget. By the derive rule (2.57 GB x 15, then the next power of two, i.e. 64 GiB) that
alone is "not executable on this host", before the pull cap ever matters. See section 5; the production ceiling
rehearsal settles it.

Branch `codex/pull-cap-precheck-20261003`; exam tree read at `37092926386a0cac14371bf48382a1cb3079e442` by `git show` and
`git archive` into a scratch copy. No file in `execution_manifest.source_hashes()` changed. Reserved confirmation
window: NONE RESERVED (checked at run time); no dated evidence was read.

## 1. Which heap pops the rehearsal counts (traced at `37092926`)

- `engine.ReplayEngine.run` pops one distinct UTC clock per iteration (`processed += 1`). `schedule()` deduplicates
  through `pending`, so `processed` is the number of **distinct clocks** ever scheduled at or before `horizon`. It is
  not a record count.
- Clocks are scheduled in `__init__` for: each bundle's day start and next day start; every window start and end; and
  every record's `captured_at`. `ingest` schedules: descriptor close - 3 h (if within `end`); coverage `valid_until`;
  book `as_of + max_book_gap_seconds` (60 s); outcome-view `valid_until` (informed-v0 only, if within `end`); terms
  `as_of + 1 h + 1 µs` (if within `end`); and info-event boundaries (informed-v0 only). `blind_re1` adds session ends
  (`re1_counterfactual.tick`). `clock_only` adds its pull windows. Ticks, spans and trades schedule nothing else.
- `pack_cli.rehearse` runs `comparison_report` on `_maintenance(bundles)`, with `max_events = max_outputs = 2^31`, under
  `collect_stats`. That is 8 engine passes: 2 fill bounds x informed-v0, no_quote, blind_re1, clock_only. It records
  `engine_events = max(p["events"])`. `ceilings.derive` takes the largest date x 15, rounded up to the next power of
  two. `run_limits` turns that into `max_events`.
- The scored run sets `config.max_events` to that ceiling. `__main__` (`engine_preflight`, before reservation) refuses
  `pull_opportunity_cap` when `opportunity_candidates(ReplayEngine(bundles, config).windows) > config.max_events`.
  `pull_efficiency` repeats the same cap inside scoring. **The rehearsal never measures candidates**: its pull
  endpoint runs uncapped at 2^31.
- **What drives pops in real bundles** (`maker_replay_bundle.export` at the exam tree, with `maker_evidence_capture` and
  `maker_evidence_store`). 88a runs one cycle a minute. In it, `reward_record` journals one `rewards` row per selected
  condition, each at its own `captured_at`, even when the body is unchanged (`payload_ref`). The exporter turns each
  row into a `terms` record whose `as_of` is that clock. That gives 2 distinct clocks per selected band per minute:
  the record and its +1 h expiry. Books are fetched in batches of 100 tokens, so each cycle has ceil(2D/100) books
  rows. Each row projects book plus coverage for every condition with a descriptor, at the row's clock (+60 s and
  +30 s expiries). Each trade-stream row adds its clock and +30 s.
- **What drives candidates.** The exporter writes every condition with `active_from`/`active_until` spanning the full
  UTC day. A band therefore earns 1,260 candidate minutes per quote day, from 24 h minus 05:00–08:00 UTC, even if it
  was selected for only part of that day. So candidates follow the **daily union** of bands. Pops follow the
  **instantaneous** selected universe. 88a selects 10 per city, 12 cities, with at least 3 per DTE.

## 2. Pop counter validated against the real engine and rehearsal

`tools/research/pull_cap_precheck/measure.py --validate` replays fixtures through `ReplayEngine.run()`. It also runs
`pack_cli.rehearse()` on sealed files. Its pop counter is `run()` without ticks, spans and trades. "Reduced" density
keeps one record per (clock, schedule effect). All counts are exact matches:

| Fixture | Records (full / reduced) | Counter full | Counter reduced | `run()` processed |
| --- | --- | --- | --- | --- |
| 180 min, D = 12, churn 1, 300 trade rows | 10,608 / 3,348 | 5,469 | 5,469 | 5,469 |
| 120 min, D = 12, churn 2, 200 trade rows | 9,836 / 2,404 | 3,638 | 3,638 | 3,638 |
| 90 min, D = 40, churn 1.5, 100 trade rows | 18,220 / 4,605 | 7,628 | 7,628 | 7,628 |
| 40 min, D = 60, churn 1.5 (2 books batches) | 22,500 / 3,358 | 5,165 | 5,165 | 5,165 |

`pack_cli.rehearse` on the first fixture: `engine_events = 5,469`. The passes were informed-v0 5,469 (both bounds),
blind_re1 5,453, no_quote 5,452 and clock_only 5,452. **The informed-v0 pass is the maximum, and it equals the
counter.**

## 3. Measured: candidates vs rehearsed engine events (full-day fixtures)

Each scenario has three full calibration days at 88a density unless stated otherwise. `max_events` =
next_pow2(15 x largest pops). Candidates use the panel window rule: 14 quote days x D_union x 1,260 minutes, with the
settlement day and the 10-13 horizon-2 bands (target 10-15) excluded. They are counted by the exam tree's own
`opportunity_candidates(ReplayEngine(...).windows)`. "Churn" means D_union / D_inst. Ratio = candidates / max_events;
the preflight refuses above 1.

| D_inst | Churn (cal / panel) | Trade rows/day | Reward clocks | Largest pops/date | max_events | Candidates | Ratio | Unrounded | Preflight |
| --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: | --- |
| 12 | 1 / 1 | 0 | per band-minute | 38,281 | 1,048,576 | 206,640 | **0.197** | 0.360 | pass |
| 12 | 1 / 1 | 2,000 | per band-minute | 42,281 | 1,048,576 | 206,640 | 0.197 | 0.326 | pass |
| 12 | 2 / 2 | 0 | per band-minute | 38,333 | 1,048,576 | 413,280 | 0.394 | 0.719 | pass |
| 12 | 3 / 3 | 0 | per band-minute | 38,368 | 1,048,576 | 619,920 | 0.591 | 1.077 | pass |
| 12 | 4 / 4 | 0 | per band-minute | 38,389 | 1,048,576 | 826,560 | 0.788 | 1.435 | pass |
| 12 | 6 / 6 | 0 | per band-minute | 38,395 | 1,048,576 | 1,239,840 | **1.182** | 2.153 | **REFUSE** |
| 12 | 1 / 2 | 0 | per band-minute | 38,281 | 1,048,576 | 413,280 | 0.394 | 0.720 | pass |
| 12 | 1 / 1 | 0 | hourly | 5,006 | 131,072 | 206,640 | **1.577** | 2.752 | **REFUSE** |
| 12 | 1 / 1 | 2,000 | hourly | 9,005 | 262,144 | 206,640 | 0.788 | 1.530 | pass |
| 12 | 1 / 1 | 0 | none | 4,454 | 131,072 | 206,640 | **1.577** | 3.093 | **REFUSE** |
| 120 | 1 / 1 | 0 | per band-minute | 351,524 | 8,388,608 | 2,066,400 | 0.246 | 0.392 | pass |
| 120 | 1.5 / 1.5 | 2,000 | per band-minute | 355,574 | 8,388,608 | 3,099,600 | 0.370 | 0.581 | pass |
| 120 | 2 / 2 | 2,000 | per band-minute | 355,483 | 8,388,608 | 4,132,800 | 0.493 | 0.775 | pass |
| 120 | 3 / 3 | 2,000 | per band-minute | 355,459 | 8,388,608 | 6,199,200 | 0.739 | 1.163 | pass |
| 120 | 1.5 / 3 | 2,000 | per band-minute | 355,574 | 8,388,608 | 6,199,200 | 0.739 | 1.162 | pass |
| 120 | 1.5 / 4.5 | 2,000 | per band-minute | 355,574 | 8,388,608 | 9,298,800 | **1.109** | 1.743 | **REFUSE** |

**Headline (the requested D >= 12 full-day fixture):** candidates 206,640 against measured engine events of 38,281 per
date. That gives `max_events` 1,048,576 and a **ratio of 0.197**. The unrounded ratio is 0.360, and the per-date
quotient is 0.395 candidates per heap pop.

**Where it refuses.** Per date at 88a density, pops ≈ 2 x 1,440 x D_inst plus books, stream and view terms. So the
unrounded ratio is about 0.39 x D_union / D_inst. The preflight refuses once that crosses the power-of-two headroom:
churn above ~4.1 at D_inst = 120 and above ~5.1 at D_inst = 12 at these fixtures' rounding positions. At the least
favourable rounding (15 x pops just above a power of two), the threshold falls to ~2.5-2.8. Without per-band reward clocks,
pops per date drop to ~1,440 x 3. The ratio then rises with D_union alone, and refuses already at D = 12.

Not measured here: the real calibration days' D_union, churn and trade-row counts. The workstation has no production
data. The precheck tool measures them on production (section 4).

## 4. The read-only precheck tool

`tools/exam_pull_cap_precheck.py` (fixture tests: `tests/maker_core/test_exam_pull_cap_precheck.py`). It reads only each
bundle's `bundle.json`; record streams are never opened. It applies the manifest window rule: 05:00–08:00 UTC removed,
nothing on the settlement date, and nothing for targets after it when `--universe` is given. Without `--universe` it
reports an upper bound. It counts minute starts and recounts with the pinned tree's own
`opportunity_candidates(ReplayEngine(...).windows)`, refusing any disagreement. It reads the ceiling from
`derive_ceilings` output (re-derived by the exam rule), from the rehearsal JSONs, or from `--max-events`. It prints JSON
plus `candidates=… max_events=… ratio=… verdict=…`. Exit 0 means the preflight would pass, 3 that it would refuse, 2
that input was refused or the exam tree is missing from PYTHONPATH.

Production, first with the calibration projection (no panel export needed), then on the full panel:

```powershell
$env:PYTHONPATH = "C:\Users\<user>\Documents\github\weather-exam-deployed-<pin>\src"
.\venv\Scripts\python.exe tools\exam_pull_cap_precheck.py `
  --calibration-bundle <calibration root>\2026-09-27\bundle --calibration-bundle <calibration root>\2026-09-28\bundle `
  --calibration-bundle <calibration root>\2026-09-29\bundle `
  --rehearsal <exam root>\rehearsal-2026-09-27.json --rehearsal <exam root>\rehearsal-2026-09-28.json `
  --rehearsal <exam root>\rehearsal-2026-09-29.json
.\venv\Scripts\python.exe tools\exam_pull_cap_precheck.py --bundle <panel root>\2026-09-30\bundle `
  <...one --bundle per quote date...> --bundle <panel root>\2026-10-14\bundle `
  --universe <exam root>\universe.json --ceiling-measurement <exam root>\ceiling_measurement.json
```

The projection uses 14 x the busiest calibration date's candidates. It also prints `candidates_per_heap_pop` for each
date: the real churn signal. A projection near or above 1 is the signal to stop before panel exports. The tool is read
only and light. It is still a tool run on the capture host, so run it outside the graded window.

## 5. Side finding: rehearsal runtime scales with pops x conditions

`run()` ticks every condition at every pop, and appends a span for every active condition per pop. Measured
`run()` times on the validation fixtures: 6.3 s for 5,469 pops x 12 conditions, and 31 s for 7,628 pops x 60
conditions. That is about 70–100 µs per condition-tick per pass, and the rehearsal makes 8 passes plus report rendering.
One sealed full-day rehearsal at D = 12 (churn 1, 2,000 trade rows; `pack_cli.rehearse` on files written by `seal`)
measured these values:

| Quantity | Measured | x 15 -> next power of two | Clarification 2 host limit |
| --- | ---: | ---: | --- |
| records | 79,508 | 2,097,152 | 2^31 |
| engine_events | 42,281 (identical to the reduced counter's grid row) | 1,048,576 | 2^31 |
| decisions_spans | 884,952 | 16,777,216 | 2^31 |
| runtime_seconds | 373.0 | 8,192 | 14,400 (fits, barely: 546 s per date) |
| report_bytes | 225,628,370 | 4 GiB | 70% of 16 GiB |
| peak_memory_above_baseline | 2,566,868,992 | **64 GiB** | **binds** (~546 MiB per date allowed) |

The baseline (1.76 GB) is inflated here because the fixture was generated in the same process. The peak above baseline
is the pipeline's own. The fixture is synthetic, with one-level books and invented prices, so real days may differ in
both directions. Projected from
the per-tick cost, a D_inst = 120, churn 1.5 date would need roughly 355,000 pops x 180 conditions x 8 passes. That is
hours per date and tens of millions of spans per pass, far past Clarification 2's ~546 s and ~546 MiB per-date budgets.
The D = 120 projection is not measured. The D = 12 memory figure already binds. If production matches it,
`derive_ceilings` reports "not executable on this host" before the pull cap ever matters. The production rehearsal (critical path step 1) measures it directly.

## 6. Per-file roll verdict

| File | Closures entered |
| --- | --- |
| `tools/exam_pull_cap_precheck.py` | none (not under `src/`; never imported by a capture loop) |
| `tools/research/pull_cap_precheck/fixture.py`, `measure.py` | none (research scripts) |
| `tests/maker_core/test_exam_pull_cap_precheck.py` | none (tests) |
| `docs/roadmap/agent-report-2026-10-03-pull-cap-precheck.md`, `docs/research/maker-replay-clarification-4-draft.md`, `docs/roadmap/correspondence-index.md` | none (docs: roll-free) |

The branch is roll-free. `execution_manifest.source_hashes()` is unchanged: nothing under `src/maker_core`,
`src/weather/market/maker_plugin*`, `maker_replay_bundle.py` or `pyproject.toml` changed. Confirm with
`scripts\ops\roll_verdict.ps1 -Branch codex/pull-cap-precheck-20261003`.

## 7. What was NOT done

No production data, credentials, `.env` or venue calls were used. No registration, Scheduler change, restart, merge or
order. No code change to the exam tree, no rehearsal or export on production, and no signature. The Clarification 4
draft is unsigned and proposes no code. Real-bundle churn and trade density are unmeasured. The rehearsal-runtime
projection in section 5 beyond D = 12 is an extrapolation.

## 8. Reproduce (workstation, or the capture host only inside its admitted window)

```powershell
# Exam tree on PYTHONPATH (pinned worktree, or `git archive 37092926 src` into a scratch folder).
$env:PYTHONPATH = "<pinned exam worktree>\src"
.\venv\Scripts\python.exe tools\research\pull_cap_precheck\measure.py --validate <new empty scratch folder>
.\venv\Scripts\python.exe tools\research\pull_cap_precheck\measure.py --grid
.\venv\Scripts\python.exe -m pytest tests\maker_core\test_exam_pull_cap_precheck.py -q
```

The exam-backed recount test is skipped when this worktree's own `src` (without `maker_core.replay`) comes first on the
path, as in CI. It runs, together with the exam's `test_replay_pull_efficiency.py` (24 passed), when the tool and test
are copied into the exam tree.

Commit: see the PR head on `codex/pull-cap-precheck-20261003`.
