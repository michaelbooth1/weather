# Data Retention Policy

- **Owns:** pruning rules for local `data/`, the two scheduled CLOB tiering
  tasks, the capture long-CSV switch, and the manual replay-cache and
  closed-day projection tiering tools.
- **Read when:** you are about to delete, compress, tier or move anything under
  `data/`, or you are judging production disk headroom.
- **Do not use for:** archive upload/restore (see
  [cold-archive-locations.md](cold-archive-locations.md)), current disk numbers
  or what is armed tonight ([STATE_OF_PLAY.md](STATE_OF_PLAY.md)), or config
  classification ([config-inventory.md](config-inventory.md)).
- **Verify with:** `data\logs\clob_tiering_task_status.json` and
  `data\backtest\clob_order_book_tiering.json` (last tiering outcome);
  `Get-Volume -DriveLetter C` (free space now); `config\storage_pressure.json`
  on `master` (live capture switch).

Status of related machinery: **owner, 2026-09-23: no second disk; off-PC storage (the private Drive cold
archive) is used as needed** under the verify-before-reclaim gates — see
[the 2026-09-23 storage plan](storage-plan-2026-09-23.md). The workstation data mirror is **paused** since 2026-08-12
([record](mirror-paused-2026-08-12.md)), the taker is **paused**, and backups are deprioritized by the owner.

Use the data-retention inventory before pruning local `data/` files. The
report is read-only and exists to classify ownership, TTL policy, cleanup
requirements, and disk-growth pressure.

## Judging disk headroom: free space is a daily sawtooth

Free space on the production host is not a level, it is a sawtooth. Capture
appends an uncompressed `order_books_long.csv` for every open event day all day
long, and that space is only returned when the 05:00 `WeatherClobTiering`
projection job compresses the days that have since closed. The daily low is
therefore just before that job, around 04:50 local, and the 2026-09-18 audit
measured it roughly 10-13 GiB below the same day's evening reading
(`docs/roadmap/audits/full-audit-2026-09-18/`; re-measure rather than reuse the figure).

- Judge headroom, floors and "days until full" at the **daily low**, never from
  an evening or post-tiering reading.
- A heavy job admitted against an evening reading can breach its disk floor
  before 05:00 without any new fault.
- A missed or refused 05:00 run does not return the space, so the next low is
  lower again. Check `data\logs\clob_tiering_task_status.json` before trusting
  any trend.

## Daily Report

The independent [passive maker collector](passive-maker-evidence-capture.md)
streams gzip on UTC hour close, verifies the decompressed hash and retains the
logical journals permanently. Its daily raw-update cap limits new collection,
not retention. It does not delete closed evidence by age or alter the existing
capture tapes; later off-PC archive/reclaim follows the canonical-evidence gate.

Run directly:

```powershell
python -m weather.reporting.data_quality.data_retention_inventory --root data --out data\backtest\data_retention_inventory.json --report data\backtest\data_retention_inventory_report.md
```

The normal daily refresh also writes the same artifacts:

- `data/backtest/data_retention_inventory.json`
- `data/backtest/data_retention_inventory_report.md`

## Pruning Rules

Owner-approved storage decision 7 (2026-09-26) adds these family rules:

| Family | Retention and gate |
| --- | --- |
| Rotated `snapshots/clob_diagnostics.*.jsonl` and `diagnostics.*.jsonl` (including gzip) | Operator logs; verified archive and exact-path review before local reclaim. Keep active logs and incident-linked records. |
| `fetch_fanout/` receipts, including beneath `forecast_payload_cas/` | Claims strictly older than 7 days may expire only with no active owner or evidence reference; retain other receipts in verified monthly tar.gz archives. This never permits deleting CAS blobs. |
| `wunderground/` atomic `final.<pid>.<time_ns>.tmp` orphans | Exclude from canonical protection only when the exact PID is absent or its process start is later than file mtime, age is strictly over 24 hours, an exclusive handle check proves no open handle, and the final file exists. Unknown observations retain protection. Recheck all four immediately before exact-path cleanup; the pure registry accepts a bound `WuAtomicOrphanProof`, not a filename-based exemption. |
| `forecast_history/` | Canonical point-in-time evidence; permanent archive. |
| `maker_evidence/` journals and manifests (88a) | Canonical; keep forever, including compressed representations. Status and operator configuration remain caches. |
| `observation_triggers` rotations | Protected panel B source until the through-October-8 panel is scored; no diagnostic-log exemption. |

