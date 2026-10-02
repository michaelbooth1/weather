# Agent report 2026-10 — 111e follow-up: signed Clarification 2 implemented

**Verdict: IMPLEMENTED on fixtures, with no rule weakened. Every operational rule in the signed Clarification 2 that
#144 did not yet cover now exists in code with tests, and the verifier binds the second clarification as
`maker-replay-2026-10-15-v2`. #134's correspondence-index conflict is resynced. No rule was found unimplementable. One
instruction could not be followed literally: `resync_branch.ps1` does not exist in this repository or its history, so
the resync used its documented equivalent (below). Five execution risks are listed under "Risks", none resolved by
judgment. The most time-critical is risk 5: the panel export backlog must be cleared before 10-15.**

Signed text: `docs/research/maker-replay-clarification-2-2026-09-29.md`, bytes at `a8c0b846b`, raw SHA-256
`1719fd1ea679cd14501d5b6ddd392fbb9e8d2b086cf6b5a3c0348961824e60f0` (DECISION_LOG 2026-10-01). #144 had been aligned
to draft `794656c20`. The signed bytes differ from that draft in four places, and all four are implemented here. This
branch adds the signed file unchanged, byte for byte from `a8c0b846b`; a test pins its hash. The three signed 09-27
files are unchanged (carried by #134 with hashes `0380212d…`, `074a0e56…`, `37d2fd8e…`).

## Rules implemented

| Signed rule | Before (draft 794656c20) | Now | Where |
| --- | --- | --- | --- |
| Ceilings = largest calibration date × 15, rounded up to the next power of two | × 15 × 2, then power of two | × 15, then power of two; the rounding is the only headroom | `ceilings.py` (`MULTIPLIER = 15`, `RULE`, measurement format `v3`) |
| A derived ceiling above its host limit → "not executable on this host"; never sample or truncate | `executable: false`, `not_executable_on_host:<field>` | Same, plus `verdict: "not executable on this host"` in the measurement; `derive_ceilings` prints the verdict and exits 3; `run_limits` refusal names it | `ceilings.derive`, `ceilings.run_limits`, `pack_cli.execute` |
| Per-date allowance ~546 s and ~546 MiB above baseline | (implied ~273 s / 273 MiB under × 30) | 546 → 8,190 → 8,192 s fits under 4 h; 547 → 16,384 does not. Same for MiB against 70% of 16 GiB plus baseline | `test_per_date_allowance_is_about_546_seconds_and_546_mib` |
| Late look: any America/Toronto date 10-15..10-31 while no attempt is reserved; a reservation consumes the look whatever the date | Only after a non-consuming refusal recorded on 10-15 | `late_look_permitted` is true exactly while `attempts/<id>.json` does not exist; refusal records no longer gate it. `LATE_LOOK_UNTIL` stays 10-31 | `execution_receipt.late_look_permitted`, `authorization.scoring_date_allowed` |
| Manifest built, verified and enrolled on or after 2026-10-15 Toronto | Not enforced by the CLI | `manifest build` and `manifest verify` refuse before the Toronto scoring date (`manifest_before_scoring_date_toronto`), before any panel read and without a refusal record | `pack_cli.execute` |
| Runs that never reach a recorded refusal consume nothing; only the reservation consumes | Already true in #144 | Unchanged; now also covered by the late-look test (a 10-17 look with no prior record) | — |
| k = 0.3 and k = 0.5 lower-bound flag (strictly_through, both baselines); `hurdles_met_not_positive_at_measured_k` when REPLAY_HURDLES_MET with a non-positive k = 0.3 lower bound; changes no status | k = 0.3 rows and intervals reported, no flag or label | `registered_decision.measured_k_sensitivity` (two booleans plus per-cell status and lower bound), `registered_decision.label`. Status, hurdle flags and reasons are computed exactly as before. Rendered in the Markdown report and kept in the completed receipt | `execution_receipt.measured_k_sensitivity`, `evaluate_hurdles`, `report.report_bytes` |
| Authorization: v2 binds registration, addendum, Clarification 1 and Clarification 2; row expires 2026-11-01 | v2 required the two clarification fields and checked them against the supplied bytes | Additionally pins the four signed hashes, scoring date 2026-10-15 and `expires_at` ≤ `2026-11-01T04:00:00Z` (00:00 Toronto) for v2. A row with any other hash, date or later expiry refuses even if its bytes agree with it. v1 rows verify unchanged | `authorization.SIGNED_BINDINGS`, `EXPIRES_NO_LATER_THAN` |

Two interpretation choices, both fail-closed and neither weakening a rule:

- **Flag scope.** "Lower bounds … (strictly_through, both baselines)" is read as both economic baselines (`blind_re1`,
  `no_quote`) × both registered clusters (`date`, `date_x_market`). That is the same cell set the economic hurdle reads.
  A missing or non-OK estimate counts as not positive, so the label fires on any REPLAY_HURDLES_MET without four
  positive k = 0.3 bounds. The flag never adds a reason or changes a status. A test proves that removing every
  k = 0.3 contrast leaves status, hurdle flags and reasons identical.
- **Expiry instant.** "Expires 2026-11-01" uses the v1 convention: 04:00Z is 00:00 America/Toronto (EDT still applies;
  DST ends 02:00 that day). An earlier `expires_at` is accepted; a later one refuses.

## Tests (fixtures built with the production writers)

The fixture now copies the four signed documents' exact bytes, because v2 pins their hashes.
`tests/maker_core/test_replay_execution_pack.py` adds or changes:

- **v2 binding.** `test_v1_rows_still_verify_and_v2_requires_clarification_2`:
  - a v1 row still verifies;
  - a v2 row missing `clarification_2_sha256` refuses (`invalid_owner_decision`);
  - a v2 row whose Clarification 2 hash matches its own supplied bytes but not the signed hash refuses
    (`signed_binding_mismatch:clarification_2_sha256`);
  - another scoring date refuses, and so does a later expiry;
  - tampered bytes refuse; revoking v1 leaves v2 valid; revoking v2 refuses.
- **Pinned hashes.** `test_signed_documents_on_disk_match_the_pinned_v2_hashes` checks the pins against the files in
  `docs/research/`.
- **Late look.**
  - `test_late_look_runs_on_any_permitted_date_while_unreserved`: with no prior record, a 10-17 look reserves and is
    consumed. Afterwards 10-15 and 10-20 refuse, and write nothing new.
  - `test_late_look_window_is_toronto_10_15_to_10_31_and_v2_only`: 10-14, 11-01, a reserved attempt and v1 later dates
    are all refused.
- **Manifest timing.** `test_manifest_cli_refuses_before_the_toronto_scoring_date`, for build and verify: 10-14 23:59
  Toronto refuses and writes nothing; 10-15 00:00 passes.
- **Ceilings.** These tests reflect the new rule:
  - `test_ceilings_follow_the_rule_and_bind_engine_and_cli`;
  - `test_binding_host_limit_is_not_executable_never_truncated`, with the new verdict;
  - `test_per_date_allowance_is_about_546_seconds_and_546_mib`;
  - `test_derive_ceilings_cli_reports_not_executable_and_exits_nonzero`.
- **k = 0.3 label.**
  - `test_measured_k_label_is_reported_beside_an_unchanged_status`: the label fires at k = 0.3 bounds of 0 and −1. A
    negative bound on `clock_only` or `at_price` does not trigger it. A missing estimate counts as not positive. The
    label never appears on a non-MET status.
  - `test_completed_look_carries_the_measured_k_flag_in_report_and_receipt`: a full scored v2 look via the CLI writes
    the flag into `report.json`, the Markdown and `.completed.json`.
- `tests/maker_core/test_replay_report.py::test_k03_measured_reaction_sensitivity_is_reported_never_decisive` now
  compares status, hurdle flags and reasons rather than the whole decision, since the decision now carries the flag.

Run under `scripts\ops\workstation_heavy.ps1` (workstation, `--basetemp C:\tmp\bt111e`, deleted after):
`tests/maker_core` plus both exporter suites and `test_replay_bundle_export_scripts.py`, plus the repo-wide audits:
schema registry, import architecture, agent docs, path policy, module size, release import boundary and
correspondence index. Result: 1,003 passed, 1 skipped, 5 xfailed. The one failure was the correspondence index,
stale until this report's commit, and it was regenerated after. The full suite is the PR's GitHub CI.

## Resync of #134 (correspondence index)

There is no `scripts/ops/resync_branch.ps1` on `origin/master`, on any remote or local branch, or in history
(`git log --all -S resync_branch` is empty). The documented equivalent was used. On `codex/integration-20260929`:

1. merge `origin/master` (`819f8148`); the only conflict was `docs/roadmap/correspondence-index.md`;
2. regenerate the index with `python -m weather.reporting.roadmap.correspondence_index` and commit (`994d15d0`);
3. regenerate after that commit (`77d0196b`); `--check` then reports OK.

Pushed as a fast-forward to `codex/integration-20260929`. The plugin head was **not** merged into #134. #144
(`codex/exam-executability-20260930`) then merged the resynced #134 the same way. If a resync script was meant to
exist, it is a missing tool, not a step skipped.

## Risks the signed text leaves open (not resolved by judgment)

1. **Input and record ceilings vs. calibration bundles.** The rehearsal measures one panel-format calibration date.
   The scored run and the manifest build load 15 panel days **plus** the three calibration bundles under the same
   `max_input_bytes` and `max_records`. Power-of-two rounding usually gives room. If the 15× figure lands just under a
   power of two, the build refuses `manifest_input_ceiling`. That is an operational refusal before any score, and the
   exam would then not be executable as signed. Nothing is truncated to fit.
2. **Linear memory.** × 15 assumes peak memory grows with the number of days. The memory guard refuses rather than
   swaps, but before reservation that refusal does not consume the look; after it, it does (look protection as signed).
3. **Reservation scope.** The reservation lives in `attempts/` beside the manifest. A relocated manifest copy would not
   see it; the canonical-directory rule in `maker-replay-bundle.md` remains the control.
4. **Source data age.** Calibration exports read 88a segments from 09-27..29. Those segments must still be sealed and
   readable after the 91a cold-snapshot nightly; gzip is supported by the reader. Verify the receipts say `SEALED`.
5. **Panel export backlog.** The panel nightly is not registered on master. Every panel day from 2026-09-30 to the
   registration date must be exported by hand with `night`, before 10-15. Each run can take up to the 2,700 s default,
   inside the 00:30–09:00 lease window and beside the 91a nightly. Spread the backlog across nights now; a panel day
   that cannot be exported `SEALED` blocks the build (the manifest requires all fifteen days).

## Production runbook (exact commands)

**Revised 2026-10-03 (W2).** This section supersedes the earlier helper and the attended form in the 2026-10-01
addendum §3. Every Python step runs from one locked, pinned worktree with `-P -B`, `PYTHONPATH=<worktree>\src` and a
`__file__` probe. The look runs on v3 (Clarification 3, signed 2026-10-01T17:44Z).

Preconditions: the exam tree is landed on production master via the guarded path, and production derives each
branch's roll verdict with `scripts\ops\roll_verdict.ps1 -Branch <b>`. Every heavy step runs 00:30–09:00 Toronto under
the shared lease, serially, and never on a night with a 00:30 integration suite unless the nightly is staggered
(STATE_OF_PLAY).

### Session setup (capture host, once per PowerShell session)

`$Data` and `$Releases` are the 88a data root and the immutable release root. `$Pin` is the exam-tree commit that will
be enrolled; it is replaced by the enrolment commit in step C4.

```powershell
$Repo = '<production repo root>'; $Py = Join-Path $Repo 'venv\Scripts\python.exe'
$Data = '<-DataRoot>'; $Releases = '<-ReleaseRoot>'
$Pin = '<exam tree commit on master>'
$Wt = "C:\weather-pinned\exam-$($Pin.Substring(0,8))"
git -C $Repo worktree add --detach $Wt $Pin
git -C $Repo worktree lock $Wt --reason 'maker replay exam (W2 runbook)'
$Src = Join-Path $Wt 'src'
$Exam = '<exam root: outside $Data, never inside a repository>'
New-Item -ItemType Directory -Path $Exam | Out-Null
# Signed documents come from the locked worktree; only the decision log is read from master.
$Docs = @('--decision-log', "$Repo\docs\operations\DECISION_LOG.md",
  '--frozen-protocol', "$Wt\docs\research\maker-replay-hurdles-preregistration-2026-09-27.md",
  '--execution-addendum', "$Wt\docs\research\maker-replay-execution-addendum-2026-09-27.md",
  '--clarification', "$Wt\docs\research\maker-replay-clarification-1-2026-09-27.md",
  '--clarification-2', "$Wt\docs\research\maker-replay-clarification-2-2026-09-29.md",
  '--clarification-3', "$Wt\docs\research\maker-replay-clarification-3-2026-10-01.md")
# Lease and job helpers stay dot-sourced from production master; only Python code comes from the worktree.
. "$Repo\scripts\ops\workload_admission.ps1"; . "$Repo\scripts\ops\windows_kill_on_close_job.ps1"
function Assert-PinnedImports {
  $probe = & $Py -P -B -c "import weather.market.maker_replay_night as n, maker_core.replay.ceilings as c, maker_core.replay.approved_registrations as a; print(n.__file__); print(c.__file__); print(a.__file__)"
  if ($LASTEXITCODE -ne 0 -or @($probe).Count -ne 3 -or @($probe | Where-Object { -not $_.StartsWith($Src + '\') }).Count) {
    throw "module-path probe failed: $probe" }
}
function Invoke-ExamStep([string]$Name, [string[]]$Tokens) {
  $env:PYTHONPATH = $Src
  try {
    Assert-PinnedImports                                   # immediately before every step
    $lease = Enter-WeatherHeavyWorkloadLease -RepoRoot $Repo -Workload "maker_replay_exam_$Name" `
      -ExpectedExecutionHostId (Get-WeatherExecutionHostId)
    if ($null -eq $lease) { throw 'REFUSED: shared heavy-work lease busy' }
    $job = $null; $child = $null; $proved = $false
    try {
      $job = New-WeatherKillOnCloseJob
      $child = Start-WeatherInteractiveProcessInJob -Job $job -FilePath $Py -WorkingDirectory $Repo `
        -ArgumentString (ConvertTo-WeatherWindowsArgumentString -Tokens (@('-P','-B') + $Tokens))
      $null = $child.Handle; $child.WaitForExit(); $code = $child.ExitCode
    } finally {
      try { if ($job) { $job.TerminateAndWait(5000) }; $proved = $true }
      finally { if ($child) { $child.Dispose() }; if ($job) { $job.Dispose() }
        if ($proved) { Exit-WeatherHeavyWorkloadLease -Lease $lease } else { Set-WeatherHeavyWorkloadLeasePoisoned -Lease $lease } }
    }
  } finally { Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue }
  if ($code -ne 0) { throw "$Name exited $code" }
}
function Read-Json([string]$Path) { Get-Content $Path -Raw | ConvertFrom-Json }
$Cal = '2026-09-27', '2026-09-28', '2026-09-29'
# Export ceilings: 16 GiB streamed input (the exporter's MAX_INPUT_BYTES), 11,000 s (inside the 4 h host limit with
# room for teardown) and an explicit 2 GiB output. Peak memory is about 6x the events.jsonl bytes
# (docs/operations/maker-replay-bundle.md), so 2 GiB of output is already near the 16 GB host's limit.
$ExportLim = @('--max-input-bytes','17179869184','--max-seconds','11000','--max-output-bytes','2147483648')
$env:PYTHONPATH = $Src; Assert-PinnedImports
$Mod = ((& $Py -P -B -m weather.market.maker_plugin.replay_export module-hash) | ConvertFrom-Json).module_sha256
Remove-Item Env:PYTHONPATH
```

**A fresh `--out` root per attempt.** An attempted day refuses in place, and a refused day is never retried there.
Each export attempt therefore gets a new root, and the roots that are used are recorded:

```powershell
function New-AttemptRoot([string]$Kind) {
  $root = Join-Path $Exam ("$Kind-" + (Get-Date).ToUniversalTime().ToString('yyyyMMddTHHmmssZ'))
  New-Item -ItemType Directory -Path $root | Out-Null; $root
}
```

### A. Calibration and rehearsal-panel export (09-27..29)

```powershell
$CalRoot = New-AttemptRoot 'calibration'; $RehRoot = New-AttemptRoot 'rehearsal-panel'
foreach ($d in $Cal) { Invoke-ExamStep "calibration_$d" (@('-m','weather.market.maker_plugin.replay_export','calibration',
  '--day',$d,'--data-root',$Data,'--out',$CalRoot,'--expected-module-sha256',$Mod) + $ExportLim) }
foreach ($d in $Cal) { Invoke-ExamStep "rehearsal_panel_$d" (@('-m','weather.market.maker_plugin.replay_export','night',
  '--day',$d,'--data-root',$Data,'--release-root',$Releases,'--out',$RehRoot,'--expected-module-sha256',$Mod) + $ExportLim) }
foreach ($r in @($CalRoot, $RehRoot)) { foreach ($d in $Cal) {
  $x = Read-Json "$r\$d\receipt.json"
  if ($x.status -ne 'SEALED' -or $x.module_sha256 -ne $Mod) { throw "$r $d not SEALED under the pinned module hash" }
  if ($x.PSObject.Properties.Name -contains 'events_trimmed') { "$r $d event lists trimmed: " + ($x.events_trimmed | ConvertTo-Json -Compress) }
  "$r $d leading_capture=$($x.bundle.trade_clock_skew.leading_capture) max_us=$($x.bundle.trade_clock_skew.max_us) peak=$($x.peak_memory_bytes) bytes=$($x.bundle.bytes)" } }
```

Any `REFUSED` receipt, including `MemoryError` (now recorded, not left stuck), stops the line. Fix the cause, and only
then export again into a new attempt root, never in place.

### B. Quote markets, hazard calibration, ceiling rehearsal

Size the replay read limits from the calibration receipts. The CLI defaults are diagnostic values, not exam values.

```powershell
$r = $Cal | ForEach-Object { (Read-Json "$CalRoot\$_\receipt.json").bundle }
$Bytes = [string](($r | Measure-Object bytes -Sum).Sum); $Recs = [string](($r | Measure-Object records -Sum).Sum)
$CalB = $Cal | ForEach-Object { '--calibration-bundle', "$CalRoot\$_\bundle" }
$Lim = @('--max-input-bytes',$Bytes,'--max-records',$Recs,'--max-seconds','2700','--max-output-bytes','8388608')
Invoke-ExamStep 'quote_markets' (@('-m','maker_core.replay','quote_markets') + $CalB + @('--out',"$Exam\quote-markets.json") + $Lim)
Invoke-ExamStep 'calibrate' (@('-m','maker_core.replay','calibrate_hazard') + ($Cal | ForEach-Object { '--bundle', "$CalRoot\$_\bundle" }) +
  @('--quote-markets',"$Exam\quote-markets.json",'--out',"$Exam\calibration.json") + $Lim)
$c = Read-Json "$Exam\calibration.json"
if ($null -ne $c.global_fallback) { throw "calibration global_fallback=$($c.global_fallback)" }
if ($c.PSObject.Properties.Name -contains 'binding_status') { throw "calibration binding_status=$($c.binding_status)" }
foreach ($d in $Cal) { Invoke-ExamStep "rehearse_$d" @('-m','maker_core.replay','rehearse','--bundle',"$RehRoot\$d\bundle",
  '--calibration',"$Exam\calibration.json",'--out',"$Exam\rehearsal-$d.json") }      # one fresh process per date
$env:PYTHONPATH = $Src; Assert-PinnedImports
& $Py -P -B -m maker_core.replay derive_ceilings --rehearsal "$Exam\rehearsal-2026-09-27.json" `
  --rehearsal "$Exam\rehearsal-2026-09-28.json" --rehearsal "$Exam\rehearsal-2026-09-29.json" --out "$Exam\ceiling-measurement.json"
$Derive = $LASTEXITCODE; Remove-Item Env:PYTHONPATH
$CalKey = (Get-FileHash "$Exam\calibration.json" -Algorithm SHA256).Hash.ToLowerInvariant()
if ((Read-Json "$Exam\ceiling-measurement.json").calibration_sha256 -ne $CalKey) { throw 'ceilings rehearsed on another calibration' }
```

`derive_ceilings` is light: it reads three small JSON files. Exit 0 (`executable_on_host=True`) lets the line continue.
**Exit 3 (`not executable on this host`, `binding=<fields>`) ends the exam on this host as signed.** Report it. Do not
re-rehearse to make it fit, and never sample or truncate. Manifest build also refuses a measurement whose
`calibration_sha256` is not the sealed `calibration.json` (`ceiling_measurement_calibration_mismatch`).

### C. Authorization, build, verify, enrolment, look

1. **Authorization rows (production, any day before the look).** Append an APPROVE row for v3 to `DECISION_LOG.md`.
   The look is single: if a v2 APPROVE row exists, the owner decides whether to append a v2 REVOKE row with it. Only
   the one enrolled manifest can run in any case.
   `| <date> | APPROVE_MAKER_REPLAY | offline replay only | `<json>` | — |`, where `<json>` is:

   `{"authorization_id":"maker-replay-2026-10-15-v3","owner":"michaelbooth1","protocol_sha256":"0380212d8e82474281afbed1197161263f794570ec06cf51fec99a3c6c03a6bf","addendum_sha256":"074a0e56b87770eff9f574232819b5d95ecd7073e450f27adac7bf555a43410b","clarification_sha256":"37d2fd8e34462a77d6209ee4018e3685bf91a81a93e2cb08df6986985811fa0e","clarification_2_sha256":"1719fd1ea679cd14501d5b6ddd392fbb9e8d2b086cf6b5a3c0348961824e60f0","clarification_3_sha256":"fcbcb7d0d2a38777814b6f9d5e8b96c879d069af873c0b32fb4b274506b03eaa","signed_at":"<UTC approval time>","scoring_date":"2026-10-15","expires_at":"2026-11-01T04:00:00Z"}`

   The Date column must equal the UTC date of `signed_at`. Save the exact JSON as `$Exam\owner-decision.json`
   (UTF-8, no BOM). The v3 key set is the decision fields plus all three clarification hashes; any other set refuses.
2. **Panel completeness (10-15, after the 10-14 UTC day closes).** Export all fifteen days 2026-09-30..2026-10-14
   from the same `$Mod` into one new attempt root, with `$ExportLim`. Each `receipt.json` must be `SEALED` with
   `module_sha256 == $Mod`. A refused day means a new root for the whole panel; roots are never mixed.

   ```powershell
   $PanelRoot = New-AttemptRoot 'panel'
   $Days = 0..14 | ForEach-Object { ([datetime]'2026-09-30').AddDays($_).ToString('yyyy-MM-dd') }
   foreach ($d in $Days) { Invoke-ExamStep "panel_$d" (@('-m','weather.market.maker_plugin.replay_export','night','--day',$d,
     '--data-root',$Data,'--release-root',$Releases,'--out',$PanelRoot,'--expected-module-sha256',$Mod) + $ExportLim) }
   foreach ($d in $Days) { $x = Read-Json "$PanelRoot\$d\receipt.json"
     if ($x.status -ne 'SEALED' -or $x.module_sha256 -ne $Mod) { throw "panel $d not SEALED under the pinned module hash" } }
   ```
3. **Universe, build, verify (00:30–09:00).**

   ```powershell
   $PanB = $Days | ForEach-Object { '--bundle', "$PanelRoot\$_\bundle" }
   $Bind = $CalB + @('--calibration',"$Exam\calibration.json",'--universe',"$Exam\universe.json",
     '--quote-markets',"$Exam\quote-markets.json",'--ceiling-measurement',"$Exam\ceiling-measurement.json") + $Docs
   New-Item -ItemType Directory -Path "$Exam\manifest" | Out-Null      # canonical directory; never relocate
   Invoke-ExamStep 'universe' (@('-m','weather.market.maker_plugin.replay_export','universe') + $PanB + @('--out',"$Exam\universe.json"))
   Invoke-ExamStep 'manifest_build' (@('-m','maker_core.replay','manifest','build') + $PanB + $Bind +
     @('--owner-decision',"$Exam\owner-decision.json",'--out',"$Exam\manifest\manifest.json"))
   $Key = (Get-FileHash "$Exam\manifest\manifest.json" -Algorithm SHA256).Hash.ToLowerInvariant()
   Invoke-ExamStep 'manifest_verify' (@('-m','maker_core.replay','manifest','verify') + $PanB + $Bind +
     @('--manifest',"$Exam\manifest\manifest.json",'--manifest-sha256',$Key))   # requires VERIFIED_PREFLIGHT_ONLY
   ```
4. **Enrolment round, between build and look.** This follows `docs/research/maker-replay-enrollment-template-2026-09-27.md`
   steps 4–6 for v3:
   1. On a topic branch from master, add exactly `$Key` → `michaelbooth1` to
      `src/maker_core/replay/approved_registrations.py`. Nothing else changes.
   2. Get independent review of that diff.
   3. Get the roll verdict with `scripts\ops\roll_verdict.ps1 -Branch <topic>`, and land the branch by the path that
      verdict names.
   4. **Re-pin.** Set `$Pin` to the landed commit, then create and lock a new worktree for it with the session-setup
      commands. The probe now includes `approved_registrations.py`, so a stale pin fails it.
      `approved_registrations.py` is the only file excluded from `source_hashes()`, so the manifest still binds.
   5. Run a **second** `manifest_verify` from the new pin. It must print `VERIFIED_PREFLIGHT_ONLY`; any other result
      stops the look.
5. **Pre-look checks (the same session, immediately before the look).** The look's own preflights refuse
   non-consumingly on commit charge and on the window. These checks catch the ceilings whose overrun after
   reservation **consumes** the look:

   ```powershell
   $m = Read-Json "$Exam\manifest\manifest.json"; $cl = $m.ceilings
   $now = [TimeZoneInfo]::ConvertTimeBySystemTimeZoneId([DateTime]::UtcNow, 'Eastern Standard Time')
   if ($now.TimeOfDay -lt [TimeSpan]'00:30:00' -or $now.AddSeconds($cl.max_seconds).Date -ne $now.Date -or
       $now.AddSeconds($cl.max_seconds).TimeOfDay -gt [TimeSpan]'09:00:00') { throw "max_seconds=$($cl.max_seconds) does not fit before 09:00" }
   $free = (Get-CimInstance Win32_OperatingSystem).FreePhysicalMemory * 1024
   if ($free -lt $cl.max_memory_bytes) { throw "available RAM $free < memory ceiling $($cl.max_memory_bytes)" }
   if ((Get-PSDrive (Split-Path -Qualifier $Exam).TrimEnd(':')).Free -lt 2 * $cl.max_output_bytes) { throw 'disk below 2x report cap' }
   if (Test-Path "$Exam\manifest\attempts\maker-replay-2026-10-15-v3.json") { throw 'look already reserved' }
   "time cap $($cl.max_seconds) s; report cap $($cl.max_output_bytes) bytes; memory cap $($cl.max_memory_bytes) bytes"
   ```

   Close other heavy processes first. Free physical memory is a snapshot, so do not start the look if the capture
   workers are near their own peaks.

   **Latest start** (Toronto) by the manifest's runtime ceiling. The CLI refuses a later start non-consumingly, but
   the time is the operator's to plan:

   | `max_seconds` | Latest start |
   | ---: | ---: |
   | 1024 | 08:42 |
   | 2048 | 08:25 |
   | 4096 | 07:51 |
   | 8192 | 06:43 |
   | ≥ 16384 | not executable (exceeds the 4 h host limit) |

6. **The single look.** Run it on any Toronto date 2026-10-15..2026-10-31, from the re-pinned worktree, after step 5:

   ```powershell
   $LookOut = Join-Path $Exam ('look-' + (Get-Date).ToUniversalTime().ToString('yyyyMMddTHHmmssZ'))   # fresh per attempt
   Invoke-ExamStep 'look' (@('-m','maker_core.replay','run','--compare','--pre-registration',"$Exam\manifest\manifest.json",
     '--pre-registration-sha256',$Key,'--out',$LookOut) + $PanB + $Bind)
   ```

   Read the outcome only from `$LookOut` and `$Exam\manifest\attempts\`:
   - A `*.refusal-*.json` means the look was not consumed. That includes `engine_preflight` refusals (`engine_record_cap`,
     `pull_opportunity_cap`), which are now checked before reservation. Fix the operational cause and run again on a
     permitted date into a new `$LookOut`.
   - `maker-replay-2026-10-15-v3.json` without `.completed.json` means the look was consumed and stopped. Do not retry.
   - `registered_decision.status` is the result. `measured_k_sensitivity`, `label` and the `clarification_3` fields
     are reported beside it and change nothing.

## What was NOT done

- No registration or enrollment.
- No DECISION_LOG row.
- No production read or write, and no Scheduler change.
- No merge to master, and the plugin head was not merged into #134.
- No signed byte modified: the Clarification 2 file was added unchanged.
- No real data read.

## Commits

- #134 `codex/integration-20260929`: `994d15d0` (merge `819f8148`), `77d0196b` (index).
- #144 `codex/exam-executability-20260930`: merge of the resynced #134, then `71716c29` (implementation). This report
  and the index regeneration follow; the final head SHA is in the handback reply.

## Addendum 2026-10-01: export dependencies, module-hash binding, pinned-worktree execution

**Verdict:**

1. **Yes.** A panel bundle's content depends on the plugin's fair-value code, and fair values are baked in at export time;
   scoring never recomputes them. Panel bundles exported before prompt 2's fix carry the old fair values and must be
   re-exported after it. Calibration bundles do not carry fair values.
2. **No shared hash is required, and nothing refuses a mix.** Manifest build binds bundle bytes and the build-time
   source tree, not the exporter's module hash. Mixing pre-fix and post-fix panel bundles would therefore be accepted
   silently. That is a method decision for production and the owner, not a code refusal.
3. **Yes, as attended commands, and only with `-P` plus a module-path probe.** No registrar can pin a worktree for this
   exporter yet. No production measurement of per-day runtime or size exists.

All evidence below is read from code at `c1579cf9`.

### 1. What goes into a bundle

- **Fair value is computed during export.**
  - `maker_replay_bundle.export` calls `evaluate_event` for every book capture (`src/weather/market/maker_replay_bundle.py:379`).
  - That builds `WeatherFairValue` (`src/weather/market/maker_plugin_runner.py:23,227`), evaluates it
    (`maker_plugin_runner.py:275`) and stores the result in `entry["fair_value"]` (`maker_plugin_runner.py:279`).
  - The exporter writes it as an `outcome_view` record (`maker_replay_bundle.py:404`).
  - The knot failure is raised in `src/weather/market/maker_plugin/nbp.py:100`. `WeatherFairValue.evaluate` turns it
    into `Unavailable("nonincreasing_percentile_knots")` (`src/weather/market/maker_plugin/fair_value.py:80-81`), so it
    is baked into the bundle as an unavailable `outcome_view` rather than aborting the export.
- **At scoring time the stored view is read, not recomputed.** The engine keeps the latest `outcome_view` and feeds it
  to `informed-v0` as `fair_value` (`src/maker_core/replay/engine.py:290,418`). `plugin_input` rows, the raw captured
  support, are skipped (`engine.py:273-274`). `maker_core.replay` imports no `weather` code; the plugin runs only
  inside the exporter process.
- **Other content written by plugin code at export:**
  - descriptors from `WeatherUniverse` (`maker_plugin_runner.py:266-268`);
  - exposure factors (`maker_replay_bundle.py:398`);
  - info-clock events, settlement facts, books and terms (`maker_replay_bundle.py:400-421`);
  - raw support rows with `release_calibration_method` (`maker_replay_bundle.py:248-262`).

  A fix confined to `fair_value.py` / `nbp.py` changes only `outcome_view` payloads. A fix that also touches the
  universe, clock or settlement providers would change those records too.
- **Calibration bundles keep only `descriptor`, `coverage` and `trade`** (`maker_replay_bundle.py:39,165`). The
  descriptor is derived before fair value (`maker_plugin_runner.py:264-275`), and a fair-value failure returns
  `Unavailable` rather than raising. Calibration bundle bytes are therefore independent of the fair-value fix, and
  calibration can be exported now.
- **The rehearsal is not independent of the fix.** Its input is a night-format bundle with `outcome_view` records
  (`src/maker_core/replay/pack_cli.py`, `rehearse`). More available fair values mean more `informed-v0` quoting, so
  more engine events, decisions and runtime. Ceilings rehearsed on pre-fix bundles could undershoot a post-fix panel,
  and hitting the time or memory ceiling after reservation consumes the look. **Export the rehearsal-panel bundles
  and rehearse after the fix.**
- **Re-exports go to a new root.** An attempted day refuses in place (`src/weather/market/maker_replay_night.py:198-199`).

### 2. Module-hash and source binding

- **`--expected-module-sha256` is checked per export only.** The exporter refuses unless its own loaded module closure
  matches (`maker_replay_night.py:177`) and records `module_sha256` in the day's `receipt.json`
  (`maker_replay_night.py:204`). The receipt sits outside the bundle directory.
- **The bundle reader never reads the receipt or `export.json`.** Its `input_hashes` cover `bundle.json` and the
  declared streams only (`src/maker_core/replay/bundle.py:268,284`).
- **The manifest binds only these four things:**
  - each bundle's `input_hashes` (`src/maker_core/replay/execution_manifest.py:174`);
  - the records' captured-source hashes (`execution_manifest.py:175`), which are 88a segment seals, not code;
  - `source_hashes()` of the **build-time tree**: all of `maker_core`, `weather/market/maker_plugin`, the runner,
    capture, sources and `maker_replay_bundle.py`, plus `pyproject.toml` (`execution_manifest.py:36-54,177`);
  - that tree, re-checked at the action boundary before reservation (`src/maker_core/replay/__main__.py:169-173`).

  No check compares exporter hashes across the 18 bundles.
- **Consequence.**
  - Pre-fix and post-fix panel bundles are **not refused together**.
  - Build, verify and the look must run from one tree, and the look refuses if the tree changed after the build.
  - Exporting all 15 panel days (and the rehearsal days) from the **same** post-fix exporter hash keeps the panel
    consistent. Record one `module_sha256` per output root, and do not mix roots across a fix.

### 3. Running from a pinned detached worktree

- **Why `-P` and the probe are required.** The production venv's editable install resolves the **main checkout**.
  Measured on the workstation: `python -P -B -c "import weather, maker_core"` with no `PYTHONPATH` printed
  `...\weather\src\weather\__init__.py` and `...\weather\src\maker_core\__init__.py`. With
  `PYTHONPATH=<worktree>\src` and `-P`, both `weather.market.maker_replay_night` and `maker_core.replay.ceilings`
  came from the worktree.

  Without `-P`, a worktree working directory puts the root `weather/` shim first (`weather/__init__.py:7-11`), while
  `maker_core` still comes from the main checkout. That is a mixed import, so the order-journal pattern is required:
  `-P -B`, `PYTHONPATH` set for the child only, and a `__file__` probe before any data read. The exporter's module hash
  comes from `weather.paths.SRC_ROOT`, the worktree's own `src` (`maker_replay_night.py:44-46`). It is identical for
  any checkout of the same commit.
- **The registered nightly wrapper cannot be pinned as written.**
  - `RepoRoot` must own the wrapper (`scripts/ops/replay_bundle_export_nightly.ps1:59-60`).
  - It requires `RepoRoot\venv` (`:77`), which a worktree lacks.
  - It reads the host assignment from `RepoRoot` (`:80`).
  - It starts Python without `-P` or `PYTHONPATH` (`:110`).

  A pinned *scheduled* export needs a reviewed registrar change, like the order journal's `-RepoRoot`/`-StateRoot`/`-P`
  split. Until then, use **attended** commands.
- **Attended form** (superseded 2026-10-03 by the revised production runbook above), a change to the runbook helper above.

  ```powershell
  git -C $Repo worktree add --detach C:\weather-pinned\exam-c1579cf9 c1579cf9c2cdad54e6cb78f4a3c8d1fd4ba91e9b
  git -C $Repo worktree lock C:\weather-pinned\exam-c1579cf9 --reason 'maker replay exam exports'
  $Src = 'C:\weather-pinned\exam-c1579cf9\src'
  # Lease and job helpers stay dot-sourced from production master ($Repo); only Python code comes from the worktree.
  $env:PYTHONPATH = $Src
  $probe = & $Py -P -B -c "import weather.market.maker_replay_night as n, maker_core.replay.ceilings as c; print(n.__file__); print(c.__file__)"
  if (@($probe | Where-Object { -not $_.StartsWith($Src + '\') }).Count) { throw 'module-path probe failed' }
  # In Invoke-ExamStep, change the token prefix @('-B') to @('-P','-B'); keep -WorkingDirectory $Repo.
  # The child inherits PYTHONPATH; afterwards: Remove-Item Env:PYTHONPATH
  ```

  Run the probe in the same session immediately before each step. The `module-hash` printed under this environment is
  the value to pass to `--expected-module-sha256`.
- **Scope.** Panel export, calibration export, quote markets, calibration and rehearsal can all run this way without
  #134/#144 on master. **Manifest build, verify and the look should run from the tree that will be enrolled**, because
  `source_hashes()` hashes the importing tree (`execution_manifest.py:37`). Use either the landed master or one pinned
  worktree for all three.
- **Runtime and size: no evidence.**
  - No production export has been measured; `docs/operations/maker-replay-bundle.md` states bytes/day are unmeasured.
  - The fixture tests measure synthetic bundles only, which is not evidence for 88a volume.
  - Bounds: 2,700 s, 4 GiB of input and 2 GiB of output per day by default (`maker_replay_night.py:35-38`).
  - The first real export's `receipt.json` gives `runtime_seconds`, `peak_memory_bytes`, `bundle.bytes` and
    `bundle.records`.

  **Suggestion:** export one calibration day first and read its receipt before scheduling the rest of the backlog.
