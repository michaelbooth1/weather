# Audit dimension: data integrity, atomicity, locking and concurrency

Auditor: data-integrity subagent. Date: 2026-09-19 (audit label 2026-09-18). Host: live production capture host, read-only.
Method constraint: Read / Grep / Glob on `src/`, `tests/`, `docs/`, `scripts/` only, plus two whitelisted `git log` / `git show --stat` calls.
`data/` was NOT opened (my brief did not explicitly allow it), so every statement about on-disk state is either `doc_claimed` or `inferred` and is labelled as such. No Python, no tests, no scripts were run. Nothing in the project was modified.

Health grade for this dimension: **C**.
The newest writers are genuinely well engineered (content-addressed stores, execution tape, settlement-ledger append, cold archive, projection tiering, hash-chained evidence ledger). The oldest and most heavily used paths are not (labels CSV, CLOB tapes, canonical snapshot JSONL, CLOB tiering delete), and the same primitive is re-implemented many times with different guarantees (3 lock implementations, 5+ private `read_jsonl` copies, 3 private `merge labels CSV` copies, 86 atomic JSON writes vs 162 in-place JSON writes).

---

## 1. Scope covered

| Area | Files actually read |
| --- | --- |
| Shared IO primitives | `src/weather/io.py` (whole file) |
| Settlement ledger + labels CSV | `src/weather/backtesting/settlement_ledger.py` (whole), `src/weather/market/market_day_labels.py`, `src/weather/backtesting/settled_days.py`, `src/weather/operations/settled_day_freshness.py` (parts), `src/weather/operations/daily_refresh_source_steps.py:600-678`, `src/weather/operations/daily_refresh_trading_steps.py:610-690`, `src/weather/reporting/source_gates/settlement_source_audit.py` (parts), `tests/backtesting/test_settlement_ledger.py`, `docs/operations/FINALIZE_LOST_A_SETTLEMENT_DAY_2026-08-11.md`, `scripts/ops/settlement_backfill_one.ps1`, `scripts/ops/daily_refresh_contract.ps1` |
| Snapshot tape | `src/weather/collection/snapshot_store.py` (write path 640-1090, CAS 1320-1440, append helpers 2486-2615, lock 3055-3108), `src/weather/collection/forecast_archive.py:380-470` |
| CLOB / order-book tape | `src/weather/market/market_microstructure_capture.py` (store 740-885, capture 1085-1200, 1340-1420, 1535-1595, price history 470-540), `src/weather/market/order_book_tape.py`, `src/weather/market/market_microstructure_features.py:551-566` |
| Execution tape | `src/weather/market/execution_tape_store.py` (1-1337, 1570-1610), `src/weather/market/execution_tape_capture.py:525-595` |
| Forecast payload CAS | `src/weather/collection/forecast_payload_cas.py` (structure) |
| Tiering / archive | `src/weather/operations/clob_raw_tape_tiering.py:200-340`, `clob_order_book_tiering.py` (structure), `closed_day_projection_tiering.py` (fsync/replace sites), `closed_day_projection_registry.py:1-110`, `cold_archive_locations.py` (resolver), `cold_archive_catalog.py` (structure), `storage_classes.py:30-160`, `event_day_manifest.py:1-200, 385-460` |
| WU history store | `src/weather/sources/wu_history.py` (writers) |
| Evidence ledgers / locks / supervisor | `production_evidence_ledgers.py` (structure), `process_lock_identity.py` (structure), `supervisor.py:205-285, 1400-1450`, `snapshot_tracker.py:1466-1515`, `loop_jsonl_repair.py:1-80` |
| Config writers | `src/weather/operations/location_config_refresh.py` |

Repo-wide counts used (Grep, `src/weather` only): `write_json_atomic(` 86 call sites / 52 files; `.write_text(json.dumps` 162 sites / 144 files; `fsync` 85 occurrences / 52 files; `os.replace|fsync|NamedTemporaryFile|msvcrt|portalocker` 123 / 62 files. No use of `msvcrt.locking` or `portalocker` anywhere: every lock in the project is an `O_CREAT|O_EXCL` lock file.

---

## 2. Ranking of evidence files by irreplaceability x exposure

Irreplaceability: can the bytes be re-obtained after loss? Exposure: how weak is the write path and how often is it exercised. Off-host mirror paused since 2026-08-12 (owner decision, `known_accepted`), so for every row below there is exactly one copy.

