# 110j Part A — storage registry corrections

**PASS — registry and owning procedures implemented; 64 tests and 40 subtests pass, including all four repo-wide audits. Production roll authority remains UNDECIDABLE without current capture closures; treat the Python change as roll-sensitive pending production's verdict.**

Branch: `codex/storage-registry-corrections-20260926`. Base:
`965374a0edc6fcb65d66e257be9e404cc9af8d60` (`origin/master`). Handoff read from
`origin/codex/owner-decisions-0926-day` at `ed075014161e6e0b0f8d3e9d0fc8dd265356d2c2`,
descendant of the requested `8cf764d26`. Owner storage decisions 1–9 approved
2026-09-26; decision 10 kept and 11 declined. No decision outside Part A was executed.

Rotated capture diagnostics become archive-eligible operator logs; fanout
claims and monthly receipts have separate retention rows; forecast history
is canonical. The WU classifier accepts an exact-path `WuAtomicOrphanProof`
only when all four proofs pass; ordinary path-only inventories retain the
temporary file as canonical. This pure registry API does not probe processes,
open handles, or delete files. The cleanup owner must obtain and recheck those
proofs in the approved campaign. The replay-cache waiver is recorded without
weakening the general reachability tool. Maker journals already had canonical
coverage; their forever-retention row is now explicit in the policy.

Both retired paper-maker tasks were already in `status.ps1`'s `$expDisabled`
set on the fetched base, with the September 24 owner/DECISION_LOG reference.
The health watchdog consumes that status. A regression assertion verifies
both exact names; no duplicate setting or Scheduler mutation was needed.
The economics runbook now explains preservation, owner review, acceptance,
drift verification and Stage-A recovery; the September 26 production outcome
is a supplied handoff fact, not a new workstation observation.

## Per-file roll classification

| File | Classification / closures |
| --- | --- |
| `src/weather/operations/storage_classes.py` | Roll-sensitive treatment (UNDECIDABLE: no retained production closure available in the clean worktree); production must identify any importing closures with `roll_verdict.ps1`. |
| `tests/operations/test_storage_classes.py` | Roll-free; tests excluded from capture closures. |
| `docs/operations/data-storage-class-contract.md` | Roll-free. |
| `docs/operations/data-retention-policy.md` | Roll-free. |
| `docs/operations/EXCHANGE_ECONOMICS_SNAPSHOT_RUNBOOK.md` | Roll-free. |
| `docs/roadmap/agent-report-2026-09-110j-a.md` | Roll-free. |
| `docs/roadmap/correspondence-index.md` | Roll-free; generated after report commit. |

No schema-registry change. `roll_verdict.ps1 -Branch codex/storage-registry-corrections-20260926 -Base origin/master`
returned UNDECIDABLE with all four closure files absent. Synthetic evidence
was not substituted for live closure authority.

## Reproduction and production handback

Focused tests, through `scripts/ops/workstation_heavy.ps1 -Kind pytest` with
the project interpreter, an explicit disposable basetemp and these arguments:

```text
-m pytest -q tests/operations/test_storage_classes.py tests/operations/test_health_watchdog_script.py tests/operations/test_schema_registry.py tests/operations/test_import_architecture.py tests/operations/test_agent_docs_audit.py tests/operations/test_path_policy.py --basetemp <owned-temp-directory>
```

All fixtures/synthetic paths; test temp removed. Free C: bytes before/after:
138545037312 / 138513956864 (volume observations, not an attributed reclaim).
The first sandboxed wrapper attempt refused the sandbox principal; the
attending-user wrapper passed without changing its identity or lease gates.

Production, after fetching, runs its read-only merge gate:

```powershell
.\scripts\ops\roll_verdict.ps1 -Branch origin/codex/storage-registry-corrections-20260926 -Base master
```

Use the owning retention policy for exact-path campaigns; classification is
not deletion authority. The economics procedure's exact commands are in
`docs/operations/EXCHANGE_ECONOMICS_SNAPSHOT_RUNBOOK.md`; do not repeat the
already supplied September 26 acceptance solely because this branch lands.

No production data, credentials, venue calls, registration, restart, merge,
or production write. Implementation commit and generated-index commit are
recorded by this branch's immutable Git history (`git log origin/master..HEAD`).
