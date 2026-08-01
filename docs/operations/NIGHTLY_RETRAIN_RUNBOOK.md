# Nightly Retrain, Validate, And Build Candidate Release Runbook

This runbook covers the overnight self-improvement job that refreshes daily
learning, retrains candidate artifacts, validates promotion evidence, and
writes one operator-readable status report. It never activates a model: the
scheduled job can only build an immutable, inactive candidate release.

## Choose One Scheduling Topology

There are two alternative scheduling patterns:

- Dedicated single-host capture: `register_training_window.ps1` owns a bounded
  maintenance window that stops and always restores all three capture loops.
- Separate-capacity/direct scheduling: `register_nightly_retrain.ps1` owns
  `WeatherNightlyRetrainValidatePromote`, which defaults to `03:30` local time.

Do not enable both patterns for the same workload. The direct registration
requires explicit served/replay captured-input parity files, served artifact
bindings, and the served route. Read its `param(...)` block and provide reviewed
current paths; there is intentionally no argument-free production example.

Both patterns are scheduler-attested, but their process topology is different.
The direct task records `scheduler-invocation-topology=direct` and requires its
registered Python executable, complete argument vector, working directory,
running state, and task-run time to match the producer exactly. Its OS-observed
process chain must bind the current PID, base-Python image and complete command,
current working directory, and expected venv redirector to the current Task
Scheduler engine PID and instance identity. The single-host window is a
scheduled PowerShell wrapper. Its registration and runtime share
`scripts/ops/training_window_contract.ps1`; the nightly Python child records
`delegated_child`, the exact registered wrapper action tokens, its own Python
executable and arguments, the repository working directory, and a correlation
allowance that covers the bounded capture-stop phase. The same bounded Windows
lineage then continues through at most the expected venv redirector to the
exact PowerShell engine PID, image, complete command line, and start time for
the current task instance. Child, redirector, wrapper, and scheduler-run start
times must be present and ordered within their declared bounds. A missing,
disabled, stale, unrelated, over-deep, or mismatched parent/child contract
remains `manual_or_unverified` and is not countable production evidence.
Re-register the window after any task name, PowerShell executable, repository
path, or wrapper action change.

The direct task calls:

```powershell
python -m weather.operations.nightly_retrain run --fail-on-daily-learning-blocker
```

That flag is also the CLI default. It makes `daily_learning.status == BLOCKED`
stop the run before expensive retraining or promotion refresh steps.

## Research And Production Candidate Modes

`--release-candidate-mode research_only` is the default. It preserves the
ordinary candidate-only research workflow and schedules no production
point-in-time prelock or qualification steps.

Production capability is explicit and requires the narrow, candidate-
independent `production_point_in_time_preselection_source_v1` source. Supply
either repeated `--point-in-time-folder` arguments, or the paired
`--point-in-time-source-corpus` and `--point-in-time-source-manifest` paths. The
generic candidate-scoring materialization schema is rejected. Folder mode
builds a quality-grade-only replay manifest, then projects every manifest-
pinned captured snapshot/band without loading a model. A reviewed
`--point-in-time-source-replay-manifest` may pin the replay inventory; when it
is omitted for a staged source, the prelock copies the exact replay manifest
already hash-bound by that source. For example:

```powershell
python -m weather.operations.nightly_retrain run `
  --release-candidate-mode production `
  --point-in-time-source-corpus <production-preselection-source-v1.parquet> `
  --point-in-time-source-manifest <production-preselection-source-v1-manifest.json> `
  --point-in-time-source-replay-manifest <promotion-corpus.json>
```

Folder mode accepts repeated, reviewed settled folders and writes the same
narrow staged source inside the candidate work area:

```powershell
python -m weather.operations.nightly_retrain run `
  --release-candidate-mode production `
  --point-in-time-folder <snapshots-root>/<settled-event-1> `
  --point-in-time-folder <snapshots-root>/<settled-event-2>
