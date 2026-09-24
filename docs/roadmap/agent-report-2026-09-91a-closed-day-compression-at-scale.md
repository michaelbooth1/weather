# Mission 91a — closed-day compression at scale

**PARTIAL / NOT QUALIFIED — implementation and design drafted; heavy verification is blocked by the shared lease. Do not register or run on production yet.**

Branch: `codex/closed-day-compression-20260924`, based on fetched `origin/master`
`198f7ccbcd8e80271693462425582097d22b298b`. Handoff authority:
`origin/codex/reward-test-attended-handoff-20260921` at
`7014b637e228228fab763a7febea82c8852b6809`. This report travels with the draft
implementation commit; publication is not qualification or runtime adoption.

## Implementation

The new nightly consumer reuses the existing bounded metadata inventory and
`compress_candidate` verifier. It streams SHA-256 before/after native NTFS
compression under the same writer-excluding file handle, checks native
identity/timestamps and counts only positive verified allocation savings.
The original attended request, thirty-day cutoff, 64-MiB default and
600-second bound remain intact. The existing manually planned early/late
`storage_recovery_night` workflow also remains intact; it is not silently
retargeted to automatic recurring selection.

Nightly mode selects immediate ordinary text files in recognized built-in
snapshot event folders strictly older than fourteen local calendar days and
unchanged for fourteen days. It never traverses nested campaign, mm_runs,
settlement or payload roots. Limits: 256 MiB/file, 1 GiB/256 files per batch,
at most 32 GiB/8,192 files per night, with a smaller policy budget allowed.
Inventory and evidence bounds are explicit. Hashing remains 16 MiB/s with
1 MiB buffers. Disk reserve includes two maximum file images and evidence.

An expiring, host-bound policy authorizes automatic selection for at most
31 days. The scheduled action binds its immutable path/hash and the reviewed
source tip. A policy expiry stops work; there is no automatic renewal. The
runner and wrapper use kill-on-close Jobs; the wrapper owns the shared lease,
retains health/memory/identity gates, and tears down before 04:45.

Every attempt retains policy, inventories, hash-bound batch selections,
per-file preimage/postimage journals, batch results, nightly savings and the
wrapper result. One failure stops expansion. A failed/incomplete prior nightly
attempt blocks later automatic runs for production review. No automatic
repair, deletion, decompression or evidence namespace reuse is implemented.
That interlock currently requires a separately reviewed recovery change after
retained-file reconciliation; there is no casual clear-lock switch. A second
nightly-entrypoint invocation on the same local date refuses.