The owner's 2026-09-26 replay-cache waiver applies only to
`data/backtest/replay_cache`: an owner-signed manifest naming exact files,
current checksums and reason may authorize deletion without a release
reachability manifest (production has no release pointer). Retain the signed
manifest and apply receipt. This is a separate reviewed cleanup campaign;
`replay_cache_retention` still fails closed without its normal reachability
inputs. The waiver does not cover `backtest/cache/replay`, source tapes,
settlements, artifacts, or releases.

- Classify files with the
  [Data Storage Class Contract](data-storage-class-contract.md) before cleanup:
  `canonical_evidence`, `analysis_projection`, and `operator_cache` have
  different review, rebuild-source, and deletion gates.
- Do not delete `snapshots`, `mm_runs`, `taker_runs`, or canonical historical
  source rows unless a reviewed cleanup manifest names the exact files. The one
  taker exception is the reviewed counterfactual replay-detail policy: daily
  roll writes an exact-path, SHA-256 and byte-bound plan before removing only
  `counterfactual_orders_long.csv` and
  `settled_counterfactual_orders_long.csv` after their declared retention.
  Settlement-summary presence is deliberately not a prerequisite.
  **Note:** the taker is PAUSED since 2026-08-07, so that roll does not run and
  those files are currently retained.
  **Executed exception:** the 2026-08-07 taker prune deleted 19.2 GB without the
  manifest workflow, under direct operator authorisation — see
  [taker-paused-and-pruned-2026-08-07.md](taker-paused-and-pruned-2026-08-07.md)
  for what replaced it and what was deliberately kept.
- Run `python -m weather.operations.cleanup_preflight --manifest <cleanup.json>`
  before any cleanup workflow that could delete local data. A canonical
  evidence candidate requires operator review, exact paths, and current
  checksums.
- Closed market-day Parquet partitions live under
  `data/archive/closed_market_days/v0.1` and are analysis copies, not raw
  evidence replacements. Follow
  [Closed Market-Day Parquet Archive Contract](closed-market-day-parquet-archive-contract.md)
  for eligibility, manifest validation, reader fallback, and raw-evidence
  boundaries.
- Use `python -m weather.reporting.data_quality.backtest_artifact_retention` for large
  rebuildable `data/backtest` row exports; delete only from its cleanup
  manifest when paired reports or manifests exist.
- Prefer gzip tiering or externalization for large historical JSONL/CSV
  evidence before deleting local copies.
- Explicitly approved cold replay-cache files may use the separate
  [bounded NTFS compression lane](replay-cache-compression.md). It preserves
  paths and bytes, has its own narrow disk reservation and retains all ordinary
  capture-window, memory and lease gates. It grants no cache eviction authority.

Routine provider caches may be pruned after TTL expiry when no replay,
promotion, or incident report references them. Forecast archives used for
settled replay evidence are not routine cache.

## Scheduled CLOB Long-Tape Tiering

`WeatherClobTiering` runs the canonical
`scripts/ops/clob_tiering_run.ps1` daily at 05:00 local with a 1,800-second
runner bound and PT31M task limit. `WeatherClobRawTapeTiering` runs
`scripts/ops/clob_raw_tape_tiering_run.ps1` at 06:00 with a 2,400-second bound,
PT41M task limit, and `-Limit 150`. Both are S4U/Limited, use kill-on-close
child-tree containment in the runner, and deliberately disable
`StartWhenAvailable`: a missed occurrence must not drift into Stage A or a
protected host window. Projection tiering is the load-bearing defence against
the single largest retention leak in this project. It compresses the
`order_books_long.csv` of every event day whose date is before the host's local
date and whose source has been quiet for `MIN_QUIET_SECONDS`
(`src/weather/operations/clob_order_book_tiering.py`, `default_settled_before`)
to `.csv.gz`, and deletes the source only after byte-parity verification.
"Settled" in its reports means that date test, not a settlement label.