| Rank | Evidence | Irreplaceable? | Write path | Exposure | Net |
| --- | --- | --- | --- | --- | --- |
| 1 | CLOB full-depth book tape `snapshots/<event>/order_books.jsonl`, `market_ws.jsonl`, `clob_capture_status.jsonl` | Yes (live book state cannot be backfilled) | `open("a")`, no fsync, no torn-tail guard, 50 ms lock then DROP (`market_microstructure_capture.py:783-847`); later gzip-then-delete without fsync (`clob_raw_tape_tiering.py:221-249,321`) | Highest volume writer on the host; hard-killed by supervisor on rolls; strict reader fails whole day on one bad line | **Highest** |
| 2 | Canonical snapshot JSONL (`snapshots.jsonl`, `replay_inputs.jsonl`, `source_status.jsonl`, `features/components/forecasts/variant_predictions/explanations .jsonl`) | Yes (classified CANONICAL_EVIDENCE, `storage_classes.py:144-159`) | streamed token-by-token, no fsync, no torn-tail guard (`snapshot_store.py:2547-2558`, called at 892, 936, 949, 964, 984, 994, 1002, 1011) | 12 markets x every 10 min; a transaction can last minutes (`snapshot_store.py:3099-3103`) | **High** |
| 3 | `data/backtest/market_day_labels.csv` | Derived from ledger in principle, but NO rebuild-from-ledger tool exists; today it can only be rebuilt by re-finalizing local snapshot folders | whole-file `open("w")` rewrite, 3 unlocked read-modify-write copies | Rewritten every chain run and every backfill; has been truncated before | **High** |
| 4 | Settlement ledgers `data/settlements/<market>/ledger.jsonl` | Yes for history (authority for labels) | lock + per-slug hash chain + fsynced append (good) but O(n) read per upsert and unbounded growth | ~100 appends per market per chain run | Medium (design cost, not loss) |
| 5 | Execution tape `execution_tape/{trades,dedupe,gaps,seeds}-NNNNN.jsonl` | Yes ("cannot be backfilled") | held-open handle, fsync per row, strict validation at open | Best writer in the repo; weakness is availability (fail-closed crash), not loss | Medium |
| 6 | `snapshots_long.csv` and other `*_long.csv` | Projection of #2 (but it is what settlement and evaluation actually read) | fsynced append, atomic fsynced schema migration (`snapshot_store.py:2489-2545`) | Good | Low-Medium |
| 7 | Forecast / observation payload CAS blobs | Yes | staged file, fsync, hard-link publish, re-hash verify (`snapshot_store.py:1344-1438`, `forecast_payload_cas.py:115-157`) | Excellent | Low |
| 8 | WU history store (raw JSON, partitions, `daily_summary.csv`, manifest) | Re-fetchable while WU retains history | tmp + replace with 8x PermissionError retry, manifest with sha256 + row counts (`wu_history.py:57-67,425-486,526-537`); no fsync; fixed `.tmp` name | Good | Low |
| 9 | Status JSONs, reports | Regenerable | mix of `write_json_atomic` (no fsync) and 162 in-place `write_text(json.dumps(...))` | Cosmetic, except where a status file is state (see F7) | Low |

---

## 3. Findings

Severity scale per the audit brief. `basis` and `known_status` are stated for each.

### F1 (HIGH, known_open) - The labels CSV is rewritten whole, in place, from "whatever folders were discovered", by three unlocked copies of the same routine, with nothing that detects shrinkage

