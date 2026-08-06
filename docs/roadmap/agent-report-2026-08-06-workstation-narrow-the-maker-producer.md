# Workstation report 2026-08-06 — narrow the maker producer

## Verdict

**NO-GO: the authoritative soak status is FAIL. Do not register or start
`WeatherMakerExecutionCapture`.**

The held full-payload producer remains a **NO-GO**. This branch implements the
execution-only replacement specified by the accepted `-09-17a` measurement,
and the narrowed resource/lock contract itself passed with wide margin:
11.34 MiB/day, 45.91 MiB peak RSS, 1.79% combined CPU share, no
`RawTapeWriterBusy`, and no book-writer error. However, a remote WebSocket loss
created a 2.165-second gap at 00:08:24 ET. No single complete bound receipt
therefore covers the full 00:00–00:30 settlement interval, and the deliberately
conservative harness returned one hard failure:
`settlement_period_not_continuously_covered`.

This does not falsify the execution-only disk sizing or dedicated-lock safety.
It does falsify the stronger registration-clearance claim made by this mission:
the run cannot be called PASS and cannot start the MM decision clock. Per the
handoff's fail-closed instruction, this report records the failure and stops
before production adoption.

Nothing in this mission was registered, scheduled, started in production,
written under `data/`, promoted, or traded. The only public-feed writes are
isolated evidence beneath `scratch/runs/` in this worktree.

## Branch and carried dependency

The exact branch is
`codex/workstation-narrow-the-maker-producer-2026-09-18a`. It was cut from the
then-refreshed `origin/master @ 2d0f7f1493b6fd8231ed9012ff7bde75b5c9dc0a`
and carries
`origin/codex/workstation-make-mm-days-countable-2026-09-11a @ 14dd1e84`
through merge commit `ff7d9ceb`. Before push it will also merge the latest
refreshed `origin/master`; that refresh is branch maintenance, not integration
of this branch into `master`.

## P1 — the three registration contracts

The command line now advertises and accepts exactly the three required values:

```text
--retention-mode executions-only
--lock-scope execution-tape
--host-policy-mode pause-training-window
```

There is no registered-command route to book or price-change retention. The
producer subscribes the full active fleet on one public WebSocket but filters
individual mixed-payload members and retains only `event_type =
last_trade_price`.

Raw execution append, canonical execution append, and receipt prefix binding
are serialized with the event-local `root/mm_execution_tape` anchor. The
producer never enters `raw_tape_guard` and therefore never takes the CLOB
writer's `clob_raw_tape` anchor.

The loop refuses to connect from 01:00 through the 04:15
`WeatherTrainingWindow` restore in `America/Toronto`, disconnects at the
boundary, and carries the planned gap into the first receipt after restore.
The 18:00–00:30 protected interval permits only the intended small append-only
execution evidence; the producer performs no bulk work there.

## P2 — dedicated rows, receipts, and countability

The dedicated raw JSONL and canonical CSV rows retain the source integer epoch
millisecond timestamp and normalize it to millisecond-precision UTC. They also
retain transaction hash, session id, condition/token identity, price, size,
side, and a monotonically increasing local connection-message sequence. Both
representations explicitly label that sequence as connection-local and label
exchange book alignment as unavailable from the public feed.

Each per-event receipt is written under the same execution-only guard and
binds:

- the exact subscribed asset list, count, and hash;
- that event's observed asset list, count, hash, and market-data message count;
- the local connection-message sequence interval;
- the exact execution count, including zero; and
- raw and canonical filename, prefix byte count, and prefix SHA-256.

Coverage begins only after every subscribed asset in every event has appeared
in public market data. A frame for one event therefore cannot make another
event's exact-zero receipt complete. Silent, heartbeat-only, malformed,
partially observed, or disconnected sessions fail closed.

`build_execution_tape_inventory` accepts absent raw/canonical files only for a
complete, self-hashed, full-readiness receipt whose exact execution count is
zero and whose two absent prefixes bind zero bytes and SHA-256(empty). Any
positive count requires matching raw and canonical prefixes. It validates
source payload semantics, canonical projection, event/asset/session identity,
local sequence scope and interval, and the scorer-required strict-through
fields. A fill must cite both dedicated representations and an audit key whose
bound execution matches the fill's token, condition, side, price, size,
transaction hash, exchange time, and raw hash; it cannot borrow another valid
execution's key.

