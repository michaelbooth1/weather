# Agent report 2026-09-111e — make the signed replay exam executable

Handoff: `docs/roadmap/workstation-handoff-2026-09-111e-exam-executability.md` (branch
`codex/exam-fixes-handoffs-20260929`). Branch `codex/exam-executability-20260930`, based on
`origin/codex/integration-20260929` because integration PR #134 had not landed. Draft PR #144.

**Verdict: IMPLEMENTED on fixtures; all seven defects are fixed to the Clarification 2 draft. Whether the exam can run
on this host is NOT YET KNOWN. The `measure_ceilings` run on 2026-09-27 decides it, and the rule as drafted is likely
to report NOT EXECUTABLE on runtime or memory (see "What would falsify").** Eight points where the draft is ambiguous
are listed below. The tooling implements one stated reading of each. The owner should settle them before signing the
bytes; three of them (A1, A5, A8) decide whether the look can be spent by a refusal.

## What changed, per defect

1. **Manifest-only intervals.** `night` no longer takes `--exclude-utc` and writes no `active_intervals`. The neutral
   reader keeps its exact field set; `apply_manifest` stays the only interval source. The wrapper loses `-ExcludeUtc`.
2. **Calibration bundles and one directory per date.** `replay_export night` now exports every discovered city in one
   call into `<root>/<day>/bundle/`, which `pack_io.load_days` admits. `replay_export calibration` (calibration dates
   only, refused before any read otherwise) writes the same projection filtered to `descriptor`/`coverage`/`trade`,
   same sources, same hashing, into its own ledger. `calibrate()` accepts it.
3. **Nightly reliability.**
   - `ReleaseSources` writes its projection back into the event cache, so projection and providers are built once per
     event. The fixture test counts 1 build over 4 minutes; old code rebuilt both every book capture.
   - `ExportReader` pins each live plain file at its first-seen size. Appends with an unchanged prefix hash are
     accepted at recheck. Truncation, replacement or an edited prefix refuses.
   - A partial final line of a live file is skipped and counted (`unterminated_tail_skipped.<source>`).
   - The runner is pinned by its own hash plus the exporter's module-closure hash (`replay_export module-hash`); the
     Git-tip and clean-tree checks are removed.
4. **Ceilings.**
   - New `maker_core.replay.ceilings` implements the rule.
   - `measure_ceilings` writes only the six measured quantities plus per-pass event/decision/span counts.
   - The v2 manifest binds the measurement and its hash. The CLI byte/record/time ceilings, `ReplayConfig.max_events`,
     the new `max_outputs`, and a sampled process-memory ceiling are all derived from it.
   - If a host cap binds, the build refuses with `not_executable_on_host:<field>`. Nothing is sampled or truncated.
5. **Look protection.**
   - A scored run tracks its stage. Every check that needs no policy call runs before the reservation: output
     directory, host commit charge, input, manifest verification, scope, engine construction, and the action-boundary
     recheck.
   - The reservation (`attempts/<id>.json`) now sits immediately before the first policy replay.
   - A refusal before it writes a non-consuming `<id>.refusal-*.json` naming the stage. A stop after it writes
     `<id>.stopped.json`.
   - Manifest build/verify refusals after the owner decision verifies are recorded the same way.
   - `rehearse` runs the score-free full pipeline on calibration dates only.
   - A wrong-typed calibration JSON now refuses instead of crashing with `AttributeError`.
6. **Verifier.** `maker-replay-2026-10-15-v2` must bind `clarification_sha256` and `clarification_2_sha256`; a v2 row
   without the second hash refuses. v1 rows verify unchanged. All manifest/run commands take `--clarification-2`.
   Late look: a later Toronto date up to 2026-10-31 is admitted only when a non-consuming refusal was recorded on the
   scoring date and no attempt was consumed.
7. **Quote markets.** `quote_markets` writes the sorted cities of the three calibration bundles. A weather condition
   enters a bundle only with both token books captured (the descriptor requires them), so this is the captured-band
   inventory. `calibrate_hazard` and manifest build/verify refuse any other list.

The owning document `docs/operations/maker-replay-bundle.md` is updated (exporter, nightly/calibration bundles,
scheduled export, Clarification 2 section).

## Ambiguities in the draft (implemented reading → owner decision)

- **A1 "engine pass".** Implemented as the full scored pipeline on 09-27: both bounds, all four policies,
  matched-clock trials, bootstrap and report rendering. That is ~20+ engine passes. If a single pass were measured,
  runtime ×60 would under-bound the scored run by roughly the number of passes. The run would then hit `time_cap`
  after reservation and spend the look, which is the exact failure Clarification 2 exists to prevent.
- **A2 host cap values.** Implemented as:
  - peak memory and input bytes ≤ 70% × 16 GiB;
  - runtime ≤ 2,700 s;
  - counts ≤ 2^31;
  - "at most 70% commit" as a pre-reservation refusal when system commit is ≥ 70%.