Evidence (all read):
- `settlement_ledger.py:1326-1334` `write_labels_csv`: `path.open("w")` then writes only the labels handed in. No temp file, no replace, no fsync, no lock.
- `settlement_ledger.py:1483-1490`: `merge_labels_csv` is used ONLY when a folder failed; the success path at :1489 is `write_labels_csv(labels_csv, labels)`, i.e. replace the file with exactly the folders passed to this run.
- `market_day_labels.py:36-47, 74` and `daily_refresh_cli.py:111`: both CLIs accept a positional `folders` subset. A subset invocation with zero failures therefore truncates the production CSV to that subset. This exact trap is recorded in `docs/operations/FINALIZE_LOST_A_SETTLEMENT_DAY_2026-08-11.md:43-51` ("would have truncated 789 rows to 12") but the code is still unguarded: the fix added merge-on-failure, not merge-on-subset.
- Three independent read-modify-write implementations, none locked, all ending in an in-place `open("w")`: `settlement_ledger.py:1337-1354`, `daily_refresh_trading_steps.py:631-655`, `settled_day_freshness.py:168-177` (via :75-88). A reader-side failure or a concurrent half-written file yields fewer `existing` rows, which are then written back as the new truth.
- `settled_days.py:68-96` `discover_settled_folders` decides membership with a plain `(child / required_file).exists()` (:93). It does not consult the cold-archive markers that `cold_archive_locations.resolve_local_path` (:236-247) exists to honour. Any market-day whose `snapshots_long.csv` stops being local silently leaves discovery, and the next successful full run silently deletes its row from the CSV. (Forward risk, `inferred`: I verified the mechanism, not that storage recovery currently selects `snapshots_long.csv`; `closed_day_projection_registry.py:35-46` marks that family `eligible=False` for in-place gzip tiering today.)
- Nothing detects the loss. `settlement_source_audit.py:295-306` unions ledger and CSV slugs, so a truncated CSV is silently back-filled from the ledger inside the audit and the audit still passes; it also lets a non-empty CSV value override the ledger value (:302-304), the reverse of the project's stated authority order. Grep for any row-count / shrink guard on the labels CSV in `src/weather` found none (grep-level, not a trace).
- No tool rebuilds the CSV from the ledgers (grep for such a function in `src/weather` found none). Recovery today means re-finalizing local snapshot folders, which stops working the day those folders are archived off the host.

Impact: the file every evaluation, streak and promotion count reads can lose history in four ways (crash or guard-kill mid-write, disk-full after the `"w"` truncate, subset invocation, folder leaving local disk) and nothing will say so. `csv.DictReader` reads a truncated file without error.

Recommendation: one shared `write_labels_csv` that (a) always merges by `event_slug` unless an explicit `--replace-all` is passed, (b) writes temp + fsync + `os.replace` with PermissionError retry, (c) refuses to publish a file with fewer slugs than the one it replaces unless told to, (d) is rebuildable from `ledger.jsonl` alone. Delete the two private copies.

### F2 (HIGH, known_open) - Settlement-ledger idempotency is defeated by a timestamp inside the hashed payload, so every chain run appends a new ~10 KB revision for every historical market-day and re-reads the whole ledger each time

Evidence:
- `settlement_ledger.py:1460` sets `finalized_at = datetime.now(...)` once per run; it flows into the label at :1321 (`finalized_at_utc`) and :1234 (`evidence.five_time_provenance.label_finalized_at`).
- `_label_payload` (:849-854) excludes only `LEDGER_REVISION_METADATA_FIELDS` (:825-835); `finalized_at_utc` and `evidence` are hashed. So `record_hash` (:1043) never equals the previous `label_hash` on a re-run and the idempotent early-return at :1044-1049 is unreachable in production.
- The only idempotency test pins `finalized_at_utc` to a constant (`tests/backtesting/test_settlement_ledger.py:28, 69-79`), so it passes while production never takes that branch.
- The scheduled chain passes no folders (`scripts/ops/daily_refresh_contract.ps1:87-114`), so `run_market_day_labels_finalize` (`daily_refresh_source_steps.py:658`) finalizes every discovered settled folder, every day. `settlement_backfill_one.ps1:175-181` does the same for a one-date backfill.
- Each upsert reads and parses the entire market ledger (`settlement_ledger.py:1032`) and re-verifies the slug chain (:1034) before appending one line. Cost per run is (folders per market) x (ledger size) x 12, and ledger size grows by (folders) rows per run: quadratic in days.
- `revision_changes` (:965-976) diffs top-level fields, and `evidence` always differs, so every revision row embeds the full old and new `evidence` dicts.
- `doc_claimed`: `FINALIZE_LOST_A_SETTLEMENT_DAY_2026-08-11.md:79-85` measured Austin's ledger at 19.5 MB with ~66 folders/run and a July-12 label already at `revision_number = 28`, and filed it as "an open question, not a finding". It is not in `active-backlog.md` (grep: no match). That document attributes the churn to "evidence churns"; the deterministic cause is the timestamp.
- Side note for the retraction list: the same document says `upsert_ledger_record` "rewrites the entire ledger on every single upsert", and the docstring at `settlement_ledger.py:1384-1387` repeats it. The current code appends (`:1073-1076`); it re-READS the whole ledger, it does not rewrite it. I did not verify what the code did on 08-11.

