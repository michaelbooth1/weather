# Agent report — 2026-10-04 maker replay v2 W2 (exporter v0.2)

**Verdict: W2 is BUILT. S2 PASSES (MEASURED): the v0.2 night export of a full 170-condition fictional 88a capture day
peaked at 0.303 GiB (325,394,432 B) with one BLAS thread (at most 1.84 GiB with 32 threads), against the 2 GiB target. The frozen v0.1
exporter on the same day peaked at 11.50 GiB (12,349,501,440 B). The v0.2 output expands byte for byte to the v0.1 exporter's rows.
S1 from the real exporter is 1.09 GiB of v0.2 per date, over the 1 GiB rule. At real 88a cadence, descriptors and
outcome views are not rare, and books, views and descriptors are 89% of the bytes. Gate E2 is at risk; see the
findings.**

Branch `codex/mrv2-w2-20261004`, from the integration branch `codex/maker-replay-v2-build-20261003` at `ae08de20`
(W0/W1 merged). The work follows `docs/research/maker-replay-v2-engineering-plan-DRAFT.md` (W2, S1, S2), with
Session A's corrections from `docs/roadmap/agent-report-2026-10-03-mrv2-w0-w1.md`:

- coverage groups per subscription, not per socket;
- no reliance on duplicate elision;
- streaming sorted writes;
- validation by streaming re-read.

Fictional fixtures only. No file of the frozen exam tree `664c8943` was edited.

## What was built

- **`src/maker_core/replay/v2/writer.py`** (domain-neutral, new). `BundleWriter` takes the exporter's v0.1 rows in
  sequence order and holds nothing whole-output in memory.
  - **Sorted streams.** Each kind is one `<kind>.jsonl` stream in `(captured_at, sequence)` order. A kind that
    arrives in order is written straight to disk. The real exporter emits two kinds out of order: plugin inputs
    keep their original capture time, and ledger settlements keep their later record time. A kind that breaks
    order spills sorted runs of at most 32 MiB, merged once at the end. Duplicate keys refuse.
  - **Coverage.** Group membership is known only at the day's end, because a subscription can connect after a
    condition's first coverage row. Coverage therefore goes to a compact disk spool: one line per exporter run,
    plus a marker at each condition's first descriptor. `finish` replays the spool through W1's `Compactor` under
    the final groups, so the same-coverage refusal (`coverage_group_mismatch`) is W1's, unchanged.
  - **Validation** (`validate`) re-reads the written bundle through W1's two-pass stream reader and `expand`. The
    expanded rows must equal the pushed v0.1 rows in count, bytes and an order-independent SHA-256 sum, and the
    per-kind counts must match.
  - The writer also records `v01_equivalent.sha256`, the sequence-order SHA-256 of the rows. That is exactly the
    `events.jsonl` hash the v0.1 exporter writes from the same inputs, which gives E3 a direct comparator.
- **`src/weather/market/maker_replay_bundle_v02.py`** (new). It subclasses the frozen `Projection`, keeping the
  same admission, dedup and row, with rows pushed to the writer. The `export` loop is copied unchanged except for
  its sink.
  - **Coverage groups are subscriptions.** The frozen projection's `connections` map is replaced by a recording
    map, so every subscription each token joins is captured without copying `stream()`. Conditions whose tokens
    joined exactly the same subscriptions form a group. Conditions never subscribed share one always-unhealthy
    group.
  - No elision is added. Output is built in `<out>.partial` and renamed only after validation. A refusal removes
    the partial folder.
- **`src/weather/market/maker_replay_night_v02.py`** (new). This is night/calibration v0.2: the frozen night
  module's inventory, ledger, receipt and module-closure rules, with a streaming finalize. File hashes are
  streamed, and book-gap intervals come from recorded book minutes instead of a second whole-bundle load. The
  receipt adds bytes and records per kind (v0.2 and v0.1), the coverage-group count, `v01_equivalent`, the peak
  and the runtime. Ledgers are separate (`panel-v02-ledger.jsonl`, `calibration-v02-ledger.jsonl`). CLI:
  `python -B -m weather.market.maker_replay_night_v02 {module-hash|night|calibration}`.
