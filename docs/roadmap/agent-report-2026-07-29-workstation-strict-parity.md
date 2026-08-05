# Agent report - 2026-07-29 workstation strict parity

Status: **NO-GO. Toronto is not qualified by the current evidence, the
immutable release has no Toronto route, and Toronto's captured-input tape
cannot pass the strict identity contract. `NOT_ACCOUNTED_FOR` remains open.**

This handback executes
`docs/roadmap/workstation-handoff-2026-07-30c-toronto-scope-and-strict-parity.md`
from exact `origin/master`
`5954da1b2129615259cc2bd2b939db12688365f0`, with the already-pushed blocker
foundation `0beb40b8c7e4dab78e376a32bb7028d5e02db496` stacked into the topic branch.

## Executive verdict

1. **Toronto itself does not currently qualify.** The production-mode
   promotion artifact is an F-family evaluation and makes no Toronto allowlist
   decision. Its separate Toronto early-hour row is `BLOCK`. The current
   immutable release has no Toronto route, and the production readiness gate is
   `BLOCK`.
2. **Strict Toronto forward shadow blocks before inference.** The current
   release first blocks because it has no executable Toronto route. Independent
   tape verification then proves that a correctly routed release would block
   on the first captured-input row.
3. **The hash defect reaches Toronto and eight of twelve markets on the current
   day.** It is not Austin-specific.
4. **The hash defect is not the `order_books_long` tiering race.** It is a new,
   deterministic capture-time key-type normalization defect. A separate
   malformed Toronto line on July 24 is consistent with concurrent append
   corruption and is in the same broad writer-race class as the split pair.
5. **The requested two-week strict result does not exist.** The 14 Toronto
   market-days contain 2,470 invalid self-hashes and one malformed JSON line.
   There are zero strict-grade partitions available for parity.
6. **The missing incumbent number was already present in a self-hashed PASS
   packet but was not surfaced as the baseline.** On the clean POST F-family
   population, incumbent binary Brier is `0.0637034034` versus raw market
   `0.0382799819`, or **1.664x market**. It is worse than preblend and
   replay-final.

No pointer, promotion, serving, model, configuration, or `data/` mutation was
performed.

## 1. Toronto qualification

### Verdict: not qualified

The operator's desired scope is coherent as a future release shape: Toronto
would be the only promoted market and all eleven F markets would remain
shadow/blocked. The current evidence does not authorize that shape.

The exact production rehearsal artifact is:

```text
C:\Users\Michael\Documents\github\weather\scratch\r30a\r\synthetic_compatibility\m\artifacts\candidates\r1-rehearsal-20260729\qualification\promotion\promotion_refresh.json
```

It declares `family_unit=F`. Its promotion allowlist contains exactly the
eleven F markets, has `promote_count=0`, and contains no Toronto decision.
Toronto's separate early-hour diagnostic is:

| Field | Value |
| :--- | ---: |
| Status | **BLOCK** |
| Blocking gates | `early_hour_brier_regression`, `early_hour_logloss_regression` |
| Rows | 4,323 |
| Snapshots | 393 |
| Market-days | 46 |
| Model Brier | `0.0811212367` |
| Raw-market Brier | **`0.0621242196`** |
| Model log loss | `0.2805083142` |
| Raw-market log loss | **`0.1994020450`** |

The exact immutable release,
`r1-rehearsal-20260729`, manifest SHA-256
`4865ab19b9a84e7d54a249ecda3c26097bde7003ddbb1e0d25a4830c8e5fcc6a`,
contains Atlanta `blocked` plus ten F markets `shadow`. Toronto is absent.
Running the strict forward-shadow command from the source identity bound into
that release fails closed with:

```text
InactiveReleaseForwardShadowError:
inactive release has no executable shadow/promote route for 'toronto'
```

The current generic production-readiness evidence at
`data/backtest/production_readiness_gate.json`, generated
`2026-07-29T05:00:05.772583+00:00`, is also `BLOCK` / `NOT_READY` with 69
blockers. Finally, `weather.operations.nightly_retrain run --help` permits only
`--family-unit {F}`. There is no canonical C-family production candidate build
path to substitute.

Therefore:

- **Toronto is not a promotion candidate under the current allowlist.**
- **Toronto does not have a production-capable immutable route.**
- **A Toronto-only promotion decision cannot honestly be written today.**

This is a model/evidence and release-construction blocker, not a request to
relax a gate.

## 2. Strict Toronto verdict

The current July 29 Toronto input is:

```text
C:\Users\Michael\Documents\github\weather\data\snapshots\highest-temperature-in-toronto-on-july-29-2026\replay_inputs.jsonl
```

Its SHA-256 is
`5d165bab3b003f2a7aadebeb4f5d25c3c3c134767072b775c1b765f4bd730f8d`.
All 35 rows declare
`sha256-canonical-json;omit=captured_input_hash`; all 35 claimed hashes are
invalid under that declared algorithm and match compact insertion-order JSON
instead.

The first current-day failure is:

| Field | Value |
| :--- | :--- |
| Snapshot | `20260729T000030191354-0400` |
| Captured | `2026-07-29T04:00:30.191354+00:00` |
| Claimed | `36e44b007365f774863a878ca44a6d3e18a69f643fdf8627a093e542cc629c0a` |
| Canonical | `4e44ee0e6208561b5b34a967278ac1db9604608ec51f0e7f506a00f4e47562e2` |
| Claimed equals insertion-order | `true` |

The last observed current-day failure is:

| Field | Value |
| :--- | :--- |
| Snapshot | `20260729T045421266167-0400` |
| Captured | `2026-07-29T08:54:21.266167+00:00` |
| Claimed | `e09aa1c3d9c03c4f283b5d94d0a29cd98ece230e9fb6de23c6839c0f1209cfa6` |
| Canonical | `9e122f641fc2a6264706a323f401a41a20bcd803c9fefd72e75d26c2c1dd2101` |
| Claimed equals insertion-order | `true` |

The first observed Toronto hash-bearing row went invalid during the July 11
market-day tape:

| Field | Last legacy row | First hash-bearing row |
| :--- | :--- | :--- |
| Captured | `2026-07-12T00:56:33.405441+00:00` | `2026-07-12T01:13:08.271825+00:00` |
| Snapshot | `20260711T205633405441-0400` | `20260711T211308271825-0400` |
| Schema | `toronto_replay_inputs_v0.1` | `toronto_replay_inputs_v0.2` |
| Claimed | absent | `7a17a19725049277553a3f536f0590c1b6133e3fe0833d6747cce98d85fa6cae` |
| Canonical | n/a | `31cbf18894557b55fcffc71db604c8a1a010a080f9645849a979ea4da7372326` |

Thus the Toronto lane has two ordered blockers:

1. no Toronto route in the immutable release; and
2. invalid captured-input identity before predictor execution.

No derived hash repair is strict evidence. The original tape was not changed.

## 3. Invalid-hash scope and cause

### Current fleet

The full July 29 scan read all 284 available rows across every fleet market:

| Market | Rows | Canonical | Invalid insertion-order | Current verdict |
| :--- | ---: | ---: | ---: | :--- |
| Atlanta | 33 | 0 | 33 | BLOCK |
| Austin | 24 | 0 | 24 | BLOCK |
| Chicago | 24 | 24 | 0 | PASS |
| Dallas | 24 | 0 | 24 | BLOCK |
| Denver | 18 | 0 | 18 | BLOCK |
| Houston | 25 | 0 | 25 | BLOCK |
| Los Angeles | 11 | 11 | 0 | PASS |
| Miami | 33 | 0 | 33 | BLOCK |
| NYC | 33 | 0 | 33 | BLOCK |
| San Francisco | 12 | 12 | 0 | PASS |
| Seattle | 12 | 12 | 0 | PASS |
| Toronto | 35 | 0 | 35 | BLOCK |
| **Total** | **284** | **59** | **225** | **8 / 12 markets block** |

The first observed invalid capture by market is:

