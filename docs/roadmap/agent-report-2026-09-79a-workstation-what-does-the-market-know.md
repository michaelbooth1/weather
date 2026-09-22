# Workstation handback: missing-information mission 2026-09-79a

**BLOCKED ON THE PRODUCTION EXPORT. SSH works; no market-data result exists.**
This is a preparation checkpoint, not completion of the five descriptive checks.
At **2026-09-21 00:46:32 America/Toronto**, an authenticated `scp` request for
`production-pc:C:/tmp/mi-handoff/MANIFEST.json` returned `No such file or directory`.
The same exact path was absent at 00:23, 00:28, 00:31, 00:36 and 00:42.
No archive was downloaded, opened, or scored. Whether the staging job was running
was not inspected: the handoff permits only copies from the staged directory.

## Authority and provenance

- User request: read and execute the production-host scratch handoff, and prove
  SSH immediately. The local checkout did not contain that handoff. An initial
  sandboxed SSH attempt could not read the existing SSH configuration; the
  same command outside the sandbox authenticated and returned hostname `Michael`.
  No key or credential contents were opened. SSH needs no repair.
- The requested handoff and reservation status were read from production to
  establish the task. Reservation status was **NONE RESERVED**. After reading
  the handoff's narrower transfer boundary, subsequent remote operations were
  only `scp` of its exact staged manifest.
- Branch: `codex/missing-information-checks-20260921`, stacked on fetched
  `origin/codex/missing-information-handoff-20260921` at
  `278c2388b439f71f81233ae96ab3ff0d2d500794`. This is not based directly on master.
- Worktree: `C:/Users/Michael/Documents/github/weather/scratch/w/missing-information-checks-20260921`.
  Created with LFS smudging disabled. The original master checkout was clean
  at intake; it was not changed by implementation work.
- Freeze commit: `058f638a`. Plan SHA-256:
  `024dbac70c636e42c4f514d66d79fb955c75362c6534892954c05d0bc9e33a81`.
  The settings were committed before opening any production research data.
- Implementation checkpoint: `a9955d4c2b08c598aac2f516517fcf20b4c7998f`.
- The owner explicitly approved one scope extension in this task: add
  `tools.research.missing_information.run` to the workstation allowlist and its
  matching hook allowlist, with validation tests. No host, principal, mutex,
  cleanup, live-argument or poison-recovery condition was weakened.

## Prepared and verified

The [research README](../../tools/research/missing_information/README.md) owns
the implementation status and pre-result interpretation notes. The offline
driver verifies the three archive hashes before safe extraction, admits only
boolean `promotion_countable`, preserves native-unit values, builds a per-snapshot
table, and implements checks 1, 2, 4a and 5. Check 3 is conditional on P0 and is
not implemented or skipped on scientific grounds. Actual snapshot-to-artifact
trace 4b and conditional guidance download 4c also remain pending.

Synthetic validation covers Celsius/Fahrenheit bands, rounding, CDF tails,
probability mass, floor behavior, missing inputs, peak-time rules, crossed
bootstrap multiplicities, cadence weighting, kernel chronology, exclusion of
noncountable dates, archive traversal rejection, and the end-to-end scoring path.
The expanded focused run passed **98 tests with 11 expected skips** (outer-lease
and platform-dependent safety tests). After review, the final research-focused
run passed **27/27**. PowerShell parsing and `git diff --check` passed.
The exact new driver passed `preflight` through the required workstation wrapper;
its printed module paths resolved to this worktree. No direct heavy Python run
was used.