- **A3 rounding unit.** Powers of two are taken in each ceiling's natural unit: bytes, records, seconds.
- **A4 decision/span ceiling.** The addendum's single `max_events` covers both events and decisions+spans. Separate
  ceilings need a new `ReplayConfig.max_outputs`, which the addendum says requires a prospective document.
  Clarification 2 should name it.
- **A5 report output ceiling.** It is not in the rule and stays 8 MiB. A `report_byte_cap` refusal can only happen
  after scoring, so it consumes the look. Recommend adding report bytes, measured by the rehearsal's rendering, to
  the rule's list.
- **A6 late-look trigger.** Implemented as any non-consuming refusal recorded on the scoring date (Toronto), from
  `run` or from `manifest build/verify`. The owner row's `expires_at` must then reach 2026-11-01.
- **A7 "operational".** Implemented as any refusal after authorization verifies and before reservation.
- **A8 fixed baseline ×60.** The interpreter's baseline memory is multiplied too, making the practical threshold a
  per-day peak of about 136 MiB, including Python and SciPy. The rehearsal records
  `peak_memory_before_input_bytes` so the owner can see the baseline share.

## What would falsify this mission

- The rule binds when the per-day full-pipeline runtime exceeds ~34.1 s (2,048 s is the largest power of two under
  2,700) or the per-day peak memory exceeds ~136 MiB (8 GiB is the largest power of two under 11.2 GiB).
- The only scale evidence is 111a's synthetic benchmark (11 markets, 60 simulated minutes: 23 s, ~640 MB working set,
  dry run, not the engine). It suggests a real all-city day will exceed both.
- If `measure_ceilings` reports `executable: false`, **the exam is not executable on this host as designed. That is
  the finding.** No rule is weakened here.

## Measured values

None on real data. All tests use synthetic fixtures. No production, panel, settlement, wallet or calibration data was
read. The fixture measurement ran inside the pytest process (1.6 GB peak), so its numbers mean nothing.

## Verification

- `tests/maker_core/test_replay_execution_pack.py`: 35 passed.
- `tests/market/test_maker_replay_night.py`: 27 passed.
- `tests/market/test_maker_replay_bundle.py`: 10 passed.
- `tests/operations/test_replay_bundle_export_scripts.py`: 11 passed.
- Audits (`test_import_architecture`, `test_module_size_audit`, `test_path_policy`, `test_schema_registry`,
  `test_agent_docs_audit`) and `agent_docs_audit`: pass.
- The five key regression tests (memo, prefix growth, pinned reads, two partial-tail cases) fail against the old
  code, as they should.
- Full suite: GitHub CI on PR #144.

## Per-file roll verdict (expected; derive with `roll_verdict.ps1`)

No capture loop imports `maker_core.replay`, `maker_plugin_capture`, `maker_replay_bundle/night/release` (repository
grep). Every changed file is expected **roll-free**: 12 source files under `src/maker_core/replay/` and
`src/weather/market/maker_*`, two `.ps1` files, one doc, four test files. No `schema_registry*` file changed.
Closure membership cannot be decided on the workstation; production must run
`scripts\ops\roll_verdict.ps1 -Branch codex/exam-executability-20260930`.

## What was NOT done

- No registration, Scheduler change, production write, restart, merge, venue call or credential use.
- No signed file was touched.
- No universe-JSON producer: the manifest still needs `--universe` (sorted rows of `condition_id`, `market_id`,
  `domain_id`, `target_date`, `local_timezone`) and no tool writes it. This is outside 111e's seven defects but blocks
  the 10-15 build. It needs a follow-up.
- The nightly budget was raised to 45 min (task limit PT50M; export defaults 4 GiB read, 2 GiB output) because a
  300 s all-city export is unlikely to finish. This is a reliability change beyond the handoff's literal list; review
  it. The 2 GiB child-memory ceiling is unchanged. The export receipt records its own peak memory so production can
  judge that ceiling.
- Dot-sourced admission helpers are no longer pinned by a tip. The runner hash and module hash are the only pins.

## Production commands

Run on the capture host in 00:30–09:00 under the shared lease, from a **new detached worktree at the pushed head**,
with a module-path probe, as in 111a. The production agent verifies local paths; this workstation has not seen them.