| Market | First observed invalid UTC | Current July 29 |
| :--- | :--- | :--- |
| Atlanta | `2026-07-17T04:00:36.774293+00:00` | invalid |
| Austin | `2026-07-12T01:13:15.672143+00:00` | invalid |
| Chicago | `2026-07-13T05:00:37.319881+00:00` | canonical |
| Dallas | `2026-07-12T01:13:27.256934+00:00` | invalid |
| Denver | `2026-07-12T01:12:36.329536+00:00` | invalid |
| Houston | `2026-07-12T01:13:33.426281+00:00` | invalid |
| Los Angeles | none observed | canonical |
| Miami | `2026-07-12T01:13:44.066455+00:00` | invalid |
| NYC | `2026-07-12T01:28:33.047197+00:00` | invalid |
| San Francisco | `2026-07-22T03:20:41.278189+00:00` | canonical |
| Seattle | `2026-07-21T07:01:04.343184+00:00` | canonical |
| Toronto | `2026-07-12T01:13:08.271825+00:00` | invalid |

This is not a monotonic writer-version transition. A market becomes
verifiable or unverifiable according to the numeric support present in that
captured distribution.

### Root cause

`captured_input_hash` is computed before JSON persistence. At that point
`recorded_distribution` has integer band keys, so `sort_keys=True` sorts them
numerically. JSON persistence converts object keys to strings. Strict replay
loads those strings and canonical sorting becomes lexicographic.

Toronto's first unordered mapping is always:

```text
recorded_distribution observed: 8,9,10,11,...,36
recorded_distribution canonical string order: 10,11,...,36,8,9
```

The failing F markets cross the corresponding `99,100` width boundary. The
currently passing F markets keep a same-width support, so numeric and
lexicographic order coincide.

The declared algorithm therefore hashes two different logical types on the two
sides of a JSON round trip. The claimed digest happens to equal insertion-order
JSON after reload, but this is not an arbitrary key-order writer bug.

### Relationship to the split `order_books_long` pairs

The captured-input hash defect is **new and distinct**:

- it is already present in active `replay_inputs.jsonl`;
- it is created before closed-day projection or tiering;
- it is deterministic from integer-to-string key normalization; and
- it does not require two writers or a tier transition.

There is, however, one separate writer-race finding. Toronto July 24 line 46 is
malformed JSON, raw-line SHA-256
`8f17b3b1de8d85a101bbe3f50b32aa7f03f00df90d2e801806fa78856054e47f`.
At character 8,155 a second JSON object starts inside the first object's
`runtime_identity.source_scope_files` array. The line contains capture
timestamps around `09:34:37Z` and `09:43:42Z`. This is consistent with
interleaved append corruption and belongs to the same broad concurrent-writer
integrity class as the split pair, but it is not the cause of the other 2,470
hash failures.

## 4. Lock-day ordered checklist

This checklist is Toronto-only in promotion authority: Toronto must be
`promote`; the eleven F markets may be present only as `shadow` or `blocked`.
It is not fully executable today. Step 4 is a mandatory stop until a canonical
C-family production candidate path exists and Toronto passes its unmodified
quality gates.

All commands are PowerShell from the repository root. Before promotion,
failure rollback is **leave the pointer absent, preserve evidence, stop**.
After promotion, use step 8.

### Step 0 - exact host and code identity

```powershell
Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$RepoRoot = (Resolve-Path -LiteralPath ".").Path
$Python = Join-Path $RepoRoot "venv\Scripts\python.exe"
$ReviewedCommit = "REPLACE_WITH_REVIEWED_40_HEX_COMMIT"

& $Python --version
if ($LASTEXITCODE -ne 0) { throw "Canonical venv is not runnable." }

git fetch origin
if ($LASTEXITCODE -ne 0) { throw "Fetch failed." }
if (@(git status --porcelain --untracked-files=no).Count -ne 0) {
    throw "Tracked worktree is dirty."
}
$Head = (git rev-parse HEAD).Trim()
$OriginMaster = (git rev-parse origin/master).Trim()
if ($Head -ne $ReviewedCommit) { throw "HEAD differs from reviewed commit." }
if ($OriginMaster -ne $ReviewedCommit) {
    throw "Reviewed commit is not exact origin/master."
}
```

Expected artifact: terminal capture of Python version, clean status, and one
exact reviewed commit.

Failure: **STOP**. The canonical repository `venv` is currently broken on this
host, so this step does not pass today.

Rollback: none; no pointer or candidate write has occurred.