- **Fixture and measurement tooling** (`tools/research/maker_replay_v2/`):
  - `capture170.py` writes the exporter's *input*. That is a fictional sealed 88a day for the 12 built-in markets,
    through the production `EvidenceStore`:
    - hourly segments;
    - one discovery and one reward capture a minute;
    - book captures of at most 50 bands with 8 levels a side;
    - per-subscription trade streams with outages, and per-event plugin sources.
  - `s2.py` holds S2 and the books sweep, dispatched by the admitted `run.py` (`s2-input`, `s2`, `books`).
- **Tests.**
  - `tests/maker_core/test_replay_v2_writer.py` (6) covers exact expansion, a refusal for a socket-level group
    and for a missing group, tamper detection by streaming validation, bounded spill and merge, straight-through
    in-order kinds, and duplicate-key refusal.
  - `tests/market/test_maker_replay_bundle_v02.py` (13) checks the v0.2 digest against the frozen v0.1
    exporter's `events.jsonl` byte for byte, on the 88a test fixture and on a 12-city 3-minute `capture170`
    window. It also covers:
    - two subscriptions on one connection giving two groups, while a socket grouping is refused;
    - six refusal faults that leave no bundle and no partial;
    - night v0.2 against night v0.1 (same gaps, conditions and records);
    - calibration kinds; refused receipts; the CLI.

## Measurements (MEASURED; fictional data; serial, one fresh process each, under `workstation_heavy.ps1`)

Input: `capture170` for fictional date 2026-09-27, the full 1,440 minutes. It covers 12 markets and 48 events, with
a union of 170 conditions and 113–128 live at once (mean 126.9). There are 16 subscriptions, 2,000 prints and two
outages per socket. Books have 8 levels a side. That is 433 MB of sealed input in 24 hourly segments: 4,320 book
captures with 366,072 token books, 183,036 reward captures and 1,440 discovery captures. The measured exporter
modules are identical at `c52c3191` and `d4126a64`. `d4126a64` changed only the S2 sampler (finding 5).
`s2_v02_t1_clean` and `s2_v01_t1b` ran at `d4126a64`. `s2_v02_tdefault`, the tracemalloc run and `books` ran at
`c52c3191`, so the 1.836 GiB default-threads peak includes up to about 0.1 GiB of sampler leak and is an upper
bound. The workstation has 32
logical CPUs.

### S2: exporter peak vs output bytes, full day

Memory is read the way the nightly wrapper's ceiling reads it: the larger of working set and private commit,
sampled every 50 ms per exporter phase.

| Run | Exporter | BLAS threads | Peak | Runtime | Output |
| --- | --- | ---: | ---: | ---: | ---: |
| `s2_v02_t1_clean` | v0.2 night | 1 | **0.303 GiB (325,394,432 B)** | 1,135 s | 1,173,004,724 B (1.092 GiB) |
| `s2_v02_tdefault` | v0.2 night | 32 (default) | 1.836 GiB (1,971,171,328 B) | 940 s | identical bytes |
| `s2_v01_t1b` | v0.1 night (frozen) | 1 | **11.50 GiB (12,349,501,440 B)** | 1,340 s | 1,595,596,096 B (1.486 GiB) |

The two v0.2 runs give the same `v01_equivalent.sha256` (`bcaf3f19…a374baf`, 2,494,760 rows, 1,594,277,445 B).
That is the v0.1 events stream the v0.2 bundle validated against before publishing.

**Memory drivers** (v0.2, one thread). Phase peaks: start 62 MiB; `projecting` 225 MiB; `segment_loaded` 310 MiB; `segment_projected` 308 MiB; `writing`, `validating` and `done` 288–289 MiB. The level is flat from the first segment to the last, so nothing grows with the day.