The independent light IEM download completed **24 files / 3,653,696 bytes**:
routine and special observations separately for the 12 specified stations,
UTC 2026-08-01 through exclusive 2026-09-20 12:00. The endpoint and report-type
parameters were verified against the [official IEM documentation](https://mesonet.agron.iastate.edu/cgi-bin/request/asos.py?help).
Requests were serial, separated by at least 1.1 seconds. Each file's URL, SHA-256,
report type and download time is in
`C:/Users/Michael/Documents/github/weather/scratch/missing-information-20260921/iem/manifest.json`.
That manifest's SHA-256 is
`2016684e9e1e32a9d1e14bd646b426ab66efb819c0e01a67d4d7989a1d8bbe91`.
This acquisition establishes no information-gap result.

## Missing evidence and scientific disposition

| Required archive | Verified SHA-256 | Disposition |
| --- | --- | --- |
| `mi-core.tgz` | unavailable | not received |
| `mi-tape.tgz` | unavailable | not received |
| `mi-books-sample.tgz` | unavailable | not received |

Admitted research support is **0 date clusters, 0 market clusters, 0 market-days**.
The excluded market-day list is unavailable, not empty. No confidence interval,
power estimate, MDE, gap ratio, tail attribution, guidance comparison or candidate
verdict is available. Synthetic dates are never counted as research support.
The six hypotheses remain unassessed; see the
[one-page disposition](../research/missing-information-results-2026-09-79a.md).
No candidate or alpha allocation is proposed on absent evidence.

Before publishing eventual measurements, complete the documented sensitivities
(inclusive-hour boundaries, nonmonotone/partial-day peaks, pre-07:00 station
maximum provenance, lag censoring intervals, weather-tag thresholds), validate
the real export schema and bindings, and complete 4b plus conditional 3/4c.
The current tests are not a substitute for those steps.

## Roll verdict and unchanged authority

The repository-owned `roll_verdict.ps1` was executed in this isolated worktree.
It returned **exit 1, UNDECIDABLE: no live closure evidence**, naming the four
missing capture closure files. Production closure files are outside this mission's
authorized copy directory, and the frozen mirror was not substituted.

| Changed files | Production closure membership / roll verdict |
| --- | --- |
| `.codex/hooks/pre_tool_use_host_load.py` | unverified / UNDECIDABLE |
| `scripts/ops/workload_admission.ps1` | unverified / UNDECIDABLE |
| `tests/operations/test_codex_host_load_hook.py` | unverified / UNDECIDABLE |
| `tests/operations/test_workload_admission_script.py` | unverified / UNDECIDABLE |
| `tests/operations/test_missing_information_admission.py` | unverified / UNDECIDABLE |
| `tests/reporting/test_missing_information_methods.py` | unverified / UNDECIDABLE |
| `tests/reporting/test_missing_information_pipeline.py` | unverified / UNDECIDABLE |
| `tools/research/missing_information/__init__.py`, `methods.py`, `extract.py`, `checks.py`, `regimes.py`, `run.py`, `fetch_iem.py` | each unverified / UNDECIDABLE |
| `tools/research/missing_information/analysis_settings.json`, `README.md`, this report and the one-page disposition | each unverified / UNDECIDABLE |

No production registration, Scheduler mutation, production write, restart,
merge, hook installation, provider credential, exchange call, order, serving
change, model fit or candidate occurred. The workstation's frozen data and both
mirrors were untouched. The required wrapper retained its own local worktree
lease bookkeeping; research inputs and outputs are in separate scratch.

## Reproduction and continuation on the workstation

These paths exist on the workstation. The three archives and their manifest
are the only missing inputs. Commands below are for an attending PowerShell
operator; Codex calls use the literal wrapper form in `docs/development.md`.

```powershell
$miRepo = 'C:/Users/Michael/Documents/github/weather/scratch/w/missing-information-checks-20260921'
$miPython = 'C:/Users/Michael/Documents/github/weather/venv/Scripts/python.exe'
$miScratch = 'C:/Users/Michael/Documents/github/weather/scratch/missing-information-20260921'
Set-Location $miRepo
function Invoke-MissingInformation([string[]]$Arguments) {
    $encoded = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes((ConvertTo-Json -InputObject $Arguments -Compress)))
    & "$miRepo/scripts/ops/workstation_heavy.ps1" -Kind weather_heavy -PythonPath $miPython -ArgumentsBase64 $encoded -RepoRoot $miRepo
    if ($LASTEXITCODE -ne 0) { throw 'Research stage failed; retain partial output.' }
}
Invoke-MissingInformation @('-m','tools.research.missing_information.run','preflight')
# Once staging publishes its manifest, outside 12:00-18:00 Toronto, one file at a time:
scp -o BatchMode=yes -o ConnectTimeout=10 production-pc:C:/tmp/mi-handoff/MANIFEST.json "$miScratch/downloads/MANIFEST.json"
scp -o BatchMode=yes -o ConnectTimeout=10 production-pc:C:/tmp/mi-handoff/mi-core.tgz "$miScratch/downloads/mi-core.tgz"
scp -o BatchMode=yes -o ConnectTimeout=10 production-pc:C:/tmp/mi-handoff/mi-tape.tgz "$miScratch/downloads/mi-tape.tgz"
scp -o BatchMode=yes -o ConnectTimeout=10 production-pc:C:/tmp/mi-handoff/mi-books-sample.tgz "$miScratch/downloads/mi-books-sample.tgz"
Invoke-MissingInformation @('-m','tools.research.missing_information.run','prepare','--input',"$miScratch/downloads",'--output',"$miScratch/unpacked")
Invoke-MissingInformation @('-m','tools.research.missing_information.run','extract','--input',"$miScratch/unpacked",'--output',"$miScratch/extracted")
Invoke-MissingInformation @('-m','tools.research.missing_information.run','analyze','--input',"$miScratch/extracted",'--output',"$miScratch/analysis",'--iem',"$miScratch/iem")
```

The production operator must later obtain the actual roll verdict from its
current closures before any integration. This checkpoint requests no merge.