### Step 1 - declare and validate exactly fourteen Toronto folders

```powershell
$AsOf = "YYYY-MM-DD"
$WindowEnd = "YYYY-MM-DD"
$CandidateId = "r1-toronto-YYYYMMDD"
$ReviewedFolderList = "C:\REVIEWED\$CandidateId-folders.txt"

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
$EvidenceRoot = Join-Path $RepoRoot "scratch\lock-day\$CandidateId"

$Folders = @(
    Get-Content -LiteralPath $ReviewedFolderList |
    Where-Object { -not [string]::IsNullOrWhiteSpace($_) }
)
if ($Folders.Count -ne 14) { throw "Expected exactly 14 Toronto folders." }

$Dates = @()
foreach ($Folder in $Folders) {
    $Resolved = (Resolve-Path -LiteralPath $Folder).Path
    if (-not $Resolved.StartsWith(
        $SnapshotsRoot.TrimEnd("\") + "\",
        [StringComparison]::OrdinalIgnoreCase
    )) { throw "Folder escaped snapshots root: $Resolved" }
    $Replay = Join-Path $Resolved "replay_inputs.jsonl"
    $Snapshots = Join-Path $Resolved "snapshots.jsonl"
    if (-not (Test-Path -LiteralPath $Replay)) { throw "Missing $Replay" }
    if (-not (Test-Path -LiteralPath $Snapshots)) { throw "Missing $Snapshots" }
    $First = Get-Content -LiteralPath $Replay -TotalCount 1 | ConvertFrom-Json
    if ($First.event_slug -notlike "highest-temperature-in-toronto-on-*") {
        throw "Non-Toronto folder: $Resolved"
    }
    $Dates += [DateTime]::ParseExact(
        [string]$First.target_date, "yyyy-MM-dd", $null
    )
}
$Dates = @($Dates | Sort-Object -Unique)
if ($Dates.Count -ne 14) { throw "Toronto dates are not unique." }
for ($Index = 1; $Index -lt $Dates.Count; $Index++) {
    if (($Dates[$Index] - $Dates[$Index - 1]).Days -ne 1) {
        throw "Toronto window is not contiguous."
    }
}
if (Test-Path -LiteralPath $Pointer) {
    throw "Active pointer already exists; this is not first-release bootstrap."
}
```

Expected artifact: reviewed list containing exactly fourteen contiguous,
settled Toronto market-days and no other market.

Failure: **STOP** on missing, reconstructed, malformed, non-Toronto,
non-contiguous, or already-active state.

Rollback: none; inputs are read-only.

### Step 2 - freeze the candidate-independent PIT population

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
    "--max-market-days", "14",
    "--max-rows-per-market-day", "250000",
    "--batch-rows", "65536",
    "--source-corpus-out", $SourceCorpus,
    "--source-manifest-out", $SourceManifest,
    "--replay-manifest-out", $ReplayManifest,
    "--lock-out", $PreselectionLock
)
foreach ($Folder in $Folders) { $PrelockArgs += @("--folder", $Folder) }
& $Python @PrelockArgs
if ($LASTEXITCODE -ne 0) { throw "Toronto production prelock failed." }
```

Expected artifacts: `$SourceCorpus`, `$SourceManifest`, `$ReplayManifest`, and
`$PreselectionLock`; the lock must be `PASS`, name exactly 14 contiguous
Toronto dates, have no exclusions, and be no more than seven days stale.

Failure: **STOP** on incomplete settlement, changed bytes, malformed capture,
missing winner, duplicate coordinate, reconstruction, root escape, stale
window, or resource bound.

Rollback: preserve candidate-only artifacts; pointer remains absent.

### Step 3 - bind and reverify staged bytes

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
    Get-Content -LiteralPath $StagingReceipt -Raw | ConvertFrom-Json
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

Expected artifact: a self-hashed receipt binding corpus, manifests, ledger, and
all fourteen target dates.

Failure: **STOP** and preserve the receipt.

Rollback: pointer remains absent.

### Step 4 - mandatory current stop: qualify and build Toronto

There is no honest command for this step on current master:

- `weather.operations.nightly_retrain run` accepts only `--family-unit {F}`;
- the current allowlist has no Toronto row;
- the current release route omits Toronto; and
- Toronto's available early-hour comparison is `BLOCK`.

Do **not** run the F-family command against Toronto folders, hand-edit the
allowlist, hand-author a promote route, or use a research-only bootstrap.

Expected artifact after the missing capability is implemented: a
production-capable, candidate-only Toronto qualification with unmodified gates
at `PASS`, plus an immutable release whose manifest route promotes Toronto and
does not promote any F market.

Failure: anything except exact PASS is **STOP**.

Rollback: leave `$Pointer` absent.

### Step 5 - verify route, immutable release, and fourteen strict shadows

Run only after step 4 has a supported command and PASS output.

```powershell
$ReleaseDir = Join-Path $ReleasesRoot $CandidateId
$ManifestPath = Join-Path $ReleaseDir "release_manifest.json"
$Manifest = Get-Content -LiteralPath $ManifestPath -Raw | ConvertFrom-Json
$ManifestSha = [string]$Manifest.manifest_sha256
$FMarkets = @(
    "atlanta", "austin", "chicago", "dallas", "denver", "houston",
    "los-angeles", "miami", "nyc", "san-francisco", "seattle"
)