## Storage and registration surface

`mm_execution_tape.jsonl`, `mm_execution_tape.csv`, and
`mm_execution_tape_sessions.jsonl` are classified as permanent canonical maker
evidence. Event-day manifests list the family when present. Closed-day archive
planning treats it as raw-reference-only: it is not converted to Parquet,
deleted, or admitted to projection cleanup.

`scripts/ops/register_mm_execution_capture.ps1` is fail-closed on the deployed
module's `--help`, supplies all three exact arguments, requires enrichment to
be disabled, registers priority 6 / BelowNormal, and never invokes
`Start-ScheduledTask`. The accepted `-09-17a`
`scripts/ops/register_maker_tape.ps1` guard checks the same six help tokens, so
the narrowed module satisfies that future operator surface honestly. This
mission did not invoke either registration path.

## P3 — public settlement-crossing soak

| Measure | Result | Gate |
| --- | ---: | --- |
| Harness status | **FAIL** | requires no hard failures |
| Local interval | 2026-08-05 17:47:56.990944 through 2026-08-06 00:40:02.474316 ET | crosses protected and settlement windows |
| Wall time | 24,725.484 s (6 h 52 m 5.484 s) | long public soak |
| Fleet | 12 events / 264 assets | full built-in fleet |
| Public messages | 767,969 | retained only executions |
| Executions retained | 1,802 raw + 1,802 canonical | exact representation parity |
| Maker bytes | 3,401,643 B | measured delta |
| Projected daily maker bytes | 11,886,600.69 B / **11.33595 MiB** | PASS: <= 100 MiB/day |
| Peak RSS | 48,136,192 B / **45.90625 MiB** | PASS: <= 64 MiB |
| Combined CPU | 441.594 s / **1.78599% of one core** | producer + sampler + probe |
| Unplanned reconnects | **5** | report; four remote losses plus one incomplete final subscription |
| `RawTapeWriterBusy` | **0** | PASS: none from any writer |
| Book-writer errors | **0** | PASS: none |
| Book-probe writes | **200,451** | all 12 events |
| Worst per-event book gap | **3.490662 s** | PASS: <= 10 s |
| Probe thread lifecycle | clean | PASS |
| Full 18:00–00:30 crossed | yes | PASS |
| Full 00:00–00:30 crossed | yes | PASS |
| Settlement continuously covered by one complete receipt | **no** | **FAIL** |
| Hard failures | `settlement_period_not_continuously_covered` | sole failure |

The authoritative run root is
`scratch/runs/mmexec-settlement-2026-08-05-final-1748`. The harness records its
PID, arguments, BelowNormal priority, source hashes, initial/final/delta maker
bytes, one-second RSS samples, conservative combined CPU time, connection
coverage intervals, and per-event book-writer liveness. The concurrent probe
uses the real `clob_raw_tape` guard and `write_books` path for every event while
the maker uses its dedicated lock.

The public connection established full-fleet readiness at 17:47:58.961552 ET.
Four remote connection losses ended otherwise observed intervals. The
settlement-breaking loss ended coverage at 00:08:24.636461; full readiness on
the replacement connection was restored at 00:08:26.801465, a measured gap of
2.165004 seconds. That replacement covered through 00:31:08.759549, but the two
intervals cannot be merged into continuous evidence. A fifth/final attempt did
not observe Toronto's complete subscription before the harness deadline. All
gaps and reasons are explicit in the 60 bound per-event receipts; they are not
silently treated as zero executions. Under the current deliberately fail-closed
contract, all five fleet sessions are INCOMPLETE, so this soak cannot certify a
countable maker day; the physical settlement gap itself occupied 0.1203% of the
half-hour.

The resource and incumbent-writer evidence is independently strong. The raw and
canonical execution files each contain exactly 1,802 rows. All 12 book probes
ran from before 18:00 through after 00:30, completed 200,451 guarded
`write_books` calls, stayed below the 10-second per-event cadence bound, and
shut down cleanly. RSS sampling produced 24,498 samples without a measurement
error. Neither producer nor book probe recorded `RawTapeWriterBusy`; stderr is
the empty file. An independent audit matched raw rows, canonical rows, result
count, and the sum of receipt counts at 1,802. It also validated all 60 receipt
self-hashes, every bound raw/canonical prefix hash, representation linkage, and
the required timestamp, transaction, session, and local-sequence semantics.

