# Agent report — 2026-07-27 workstation storage-pressure build

## Outcome

The three storage-pressure mechanisms requested by
`workstation-handoff-2026-07-27h-storage-pressure-build.md` are built on
`codex/production-storage-pressure-2026-07-28` from exact
`origin/master` commit `c83b034ce98ca224f4d34b31c84100ba16005584`.

On 2026-07-28 the accepted build was merged forward to exact `origin/master`
`7c33f90cf9e4c55f348615606e981b5e8d02b4b9`, including the operator's
`2d4c2811` CLOB writer-quiescence fix. The release-binding rework restores
`release_artifacts.py` and `release_serving.py` exactly to master. Replay-cache
apply now resolves only the genuine active pointer through that strict path
and aborts if its release ID, manifest SHA-256, or release directory differs
from the approved plan. No temporary or external pointer is used.

This is a **build-only** handback. No repository command read, compressed,
rewrote, or deleted production `data/`; no mirror path was accessed. All
mutation tests used pytest temporary fixtures. The checked-in capture policy
still preserves current behavior.

## NOT DONE / NOT REHEARSED

- No production dry-run, manifest review, apply, compression, or deletion.
- No production cache-off rebuild or replay-cache deletion. Apply tests use a
  labeled stub for the expensive candidate scorer while exercising the
  complete destructive orchestration and failure boundaries. Separate
  synthetic tests load a real verified release graph and execute replay with
  an explicit bundle and corpus-pinned settlement, but this is not production
  model parity.
- No 85 GiB full-book corpus read.
- No change to `WeatherDataMirror`, `/MIR`, or any scheduler. The existing
  `clob_order_book_tiering` implementation changed only through the required
  merge of upstream `2d4c2811`; this branch does not alter that merged code.
- No capture restart, supervisor action, deployment, config activation,
  modelling, training, promotion, release, or live trading.
- No restore drill and no completion claim for roadmap Item 325's broader
  archive-offload design.
- No PR, merge, or push to `master`. Only the authorized topic branch is part
  of this handback.

The operator still owns the production dry-runs, approval fields, exact
manifest review, quiet-window apply, disk measurements, flag activation, and
rollback.

## Build identity and isolation

| Field | Value |
| --- | --- |
| Original build base | `origin/master` at `c83b034ce98ca224f4d34b31c84100ba16005584` |
| Rework merge base | `origin/master` at `7c33f90cf9e4c55f348615606e981b5e8d02b4b9`, including `2d4c2811` |
| Topic branch | `codex/production-storage-pressure-2026-07-28` |
| Build worktree | `scratch/worktrees/weather-production-storage-pressure-2026-07-28` |
| Production/runtime data | Not present in the isolated worktree and not accessed |
| Test mutation boundary | Synthetic pytest temporary folders only |
| Output protection | Repeated explicit `--protected-root` values; source data root is also independently protected |

## Mission 1 — default-preserving capture flag and full-book reader

`config/storage_pressure.json` now owns one activation control:

```json
{
  "schema_version": "storage_pressure_policy_v0.1",
  "capture": {
    "write_order_books_long_csv": true
  }
}
```

The checked-in value is `true`, so merge alone preserves today's
`order_books_long.csv` append behavior. Missing files, malformed JSON, duplicate
keys, non-finite constants, a wrong schema, a missing capture object, or a
non-boolean value all fail safe to `true`.

When the operator later sets the value to `false`, only future
`order_books_long.csv` appends are skipped. The same capture still writes:

- `order_books_summary.csv`;
- canonical `order_books.jsonl`;
- capture status and the rest of the existing CLOB outputs.

The store records the effective policy and the number of long rows written in
capture status. Existing historical long tables are never inspected or changed
by the flag.

`weather.market.order_book_tape` is the full-depth streaming boundary:

1. canonical `order_books.jsonl`;
2. `order_books_long.csv.gz`;
3. `order_books_long.csv`.

It rebuilds the exact `BOOK_LEVEL_COLUMNS` projection from raw JSONL with an
atomic output and refuses overwrite. Fixture proof covers byte-identical
rebuild, JSONL streaming, gzip fallback, header enforcement, and failed-build
cleanup.

## Consumer audit — `order_books_long`

The original 11 production references were audited individually. "Consumes"
below distinguishes actual row reads from presence/inventory checks.