**It exists because the identical work as a daily-refresh chain step is not
reliable.** `clob_order_book_tiering` sits well down `STEP_REGISTRY`
(`src/weather/operations/daily_refresh_registry.py`); when the chain defers
earlier, the step never runs and uncompressed tapes accumulate across every
market (read the current daily growth from the retention inventory report, not
from this file). That has happened twice for unrelated reasons — memory
admission on 2026-07-18, and a single transient capture error
(`capture_loop_not_fresh`, `consecutive_errors: 1`) deferring step 7 on
2026-08-04. Both times free space fell far enough to threaten capture. Disk
headroom must not be a downstream consequence of chain health.

Registration is owned by `scripts/ops/register_clob_tiering.ps1` and
`scripts/ops/register_clob_raw_tape_tiering.ps1`. Each registrar reads back the
exact canonical action, trigger, runtime limit, no-catch-up setting, and
principal before claiming success. Task-level outcomes, including bytes
reclaimed, are written to `data/logs/clob_tiering_task_status.json` and
`data/logs/clob_raw_tape_tiering_task_status.json`; the projection-tiering
report itself stays at the shared
`data/backtest/clob_order_book_tiering.json` path that the chain step also
writes, so one file always answers "when did tiering last succeed."

Running the job twice is harmless. An already-tiered day is classified
`already_tiered` and skipped, so the chain step and the scheduled task cannot
conflict — whichever runs first leaves nothing for the other.

**Split market-days are structurally excluded, not merely avoided.** A day that
already holds an `order_books_long.csv.gz` can never become a candidate, and
`apply` re-checks `gzip_path.exists()` before compressing. The disjoint-halves
hazard described under *Storage-Pressure Build* below therefore cannot be
triggered by this job. Those days appear in the plan as
`already_tiered_source_present` and are left alone; reclaiming them needs the
separate verified-delete path.

The runner refuses to start outside the 00:30-09:00 heavy-work window;
`-Forced` cannot bypass that host policy. It runs its child process at
`BelowNormal` priority so sustained
compression cannot starve the capture loops.

## Storage-Pressure Build

The workstation storage-pressure tools are manual and dry-run first. They are
not scheduled and a code merge performs no cleanup.

The [Verified Cold-Archive Foundation](verified-cold-archive.md) adds a separate
fixture-only path for preserving an entire sealed market-day as one
deterministic create-only object. It reuses the event-day manifest,
storage-class classification, and cleanup-manifest helper; requires a minimum
30-day hot window plus explicit settled/closed/barrier/queue/window evidence;
and gates cleanup-plan generation on exact archive verification and a successful
restore receipt. It contains no production transport or delete executor and
does not change any retention period or current reader.

The same contract now owns a separate provisional workstation staging adapter
for one already-rotated mirror file. It deterministically compresses at most
1 GiB, proves that an encrypted rclone config wraps the exact explicit local
ciphertext root, copies with immutable/create-only flags, cryptchecks the
result, and writes self-hashed terminal evidence. The adapter is admitted only
as the literal `weather.operations.workstation_cold_archive_stage` module under
the workstation-heavy wrapper. Every receipt remains
production-identity-unproved and deletion-ineligible; no real source, key,
cloud target, restore, or cleanup is part of the build-and-test evidence.

### Capture long-CSV switch

`config/storage_pressure.json` owns the capture switch
`capture.write_order_books_long_csv`. It is loaded by
`load_storage_pressure_policy` (`src/weather/market/storage_pressure_policy.py`;
the boolean check is at `:78-85`, the code default `True` at `:17`). The
loader has no cache and runs each time a `MarketMicrostructureStore` is built
(`src/weather/market/market_microstructure_capture.py:761-766`), which
`capture_event_books` does on every call (`:1079`). A changed value therefore
applies from the next capture iteration, without a process restart, but only
in the checkout whose `config/` the running capture process resolves through
`weather.paths.config_path`; a merge to another worktree changes nothing.
`write_books`
(`:835-838`) then skips only the `order_books_long.csv` append: the summary CSV
and canonical `order_books.jsonl` capture continue, and existing long tables
are untouched. Missing, malformed, wrong-schema, duplicate-key, or non-boolean
policy fails safe to writing the projection.

