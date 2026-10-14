# #263 r2 desk-study power rule (N_req): host run

- Head: `claude/desk-study-power-rule-r2-20261014` @ `69af7d613b97` (draft PR #283). Read the script diff in #283 first.
- Script: `tools/research/maker_pnl_power_rule_pilot.py`. Read-only, never trades, refuses any date after 2026-09-29
  (rc 3). It puts its own worktree's `src` first, so production `src` is never imported.
- Slot: master's choice. Tonight after N9 if the lease is free with a clean gap before 04:45, else the 10-15 night.
  00:30-09:00 only, under the shared heavy lease.
- Measured on the workstation, synthetic store only (no real `maker_evidence` on the WS): 0.75 GB gz / 5.1 GB raw,
  120 segments, 327.6 s, peak working set 0.68 GB, peak commit 2.2 GB. Host extrapolation: 3-7 min, < 1 GB.

## (a) Command block

Assumptions to replace before running: `$repo` = the production root (inputs are read from its `data\` only);
`$wt` = a fresh, non-existent path for a detached worktree; `$out` = a new directory not under any `data` folder.

```powershell
$repo = '<PRODUCTION ROOT>'                         # read-only inputs: data\maker_evidence, data\settlements
$wt   = 'C:\wt\pwr-run-69af7d613'                   # fresh path; must not exist
$out  = 'C:\tmp\maker-pnl-power-rule-r2'            # new directory, not under any data folder
git -C $repo fetch origin claude/desk-study-power-rule-r2-20261014
git -C $repo worktree add --detach $wt 69af7d613b97
git -C $wt rev-parse HEAD                           # must print 69af7d613b97...
New-Item -ItemType Directory $out | Out-Null        # fails if it exists: good
$sha = git -C $repo rev-parse origin/master
. "$repo\scripts\ops\workload_admission.ps1"
$lease = Enter-WeatherHeavyWorkloadLease -RepoRoot $repo -Workload 'maker_pnl_power_rule_pilot'
if ($null -eq $lease) { throw 'heavy lease busy; do not run' }
try {
  $env:OPENBLAS_NUM_THREADS = '1'
  $py = "$repo\venv\Scripts\python.exe"
  $s  = "$wt\tools\research\maker_pnl_power_rule_pilot.py"
  & $py $s --maker-evidence-root "$repo\data\maker_evidence" --settlement-root "$repo\data\settlements" `
      --output "$out\dry-run.json" --dry-run --master-sha $sha
  "dry rc=$LASTEXITCODE"
  # STOP HERE unless every dry-run check in (b) passes.
  & $py $s --maker-evidence-root "$repo\data\maker_evidence" --settlement-root "$repo\data\settlements" `
      --output "$out\power-rule.json" --master-sha $sha
  "full rc=$LASTEXITCODE"
} finally { Exit-WeatherHeavyWorkloadLease $lease }
git -C $repo worktree remove $wt
```

Pre-checks (HOST_LOAD_POLICY rule 2): inside 00:30-09:00, commit charge < 70 %, at least 50 GiB free, the three
capture workers healthy before and after.

Stop rules (do not start the full run; report instead):
- dry-run rc is not 0, or stderr has `REFUSED:`;
- `upper_bound_on_disk_bytes_read` > 4 GB (4,000,000,000; 60 min at 1.1 MB/s);
- `dry-run.json` `diagnostics.missing_88a_days` is non-empty (any missing day).

## (b) Expected outputs

Dry run:
- `dry rc=0`; stdout is one JSON line `{"upper_bound_on_disk_bytes_read": <int>, "sealed_segments": <int>}`.
- `sealed_segments` about 100-125 (09-25 from 06:34Z, 24 per later day, plus 100 MB rotations); bytes about 0.3-0.6 GB.

Full run:
- `full rc=0` in about 3-7 min. Stdout is one JSON line with `n, sigma_d, c, sigma_up, n_req, branch, decision,
  result_sha256`.
- `n` = 4 (event dates 09-26..09-29).
- **`c` is a fixed function of `n` only**: `c = scipy.stats.chi2.ppf(0.10, n - 1)` (`chi2_lower_quantile`,
  `power_rule()` in the script). It does not depend on the data. With n = 4, `c` = `0.5843743741551835` exactly
  (scipy 1.17.1 on the WS). A different `c` with n = 4 is a STOP signal (wrong scipy or wrong code), not a result.
  For diagnosis only: n=2 0.01579077409343122, n=3 0.21072103131565273, n=5 1.0636232167792241,
  n=6 1.6103079869623227. Any `n` other than 4 is itself a stop-and-report.
- `sigma_d`, `sigma_up`, `n_req` depend on the data; no expected value.
- `branch` is one of `PANEL_STAYS_14` / `PANEL_EXTENDED_TO_N_REQ` / `UNDECIDABLE_AT_DELTA` /
  `SIGMA_D_UNDEFINED_PANEL_28`.
- `decision` is `WRITE_DATED_CLARIFICATION_MOVE_EMBARGO_END` only if `n_req` <= 14; otherwise
  `EMBARGO_END_UNCHANGED`. The clarification itself is a separate DECISION_LOG row, not written by the script.
- `power-rule.json` `envelope.peak_working_set_bytes` is non-zero and < 1 GB.
- A rerun to a new `$out` reproduces `result_sha256`.

Refusal: `REFUSED: ...` on stderr with rc 3 means a guard fired (integrity, date, output path). Report it; do not
retry with changes.
