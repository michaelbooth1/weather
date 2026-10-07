# B replay: capture-host command spec (for master-agent, N2 night of 2026-10-08)

Written 2026-10-07 by the workstation research helper. All evidence comes from `git show <sha>:<path>` at the SHAs named.
I checked the import guard on the workstation in a throwaway worktree (`C:\lpf-s\wt-b-check`, since deleted). Nothing was
run on the host. The replay was not run.

## 0. Headline findings (read first)

1. **The B replay validates RS2's model code.** Between scratch `7771474` and RS2 `d9240032`, the only difference
   under `src/weather/model/` is `model_constants.py`: the `ML_MODEL_VERSION` label v0.5.11 -> v0.5.12 and its comment.
   That label is only an identity string (`MODEL_VERSION_HGB/LR`, `get_model_version_string`); nothing uses it in a
   computation. The #246 logic in `model_distribution.py` and `model_distribution_constants.py` (lockin-anchor-v4) is
   byte-identical, and so are `tests/model/` and #189's code. The other src differences are master drift between the two
   bases and the #224 replay tool (see §5). None of them is on the `estimate_distribution` path.
2. **The pass rule is not fully machine-checkable as written.** The owner's text is "0 below-anchor mass in every hour
   block". No field is named and no threshold is pre-registered. The literal code field
   (`rows_new_below_anchor_positive`) measures mass below the *full* anchor bucket. By design, #246 floors only at the
   **METAR** bucket (`metar_bucket`), and only for `observed_station_rows` anchors. So that literal field can be
   non-zero even when B works exactly as intended, for example when a SWOB row is above the METAR max. §4 gives three
   checks. Two can be evaluated mechanically: the built-in floor check, and a PROPOSED B-floor invariant. The third is
   the literal reading. If only the literal reading fails, landing RS2 **needs a human (owner) call**.
3. **There is an import trap and a data-root trap.**
   - Import: `cwd` must be the worktree root. With `cwd` at the production root, the production `weather\` shim wins
     even when `PYTHONPATH` points at the worktree. I reproduced this.
   - Data: `weather.paths` has **no env var or flag**. `DATA_ROOT` is `<worktree>\data`, derived from `__file__`. The
     model reads climatology (`data\wunderground\<icao>\daily|hourly`) and forecast history (`data\forecast_history\`)
     from that root. A bare worktree would therefore replay with empty climatology, which is not production-faithful.
     The fix is a junction `C:\tmp\wt-b-replay\data -> production data`. It **must be removed with `cmd /c rmdir`
     before** the worktree is deleted (§1.4).
4. **Runtime is uncertain: budget 2 h 10 m, not 85 min.** The workstation plan (`l-data/design/D1.md:243`) records
   about 2 h 10 m for this replay class. `--compare-pre-lockin-floor` adds a 4th `estimate_distribution` per snapshot
   (`metar_v4_lockin_replay.py:197-198`). The planned order (RS1 -> B -> RS2, with RS2 needing to merge by ~03:45)
   only fits if B starts by about 01:15. Consider running B first at 00:30. It does not depend on RS1, because the code
   comes from the worktree and the data is read-only.

## 1. Exact command, cwd, import guard, data root

### 1.1 Module / CLI (at 7771474)
`python -m weather.backtesting.metar_v4_lockin_replay`. CLI evidence: `src/weather/backtesting/metar_v4_lockin_replay.py:50-55`
(usage) and `:417-434` (argparse). The flags are:
- `--snapshots-root`, default `data_path()/"snapshots"` (`:424`)
- `--from-date` and `--through-date`; the through date defaults to, and is capped at, 2026-09-29 (`:426-428`)
- `--out`, required: a NEW `.jsonl` FILE, never overwritten, refused inside the data root (`:429-430`)
- `--compare-pre-lockin-floor` (`:431-433`)

The per-hour-block **summary goes to stdout only** (`:452-453`); it is not written to a file. So stdout must be redirected.
Exit codes: 0 means OK; 2 means refused (`ReplayRefused`, `:449-451`); 3 means the built-in floor check failed (`:454-460`,
`FLOOR_CHECK_FAILED_EXIT = 3` in `lockin_anchor_replay.py:53`).

Exact invocation (HOST paths; cwd = `C:\tmp\wt-b-replay`):
```
C:\Users\micha\Desktop\github\weather\venv\Scripts\python.exe -m weather.backtesting.metar_v4_lockin_replay `
  --snapshots-root C:\Users\micha\Desktop\github\weather\data\snapshots `
  --from-date 2026-08-25 --through-date 2026-09-29 --compare-pre-lockin-floor `
  --out C:\tmp\b-replay-20261008\b-replay.jsonl
  # stdout -> C:\tmp\b-replay-20261008\summary.json ; stderr -> C:\tmp\b-replay-20261008\stderr.log
```

### 1.2 Why it imports the worktree's src, and the guard
- Repo-root `weather\__init__.py` at 7771474 is a shim. It inserts `<its own repo>\src\weather` at the front of
  `__path__`. `sitecustomize.py:17-22` inserts `<its own repo>\src` into `sys.path`. Both are relative to their own file,
  so whichever repo root is first on `sys.path` wins.
- The venv has an editable install. On the workstation, `venv\Lib\site-packages\__editable__.weather_market-0.1.0.pth`
  contains the repo's `src`. The host venv almost certainly has the same file pointing at
  `C:\Users\micha\Desktop\github\weather\src`. `.pth` entries come **after** cwd and `PYTHONPATH`.
- I verified this on the workstation with Python 3.11.9 and a worktree of 7771474:
  - With `cwd = worktree` and `PYTHONPATH=<wt>\src;<wt>`, imports resolve to `<wt>\weather\__init__.py`, with `__path__`
    `[<wt>\src\weather, <wt>\weather]`, and `weather.paths.__file__` = `<wt>\src\weather\paths.py`. The production src
    from the `.pth` is last on `sys.path`.
  - With `cwd = production root` and the same `PYTHONPATH`, `weather.paths.__file__` resolves to **production**. This
    is the trap; it is also the ESTABLISHED_FINDINGS §8s incident (`ESTABLISHED_FINDINGS.md:2845`).