```

Production ordering is fail-closed:

1. Enumerate the manifest-pinned captured tape and replay rows directly, attach
   only the pinned settlement label, and freeze that candidate-independent
   source/replay inventory plus the contiguous 14-day evaluation window before
   any model is loaded or candidate-dependent selection occurs. The source's
   latest target date must be no more than seven days old.
2. Fit family calibration/trust and pooled feature/model artifacts with every
   locked date excluded. Feature priors, source-reliability priors,
   calibration/trust selection, and pooled fitting are confined to the exact
   immutable preselection universe and cannot see the window.
3. Refresh routing/promotion selection from only the manifest-pinned unlocked
   folders and persist a self-hashed `used_for_selection: false` lock binding.
4. Replay the exact serialized pooled candidate over the pinned population,
   attach settlement evidence only after prediction, and write the four
   qualification roles.
5. Reverify the complete model/calibration/routing/route hash graph while
   freezing the immutable candidate release. The release stays inactive.

When partition normalization and contextual current blending are enabled,
serving and replay restore categorical probability mass after the row-specific
blend. Candidate shadow rows may carry `candidate_preblend_probability`, the
normalized candidate value captured immediately before that blend. Validation
of a mass-restored replay requires that exact value on every scoreable row plus
artifact and postprocess hashes matching the base replay report; reconstruction
is reserved for explicitly legacy reports that predate mass restoration.

Each outer and inner training scope carries chained, self-hashed receipts for
`feature_selection`, `scaling_imputation`, `model`, `calibration`,
`postprocessing`, and `regime_router`. A separate final-refit receipt binds the
serialized serving bundle. Candidate and immutable-release verification reject
missing receipts, changed stage payloads, reused locked dates, or mismatched
artifact and route identities.

The currently served calibration temperature and learned-postprocessing
switches are identity-disabled, and the regime router has one predeclared
pooled route. Their receipts execute and hash those exact canonical transforms
over each fold; they do not claim nonexistent learned parameters. Any future
learned calibration, postprocessor, or route must be selected from training-
only/inner-OOF data and bound into the final serving receipt before promotion.

Candidate-local qualification outputs are:

- `qualification/point_in_time/corpus.parquet`
- `qualification/point_in_time/materialization_manifest.json`
- `qualification/point_in_time/validation_plan.json`
- `qualification/point_in_time/streaming_evaluation.json`

Immutable candidate construction copies those exact roles to
`contract/point_in_time/` and binds their hashes in the semantic serving
contract. Production defaults cap the source/replay population at 60 market
days and 250,000 rows per market-day, read Parquet in 65,536-row batches, and
retain one raw market-day at a time. Preselection additionally caps each tape
at 128 MiB with 1 MiB CSV fields and each captured replay file at 64 MiB with
8 MiB lines. Optional feature CSVs use the tape bounds; settlement JSON is
capped at 1 MiB, replay/source manifests at 16/4 MiB, and source Parquet at
1 GiB. It rejects reconstructed/unsettled inputs, root escapes, source mutation,
row-inventory drift, and zero or multiple winners per snapshot. Exclusive
output locks reject concurrent writers; publication is per-file atomic and
manifest-last, and consumers require the complete hash-bound pair.
Qualification declares a
4 GiB private-memory budget, permits at most 128 fold scopes, and advances
folds in seven-date steps. The non-incremental HGB trainer retains its
normalized training population, so its separate source contract caps that
population at 60 × 1,000 rows and records the observed row count; it does not
claim that fitted feature rows are streamed away. These are bounded
qualification declarations, not permission to raise the host load limits.

Production mode remains candidate-only. It does not promote, replace the
active pointer, restart workers, or grant trading permission.

### First inactive production release

Captured-input parity is ordinarily checked before candidate work and must bind
the currently active release. On a new release store, that ordering cannot be
satisfied because no immutable release identity exists yet. Do not use the
generic `--skip-captured-input-replay-parity` switch to hide that condition.

The one fail-closed bootstrap is explicit:

```powershell
python -m weather.operations.nightly_retrain run `
  --release-candidate-mode production `
  --bootstrap-first-inactive-release `
  --point-in-time-source-corpus <production-preselection-source-v1.parquet> `
  --point-in-time-source-manifest <production-preselection-source-v1-manifest.json> `
  --point-in-time-source-replay-manifest <promotion-corpus.json>
```