The registrar is `scripts/ops/register_cold_snapshot_nightly.ps1`; it creates
`WeatherColdSnapshotNightly` at 00:30, S4U/Limited, IgnoreNew, no late catch-up,
255-minute Scheduler limit, and reads back action/trigger/settings. It has
not been executed. Production's exact registration command and policy fields
are in [the owning runbook](../operations/cold-snapshot-compression.md#nightly-automatic-selection).

## Capacity projection, not a measurement

At a fully consumed 32-GiB logical-input budget, hypothetical NTFS ratios of
2x and 3x imply **16 to 21.3 GiB verified savings/night**. Two hash passes alone
take at least 68.3 minutes at 16 MiB/s, before inventory and compression time.
Actual savings depend on eligible old files, NTFS ratio, writer availability
and resource admission; they can be zero. The handoff's gzip ratios are not
NTFS measurements. The supplied 453-GiB inventory and ~10-GiB/day growth are
production facts from the handoff, not workstation observations. Neither the
eligible fraction nor a production throughput guarantee is established.

## Source-close and mm_runs decisions

Compress-on-close is a written design only. `SnapshotStore` owns the replay,
snapshot, component, variant and explanation writers (`snapshot_store.py:622`
through its path setup); `MarketMicrostructureStore` owns CLOB token and
summary writers (`market_microstructure_capture.py:769`). Moving compression
into either writer is not small: the close boundary must coordinate backfills,
read/replay activity, writer handles and a durable queue without blocking the
capture iteration. This branch changes neither writer. A separate close lane
would reuse unchanged-path NTFS and require an explicit close policy rather
than weakening the nightly fourteen-day floor.

The proposed mm_runs lane keeps lifecycle/risk/order evidence permanently
under `storage_classes.py:243`. Only terminal paper runs would qualify for
separate lossless NTFS compression after writer and replay-reference checks.
There is no age-only pruning. Original removal remains subject to off-PC
archive, independent restore proof and exact-file approval. RE-1/live/active
runs and incident evidence stay excluded. Nothing in mm_runs was read or changed.

## Readers and compatibility proof

The selected format remains ordinary JSON/JSONL/CSV at exactly the same path.
NTFS decompresses logical reads; no application gzip support is required.
Per-file identity/size/hash equality is therefore the compatibility contract
for direct, registry-routed and dynamically constructed readers alike. The
native synthetic test exercises this contract above the former 64-MiB limit;
it is present but not yet run. This is not a claim that a filename search
proves every dynamic caller, or that every consumer has been runtime tested.

The reference inventory below lists static filename references in canonical
`src/weather` and `app`, including producers, readers, registry routes and
audits. The key shared reader routes are `closed_day_projection_registry`
(plain/gzip/Parquet selection), snapshot/replay readers, CLOB feature readers,
markout scoring and the dashboard input paths. Their logical format is unchanged.
No gzip migration is authorized by this branch.

## Verification and boundaries

All three PowerShell scripts pass parser-only checks. Diff whitespace checks
pass. Synthetic tests were added for large files, writer exclusion, budget
stop, hot-day refusal, failure stop, policy expiry and wrapper time bounds.
Existing hash-mismatch, native-identity and child teardown tests remain the
regression net. **No 91a test or compile run has succeeded yet:** the shared
workstation wrapper refused both attempts before starting pytest.

Initial local checks found no matching RE-1 command. Subsequent investigation
found running Python processes with unreadable command-line metadata; their
role cannot be proved. Heavy work is held pending owner confirmation that
RE-1 is stopped and availability of the required shared lease. No process was
stopped and no lease or guard was bypassed.

Reproduction payload, through `scripts/ops/workstation_heavy.ps1 -Kind pytest`,
from this checkout with the project's interpreter and a short owned basetemp:

```text
-m pytest tests/operations/test_cold_snapshot_nightly.py
tests/operations/test_cold_snapshot_compression.py
tests/operations/test_cold_snapshot_compression_wrapper.py
tests/operations/test_storage_recovery_inventory.py
tests/operations/test_replay_cache_compression.py
tests/operations/test_schema_registry.py
tests/operations/test_import_architecture.py -q --basetemp <owned-absolute-short-directory>
```

No production or mirror access, real-tape read, credential access, venue call,
RE-1 worktree/campaign access, Scheduler registration, restart, merge or
production write occurred. No empirical inference or date/market clusters
apply to these synthetic storage checks. No source bytes were compressed by
the workstation task; native compression remains an unrun disposable fixture.

## Per-file roll disposition

| File | Disposition |
| --- | --- |
| `src/weather/schema_registry_recent_data.py` | Two additive-only registrations; schema registry family enters all four retained capture closures by the standing contract. Treat branch as roll-sensitive pending production verdict. |
| `src/weather/operations/cold_snapshot_nightly.py` | New operation-only consumer; production closure verdict required. |
| `src/weather/operations/ntfs_file_compression.py` | Shared native helper, default unchanged; production closure verdict required. |
| `src/weather/operations/storage_recovery_inventory.py` | Optional age profile, default unchanged; production closure verdict required. |
| `scripts/ops/cold_snapshot_compression_run.ps1` | Roll-free PowerShell; attended bound preserved. |
| `scripts/ops/cold_snapshot_nightly_run.ps1` | Roll-free PowerShell. |
| `scripts/ops/register_cold_snapshot_nightly.ps1` | Roll-free PowerShell; registration still requires production authority. |
| `tests/operations/test_cold_snapshot_nightly.py` | Synthetic-only; include in production branch verdict. |
| `tests/operations/test_cold_snapshot_compression_wrapper.py` | Fixture-only; include in production branch verdict. |
| Three owning operations documents and this report | Roll-free Markdown. |

Production must obtain the actual per-file verdict with
`scripts/ops/roll_verdict.ps1 -Branch codex/closed-day-compression-20260924`.
The additive registry change is explicitly separated from operation-only
code and roll-free scripts/docs; no live closure was read on the workstation.

## Static reader/reference inventory

```text
src/weather\backtesting\replay_backtest.py:362:            print(f"  skip {Path(folder).name}: no replay_inputs.jsonl (capture not yet seeded)")
src/weather\collection\snapshot_tracker.py:353:    replay_inputs_path = folder / "replay_inputs.jsonl"
src/weather\collection\snapshot_tracker.py:374:            "reason": "no replay_inputs.jsonl or replay_inputs_reconstructed.jsonl",
src/weather\collection\snapshot_tracker.py:428:            "reason": "no replay_inputs.jsonl or replay_inputs_reconstructed.jsonl",
src/weather\collection\snapshot_tracker.py:2245:            "Rebuild source_status_long.csv/jsonl from replay_inputs.jsonl "
src/weather\collection\snapshot_tracker.py:2254:            "from replay_inputs.jsonl or replay_inputs_reconstructed.jsonl under --snapshots-root."
src/weather\collection\snapshot_store_backfill.py:161:    core.add_argument("folders", nargs="+", help="Snapshot folder(s) containing snapshots.jsonl.")
src/weather\collection\snapshot_store_backfill.py:164:    backfill.add_argument("folders", nargs="+", help="Snapshot folder(s) containing snapshots.jsonl.")
src/weather\backtesting\replay.py:29:REPLAY_INPUTS_FILENAME = "replay_inputs.jsonl"
src/weather\backtesting\replay.py:30:# Reconstructed records (approximate, regenerable from snapshots.jsonl) are kept
src/weather\backtesting\replay.py:301:# writes replay_inputs.jsonl are fully, faithfully replayable. To make the
src/weather\backtesting\replay.py:508:    return _read_jsonl(Path(folder) / "snapshots.jsonl")
src/weather\backtesting\replay.py:513:    ``replay_inputs_reconstructed.jsonl``) for any snapshot in ``snapshots.jsonl``
src/weather\backtesting\replay.py:648:        folders = sorted(str(p.parent) for p in root.glob("*/snapshots.jsonl"))
src/weather\collection\snapshot_store.py:622:        self.jsonl_path = self.root / "snapshots.jsonl"
src/weather\collection\snapshot_store.py:629:        self.components_jsonl_path = self.root / "components.jsonl"
src/weather\collection\snapshot_store.py:638:        self.variant_predictions_long_path = self.root / "variant_predictions_long.csv"
src/weather\collection\snapshot_store.py:639:        self.variant_predictions_jsonl_path = self.root / "variant_predictions.jsonl"
src/weather\collection\snapshot_store.py:640:        self.replay_inputs_path = self.root / "replay_inputs.jsonl"
src/weather\collection\snapshot_store.py:641:        self.snapshot_explanations_long_path = self.root / "snapshot_explanations_long.csv"
src/weather\calibration\residual_distribution_corpus.py:6:instead consumes the captured ``replay_inputs.jsonl`` payload, selects exactly
src/weather\calibration\residual_distribution_corpus.py:54:REPLAY_INPUT_FILENAME = "replay_inputs.jsonl"
src/weather\calibration\residual_distribution_corpus.py:57:VARIANT_PREDICTIONS_FILENAME = "variant_predictions.jsonl"
src/weather\collection\collection_health.py:1320:            "path": str(folder / "variant_predictions_long.csv"),
src/weather\collection\collection_health.py:1334:            "path": str(folder / "variant_predictions_long.csv"),
src/weather\collection\collection_health.py:1343:            "path": str(folder / "variant_predictions_long.csv"),
src/weather\collection\collection_health.py:1348:    path = folder / "variant_predictions_long.csv"
src/weather\collection\collection_health.py:1355:            "reason": "variant_predictions_long.csv missing or empty",
src/weather\market\market_making_preflight.py:1089:        filename = "clob_tokens.csv" if gate_name == "clob_tokens" else "order_books_summary.csv"
src/weather\market\clob_recon.py:178:        if folder.is_dir() and (folder / "order_books_summary.csv").exists()
src/weather\market\clob_recon.py:246:        for row in read_csv_rows(Path(folder) / "order_books_summary.csv"):
src/weather\market\execution_tape_markout.py:16:* ``order_books_summary.csv`` -- THE CHOSEN MIDPOINT SOURCE.  It already carries
src/weather\market\execution_tape_markout.py:62:SUMMARY_FILENAME = "order_books_summary.csv"
src/weather\calibration\pooled_candidate_replay_report.py:417:        "> Candidate features are rebuilt from pinned `replay_inputs.jsonl` with",
src/weather\market\market_latest_inputs.py:326:        folder / "clob_tokens.csv",
src/weather\market\market_latest_inputs.py:333:        folder / "order_books_summary.csv",
src/weather\market\mm_live_candidate_cli.py:426:            == event_folder / "clob_tokens.csv"
src/weather\market\mm_live_candidate_cli.py:428:            == event_folder / "order_books_summary.csv"
src/weather\market\market_microstructure_features.py:527:        read_csv_rows(folder / "order_books_summary.csv"),
src/weather\calibration\pooled_candidate_replay.py:782:        if not (Path(folder) / "order_books_summary.csv").exists():
src/weather\calibration\pooled_candidate_replay.py:2418:        folder / "replay_inputs.jsonl",
src/weather\calibration\pooled_candidate_replay.py:2765:        replay_path = folder / "replay_inputs.jsonl"
src/weather\market\market_microstructure.py:500:    path = Path(folder) / "order_books_summary.csv"
src/weather\market\mm_paper.py:2102:        if (Path(snapshots_root) / slug / "order_books_summary.csv").exists()
src/weather\market\mm_paper_scoring.py:1564:    for row in iter_csv_rows(Path(folder) / "order_books_summary.csv"):
src/weather\market\mm_paper_scoring.py:1767:    for row in iter_csv_rows(folder / "order_books_summary.csv"):
src/weather\market\mm_paper_scoring.py:1768:        add_mark(row, "order_books_summary.csv", time_keys=("captured_at_utc", "book_time_utc", "captured_at_local"))
src/weather\market\market_microstructure_capture.py:769:        self.token_path = self.root / "clob_tokens.csv"
src/weather\market\market_microstructure_capture.py:770:        self.token_jsonl_path = self.root / "clob_tokens.jsonl"
src/weather\market\market_microstructure_capture.py:771:        self.books_summary_path = self.root / "order_books_summary.csv"
src/weather\market\market_making_run_support.py:66:        folder / "clob_tokens.csv",
src/weather\market\market_making_run_support.py:67:        folder / "order_books_summary.csv",
src/weather\market\market_making_run_support.py:187:        for row in read_csv_rows(Path(folder) / "order_books_summary.csv")
src/weather\market\market_making_run_support.py:323:    all_token_rows = read_csv_rows(Path(folder) / "clob_tokens.csv")
src/weather\market\market_making_run_support.py:510:        reason = "clob_tokens.csv has no rows"
src/weather\market\market_making_run_support.py:798:    token_rows = read_csv_rows(folder / "clob_tokens.csv")
src/weather\market\portable_live_candidate_preflight.py:109:    rows = read_csv_rows(folder / "clob_tokens.csv")
src/weather\market\portable_live_candidate_preflight.py:239:        "clob_tokens": folder / "clob_tokens.csv",
src/weather\market\portable_live_candidate_preflight.py:240:        "order_books_summary": folder / "order_books_summary.csv",
src/weather\sources\official_guidance_collection.py:626:        if path.is_file() and path.name == "replay_inputs.jsonl":
src/weather\sources\official_guidance_collection.py:629:            output.extend(sorted(path.rglob("replay_inputs.jsonl")))
src/weather\sources\official_guidance_collection.py:762:    parser.add_argument("paths", nargs="+", help="Snapshot root(s) or replay_inputs.jsonl file(s).")
src/weather\market\taker_bot_scoring.py:177:    for row in read_csv_rows(folder / "order_books_summary.csv", attach_diagnostics=True):
src/weather\market\taker_bot_strategy_evaluation.py:30:        token_rows = read_csv_rows(Path(folder) / "clob_tokens.csv", attach_diagnostics=True)
src/weather\market\worker_release_binding.py:6:been captured by that exact bundle.  ``replay_inputs.jsonl`` is the independent,
src/weather\market\worker_release_binding.py:41:REPLAY_INPUT_FILENAME = "replay_inputs.jsonl"
src/weather\operations\clob_order_book_tiering.py:220:            "summary_present": (folder / "order_books_summary.csv").exists(),
src/weather\operations\clob_order_book_tiering.py:222:            "token_map_present": (folder / "clob_tokens.csv").exists()
src/weather\operations\clob_order_book_tiering.py:223:            or (folder / "clob_tokens.jsonl").exists(),
src/weather\operations\closed_market_day_archive.py:108:        ("snapshots.jsonl",),
src/weather\operations\closed_market_day_archive.py:122:        ("components.jsonl",),
src/weather\operations\closed_market_day_archive.py:160:        ("source_status.jsonl", "replay_inputs.jsonl", "replay_inputs_reconstructed.jsonl"),
src/weather\operations\closed_market_day_archive.py:166:        ("replay_inputs.jsonl", "replay_inputs_reconstructed.jsonl"),
src/weather\operations\closed_market_day_archive.py:167:        ("replay_inputs.jsonl", "replay_inputs_reconstructed.jsonl", "replay_input_status.json"),
src/weather\operations\closed_market_day_archive.py:188:        ("clob_tokens.csv", "clob_tokens.csv.gz"),
src/weather\operations\closed_market_day_archive.py:189:        ("clob_tokens.jsonl",),
src/weather\operations\closed_market_day_archive.py:195:        ("order_books_summary.csv", "order_books_summary.csv.gz"),
src/weather\operations\closed_market_day_archive.py:231:            "clob_tokens.jsonl",
src/weather\operations\closed_market_day_archive.py:238:        ("variant_predictions_long.csv", "variant_predictions_long.csv.gz"),
src/weather\operations\closed_market_day_archive.py:239:        ("variant_predictions.jsonl", "live_variant_predictions.jsonl"),
src/weather\operations\closed_day_projection_registry.py:38:        ("snapshots.jsonl",),
src/weather\operations\closed_day_projection_registry.py:62:        ("components.jsonl",),
src/weather\operations\closed_day_projection_registry.py:131:        ("replay_inputs.jsonl", "replay_inputs_reconstructed.jsonl"),
src/weather\operations\closed_day_projection_registry.py:132:        ("replay_inputs.jsonl", "replay_inputs_reconstructed.jsonl"),
src/weather\operations\closed_day_projection_registry.py:135:            "canonical_jsonl:replay_inputs.jsonl",
src/weather\operations\closed_day_projection_registry.py:145:            "snapshots.jsonl",
src/weather\operations\closed_day_projection_registry.py:146:            "replay_inputs.jsonl",
src/weather\operations\closed_day_projection_registry.py:171:        ("clob_tokens.csv", "clob_tokens.csv.gz"),
src/weather\operations\closed_day_projection_registry.py:172:        ("clob_tokens.jsonl",),
src/weather\operations\closed_day_projection_registry.py:175:            "gzip_tiered_text:clob_tokens.csv.gz",
src/weather\operations\closed_day_projection_registry.py:176:            "text_tape:clob_tokens.csv",
src/weather\operations\closed_day_projection_registry.py:186:        ("order_books_summary.csv", "order_books_summary.csv.gz"),
src/weather\operations\closed_day_projection_registry.py:190:            "gzip_tiered_text:order_books_summary.csv.gz",
src/weather\operations\closed_day_projection_registry.py:191:            "text_tape:order_books_summary.csv",
src/weather\operations\closed_day_projection_registry.py:255:            "clob_tokens.jsonl",
src/weather\operations\closed_day_projection_registry.py:267:        ("variant_predictions_long.csv", "variant_predictions_long.csv.gz"),
src/weather\operations\closed_day_projection_registry.py:268:        ("variant_predictions.jsonl", "live_variant_predictions.jsonl"),
src/weather\operations\closed_day_projection_registry.py:271:            "gzip_tiered_text:variant_predictions_long.csv.gz",
src/weather\operations\closed_day_projection_registry.py:272:            "text_tape:variant_predictions_long.csv",
src/weather\reporting\casebooks\disagreement_casebook.py:78:REPLAY_INPUTS_FILENAME = "replay_inputs.jsonl"
src/weather\reporting\casebooks\disagreement_casebook.py:79:BOOK_SUMMARY_FILENAME = "order_books_summary.csv"
src/weather\operations\daily_refresh_reporting_steps.py:876:        for path in root.glob("*/variant_predictions_long.csv"):
src/weather\reporting\data_quality\data_layer_audit_collectors.py:32:    "snapshots_jsonl": "snapshots.jsonl",
src/weather\reporting\data_quality\data_layer_audit_collectors.py:33:    "replay_inputs": "replay_inputs.jsonl",
src/weather\reporting\data_quality\data_layer_audit_collectors.py:39:    "components_raw": "components.jsonl",
src/weather\reporting\data_quality\data_layer_audit_collectors.py:40:    "snapshot_explanations": "snapshot_explanations_long.csv",
src/weather\reporting\data_quality\data_layer_audit_collectors.py:44:    "variant_predictions": "variant_predictions_long.csv",
src/weather\reporting\data_quality\data_layer_audit_collectors.py:45:    "variant_predictions_raw": "variant_predictions.jsonl",
src/weather\reporting\data_quality\data_layer_audit_collectors.py:48:    "clob_tokens": "clob_tokens.csv",
src/weather\reporting\data_quality\data_layer_audit_collectors.py:49:    "clob_tokens_raw": "clob_tokens.jsonl",
src/weather\reporting\data_quality\data_layer_audit_collectors.py:50:    "order_books_summary": "order_books_summary.csv",
src/weather\reporting\data_quality\feature_quality_quarantine.py:35:REPLAY_INPUTS = "replay_inputs.jsonl"
src/weather\reporting\data_quality\data_layer_audit.py:569:            "snapshots.jsonl",
src/weather\reporting\data_quality\data_layer_audit.py:570:            "replay_inputs.jsonl",
src/weather\reporting\data_quality\data_layer_audit.py:1035:            f"{replay_days}/{snapshot.get('folder_count', 0)} snapshot folders have replay_inputs.jsonl.",
src/weather\reporting\data_quality\data_layer_audit.py:1045:            f"{explanation_days}/{snapshot.get('folder_count', 0)} snapshot folders have snapshot_explanations_long.csv.",
src/weather\reporting\data_quality\data_layer_audit.py:1047:                "Write snapshot_explanations.jsonl and snapshot_explanations_long.csv for each live snapshot, "
src/weather\reporting\fleet\fleet_observability_gates.py:206:        return variant_tape.get("reason") or "variant_predictions_long.csv is missing or stale"
src/weather\operations\density_live_replay_parity.py:376:        snapshot_path = folder / "snapshots.jsonl"
src/weather\operations\density_live_replay_parity.py:377:        tape_path = resolve_local_path(folder / "variant_predictions.jsonl")
src/weather\operations\density_live_replay_parity.py:378:        replay_path = folder / "replay_inputs.jsonl"
src/weather\reporting\data_quality\clob_coverage_audit.py:24:    "order_books_summary.csv",
src/weather\reporting\data_quality\clob_coverage_audit.py:30:TOKEN_FILES = ("clob_tokens.csv", "clob_tokens.jsonl")
src/weather\reporting\research\blind_feature_repair.py:303:    first = _read_first_jsonl(path / "replay_inputs.jsonl")
src/weather\reporting\research\blind_feature_repair.py:339:    for folder in sorted(snapshots_root.glob("*/replay_inputs.jsonl")):
src/weather\reporting\research\quotable_edge.py:383:        records = _read_selected_records(folder / "replay_inputs.jsonl", selected_ids)
src/weather\reporting\source_gates\source_family_inventory.py:263:            "order_books_summary.csv",
src/weather\reporting\source_gates\source_family_inventory.py:759:        "order_books_summary.csv",
src/weather\reporting\scorecards\captured_input_parity_evidence.py:3:The replay side is rebuilt from ``replay_inputs.jsonl`` plus the sibling
src/weather\reporting\scorecards\captured_input_parity_evidence.py:222:            next_action="run the bounded generator against fresh release-bound replay_inputs.jsonl",
src/weather\reporting\scorecards\captured_input_parity_evidence.py:243:                "wait for fresh replay_inputs.jsonl capture under the verified release"
src/weather\reporting\scorecards\captured_input_parity_evidence.py:480:            next_action="point the command at exactly one market-day replay_inputs.jsonl",
src/weather\reporting\scorecards\captured_input_parity_evidence.py:557:                next_action="restore the exact sibling snapshots.jsonl for this replay corpus",
src/weather\reporting\scorecards\captured_input_parity_evidence.py:589:            next_action="restore snapshots.jsonl for the captured inputs; do not copy bands or probabilities from the served tape",
src/weather\reporting\scorecards\captured_input_parity_evidence.py:1066:    captured_path = Path(captured_inputs_path) if captured_inputs_path else folder / "replay_inputs.jsonl"
src/weather\reporting\scorecards\captured_input_parity_evidence.py:1067:    snapshots_path = Path(snapshot_tape_path) if snapshot_tape_path else folder / "snapshots.jsonl"
src/weather\reporting\scorecards\captured_input_parity_evidence.py:1068:    served_path = Path(served_tape_path) if served_tape_path else folder / "variant_predictions.jsonl"
src/weather\reporting\scorecards\inactive_release_forward_shadow.py:852:            "recorded_production_field": "snapshots.jsonl.bands[].model_probability",
src/weather\reporting\scorecards\inactive_release_forward_shadow.py:853:            "captured_input_identity": "replay_inputs.jsonl.captured_input_hash",
src/weather\reporting\scorecards\live_variant_settlement_scorecard.py:1972:    return sorted(Path(snapshots_root).glob("*/variant_predictions_long.csv"))
src/weather\reporting\scorecards\live_variant_settlement_scorecard.py:2915:                        "generate replay rows from replay_inputs.jsonl under the exact "
src/weather\operations\event_day_manifest.py:135:    EventDayArtifactFamily("clob_tokens", ("clob_tokens.csv", "clob_tokens.jsonl")),
src/weather\operations\event_day_manifest.py:138:        ("order_books.jsonl", "order_books_summary.csv", "order_books_long.csv", "order_books_long.csv.gz"),
src/weather\operations\event_day_manifest.py:158:    EventDayArtifactFamily("variant_predictions", ("variant_predictions*.jsonl", "variant_predictions*.csv", "variant_predictions*.csv.gz")),
src/weather\reporting\scorecards\settled_day_root_cause.py:45:EXPLANATIONS_FILENAME = "snapshot_explanations_long.csv"
src/weather\reporting\scorecards\snapshot_evaluation.py:42:    "replay_inputs": "replay_inputs.jsonl",
src/weather\reporting\scorecards\snapshot_evaluation.py:49:    "order_books": "order_books_summary.csv",
src/weather\operations\market_making_tape_encoding.py:32:    "order_books_summary.csv",
src/weather\operations\market_making_tape_encoding.py:35:    "clob_tokens.csv",
src/weather\operations\observation_trigger.py:1446:        for record in read_jsonl(Path(folder) / "replay_inputs.jsonl")
src/weather\operations\release_admissibility_clock.py:660:            folder / "replay_inputs.jsonl",
src/weather\operations\release_admissibility_clock.py:666:            folder / "replay_inputs.jsonl",
src/weather\operations\replay_cache_retention.py:93:    "order_books_summary.csv",
src/weather\operations\replay_status_backfill.py:84:    snapshots_path = folder / "snapshots.jsonl"
src/weather\operations\storage_classes.py:157:            "snapshots/*/variant_predictions.jsonl",
src/weather\operations\storage_classes.py:158:            "snapshots/*/live_variant_predictions.jsonl",
src/weather\operations\storage_classes.py:170:            "data/snapshots/<event>/snapshots.jsonl",
src/weather\operations\storage_classes.py:173:            "data/snapshots/<event>/variant_predictions.jsonl",
src/weather\operations\storage_classes.py:181:            "snapshots/*/replay_inputs.jsonl",
src/weather\operations\storage_classes.py:189:        examples=("data/snapshots/<event>/replay_inputs.jsonl",),
src/weather\operations\storage_classes.py:198:            "snapshots/*/clob_tokens.jsonl",
src/weather\operations\storage_classes.py:216:        ("snapshots/*/clob_tokens.csv",),
src/weather\operations\storage_classes.py:221:        examples=("data/snapshots/<event>/clob_tokens.csv",),
src/weather\operations\storage_classes.py:426:            "snapshots/*/order_books_summary.csv",
```