```powershell
$repo = (Resolve-Path .).Path
$sha = '<pushed head of codex/exam-executability-20260930>'
$wt = Join-Path $repo 'scratch\w\111e-exam'
git -C $repo fetch origin codex/exam-executability-20260930
git -C $repo worktree add --detach $wt $sha
$python = Join-Path $repo 'venv\Scripts\python.exe'
$env:PYTHONPATH = Join-Path $wt 'src'
$data = Join-Path $repo 'data'; $releases = Join-Path $repo 'artifacts\releases'
$cal = Join-Path $repo 'scratch\replay-calibration'; $measure = Join-Path $repo 'scratch\replay-measure'
. (Join-Path $repo 'scripts\ops\workload_admission.ps1')
$lease = Enter-WeatherHeavyWorkloadLease -RepoRoot $repo -Workload 'ReplayExam-111e'
if ($null -eq $lease) { throw 'not admitted' }
try {
  $mod = (& $python -B -P -m weather.market.maker_plugin.replay_export module-hash | ConvertFrom-Json).module_sha256
  # 1. Calibration export, 09-27..09-29 (one call each; a refused day is never retried into the same root).
  foreach ($d in '2026-09-27','2026-09-28','2026-09-29') {
    & $python -B -P -m weather.market.maker_plugin.replay_export calibration --day $d --data-root $data `
      --release-root $releases --out $cal --expected-module-sha256 $mod }
  # 2. Rule-derived quote markets, then the frozen hazard calibration.
  $cb = '2026-09-27','2026-09-28','2026-09-29' | ForEach-Object { '--calibration-bundle'; (Join-Path $cal "$_\bundle") }
  # Explicit host-cap reads (defaults are 64 MiB / 100k records); refusal, never truncation, if exceeded.
  $caps = '--max-input-bytes','12025908428','--max-records','2147483648','--max-seconds','2700'
  & $python -B -P -m maker_core.replay quote_markets @cb @caps --out (Join-Path $cal 'quote-markets.json')
  $b = $cb | ForEach-Object { $_ -replace '^--calibration-bundle$','--bundle' }
  & $python -B -P -m maker_core.replay calibrate_hazard @b @caps --quote-markets (Join-Path $cal 'quote-markets.json') `
    --out (Join-Path $cal 'calibration.json')
  # 3. Diagnostic ceiling measurement: panel-format export of 09-27 only, then the score-free pipeline.
  & $python -B -P -m weather.market.maker_plugin.replay_export night --day 2026-09-27 --data-root $data `
    --release-root $releases --out $measure --expected-module-sha256 $mod
  & $python -B -P -m maker_core.replay measure_ceilings --bundle (Join-Path $measure '2026-09-27\bundle') `
    --calibration (Join-Path $cal 'calibration.json') --out (Join-Path $cal 'ceiling-measurement.json')
} finally { Exit-WeatherHeavyWorkloadLease -Lease $lease }
```

`measure_ceilings` prints `executable_on_host=True|False`. **False ends the exam as designed on this host.** Report
it, and do not read panel bundles.

**Nightly panel export** (after adoption and review). First run `-WhatIf`, then register:

```powershell
& (Join-Path $repo 'scripts\ops\register_replay_bundle_export_nightly.ps1') -DataRoot $data -ReleaseRoot $releases `
  -OutputRoot (Join-Path $repo 'scratch\replay-panel') -ExpectedModuleSha256 $mod `
  -ExpectedRunnerSha256 (Get-FileHash (Join-Path $repo 'scripts\ops\replay_bundle_export_nightly.ps1')).Hash.ToLower() -WhatIf
```

Backfill any missed panel date manually with `replay_export night --day <date> --out <panel root>` under the lease.

**2026-10-15 (Toronto) look**, after the 10-14 bundle seals:

1. Append the owner-signed rows (REVOKE v1, APPROVE v2 with all four hashes, `expires_at` 2026-11-01T04:00:00Z).
2. Build, then verify:

   ```powershell
   $bind = @($cb) + @('--calibration', (Join-Path $cal 'calibration.json'), '--universe', '<universe.json>',
     '--quote-markets', (Join-Path $cal 'quote-markets.json'), '--ceiling-measurement', (Join-Path $cal 'ceiling-measurement.json'),
     '--decision-log', 'docs\operations\DECISION_LOG.md', '--frozen-protocol', 'docs\research\maker-replay-hurdles-preregistration-2026-09-27.md',
     '--execution-addendum', 'docs\research\maker-replay-execution-addendum-2026-09-27.md',
     '--clarification', 'docs\research\maker-replay-clarification-1-2026-09-27.md',
     '--clarification-2', 'docs\research\maker-replay-clarification-2-2026-09-29.md')
   $panel = (0..14 | ForEach-Object { '--bundle'; (Join-Path $repo ('scratch\replay-panel\' + (Get-Date '2026-09-30').AddDays($_).ToString('yyyy-MM-dd') + '\bundle')) })
   & $python -B -P -m maker_core.replay manifest build @panel @bind --owner-decision <row-source.json> --out <canonical>\manifest.json
   & $python -B -P -m maker_core.replay manifest verify @panel @bind --manifest <canonical>\manifest.json --manifest-sha256 <hash>
   ```

3. Enrol the hash in `approved_registrations.py` through the reviewed path.
4. Run the look:

   ```powershell
   & $python -B -P -m maker_core.replay run --compare --pre-registration <canonical>\manifest.json `
     --pre-registration-sha256 <hash> @panel @bind --out <new result dir>
   ```

   Do not pass ceiling flags; the manifest supplies them.
5. A refusal before reservation leaves `attempts\...refusal-*.json`. Fix the cause and rerun the same day, or on a
   later date up to 10-31.

## Open questions served

None recorded in `OPEN_QUESTIONS.md`. This serves the 111e handoff and the replay exam critical path.