- Guard: set `$env:PYTHONPATH='C:\tmp\wt-b-replay\src;C:\tmp\wt-b-replay'`, `PYTHONNOUSERSITE=1`, and
  `PYTHONDONTWRITEBYTECODE=1`. Remove `PYTHONSAFEPATH` and `PYTHONHOME`, and do not use `-I`/`-P`. Set the cwd to
  `C:\tmp\wt-b-replay`.
- The proof one-liner **asserts** the guard. Run it from the worktree cwd with the env above. It must print `IMPORT-OK`:
```
& C:\Users\micha\Desktop\github\weather\venv\Scripts\python.exe -c "import sys,pathlib,weather,weather.paths as p,weather.backtesting.metar_v4_lockin_replay as m,weather.model.model_distribution_constants as c,weather.model.model_constants as k; W=pathlib.Path(r'C:\tmp\wt-b-replay'); D=pathlib.Path(r'C:\Users\micha\Desktop\github\weather\data'); print(sys.version.split()[0], p.__file__, m.__file__, p.REPO_ROOT, pathlib.Path(p.data_path()).resolve(), c.LATE_DAY_LOCKIN_ANCHOR_VERSION, k.ML_MODEL_VERSION); assert pathlib.Path(p.__file__).resolve()==W/'src'/'weather'/'paths.py'; assert pathlib.Path(m.__file__).resolve()==W/'src'/'weather'/'backtesting'/'metar_v4_lockin_replay.py'; assert p.REPO_ROOT==W; assert pathlib.Path(p.data_path()).resolve()==D.resolve(); assert c.LATE_DAY_LOCKIN_ANCHOR_VERSION=='lockin-anchor-v4' and k.ML_MODEL_VERSION=='v0.5.11'; print('IMPORT-OK')"
```
(`v0.5.11` is correct here. The scratch has #246 without the version bump; see §5.)

### 1.3 Data inputs, read-only
- `weather/paths.py:8-23` at 7771474 sets `REPO_ROOT = paths.py/../..`, `DATA_ROOT = REPO_ROOT/"data"`. There is **no
  env var**, and none in `paths.py`, `weather/__init__.py` or `sitecustomize.py`.
- The replay reads:
  - snapshot folders: `replay_inputs.jsonl`, `observation_payloads.jsonl` or `_long.csv`, and blobs under
    `observation_payloads\sha256\` (`metar_keying_replay.py:114-172`). `--snapshots-root` covers these.
- The model also reads these through `data_path()`, and **no flag covers them**:
  - `MarketSpec.data_root = data_path()/"wunderground"/<icao>` (`market_registry.py:49-52`), used for climatology
    `daily\daily_summary.csv` and `hourly\year=*\month=*\observations.jsonl` (`model_climatology.py:102-145, 211`);
  - `weather.sources.forecast_history` (`data_path()/"forecast_history"/<icao>`, `forecast_history.py:155-172`),
    imported by `model_features.py:28`.
- Therefore create the junction `C:\tmp\wt-b-replay\data` -> `C:\Users\micha\Desktop\github\weather\data`. This gives
  the replay production inputs.
  - Python 3.11 `Path.resolve()` follows junctions. I verified this: `check_out_path` then refuses an `--out` inside the
    junction target. So the replay's own data-tree guard (`lockin_anchor_replay.py:74-81`) protects **production** data.
- Without the junction, the replay runs with empty climatology. The floor checks would still be internally valid, but
  the calibration paragraph numbers would not reflect serving. If master prefers no junction, say so in the record.
- Write paths: the replay writes exactly one file, `--out` (`metar_v4_lockin_replay.py:374-379`, `open("x")`).
  - The model writes into `data_root` only on network-fetch paths: `save_last_good_sources`, `cached_nws_points` and
    `cached_nws_grid_metadata` (`model_sources.py:596-602, 2048-2093`). The replay never calls them, because it passes
    captured sources to `estimate_distribution_result`.
  - I found no logging FileHandler on the import path.
  - I also confirmed that `load_replay_records` does not write. The reconstruct writer
    (`replay.py:511-525, 615-628`) is not imported by this CLI.
- Release binding: the active-release pointer is `<REPO_ROOT>\artifacts\releases\current_release.json`
  (`release_artifacts.py:49-50`), which is untracked. A worktree has none, so it runs `RESEARCH_UNBOUND` with the
  tracked global artifacts (`release_serving.py:513-520`, `toronto_model.py:107-150`). Operator: check
  `Test-Path C:\Users\micha\Desktop\github\weather\artifacts\releases\current_release.json`.
  - If it returns True, production serves a bound release and the replay's absolute distributions are not
    production's. The floor invariants in §4 are unaffected, because they are hard floors.
- LFS: `artifacts/models/hgb/*.pkl` are LFS (`.gitattributes`). Do **not** set `GIT_LFS_SKIP_SMUDGE`. Verify that
  `feature_model_hgb.pkl` does not begin with `version https://git-lfs` (step in §2).
- Read-boundary note:
  - Folder selection drops targets after 2026-09-29 (`lockin_anchor_replay.py:84-108`), and the CLI refuses
    `--through-date` after it (`:65-71`).
  - Snapshots with `built_at.date() > 2026-09-29` are skipped without opening their blob
    (`metar_v4_lockin_replay.py:390-393`). `compare_snapshot` refuses later targets (`:180-181`).
  - Climatology parses the whole `daily_summary.csv` but skips rows with `year >= target year`
    (`model_climatology.py:116-121`). This is the same parse-and-discard that production serving does daily
    (STATE_OF_PLAY.md:76: "Q14/OD17 parse-and-discard is not a read").
  - No 88a or panel data is touched.

### 1.4 The host procedure (one detached PowerShell process holds the lease for its whole life)
The lease is an open file handle plus a named mutex owned by the PowerShell process that called
`Enter-WeatherHeavyWorkloadLease` (`workload_admission.ps1:1-16, 1957-1961`). So the whole procedure must run in one
long-lived process. A tool call that times out would abandon it. Save four files in `C:\tmp\b-replay-20261008\`:
- the following script as `run-b-replay.ps1`;
- the §4 evaluator as `eval_b.py`;
- the §1.2 proof body as `proof_b.py`;
- the §7 audit wrapper as `b_audit_run.py` (byte-identical to `l-data\b_audit_run.py`, LF endings; sha256 in §7.4).
The replay is launched through `b_audit_run.py` (§7 amendment, already applied below).

Launch it with
`Start-Process powershell.exe -ArgumentList '-NoProfile','-ExecutionPolicy','Bypass','-File','C:\tmp\b-replay-20261008\run-b-replay.ps1' -WindowStyle Hidden -PassThru`,
retain the PID, and poll `C:\tmp\b-replay-20261008\result.json`.

```powershell
param([string]$StopAt = '08:40')   # hard child kill time (local), before the 09:00 lease end
$ErrorActionPreference = 'Stop'
$Prod = 'C:\Users\micha\Desktop\github\weather'
$Py   = "$Prod\venv\Scripts\python.exe"
$Wt   = 'C:\tmp\wt-b-replay'
$Out  = 'C:\tmp\b-replay-20261008'
$Sha  = '7771474848e253ec6a45c4524ebfb70b726e08de'
New-Item -ItemType Directory -Force $Out | Out-Null      # already holds the three files
$res  = [ordered]@{ started = (Get-Date).ToString('s'); sha = $Sha }
function Save-Result { $res.saved = (Get-Date).ToString('s'); $res | ConvertTo-Json -Depth 6 | Set-Content -Encoding UTF8 "$Out\result.json" }
# --- resource preconditions (policy rule 2: HOST_LOAD_POLICY.md:400-404) ---
$g = Get-Content "$Prod\data\logs\memory_commit_guard_status.json" -Raw | ConvertFrom-Json
if ([double]$g.commit_percent -ge 70) { $res.refused = "commit_percent $($g.commit_percent)"; Save-Result; exit 1 }
$availGiB = (Get-CimInstance Win32_OperatingSystem).FreePhysicalMemory / 1MB
if ($availGiB -lt 4) { $res.refused = "available RAM $availGiB GiB"; Save-Result; exit 1 }
$freeGiB = (Get-PSDrive C).Free / 1GB
if ($freeGiB -lt 50) { $res.refused = "C: free $freeGiB GiB"; Save-Result; exit 1 }
if (Test-Path "$Out\b-replay.jsonl") { $res.refused = 'out exists'; Save-Result; exit 1 }
if (Test-Path $Wt) { $res.refused = "$Wt already exists"; Save-Result; exit 1 }
$res.pre = @{ commit_percent = $g.commit_percent; avail_gib = $availGiB; free_gib_before = $freeGiB }
. "$Prod\scripts\ops\workload_admission.ps1"
$lease = Enter-WeatherHeavyWorkloadLease -RepoRoot $Prod -Workload 'b_replay_7771474'   # throws outside 00:30-09:00
$junction = $false
try {
  git -C $Prod fetch origin claude/scratch-189-224-b-20261006
  if ((git -C $Prod rev-parse "$Sha^{commit}") -ne $Sha) { throw 'scratch SHA missing' }
  git -C $Prod worktree add --detach $Wt $Sha
  if ((git -C $Wt rev-parse HEAD) -ne $Sha) { throw 'worktree HEAD mismatch' }
  if (git -C $Wt status --porcelain) { throw 'worktree not clean' }
  $head = [IO.File]::ReadAllBytes("$Wt\artifacts\models\hgb\feature_model_hgb.pkl")[0..22]
  if ([Text.Encoding]::ASCII.GetString($head) -like 'version https://git-lfs*') { throw 'LFS not smudged' }
  New-Item -ItemType Junction -Path "$Wt\data" -Target "$Prod\data" | Out-Null; $junction = $true
  $env:PYTHONPATH = "$Wt\src;$Wt"; $env:PYTHONNOUSERSITE = '1'; $env:PYTHONDONTWRITEBYTECODE = '1'; $env:PYTHONUTF8 = '1'
  Remove-Item Env:PYTHONSAFEPATH, Env:PYTHONHOME -ErrorAction SilentlyContinue
  Set-Location $Wt
  # proof_b.py = the §1.2 one-liner's python body (the text between the outer double quotes), one statement per line.
  # exec under -c keeps sys.path[0] = cwd, exactly as `-m` will see it.
  $proof = & $Py -c "exec(open(r'C:\tmp\b-replay-20261008\proof_b.py').read())"
  $res.import_proof = ($proof -join ' | ')
  if ($LASTEXITCODE -ne 0 -or ($proof -join ' ') -notmatch 'IMPORT-OK') { throw 'import proof failed' }
  # §7 amendment: run under the audit-hook wrapper (abort on the first non-temp write outside $Out -> exit 4)
  if ((Get-FileHash "$Out\b_audit_run.py" -Algorithm SHA256).Hash -ne '0BB589284DBE8BC103D874F1599A385BAAD11589C15FC4B7AD609E7D9A04F09B') { throw 'b_audit_run.py hash mismatch' }
  $rargs = @("$Out\b_audit_run.py",'--audit-dir',$Out,'--abort-on-write','--',
            '--snapshots-root',"$Prod\data\snapshots",
            '--from-date','2026-08-25','--through-date','2026-09-29','--compare-pre-lockin-floor',
            '--out',"$Out\b-replay.jsonl")
  $p = Start-Process -FilePath $Py -ArgumentList $rargs -WorkingDirectory $Wt -NoNewWindow -PassThru `
        -RedirectStandardOutput "$Out\summary.json" -RedirectStandardError "$Out\stderr.log"
  $null = $p.Handle                        # PS 5.1: needed for ExitCode later
  $p.PriorityClass = 'BelowNormal'
  $res.replay_pid = $p.Id; $res.replay_started = (Get-Date).ToString('s'); Save-Result
  $stop = [datetime]::ParseExact($StopAt, 'HH:mm', $null); $peakPriv = 0; $peakWs = 0
  while (-not $p.HasExited) {
    $p.Refresh(); $peakPriv = [math]::Max($peakPriv, $p.PrivateMemorySize64); $peakWs = [math]::Max($peakWs, $p.PeakWorkingSet64)
    if ($p.PrivateMemorySize64 -gt 6GB) { taskkill /PID $p.Id /T /F | Out-Null; $res.killed = 'private > 6 GiB'; break }
    if ((Get-Date) -gt $stop) { taskkill /PID $p.Id /T /F | Out-Null; $res.killed = "deadline $StopAt"; break }
    Start-Sleep -Seconds 30
  }
  $p.WaitForExit()
  $res.replay_exit = $p.ExitCode; $res.replay_finished = (Get-Date).ToString('s')
  $aw = @(if (Test-Path "$Out\audit-writes.jsonl") { Get-Content "$Out\audit-writes.jsonl" | Where-Object { $_ } })
  $res.audit_events = $aw.Count; $res.audit_nontemp = @($aw | Where-Object { $_ -notmatch '"temp": true' }).Count
  if ($res.replay_exit -eq 4 -or $res.audit_nontemp -gt 0) { $res.audit_abort = $true; throw 'AUDIT: write outside C:\tmp\b-replay-20261008 - see audit-writes.jsonl; B result void' }
  $res.peak_private_gib = [math]::Round($peakPriv / 1GB, 2); $res.peak_ws_gib = [math]::Round($peakWs / 1GB, 2)
  if (Test-Path "$Out\b-replay.jsonl") { $res.out_gib = [math]::Round((Get-Item "$Out\b-replay.jsonl").Length / 1GB, 3) }
  if (-not $res.killed -and $res.replay_exit -in 0, 3) {
    $v = & $Py "$Out\eval_b.py" "$Out\b-replay.jsonl"; $res.eval_exit = $LASTEXITCODE
    ($v -join "`n") | Set-Content -Encoding UTF8 "$Out\verdict.json"
  }
} catch { $res.error = $_.Exception.Message }
finally {
  Set-Location 'C:\tmp'
  if ($junction -or (Test-Path "$Wt\data")) {
    cmd /c rmdir "$Wt\data"                                  # removes the LINK only, never the target
    if (Test-Path "$Wt\data") { $res.teardown = 'JUNCTION STILL PRESENT - worktree NOT removed' }
  }
  if (-not $res.teardown -and (Test-Path $Wt)) { git -C $Prod worktree remove --force $Wt; git -C $Prod worktree prune }
  $res.free_gib_after = (Get-PSDrive C).Free / 1GB
  Save-Result
  Exit-WeatherHeavyWorkloadLease -Lease $lease
}
```
**Never** run `Remove-Item -Recurse` or `git worktree remove` on `C:\tmp\wt-b-replay` while `data` is still a junction.
Windows PowerShell 5.1 recursive delete can follow a junction into its target. The script refuses to remove the worktree
in that case. Fix it by hand with `cmd /c rmdir C:\tmp\wt-b-replay\data`.

## 2. Heavy lease
- Function: dot-source `C:\Users\micha\Desktop\github\weather\scripts\ops\workload_admission.ps1`. Then call
  `Enter-WeatherHeavyWorkloadLease -RepoRoot C:\Users\micha\Desktop\github\weather -Workload b_replay_7771474`
  (`workload_admission.ps1:1620-1628` at c9cf068be). In the `try/finally`, end with
  `Exit-WeatherHeavyWorkloadLease -Lease $lease` (`:2279`). This is the pattern used by `clob_tiering_run.ps1:45,105,169`.
  - Use the default profile `capture_colocated_v1`. With it the workload name is free text, and the window comes from
    `Get-WeatherHeavyWorkloadPolicyWindow` (`:565-608`): `agent_heavy` from 00:30 up to 09:00. Outside that, Enter
    throws "outside the 00:30-09:00 window" (`:1766-1772`).
- The lease does **not** check memory, disk or capture health (`HOST_LOAD_POLICY.md:400-404`). The script does those
  checks itself (commit < 70%, >= 4 GiB available, >= 50 GiB free). It does no capture-health check; master should
  confirm capture is healthy before launching.
- `workstation_heavy.ps1` is for the non-capture workstation only. Do not use it on the capture host.
- The module name matches the S4U heuristic-heavy pattern `replay|backtest` (`workload_admission.ps1:797-807`). Claude
  sessions have no hook, so the S4U guard is the only backstop (`HOST_LOAD_POLICY.md:451`). It kills agent-rooted
  trees whose private bytes reach 8 GB (`:443`). The script's own kill is at 6 GiB.
- Serial: while B holds the lease, no RS2 suite, merge or 91a can run.

## 3. Memory, disk, output (estimates; LOW-MEDIUM confidence; no prior host run log found)
- **Output location:** `C:\tmp\b-replay-20261008\`, outside `data\`. The out-dir "flag" is just `--out <file>`. Its
  parent is created by `out.parent.mkdir` (`metar_v4_lockin_replay.py:378`).
  - `b-replay.jsonl`: one row per compared snapshot, holding 4 full distributions (`old_final`, `v3_captured_final`,
    `new_final`, `b_off_final`), 2 anchors without `history`, and METAR row lists (`:200-242`).
  - `summary.json`: the stdout summary.
  - `stderr.log`, `result.json` and `verdict.json`.
- **Disk:** about 5-20 KB per row. Rough count: 36 dates x 12 markets x a few hundred snapshots/day gives roughly
  50k-150k rows, so **about 0.3-3 GB**. Treat this as a guess and check `result.json:out_gib`. Worktree plus LFS
  pickles add about 0.35 GB, removed at teardown.
- **Peak memory: about 1.5-3 GB private, ceiling about 4 GB.**
  - 12 market models (coefs JSON about 0.4 MB each; tracked HGB pickles total about 290 MB across 20 files if
    materialized).
  - The class-level climatology cache, capped at 128 entries (`model_climatology.py:30, 58-69`).
  - Per-folder blob cache, released per folder (`metar_v4_lockin_replay.py:383`).
  - The in-memory `rows` list of 15 summary keys per row (`:413`), about 0.2-0.4 GB at 150k rows.
  - The script records `peak_private_gib` and `peak_ws_gib`.
- **Runtime:** your figure is about 85 min. The workstation plan's figure is about 2 h 10 m for this class
  (`l-data/design/D1.md:243`). `--compare-pre-lockin-floor` adds about 33% more model calls per row. Plan for 2 h 10 m.

## 4. Pass rule for landing RS2 the same night

**What the decision documents define.** DECISION_LOG.md:126 and STATE_OF_PLAY.md:43-45 say:
"lands with #189 in a quiet window only after the 10-07 replay on scratch `77714748` shows 0 below-anchor mass in every
hour block; that replay's calibration paragraph goes in the record."
- That is the only pre-registered criterion: zero, per hour block. No field or tolerance is named.
- The calibration paragraph is a human write-up for the record. It is not a numeric gate. The workstation writes it
  after the run (`l-data/QUEUE.md:46,61`).
- The decision says "10-07 replay". It is now running on the N2 night on the same scratch SHA, and the record should
  say so.

**Hour blocks.** These are `00-05, 06-09, 10-12, 13-16, 17-23` of `built_at.hour` in the recorded offset, i.e. host
(Toronto) local time, not market-local (`metar_v4_lockin_replay.py:82-88, 205`; `replay.py:87-98`).

**Checks.** All are computed by `eval_b.py` directly from `b-replay.jsonl`, independent of stdout. The tolerance is the
code's own `BELOW_ANCHOR_TOLERANCE = 1e-9` (`lockin_anchor_replay.py:52`).
- **D (dates, required):** every compared row has `2026-08-25 <= target_date <= 2026-09-29`. Code also guarantees this
  (§1.3).
- **R1 (required; built-in, pre-existing #189/#224 floor check):** in every block, `rows_new_below_anchor_exceeds_old == 0`,
  i.e. replay exit code 0 and `summary.floor_check == "PASS"` (`:245-264, 334, 338-343`). Carry-over rows are excluded
  by design (`trace-189-floor-check.md`, owner-reviewed 10-06). Its non-carry violators were already 0 in the 10-06
  production run.
- **R3 (required; PROPOSAL, the B invariant):** for every row whose `lockin_anchor.observed_floor_bucket` is set, the
  mass in `new_final` below that bucket must be at most 1e-9, in every block. Each block must have more than 0 rows. At
  least one row must have `observed_floor_stage == "pre_lockin"`, which proves the floor was not inert. `anchor_versions`
  must contain only `lockin-anchor-v4` or `None`.
  - Why this is the B invariant: #246 calls `apply_lockin_observed_floor` with `observed_floor_bucket` (the anchor
    bucket late-day, the `metar_bucket` pre-lock-in; `model_distribution.py:1517-1546`). That function zeroes mass
    below the bucket (`:1361-1374`). Calibration then gets `floor_bucket = max(hard_floor, observed_floor_bucket)`
    (`:557-562`).
- **R2 (literal reading; owner's words):** in every block, `rows_new_below_anchor_positive == 0`, i.e. `new_final`
  mass below the **full** anchor bucket is at most 1e-9 (`:267-272, 312`). By #246's design (`model_distribution.py:1244-1252`:
  "the pre-lock-in floor (v4) reads METAR rows only ... SWOB keeps its warm-bias hedge"; and the floor applies only to
  `source == "observed_station_rows"` anchors), R2 can be non-zero while B is working.

**Verdict.** `eval_b.py` exits **0 = PASS_LITERAL** when D, R1, R3 and R2 all hold. It exits
**10 = PASS_B_FLOOR_ONLY_NEEDS_JUDGEMENT** when D, R1 and R3 hold but R2 does not. It exits **1 = FAIL** otherwise. My
recommendation:
- land RS2 on exit 0 together with replay exit 0;
- on exit 10, do **not** land the same night without an owner call, and send the owner the per-block `lit_pos`/`lit_max`;
- never land on exit 1.

`verdict.json` carries the per-block counts.

**Evaluator** (`C:\tmp\b-replay-20261008\eval_b.py`; tested on synthetic rows on the workstation):
```python
import json,sys,collections
p=sys.argv[1];T=1e-9
B=[("00-05",0,5),("06-09",6,9),("10-12",10,12),("13-16",13,16),("17-23",17,23)]
def blk(h): return next((n for n,a,b in B if h is not None and a<=h<=b),"none")
st=collections.OrderedDict((n,dict(rows=0,lit_pos=0,lit_max=0.0,exceeds_old=0,floored=0,pre_lockin=0,below_floor_viol=0,below_floor_max=0.0)) for n,_,_ in B+[("none",0,0)])
dmin=dmax=None;ver=collections.Counter();other=collections.Counter()
with open(p,encoding="utf-8") as f:
  for line in f:
    r=json.loads(line)
    if "new_final" not in r: other[str(r.get("status"))]+=1; continue
    d=r["target_date"];dmin=min(dmin or d,d);dmax=max(dmax or d,d);ver[str(r.get("anchor_version"))]+=1
    s=st[blk(r.get("hour"))];s["rows"]+=1
    nb,ob=r.get("new_mass_below_anchor"),r.get("old_mass_below_anchor")
    if nb is not None and nb>T: s["lit_pos"]+=1;s["lit_max"]=max(s["lit_max"],nb)
    if nb is not None and ob is not None and nb>ob+T and not r.get("carried_prior_day_rows"): s["exceeds_old"]+=1
    a=r.get("lockin_anchor") or {};fb=a.get("observed_floor_bucket")
    if fb is not None:
      s["floored"]+=1;s["pre_lockin"]+=a.get("observed_floor_stage")=="pre_lockin"
      m=sum(v for k,v in r["new_final"].items() if int(k)<fb);s["below_floor_max"]=max(s["below_floor_max"],m);s["below_floor_viol"]+=m>T
blocks=[s for n,s in st.items() if n!="none"]
dates_ok=dmin is not None and dmin>="2026-08-25" and dmax<="2026-09-29"
r1=all(s["exceeds_old"]==0 for s in blocks)
r3=all(s["rows"]>0 and s["below_floor_viol"]==0 for s in blocks) and sum(s["pre_lockin"] for s in blocks)>0 and set(ver)<={"lockin-anchor-v4","None"}
r2=all(s["lit_pos"]==0 for s in blocks)
v="FAIL" if not(dates_ok and r1 and r3) else ("PASS_LITERAL" if r2 else "PASS_B_FLOOR_ONLY_NEEDS_JUDGEMENT")
print(json.dumps(dict(verdict=v,dates=[dmin,dmax],dates_ok=dates_ok,R1_floor_check=r1,R3_b_floor_invariant=r3,R2_literal_zero_below_anchor=r2,anchor_versions=ver,non_compared=other,blocks=st),indent=1))
sys.exit({"PASS_LITERAL":0,"PASS_B_FLOOR_ONLY_NEEDS_JUDGEMENT":10}.get(v,1))
```
Quick read after the run: `(Get-Content C:\tmp\b-replay-20261008\verdict.json -Raw | ConvertFrom-Json).verdict`.
For the cross-check, `summary.json` `floor_check` must be `PASS` and `pre_lockin_floor.rows_changed` must be > 0.

## 5. What 7771474 contains, and RS2 identity

- `git log --oneline --first-parent c9cf068be..7771474`:
  - `7771474` merges `origin/codex/metar-v4-lockin-v3-replay-20261005` (#224 @ `96a207ea7`)
  - <- `09c6a4fe4` B, lockin-anchor-v4, whose parent is `5e03609e3`
  - <- `5e03609e3` (#189 head) <- `22328fce1` <- `9de095559` <- `8cde625e8` <- `bbd121bf6`
- **So 7771474 = #189 `5e03609e` + B `09c6a4fe` + #224 `96a207ea` (yes, #224 is in it).**
  - #224 brings `src/weather/backtesting/metar_v4_lockin_replay.py`, the tool being run, plus its tests and the
    carry-over defect-baseline class.
- **Base caveat:** c9cf068be is **not** an ancestor of 7771474. Their merge-base is `79415b2ae` (master 10-06 03:18).
  The 68 master commits `79415b2ae..c9cf068be` are absent from the scratch.
- `git branch -r --contains 7771474`: only `origin/claude/scratch-189-224-b-20261006`. `09c6a4fe` is in `rs`, `rs2`,
  `pre-lockin-same-day-floor` and the scratch.
- RS2 `d9240032` (first-parent over c9cf068be):
  - `c78ba63de` merges #189 `5e03609e`;
  - `8a8d5b16c` merges #246 `91bf0786`, which = `09c6a4fe` + one commit "bump ML_MODEL_VERSION to v0.5.12":
    `model_constants.py` plus the `docs/architecture.md` comment;
  - `d9240032e` merges the time-bomb fix `27e67f6e`.
- `git diff 7771474 d9240032 -- src` (114 files) breaks down as follows:
  - `src/weather/model/`: **only `model_constants.py`**, the label v0.5.11 -> v0.5.12 and its comment. The label is
    used only as an identity string (`toronto_model.py:352-354`, `model_identity.py:109-115`, `snapshot_store.py:100`),
    never in a computation or a release-binding check.
  - `src/weather/backtesting/`: RS2 lacks `metar_v4_lockin_replay.py` (#224 is not in RS2), which is expected.
  - Everything else is master drift `79415b2..c9cf068`: mm_paper/taker retirement, schema registry, ops, `time.py`
    (`utc_now` gains optional args, backward-compatible), and `sources/asos_one_minute.py` and `grib_probe.py`. None of
    it is imported on the `estimate_distribution` path. I intersected the model's `from weather.*` imports with the
    changed files: the hits are only `model_constants`, `schema_registry_*` (mm entries) and `time.py`, which the model
    does not call.
  - Tracked `artifacts/` are identical. `config/` differs only by the event-metadata refresh (October events, outside
    the window) and `scheduled_tasks.json`.
  - `tests/model` and `tests/backtesting` differ only by the absent #224 test.
- **Conclusion: B's model code = RS2's model code.** The replay validates RS2's distribution behaviour, apart from the
  version label. The import proof therefore expects `v0.5.11`.

## 6. Open items for master
1. Does the host have `artifacts\releases\current_release.json`? This affects only how representative the calibration
   paragraph is (§1.3).
2. How was the 10-06 #224 production run (the violators-by-block evidence) set up: worktree with or without a data
   junction? Use the same setup, or note the difference, so the two runs are comparable.
3. Scheduling: B (up to about 2 h 10 m) then RS2 by about 03:45 only fits if B starts by about 01:15, or runs first at
   00:30 before RS1.

## 7. Write-sink audit under DATA_ROOT (gate for B; answered 2026-10-07 for master)

**Verdict: no reachable write sink under DATA_ROOT. The gate is clear for B.** The replay writes exactly two things:
the parent `mkdir` of `--out` and the `--out` file itself (`metar_v4_lockin_replay.py:378-379`, `open("x")`). Both
sit behind `check_out_path`, which refuses any path inside the resolved data tree (`lockin_anchor_replay.py:74-81`).
The dynamic run saw zero write events outside the output dir, not even in `%TEMP%`. The static sweep found no other
write sink on the replay's call path.

### 7.1 Dynamic (workstation, under the §7.3 wrapper)
- Setup:
  - throwaway worktree `C:\lpf-s\wt-b-audit` @7771474, cwd = the worktree;
  - `PYTHONPATH=<wt>\src;<wt>`, `PYTHONNOUSERSITE=1`, `PYTHONDONTWRITEBYTECODE=1`;
  - junction `<wt>\data` -> the **workstation** `data\` (never production);
  - output in the session scratchpad.
- Snapshots: the workstation has none in 08-25..09-29 (its latest market-days are about 08-12). I used two in-range
  folders, both ≤ 09-29: `highest-temperature-in-toronto-on-august-12-2026` (CA path, 36 snapshots) and
  `highest-temperature-in-seattle-on-august-9-2026` (US path, 149 snapshots). Run with `--compare-pre-lockin-floor`.
- Run 1, abort OFF, all events collected:
  - exit 0, 185 rows, `status: {ok: 185}`, `floor_check: PASS`;
  - **0 write events** in `audit-writes.jsonl`, including 0 temp-file events.
- Run 2, abort ON (the host configuration): exit 0, again 0 events. Its summary is byte-identical to run 1 apart from
  the `out` path, so the wrapper does not change results.
- Wrapper self-test with a probe module:
  - all of these were logged with path, mode and stack: mkdir, `open("w")`, `os.open(O_WRONLY|O_CREAT)`,
    `os.replace` (it fires `os.rename`), `shutil.copyfile`, `os.remove`/`os.unlink`;
  - `tempfile` writes were logged with `temp: true` and did not abort;
  - `sqlite3.connect(":memory:")` was ignored;
  - read-only opens were not logged;
  - the module's own exit 7 passed through, and abort-ON exited 4 at the first mkdir.
- Scoped mtime check: a marker was touched before each run, then `find <dir> -newer marker` (no recursive walk of
  `data\`). Zero newer entries in every place checked:
  - `wunderground\CYYZ` and `wunderground\KSEA`;
  - `forecast_history\cyyz` and `forecast_history\ksea`;
  - both snapshot folders;
  - `snapshots\observation_source_cache`;
  - `data\` maxdepth 1 and `data\snapshots\` maxdepth 1.
- Speed, for information only: 185 snapshots with four model runs each took about 20 s wall time, including startup,
  on the workstation. The §3 runtime estimate is probably pessimistic.

### 7.2 Static (every `weather` module actually loaded, from `sys.modules` at the end of the run)
- Module set: 59 files. All resolve inside the worktree, including `sitecustomize.py` and `src\weather\__init__.py`;
  none come from production `src`.
- Reachability was measured, not guessed:
  - a `sys.setprofile` trace of the same two-folder run recorded 588 executed worktree functions;
  - a grep over the 59 files for write sinks gave 140 hits, and each was mapped to its enclosing function by AST;
  - the grep pattern covered: `open(` w/a/x/+, `mode=`, `write_text`/`write_bytes`, `to_csv`/`parquet`/`json`/
    `feather`/`pickle`, `json.dump`, `pickle`/`joblib.dump`, `np.save`, `mkdir`/`makedirs`, `shutil.`, `os.replace`/
    `rename`/`remove`/`unlink`/`rmtree`, `os.open`, `sqlite3`, `FileHandler`, `requests_cache`, `diskcache`, `shelve`,
    `tempfile`, `Memory(`, `atomic_write`/`write_json*`/`append_json*`, `link`/`symlink`.
- Result: 3 hits executed, 3 module-level imports, 134 never executed.
- **Executed:**
  - `metar_v4_lockin_replay.py:378` (`out.parent.mkdir`) and `:379` (`out.open("x")`): the `--out` file only.
  - `release_serving.py:113`: `is_symlink()`, a read and a grep false positive.
- **Module level:** import lines only, at `model_sources.py:26`, `reanalysis_history.py:19` and `wu_history.py:15`.
- **Not executed, and not reachable from the replay's call path:**
  - **`model/model_sources.py`, the live-fetch and last-good caches** (`data_root`, i.e. under DATA_ROOT, so these
    were the dangerous ones):
    - sinks: `quarantine_last_good_sources_cache:590`; `save_last_good_sources:600,615`;
      `record_source_family_rate_limit:701`; `cached_nws_points:2061-2062`; `cached_nws_grid_metadata:2092-2093`;
    - all of them are reachable only from `fetch_sources:180-184` -> `fetch_live_sources` (`:243`
      `blend_with_last_good(fetch_live_source_groups(...))`, and `source_fetcher_with_budget` at `:439`/`:471`);
    - the only callers of `fetch_sources` and `fetch_live_sources` are `toronto_model.py:289-292` (`build()`, only when
      both source args are None) and `collection/snapshot_tracker.py:221`;
    - the replay never calls `build`. It calls `estimate_distribution_result(record["sources"], now=built_at)`
      (`lockin_anchor_replay.py:130-132`);
    - it skips any record with no captured sources (`metar_v4_lockin_replay.py:388-389`);
    - `model_distribution.py` has no `fetch` or `last_good` reference at all;
    - the trace confirms `fetch_sources`, `fetch_live_source_groups`, `blend_with_last_good`, `load_last_good_sources`
      and `build` were never called, while `estimate_distribution_result`, `compare_snapshot` and `load_blob` were.
  - **`sources/wu_history.py`, the WU fetch/ingest writers:**
    - sinks: `write_payload`, `write_fetch_error`, `write_daily_summary`, `write_hourly_partitions`, `write_manifest`,
      `recover_unavailable_errors`, `unlink_with_retry` (:719 and others);
    - they are called only inside `wu_history.py` (its own CLI), never from `model/` or the replay modules;
    - the replay reads WU climatology only (`model_climatology.py`, which has no sink hits).
  - **`sources/forecast_history.py`:** `backfill`, `write_csv`, `write_forecast_history_coverage_outputs`. These are
    its own CLI only; the model reads forecast history only (`forecast_history.py:155-172`).
  - **`sources/grib_probe.py`, `nbm_probabilistic_tmax.py`, `reanalysis_history.py`, `reanalysis_synoptic.py`,
    `historical_schema.py`:** fetch, build and CLI writers, called only within their own modules.
  - **`artifacts.py`** writers (`writable_artifact_path:412` and the `write_artifact_*` family) are called only from
    `calibration/*`, which is not loaded. The `release_artifacts.py`, `point_in_time_contract.py:663` and
    `cold_archive_locations.py:154` hits are `is_symlink()` reads, i.e. false positives.
  - **`io.py`:** the generic writer helpers (`write_json_atomic`, `write_text_atomic`, `append_jsonl`,
    `write_csv_rows*`, `acquire_writer_lock`, and others) all show 0 executions.
  - **`backtesting/replay.py`:** `write_replay_input_status`, `reconstruct_corpus_for_folder:525`. Also
    `lockin_anchor_replay.run:215-216` and `metar_keying_replay.run:237-238` (the sibling CLIs). None of these are
    called by this CLI.
- Third-party caches and logs:
  - `sqlite3`, `requests_cache`, `diskcache` and `shelve` are not in `sys.modules`;
  - `joblib` is loaded (by sklearn), but no `Memory(`/`joblib.dump` exists in any loaded `weather` module;
  - there is no `FileHandler` in the loaded modules;
  - `requests` is imported but unused (network fetch paths not reached, as above).
- Residual risk:
  - the audit hook cannot see writes made natively by C extensions (for example pyarrow file sinks);
  - the static sweep found no `to_parquet`/`to_feather`/`np.save`/`pickle.dump` in any loaded module, which covers
    that gap at source level;
  - code running before the hook (`sitecustomize.py`, the root shim) is path setup only, with no sink hits;
  - the host run touches more markets and dates, but through the same class (`TorontoHighTempModel` for every market,
    `metar_v4_lockin_replay.py:369-373`) and the same call path. The abort-ON wrapper is the backstop.

### 7.3 The wrapper `b_audit_run.py`
- Location: `C:\wt\workstation-chat\l-data\b_audit_run.py`. Copy it byte-for-byte (LF endings) to
  `C:\tmp\b-replay-20261008\b_audit_run.py`.
- Usage: `python b_audit_run.py [--audit-dir DIR] [--abort-on-write|--no-abort-on-write] [--dump-modules FILE] -- <replay args>`.
  `--audit-dir` defaults to `C:\tmp\b-replay-20261008`, and abort is ON by default.
- Order of operations: it installs `sys.addaudithook` before any `weather` import, sets `sys.argv`, then runs
  `runpy.run_module('weather.backtesting.metar_v4_lockin_replay', run_name='__main__', alter_sys=True)`. `SystemExit`
  codes pass through.
- What it logs, to `<audit-dir>\audit-writes.jsonl`, one JSON line per event with `event`, `path`, `mode`/`flags` or
  `args`, `temp`, and `stack` (3 frames):
  - `open` with mode w/a/x/+ or flags `O_WRONLY|O_RDWR|O_CREAT|O_APPEND|O_TRUNC`;
  - `os.rename` (which also covers `os.replace`), `os.remove` (also `os.unlink`), `os.rmdir`, `os.mkdir`,
    `os.truncate`, `os.symlink`, `os.link`, `os.chmod`, `os.utime`, `shutil.*`, and `sqlite3.connect` (except
    `:memory:`).
- Exclusions: anything under `--audit-dir` (which includes `audit-writes.jsonl`, opened before the hook) is not
  logged. A thread-local busy flag prevents recursion. Writes through already-open integer fds are skipped, because
  their `os.open` was already audited.
- Abort: `%TEMP%`/`%TMP%` paths (both `abspath` and `realpath` spellings) are logged with `temp: true` and never abort.
  Any other event is written, flushed, and then `os._exit(4)`.
- Temp files seen: none from the replay. The workstation replay runs logged zero temp events; the only temp events
  seen were from the self-test's own `tempfile` probe.
- `sys.path` note: launched as a script, `sys.path[0]` is `C:\tmp\b-replay-20261008`. That directory must contain no
  `weather\` package and no `sitecustomize.py`; it holds only the four files and outputs. With that,
  `PYTHONPATH=<wt>\src;<wt>` resolves `weather` to the worktree. This was verified on the workstation: all 59 loaded
  `weather` files came from the worktree.

### 7.4 Launch-line replacement in run-b-replay.ps1 (already applied in §1.4)
Replace the `$rargs = @('-m', ...)` assignment with:
```powershell
  if ((Get-FileHash "$Out\b_audit_run.py" -Algorithm SHA256).Hash -ne '0BB589284DBE8BC103D874F1599A385BAAD11589C15FC4B7AD609E7D9A04F09B') { throw 'b_audit_run.py hash mismatch' }
  $rargs = @("$Out\b_audit_run.py",'--audit-dir',$Out,'--abort-on-write','--',
            '--snapshots-root',"$Prod\data\snapshots",
            '--from-date','2026-08-25','--through-date','2026-09-29','--compare-pre-lockin-floor',
            '--out',"$Out\b-replay.jsonl")
```
The `Start-Process -FilePath $Py -ArgumentList $rargs ...` line itself is unchanged. Directly after
`$res.replay_exit = $p.ExitCode; ...`, add:
```powershell
  $aw = @(if (Test-Path "$Out\audit-writes.jsonl") { Get-Content "$Out\audit-writes.jsonl" | Where-Object { $_ } })
  $res.audit_events = $aw.Count; $res.audit_nontemp = @($aw | Where-Object { $_ -notmatch '"temp": true' }).Count
  if ($res.replay_exit -eq 4 -or $res.audit_nontemp -gt 0) { $res.audit_abort = $true; throw 'AUDIT: write outside C:\tmp\b-replay-20261008 - see audit-writes.jsonl; B result void' }
```
- Exit 4, or any non-temp line, voids B; the `finally` block still tears down. Temp lines are recorded in
  `result.json` (`audit_events`) for master to list.
- sha256 of `b_audit_run.py` (LF): `0bb589284dbe8bc103d874f1599a385baad11589c15fc4b7ad609e7d9a04f09b`. A CRLF
  conversion changes the hash and makes the script refuse to run; copy it as binary.