- **Interpreter and libraries: about 50 MiB** with one BLAS thread. With default threads, numpy's OpenBLAS commits
  about 47 MiB per thread at import, so 1.51 GiB is committed before any data is read on this 32-thread host. That
  commit is private memory, so the nightly wrapper's `PrivateMemorySize64 ≥ 2GB` check counts it. It is the
  difference between 0.3 and 1.8 GiB here, and it would add the same per thread to the v0.1 exporter.
- **One hourly segment's decoded captures** (`Segment.captures()`, `CaptureIndex`, the timeline). This is the
  step from the `projecting` phase to `segment_loaded`, freed between segments. It is capped by the exporter's
  64 MiB decoded-bytes-per-segment rule.
- **Accumulators at the end of projection** (full day): 1,356 dedup entries, 340 tokens, 170 conditions, 2,000
  trade skews, 183,036 book minutes and a 279 KB event cache. tracemalloc attributes about 80 MiB of Python heap at
  that point:
  - `maker_plugin/inputs.py` 26 MiB;
  - the v0.2 exporter 17–19 MiB (book minutes);
  - JSON decoding 16 MiB;
  - `pathlib` 7 MiB.
- **Output: 0 bytes in memory.** Streams go to disk, out-of-order kinds spill 32 MiB runs (plugin inputs: one run),
  and validation streams one record at a time.

**Why v0.1 peaks higher.** The v0.1 exporter:

1. holds every row's bytes in `Projection.records`;
2. joins them into a second copy;
3. re-parses the whole bundle into frozen records to validate it (`load_bundle`);
4. lets the night wrapper's `_finalize` call `load_bundle` again and read each file whole.

Its peak therefore scales with output bytes. The v0.2 peak does not. On this day v0.1 peaked at 11.50 GiB on
1.486 GiB of output (7.7x), consistent with production's 9.9 GiB on 1.30 GB (7.6x). v0.2 peaked at 0.303 GiB on
1.092 GiB of output, 38x lower than v0.1.

### S1 from the exporter: bytes and records per kind, v0.1 vs v0.2, full day

| Kind | v0.1 bytes | v0.2 bytes | v0.1 records | v0.2 records | Reduction | Share of v0.2 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| book | 514,196,267 | 514,196,267 | 546,650 | 546,650 | 0 | 43.9% |
| outcome_view | 303,767,314 | 303,767,314 | 546,650 | 546,650 | 0 | 25.9% |
| descriptor | 222,444,888 | 222,444,888 | 183,036 | 183,036 | 0 | 19.0% |
| terms | 86,935,663 | 86,935,663 | 183,036 | 183,036 | 0 | 7.4% |
| coverage | 456,946,478 | 34,339,371 | 1,023,548 | 84,870 | **92.5%** | 2.9% |
| info_event | 7,286,804 | 7,286,804 | 8,206 | 8,206 | 0 | 0.6% |
| plugin_input | 1,575,401 | 1,575,401 | 1,634 | 1,634 | 0 | 0.1% |
| trade | 1,124,630 | 1,124,630 | 2,000 | 2,000 | 0 | 0.1% |
| **streams** | **1,594,277,445** | **1,171,670,338** | **2,494,760** | **1,556,082** | **26.5%** | |

The v0.2 bundle, with `bundle.json` and `export.json`, is 1,173,004,724 B = **1.092 GiB per date, over the 1 GiB
rule**. Coverage compacts to 16 groups, 12.1 v0.1 rows per group row. Every other kind is unchanged, because
nothing is elided.

### Book bytes against levels a side

Each depth was a separate 60-minute `capture170` window with 22,934 book records, through the v0.2 exporter.

| Depth requested | Mean levels a side present | Bytes per book record |
| ---: | ---: | ---: |
| 4 | 3.95 | 717.9 |
| 8 | 7.76 | 939.3 |
| 16 | 14.95 | 1,358.1 |
| 32 | 27.66 | 2,097.8 |
| 64 | 44.14 | 3,056.8 |