The sorted path/size/file-hash manifest for the complete 52-file, 41,612,767 B
scratch evidence tree hashes to
`61df87eae422cbb98d4e33888e6eae7691583a951d0795c08b55ae6c98cc279f`.
Family manifests hash to
`4e048a506922cb02e9f2fb7a59496b9ee657509846f25c04873d796ac401de20`
for raw executions,
`fa597632ac4bfd489ac7ce6c6715965b73721072a1cec672b5f1fe024b6abcc7`
for canonical executions,
`ddcc4fb6b7e305db6a953f6e17b02a327cac9d8a1e5ac1aa1539e4c97029318c`
for receipts, and
`d2fc47abfee19559dd1529ce6174ff0117d5dd4f2015e6ab848ff5f57df71796`
for book probes.

Top-level evidence hashes are:

| File | Bytes | SHA-256 |
| --- | ---: | --- |
| `launch_metadata.json` | 884 | `38f7259be9b32fe924986c782277c52cf9cca2198353036ec6c4fef38e1ba84f` |
| `soak_result.json` | 9,252 | `48968391770362dbd34b3315c60f7eb05e95a71343cd079fa4619c68e414aee3` |
| `stdout.log` | 9,252 | `48968391770362dbd34b3315c60f7eb05e95a71343cd079fa4619c68e414aee3` |
| `stderr.log` | 0 | `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855` |

The launch metadata binds PID 5524, the exact arguments, BelowNormal priority,
and these source hashes:

- harness: `929567dbec8b96f371b5cafc41a280a6660a7474bea32c50bc5c4114ef5cfdd8`;
- narrowed producer: `2271e97856d4af4424d405752dd5aead491046c36faa86f1f8d27c335613bd3a`;
- maker constants: `f923f1d4959fc89960cec2fa4c22c08890fa6bdb2065d323548039f55f2e8ee2`; and
- shared CLOB store/writer: `47e2487754563e925ad1ab4f467b57a962558c0ebfb4bb94da3f65ee4150173e`.

The detached launcher did not retain a queryable OS exit-code object after
process exit. The harness's explicit return contract is exit 1 for a FAIL, and
the byte-identical `stdout.log` and `soak_result.json` both record that FAIL.
This report does not convert the passed resource sub-gates into an overall GO.
A follow-up must decide whether an exactly recorded reconnect gap should merely
make overlapping decisions/quotes uncountable, or whether registration still
requires a fresh settlement half-hour with no reconnect. This failed mission
does neither and schedules nothing.

## P4 — retained import-closure roll analysis