| File | Classification | What it does | Safe when plain long CSV is absent? |
| --- | --- | --- | --- |
| `market/market_microstructure_capture.py` | Live capture path | Direct producer of summary CSV, long CSV, and raw JSONL. | Yes, only when the explicit policy is `false`; summary and raw writes continue. |
| `market/market_making_preflight.py` | Live-pilot gate | Presence-only any-of check across summary, raw JSONL, long CSV, and gzip long CSV. | Yes. Summary alone passes; gzip alone is also proven by test. |
| `operations/clob_order_book_tiering.py` | Existing scheduled/operator archive mutator | Inventories, compresses, and can remove the long CSV. It does not serve full-depth rows. | It already recognizes gzip. This build does not modify or schedule it. |
| `operations/closed_market_day_archive.py` | Archive reader/writer | Treats CSV and CSV.GZ as source patterns and uses pandas gzip inference. | Yes for its archive/read boundary. |
| `operations/closed_market_day_archive_manifest_contract.py` | Archive schema vocabulary | Names the `order_books_long` family. | Yes; no direct row read. |
| `operations/event_day_manifest.py` | Archive/inventory manifest | Inventories raw, summary, long, and gzip forms. | Yes; retained gzip and raw are represented. |
| `operations/market_making_tape_encoding.py` | Audit/repair utility | Audits gzip CSV with encoding diagnostics; refuses in-place repair of compressed input. | Yes for audit. |
| `operations/storage_classes.py` | Storage policy registry | Classifies long CSV/GZ as an analysis projection with raw JSONL rebuild source. | Yes; no direct row read. |
| `reporting/data_quality/clob_coverage_audit.py` | Audit | Presence/size inventory across summary, raw, long, and gzip. | Yes. |
| `reporting/data_quality/data_layer_audit_collectors.py` | Audit feeding live preflight | Exposes separate presence keys and an any-of raw-book family. | Yes; gzip and raw are recognized. |
| `reporting/source_gates/source_family_inventory.py` | Audit/source gate | Presence inventory for summary, raw, long, and gzip. | Yes; no full-depth row read. |

Relevant fixture coverage spans:

- `tests/market/test_market_microstructure.py`;
- `tests/market/test_storage_pressure_policy.py`;
- `tests/market/test_order_book_tape.py`;
- `tests/market/test_market_making_run.py`;
- `tests/market/test_market_making_csv_encoding.py`;
- `tests/operations/test_clob_order_book_tiering.py`;
- `tests/operations/test_closed_day_projection_tiering.py`;
- `tests/operations/test_closed_market_day_archive.py`;
- `tests/operations/test_event_day_manifest.py`;
- `tests/operations/test_storage_classes.py`;
- `tests/reporting/test_clob_coverage_audit.py`; and
- `tests/reporting/test_data_layer_audit.py`.

## MM representation answer

Current market-making execution and the current
`codex/workstation-mm-scaled-2026-07-28c` branch read
`order_books_summary.csv`, not the full-depth long projection. Repository and
branch searches found no current MM row reader of `order_books_long.csv`.
Summary capture is untouched.

For the future full-depth scaled-corpus slice, the intended representation is
canonical `order_books.jsonl` through `weather.market.order_book_tape`, with
transparent gzip and plain-CSV fallback. That future branch must explicitly
adopt this boundary before claiming an 85 GiB full-book run; the boundary exists
and is fixture-proven, but the full run is NOT REHEARSED here.

`BOOK_LEVEL_COLUMNS` remains unchanged from its original full-book introduction
at `f7265bd3`. Mission 3 therefore does not strand a present runtime reader.

## Mission 2 — reachability-only replay-cache retention

`weather.operations.replay_cache_retention` is manual and dry-run by default.
It requires explicit:

- cache root;
- one or more pinned promotion corpora;
- model-variant registry;
- active-release pointer and releases root;
- review output root; and
- every production data or mirror boundary through repeated
  `--protected-root`.

Output is rejected if it overlaps any protected root. One protected root must
contain the cache. Paths with lexical symlink/reparse components are rejected.

### Reachability and selection

Reachability uses the complete six-field cache key:

1. `event_slug`;
2. `consumer`;
3. `inputs_fp`;
4. `model_fp`;
5. `config_fp`; and
6. `schema_version`.

Active and shadow variant/corpus/config combinations are retained. An
unreachable entry is a candidate only when an exact retained
corpus/artifact/config binding can rebuild that key. There is no age, mtime, or
LRU selection. Unreadable subtrees, unexpected files, malformed or non-finite
JSON, duplicate keys, short/incomplete keys, path/key disagreement, source
change, links, reparse points, or any other ambiguity retain all provisional
candidates and block apply.