On this branch the checked-in value is `true`. An owner decision dated
2026-09-19 sets it to `false` on a separate branch; this file does not claim
that change is live. Read `config/storage_pressure.json` on `master` for the
live value and `order_books_long_csv_enabled` in the capture status rows for
what the running process actually loaded. With the switch off the sawtooth
above flattens for new days, and any reader that needs depth must go through
`weather.market.order_book_tape` (canonical JSONL first).

Plan replay-cache retention from explicitly named reachability roots:

```powershell
python -m weather.operations.replay_cache_retention --cache-root <replay-cache-root> --corpus <pinned-promotion-corpus.json> --registry config\model_variant_registry.json --active-release-pointer <artifacts\releases\current_release.json> --releases-root <artifacts\releases> --output-root <review-output-outside-data> --protected-root <production-data-root> --protected-root <mirror-data-root>
```

The planner uses full cache keys and exact corpus/artifact/config identities.
It never selects by age, modification time, or LRU. Missing or changing roots,
unreadable subtrees, malformed entries, path/key mismatches, links, or any
other ambiguity retain every provisional candidate. The recommended quota is
10 GiB: it is deliberately far above the expected healthy cache working set
and therefore detects runaway identity/config accumulation. It is a diagnostic
ceiling, not an eviction policy; reachable entries are never selected even
when reachable bytes exceed the quota. Rebuildable candidates must use a
verified `production_static_context`; legacy artifacts that could consult
mutable climate, source-reliability, reanalysis, or marine sidecars are
retained. The plan also pins the genuine active pointer's exact identity plus
the complete retained release manifest and declared artifact inventory. Apply
resolves that same pointer through the strict
release-root-contained serving path. The resolved `release_id`,
`manifest_sha256`, and `release_dir` must match the approved plan; any active
release drift aborts cleanup and requires a new plan.

Apply also performs the real
`_compute_pooled_candidate_day` cache-off computation for every exact
corpus/artifact binding, compares the full six-field key plus `rows`,
`replay_results`, `coverage`, and `diagnostics`, writes a durable
`PRE_UNLINK` record, then repeats the computation and source/candidate
verification immediately before the exact-file unlink. A mismatch or compute
failure retains the candidate.

After reviewing every candidate, edit only the manifest's
`operator_review.approved`, `approved_by`, `approved_at_utc`, and `note`
fields. Then bind apply to the edited file and repeat every planning root:

```powershell
$manifestHash = (Get-FileHash -Algorithm SHA256 <review-output-outside-data>\replay_cache_retention_manifest.json).Hash.ToLowerInvariant()
python -m weather.operations.replay_cache_retention --apply --manifest <review-output-outside-data>\replay_cache_retention_manifest.json --expected-manifest-sha256 $manifestHash --cache-root <replay-cache-root> --corpus <pinned-promotion-corpus.json> --registry config\model_variant_registry.json --active-release-pointer <artifacts\releases\current_release.json> --releases-root <artifacts\releases> --output-root <review-output-outside-data> --protected-root <production-data-root> --protected-root <mirror-data-root>
```

The standalone two-file fixture comparison does not prove an actual rebuild,
but can be run without unrelated plan inputs:

```powershell
python -m weather.operations.replay_cache_retention --rebuild-one-cache-entry <cache-entry.json> --rebuild-one-payload <rebuilt-payload.json> --output-root <proof-output-outside-data> --protected-root <production-data-root> --protected-root <mirror-data-root>
```

Plan closed-day projection tiering separately:

```powershell
python -m weather.operations.closed_day_projection_tiering plan --snapshots-root <data\snapshots> --as-of-date <YYYY-MM-DD> --output-root <review-output-outside-data> --protected-root <production-data-root> --protected-root <mirror-data-root>
python -m weather.operations.closed_day_projection_tiering rebuild-one --folder <closed-event-folder> --output-root <proof-output-outside-data> --protected-root <production-data-root> --protected-root <mirror-data-root>
```

The projection registry names every closed-day archive family, its canonical
rebuild source, accepted reader representations, and its current blocker.
Only `order_books_long` is eligible. It requires finalized closed-day evidence,
a current event-day manifest, no writer lock, at least
`MIN_QUIET_SECONDS` of source-write quiescence, canonical `order_books.jsonl`,
and an exact byte-parity rebuild proof. Apply retains
`order_books_long.csv.gz` and removes only the verified same-folder
`order_books_long.csv`; it never treats the raw JSONL as disposable.