The contract passes only when all of these conditions hold:

- `artifacts/releases/current_release.json` is absent and the releases root is
  absent or completely empty. Existing releases, files, symlinks, locks, or an
  injected serving identity block before candidate preparation.
- Candidate mode is `production`, immutable release construction is enabled,
  and no release parent is supplied.
- Neither the generic parity-skip flag nor served/replay parity inputs are
  supplied. If parity evidence exists, verify it through the ordinary path.
- Every ordinary offline training, leakage, point-in-time, promotion-refresh,
  clean-source, and semantic-contract gate still passes.

The preflight writes a self-hashed contract into
`nightly_retrain_status.json`. The immutable manifest binds the contract hash
in `lineage.first_inactive_release_bootstrap`. After copying, the nightly job
independently verifies every release file and manifest hash, the exact
production semantic contract, null parent and rollback target, and the release
store's one-directory inventory. It then checks again at whole-run finalization
that the active pointer is still absent.

Success creates only `IMMUTABLE_CANDIDATE` state. Its reported activation is
`NONE`; promotion, serving, and live fallback are explicitly unauthorized and
remain blocked pending exact release-bound captured-input parity, forward
shadow qualification, and a separate reviewed promotion decision. The
bootstrap flag itself does not configure shadow capture, start or restart a
worker, or authorize the separate serving-identity exception below.

## Smoke Test

Before or after registration, use the non-activating dry-run and read-only
status paths:

```powershell
python -m weather.operations.nightly_retrain run --dry-run
python -m weather.operations.nightly_retrain status
```

When daily learning is currently blocked and you want to verify the
short-circuit path without training, run:

```powershell
python -m weather.operations.nightly_retrain run --step-timeout-seconds 300
python -m weather.operations.nightly_retrain status
```

Manual and dry-run commands intentionally cannot claim scheduled provenance;
use their outputs for smoke diagnostics, not scheduled-run acceptance.

Expected outputs:

- `data/backtest/nightly_retrain_status.json`
- `data/backtest/nightly_retrain_report.md`
- `data/backtest/nightly_retrain_sla_status.json`
- `data/backtest/nightly_retrain_sla_status_report.md`
- `artifacts/candidates/nightly-<UTC timestamp>/...` for mutable training outputs
- `artifacts/releases/nightly-<UTC timestamp>/release_manifest.json` only when
  every existing validation gate passes and the source tree is clean

The active pointer remains `artifacts/releases/current_release.json`. Nightly
retraining does not create or modify it. Promotion remains a separate reviewed
operation through `python -m weather.operations.release_lifecycle promote`,
which requires both a matching promotion-decision proof and a fresh
market-day-boundary proof.

## Reviewed All-Shadow Research Bootstrap

Use this bounded workstation entry point when the repository has no active
pointer and the immediate objective is an inspectable immutable identity
release, not production qualification:

```powershell
python -m weather.operations.all_shadow_release_bootstrap `
  --candidate-id <reviewed-release-id> `
  --run-root <dedicated-run-root-outside-data>
```

If the tracked research bundle predates the required corpus-lineage contract,
add `--model-source-release <verified-immutable-release-directory>`. The builder
reverifies that release without adopting its runtime identity, copies its
hash-bound `pooled_band_model` role, and imports the corpus lineage from the
same release's model-bound `training_evaluation_corpus` role. The new release
still freezes the current tracked family-secondary manifest, artifact registry,
runtime market set, and base graph.

