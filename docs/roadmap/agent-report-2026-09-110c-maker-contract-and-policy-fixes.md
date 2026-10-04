# 110c — maker contract and policy fixes before the v0.1 tag

**PASS for offline contract, policy and weather-plugin fixes. RE-1 parity remains
first-minute price parity only; all twelve full-minute journal cases are explicit
skeleton skips. No economic, production-adoption or live-readiness claim.**

Answers [handoff 110c](https://github.com/michaelbooth1/weather/blob/0ea5d5fa658afa874942f81994fd86a1131e09ec/docs/roadmap/workstation-handoff-2026-09-110c-maker-contract-and-policy-fixes.md)
and its [contract review](https://github.com/michaelbooth1/weather/blob/0ea5d5fa658afa874942f81994fd86a1131e09ec/docs/roadmap/audits/maker-contract-review-2026-09-25.md).
Open-question IDs: none assigned. No model was fitted and no scored panel was read.

## Branches and delivery

- A: `codex/maker-core-phase0-20260925`, base `853cba778`, implementation tip
  `98a2dd97e9b8c5eb781ca21d47fa5d92ddd41986`.
- B: `codex/weather-maker-plugin-20260925`, base
  `a4900d2e06ba41b650b31951a38f8bfe62edf2e9`. A was merged into its working tree
  before the weather edits; tested implementation tip:
  `5042a6315591ed86c352b5ef1ec01e719616c1b9` (merge commit).
- There is one implementation commit per branch. Separate report/index commits
  follow the repository correspondence workflow: the source report is committed
  before regenerating the index so its Git-added date is available. The index's
  Git scan omits merge-only additions, so the new report uses a normal commit.
  The final branch tips are resolved with:

```powershell
git ls-remote --exit-code origin refs/heads/codex/maker-core-phase0-20260925 refs/heads/codex/weather-maker-plugin-20260925
```

A used isolated `scratch/w/maker-core-110c`; B used its existing clean
`scratch/w/weather-maker-plugin-110b` worktree. The main checkout's wrapper could
not open its workload lock; owned edits were preserved and relocated to A's
isolated worktree, where the unchanged admission wrapper succeeded. No lock
permissions, host gates or runtime data were changed. The generated index was
the only merge conflict and was resolved with its canonical producer.

## Each review finding's disposition

| Finding | Disposition and verification |
| --- | --- |
| Half-tick midpoint silently fails maximum width | After outward snapping, step one tick inward only when beyond the high distance bound and the low bound remains satisfied. Fixture midpoint .505, width 3 c produces .48/.47 legs, both 2.5 c from their centres. |
| Every one-tick mid move cancels informed quotes | Mid-only movement holds eligible resting legs in the [1,3] c window. Fair-value delta drives adverse cancellation: half-delta at least one tick or absolute delta above max(effective sigma, .01). Smaller changes respect the 60-second cooldown. Tests cover both mid directions, inside/outside cooldown and adverse cancellation. |
| Unavailable view receives larger size | Informed missing views receive `grade_size_caps[0]` (30); existing oversized legs cancel. An eligible missing-view fixture quotes at or below 30. |
| Own orders counted as competition | Remove resting YES buys and mirrored NO buys at their prices, bounded by displayed quantity, before competition/depth scoring. HOLD share and net match the same external book before posting. |
| Weather literals in neutral core | `Profile.eligible_horizons` owns the default (1,2); `HORIZON_NOT_ELIGIBLE` replaces the weather reason. Pulls depend on `action_hint`, not `kind`; custom horizon and renamed-event fixtures pass. |
| Events never expire | Optional `InfoEvent.active_until_utc` is UTC, follows its detected/observed/scheduled reference, and is enforced inclusively. Weather scheduled METAR/model events end at +10 minutes; detected bulletins end at fetch +10 minutes. Two retained old bulletins no longer widen current quotes, while a fresh arrival does. Existing new-high/decided veto lifetime remains unchanged. |
| Threshold-group coherence | Defaulted trailing `MarketDescriptor.group_relation` accepts only None/partition/nested_ge/nested_le; weather descriptors declare partition. The binary token mapping and partition `joint` validation are unchanged; this is not a new multi-outcome execution engine. |
| Decided outcomes rejected by positive stdev | `OutcomeView` accepts zero stdev only at p=0 or p=1. Exact decided NBP and T+0 fixtures return views without epsilon. Other invalid uncertainty remains rejected. |
| Unavailability / settlement extensibility | Trailing defaulted `Unavailable.kind` validates missing_input/out_of_scope/corrupt/decided; `SettlementFact.resolved_value` is optional domain-native text. Defaults and invalid values are tested. |
| Package ratchet hole / dotenv ownership / missing HTTP families | Ratchet checks canonical module plus a dot, including root and nested initializers. Only runtime.credentials may import dotenv. Added http.client, ssl, websocket(s), aiohttp and web3 checks; synthetic forbidden/allowed imports pass. |
| SecretGuard exact-key gap | Normalized substring tokens scrub x-api-key, POLY_PASSPHRASE, secret/token/bearer/mnemonic/seed/private variants recursively, retaining existing auth/header/signature scrubs and residual-secret refusal. The contract requires runtime to supply every loaded secret. No secret was loaded here. |
| Empty journal left on opening failure | Exclusive-created journal is closed and unlinked if its opening record fails, including an injected fsync failure. Existing evidence survives an attempted duplicate open. |
| Blind RE-1 runtime parity overclaim | Took the handoff's explicit alternative: document **first-minute price parity only**. Per-leg replacement and max_requotes=5 remain unimplemented. Added twelve skipped full-minute replay skeleton cases naming required HOLD/requote, replacement prices and end-reason comparisons. No account journal was read or probed. |
| T+0 market-informed calibration | Require `release_calibration_method` on source-row export projections bound to the matching verified release ID/manifest. Include method in model_id and inputs_hash; reject market_shrink as out_of_scope/market_informed_release. Missing/conflicting methods fail closed. Dated Clarification 1 appends to the frozen pre-registration; the no-market claim is scoped to T+1/T+2. |
| NBP row-parser differential | Copied 44 explicitly requested tracked .txt controls from parser integration abd648c7c2de55289e88dc7d023136b981e2cb74, pinned SHA-256. Compare every FHR/TXN row to its verbatim pair-parser oracle and selected T+1/T+2 percentile values to the slot oracle. Sentinel slots remain aligned; three-token groups deliberately refuse instead of legacy truncation. |
| Low-priority review items | No new price-perturbation hook, settlement-recorded-time field or venue-close inference. Existing weather event deduplication already avoids hashing mapping fields and is retained. Opening-record cleanup and resolved_value were included as explicitly requested. |

The existing source-row writer does **not** emit `release_calibration_method`.
The future bounded export must project it from the bound release's calibration
artifact (`market_bin.method`); until then T+0 is unavailable. This is documented
as a new export requirement, not fabricated evidence of today's release method.
Other audit uncertainties (real sidecar/release statuses, venue close times,
issue-time coverage and min-order semantics) require a separately authorized
bounded export. None was investigated through production or provider reads.

## Tests and reproduction

- A: **610 passed, 12 skipped** (core and import architecture); **29 documentation
  tests passed** after repairing the inherited uncommitted-date index entry.
- B including merged A: **1,134 passed, 12 skipped** (plugin, core and architecture);
  **29 documentation tests passed**, including final report/index validation.
- Focused compilation passed on both branches; diff whitespace checks passed.
- These are deterministic code/fixture checks, not estimates. Date/market clusters,
  confidence intervals, power and MDE are not applicable. The 44 historical public
  parser controls were already tracked on the handoff-named branch; all new adapter
  and policy scenarios are synthetic. No fresh evidence was downloaded.

From the appropriate branch worktree on the non-capture workstation:

```powershell
$missionRepo = (Get-Location).Path
$missionGit = (Resolve-Path (git rev-parse --git-common-dir)).Path
$missionPython = (Resolve-Path (Join-Path (Split-Path $missionGit -Parent) 'venv\Scripts\python.exe')).Path
$missionTests = @('-m','pytest','tests/maker_core','tests/operations/test_import_architecture.py','tests/operations/test_agent_docs_audit.py','tests/reporting/test_correspondence_index.py','tests/reporting/test_roadmap_backlog.py')
# On B only:
$missionTests += @('tests/market/test_maker_plugin.py','tests/market/test_maker_plugin_110c.py')
$missionTests += @('-q','--basetemp',"$missionRepo\scratch\test-110c-reproduce")
$missionEncoded = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes((ConvertTo-Json -InputObject $missionTests -Compress)))
& "$missionRepo\scripts\ops\workstation_heavy.ps1" -Kind pytest -PythonPath $missionPython -ArgumentsBase64 $missionEncoded -RepoRoot $missionRepo
$missionCompile = @('-m','compileall','-q','src/maker_core','tests/maker_core','tests/operations/test_import_architecture.py')
# On B only:
$missionCompile += @('src/weather/market/maker_plugin','tests/market/test_maker_plugin.py','tests/market/test_maker_plugin_110c.py')
$missionEncoded = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes((ConvertTo-Json -InputObject $missionCompile -Compress)))
& "$missionRepo\scripts\ops\workstation_heavy.ps1" -Kind compileall -PythonPath $missionPython -ArgumentsBase64 $missionEncoded -RepoRoot $missionRepo
```

All actual pytest/compilation commands used the unchanged workload wrapper. Test
scratch directories are task-owned synthetic state and are cleaned after verification.

## Roll disposition and boundaries

A's `roll_verdict.ps1 -Branch codex/maker-core-phase0-20260925 -Base origin/master`
returned exit 1, **UNDECIDABLE: no live closure evidence**. This isolated worktree
has none of the four snapshot/CLOB/observation-trigger/enrichment closure files.
Production must re-derive closure membership; no manual roll-free inference is made.
B's `roll_verdict.ps1 -Branch codex/weather-maker-plugin-20260925 -Base origin/master`
also returned exit 1, **UNDECIDABLE**, with the same four missing closure files.

| Changed path group | Per-file disposition |
| --- | --- |
| A contracts/__init__.py, quoting/policy.py, evidence/journal.py under src/maker_core | Closure evidence unavailable for each; re-derive on production. |
| B clock.py, fair_value.py, nbp.py, universe.py under src/weather/market/maker_plugin | Closure evidence unavailable for each; re-derive on production. |
| tests/maker_core/test_110c.py, test_policy.py, test_journal.py, test_re1_parity.py; tests/operations/test_import_architecture.py | Test-only changes; no available live closure evidence. |
| tests/market/test_maker_plugin.py, test_maker_plugin_110c.py; fixture oracle, copied controls and hash manifest | Offline tests/fixtures; no available live closure evidence. |
| Contract/package guides, dated clarification, fixture READMEs, report and generated index | Documentation, roll-free class. |

No venue calls, credentials, actual `.env`, production data, workstation mirror,
scheduled tasks or live trading were accessed. No service was started/restarted,
no production state was written, no branch was merged to master, and no contract
tag was created. The wallet reader and other worktrees were left running and
unchanged. Production owns source adoption and creation of `maker-core-contracts-v0.1`.
