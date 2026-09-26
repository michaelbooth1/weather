# Mission 94b — monitoring fixes

**Verdict: implemented and verified on the Windows workstation; production adoption pending.**
Answers [handoff 94b](workstation-handoff-2026-09-94b-monitoring-fixes.md), Q-11, and host-audit findings 3, 9, 10.
This is the mission handback, not current production state; read [STATE_OF_PLAY](../operations/STATE_OF_PLAY.md) for that.

Branch: `codex/monitoring-fixes-20260924`. Implementation commit: `e14219b54273dfb6901922e8e91ff45334f29d46`.
The final branch tip includes this report and is returned in the task handback; resolve it with
`git rev-parse origin/codex/monitoring-fixes-20260924` after fetching.
Base: `683e8f3afc1bbc6508494e7d23f57ea3dac5cb66` from
`origin/codex/reward-test-attended-handoff-20260921`, fetched first. **User override:** the task explicitly named
this base; it takes precedence over the handoff's `origin/master` instruction. The topic therefore inherits the
handoff branch's documentation commits; review the mission delta against the named base.

## Changes and falsifying controls

| Change | What it catches | Positive/negative controls |
| --- | --- | --- |
| Status imports the sweep's CRITICAL table rows into flags, changing verdict to ATTENTION / exit 2 | Stale learning/scoreboard findings previously buried in the sweep | Critical row flags; clean/WARN-only does not; missing, malformed, stale and count-mismatched snapshots flag |
| Sweep always emits `capture/reward_records` | No registered producer, disabled producer, or stale/missing successful 88a reward records | No task is CRITICAL with “no producer registered”; a fresh heartbeat without records stays CRITICAL; successful recent record passes; 5/15-minute warning/critical thresholds; HTTP error/future record cannot make it green |
| Status recognizes later exact-attempt retirement evidence | The old UNPROVEN rollback alarm after an owner/agent retirement | Owner and agent receipts pass; wrong marker/report hash, other attempt, incident mode, recorded merge, failed capture attestation, unapproved/old/future/dry receipt and active marker do not clear |
| Watchdog rotates before oversized append | Reopening the growing health JSONL in place | Archive bytes preserved exactly; two new appends remain in the fresh log; a held file that prevents rename leaves the oversized file unchanged and fails |

The owner receipt named by the recovery table was read **read-only over SSH**, along with a compact projection of
`quiet_window_merge_last.json`. Its schema is `owner_approved_marker_retirement_v0`; PowerShell serialized
`marker_bytes` as an object containing `value`. The UTF-8 text hashes to
`8b0e95c15ebc493c7ee969408c51b1fa91c24f70eb61b2fd3fdfcc19acc769de`, the receipt's marker hash.
The old report has no `marker_sha256`: compatibility matches all six root/branch/tip/baseline/pre-merge fields plus
a marker timestamp within five minutes before the report. A supplied report hash must match. No active marker or
incident publication gate is suppressed, and no historical report is rewritten.

The agent receipt shape is documented in the [status/watchdog runbook](../ops/streak-soak.md):
`agent_marker_retirement_v0`, exact embedded marker bytes/hash, true conditions/capture attestations, no MERGE_HEAD,
allowed dirty paths, and head equal to baseline and origin/master. This is a consumer contract, not a new retirement
command or expanded authority. The [fail-forward table](../operations/fail-forward-recovery.md) still owns permission.

Reward reads use 88a at `origin/codex/maker-evidence-capture-20260923`: explicit UTC hour segments, successful
`rewards` rows with content hashes and `captured_at_utc`, including unchanged-payload reference rows. The monitor
reads at most 32 segments, 512 reward files, 32 KiB per file, current/previous two UTC hours. Older or compressed
evidence cannot prove freshness. This check proves a recent successful reward read, not complete band coverage.

Rotation is 16 MiB, exclusive append lock, rename to a dated unique archive, no deletion/overwrite/fallback append.
The briefing reads only bounded tails from the active log and newest archive and labels possible omissions. A failed
append exits 2 and does not advance the dedup/heartbeat state. This is size bounding, not a disk-retention policy.

## Verification and reproduction

Windows workstation, attending principal, no concurrent RE-1; all Python verification used
`scripts/ops/workstation_heavy.ps1` with a short explicit basetemp and its shared lease/Job cleanup.

- Four-file focused suite: **122 passed**, 236.90 s.
- After the final bounded-read/receipt edits: **34 synthetic cases passed**.
- `compileall -q app src tests`: exit 0.
- Agent documentation audit: PASS; generated roadmap `--fail-on-lint --check`: matches, no lint issues.
- `git diff --check`: clean. No full local suite claimed; PR CI is separate, and Linux CI skips Windows-executing cases.

The initial temporary docs-test adapter wrongly compared the backlog function's returned report object to integer 0;
both commands had reported PASS/OK. Corrected to check `lint_issues == []` and rerun before handback.

From the checked-out branch on the workstation, the supported operator invocation is:

```powershell
$missionRoot = (Resolve-Path .).Path
$missionPython = (Resolve-Path .\venv\Scripts\python.exe).Path
$missionArgs = '["-m","pytest","tests/operations/test_monitoring_fixes.py","tests/operations/test_status_script.py","tests/operations/test_staleness_sweep_script.py","tests/operations/test_health_watchdog_script.py","-q","--basetemp=C:/tmp/m94b"]'
$missionEncoded = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($missionArgs))
& .\scripts\ops\workstation_heavy.ps1 -Kind pytest -PythonPath $missionPython -ArgumentsBase64 $missionEncoded -RepoRoot $missionRoot
```

For a linked worktree, resolve the interpreter from the existing parent checkout instead of assuming its own venv.
Production runs these focused Windows tests through its admitted verification path; the workstation allowance is not
capture-host permission. Delete only the owned short test-temp directory after the run.

## Integration disposition

| Mission file | Expected roll classification / closure |
| --- | --- |
| `scripts/ops/status.ps1` | Roll-free PowerShell; no Python capture closure |
| `scripts/ops/staleness_sweep.ps1` | Roll-free PowerShell; no Python capture closure |
| `scripts/ops/health_watchdog.ps1` | Roll-free PowerShell; no Python capture closure |
| `tests/operations/test_monitoring_fixes.py` | Test-only; no runtime import added |
| `docs/ops/streak-soak.md`, this report | Roll-free documentation |

These are expected classifications from the standing contract, **not a host-derived roll verdict**. Production must
run `scripts/ops/roll_verdict.ps1 -Branch origin/codex/monitoring-fixes-20260924` against its retained closures before
adoption. The inherited handoff delta must also be considered. The deployed watchdog is newer and hash-pinned:
carry the rotation change into that deployment while preserving its pinning/RepoRoot parameters; do not re-register
the older unpinned registrar from this base. See [what actually executes](../operations/OPERATIONS_DESIGN.md).

No registration, production write, restart, master merge, live command, credential/.env read, or mirror write occurred.
Worktrees and unrelated user state are retained. Push and draft PR route source review to the production owner;
they do not prove operational adoption or repair the blocked learning lane itself.