if ($Manifest.route.markets.toronto.decision -ne "promote") {
    throw "Toronto is not the promoted route."
}
if (-not $Manifest.route.markets.toronto.candidate_variant_id) {
    throw "Toronto route has no executable candidate."
}
foreach ($Market in $FMarkets) {
    if ($Manifest.route.markets.$Market.decision -eq "promote") {
        throw "F market unexpectedly promoted: $Market"
    }
}

& $Python -m weather.operations.release_lifecycle `
  --releases-root $ReleasesRoot `
  --pointer $Pointer `
  --repo-root $RepoRoot `
  verify $CandidateId
if ($LASTEXITCODE -ne 0) { throw "Immutable release verification failed." }
if (Test-Path -LiteralPath $Pointer) {
    throw "Inactive verification unexpectedly created a pointer."
}

$TorontoZone = [TimeZoneInfo]::FindSystemTimeZoneById("Eastern Standard Time")
foreach ($Folder in $Folders) {
    $Replay = Join-Path $Folder "replay_inputs.jsonl"
    $Snapshots = Join-Path $Folder "snapshots.jsonl"
    $First = Get-Content -LiteralPath $Replay -TotalCount 1 | ConvertFrom-Json
    $Day = [string]$First.target_date
    $LocalStart = [DateTime]::SpecifyKind(
        [DateTime]::ParseExact($Day, "yyyy-MM-dd", $null),
        [DateTimeKind]::Unspecified
    )
    $StartUtc = [TimeZoneInfo]::ConvertTimeToUtc(
        $LocalStart, $TorontoZone
    ).ToString("o")
    $EndUtc = [TimeZoneInfo]::ConvertTimeToUtc(
        $LocalStart.AddDays(1), $TorontoZone
    ).ToString("o")

    & $Python -m weather.reporting.scorecards.inactive_release_forward_shadow `
      --release-dir $ReleaseDir `
      --manifest-sha256 $ManifestSha `
      --market-id toronto `
      --target-date $Day `
      --captured-inputs $Replay `
      --snapshot-tape $Snapshots `
      --window-start $StartUtc `
      --window-end $EndUtc `
      --active-release-pointer $Pointer `
      --repo-root $RepoRoot `
      --max-snapshots 500 `
      --float-tolerance 1e-12 `
      --output-root $EvidenceRoot
    if ($LASTEXITCODE -ne 0) { throw "Strict Toronto shadow blocked: $Day" }

    $ResultPath = Join-Path $EvidenceRoot "toronto\$Day\forward_shadow.json"
    $Result = Get-Content -LiteralPath $ResultPath -Raw | ConvertFrom-Json
    if ($Result.status -ne "PASS") { throw "Shadow status is not PASS: $Day" }
    if (
        $Result.summary.tolerance_whole_partition_matches.inactive_incumbent `
        -ne $Result.summary.snapshot_count
    ) { throw "Incumbent does not reproduce every partition: $Day" }
}
```

Expected artifacts: verified release manifest plus fourteen self-hashed
`forward_shadow.json`/Markdown pairs. Report total partitions, worst incumbent
absolute delta, every nonmatch, and the first exact and first material pipeline
divergence.

Failure: **STOP** on any route, runtime, manifest, tape, hash, feature,
probability-mass, coverage, or incumbent-tolerance failure. Never use
`--integrity-only` or rewrite a captured hash as promotion evidence.

Rollback: pointer remains absent.

### Step 6 - reviewed decision and fresh boundary

```powershell
$Decision = "C:\REVIEWED\$CandidateId-promotion-decision.json"
$Boundary = "C:\REVIEWED\$CandidateId-market-day-boundary.json"

