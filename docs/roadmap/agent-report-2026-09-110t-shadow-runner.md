# Agent report 2026-09-110t — public-only maker shadow runner

**PASS for fixture implementation and repository audits. Forward shadow qualification NOT_RUN; economics NOT_RUN.**
The owner starts the first public session. No seven-day, economic, exchange-lifecycle or live-readiness claim is made.

## Provenance and scope

- Mission: `workstation-handoff-2026-09-110t-shadow-runner.md`, read from
  `origin/codex/handoff-110k-20260926` at `f7b6eff7d` and rechecked unchanged at
  `795e87d60d94d123ba86c666906ce42fe442a50f`.
- Branch: `codex/shadow-runner-20260927`.
- Replay base: `8ee7b8ad34c3d6ab8c073e93f90fc717586505ca`.
- Required design merge: fast-forward to PR #108's
  `bd3291aa22496078e6d0f22de91da65291cd2c4f`. The draft PR is stacked on
  `codex/shadow-runner-design-20260927`; that branch depends on the replay branch.
- Implementation commit: `4cbb2c31841360672d03241eaaf4d4d89d9f081c`.
- Separate non-capture workstation; synthetic fixtures and recording transports only.
  No production evidence was opened. Date clusters, market clusters and scored market-days: zero;
  statistical intervals are not applicable to deterministic conformance fixtures.
- Open-question ids: none. This is implementation evidence, not acceptance of a research claim.

## Delivered behavior

The shadow runner shares the Phase 2 lifecycle and pure decision kernel. Extraction into
`maker_core.replay.lifecycle` leaves RE-1 composition in `replay.engine`, outside the runner's
transitive import closure. Its only venue dependency is the dedicated public reader: fixed GET
book/reward/discovery endpoints and public market-stream subscription/ping. There are no mutation,
account, wallet, environment-credential, signing or RE-1 adapters in that closure.

Each frozen session binds code/contracts, plugin/model, conditions/local dates, UTC scope,
configuration, registration digest, hypothetical initial cash/caps/hazard, both independent fill
bounds, and resource ceilings. Typed content-addressed inputs round-trip through a reviewed public
field projection without weakening `SecretGuard`; a field that would be silently scrubbed refuses
the write. The journal remains the existing fsynced hash-chain envelope. Minute checkpoints,
intervening transitions, input/state artifacts, gaps, stops, UTC-day/size segment seals and a closed
receipt are create-only. The receipt digest must be retained independently.

Books expire after ten seconds; terms refreshes and validity, trade health and provider validity
are separate. Public book source timestamps are retained. A heartbeat never refreshes a book.
Changed terms withdraw proposals before cooldown. Public-health gaps latch unknown continuity;
reconnection does not reset held lots or cash. Duplicate prints, first-fill sibling withdrawal,
cross-midnight state, local stops, missing acknowledgments, persistence crashes, torn/truncated
tapes, duplicate writers and exact replay are covered by fixtures. Failed persistence poisons the
writer. An ambiguous or crashed session cannot be repaired or restarted in place.

The evaluator emits canonical decision and full trace agreement only. P&L and policy comparison
remain `NOT_RUN` for all inputs, hence also for the September 30–October 13 panel before the
October 15 scored look. It cannot import the economic scorer. A later look still needs its
separate registration/admission; reaching the calendar date alone does not enable scoring.

The dedicated workstation launcher adds a public-shadow admission profile while preserving the
host/principal check, host-global exclusion, ACTIVE/TEARDOWN_PENDING poison and kill-on-close Job.
The ordinary offline module allowlist is unchanged. The launcher rejects bare/wrong-host use,
changed source/input hashes, existing output, missed start, deadline and memory excess. No task
is registered. Nightly agreement runs after the public session releases the same lease.

## Verification

Final admitted batch: **1,281 passed, 12 skipped, 5 expected xfails**. It includes every maker-core
test, weather-plugin conformance and composition, public recording transport, all repository import
ratchets, native admission refusal/residual classification, existing workload-admission regressions,
the repo-wide agent-docs audit, schema registry audit, path policy and generated-roadmap parity.
The skips include native acquisition tests that cannot take the real host-global mutex while the
required outer verification wrapper owns it. They were not bypassed.