Consequences:
1. The finalize step's cost grows without bound on a 16 GB host with a 70% commit gate. I could not measure the current ledger sizes or the step duration (no `data/` access); the lead should read `data/settlements/*/ledger.jsonl` sizes and the `market_day_labels_finalize` duration in `daily_refresh_status.json`.
2. "Frozen settlement labels" are not frozen. Every historical label is recomputed daily from whatever `daily_summary.csv`, `snapshots_long.csv` and Gamma response exist that day, and `current_ledger_label` (:892-902) returns the newest revision. There is no guard against a downgrade (for example a settled `daily_summary` label being superseded by `snapshot_high` or `none` because an input went missing). History is preserved, but the current view moves silently.
3. `ledger_grew` in `settlement_backfill_one.ps1:259-260` is uninformative: any finalize pass grows every ledger.

Recommendation: exclude `finalized_at_utc` and `evidence.five_time_provenance.label_finalized_at` from the label hash (or only append when a settlement-relevant field changes); finalize only folders without a current countable label plus an explicit re-check window; index the ledger tail instead of re-parsing it per upsert; refuse, or at least alert on, a revision that downgrades `settlement_source`.

### F3 (MEDIUM, new) - Canonical JSONL evidence is the non-durable, tear-prone side of every snapshot; the fsync went to the projections

Evidence:
- `storage_classes.py:144-159` classifies `snapshots/*/snapshots*.jsonl`, `features*.jsonl`, `components*.jsonl`, `forecasts*.jsonl`, `source_status*.jsonl`, `snapshot_explanations.jsonl`, `variant_predictions.jsonl` as CANONICAL_EVIDENCE ("cannot be safely rebuilt after the fact", :46-52) and `snapshots/*/snapshots*.csv` as analysis projection (:406-419). `event_day_manifest.py:71-126` requires the `.jsonl` members as the canonical evidence of the `snapshots`, `source_status` and `replay_inputs` families.
- `snapshot_store.py:2489-2545` `append_csv` flushes and fsyncs every append. `snapshot_store.py:2547-2558` `append_jsonl` fsyncs only when `durable=True`, and the only callers that pass it are the forecast/observation payload manifests (:1911, :2008, :2789). `snapshots.jsonl` (:892), `features.jsonl` (:936), `components.jsonl` (:949), `snapshot_explanations.jsonl` (:964), `forecasts.jsonl` (:984), `source_status.jsonl` (:994), `replay_inputs.jsonl` (:1002, :3058) and `variant_predictions.jsonl` (:1011) are not fsynced.
- The JSONL record is streamed through `json.JSONEncoder.iterencode` token by token into a buffered text handle (`snapshot_store.py:133-153`, :2549-2555), so one record reaches the OS as many separate writes. The file's own comment says a replay payload "can keep a healthy writer inside one snapshot transaction for more than five minutes" (:3099-3103). Anything that stops the process inside that window leaves a torn record.
- Such stops are routine here: the supervisor's relaunch path "hard-kills the loop" (`supervisor.py:490`, `terminate_managed_process` :1487-1513), and the brief records 3 unexpected shutdowns in 90 days.
- No append path checks that the file ends in `\n` before appending (grep for torn/trailing-newline handling in `src/weather/collection` found only an unrelated lock comment). After a torn tail the next record is concatenated onto the fragment, so TWO records become unparseable.
- Readers then diverge: `snapshot_store.read_jsonl` (:2598-2614), `io.read_jsonl` (`io.py:690-705`, default `skip_invalid=True`) and `settlement_ledger.read_jsonl` (:800-814) drop invalid lines silently with no count; `event_day_manifest._inspect_file` (:394-412) returns BLOCK for the whole file on the first invalid line, which blocks that day's manifest and therefore its archive/tiering.
- Same pattern in the CLOB store: `market_microstructure_capture.py:806-828` appends `order_books.jsonl`, `market_ws.jsonl`, `clob_capture_status.jsonl` and the CSVs with no fsync and no tail guard, and `order_book_tape.iter_raw_jsonl_level_rows` (:78-92) raises `ValueError` on the first invalid line, making the whole day's canonical tape unreadable through the canonical reader until hand-repaired.

Basis: mechanism `verified_in_code`; frequency of actual torn tails `inferred` (I could not inspect tapes). `io.read_jsonl_tail_with_diagnostics` (`io.py:994-1063`) and `supervisor.jsonl_integrity` (:255-284) show the project already knows the failure shape; they are applied to loop logs and bounded tails, not to the evidence writers.

Recommendation: a single evidence-append helper: serialize the record fully in memory, heal an unterminated tail by writing `\n` first (and log it), emit the record with one `os.write`, fsync for CANONICAL_EVIDENCE families. Make lenient readers count and report skipped lines. Add a torn-tail test for each writer.