The builder requires a clean code identity and the exact runtime fleet
(Toronto in C plus eleven F markets). It copies the tracked pooled F bundle,
family-secondary manifest, and artifact registry; freezes every market as
explicit `shadow`; freezes all seven base-model components for every market;
creates a `research_only` immutable release; and reverifies its hashes,
runtime, route, and semantic contract. Its self-hashed
`all_shadow_release_bootstrap_receipt_v1` remains under the declared run root.
It refuses an existing candidate/release identity and proves
`current_release.json` stayed absent. It never promotes, writes a pointer, or
changes serving state.

## Separate Serving-Identity Bootstrap

This manual research-serving exception is not part of the first inactive
production-release workflow above and does not satisfy production
qualification. Prefer the inactive production bootstrap when the objective is
a production release.

Ordinary `research_only` releases still fail closed at promotion and serving.
There is one explicit exception for establishing the first verified serving
identity on a repository that has no active pointer:

```powershell
python -m weather.operations.release_lifecycle promote <release-id> `
  --decision <reviewed-promotion-decision.json> `
  --market-day-boundary <fresh-boundary-proof.json> `
  --bootstrap-first-release
```

This exception applies only when all of the following are true:

- `artifacts/releases/current_release.json` does not exist, the candidate's
  `rollback_target` is null, and the research-only immutable release passes its
  complete integrity, runtime, clean-code, and exact-commit checks.
- The ordinary promotion decision passes and declares
  `"release_kind": "serving_identity_bootstrap"` in addition to the exact
  release/manifest identity, `decision=PROMOTE`, `gate_status=PASS`, review,
  and candidate-only-build proof.
- The market-day-boundary proof is fresh and binds the same release and
  manifest.

Without `--bootstrap-first-release`, the research-only promotion is rejected.
Once an active pointer exists, the flag cannot authorize a replacement
research-only release. A successful bootstrap writes pointer sequence 1 with
`release_kind=serving_identity_bootstrap` and self-hashed origin provenance for
the reviewed decision, market-day boundary, reviewer, action, and sequence.
Serving accepts the research-only manifest only while that exact provenance is
valid.

Bootstrap is a serving-identity state, not a production qualification or a
trading permission. It may support release-bound research, shadow, and paper
evidence, but `production_capable` remains false: capital-canary readiness and
`live-pilot` are blocked even if their other inputs pass. A later reviewed
production promotion records the bootstrap kind and origin proof with the
previous-release identity. Reviewed rollback carries that proof back to the
active pointer, preserving the release's non-capital semantics.

Every promotion returns `restart_required=true`; coordinate all release-bound
workers onto the new pointer before treating runtime identity as adopted. The
serving loader is loop-loaded, so deploying changes to this bootstrap contract
also consumes the repository's normal fleet-roll/restart budget. Do not combine
that rollout with an unreviewed promotion or use the bootstrap path to bypass
the existing release, readiness, or live-order gates.

## Reviewed Rollback

Rollback is also separate from nightly retraining. At a reviewed market-day
boundary, one command returns the pointer to its recorded prior release:

```powershell
python -m weather.operations.release_lifecycle rollback --market-day-boundary <reviewed-boundary-proof.json>
```

The command fully hash-verifies the rollback target and atomically writes a
self-hashed reconciliation intent before the atomic pointer replacement. It
then re-reads both the pointer and immutable release, emits the post-rollback
identity proof, and atomically finalizes the drill record at
`data/backtest/release_rollback_drill.json`. If finalization is interrupted,
the same command recognizes the exact pointer-bound intent and retries only
the proof/record finalization; it never toggles back to the failed release.
`--drill-record` may select an isolated output for a synthetic drill but cannot
point inside the immutable release tree.

The first active release has an explicit `NO_ACTIVE_POINTER` rollback target.
It is eligible only when the active pointer is the verified sequence-1
`PROMOTE` transition and the immutable manifest has null `parent_release` and
`rollback_target`. For that transition the market-day-boundary proof binds the
active source release being deactivated. The command writes a self-hashed,
source-pointer-bound intent before removing `current_release.json`, then calls
the canonical serving resolver and requires the absent pointer to resolve as
`RESEARCH_UNBOUND` / `research_unbound_non_countable`. The finalized drill
keeps the source release identity for evidence scope, records a null restored
release and absent pointer, and embeds the post-deactivation serving proof.
Interrupted finalization is recoverable from the same intent while the pointer
remains absent; it never recreates or toggles the release.

Loop control remains an explicit operator step. The initial record truthfully
uses `status=PENDING_MANUAL_RESTART` and names the target runtimes under
`manual_coordinated_restart.required_runtimes`. A real drill becomes complete
only after those workers are coordinated onto the restored release, their
runtime-identity proof is attached, post-restart health passes, and the manual
restart, health, and overall statuses are all recorded as `PASS`.

## Inactive-release forward shadow

Forward shadow is a read-only comparison, not activation. It loads one
immutable release with no pointer authority, rejects that release if it is
currently active, and replays the exact captured source payload used by each
recorded production snapshot in a declared half-open UTC window:

```powershell
python -m weather.reporting.scorecards.inactive_release_forward_shadow `
  --release-dir <artifacts/releases/release-id> `
  --manifest-sha256 <expected-manifest-sha256> `
  --market-id <market-id> `
  --target-date <yyyy-mm-dd> `
  --captured-inputs <market-day/replay_inputs.jsonl> `
  --snapshot-tape <market-day/snapshots.jsonl> `
  --window-start <iso-8601-utc> `
  --window-end <iso-8601-utc> `
  --output-root <declared-output-root>
```

