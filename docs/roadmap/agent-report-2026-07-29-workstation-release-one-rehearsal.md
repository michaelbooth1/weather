# Workstation release #1 rehearsal — 2026-07-29

## Failure list first

### F1 — NO-GO: the real promotion gate blocks release #1

Both integrated production-mode rehearsals completed point-in-time
qualification and then stopped at the existing promotion gate. No integrated
run built a release, promoted anything, or wrote an active pointer.

- `origin/master` rehearsal:
  - code: `28d0dfb433e6ac100985d5ec8a8c71c7e2caa904`
  - promotion verdict: `blocked`
  - blocked market: `atlanta`
  - promote-ready markets: none
  - shadow markets: `austin`, `chicago`, `dallas`, `denver`, `houston`,
    `los-angeles`, `miami`, `nyc`, `san-francisco`, `seattle`
  - readiness: `OPEN`
  - serving gauntlet: `PASS_WITH_SHADOWS`
  - candidate release step: `skipped`
  - exact skip reason: `existing_validation_gates_not_passed`
- pending warm-tier rehearsal:
  - code: `58ab0dd39293f0f0914dc8e4690b78b64414f21c`
  - promotion verdict: `blocked`
  - blocked market: `atlanta`
  - promote-ready markets: none
  - the same ten other markets remained shadow-only
  - readiness: `OPEN`
  - serving gauntlet: `BLOCK` for the separate reduced-mirror baseline
    omission in F5
  - candidate release step: `skipped`

This is a real model/evidence gate, not a technical pipeline error. The
rehearsal does not establish edge over market prices.

### F2 — NO-GO: release #1 has no rollback target

The first-inactive-release contract correctly requires a null parent and null
`rollback_target`. If that release becomes the first active pointer, the
pointer has no previous release. The repository's rollback command cannot
return to an absent pointer.

I rehearsed the rollback command against the archived scratch pointer. It
failed closed exactly as follows:

```json
{"error": "active release pointer has no verified rollback target", "status": "BLOCK"}
```

The command exited `2`, wrote no drill record, and the temporary scratch pointer
was removed. No production pointer was touched.

Therefore the requested lock-day checklist cannot currently promise rollback
for release #1. Before a real first promotion, operators need one of:

1. a reviewed, verified predecessor release that becomes the recorded rollback
   target; or
2. a repository-owned first-release deactivation/recovery procedure with an
   atomic command, identity proof, worker coordination, and health verification.

Deleting `current_release.json` by hand is not an acceptable rollback.

### F3 — NO-GO: no canonical inactive-release parity/forward-shadow command

The first-inactive-release verifier correctly reports these next requirements:

- `EXACT_RELEASE_BOUND_CAPTURED_INPUT_PARITY`
- `FORWARD_SHADOW_QUALIFICATION`
- `SEPARATE_REVIEWED_PROMOTION_DECISION`

The available parity generator,
`weather.reporting.scorecards.captured_input_parity_evidence`, requires a
verified **active** release pointer. The runbook does not provide a canonical
command that binds parity and forward-shadow evidence to an inactive
production release before its first promotion. Conversely,
`release_lifecycle promote` validates the reviewed decision and fresh boundary
proof but does not itself create the missing parity or shadow evidence.

Do not solve this by using the generic parity skip or by promoting first and
hoping to validate afterward. The lock-day checklist below stops at the
verified inactive release until this operational bridge exists.

### F4 — NOT-DONE on master: the warm tier is not merged

The handoff said to pull after the warm-tier merge. Exact requested
`origin/master` is:

```text
28d0dfb433e6ac100985d5ec8a8c71c7e2caa904
```

Warm-tier commit `7232a896` is not its ancestor. The available pending branch
was:

```text
origin/codex/workstation-who-breaks-floor-2026-07-27g
58ab0dd39293f0f0914dc8e4690b78b64414f21c
```

That head is the warm-tier branch merged with current master, not
`origin/master`. The compressed-evidence result is consequently conditional
branch evidence only. It cannot authorize the remaining warm-tier application
or establish the behavior of a future merged master.