### F4 (MEDIUM, new) - CLOB tiering deletes the only uncompressed canonical tape after verifying a gzip that was never fsynced

Evidence:
- `clob_raw_tape_tiering.py:221-249`: gzip to `<name>.gz.tmp`, re-read it to compare sha256 and line count (:235-237), `tmp_path.replace(gzip_path)` (:238). No `flush`/`os.fsync` anywhere in the module (the repo-wide fsync grep lists neither `clob_raw_tape_tiering.py` nor `clob_order_book_tiering.py`). `apply_tiering` then `source.unlink()` (:321). `clob_order_book_tiering.py:265-280, 350` is the same shape.
- The verification read is served from the page cache, so it proves the bytes handed to the OS, not the bytes on disk. NTFS journals the rename and the delete; it does not journal file data. A power loss between the unlink and the lazy write-back leaves a journaled delete of the source next to a gzip whose data never landed.
- Both are scheduled on this host and delete by default: `scripts/ops/clob_raw_tape_tiering_run.ps1:25-27, 90`, `scripts/ops/clob_tiering_run.ps1:97`.
- The project's newer tiering code does this correctly: `closed_day_projection_tiering.py:855-857` (flush + fsync before the replace at :905), :1563-1566, :1723-1726.

Impact: low probability per event (the vulnerable window is the write-back lag of the most recently tiered files during a 30-40 minute nightly run), but the loss is the canonical full-depth book for those market-days, with no second copy (mirror paused) and unexpected shutdowns a recorded recurring event on this host.

Recommendation: fsync the gzip handle before the replace, and either fsync the directory or defer the unlink to the next run after re-verifying the gzip from disk. Reuse the `closed_day_projection_tiering` helper rather than keeping three compress-verify-delete implementations.

### F5 (MEDIUM, new) - Execution-tape capture is fail-closed with no repair path and a fleet-wide blast radius; its seed file is rewritten in place underneath it

Evidence:
- `execution_tape_store.py:438-468`: opening a `RotatingJsonlWriter` raises `ExecutionTapeError` on any unterminated line (:458-459), invalid row (:460-463), non-contiguous part set (:445-446) or oversize part (:450-453). Each `MarketDayTapeStore` opens four such writers (:566-569).
- `execution_tape_capture.py:569-572`: `coordinator.replace_seeds(seeds, now=now)` is outside the `try` that guards seed loading (:554-567). An `ExecutionTapeError` from any one market-day's store leaves the `while` loop, runs `finally`, and ends the process. On restart the same file raises again. One bad line in one of 4 tapes of one active market-day therefore keeps execution capture down for ALL market-days until a human repairs the file. Grep for unterminated/quarantine/repair/truncate in `execution_tape*.py` finds no recovery path.
- The store's own writes make a torn tail unlikely (single `write` + flush + fsync of a < 1 MB line, :498-500), so this is about blast radius and absence of a runbook, not about a likely tear. The project's own classification says this data "cannot be backfilled".
- The seed source is rewritten in place: `location_config_refresh.py:63-67, 389-390` does `path.write_text(json.dumps(...))` on `config/locations.json` and the 1.7 MB `config/location_market_events.json`. The capture loop re-reads that file every seed check (`execution_tape_capture.py:555-560`); a parse failure takes the branch at :562-567, which stops the whole websocket fleet and marks every store disconnected. A reader that lands inside the write window, or a write that dies after the `"w"` truncate (disk full, kill), darkens execution capture until the next good refresh.
- Lock detail: `io.acquire_writer_lock` with `attempts=1` (`execution_tape_store.py:1110-1124`) clears a stale lock and then returns `None` anyway, because the `continue` at `io.py:669` consumes the only iteration. The coordinator heartbeats its lock (`execution_tape_store.py:1585-1589`), so after an unclean stop every restart inside 300 s reports busy, the first restart after 300 s clears the lock and still reports busy, and only the next one succeeds. The supervisor's exact-instance lock cleanup (`supervisor.py:1400-1449`) mitigates this for supervised loops; I did not verify that it covers this process.

Recommendation: quarantine-and-continue for a bad market-day store (rename the damaged part, open a gap row, keep the other market-days connected); wrap `replace_seeds` per store; write both config files with temp + fsync + replace; let `acquire_writer_lock` retry once after clearing a stale lock regardless of `attempts`.

