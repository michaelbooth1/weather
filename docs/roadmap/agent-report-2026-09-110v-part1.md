# Agent report 2026-09-110v Part 1 — execution-tape write throttle

**PASS on fixtures; ready for production qualification for the September 28/29
quiet window. No production adoption or throughput claim.**

This answers Part 1 of `workstation-handoff-2026-09-110v-efficiency-fixes.md`
from `origin/codex/handoff-110k-20260926` at `795e87d6`. Open questions: none.
Branch: `codex/exec-tape-write-throttle-20260927`. Implementation commit:
`400b0226` (resolve the full hash with `git rev-parse 400b0226`). Declared base:
`origin/codex/integration-91a-110f-20260926` at `e3bc4dc8`, the user-authorized
integration dependency pending tonight's landing. Retarget to master after it
lands; merge the target forward, never rebase published history.

## Result and durability

Both the frame-ingestion and heartbeat paths coalesce root and market status
writes for ten seconds. Connection, seed-error, retirement, degradation and
stop transitions publish immediately. All status fields remain; the descriptive
counter-basis string now says that fsync is grouped. Clean close publishes final
counters. Startup reconciles identity counters and rejection evidence with
the physical tapes, so cached status does not hide surviving rows or errors.

One lazy background flusher per worker process groups dirty-file fsync at
one-second monotonic deadlines, including files that receive no further rows.
Python buffers still flush on append; JSON encoding, row order, hashes and
rotation boundaries are unchanged. Rotation and clean close force pending
syncs. The documented default accepts **≤ 1 s of rows at risk on a crash**
under normal scheduling and successful storage sync. Missing stream rows
cannot be recreated; partial JSONL remains fail-closed. A sync error propagates
on the next capture operation. Recovery gaps conservatively begin at the last
persisted heartbeat, which may lag ten seconds.

## Verification

- Guarded workstation focused run: **166 passed**. Every focused run included
  docs/knowledge, schema, module-size, imports, paths and roadmap audits.
- Repository compileall (`app src tests`): PASS. Diff whitespace checks: PASS.
- A deterministic 999-frame burst in 9.99 seconds produced zero status writes
  after the connected transition, then exactly two at ten seconds (root and
  market). The former call paths would publish four times per frame.
- Grouping fixture: four rows before one second produce zero fsync calls,
  then one sync without any new append. Clean close and rotation sync pending
  rows. An actual background-thread fixture also proves idle sync.
- All trade, repeat-identity, gap, seed and rejection JSONL bytes, including
  rotated parts, match the former per-row-fsync write reference exactly.
- Crash fixtures reopen stale status with either all OS-visible rows or a lost
  unsynced suffix; counters match actual rows. Torn tails remain blocked.
- The first run exposed stale root identity counters (fixed) and unstaged new
  files in the tracking audit (staged); the complete focused run then passed.

These are deterministic engineering fixtures, not market samples. Date/market
clusters and statistical intervals do not apply. Production's supplied
3.7 MB/s measurement is the handoff premise, not a workstation measurement;
post-adoption I/O measurement remains production's responsibility.

## Reproduction

From this branch's repository root on the workstation, using its approved
project interpreter (`$python` must be the absolute project Python path):

```powershell
$root = (Get-Location).Path
$python = (Resolve-Path .\venv\Scripts\python.exe).Path
$testArgs = @('-m','pytest','-q',
 'tests/market/test_execution_tape_write_cadence.py',
 'tests/market/test_execution_tape_capture.py',
 'tests/market/test_execution_tape_markout.py',
 'tests/operations/test_execution_tape_supervisor.py',
 'tests/operations/test_agent_docs_audit.py',
 'tests/operations/test_schema_registry.py',
 'tests/operations/test_module_size_audit.py',
 'tests/operations/test_import_architecture.py',
 'tests/operations/test_path_policy.py',
 'tests/operations/test_knowledge_structure_audit.py',
 'tests/reporting/test_roadmap_backlog.py',
 "--basetemp=$env:TEMP/weather-110v-part1-tests")
$encoded = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes(
 (ConvertTo-Json -Compress -InputObject $testArgs)))
& .\scripts\ops\workstation_heavy.ps1 -Kind pytest -PythonPath $python -ArgumentsBase64 $encoded -RepoRoot $root
& .\scripts\ops\workstation_heavy.ps1 -Kind compileall -PythonPath $python -ArgumentsBase64 'WyItbSIsImNvbXBpbGVhbGwiLCItcSIsImFwcCIsInNyYyIsInRlc3RzIl0=' -RepoRoot $root
```

An isolated worktree without its own venv uses the existing project's absolute
interpreter path, as in the actual run. Capture-host verification must instead
use its admitted bounded suite and live roll-verdict evidence.

## Roll and adoption handback

`scripts/ops/roll_verdict.ps1 -Branch codex/exec-tape-write-throttle-20260927
-Base origin/codex/integration-91a-110f-20260926` reports **UNDECIDABLE: no live
closure evidence** here. No production data was imported to manufacture a
verdict. Treat the change as roll-sensitive per the handoff and rerun the tool
on production before the guarded quiet-window merge.

| Changed file | Classification / closure evidence |
| --- | --- |
| `src/weather/market/execution_tape_store.py` | Roll-sensitive candidate; execution-tape owner, actual retained closure membership requires production verdict. |
| `src/weather/market/execution_tape_io.py` | New helper imported by the changed store; same adoption boundary, not independently roll-free. |
| `tests/market/test_execution_tape_capture.py` | Test only; live closure membership not asserted. |
| `tests/market/test_execution_tape_write_cadence.py` | New fixture tests; live closure membership not asserted. |
| `docs/operations/data-storage-class-contract.md` | Roll-free documentation. |
| This report and generated correspondence index | Roll-free documentation. |

No schema-registry change. No venue/network collector call, credentials,
production data read/write, mirror access, registration, task mutation,
restart, merge, model fitting, promotion or live trading was performed.
Only origin fetch/push and draft-PR publication use the network.