| Changed path | Snapshot | CLOB | Observation | Enrichment | Roll verdict |
| --- | ---: | ---: | ---: | ---: | --- |
| `README.md` | no | no | no | no | roll-free |
| `docs/operations/HOST_LOAD_POLICY.md` | no | no | no | no | roll-free |
| `docs/operations/OPERATIONS_DESIGN.md` | no | no | no | no | roll-free |
| `docs/operations/closed-market-day-parquet-archive-contract.md` | no | no | no | no | roll-free |
| `docs/operations/data-storage-class-contract.md` | no | no | no | no | roll-free |
| `docs/roadmap/agent-report-2026-08-06-workstation-narrow-the-maker-producer.md` | no | no | no | no | roll-free |
| `scripts/ops/AGENTS.md` | no | no | no | no | roll-free |
| `scripts/ops/register_mm_execution_capture.ps1` | no | no | no | no | roll-free |
| `src/weather/market/market_making_model_variants.py` | no | no | no | no | roll-free |
| `src/weather/market/mm_day_countability.py` | no | no | no | no | roll-free |
| `src/weather/market/mm_execution_capture.py` | no | no | no | no | roll-free |
| `src/weather/market/mm_paper.py` | no | no | no | no | roll-free |
| `src/weather/market/mm_paper_aggregation.py` | no | no | no | no | roll-free |
| `src/weather/market/mm_paper_constants.py` | no | no | no | no | roll-free |
| `src/weather/market/mm_paper_reports.py` | no | no | no | no | roll-free |
| `src/weather/market/mm_paper_scoring.py` | no | no | no | no | roll-free |
| `src/weather/market/mm_reward_q_share.py` | no | no | no | no | roll-free |
| `src/weather/operations/closed_day_projection_registry.py` | no | no | no | no | roll-free |
| `src/weather/operations/closed_market_day_archive.py` | no | no | no | no | roll-free |
| `src/weather/operations/closed_market_day_archive_manifest_contract.py` | no | no | no | no | roll-free |
| `src/weather/operations/event_day_manifest.py` | no | no | no | no | roll-free |
| `src/weather/operations/storage_classes.py` | no | no | no | no | roll-free |
| `src/weather/reporting/market/trading_evidence.py` | no | no | no | no | roll-free |
| `src/weather/schema_registry_data.py` | **yes** | **yes** | **yes** | **yes** | **coordinated quiet-window roll** |
| `tests/market/test_mm_day_countability.py` | no | no | no | no | roll-free |
| `tests/market/test_mm_execution_capture.py` | no | no | no | no | roll-free |
| `tests/market/test_mm_paper.py` | no | no | no | no | roll-free |
| `tests/market/test_mm_paper_scoring.py` | no | no | no | no | roll-free |
| `tests/operations/test_closed_day_projection_tiering.py` | no | no | no | no | roll-free |
| `tests/operations/test_closed_market_day_archive.py` | no | no | no | no | roll-free |
| `tests/operations/test_event_day_archive_coverage.py` | no | no | no | no | roll-free |
| `tests/operations/test_event_day_manifest.py` | no | no | no | no | roll-free |
| `tests/operations/test_register_mm_execution_capture_script.py` | no | no | no | no | roll-free |
| `tests/operations/test_schema_registry.py` | no | no | no | no | roll-free |
| `tests/operations/test_storage_classes.py` | no | no | no | no | roll-free |
| `tests/reporting/test_trading_evidence.py` | no | no | no | no | roll-free |

The retained runtime identities are the evidence source, not source-pattern
globs:

- snapshot: commit `498757fbccd7`, 77 loaded source files;
- CLOB: commit `498757fbccd7`, 23 loaded source files;
- observation trigger: commit `498757fbccd7`, 85 loaded source files; and
- CLOB enrichment: commit `5c004c4554d8`, 21 loaded source files.

Only `src/weather/schema_registry_data.py` enters any retained closure, and it
enters all four. Its diff is purely additive: three new `SchemaSpec` entries,
with no existing entry changed. A single coordinated quiet-window adoption is
therefore unavoidable and expected. Roll the snapshot, CLOB, and observation
loops together after this branch lands; roll enrichment in the same window if
it is deployed/running, then start the maker producer only after all incumbent
loops are healthy. Every other changed file is roll-free for these retained
processes.

The downstream merge order remains:

```text
-09-18a -> -09-14a -> -09-17a (roll-free script/report)
  -> refreshed -09-01a alone -> -09-04a -> refreshed -09-12a + PIT seam
```

## Verification

Completed checks before the soak source was frozen:

- producer/countability/scoring focused suite: **45 passed**;
- maker paper/reporting regression suite: **98 passed** after the final
  adversarial audit-key test;
- storage/archive contract selection: **10 passed, 35 subtests passed**;
- archive-coverage/schema/registration-script selection: **15 passed**;
- `compileall -q app src tests`: **PASS**;
- PowerShell parser for `register_mm_execution_capture.ps1`: **PASS**;
- deployed module `--help`: all six required guard tokens present; and
- `git diff --check`: **PASS**.

The workstation's checked-in venv points to a removed Python 3.11 base
interpreter. Pure-Python checks used the bundled Python 3.12 runtime with the
repository's pure site packages; the archive selection used import-only
`pandas`/`pyarrow` stubs because the retained compiled wheels are CPython 3.11.
This does not replace the earlier canonical-environment runs: before that base
interpreter disappeared, the focused suite passed and the broader architecture
selection reached 21 passes, with only the then-untracked scheduler test and
the known CPython-wheel mismatch preventing a clean aggregate command. The
agent-doc audit also reports one unrelated pre-existing broken link in the
August 2 contract-repair report.

## Safety ledger

- production `data/` writes: **none**;
- scheduled-task registration, mutation, or start: **none**;
- mirror or `D:\weather-mirror` writes: **none**;
- credentials read: **none**;
- orders or trading calls: **none**;
- reserved confirmation dates declared, consumed, or read: **none**; and
- PR or integration merge: **none**.