### F5 — pending warm lane lacked the production gauntlet baseline

The final gzip-only integrated lane passed preselection, family-secondary,
pooled training, registry binding, promotion refresh execution, and production
PIT qualification. Its serving gauntlet nevertheless returned `BLOCK` because
the deliberately reduced scratch mirror did not contain:

```text
data/backtest/replay_baseline.json
```

Exact report detail:

```text
Regression: FAIL — could not read baseline ...\data\backtest\replay_baseline.json:
[Errno 2] No such file or directory
```

`data/backtest/forecast_vs_realized.json` was also absent and produced a WARN.
Corpus pinning and replay fidelity both passed. This failure is attributable to
the reduced test topology, not a gzip reader error, but it means the warm-lane
serving-gauntlet result is not comparable to the full-data master result.

### F6 — the contiguous window was conditional, synthetic evidence

The lock was intentionally non-authorizing:

```text
conditional_evidence_only=true
production_evidence_authorized=false
```

- Atlanta: 42 dates, of which 19 source labels were complete and 23 partial
  dates were forced to synthetic `complete`.
- Toronto: 14 dates, of which 11 source labels were complete and 3 partial
  dates were forced to synthetic `complete`.
- The actual point-in-time evaluation locked Atlanta
  `2026-07-14..2026-07-27`.

This proves control flow and artifact contracts, not production readiness.

### F7 — the repository venv is broken on this workstation

The canonical interpreter fails before Python starts:

```text
Unable to create process using
'"C:\Users\Michael\AppData\Local\Programs\Python\Python311\python.exe" --version'
```

The missing Python 3.11 path is recorded in `venv\pyvenv.cfg`. Rehearsal used an
isolated Python 3.12 environment under the one declared scratch output root.
Repair and reverify the canonical venv before lock day.

### F8 — scheduled provenance and ordinary host gates were not accepted

This was a manual workstation rehearsal. Scheduler attestation was `BLOCK`, and
the harness deliberately skipped production readiness, settled-day freshness,
daily learning, experiment queue, and shadow A/B monitor so it could exercise
the previously unreachable release path. Those skips are diagnostic only and
must not appear in the real lock-day invocation.

### F9 — the disk-floor exception did not trigger

Free space was `63.779 GiB` at the start, below the prior `66 GiB` workstation
floor. The handoff's “run MM first” exception therefore did not apply. Free
space was `51.212 GiB` at handback after retaining all scratch evidence. An
unrelated `market-making` Python job appeared after this work began; it was not
started, stopped, or modified here.

## Overall verdict

**Release #1 is NO-GO for a real pointer.**

The technical path is substantially de-risked:

- the former 149 probability-simplex failures are gone;
- the 14-day lock, training, registry, promotion refresh, and 2,000-iteration
  PIT qualification all execute;
- candidate output guards pass;
- a diagnostic continuation can construct and verify a complete immutable
  inactive release;
- a scratch pointer resolves strictly inside the release root and the serving
  loader binds all declared roles.

The production decision remains blocked by the real Atlanta gate, missing
inactive-release parity/shadow procedure, and absence of any rollback target
for the first pointer. Compressed evidence is additionally conditional because
the warm-tier code is not merged.

## Provenance and guardrails

### Source state

| Item | Identity |
| :--- | :--- |
| Pulled `origin/master` | `28d0dfb433e6ac100985d5ec8a8c71c7e2caa904` |
| Master topic branch | `codex/workstation-release-one-rehearsal-2026-07-29` |
| Pending warm probe head | `58ab0dd39293f0f0914dc8e4690b78b64414f21c` |
| Pending warm topic branch | `codex/workstation-release-one-warm-tier-probe-2026-07-29` |
| Declared output root | `C:\Users\Michael\Documents\github\weather\scratch\r30a` |
| Master input manifest SHA-256 | `3680448ad3cf88a939efdd242ed90f245e6d5f132b940870abdb278565e42573` |
| Warm input manifest SHA-256 | `268c8f263710aae3f7c0f52d70715b7d4e4297f57d02390bbdfc86fc3818be78` |