$DecisionObject = Get-Content -LiteralPath $Decision -Raw | ConvertFrom-Json
$BoundaryObject = Get-Content -LiteralPath $Boundary -Raw | ConvertFrom-Json
if ($DecisionObject.decision -ne "PROMOTE") { throw "Decision is not PROMOTE." }
if ($DecisionObject.gate_status -ne "PASS") { throw "Gate is not PASS." }
if (-not $DecisionObject.reviewed) { throw "Decision is not reviewed." }
if ($DecisionObject.release_id -ne $CandidateId) {
    throw "Decision release mismatch."
}
if ($BoundaryObject.release_id -ne $CandidateId) {
    throw "Boundary release mismatch."
}
```

Expected artifacts: separate reviewed, self-hashed decision and a less-than
15-minute-old boundary proof binding the exact release/manifest, quiesced
processes, and no open or mixed-release market-day.

Failure: **STOP**. Do not create either proof automatically inside the
promotion command.

Rollback: pointer remains absent.

### Step 7 - atomically promote and verify the pointer

This is the first command in the checklist that may create the real pointer.
It requires separate explicit operator authorization on lock day.

```powershell
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

Expected artifact: atomic pointer sequence 1 bound to exact release and
manifest identity, `restart_required=true`, and strict active resolution.

Failure after the pointer exists: proceed immediately to step 8 with a fresh
rollback boundary. Do not remove the pointer by hand.

### Step 8 - first-release rollback to `NO_ACTIVE_POINTER`

```powershell
$RollbackBoundary = "C:\REVIEWED\$CandidateId-rollback-boundary.json"
$RollbackDrill = Join-Path $RepoRoot "data\backtest\release_rollback_drill.json"

& $Python -m weather.operations.release_lifecycle `
  --releases-root $ReleasesRoot `
  --pointer $Pointer `
  --repo-root $RepoRoot `
  rollback `
  --market-day-boundary $RollbackBoundary `
  --drill-record $RollbackDrill
if ($LASTEXITCODE -ne 0) { throw "First-release rollback failed closed." }

if (Test-Path -LiteralPath $Pointer) {
    throw "Pointer still exists after first-release rollback."
}
$Drill = Get-Content -LiteralPath $RollbackDrill -Raw | ConvertFrom-Json
if ($Drill.rollback_target_state -ne "NO_ACTIVE_POINTER") {
    throw "Rollback did not target NO_ACTIVE_POINTER."
}
if ($Drill.post_rollback_identity.serving_bundle_status -ne "RESEARCH_UNBOUND") {
    throw "No-pointer serving proof failed."
}
```

Expected artifact: durable self-hashed intent/drill bound to the source pointer,
absent active pointer, null restored release, target
`NO_ACTIVE_POINTER`, and canonical `RESEARCH_UNBOUND` /
`research_unbound_non_countable` serving proof. The initial drill remains
truthfully `PENDING_MANUAL_RESTART` until the coordinated runtime restart and
identity proof are completed.

Failure: preserve the intent and rerun only the canonical rollback command; its
reconciliation path never recreates or toggles the pointer.

## 5. Widened parity

### Verdict: not run at strict grade

The prerequisite "Toronto passes strict" is false. The read-only two-week audit
covered target dates 2026-07-16 through 2026-07-29:

| Measure | Result |
| :--- | ---: |
| Market-days | 14 |
| Replay lines | 2,471 |
| Invalid insertion-order hashes | **2,470** |
| Malformed JSON lines | **1** |
| Canonical strict inputs | **0** |
| Strict partitions compared | **0** |
| Worst strict divergence | not measurable |