The plan pins corpus, registry, candidate artifacts, semantic snapshot/replay
hashes, the genuine active pointer's exact identity, the complete release
manifest and declared artifact inventory, and the presence or absence of
event-side inputs used by replay:
`features_long.csv`, reconstructed replay input, `settlement.json`,
`order_books_summary.csv`, `price_history.csv`, `market_ws_events.csv`, and
`market_ws.jsonl`. Host-specific absolute folder aliases are replaced with the
verified folder beneath the protected snapshots root before compute.

An unreachable key is rebuildable only when its candidate artifact carries a
verified `production_static_context`. That freezes climate and source
reliability and explicitly disables unpinned reanalysis and marine sidecars;
legacy or invalid contexts remain ambiguous and retain the cache entry. Replay
also defers mutable daily-summary loading when the promotion corpus already
pins settlement. A release graph that omits any corpus market blocks
reachability before candidate selection.

### Apply boundary

Apply requires:

- exact approved manifest SHA-256 and stable file identity;
- exact cleanup-manifest and tool schema versions;
- explicit operator, timestamp, note, and approval;
- unchanged corpus/registry/artifact/input identities;
- `cleanup_preflight=PASS`;
- exact candidate path, bytes, SHA-256, file identity, schema, full key, and
  key-derived cache path;
- durable JSON and Markdown receipts;
- stop on first failure; and
- exact-file `unlink` only, never directory removal.

For each candidate, apply calls the real
`weather.calibration.pooled_candidate_replay._compute_pooled_candidate_day`
directly, bypassing cache reads. It loads the exact retained serving graph from
the genuine active pointer through the unmodified strict release-containment
path. The resolved `release_id`, `manifest_sha256`, and `release_dir` must
match the approved plan or cleanup aborts and retains the candidate. It
computes every exact source binding, requires zero corpus warnings, and
compares `rows`, `replay_results`, `coverage`, `diagnostics`, and the full key
under the established numeric tolerance.

This cache-off proof runs once before the durable `PRE_UNLINK` write and again
after it. The second proof is durably recorded; then live reachability and all
pinned source identities are recomputed once more, the exact candidate is
reverified, and only then is that one file unlinked.

The standalone two-file `rebuild-one` comparison remains available only as a
fixture diagnostic. Its receipt explicitly says it does not prove actual
compute or retained inputs.

### Quota recommendation

Keep the proposed **10 GiB** quota. It is intentionally much larger than the
expected active/shadow working set, so it detects runaway model/config identity
accumulation without turning quota pressure into an eviction policy. If
reachable bytes exceed the quota, the plan blocks; reachable entries are never
selected to force the number down.

## Mission 3 — closed-day projection tiering

`weather.operations.closed_day_projection_tiering` is manual, plan-by-default,
and not connected to a scheduler. Planning requires a closed/finalized event,
current PASS event-day manifest, canonical rebuild source, no competing writer
lock, at least 7,200 seconds since the long projection's last write, exact
identities, and the complete family registry below.

Apply requires a separately edited approval bound to the immutable plan hash
and to the exact approved-manifest file bytes/stat identity. `cleanup_preflight`
runs before compression. The tool then acquires the shared raw-tape writer
lock, rechecks writer quiescence under that lock, writes deterministic gzip
(`mtime=0`), proves uncompressed byte, SHA-256, and line parity, rechecks
finalization/manifests/identities, writes a durable unlink-pending receipt,
rechecks immediately, and unlinks only the exact plain CSV. Raw JSONL and gzip
remain. The writer lock stays held through event-day-manifest rebuild and PASS
validation.

Every CLI operation requires repeated `--protected-root` values. The source
data root is independently derived and protected, and output is rejected if it
overlaps any declared production or mirror root.

### Projection-family registry

`P` means validated Parquet, `G` gzip CSV, `T` plain text CSV, and `J` canonical
JSONL.