The inactive loader verifies the complete production-capable artifact graph,
route, registry, base model, and manifest while keeping
`active_pointer_authority_used=false`. The command verifies every captured
input self-hash and both source-tape hashes before and after replay. An invalid
or legacy input identity blocks strict evidence; do not repair it in place or
waive the check. `--integrity-only` skips current checkout/runtime identity
matching for an archived-release diagnostic. Its output is not release
qualification or promotion evidence.

For each instant, the JSON artifact binds the captured-input, recorded
production/runtime, inactive release/manifest/candidate, model artifact, and
postprocessor identities. It compares the recorded
`snapshots.jsonl.bands[].model_probability` partition against the inactive
incumbent projection and the candidate raw, postprocessed, preblend,
current-blend, and final stages. The summary reports exact and tolerance
whole-partition counts plus the first pipeline divergence. `status=PASS` means
the instrument completed; `comparison_status=MATCH` or `DIVERGED` states the
parity result. Neither result authorizes activation, promotion, or trading.

Training output paths are candidate-only by default. An old serving path fails
before training begins. `--allow-legacy-serving-output` is a temporary migration
flag: it marks the run quarantined, blocks immutable release construction, and
cannot permit writes into `artifacts/releases` or the active pointer.

If daily learning is blocked, the nightly report should show status `blocked`,
only the `daily_learning` step should have run, and the Daily-Learning Blockers
table should list the exact P0 gates and actions.

## Missed-Run SLA

The SLA check expects a fresh `nightly_retrain_status.json` after the configured
scheduled window plus its grace period. If no fresh status exists,
`weather.operations.nightly_retrain status` returns a critical state and names
the expected task and status file. When the dedicated-host training window is
authoritative, interpret freshness together with its skip/preflight result and
restore status.

The Operations dashboard shows the same state in the Nightly Self-Improvement
table: task registration, next run, status freshness, daily-learning blocker
count, and the first P0 gate.

## Update this file when

Update when nightly mode defaults, point-in-time inputs or step ordering,
candidate/release output contracts, registration parameters, scheduling
topology, or SLA semantics change.