The batch's Python argument vector, run through `scripts/ops/workstation_heavy.ps1 -Kind pytest`
with the documented base64 JSON contract and an explicit disposable `--basetemp`, was:

```text
-m pytest tests/maker_core tests/market/test_maker_plugin.py tests/market/test_maker_shadow.py tests/operations/test_import_architecture.py tests/operations/test_shadow_admission.py tests/operations/test_workload_admission_script.py tests/operations/test_agent_docs_audit.py tests/operations/test_schema_registry.py tests/operations/test_path_policy.py tests/reporting/test_roadmap_backlog.py -q
```

`-m compileall -q app src tests` through the same wrapper's `compileall` lane passed.
`git diff --check` passed. The full unrelated repository test suite was not run.
The correspondence index is regenerated after committing this report, as its owner requires.
CI and independent PR review remain external draft-PR gates, not inferred from local tests.

## Exact workstation start command

Run from the clean reviewed topic checkout. The owner must first provide the frozen session JSON
and immutable public provider capture described in the
[installed-entrypoint contract](../operations/maker-shadow-runner-design.md#installed-entry-points).
No actual market, hazard or forward interval was selected during this fixtures-only mission.
The following is the exact PowerShell invocation; bind its path variables to those owner-prepared
absolute paths and the project's absolute CPython path, with a new output directory and absent stop file:

```powershell
$manifestSha256 = (Get-FileHash -LiteralPath $manifestPath -Algorithm SHA256).Hash.ToLowerInvariant()
$providerSha256 = (Get-FileHash -LiteralPath $providerPath -Algorithm SHA256).Hash.ToLowerInvariant()
& .\scripts\ops\workstation_shadow.ps1 -PythonPath $pythonPath -OutputPath $outputPath -ManifestPath $manifestPath -ManifestSha256 $manifestSha256 -ProviderPath $providerPath -ProviderSha256 $providerSha256 -StopPath $stopPath -Confirmation I_START_PUBLIC_SHADOW_ONLY
```

The manifest must pin the final reviewed checkout HEAD, with a start within ten minutes. Retain
the returned receipt SHA256 separately. Creating `$stopPath` requests a latched local withdrawal.
After closure, decision-only evaluation is:

```powershell
& .\scripts\ops\workstation_shadow.ps1 -PythonPath $pythonPath -OutputPath $reportPath -SourcePath $closedSessionPath -ReceiptSha256 $receiptSha256
```

## Remaining qualification and integration boundary

- No public forward session, active-feed latency/drill injection, or native positive launcher
  commissioning was performed. Fixture success does not establish those operational facts.
- Agreement reports deliberately retain `qualified_dates=0` / `PENDING_88A_ADMISSION`. They preserve
  evidence for subsequent 88a admission; they do not implement economic scoring or certify the
  seven-day acceptance clock. The frozen scope cannot shrink after coverage is observed.
- Provider captures are immutable and can expire. Missing forecasts remain unavailable; no fresh
  weather source is invented. Public prints lack guaranteed unique execution ids, so identical
  prints can collide under content deduplication. They never prove our own fills.
- The shared lease makes public capture and separate nightly agreement mutually exclusive. No
  continuous multi-session recovery or scheduling is claimed. Crashes end a campaign; any new
  initial state is a separately labelled diagnostic campaign.
- Production per-file roll verdict was **not measured**: the task permits fixtures only, and no
  production closure evidence was supplied. Documentation/tests are non-runtime changes; the new
  `.ps1` lane is workstation-only. Do not infer the branch's roll verdict from those facts.
  `schema_registry_recent_data.py` changes are **additive-only** registrations and belong to the
  capture-sensitive schema family. The production owner must obtain
  `scripts\ops\roll_verdict.ps1 -Branch codex/shadow-runner-20260927` before integration and follow
  the resulting guarded merge path. No production-source adoption is claimed.

No registration, production write, process restart, integration merge, order, credential read,
model fit, artifact promotion, panel score or live session was performed. The local required
dependency merge and authorized topic publication are source-control actions only.