| Family | Canonical rebuild source(s) | Accepted reads | Eligible | Current blocker |
| --- | --- | --- | --- | --- |
| `snapshots_long` | `snapshots.jsonl` | P / G / T | No | Direct gzip readers not all proven |
| `features_long` | `features.jsonl` | P / G / T | No | Direct gzip readers not all proven |
| `components_long` | `components.jsonl` | P / G / T | No | Direct gzip readers not all proven |
| `forecasts_long` | `forecasts.jsonl` | P / G / T | No | Direct gzip readers not all proven |
| `forecast_payloads_long` | `forecast_payloads.jsonl`, payload JSON trees, reconstructed payload JSON | P / G / T | No | Direct gzip readers not all proven |
| `observation_payloads_long` | `observation_payloads.jsonl`, payload JSON trees | P / G / T | No | Direct gzip readers not all proven |
| `source_status_long` | `source_status.jsonl` | P / G / T | No | Direct gzip readers not all proven |
| `replay_inputs` | canonical and reconstructed replay-input JSONL | P / J | No | Canonical evidence is not a cleanup candidate |
| `replay_input_status` | snapshots and replay-input JSONL | P / G / T | No | Row rebuild and gzip readers unproven |
| `clob_capture_status` | `clob_capture_status.jsonl` | P / J | No | Canonical evidence is not a cleanup candidate |
| `clob_tokens` | `clob_tokens.jsonl` | P / G / T | No | Existing storage-class and gzip-reader gates |
| `order_books_summary` | `order_books.jsonl` | P / G / T | No | Current readers require uncompressed summary |
| `order_books_long` | `order_books.jsonl` | J / P / G / T | **Yes** | None |
| `price_history` | price-history JSONL/raw manifest/raw JSON | P / G / T | No | Dedupe/upsert rebuild and gzip readers unproven |
| `market_ws_events` | `market_ws.jsonl` | P / G / T | No | Direct gzip readers not all proven |
| `clob_features_long` | feature, raw book, price-history, and token JSONL | P / G / T | No | Direct gzip readers not all proven |
| `variant_predictions_long` | `variant_predictions.jsonl`, legacy `live_variant_predictions.jsonl` | P / G / T | No | Raw rebuild parity and gzip readers unproven |

The registry is equality-checked against all 17
`closed_market_day_archive.ARTIFACT_FAMILIES`. Any missing/extra family or
ineligible family without a blocker invalidates the plan.

## Fixture receipts and adversarial proof

The tests create disposable data/mirror/output roots and exercise real file
operations only there.

| Mechanism | Fixture receipt/evidence | Result |
| --- | --- | --- |
| Capture policy default | Summary, raw JSONL, and long CSV written | PASS |
| Capture policy disabled | Summary and raw JSONL written; long CSV absent; status records zero long rows | PASS |
| Full-book rebuild/fallback | Raw JSONL rebuild byte-equals writer projection; raw then gzip fallback yields same rows | PASS |
| MM live preflight | Summary-only and gzip-only raw-book presence | PASS |
| Replay dry-run | One reachable key retained; one exact unreachable/rebuildable key selected; no age/LRU evidence | PASS |
| Replay retained-input graph | Real synthetic release manifest and every declared artifact are pinned; the genuine active pointer resolves through strict containment and exact plan matching | PASS |
| Replay active-release drift | Release ID, manifest SHA-256, or release-directory drift from the approved plan | All abort |
| Replay compute dependency path | Explicit serving bundle reaches replay/model construction; a corpus-pinned settlement does not read mutable daily history | PASS |
| Replay apply orchestration | Durable JSON/Markdown, two cache-off parity proofs, post-receipt source recheck, exact candidate removed, reachable entry retained | PASS with stubbed expensive candidate scorer |
| Replay adversarial cases | Ambiguity, source/candidate replacement, optional input appearance, reparse path, parity drift, receipt failure, stale schemas, legacy static context, and reachable-key injection | All block and retain |
| Replay folder alias | External manifest alias is neutralized; compute uses the verified canonical folder below `snapshots_root` | PASS |
| Projection dry-run | Closed/finalized and writer-quiet fixture yields one exact action; active/invalid/locked/recently-written fixtures remain blocked | PASS |
| Projection apply | Deterministic gzip retained, exact CSV removed, raw JSONL retained, event manifest rebuilt PASS | PASS on synthetic fixture |
| Projection adversarial cases | Changed identity, stale manifest/finalization, reparse, lock, lost quiescence, receipt failure, malformed approval, and first-action failure | All stop before unsafe continuation |

The destructive replay-apply tests intentionally monkeypatch the expensive
candidate scorer; therefore they prove orchestration and fail-closed behavior,
not production model parity. Separate tests execute the real replay enumerator
with its explicit serving-bundle dependency and load a real synthetic verified
release inventory. The production implementation calls the actual candidate
compute callable; the operator's production apply is the first real-data
rehearsal.