`data/` was read-only. The main-data and scratch-mirror canary writes were
denied. No real release pointer, promotion call, serving change, live fallback,
PR, merge, or master push occurred.

## Mission 1 — current-master rehearsal

### Integrated run

Run root:

```text
C:\Users\Michael\Documents\github\weather\scratch\r30a\r\synthetic_compatibility\m
```

The production-mode nightly command returned `blocked` because the existing
promotion gate did not pass. Technical stages:

| Stage | Status | Seconds |
| :--- | :--- | ---: |
| Point-in-time preselection lock | OK | 112.190 |
| Family-secondary artifacts | OK | 176.160 |
| Pooled feature/model band | OK | 333.823 |
| Artifact registry | OK | 0.457 |
| Promotion refresh | OK | 501.768 |
| Production PIT qualification | OK | 406.868 |
| Candidate release build | SKIPPED | 0.000 |

PIT receipt:

| Field | Value |
| :--- | :--- |
| Status | `PASS` |
| Locked dates | 14 |
| Window | `2026-07-14..2026-07-27` |
| Window lock ID | `e265977f5a53ef19c8a11adcc9dd8fb07ab90ff6cdb6e16ef558dbd177fad629` |
| Input rows | 64,691 |
| Window rows | 26,521 |
| Outside-window rows | 38,170 |
| Excluded cutoffs | **0** |
| Excluded rows | **0** |
| Bootstrap iterations | 2,000 for Brier and log loss |
| Candidate artifact SHA-256 | `b142f327496287fac6c1b3bed5d11d62d784e24f1ddbe7722534480de6817809` |
| Evaluation hash | `9c9d7e3a31a3e5d1447cea1dfc91f4d1ee8672e9e178933ca3a94ec25c67e7` |

Zero excluded cutoffs/rows confirms the 149 simplex failures did not recur.

### Explicit diagnostic continuation

Because the real gate correctly withheld candidate construction, a separate
scratch-only continuation exercised the downstream mechanical path while
preserving the recorded blocked gate:

- candidate output guard: `PASS`
- immutable inactive release: `CREATED`
- release ID: `r1-rehearsal-20260729`
- file count: 219
- release manifest SHA-256:
  `4865ab19b9a84e7d54a249ecda3c26097bde7003ddbb1e0d25a4830c8e5fcc6a`
- production capable: `true`
- promotion eligibility: `BLOCKED_PENDING_POST_FREEZE_EVIDENCE`
- first inactive qualification: `PASS`
- qualification SHA-256:
  `05ab27095a80428a8d7b66aae9e1fe1e8c9880ab47b56cfeeb0ea0f167a06916`
- immutable integrity verified: `true`
- semantic contract verified: `true`
- promotion/serving/live fallback authorized: all `false`

Scratch pointer rehearsal:

- promotion API called: `false`
- real pointer present before/after: `false`
- strict resolution: `PASS`
- serving resolution: `BOUND`
- artifact roles bound: 128
- base model bound: `true`
- scratch pointer SHA-256:
  `a5a18ba637cc84b98a6dfbaa2e8c07c7836ef2f21deba062f69d45f7538b2017`
- temporary pointer archived as
  `current_release.rehearsal-verified.json`
- active scratch pointer absent after rehearsal

## Mission 2 — compressed-evidence verdict

**Conditional PASS for gzip reader/build mechanics; NOT production-authorizing.**

The final pending-warm lane used 42 Atlanta and 14 Toronto real top-level
scratch folders. For the 36 Atlanta folders that had a source
`order_books.jsonl`:

- only `order_books.jsonl.gz` existed in the probe;
- all 36 plain peers were absent;
- all 36 decompressed payload SHA-256 values equalled the source raw SHA-256;
- all 36 gzip header mtime fields were `00000000`;
- the read-only input verifier checked 230 manifest-bound files and returned
  `PASS`.