### Remove a proved gzip twin (owner decision 6, 2026-09-26)

`plan-twins` selects only days strictly older than 14 days with same-folder
`order_books.jsonl.gz` and `order_books_long.csv.gz`. Any raw or long-table
split, missing raw gzip, writer lock, non-quiescent file or invalid/currently
stale event-day manifest retains the projection. The raw gzip is canonical;
full-book readers use `weather.market.order_book_tape`, which already prefers
canonical JSONL/gzip to CSV. No source reconstruction is attempted for a
folder lacking raw JSONL. Backfill event manifests with the owning
`weather.operations.event_day_manifest` command before planning if absent;
never stamp PASS manually.

Production runs all three phases through the manual admitted wrapper below.
It holds the ordinary shared workload lease, checks memory and 50 GiB free,
and kills the full child tree by its runtime bound or 09:00. It registers no
task. Outputs must be outside `data/` and any mirror, in separate new review
directories. Example from the production repository root:

```powershell
.\scripts\ops\closed_day_projection_twins_run.ps1 -Command plan-twins -OutputRoot scratch/twin-review/selection -MaxBytes 1073741824
.\scripts\ops\closed_day_projection_twins_run.ps1 -Command prove-twins -ApprovedManifest scratch/twin-review/selection/closed_day_projection_tiering_plan.json -OutputRoot scratch/twin-review/proof
# Owner reviews the proved plan and completes its operator_review fields,
# binding approved_plan_hash to the new plan_hash, before this final phase.
.\scripts\ops\closed_day_projection_twins_run.ps1 -Command apply -ApprovedManifest scratch/twin-review/proof/closed_day_projection_twins_proved.json -OutputRoot scratch/twin-review/apply
```

The proof reconstructs the original CSV byte stream (column order, CRLF,
JSONL record order and original bid/ask level order) and compares its SHA-256
and length against the decompressed twin. Apply repeats the proof under the
raw writer lock, writes an UNLINK_PENDING receipt, then repeats identities and
parity immediately before exact-file unlink. It refreshes and validates the
event-day manifest afterwards. A refresh failure remains BLOCK with the
receipt recording that unlink already happened; it is never a clean PASS.

The plan's `--max-bytes` defaults to 1 GiB of compressed twins. A fixed
`data/logs/projection-twin-budget-<local-date>.json` reserves that amount
before mutation across every plan that night; the first limit cannot be
raised by a later plan. Failed attempts consume reservations, and the same
plan cannot be reapplied. Preserve the ledger and receipts. This is a bounded
manual campaign, not permission to schedule unreviewed cleanup.

### Running the tiering plan: preconditions and known traps

Verified by the 2026-08-02 dry run. Read this before spending time on a run that
cannot succeed.

**`--protected-root` stats every path you pass, so a UNC mirror root fails
without the share credential.** The command above lists both the production data
root and the mirror root. On the production host an ordinary session is not
authenticated to `\\<workstation>\weather-mirror`, and the guard's reparse-point
check calls `Path.exists()` on it, so the run dies with
`OSError: [WinError 1326] The user name or password is incorrect` before writing
anything. The guard exists to stop *output* landing inside a protected tree, so
when the output root is on a local volume and the mirror is a UNC path on
another host they cannot overlap. Pass the production data root alone in that
case and record the omission in the run notes. Never read or supply the stored
mirror credential to satisfy this check.

**Every closed-day action requires a finalized-PASS `event_day_manifest.json` in
the event folder.** This is the gate that decides the whole run, and it is
checked per folder. In the 2026-08-02 dry run almost no folder had a manifest
and none was finalized-PASS, so the planner emitted zero actions regardless of family
eligibility; do not assume that has changed without running `plan`. If a plan returns
`Eligible actions | 0`, check the blocker histogram before assuming a tooling
problem; `event_day_manifest_missing_or_invalid_json` dominating means the
manifest pipeline is the thing to fix, not the tiering tool. See
[item 325](../roadmap/items/item-325-tiered-data-retention-and-verified-archive-offload.md).

**Exit code 2 means `NOT_DONE`, which is the normal result of a dry run with no
eligible actions.** It is not a crash. The JSON and Markdown are still written.

**Benign blockers you should expect to see and ignore:**