## Roll-safety import closure

The audit parsed all 422 `src/weather/**/*.py` files with `ast` (zero parse
errors), resolved absolute and relative `weather.*` imports conservatively, and
walked transitively from:

- `weather.collection.snapshot_tracker` — 142 modules including root;
- `weather.market.market_microstructure` — 139 modules including root; and
- `weather.operations.observation_trigger` — 145 modules including root.

The known-loaded control `weather.paths` appeared by a direct import in all
three roots, so an empty/broken graph could not report false safety.

| Audited module | Snapshot tracker | Market microstructure | Observation trigger | Classification |
| --- | --- | --- | --- | --- |
| `backtesting/replay_backtest.py` | Yes | Yes | Yes | Loop-loaded |
| `calibration/pooled_candidate_replay.py` | Yes | Yes | Yes | Loop-loaded |
| `market/market_microstructure_capture.py` | No | Yes | No | Loop-loaded |
| `market/storage_pressure_policy.py` | No | Yes | No | Loop-loaded |
| `operations/closed_market_day_archive.py` | Yes | Yes | Yes | Loop-loaded |
| `operations/storage_classes.py` | Yes | Yes | Yes | Loop-loaded |
| `release_artifacts.py` | Yes | Yes | Yes | Master-identical after release-binding rework; no final topic-branch diff |
| `release_serving.py` | Yes | Yes | Yes | Master-identical after release-binding rework; no final topic-branch diff |
| `schema_registry_recent_data.py` | Yes | Yes | Yes | Loop-loaded |
| `market/order_book_tape.py` | No | No | No | Outside all three |
| `operations/closed_day_projection_registry.py` | No | No | No | Outside all three |
| `operations/closed_day_projection_tiering.py` | No | No | No | Outside all three |
| `operations/config_inventory.py` | No | No | No | Outside all three |
| `operations/market_making_tape_encoding.py` | No | No | No | Outside all three |
| `operations/replay_cache_retention.py` | No | No | No | Outside all three |
| `operations/replay_cache_retention_parity.py` | No | No | No | Outside all three |
| `operations/replay_cache_retention_report.py` | No | No | No | Outside all three |
| `operations/replay_cache_retention_serving.py` | No | No | No | Outside all three |

The direct market-loop control is
`market_microstructure.py -> market_microstructure_capture.py`. The three-way
archive/storage path is recovered through release/corpus imports into
`event_day_manifest` and `storage_classes`. `event_day_manifest.py` itself was
not edited in this build.

This confirms why the build belongs on the workstation. Merging the seven
final topic-branch-different loop-loaded modules on the production host can
roll loaded identities even without a scheduler edit.

## Verification

| Command/scope | Result |
| --- | --- |
| Final focused storage-pressure, replay/release, tiering, schema, and module-size suite | 324 passed, 1 Windows symlink skip, 45 subtests passed |
| 2026-07-28 strict-release and writer-quiescence rework suite | 122 passed, 1 Windows symlink skip |
| Tracked-file import architecture ratchet | 21 passed |
| Strict schema-registry audit over merged `src` | 504 registered schemas, 839 discovered literals, 0 unregistered versions |
| AST loop-closure audit | 422 modules parsed, zero errors; counts 142 / 139 / 145 |
| Full merged repository suite | 3,230 passed, 4 skipped, 820 subtests passed; 12 unchanged `test_experiment_executor.py` cases hit legacy Windows `MAX_PATH` even with `C:\w` as pytest's temp root |
| Full-suite path-limit diagnosis | `LongPathsEnabled=0`; neither `experiment_executor.py` nor its tests changed in this build |
| `compileall -q app src tests` | PASS |
| `weather.operations.agent_docs_audit` | PASS: 18 agent files, 495 Markdown files |

## Operator handoff

Use the canonical commands in
`docs/operations/data-retention-policy.md`. Supply the production `data` root
and every mirror root separately with repeated `--protected-root`, and keep the
single output root outside all of them.

Recommended order remains:

1. merge in a quiet window, accounting for the seven final
   topic-branch-different loop-loaded modules;
2. leave `capture.write_order_books_long_csv=true`;
3. run and review production dry-runs during the day;
4. perform rebuild-one checks and inspect every exact path/identity/reason;
5. approve manifests externally;
6. apply only in the 01:00–04:00 quiet window while measuring disk before and
   after; and
7. activate the capture flag only after the lock and only as a separate,
   reversible operator change.