The other six Atlanta dates had no raw order-book tape to tier and were retained
as explicit missing-source cases.

### Integrated pending-warm run

Run root:

```text
C:\Users\Michael\Documents\github\weather\scratch\r30a\r\synthetic_compatibility\warm-raw-gzip-v7
```

| Stage | Status | Seconds |
| :--- | :--- | ---: |
| Point-in-time preselection lock | OK | 118.864 |
| Family-secondary artifacts | OK | 145.218 |
| Pooled feature/model band | OK | 291.733 |
| Artifact registry | OK | 0.575 |
| Promotion refresh | OK | 489.792 |
| Production PIT qualification | OK | 433.132 |
| Candidate release build | SKIPPED by real gate | 0.000 |

PIT status was `PASS` with the same 14 locked dates, 64,691 input rows,
26,521 window rows, 38,170 outside-window rows, zero excluded cutoffs, zero
excluded rows, and 2,000 bootstrap iterations. Identities:

- candidate artifact SHA-256:
  `647cd1ba582d982cee1ba4b61cd6edd708f4b92be0166393b92966a713a324d5`
- evaluation hash:
  `975fdfde74a33e28e5e79b087681afd69969e50dad5309ce17c2c6af88b833f2`
- window lock ID:
  `e265977f5a53ef19c8a11adcc9dd8fb07ab90ff6cdb6e16ef558dbd177fad629`

The explicit diagnostic continuation then produced:

- release ID: `r1-warm-gzip-v7-rehearsal-20260729`
- immutable inactive release: `CREATED`
- file count: 220
- manifest SHA-256:
  `2d2b427ab05bb74e084648d241c1339d913736248f2bcff548ba81502790e66c`
- first inactive qualification: `PASS`
- qualification SHA-256:
  `c4016001887a91c80ca0b8c42d5feff70d0224fd2b1e3731a570de6989a31324`
- strict scratch-pointer resolution: `PASS`
- serving loader: `BOUND`
- roles bound: 128
- scratch pointer SHA-256:
  `ce6c2a08f38d191f3cdbb85f98312ea059071bc195bde2d45d71c82d677b46d9`
- real pointer absent before/after
- scratch active pointer absent after

No exercised release-path contract required a plain `order_books.jsonl`.
Pending-code reader/tiering/PIT/release tests also passed. This does **not**
prove a future merged master until the warm commit lands and the lane is rerun
with the complete production backtest baseline. It does show no current reason
to size the hot window around a plain raw-order-book dependency in this release
path.

Supplementary existing long-projection evidence reconstructed the
June 28 Atlanta `order_books_long.csv` from raw and matched the decompressed
`order_books_long.csv.gz` byte-for-byte: 16,038 rows and SHA-256
`e7cbf60945ad3d601e0b9eb7736cb5bd9ee7e05aa2ba50b159f9d1513922b25e`.
That is supporting evidence for the older long projection, not a substitute
for the raw gzip lane above.

## Verification

- Master focused suite:
  - `111 passed, 5 subtests passed in 19.26s`
- Pending warm gzip/I/O/tiering/PIT/release suite:
  - `188 passed, 5 subtests passed in 24.49s`
- Main-data and scratch-mirror denied-write canaries: `PASS`
- Production pointer absence after all work: `PASS`

## Mission 3 — exact lock-day go/no-go checklist

This checklist deliberately stops at the current gaps. Commands are PowerShell
and run from the repository root. Replace only the uppercase values and
reviewed evidence paths.

### 0. Repair and identify the host