### F6 (MEDIUM, known_open) - A reader holding the raw-tape guard makes the book writer discard already-fetched, irreplaceable order books after about 50 ms

Evidence:
- `market_microstructure_capture.py:783-804`: `raw_tape_guard` = `acquire_writer_lock(attempts=3, sleep_seconds=0.025)` then raises `RawTapeWriterBusy`.
- Writer: :1115-1122 takes the guard to append tokens and books that are already in memory. On `RawTapeWriterBusy` the result is a BLOCK row with `raw_tape_write_blocked` (:1575-1583); the fetched books are not retried or queued.
- The same guard is held by a READER for the duration of a whole-day derived-feature rebuild: :1176-1181 and :1393-1398 wrap `write_clob_feature_rows`, which rebuilds the day's features from the folder's tapes and rewrites two files in place (`market_microstructure_features.py:551-565`). It is also taken by `closed_day_projection_tiering.py:336-342` and, per the project's own handoff, by the maker producer once per routed message.
- `doc_claimed`: `docs/roadmap/workstation-handoff-2026-09-18a-narrow-the-maker-producer.md:22` names this exact lock hazard; an 08-06 run recorded zero occurrences. So it is known and currently measured at zero on the workstation, not on production under end-of-day tape sizes.

Recommendation: the irreplaceable writer should never lose to a rebuildable reader. Give readers a snapshot (size-bounded read up to a recorded offset) instead of the writer's lock, or let the writer wait a bounded few seconds and spool to a sidecar on timeout rather than dropping.

### F7 (MEDIUM, new) - The shared "atomic" helpers give three different guarantees, none durable, and twice as many JSON writes bypass them

Evidence (`io.py`):
- `write_json_atomic` (:353-377): retries `PermissionError` on replace 20 times (good) but never fsyncs, and has no cleanup: if `tmp.write_text` raises (disk full) or the retries are exhausted, the `.<pid>.<ns>.tmp` file is left behind. At disk-full this litters `data/` with partial temp files on every status write, exactly when space matters. `write_json_streaming_atomic` (:441-472) does clean up.
- `write_text_atomic` (:475-492) and `write_csv_rows_atomic` (:1103-1124): cleanup but NO PermissionError retry, so a concurrent reader without delete-sharing (the 2026-08-11 incident was exactly a diagnostic reader colliding with a writer) fails the write outright. No fsync.
- `write_csv_rows` (:1091-1100) is a plain in-place `open("w")` and is used for durable tapes: `market_microstructure_capture.py:537, 646`, `market_making_run_support.py`, `taker_bot_cli.py`, `market_making_tape_encoding.py`.
- `append_jsonl` / `append_csv_rows` (:596-605, :1127-1144): no fsync, no lock, no tail guard.
- 162 `.write_text(json.dumps(...))` sites in 144 files vs 86 `write_json_atomic` call sites. Most are regenerable reports, but they include live inputs and state: `location_config_refresh.py:66` (F5), `settlement_ledger.py:566` (`resolution_specs.json`) and :1102 (per-folder `settlement.json`, which `settled_day_freshness.label_source_for` :478-481 will use as a label source), `forecast_tracker.py`, `forecast_archive.py`, several `sources/*` caches.
- The disk is reported at about 4 days of headroom. In-place `open("w")` truncates the good copy before it discovers there is no room for the new one; temp + replace would leave the old copy intact.

Recommendation: one durable primitive (temp in same directory, flush, fsync, replace with PermissionError retry, cleanup in `finally`) used by all four helpers; a lint/ratchet test that forbids new `open("w")` / `write_text` on paths under `data/` and `config/` outside that module, in the style of the existing PowerShell parse ratchet.

### F8 (LOW-MEDIUM, new) - "could not read" is treated as "empty" and then written back

Evidence:
- `io.read_csv_rows_with_diagnostics` returns `[]` on `OSError` / `csv.Error` (`io.py:774-776`) and `read_csv_rows` discards the diagnostics (:801-803).
- `market_microstructure_capture._upsert_price_history_rows` (:523-538) reads existing rows with `read_csv_rows`, merges the incoming rows and rewrites the file in place with `write_csv_rows`. A transient sharing violation or a malformed row therefore replaces the day's accumulated `price_history.csv` with only the rows fetched in this cycle. (Partly recoverable: raw responses are kept in a content-addressed sidecar, :849-851.)
- Same shape: `io.read_json` returns `default` on `OSError`/`JSONDecodeError` (:127-134); any read-modify-write state file built on `read_json(path, default={})` resets on one bad read. The execution tape avoids this correctly by rebuilding counters from the tapes (`execution_tape_store.py:622-691`); I did not enumerate other users.
- The three labels-CSV mergers (F1) have the milder version: an exception propagates on read failure, but a half-written file reads as a short file.