- `order_books_long_csv_missing` — the day is already tiered.
- `event_day_is_not_closed_before_as_of_date` and `order_books_long_recently_written`
  — the current day, correctly refused.
- `event_slug_has_no_target_date` — a non-event directory under
  `data/snapshots` (for example `observation_source_cache`) reported as a blocked
  folder rather than skipped as out-of-scope.

**Split market-days must be excluded, not tiered.** Some days hold both a plain
`order_books_long.csv` and an `order_books_long.csv.gz` covering *disjoint*
halves of the day; a gz-first reader silently returns a partial day. The plain
half is not redundant and must not be deleted. Check for both files before
approving any action on a day, and exclude such days from any future automation.

After reviewing the tiering plan, edit only
`operator_review.approved`, `approved_by`, `approved_at_utc`, `note`, and
`approved_plan_hash`; the last value must exactly equal the unchanged top-level
`plan_hash`. Apply uses the exact approved-manifest file identity:

```powershell
python -m weather.operations.closed_day_projection_tiering apply --approved-manifest <review-output-outside-data>\closed_day_projection_tiering_plan.json --output-root <review-output-outside-data> --protected-root <production-data-root> --protected-root <mirror-data-root>
```

Current market-making runtime consumes `order_books_summary.csv`, which remains
untouched. Future full-depth corpus readers must use
`weather.market.order_book_tape`: canonical JSONL first, then gzip CSV, then
plain CSV. The long-table column contract has been unchanged since its
introduction, and gzip fallback is covered by fixture tests. Full-size
production replay remains an operator rehearsal and is not implied by unit tests.

For either tool, apply requires an externally reviewed exact manifest,
`cleanup_preflight`, immediate identity/byte/SHA/key re-verification, and
durable per-action JSON and Markdown receipts. The tools stop on the first
failure and never remove directories. Every production data or mirror boundary
must be supplied with a repeated `--protected-root`; output is rejected if it
overlaps any one of them, while the source data root is independently derived
and protected as well. Do not use these commands against production data until
the operator has reviewed the dry run and scheduled the quiet window.

## Shared Forecast Payload CAS

New explicitly market-invariant forecast responses use the shared immutable
CAS under `data/forecast_payload_cas/`; their per-market append-only manifests
retain capture and extraction lineage. Inventory a possible legacy migration
without copying, rewriting, or deleting evidence:

```powershell
python -m weather.operations.forecast_payload_cas_migration
python -m weather.operations.forecast_payload_cas_migration --month 2026-07 --max-payload-bytes-read 8589934592 --max-elapsed-seconds 300
```

The command is dry-run only. It verifies legacy hash/restore/replay checks and
the shared references found in snapshot `forecast_payloads.jsonl` files. The
inventory is bounded by directory and tree-entry counts, manifest count and
bytes, JSONL line size, manifest rows, per-payload and aggregate payload bytes,
elapsed time, retained candidate detail, and physical-blob count; any reached
bound is explicit in the artifact. Use `--month YYYY-MM` for a bounded monthly
segment. The report counts a repeatedly referenced legacy file once by physical
file identity, includes verified legacy bytes, projected one-copy bytes, and
projected reclaimable bytes by month, and assigns a cross-month physical file to
its earliest observed month. Monthly one-copy projections are scenarios rather
than additive totals. Truncated results remain partial and must not be treated as
a complete reclaim total. That scan is explicitly
partial inventory, not global reachability: blobs absent from the scanned
references are non-authoritative observations, never deletion candidates. No
current cleanup review can authorize shared-CAS deletion.
The CLI returns `2` and prints `status=partial`, the stop reasons, and the
resume cursor when any bound or scan-integrity condition truncates inventory;
only a complete bounded scan returns zero.
Event-day manifests enumerate referenced shared blobs as external canonical
dependencies and remain blocked until both backup and restore evidence includes
their exact digests. Legacy market-local blobs remain canonical evidence.

## Update this file when

Update when a pruning rule, the tiering task names, times, bounds or runner
scripts, the capture long-CSV switch semantics, a retention tool's CLI, or the
cause of the daily free-space sawtooth changes. Current sizes, growth rates and
the live switch value belong to generated reports, `config/` and
`STATE_OF_PLAY.md`, not here.