```powershell
Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$RepoRoot = (Resolve-Path -LiteralPath ".").Path
$Python = Join-Path $RepoRoot "venv\Scripts\python.exe"
& $Python --version
if ($LASTEXITCODE -ne 0) { throw "Canonical venv is not runnable." }

git fetch origin
if ($LASTEXITCODE -ne 0) { throw "Fetch failed." }
git status --short
if ($LASTEXITCODE -ne 0) { throw "Git status failed." }
if (@(git status --porcelain --untracked-files=no).Count -ne 0) {
    throw "Tracked worktree is dirty."
}

$Head = (git rev-parse HEAD).Trim()
$Master = (git rev-parse origin/master).Trim()
if ($Head -ne $Master) { throw "HEAD is not exact origin/master." }
git merge-base --is-ancestor 7232a896 $Head
if ($LASTEXITCODE -ne 0) { throw "Warm tier is not merged into this master." }
```

Expected: runnable canonical interpreter, clean tracked tree, exact current
master, warm-tier commit present.

Failure mode: **STOP**. Do not build a release from a different or dirty code
identity.

### 1. Declare the reviewed lock inputs

```powershell
$AsOf = "YYYY-MM-DD"
$WindowEnd = "YYYY-MM-DD"
$CandidateId = "r1-YYYYMMDD"
$ReviewedFolderList = "C:\REVIEWED\release-one-folders.txt"

$SnapshotsRoot = Join-Path $RepoRoot "data\snapshots"
$ArchiveRoot = Join-Path $RepoRoot "data\archive"
$LedgerRoot = Join-Path $RepoRoot "data\settlements"
$CandidatesRoot = Join-Path $RepoRoot "artifacts\candidates"
$CandidateRoot = Join-Path $CandidatesRoot $CandidateId
$PitWork = Join-Path $CandidateRoot "qualification\point_in_time\work"
$SourceCorpus = Join-Path $PitWork "preselection-source.parquet"
$SourceManifest = Join-Path $PitWork "preselection-source-manifest.json"
$ReplayManifest = Join-Path $PitWork "replay_manifest.json"
$PreselectionLock = Join-Path $PitWork "preselection_lock.json"
$StagingReceipt = Join-Path $PitWork "staging_receipt.json"
$ReleasesRoot = Join-Path $RepoRoot "artifacts\releases"
$Pointer = Join-Path $ReleasesRoot "current_release.json"

$Folders = @(
    Get-Content -LiteralPath $ReviewedFolderList |
    Where-Object { -not [string]::IsNullOrWhiteSpace($_) }
)
if ($Folders.Count -lt 14) { throw "Fewer than 14 reviewed folders." }
foreach ($Folder in $Folders) {
    $Resolved = (Resolve-Path -LiteralPath $Folder).Path
    if (-not $Resolved.StartsWith(
        $SnapshotsRoot.TrimEnd("\") + "\",
        [StringComparison]::OrdinalIgnoreCase
    )) {
        throw "Folder escaped snapshots root: $Resolved"
    }
}

if (Test-Path -LiteralPath $Pointer) {
    throw "Active pointer already exists; this is not a first-release bootstrap."
}
if (Test-Path -LiteralPath $ReleasesRoot) {
    $ReleaseEntries = @(Get-ChildItem -LiteralPath $ReleasesRoot -Force)
    if ($ReleaseEntries.Count -ne 0) {
        throw "Release store is not empty."
    }
}
```

Expected: reviewed settled folders inside `data\snapshots`, no active pointer,
and absent or empty release store.

Failure mode: **STOP**. Never add `--force`, a generic parity skip, or a release
parent to get past this gate.

### 2. Freeze the candidate-independent 14-day population

```powershell
$PrelockArgs = @(
    "-m", "weather.reporting.validation.point_in_time_evaluation",
    "prelock-production",
    "--snapshots-root", $SnapshotsRoot,
    "--archive-root", $ArchiveRoot,
    "--ledger-root", $LedgerRoot,
    "--as-of", $AsOf,
    "--window-end", $WindowEnd,
    "--quality-grades", "complete,manual_override",
    "--max-market-days", "60",
    "--max-rows-per-market-day", "250000",
    "--batch-rows", "65536",
    "--source-corpus-out", $SourceCorpus,
    "--source-manifest-out", $SourceManifest,
    "--replay-manifest-out", $ReplayManifest,
    "--lock-out", $PreselectionLock
)
foreach ($Folder in $Folders) {
    $PrelockArgs += @("--folder", $Folder)
}
& $Python @PrelockArgs
if ($LASTEXITCODE -ne 0) { throw "Production prelock failed." }
```