A least-squares fit gives **488 bytes + 58.2 bytes per level a side** per book record. Edge bands cannot hold
every requested level inside (0, 1), so the levels present are fewer than requested. At about 547 k book records a
day, each extra level a side adds about 32 MB a day. Books alone would reach 1 GiB at about 25 levels a side. The
real depth is a P1 measurement.

## Findings

1. **Descriptors and outcome views are not rare at real 88a cadence.** This changes the E2 outlook.
   - 88a records discovery every capture cycle (`maker_evidence_capture.build_universe`, every minute). The
     projection's descriptor carries `source_hashes.discovery`, the hash of the latest discovery envelope, so it
     changes every minute for every live condition. The v0.1 dedup (`changed=True`) keeps every one: 183,036 a
     day, about 1.2 KB each.
   - The fair-value view's `as_of_utc` moves with each book capture, so every book capture writes an outcome
     view: 546,650 a day.
   - Session A's W0 fixture assumed about 256 descriptors a day and views refreshed every 10 minutes, so its
     0.585 GiB understated v0.2 bytes by about half.
   - Books, outcome views and descriptors are 89% of the v0.2 bytes, and the format does not touch them. If P1
     confirms this, E2 fails without a format change, for example carrying descriptor provenance and view
     freshness without a full record each capture. That needs a registration amendment before signature.
