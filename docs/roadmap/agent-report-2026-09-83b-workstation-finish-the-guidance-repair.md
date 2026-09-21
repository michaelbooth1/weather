# Mission 2026-09-83b — Part B: national bulletin reuse

**PARTIAL — capture reuse is implemented; verification pending. The new derived
index needs a storage-family registry entry outside this mission's owned files
before production adoption.**

Branch `codex/nbp-bulletin-reuse-20260921`, independent base `origin/master`
`e28530af67c7371fc7b2c08bbd0e26cfe72a28f9`. Part A is not an ancestor.
Section 3 decisions are accepted without reopening them. Production download
counts in the handoff are supplied facts, not workstation observations.

## B1 design, recorded before code (2026-09-21)

Choose a cross-pass request/cycle index, not scheduled prefetch. Capture already
knows both immutable identities; it can discover an earlier successful fetch
without a new scheduler, scope change, or required warm-up. The index copies the
existing successful fan-out receipt only after verifying the bulletin cycle and
all configured US station blocks, required TXN rows and terminal pressure rows.
Its key includes the completeness policy and station set. Reuse validates the
receipt identity and original timing, then hashes the CAS bytes and checks their
cycle. A new cycle has a new key. Missing/incomplete/error responses never enter
the index. Atomic create-only publication needs no additional claim or wait.
Index read/write/verification errors fall back to the existing pass fetch;
coordination errors fall back to the direct provider callback. A successful
download is not repeated just because publishing its index failed.

Existing columns suffice: `captured_at_utc` is this use, `fetched_at` and
request/response times remain the original network timestamps,
`single_fetch_reused=true`, `single_fetch_fetched=false`, and current
`single_fetch_scope` describe reuse. The reused result has no new coordinator
network event (zero count, `not_applicable`), rather than copying the old
coordinator's one download into a new scope. The index retains the original
receipt. The original capture owns its network attribution. Cycle age is use
time minus issue, never fetch time disguised as use time. No manifest schema or
writer change is required.

Memory remains bounded by the existing two-entry local fan-out. Completeness
scans one line at a time without making a national `splitlines()` list; the index
retains only a small receipt, never another decoded national response. Reuse
reads/verifies the same CAS bytes already used by existing cross-process
followers. It adds no background process or long-held lock.

Cold concurrent misses in different scopes may each download before the first
index is published; there is no new cross-pass network lock. The measured
before/after table is the healthy serial case requested by this mission, not
an absolute network cap under races or failed storage. An invalid immutable
index remains untouched and causes future downloads until an independently
reviewed repair. Corrupt canonical blobs are not overwritten: downloading
again does not relax the writer's existing CAS-integrity gate.

## Verification and handback

Implementation commits: `0b0c5bd3`, final code `57b69142`. Fixture probe and unchanged
replay/migration/parity checks are pending. No forecast candidate, fit, retirement,
re-score, outcome read, floor change, paid provider, credential, exchange call,
production write, Scheduler registration, capture restart or master merge.

The use-time diagnostic is `cycle_age_at_use_hours` on the live normalized
payload. It is deliberately separate from the retained parser/wrapper's
original-capture `cycle_age_hours`, so composing with Part A does not rewrite
archive provenance or change recorded-parser replay. For current-use admission,
derive age from the manifest capture time minus issue time, as section 3 directs.

## Exact remaining ownership requirement

`src/weather/operations/storage_classes.py` must register
`forecast_payload_cas/nbp_cycle_index/**/*.json` as `analysis_projection`,
rebuilt from the original fan-out receipt and verified blob by the completeness
check, with a reviewed exact-path cleanup manifest required for deletion.
The owning [storage contract](../operations/data-storage-class-contract.md)
requires classification before adding a durable data family and names that
registry as authoritative. The allowed documentation records the classification
and no-cleanup policy, but the code registry currently reports `unclassified`
and blocks deletion. That file is outside Part B's ownership and was not taken.
This is a concrete remaining registration, not an invented manifest schema
requirement or permission to relax a storage gate.

## B4 — other sources

No other source uses this cross-process fan-out or its per-iteration cache.
`CrossProcessMarketInvariantFetchFanout._validated_key` accepts only NBM NBP;
the only source call is `fetch_nbm_probabilistic_tmax`. The generic same-process
fan-out is instantiated there only as `NBM_NATIONAL_TEXT_FANOUT`. NWS, MRMS and
other provider adapters do not inherit this optimization; this mission does
not claim their traffic is measured or establish equivalent waste. No other
adapter, scope string or supervisor loop changed.

## Roll and independence

[Tool output](nbp-reuse-83b/roll-verdict.txt): **UNDECIDABLE: no live closure
evidence**, exit 1, all four required status files absent.
[Per-file inventory](nbp-reuse-83b/roll-inventory.json) therefore leaves closure
memberships null rather than guessing them. Treat as roll-sensitive; production
must rerun its tool and bounded suite before a quiet-window adoption. Part A is
not stacked here; only its 11 retained 07Z station blocks were copied into one
small deterministic fixture. No national file was fetched or placed in Git.

## Reproduction

From this branch's worktree in PowerShell. Use fresh short basetemp paths and
remove only these test directories after retaining receipts.

```powershell
$repo = (Get-Location).Path
$python = 'C:/Users/Michael/Documents/github/weather/venv/Scripts/python.exe'
function Invoke-83b([string]$kind, [string[]]$tokens) {
    $encoded = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes(
        (ConvertTo-Json -InputObject $tokens -Compress)))
    & "$repo/scripts/ops/workstation_heavy.ps1" -Kind $kind -PythonPath $python `
        -ArgumentsBase64 $encoded -RepoRoot $repo
}
Invoke-83b pytest @('-m','pytest','-q','-s','tests/collection/test_nbp_cycle_reuse.py',
    'tests/collection/test_forecast_payload_cross_process_fanout.py',
    'tests/sources/test_forecast_payload_fanout.py','--basetemp','C:/tmp/83b-b-check')
Invoke-83b pytest @('-m','pytest','-q','--basetemp','C:/tmp/83b-b-full')
Invoke-83b compileall @('-m','compileall','-q','app','src','tests')
& $python -m weather.operations.agent_docs_audit
& $python -m weather.reporting.roadmap.roadmap_backlog --fail-on-lint --check
& "$repo/scripts/ops/roll_verdict.ps1" -Branch codex/nbp-bulletin-reuse-20260921 -Base origin/master
```