Expected:

- `$SourceCorpus`
- `$SourceManifest`
- `$ReplayManifest`
- `$PreselectionLock`

The lock must say `PASS`, name exactly 14 contiguous dates, have no missing
calendar dates, and be no more than seven days stale.

Failure modes include incomplete streak, stale window, unsettled/reconstructed
input, root escape, changed bytes, duplicate coordinates, missing winner, or
resource-bound violation. Any is **STOP**.

### 3. Bind and reverify the staged source

```powershell
& $Python -m weather.operations.point_in_time_staging_receipt create `
  --receipt $StagingReceipt `
  --corpus $SourceCorpus `
  --manifest $SourceManifest `
  --replay-manifest $ReplayManifest `
  --ledger-root $LedgerRoot `
  --lock-days 14
if ($LASTEXITCODE -ne 0) { throw "Staging receipt creation failed." }

$ReceiptSha = (
    Get-Content -LiteralPath $StagingReceipt -Raw |
    ConvertFrom-Json
).receipt_sha256

& $Python -m weather.operations.point_in_time_staging_receipt verify `
  --receipt $StagingReceipt `
  --corpus $SourceCorpus `
  --manifest $SourceManifest `
  --replay-manifest $ReplayManifest `
  --ledger-root $LedgerRoot `
  --lock-days 14 `
  --expected-receipt-sha256 $ReceiptSha
if ($LASTEXITCODE -ne 0) { throw "Staged source identity drifted." }
```

Expected: self-hashed receipt with the same corpus, manifest, replay manifest,
ledger, and target-date identities.

Failure mode: **STOP** and preserve the receipt/output for diagnosis.

### 4. Run the complete first-inactive production build

Do not carry the rehearsal's skip flags into this command.

```powershell
& $Python -m weather.operations.nightly_retrain run `
  --candidate-id $CandidateId `
  --release-candidate-mode production `
  --candidates-root $CandidatesRoot `
  --releases-root $ReleasesRoot `
  --release-pointer $Pointer `
  --repo-root $RepoRoot `
  --bootstrap-first-inactive-release `
  --point-in-time-source-corpus $SourceCorpus `
  --point-in-time-source-manifest $SourceManifest `
  --point-in-time-source-replay-manifest $ReplayManifest `
  --point-in-time-source-receipt $StagingReceipt `
  --point-in-time-archive-root $ArchiveRoot `
  --point-in-time-as-of $AsOf `
  --point-in-time-window-end $WindowEnd `
  --point-in-time-max-market-days 60 `
  --point-in-time-max-rows-per-market-day 250000 `
  --point-in-time-batch-rows 65536 `
  --point-in-time-outer-min-train-dates 14 `
  --point-in-time-inner-min-train-dates 7 `
  --point-in-time-embargo-days 3 `
  --point-in-time-step-dates 7 `
  --point-in-time-max-fold-scopes 128 `
  --point-in-time-bootstrap-iterations 2000 `
  --point-in-time-private-memory-budget-bytes 4294967296 `
  --fail-on-block
if ($LASTEXITCODE -ne 0) {
    throw "Nightly release build blocked; inspect nightly status before retry."
}
```

Expected:

- every ordinary readiness/training/promotion/PIT gate passes;
- `$CandidateRoot\qualification\point_in_time\` contains the four hash-bound
  roles;
- `$ReleasesRoot\$CandidateId\release_manifest.json` exists;
- first inactive qualification is `PASS`;
- activation is `NONE`;
- `$Pointer` remains absent.

Failure mode: **STOP**. The observed rehearsal stops here with
`existing_validation_gates_not_passed`.

### 5. Verify the immutable inactive release

```powershell
& $Python -m weather.operations.release_lifecycle `
  --releases-root $ReleasesRoot `
  --pointer $Pointer `
  --repo-root $RepoRoot `
  verify $CandidateId
