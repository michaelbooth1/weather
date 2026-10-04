# Agent report 2026-09-110s — nightly sealed replay-bundle export

**PASS for fixture-only export, bounded wrapper and pinned registrar; NOT production-qualified. Exclusion-bearing bundles
require 110r's reader/engine support before replay. The owner explicitly left that compatibility change to 110r.**

Implemented on `codex/nightly-bundle-export-20260927`, based on
`origin/codex/maker-replay-harness-20260926` at `8ee7b8ad34c3d6ab8c073e93f90fc717586505ca`.
Implementation commit: **`18a9e8051d72a56f2c1ee29c3c41ee8d345887be`**.
Instruction source: [handoff 110s at the requested origin commit](https://github.com/michaelbooth1/weather/blob/f7b6eff7d1131991720f36226e14f38f9f90eb68/docs/roadmap/workstation-handoff-2026-09-110s-nightly-bundle-export.md).
The fetched handoff tip was exactly `f7b6eff7d1131991720f36226e14f38f9f90eb68`.
The implementation is stacked on [replay harness PR #100](https://github.com/michaelbooth1/weather/pull/100), not master.
Merge the dependency first and retarget normally; no rebase or history rewrite was performed.

## Delivered behavior

The requested facade is executable as `python -B -m weather.market.maker_plugin.replay_export night --day ...`.
It delegates IO outside the pure provider package and reuses the existing 110l implementation,
`weather.market.maker_replay_bundle`, whose actual module name differs from the handoff's anticipated path.

All discovered registered cities come from hash-checked sealed 88a discovery. A closed UTC date, stable source identities,
new day namespace, disjoint output and finite budgets are mandatory. Gzip and inline/content-reference journals are
covered. The complete invocation shares 1 GiB of input reads and 300 cooperative seconds; each city has a 64 MiB output
ceiling including manifest and metadata. Those ceilings can only be lowered. Any incomplete city or over-cap output
refuses the day without truncation. No source file, capture status or active release pointer is written.

Cities begin under `<out>/<day>/pending`. Only after every city passes does that directory become `bundles`; the final
receipt and its matching append-only `panel-ledger.jsonl` entry seal the day. A lock serializes writers. Every admitted
terminal attempt records free bytes before/after, cities, file hashes, gap/exclusion details, and recorded 88a run starts.
`REFUSED` and partial namespaces are retained and never reused. Rerunning a sealed or attempted day refuses. A killed
process can leave an unsealed namespace without a terminal receipt; no directory alone proves completion. Ledger
truncation is not repaired automatically. Free-after measurement precedes the small receipt/ledger writes.

Restart evidence comes from sealed `run_summary` records, and disconnect/gap/disk-brake/cap events are retained separately.
Segment rotation is not inferred to be a restart. Crashes without a summary are explicitly unknown. Per-condition missing
book intervals are recorded only inside declared activity; missing trade-stream health is never inferred from silence.

With `--release-root`, the captured source's release ID and manifest content hash bind the exact declared
`base_model.<city>.probability_calibration` JSON. Its inventory size and SHA-256 are checked before projecting
`market_bin.method` as `release_calibration_method`, with the artifact hash, onto the exported matching source row.
The plugin-input envelope repeats the method beside `record`. The projection checks only this lineage/component, not
the complete graph's serving readiness. Artifact reads cap at 2 MiB, share the nightly budget and are rechecked before
sealing. Missing/corrupt/ambiguous bindings and conflicting captured methods refuse. With no explicit release root,
previously captured methods are preserved and absent methods remain null; identity is never fabricated. The 88a writer
and central schema registry are unchanged. Tests cover both identity and market_shrink methods.

## Explicit 110r interface dependency

`--exclude-utc 05:00-08:00` gives every active condition two half-open UTC intervals. Each `bundle.json` condition gains
an additive `active_intervals` list of `{active_from, active_until}` UTC strings inside its existing outer bounds.
An empty list means zero quote activity. The outer bounds remain the envelope, not permission to quote through holes.
The receipt repeats the day intervals and declares `reader_compatibility=REQUIRES_110R_ACTIVE_INTERVALS`.

The unmodified 110l reader rejects the new field as `unexpected_fields`, which is tested. This is intentional fail-closed
compatibility, not a scoring pass. **110r must admit/validate the intervals and use them in engine windows, diagnostic
coverage, clock-baseline prefixes and execution-manifest bindings. Never strip the field or use the outer bounds as a
fallback.** No `src/maker_core/replay/` file was changed. This follows the owner's explicit response during this task.

## Fixture size and verification

Production size is **UNMEASURED**. The real-writer synthetic day has one UTC date, two fictional city datasets, three
conditions per city, two NYC book minutes, one Chicago minute, one recorded run summary and one stream gap. No production
market-day or calibration window was read. For that exact sparse fixture, without external release projection:

| Output | Bytes |
| --- | ---: |
| Chicago bundle, including export metadata | 24,725 |
| NYC bundle, including export metadata | 49,223 |
| All city bundle files | 73,948 |
| Whole fixture output day, receipts, ledger and lock | 90,501 |

This is expected bytes for the **fixture day**, not a linear extrapolation to continuous production capture. Source
support tables and repeated per-city reads may hit the input cap before production completes. Qualify actual size and
runtime in the admitted lane; do not raise a gate merely to force completion. No statistical or economic estimate was
made, so date/market confidence intervals and power calculations are not applicable.

Windows workstation checks, serially through `scripts/ops/workstation_heavy.ps1`:

- Focused provider/exporter/replay regression: **498 passed, 1 skipped**. The skip is host symlink-creation permission.
- Script plus repository import/path/schema audits: **46 passed** (the 10 script tests also occur in the first run).
- Documentation/roadmap/correspondence tests: **29 passed**. This includes the repository-wide agent-doc audit.
- `compileall -q app src tests`: **PASS**. Git diff whitespace checks: **PASS**.
- PowerShell execution tests use fixture helpers and a mocked Scheduler. They cover parser validity, winter/summer
  deadline boundaries, teardown-before-release and poisoning on unproved teardown, WhatIf, both pins, exact readback and
  refusal of late-catch-up readback. They do not prove a production S4U run or live-host resource admission.

Initial fixture setup hit a missing temp parent and then Windows long paths; a short task-specific temp root resolved
both. Test fixture defects (missing stream subscription and a missing mock TaskPath) were corrected. A real array
readback normalization issue was also fixed before the final passing run. The sandbox principal was refused by admission;
the same unchanged wrapper succeeded under the attending user's approved execution context. No guard was bypassed.

For manual reproduction on the assigned non-capture workstation, from this checkout with its project interpreter:

```powershell
$repo = (git rev-parse --show-toplevel).Trim().Replace('/', '\')
$python = (Resolve-Path .\venv\Scripts\python.exe).Path
$tests = @('-m', 'pytest', '-q', '--tb=short',
  'tests/market/test_maker_plugin.py', 'tests/market/test_maker_plugin_dry_run.py',
  'tests/market/test_maker_replay_bundle.py', 'tests/market/test_maker_replay_night.py',
  'tests/operations/test_replay_bundle_export_scripts.py',
  'tests/maker_core/test_replay_bundle.py', 'tests/maker_core/test_replay_engine.py',
  'tests/maker_core/test_replay_baselines.py', '--basetemp', 'C:/tmp/pytest-110s-reproduction')
$encoded = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes((ConvertTo-Json -InputObject $tests -Compress)))
& .\scripts\ops\workstation_heavy.ps1 -Kind pytest -PythonPath $python -ArgumentsBase64 $encoded -RepoRoot $repo
```

Use an unused temporary root, then remove only that proven fixture tree after the run. The audit files are
`tests/operations/test_import_architecture.py`, `test_path_policy.py`, `test_schema_registry.py`,
`test_agent_docs_audit.py`, `tests/reporting/test_roadmap_backlog.py`, and `test_correspondence_index.py`, run in separate
focused wrapper invocations. The correspondence generator and its read-only check run after this report's first commit;
the publication commit and draft PR carry final closeout status.

## Roll classification and production commands

There are no retained production closures in this clean worktree and the task permits fixtures only. No production
status or mirror was accessed. **Python roll verdict is UNDECIDABLE here**; no synthetic closure is presented as live
evidence. Before integration, the production agent must obtain the mechanical verdict below against its live closures.

| Changed file | Roll disposition |
| --- | --- |
| `src/weather/market/maker_plugin/replay_export.py` | UNDECIDABLE: production closures required |
| `src/weather/market/maker_replay_bundle.py` | UNDECIDABLE: production closures required |
| `src/weather/market/maker_replay_night.py` | UNDECIDABLE: production closures required |
| `src/weather/market/maker_replay_release.py` | UNDECIDABLE: production closures required |
| `scripts/ops/replay_bundle_export_nightly.ps1` | Roll-free by file-class contract |
| `scripts/ops/register_replay_bundle_export_nightly.ps1` | Roll-free by file-class contract |
| `tests/market/test_maker_replay_night.py` | Roll-free: test only |
| `tests/operations/test_replay_bundle_export_scripts.py` | Roll-free: test only |
| `docs/operations/maker-replay-bundle.md` | Roll-free: owning runbook |
| This report and regenerated `docs/roadmap/correspondence-index.md` | Roll-free: documentation |

Run on production **after separate guarded adoption/qualification**, from its canonical checkout. These are the exact
registration commands, not commands executed by the workstation. The current adopted tip must have completed the normal
review/CI/integration gates before using it as the source pin. Every later tip adoption requires reviewed re-registration.

```powershell
.\scripts\ops\roll_verdict.ps1 -Branch origin/codex/nightly-bundle-export-20260927
# Obey its verdict and the guarded integration runbook before the following block.
$repo = (git rev-parse --show-toplevel).Trim().Replace('/', '\')
git merge-base --is-ancestor 18a9e8051d72a56f2c1ee29c3c41ee8d345887be HEAD
if ($LASTEXITCODE -ne 0) { throw 'reviewed exporter is not adopted' }
$reviewedTip = (git rev-parse HEAD).Trim()
$runnerHash = '7476bd39fe0498dbd776d95d2c7734e6a25fad35fc071015054362d68d7c6af5'
$registration = @{
  RepoRoot = $repo
  DataRoot = (Join-Path $repo 'data')
  ReleaseRoot = (Join-Path $repo 'artifacts\releases')
  OutputRoot = (Join-Path $repo 'scratch\replay-panel')
  ExpectedSourceTip = $reviewedTip
  ExpectedRunnerSha256 = $runnerHash
}
.\scripts\ops\register_replay_bundle_export_nightly.ps1 @registration -WhatIf
.\scripts\ops\register_replay_bundle_export_nightly.ps1 @registration
Get-ScheduledTask -TaskName WeatherReplayBundleExportNightly | Get-ScheduledTaskInfo
```

The output parent must already exist; the registrar refuses absent/redirected roots and input/output overlap. Keep the
panel and partial attempts as evidence, never generic scratch cleanup. The scheduled task exports yesterday UTC at
00:35 Toronto, S4U/Limited, IgnoreNew, seven-minute outer Scheduler limit, no StartWhenAvailable. Busy lease is a visible
failure, not a wait or catch-up. This can contend with existing heavy jobs; changing 00:35 requires a reviewed registrar
change. The wrapper admits only 00:30–04:54, holds the common lease, owns the child in the existing kill-on-close Job,
uses a 330-second cap/2 GiB monitor, and reserves teardown before 04:55. It checks fresh commit charge below 70% and
50 GiB output-volume headroom. These are implemented limits, not measured production performance.

**Not done:** no production data/credentials or frozen mirror access, no real export, calibration read, scored look,
model fit, promotion, paid source, capture restart, production write, real task registration, task mutation, merge or
live exchange action. The authorized branch push and draft PR are source-control publication only.