Recommendation: read-modify-write helpers must distinguish missing from unreadable and refuse to write when the read was not clean.

### F9 (LOW, new) - What would detect silent loss after the fact, and where there is nothing

Present and good: per-slug hash chain with supersession links on the settlement ledger (`settlement_ledger.py:905-962`), checked before every append (:1034-1039) and every read through `ledger_label_for_slug` (:1084-1097); full `previous_entry_sha256` chain with post-append verification on the production evidence ledger (`production_evidence_ledgers.py:218-329`); sha256 + row counts in the WU manifest (`wu_history.py:526-537`); self-verifying CAS blobs; event-day manifests with sha256 and row counts and a full-audit recount (`event_day_manifest.py:1590, 1682-1689`); sha256 + line-count proof before tiering deletes.

Gaps:
- The ledger chain is per slug. Deleting the last N lines of a ledger, or every line for one slug, verifies PASS. There is no per-file running hash, row count or external anchor.
- `settled_day_freshness.ledger_by_slug` (:91-98) and `settlement_backfill_one.ps1:209-238` take the last row in file order rather than the highest `revision_number`, bypassing `current_ledger_label` and the chain check.
- The labels CSV has no manifest, no row count, no shrink guard (F1).
- Event-day manifests hash what is present at seal time; they cannot see a record that was torn or never flushed before sealing. There is no parity check between the snapshot ids in `snapshots_long.csv` and those in `snapshots.jsonl` (grep of `event_day_manifest.py`; grep-level).
- `csv.DictReader` based inspection (`event_day_manifest.py:421-436`) is not strict, so a torn-and-concatenated CSV row passes validation.
- With the mirror paused there is no second copy to diff against (`known_accepted`; recorded once, here).

### F10 (LOW, new) - The live capture path re-reads an entire day's `forecasts_long.csv` into memory on every snapshot

Evidence: `snapshot_store.py:42, 983` calls `forecast_archive.append_rows`, which calls `migrate_csv_schema` first (`forecast_archive.py:455-466`), which does `rows = list(reader)` over the whole existing file before it even compares the header (:382-391), and on a header mismatch rewrites the file in place with `write_rows` (:446-452). `snapshot_store.append_csv` was deliberately rewritten to avoid this ("Never materialize a live day-wide CSV in memory. Some retained projections are already large enough to hit the isolated capture tree cap", :2505-2508); this sibling path was missed. Twelve markets, every ten minutes, growing through the day, on the 16 GB host.

Recommendation: read only the header line; migrate with the streaming temp + fsync + replace routine already in `append_csv`.

---

## 4. Smaller observations (not in the structured top 10)

- Three lock implementations with different semantics: `io.acquire_writer_lock` (mtime staleness, no PID check, catches only `FileNotFoundError` on stale unlink, `io.py:645-672`), `snapshot_store.acquire_lock` (PID liveness + 1 h cap, same narrow except, :3061-3107) and `settlement_ledger._acquire_ledger_lock` (mtime staleness, catches `OSError`, :989-1011). The 2026-08-11 fix for "Windows raises PermissionError when the holder still has the lock open" was applied to the ledger lock only. In the other two the same condition escapes as an uncaught `PermissionError`. On Windows this is what actually preserves single-writer safety (an open lock file cannot be unlinked); on POSIX the mtime-only steal in `io.acquire_writer_lock` would be a split-brain bug, relevant if the workstation or CI ever runs writers under WSL/Linux.
- `_acquire_ledger_lock` waits at most 200 x 10 ms = 2 s (:989, :1010) while the holder parses a multi-MB ledger (F2). `TimeoutError` is an `OSError`, so `_finalize_folder_with_retry` retries it 3 times (:1391-1398); as ledgers grow this becomes a spurious-failure source.
- `wu_history.py:436, 481, 718` use a fixed `<name>.tmp`, so two concurrent builders of the same station would interleave into one temp file. The chain lock makes this unlikely.
- A snapshot is about 13 independent appends (`snapshot_store.py:886-1011`) with no transaction marker. The long CSV goes first and is fsynced, so `is_due` will not retry a half-written snapshot; sidecars for that snapshot id are simply absent. Backfill helpers exist for features/components/explanations (:2654, :2801) but not for `replay_inputs.jsonl` or `source_status.jsonl`.
- `last_snapshot_time` (:1065-1081) scans the whole long CSV on every due check and would raise `csv.Error` out of `maybe_write` if the tape contained a NUL run (a typical NTFS post-crash artifact on older Python versions), stopping that market's capture for the rest of the day. `inferred`.
- `append_mismatch_alert` (`settlement_ledger.py:1105-1122`) appends outside the ledger lock without fsync. Low value.
- PowerShell wrappers write status with `Set-Content` / `Out-File` / `Add-Content` (35 sites in 20 scripts). Operator cache; not traced.