if ($LASTEXITCODE -ne 0) { throw "Immutable release verification failed." }

if (Test-Path -LiteralPath $Pointer) {
    throw "Nightly unexpectedly activated the release."
}
```

Expected: full integrity, runtime, semantic-contract, exact-code, and manifest
verification; pointer still absent.

Failure mode: **STOP**. Do not use `--integrity-only` as promotion evidence.

### 6. Mandatory current stop: parity, forward shadow, and rollback

Current repository state has no safe exact command sequence that both:

1. gathers exact release-bound served/replay parity and forward shadow while
   the production release is inactive; and
2. guarantees rollback after promoting the first pointer.

Therefore lock-day status is **NO-GO at this step**, even if steps 0–5 pass.
Do not use `--bootstrap-first-release`; that is a separate research-only
serving-identity exception and is not the first inactive production workflow.

### 7. Promotion command, only after F2 and F3 are resolved

Once repository-owned parity/shadow evidence exists, a predecessor or safe
first-release recovery exists, and a reviewer has produced matching proofs:

```powershell
$Decision = "C:\REVIEWED\$CandidateId-promotion-decision.json"
$Boundary = "C:\REVIEWED\$CandidateId-market-day-boundary.json"

& $Python -m weather.operations.release_lifecycle `
  --releases-root $ReleasesRoot `
  --pointer $Pointer `
  --repo-root $RepoRoot `
  promote $CandidateId `
  --decision $Decision `
  --market-day-boundary $Boundary
if ($LASTEXITCODE -ne 0) { throw "Promotion failed closed." }

& $Python -m weather.operations.release_lifecycle `
  --releases-root $ReleasesRoot `
  --pointer $Pointer `
  --repo-root $RepoRoot `
  active
if ($LASTEXITCODE -ne 0) { throw "Active pointer verification failed." }
```

The decision must bind the exact release/manifest identity and declare
`decision=PROMOTE`, `gate_status=PASS`, `candidate_only_build=true`,
`reviewed=true`, reviewer identity, and timezone-aware review time. The boundary
must be under 15 minutes old, bind the same release/manifest, declare quiesced
processes, and list no open or mixed-release market days.

Expected: atomic pointer sequence 1, exact release identity, and
`restart_required=true`. Coordinated runtime restart and post-restart identity
health remain required before serving adoption is complete.

### 8. Rollback command for releases that have a verified predecessor

```powershell
$RollbackBoundary = "C:\REVIEWED\rollback-market-day-boundary.json"
$RollbackDrill = Join-Path $RepoRoot "data\backtest\release_rollback_drill.json"

& $Python -m weather.operations.release_lifecycle `
  --releases-root $ReleasesRoot `
  --pointer $Pointer `
  --repo-root $RepoRoot `
  rollback `
  --market-day-boundary $RollbackBoundary `
  --drill-record $RollbackDrill
if ($LASTEXITCODE -ne 0) { throw "Rollback failed closed." }

& $Python -m weather.operations.release_lifecycle `
  --releases-root $ReleasesRoot `
  --pointer $Pointer `
  --repo-root $RepoRoot `
  active
if ($LASTEXITCODE -ne 0) { throw "Post-rollback pointer verification failed." }
```

Expected: atomic pointer return to the hash-verified predecessor and a drill
record initially marked `PENDING_MANUAL_RESTART`, followed by coordinated
restart, runtime-identity proof, and post-restart health.

For the current release #1 design this command is expected to fail with
`active release pointer has no verified rollback target`. That is F2, not an
operator error.

## Handback

Keep all outputs under:

```text
C:\Users\Michael\Documents\github\weather\scratch\r30a
```

They include every failed topology attempt, final master and warm receipts,
diagnostic immutable releases, archived scratch pointers, compressed-input
manifests, and byte-identity evidence. They are ignored scratch state and were
not cleaned because they are the evidence behind this report.
