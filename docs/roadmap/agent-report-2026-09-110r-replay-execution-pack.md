# Agent report 2026-09-110r — replay execution pack

**PASS for fixture implementation and review; production calibration, signing, enrollment and the scored look remain gated and were NOT performed.**
Owner option A (2026-09-27) is implemented in a new unsigned clarification. Both frozen replay documents are unchanged.
The owner's follow-up explicitly confirmed an empty approval registry and a separate production enrollment template.

## Authority, branch and dependencies

- Handoff read after `git fetch origin`: `origin/codex/handoff-110k-20260926` at
  `f7b6eff7d1131991720f36226e14f38f9f90eb68`. Mission: `workstation-handoff-2026-09-110r-replay-execution-pack.md` at that ref.
- Fetched master at intake: `965374a0edc6fcb65d66e257be9e404cc9af8d60`; the user's main checkout was clean and remained unchanged.
- Required stacked base: `origin/codex/integration-91a-110f-20260926` at `f0119b4077919fa62c4d36b745047074dff13ac0`,
  merged with preregistration `bc9fd5b135cb3a0df542809d901420a96c739e84`. The local dependency merge is
  `0f7d0bac2d0811b8a94985afd395f49fb7b2c6e3`; all 110r file classifications below are relative to that merge.
- Branch: `codex/replay-execution-pack-20260927`; isolated worktree: `scratch/w/replay-execution-pack-110r` beneath
  the workstation checkout, using its ignored worktree area. LFS smudging was disabled during creation.
