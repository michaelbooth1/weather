# 110k Part 2 — WU atomic orphan proof caller

Verdict: implemented and verified on synthetic files only, including native
Windows handle checks and deletion of a synthetic orphan. No production data,
credentials, `.env` or venue access. Branch `codex/wu-orphan-proof-caller-20260926`
starts at integration `8180404a0e588f73dab3c83a171538f8a89c9705`; rebase on master
after that integration lands. No scheduler or production cleanup was executed.

The bounded planner writes an exact SHA256 manifest with file/sibling identity,
four proofs and named refusals. Generic cleanup preflight now obtains fresh
proofs. The apply caller binds operator review to the plan hash and the reviewed
file's raw SHA256, hashes under an exclusive native handle, records durable intent,
rechecks immediately before deletion, and writes per-file and overall receipts.
The final sibling and ancestor directories stay pinned. There is no pathname
unlink or recursive deletion fallback. A refusal stops further files.

**Owner clarification, 2026-09-26:** a proven later-starting PID is allowed.
This supersedes the handoff's ambiguous reused-PID fixture wording. A live
original writer, unknown start time, start at/before mtime, future start,
recent temp, missing final sibling or an existing open handle all refuse.

The PowerShell wrapper uses the existing shared lease and kill-on-close Job,
headroom checks, 00:30–09:00 gate and absolute deadline. The default limits are
10,000 visited entries, 1 GiB hashed bytes and 300 seconds. Source selection is
strictly WU atomic temps; final files are retained. An interrupted intent without
a receipt remains unresolved evidence and must not be silently retried.

## Exact production commands

After integration, inside the admitted window, from the production checkout:

```powershell
New-Item -ItemType Directory -Path .\scratch\wu-orphans-110k -ErrorAction Stop
.\scripts\ops\wu_orphan_cleanup_run.ps1 -Command plan -OutputRoot scratch/wu-orphans-110k/plan -MaxEntries 10000 -MaxBytes 1073741824 -MaxRuntimeSeconds 300
```

Review `scratch/wu-orphans-110k/plan/manifest.json`; preserve it and save an approved
copy as `scratch/wu-orphans-110k/reviewed.json`. Its operator review must contain
`approved: true`, a named reviewer, note, and `plan_sha256` equal to the unchanged
top-level hash. Only after that exact-path review:

```powershell
$WuReviewedManifest = '.\scratch\wu-orphans-110k\reviewed.json'
$WuReviewedSha256 = (Get-FileHash -LiteralPath $WuReviewedManifest -Algorithm SHA256).Hash.ToLowerInvariant()
.\scripts\ops\wu_orphan_cleanup_run.ps1 -Command preflight -ApprovedManifest $WuReviewedManifest -ManifestSha256 $WuReviewedSha256 -OutputRoot scratch/wu-orphans-110k/preflight -MaxRuntimeSeconds 300
.\scripts\ops\wu_orphan_cleanup_run.ps1 -Command apply -ApprovedManifest $WuReviewedManifest -ManifestSha256 $WuReviewedSha256 -OutputRoot scratch/wu-orphans-110k/apply -MaxRuntimeSeconds 300
```

A previous output directory refuses reuse. Preserve all manifests and receipts;
the commands above were not run against production. The standalone module also
accepts explicit root/output paths for synthetic verification. Canonical procedure:
[retention runbook](../operations/data-retention-policy.md#wu-atomic-temporary-file-cleanup).

## Verification

The final focused run passed **773 tests, 12 skipped, 40 subtests**. It includes
WU proof/caller, cleanup preflight, storage classes, projection tiering, all
`tests/maker_core`, and repo-wide schema registry, import architecture, agent docs
audit and path policy. The architecture file includes maker-core import boundaries
and their negative tests. The wrapper parsed successfully without execution;
focused compileall passed. Temporary pytest files were removed after verification.

Fixtures cover live/reused/unknown PID cases, strict age, missing sibling, open
handles, stale hash/mtime/final identity, forged proof/review, proof changes after
intent, byte/time/entry caps, generic-preflight bypass attempts, raw manifest hash,
immutable outputs, native current-process identity, native hard-link refusal,
and native handle deletion.
All tests use the workstation admission wrapper and a dedicated temporary directory.

## Per-file roll classification

The isolated worktree's mechanical `roll_verdict.ps1` returned **UNDECIDABLE:
no live closure evidence**. Production must rerun it with current closures before
integration. U is undecidable; F is roll-free by file-class contract.

| File | Class |
| --- | --- |
| `src/weather/operations/cleanup_preflight.py` | U |
| `src/weather/operations/wu_orphan_cleanup.py` | U |
| `src/weather/operations/wu_orphan_proofs.py` | U |
| `src/weather/schema_registry_data.py` | U |
| `scripts/ops/wu_orphan_cleanup_run.ps1` | F |
| `tests/operations/test_wu_orphan_cleanup.py` | F |
| `docs/operations/data-retention-policy.md` | F |
| `docs/operations/data-storage-class-contract.md` | F |
| `docs/roadmap/agent-report-2026-09-110k-2.md` | F |
| `docs/roadmap/correspondence-index.md` | F |