No partition was upgraded from diagnostic to strict. The Austin diagnostic
remains useful localization:

- incumbent: 24 / 24 partitions within `1e-12`;
- worst incumbent delta: `2.220446049250313e-16`;
- first exact difference: feature-vector float representation;
- first material candidate divergence: `candidate_raw`.

It does not close `NOT_ACCOUNTED_FOR`.

## 6. Incumbent versus raw market on clean POST

The requested baseline is already computed in the PASS packet:

```text
C:\Users\Michael\Documents\github\weather\scratch\workstation-research-output\regime-split-20260728f-9ad438a2
```

The analysis, harness, and receipt still match their recorded hashes:

| Artifact | SHA-256 |
| :--- | :--- |
| `regime_split_analysis.json` | `9ca018427e8a33703fe3152ec8165e5800b1a6d6e8426012ca44dde941e265ab` |
| `regime_split_audit.py` | `9a5689d237687c7ba11e779f35a284d1ea7665e7a2b427e4e9b477c8cfca7aac` |
| `regime_split_receipt.json` | `723b1a2d625b742625e5c84d3aabbd1c05e2a427a7065e716d0c3aa600ac8872` |

The clean POST population has 11 F markets, 8 target dates, 11,662 composite
keys, and 128,293 binary rows. The full market-stratified, row-weighted exact
CORP/isotonic Murphy decomposition is:

| Lane | Binary Brier | REL | RES | UNC | Multiple of raw market |
| :--- | ---: | ---: | ---: | ---: | ---: |
| Preblend | `0.0475721595` | `0.0039016628` | `0.0389741314` | `0.0826446281` | **1.243x** |
| Replay-final | `0.0498532509` | `0.0054229099` | `0.0382142871` | `0.0826446281` | **1.302x** |
| **Incumbent** | **`0.0637034034`** | `0.0059612493` | **`0.0249024740`** | `0.0826446281` | **1.664x** |
| Raw market | **`0.0382799819`** | `0.0051010574` | **`0.0494657037`** | `0.0826446281` | 1.000x |

The incumbent-market gap is `0.0254234216`. Reliability contributes
`0.0008601919`; the resolution deficit contributes `0.0245632297`, or
**96.62%** of the gap. Incumbent is worse than preblend by `0.0161312439` and
worse than replay-final by `0.0138501525`.

Therefore the baseline any F-family candidate must beat is not the quoted
1.243x preblend lane. The measured incumbent is materially worse at **1.664x
raw-market Brier**.

Authority caveat: this is a valid self-hashed offline POST score for
`current_probability`. The Austin forward-shadow diagnostic strongly supports
that this is the served incumbent transformation, but the blocked Toronto and
two-week strict lanes do not upgrade it to fleet-wide strict production
identity.

## Evidence and guardrails

Read-only diagnostic artifacts are under:

```text
C:\Users\Michael\Documents\github\weather\scratch\r30c\audit
```

Key hashes:

| Evidence | SHA-256 |
| :--- | :--- |
| July 29 full-fleet audit | `ae699e27dbffc888e22cf2f3fc8e895090c672c5afa914604910a7fd0b4dfb92` |
| 651-file historical edge inventory | `ab1e8989ca40b3e2d4b89ba89aeb8c6add95449a2d0d37a5662419bb2a79b99` |
| Exact first-invalid transition group | `afa78c118a43490e86760215c9ab2d59de880eadcb024cd3c4a9761d6621e52d` |
| Toronto 14-day full-row audit | `aeb5638b9e7f6ca3dd786b4c6f3ab335a2218764fa3ab290ba8dddcecf109ea` |

`data/` was read only. No captured hash, malformed line, tape, ledger, release
store, or real pointer was repaired, removed, or rewritten. No PR, merge to
master, or master push occurred.

Verification:

- `git diff --check`: PASS;
- agent documentation audit: PASS, 18 agent files and 524 Markdown files;
- release lifecycle plus inactive forward-shadow tests: 22 passed;
- strict Toronto command with the correct production pointer path: expected
  fail-closed `BLOCK` on missing Toronto route.