---

## 5. Strengths (genuine)

1. Content-addressed payload stores are textbook: exclusive staging file, streamed hashing, fsync, hard-link publish so no reader can observe a partial blob, then size and re-hash verification of the published path (`src/weather/collection/snapshot_store.py:1344-1438`, `src/weather/collection/forecast_payload_cas.py:115-157`).
2. The execution tape store: held-open handles, flush + fsync per row, bounded immutable parts, counters rebuilt from the physical tapes rather than trusted from `status.json`, explicit gap accounting including unclean-restart recovery, and an honest refusal to dedupe on an identifier the feed does not guarantee (`src/weather/market/execution_tape_store.py:404-545, 622-728`).
3. The settlement ledger moved to append-only superseding revisions with a per-slug hash chain, verification before extend and before read, a lock, and an fsynced append; the 2026-08-11 incident produced per-folder isolation, merge-on-failure and an incident write-up that names its own unknowns (`src/weather/backtesting/settlement_ledger.py:905-1081, 1436-1490`).
4. Verify-before-delete is a consistent habit in storage code: sha256 + line count before any tiering delete, writer-lock and quiet-period rechecks at apply time, exact-path deletion only, cleanup manifests (`src/weather/operations/clob_raw_tape_tiering.py:279-329`, `src/weather/operations/closed_day_projection_tiering.py:855-905, 1288-1290`), and `resolve_local_path` raising `ArchivedInputRequired` rather than letting an archived input look absent (`src/weather/cold_archive_locations.py:236-247`).
5. Bounded, stability-checked tail readers that refuse an incomplete final record and detect concurrent modification (`src/weather/io.py:878-1063`), the streaming schema migration in `snapshot_store.append_csv` (:2489-2545), and lock ownership by PID plus process creation time with exact-instance proof before the supervisor clears a lock (`src/weather/operations/process_lock_identity.py`, `src/weather/operations/supervisor.py:1400-1449`).

---

## 6. What I could not cover

- Any on-disk state: ledger sizes and revision counts, whether torn lines exist in any tape today, labels CSV row count vs ledger slug count, stray `*.tmp` litter, stale lock files. All need a bounded, off-hours read of specific files by someone authorised for `data/`.
- The cold-archive pipeline end to end (`production_cold_archive_*`, `verified_cold_archive.py`, `bulk_cold_archive_crypt.py`, `workstation_cold_archive_*`): I only confirmed it uses fsync + replace + sha256. Presumably the storage dimension covers it.
- Market-making and taker run tapes (`mm_exchange.py`, `market_making_run*.py`, `taker_bot_*`), `triggered_snapshot_queue.py`, `replay_cache*`, model/release artifact writers (`release_manifest.py`, `release_promotion.py`, `base_retrain.py`).
- `execution_tape_store.py:1338-1569` and `execution_tape_capture.py` outside :525-595.
- The PowerShell writers and the one-shot task wrappers.
- Whether the supervisor quiesces a loop before the hard kill (I found the kill path and the exact-instance checks, not a write-quiescence step).
- Python version on the host (affects NUL handling in `csv`).

## 7. Open questions for the owner / lead auditor

1. How large are `data/settlements/*/ledger.jsonl` today and how long does `market_day_labels_finalize` take? If F2 is right, size should be roughly 10 KB x sum over successful chain days of folders-per-market.
2. Does `market_day_labels.csv` currently contain every slug present in the twelve ledgers? That single comparison tests F1.
3. Has storage recovery removed, or is it planned to remove, `snapshots_long.csv` from any closed market-day folder? If yes, F1's discovery path becomes an active row-deleter on the next green chain run.
4. Does any evidence tape currently fail `supervisor.jsonl_integrity`? A bounded check of the most recent closed day per market would size F3.
5. Is the execution-tape capture process under the supervisor's lock-cleanup path?