2. **Duplicate elision buys nothing.** This confirms Session A's finding 1, end to end. W2 adds no elision, and
   the v0.2 bundle expands to exactly the v0.1 rows. The registration draft's §6 now says so, and states the
   v1-engine capture-time fact (Session A's finding 2) as a requirement on W3.
3. **Coverage groups per subscription work against the real projection.** On the full day there are 16 groups
   and no refusal. The tests show the alternative fails: a single group over two subscriptions on one connection
   is refused (`coverage_group_mismatch`).
4. **OpenBLAS commit is the largest single memory item on a many-core host.** It is about 47 MiB per thread at
   import, and the wrapper's private-memory ceiling counts it. The capture host's thread count is not recorded
   in the repository. The exporter child should run with `OPENBLAS_NUM_THREADS=1`, a roll-free change to
   `scripts/ops/replay_bundle_export_nightly.ps1` when production adopts v0.2. This branch does not change the
   wrapper, which still launches the frozen v0.1 facade.
5. **`maker_core.replay.ceilings.process_memory` leaks about 7.4 KB per call.** It defines a new ctypes
   `Structure` on every call, and ctypes caches each class's `POINTER` type forever. Exporters call it once per
   receipt, which is harmless. A 50 ms sampler grew by about 1 GiB over a 2.7-hour run. `ceilings.py` is frozen
   exam code, so it is not edited. `s2.py` uses its own leak-free probe, and the first v0.2 measurement
   (`s2_v02_t1`, 0.419 GiB, including about 100 MiB of sampler leak) was rerun clean.
6. **The real exporter's first book capture of the day finds bands with no book yet** (`book_not_captured`).
   Bands in later book batches of that first minute have no book until the next minute. On the fixture day 2,458
   condition-captures are excluded as `missing_descriptor`, mostly in the first minute. This is v0.1 behaviour,
   unchanged.

## Frozen-bytes proof

`git diff --name-only ae08de20 HEAD` lists only new files under `src/` and `tests/`, plus `tools/research/maker_replay_v2/*`
and three docs. None of them is among the 188 paths the exam tree `664c8943` changed against its merge base with
master. `README.md` and `docs/operations/maker-replay-bundle.md` are among those paths, so neither was edited. The
v0.2 command and contract documentation belongs to W8. Over the v1 hashed set, the change is additions only:

- `src/maker_core/replay/v2/writer.py`
- `src/weather/market/maker_replay_bundle_v02.py`
- `src/weather/market/maker_replay_night_v02.py`

Session A's finding 5 applies again: a v1 manifest rebuilt from this tree would list these additional files.

## Per-file roll verdict

`roll_verdict.ps1` is UNDECIDABLE on the workstation (no `data\snapshots` closure files). The static verdict:

| Files | Closure membership |
| --- | --- |
| `src/maker_core/replay/v2/writer.py`, `src/weather/market/maker_replay_bundle_v02.py`, `src/weather/market/maker_replay_night_v02.py` | New. Only each other, tests and tools import them (grep of `src`, `app`, `scripts`), so they are in none of the capture closures. |
| `tools/research/maker_replay_v2/*`, `tests/**`, `docs/**` | Roll-free |

No `schema_registry*`, `.ps1` or Scheduler file is touched. Production still runs `roll_verdict.ps1` on the
integration branch itself before any landing.

## Audits and tests

- **Focused suite and repo-wide audits**, through `workstation_heavy.ps1 -Kind pytest` at `d4126a64`: exit 0. The
  suite covered:
  - this package's tests: `test_replay_v2_writer`, `test_maker_replay_bundle_v02`;
  - W0/W1: `test_replay_v2_fixture`, `test_replay_bundle_v02`;
  - the frozen v0.1 exporter and night tests, and `test_replay_bundle`;
  - the audits: `test_maker_replay_v2_admission`, `test_import_architecture`, `test_path_policy`,
    `test_module_size_audit`, `test_schema_registry`.
- The full suite was not run on the workstation. The shared heavy lease was held by other sessions for most of
  this session, and it was used for the measurements above. GitHub CI on the PR runs the full suite (`test`,
  `native-launch`, `hook`); see the PR for its conclusion.
- `python -m weather.operations.agent_docs_audit`: PASS. `correspondence_index --check`: OK.

## What was NOT done

- No production, calibration, panel or settlement data was read.
- No registration, signature, Scheduler change, production write, restart or venue call. No merge to master.
- No file of `664c8943` was edited. The nightly wrapper was not changed.
- W3–W8 were not started here; W3–W5 run in a separate session.
- The registration draft and engineering plan edits are docs only and unsigned.

## Reproduction

From a checkout of this branch on the workstation, with a new scratch root `<S>`:

```powershell
$env:PYTHONPATH = "$PWD\src;$PWD"
$env:OPENBLAS_NUM_THREADS = '1'   # omit for the default-threads run
function Invoke-Mrv2($a) {
  $b64 = [Convert]::ToBase64String([Text.UTF8Encoding]::new($false).GetBytes((ConvertTo-Json -Compress -InputObject $a)))
  .\scripts\ops\workstation_heavy.ps1 -Kind weather_heavy -PythonPath (Resolve-Path .\venv\Scripts\python.exe).Path -ArgumentsBase64 $b64 -RepoRoot $PWD.Path
}
Invoke-Mrv2 @('-m','tools.research.maker_replay_v2.run','s2-input','--out','<S>\day')
Invoke-Mrv2 @('-m','tools.research.maker_replay_v2.run','s2','--input','<S>\day\capture','--out','<S>\v02')
Invoke-Mrv2 @('-m','tools.research.maker_replay_v2.run','s2','--format','v0.1','--input','<S>\day\capture','--out','<S>\v01')
Invoke-Mrv2 @('-m','tools.research.maker_replay_v2.run','s2','--tracemalloc','--input','<S>\day\capture','--out','<S>\trace')
Invoke-Mrv2 @('-m','tools.research.maker_replay_v2.run','books','--minutes','60','--depths','4','8','16','32','64','--out','<S>\books')
```

Each run writes its JSON under `--out`. The day input is 433 MB and each export about 1.2–1.6 GB, so delete `<S>`
afterwards. The tracemalloc run takes about 2.7 hours, and its peak is not a measurement.

For production (P1, calibration dates only, after landing), the v0.2 night export is:

```powershell
$env:OPENBLAS_NUM_THREADS = '1'
.\venv\Scripts\python.exe -B -m weather.market.maker_replay_night_v02 night --day 2026-09-27 --data-root <data> --release-root <immutable-releases> --out <v02-panel> --expected-module-sha256 <hash>
```