- Implementation commit: `f96c1f268af724904938251d8660c52ecdbf08c9`.
- Separate enrollment-template/test commit: `bc47eb7ab99837d5b507212bddbc422f18753f49`.
- The preregistration dependency is [draft PR 109](https://github.com/michaelbooth1/weather/pull/109).
  The draft PR targets that preregistration branch to keep its review delta small and declares the required integration
  branch as a second dependency. Eight inherited integration paths (decision log, economics-drift fix/tests/docs,
  module-size ownership and correspondence index) are present in addition to 110r. It is not a standalone master
  change. After the planned dependency landings, synchronize with master and rerun the relevant
  checks. Do not rewrite a published branch without the owner's explicit exception.

## Delivered behavior

The [clarification](../research/maker-replay-clarification-1-2026-09-27.md) fixes calibration to September 27–29,
quote dates to September 30–October 13, settlement-only to October 14, and the single Toronto look to October 15.
It specifies pooled all-city fallback for sparse cities, the unchanged pooled sparsity minima, and prospective
05:00–08:00 UTC maintenance exclusions. Future target dates beyond settlement-only remain in discovery inventory
but are excluded from quoting. No real evidence was read to choose these rules.

`calibrate_hazard` consumes bounded sealed descriptor/coverage/trade-only bundles. It counts complete UTC band-minutes
with captured T+1/T+2 descriptors and uninterrupted 30-second-expiry trade coverage; identical trade IDs deduplicate,
conflicts exclude affected minutes, and a gap is never zero activity. Exact binomial CP CDF bisection preserves the
larger endpoint and upward rounding. JSON records city and pooled n/x/dates, exclusions, brackets, fallbacks, source
and stream hashes, and the single maximum-city scalar. Unavailable inputs report 1.0 and incomplete bindings;
hash-invalid/changed files refuse. No actual hazard was estimated in this mission.

`manifest build` and `manifest verify` bind every frozen ReplayConfig field, policy/plugin/engine/scorer and dependency
source identities, all bundle/stream bytes, exact sorted discovery inventory, derived intervals, calibration and
all three owner-attested document hashes. Calibration is recomputed for verification. A new ReplayConfig field
requires a prospective addendum. The total bundle-input ceiling includes panel **and** calibration bundles.
Maintenance intervals are applied to each policy and the exposure-only matched clock; settlement still reconciles
carried inventory. Selected clock windows and aggregate matching are retained. Comparison rechecks authorization
and source bytes at the action boundary, consumes its canonical attempt before policy invocation, and reports the
economic/pull conjunction with both fill bounds and k sensitivities.

The verifier accepts the optional clarification hash additively, preserves old seven-field attestations, rejects
revocation of an ID permanently, and allows a separately approved successor ID. The actual approval mapping remains
empty in `src/maker_core/replay/approved_registrations.py`, re-exported by `authorization.py`. Only this enrollment
file is excluded from source hashing to avoid a circular hash. The separate
[enrollment template](../research/maker-replay-enrollment-template-2026-09-27.md) gives production the exact reviewed
`raw-manifest-hash -> michaelbooth1` procedure. No fixture or document hash substitutes for a manifest hash.

## Verification and limits

All evidence below is from the separate workstation, using the repository's host/principal-bound heavy wrapper.
No full pytest run was used.

| Focused run | Result |
| --- | --- |
| Maker-core suite plus import architecture, agent-doc audit, knowledge-structure audit, schema registry, module-size audit and roadmap backlog tests | **921 passed, 1 skipped, 5 xfailed** |
| Enrollment, authorization and execution-pack regressions after the separate template change | **40 passed** |
| Final documentation/knowledge/backlog and enrollment checks after report/index generation | **38 passed** |
| Replay calibration/execution/report/baseline/bundle focused run | **80 passed, 1 skipped** |
| Earlier maker-core, import architecture, workload-admission and Codex host-hook run | 938 passed, 12 skipped, 5 xfailed; the sole failure was the then-untracked new tests. Staging those files resolved it in the 921-pass run. |
| `compileall -q app src tests` through workstation wrapper | **PASS** |
| `git diff --check` / staged diff check | **PASS** |
| Read-only `agent_docs_audit`, `roadmap_backlog --fail-on-lint --check`, `correspondence_index --check` CLIs | **PASS / OK / OK** |
| PowerShell parser check of the changed workstation wrapper | **PASS** |

The CP fixture oracle includes endpoints and large counts against the beta quantile; the pooled control has
n=1,440, x=30, three dates and M=2, with the absent city's bound equal to the pooled bound. This is synthetic support,
not a measurement of market flow. Real support is **zero market-days, zero date clusters and zero market clusters**;
no economic interval, power estimate or model-edge claim is made. Frozen two-document byte hashes:

- Protocol: `0380212d8e82474281afbed1197161263f794570ec06cf51fec99a3c6c03a6bf`.
- Addendum: `074a0e56b87770eff9f574232819b5d95ecd7073e450f27adac7bf555a43410b`.
- New unsigned clarification: `37d2fd8e34462a77d6209ee4018e3685bf91a81a93e2cb08df6986985811fa0e`.

The calibration CLI requires production-prepared calibration-only sealed bundles. The general weather exporter
emits extra record kinds and is intentionally refused for calibration; this mission does not modify that source
adapter or read raw 88a files. Production must retain every allowed discovery, gap, invalid/conflicting trade and
source receipt when sealing its calibration inputs. The prospective city JSON must reproduce the final union;
a new city blocks rather than silently recalibrating. These input prerequisites have not been qualified on real data.

The workstation script adds only `maker_core.replay`. The independently installed Codex hook still has its older
module list; if it rejects a future replay invocation, production must resolve that through the owning host-policy
process, not bypass it. The source tree, approved invocation path, and production closure verdict need qualification
before execution. A canonical manifest directory and its attempt receipts must be preserved; copying the manifest
or using an archived pre-revocation log supplies no new authority. The library is not a hostile-operator sandbox.

## Per-file roll classification

`roll_verdict.ps1 -Branch HEAD -Base 0f7d0bac2d0811b8a94985afd395f49fb7b2c6e3` returned **UNDECIDABLE: no live closure
evidence** on this isolated workstation worktree: all four expected status files were absent. No frozen mirror was
substituted. Thus the table records file role and the owner's maker-core non-capture classification, **not a fabricated
production measurement**. Production must run the script again against its current retained closures. Inherited
integration/preregistration changes have their own roll sensitivity and are not made roll-free by this report.

| Changed file | 110r roll classification / capture closures |
| --- | --- |
| `docs/operations/maker-replay-authorization-verifier-design-2026-09-27.md` | Roll-free documentation; none |
| `docs/operations/maker-replay-bundle.md` | Roll-free documentation; none |
| `docs/research/maker-replay-clarification-1-2026-09-27.md` | Roll-free new documentation; none |
| `docs/research/maker-replay-enrollment-template-2026-09-27.md` | Roll-free template; none |
| `docs/roadmap/agent-report-2026-09-110r-replay-execution-pack.md` | Roll-free report; none |
| `docs/roadmap/correspondence-index.md` | Roll-free generated index; none |
| `scripts/ops/workstation_heavy.ps1` | Roll-free script; none |
| `src/maker_core/replay/__main__.py` | Maker core; none per owner, production confirmation pending |
| `src/maker_core/replay/approved_registrations.py` | Maker core; none per owner, production confirmation pending |
| `src/maker_core/replay/authorization.py` | Maker core; none per owner, production confirmation pending |
| `src/maker_core/replay/baselines.py` | Maker core; none per owner, production confirmation pending |
| `src/maker_core/replay/bundle.py` | Maker core; none per owner, production confirmation pending |
| `src/maker_core/replay/calibration.py` | Maker core; none per owner, production confirmation pending |
| `src/maker_core/replay/diagnostics.py` | Maker core; none per owner, production confirmation pending |
| `src/maker_core/replay/engine.py` | Maker core; none per owner, production confirmation pending |
| `src/maker_core/replay/execution_manifest.py` | Maker core; none per owner, production confirmation pending |
| `src/maker_core/replay/execution_receipt.py` | Maker core; none per owner, production confirmation pending |
| `src/maker_core/replay/pack_cli.py` | Maker core; none per owner, production confirmation pending |
| `src/maker_core/replay/pack_io.py` | Maker core; none per owner, production confirmation pending |
| `src/maker_core/replay/report.py` | Maker core; none per owner, production confirmation pending |
| `tests/maker_core/fixtures/execution_pack.py` | Test-only; no runtime imports |
| `tests/maker_core/test_replay_calibration.py` | Test-only; no runtime imports |
| `tests/maker_core/test_replay_enrollment.py` | Test-only; no runtime imports |
| `tests/maker_core/test_replay_execution_pack.py` | Test-only; no runtime imports |

## Exact production commands — future, not executed here

Run from the qualified production checkout, after reading the then-current reserved-window status and operations
role. The status at fixture implementation was NONE RESERVED. These commands assume production has sealed the named
inputs under its own `data/maker_replay/maker-replay-2026-10-15-v1` namespace; none is asserted to exist now. They use
the executing checkout's actual root and interpreter, never workstation scratch paths. The dedicated capture host
runs serially in its admitted window. The helper below acquires the repository-owned lease; it refuses starts after
08:50 local so the CLI's 300-second limit has room before 09:00. A rejected installed guard remains a block.

```powershell
$ErrorActionPreference = 'Stop'
$replayRepo = (git rev-parse --show-toplevel).Trim()
$replayPython = Join-Path $replayRepo 'venv\Scripts\python.exe'
$replayPack = Join-Path $replayRepo 'data\maker_replay\maker-replay-2026-10-15-v1'
. (Join-Path $replayRepo 'scripts\ops\workload_admission.ps1')
function Invoke-110rReplay([string[]]$ReplayArguments) {
    if ((Get-Date).TimeOfDay -ge [TimeSpan]::FromHours(8.833333333)) { throw 'Too late for bounded replay before 09:00' }
    $replayLease = Enter-WeatherHeavyWorkloadLease -RepoRoot $replayRepo -Workload 'MakerReplay-110r'
    if ($null -eq $replayLease) { throw 'Heavy workload lease busy' }
    try {
        & $replayPython -m maker_core.replay @ReplayArguments
        if ($LASTEXITCODE -ne 0) { throw "Replay refused: exit $LASTEXITCODE" }
    } finally { Exit-WeatherHeavyWorkloadLease -Lease $replayLease }
}
$calibrationArgs = @()
foreach ($day in @('2026-09-27','2026-09-28','2026-09-29')) {
    $calibrationArgs += @('--bundle', (Join-Path $replayPack "calibration-bundles\$day"))
}
# 2026-09-30, after all three UTC dates have closed; no panel scoring.
Invoke-110rReplay (@('calibrate_hazard','--quote-markets',"$replayPack\quote-markets.json",
    '--out',"$replayPack\calibration.json") + $calibrationArgs)
```

After October 14 closes, prepare the full panel bindings and the owner's exact signed Source JSON. The universe
format is specified in the [bundle contract](../operations/maker-replay-bundle.md#clarified-execution-pack).

```powershell
$panelArgs = @()
foreach ($offset in 0..14) {
    $day = ([datetime]'2026-09-30').AddDays($offset).ToString('yyyy-MM-dd')
    $panelArgs += @('--bundle', (Join-Path $replayPack "panel\$day"))
}
$bindingArgs = @('--calibration',"$replayPack\calibration.json",
    '--universe',"$replayPack\universe.json",'--quote-markets',"$replayPack\quote-markets.json",
    '--decision-log',"$replayRepo\docs\operations\DECISION_LOG.md",
    '--frozen-protocol',"$replayRepo\docs\research\maker-replay-hurdles-preregistration-2026-09-27.md",
    '--execution-addendum',"$replayRepo\docs\research\maker-replay-execution-addendum-2026-09-27.md",
    '--clarification',"$replayRepo\docs\research\maker-replay-clarification-1-2026-09-27.md")
foreach ($day in @('2026-09-27','2026-09-28','2026-09-29')) {
    $bindingArgs += @('--calibration-bundle',(Join-Path $replayPack "calibration-bundles\$day"))
}
$manifestPath = Join-Path $replayPack 'execution-manifest.json'
Invoke-110rReplay (@('manifest','build','--owner-decision',"$replayPack\owner-decision.json",
    '--out',$manifestPath) + $panelArgs + $bindingArgs)
$manifestHash = (Get-FileHash -LiteralPath $manifestPath -Algorithm SHA256).Hash.ToLowerInvariant()
Invoke-110rReplay (@('manifest','verify','--manifest',$manifestPath,
    '--manifest-sha256',$manifestHash) + $panelArgs + $bindingArgs)
```

Then follow the separate enrollment template and obtain review/production roll confirmation. The final command is
permitted only on **2026-10-15 America/Toronto**, from a fresh qualified process with the same canonical manifest and
the current reviewed log; redefine the variables/helper above without rerunning calibration or manifest creation.

```powershell
Invoke-110rReplay (@('run','--compare','--pre-registration',$manifestPath,
    '--pre-registration-sha256',$manifestHash,'--out',"$replayPack\scored-look") + $panelArgs + $bindingArgs)
```

No registration, production write, capture restart, scheduler mutation, exchange/account read, model fit, candidate,
promotion, live order, production merge or scored real-data look was performed. Only the isolated dependency merge,
fixture work, source commits and authorized topic publication/draft PR are part of this handback. Production owns
signature/revocation rows, input sealing, final enrollment, current-host qualification and any eventual adoption.
