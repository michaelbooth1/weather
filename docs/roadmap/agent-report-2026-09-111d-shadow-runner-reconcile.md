# Agent report 2026-09-111d — reconcile the shadow runner (#115) with the replay execution pack (#112)

**PASS. #112 is merged into #115's branch, and #112's two `ReplayEngine` changes are ported into the
`lifecycle.py` split with identical behaviour. #112's tests pass unchanged, alongside #115's tests and the
repo-wide audits (247 passed, 1 skipped). One premise correction: #112 did not add the five
`ReplayConfig` fields the mission names. See below.**

## Provenance and scope

- Mission: the owner's 111d dispatch prompt (no handoff file). Preamble read from `origin/master`.
- Branch: `codex/shadow-runner-20260927` (PR #115). Pre-merge head `c0a54642bc199718e06cc965bb1322a4b34ee18a`.
- Merged: `origin/codex/replay-execution-pack-20260927` (PR #112) at `96bfef806e63529cce41e03be4cef863f442e980`.
  Merge base `98f768c7cc5be07efb4510f9ba79c24e3ed41884`.
- Merge commit: `5669011b`, which is a fast-forward of the remote branch. The report commit follows it.
- Separate non-capture workstation, fixtures only. No production evidence was opened. Date clusters, market
  clusters and scored market-days are all zero. Statistical intervals do not apply to deterministic
  conformance tests.
- Open-question ids: none.

## Premise correction

The mission says #112 added the `ReplayConfig` fields and checks `fill_bound`, `clock_pulls`,
`max_book_gap_seconds`, `max_events` and `hazard_per_minute` to `engine.py`. It did not. All five are
already present at the merge base `98f768c7`, and #115's `lifecycle.py` carries them unchanged.
`git diff 98f768c7 96bfef806e -- src/maker_core/replay/engine.py` shows exactly two hunks:

1. **Condition windows.** `ReplayEngine.__init__` iterated `(c.active_from, c.active_until)`. It now
   iterates `bundle.windows(c)`, which returns a verified execution manifest's active intervals, or the
   legacy envelope when `Bundle.active_intervals is None`.
2. **Exclusion-start fills.** In `on_trade`, when any bundle declares `active_intervals`, a print at an
   instant where the condition is not active (`self.active(cid, at)`, not `at - EPSILON`) does not fill.
   A declared maintenance or settlement exclusion therefore includes its starting instant.

Both hunks are now in `src/maker_core/replay/lifecycle.py` verbatim. After the port,
`diff <#112 engine.py> lifecycle.py` shows only #115's intended refactor: the class is renamed to
`Lifecycle`, `decide` and the RE-1 blind tick move behind the `decide_inputs` and `blind_tick` hooks, and
`replay()` moves to the thin `engine.py`. Against #112's tip, the merged `src/maker_core/replay/` differs
only in `engine.py` and `lifecycle.py`.

**Shadow impact:** `ShadowEngine` builds its `Bundle` without `active_intervals`, so the default is `None`.
It keeps the legacy envelope windows, and the new exclusion-start guard is inert for it. The shadow runner's
behaviour is unchanged.

## Other conflicts

- `docs/README.md`: both routing rows kept (shadow runner design, and replay hurdles / execution addendum).
- `docs/roadmap/correspondence-index.md`: regenerated with `weather.reporting.roadmap.correspondence_index`.
- `docs/research/maker-replay-*`: not modified. All four files are byte-identical to #112's tip.
- Tests: no test file was edited. Against #112's tip, the only test differences are #115's additions
  (`test_shadow*.py`, `tests/market/test_maker_shadow.py`, `test_shadow_admission.py`, `test_import_architecture.py`).

## Verification

Run through `scripts\ops\workstation_heavy.ps1 -Kind pytest` on the merged tree:
`tests/maker_core/test_replay_*.py` (#112's replay, execution-pack, calibration, pull-efficiency,
enrollment, authorization and report tests, i.e. the hurdle tests), `tests/maker_core/test_shadow*.py`,
`tests/market/test_maker_shadow.py`, `tests/operations/test_shadow_admission.py`, and the audits
`test_import_architecture`, `test_schema_registry`, `test_agent_docs_audit`, `test_path_policy`,
`test_module_size_audit` and `test_knowledge_structure_audit`. Result: **247 passed, 1 skipped**.

Environment note, not a code defect: with a long `--basetemp` (about 150 characters) the shadow tests fail
with `FileNotFoundError` in `session.write_bytes`, on #115's unmodified tip as well. The cause is the
Windows 260-character `MAX_PATH` on content-addressed artifact paths. A short `--basetemp` such as
`C:\tmp\111d\bt` passes. PR #115's CI was green before this merge.

GitHub CI on the pushed head: see the PR checks. The final conclusion is in the handback reply.

## Per-file roll verdict

`scripts\ops\roll_verdict.ps1 -Branch codex/shadow-runner-20260927` returned **UNDECIDABLE** here (exit 1).
The workstation has no `data\snapshots\*` closure evidence. **Production must re-derive the verdict.**
Reasoned expectation for the files this merge adds to #115:

| Files | Expectation |
| --- | --- |
| `src/maker_core/replay/*` (`lifecycle.py` port, plus #112's `bundle`, `diagnostics`, `baselines`, `report`, `authorization`, `__main__`, new `calibration`, `execution_manifest`, `execution_receipt`, `pack_cli`, `pack_io`, `pull_efficiency`, `approved_registrations`) | Exam tooling, not expected in any capture closure. Confirm with `roll_verdict.ps1`. |
| `scripts/ops/workstation_heavy.ps1` | Roll-free (`.ps1`). |
| `docs/**`, `tests/**` | Roll-free. |

This merge does not touch `schema_registry*`. #115 itself already changes `src/weather/schema_registry_recent_data.py`,
which is in all four closures. That change is #115's, not this merge's.

## What was NOT done

No merge to `master`, no registration, no Scheduler change, no production write, no restart, no venue call,
no credential access, no force-push or history rewrite. `docs/research/maker-replay-*` is untouched.
#112's branch was not modified.

## Reproduction

From a checkout of `codex/shadow-runner-20260927` on the workstation:

```powershell
$files = @(Get-ChildItem tests\maker_core\test_replay_*.py, tests\maker_core\test_shadow*.py | ForEach-Object { "tests/maker_core/" + $_.Name }) + @(
  'tests/market/test_maker_shadow.py','tests/operations/test_shadow_admission.py','tests/operations/test_import_architecture.py',
  'tests/operations/test_schema_registry.py','tests/operations/test_agent_docs_audit.py','tests/operations/test_path_policy.py',
  'tests/operations/test_module_size_audit.py','tests/operations/test_knowledge_structure_audit.py')
$json = ConvertTo-Json -Compress (@('-m','pytest','-q','-p','no:cacheprovider','--basetemp','C:\tmp\111d\bt') + $files)
$b64 = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($json))
.\scripts\ops\workstation_heavy.ps1 -Kind pytest -PythonPath .\venv\Scripts\python.exe -ArgumentsBase64 $b64 -RepoRoot (Get-Location).Path
git diff 98f768c7 96bfef806e -- src/maker_core/replay/engine.py
```
