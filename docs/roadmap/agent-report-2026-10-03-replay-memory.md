# Agent report 2026-10-03 — replay peak memory vs Clarification 2's ~546 MiB per date

**Verdict: NO-GO for a byte-identical fix. STOPPED as instructed; no hashed file changed.** On the PR #166 D = 12
full-day fixture, the exam tree's rehearsal peaks at **2,514–2,616 MiB above baseline per date** (budget ~546 MiB).
**Memory scales linearly with the number of dates in one run**, so the × 15 rule is accurate, not pessimistic. Three
full days in one run peak at 7,607 MiB, 3.03 × one day. Fifteen 3-hour days peak at 5,280 MiB, 14.6 × one 3-hour day.
The best byte-identical prototypes measured reach **1,006 MiB** without touching the exporter's module closure and
**777 MiB** with slotted engine records, which do change that closure. That leaves −460 MiB and −231 MiB of margin
against 546 MiB. Real 88a selects about 120 bands, against the fixture's 12. An unsigned
[Clarification 4 memory option](../research/maker-replay-clarification-4-memory-option-draft.md) puts the choice to
the owner: a streaming scored pipeline plus a fresh rehearsal, or accepting Clarification 2's "not executable on this
host" verdict.

Two side findings:

- **The scored-run memory guard leaks.** `ceilings._windows_process_memory` defines a new ctypes `Structure` subclass
  on every call. ctypes caches its pointer type for the life of the process. tracemalloc attributes about 3.5 KB
  retained per call to `ceilings.py:80/91`. The scored run's `ceilings.guarded` calls it every 0.25 s, so a 4 h run
  would retain on the order of 200 MB that no rehearsal measures, because a rehearsal calls it twice. The fix is to
  hoist the class and argtypes to module level. `ceilings.py` is in both `source_hashes()` and the exporter closure, so
  this is not done here.
- **`engine.py` is inside the panel exporter's module closure.** `maker_replay_night` imports `ceilings`, which
  imports `engine`. The closure also holds `bundle.py`, `calibration.py`, `payloads.py`, `fill_model.py`,
  `re1*.py`, `_fill89a.py`, `evidence/journal.py` and `quoting/*`. So "exports are unaffected by replay changes" holds
  only for changes outside those files. Exporter module hash at `37092926`
  (`python -m weather.market.maker_plugin.replay_export module-hash`): `1f0085ab0dc1464471610f9cd1428f4b05f8808dafd73a315ae2bfb165c22b5d`,
  54 files. It is unchanged on this branch, because nothing under `src/` changed.

Branch `codex/replay-memory-20261003` from `37092926386a0cac14371bf48382a1cb3079e442` (head of
`codex/exam-w2-20261003`, which carries `codex/integration-exam-20261002` at `d6086f3c` plus W2; no Amendment-3 merge
of it existed at run time). Reserved confirmation window: NONE RESERVED (checked at run time). No dated evidence,
production data or credentials were read. Every input is the synthetic #166 fixture.

## 1. Method

- **Fixture.** PR #166's `fixture.py`, copied unchanged to `tools/research/replay_memory/`. D = 12, churn 1,
  2,000 public-trade rows per full day, full density, with one capture cycle a minute. The seal gives 79,508 records
  per full day, identical to #166's count. The 3-hour variant (`MINUTES=180`) gives 9,970 records and 250 trade rows.
  Dates: the three calibration dates plus 2026-09-30..10-14.
- **Measurement.** `tools/research/replay_memory/prof.py`. `--mode rehearse` runs the exam tree's own
  `pack_cli.rehearse`, which is the Clarification 2 number: peak commit or working set minus the pre-input baseline.
  `--mode multi` runs the same pipeline on N bundles of any dates, because `rehearse` refuses non-calibration dates
  and more than one date. A 50 ms sampler records the largest current commit per phase. It wraps each engine pass,
  `score`, `pull_efficiency`, `report_bytes` and so on. A tracemalloc run on a 3-hour day attributes the structures
  (`--trace`; tracemalloc inflates the process size, so its run is used only for attribution).
- **Baseline.** About 1,515 MiB on this 32-core workstation. `calibration.py` imports scipy, and numpy/OpenBLAS
  commits per-thread buffers. The baseline is subtracted, so the above-baseline figures are unaffected. The capture
  host's baseline will be smaller. Memory never falls back during a run: pymalloc keeps freed arenas, so the peak is
  a high-water mark and what matters is how much is alive at once.
- Every run was a fresh process, launched directly and one at a time; the workstation wrapper admits only listed
  modules. Every process I started was terminated or exited; none remains.

## 2. Where the memory is (exam tree, one full D = 12 date)

Phase high-water marks above baseline in the `multi` run (2,514 MiB peak), with attribution from the tracemalloc run:

| Phase | MiB above baseline | What is alive |
| --- | ---: | --- |
| Bundle load (transient JSON parse) | 208 | about 140 retained: `CapturedRecord`s with frozen `MappingProxyType` payloads (`bundle.py:87/314`) |
| After informed-v0 pass | 502 | about 360 MiB per `ReplayResult` |
| + no_quote, blind_re1, clock_only passes | 856 → 1,210 → 1,571 | all four results of a bound alive at once (`results` dict) |
| Scoring, pull efficiency, traces | 2,080 → 2,286 | score rows, `_Spans`/`_Midpoints` indexes, `excluded_intervals` dicts, `digest(r.decisions)` |
| `report_bytes` | 2,278 → 2,514 (process peak) | `plain()` copy of the whole report plus a 225,628,370-byte JSON string |

Per `ReplayResult` (442,476 decisions and 442,476 spans in the informed pass):

- `Span` dataclass instances with per-instance `__dict__`: `engine.py:466`.
- `QuoteDecision` (`policy.py:196`) and `DecisionEvent` (`engine.py:248`) instances. Nearly every tick records a
  decision, many of them pulls from `engine.py:262`.
- One 64-hex `digest(...)` string per decision: `journal.py:47`.
- A fresh `Decimal` per span from `State.reserve`: `engine.py:127`.
- Each pass's own decoded `Book` objects.

In the report, `traces.excluded_intervals` holds one dict per uncovered evaluation-active span, in 8 traces per bound
pair. The fixture's coverage records expire 30 s after each capture while books last 60 s, so about half of every
minute is `TRADE_CAPTURE_GAP`. That is #166's reading of the 88a export density; real bundles may differ. Those dicts
make up most of the 225 MB report.

**Scaling.** Spans and decisions grow with heap pops × active bands, which is linear in days. Excluded intervals grow
the same way. Bundles are linear in days. The scored run replays all 15 dates in one engine pass, because inventory is
carried to settlement. Measured:

| Run | Dates in one run | Records | Max events | Max decisions + spans | Peak above baseline (MiB) | Per date | Runtime (s) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 3-hour days | 1 | 9,970 | 5,370 | 128,832 | 362 | 362 | 53 |
| 3-hour days | 3 | 29,898 | 16,109 | 386,520 | 1,068 | 356 | 168 |
| 3-hour days | 15 | 149,416 | 80,536 | 1,932,480 | 5,280 | 352 | 1,211 |
| Full days | 1 | 79,508 | 42,281 | 884,952 | 2,514 | 2,514 | 355 |
| Full days | 3 | 238,511 | 128,294 | 2,691,744 | 7,607 | 2,536 | 1,121 |
| Full day, `pack_cli.rehearse` | 1 | 79,508 | 42,281 | 884,952 | 2,616 | 2,616 | 278 |

**× 15 linear scaling is real.** It is within 3%, and slightly favourable at 15 dates, from fixed overheads. A
15-date scored run at this density would need about 37 GiB. **Runtime is superlinear**, an aside for the runtime
ceiling: 15 three-hour dates took 1.51 × 15 one-date runs. `tick` visits every condition state at every pop, and
`portfolio()` sums over all states, so cost grows with dates × states. A real panel's runtime ceiling is therefore
optimistic under the × 15 rule, while its memory ceiling is honest.

The full-day `rehearse` figure (2,616 MiB) is higher than the `multi` figure (2,514 MiB) on the same bundle. The phase
sampler shows the same structure in both. The difference is run-to-run allocator and high-water variation; #166 measured
2,448 MiB (2,566,868,992 B) on its host.

## 3. Byte-identical reductions, prototyped and measured (not committed as code)

The patches are evidence only. They apply cleanly to `37092926`:
[prototype A](agent-report-2026-10-03-replay-memory-prototype-a.patch) and
[prototype B](agent-report-2026-10-03-replay-memory-prototype-b.patch).

- **A (only files outside the exporter closure: `report.py`, `baselines.py`, `pack_cli.py`).**
  - Each policy's result is scored and traced, then dropped. Only informed-v0 and the matched clock are kept together,
    for `pull_efficiency`.
  - `matched_clock` keeps one clock trial alive at a time and replays the best one again if it was not the last. This
    path was not exercised: the fixture matched with no bisection, 8 passes.
  - `excluded_intervals` entries become a slotted frozen dataclass. `plain()` renders it as the same dict.
  - `digest(r.decisions)` becomes a streamed SHA-256 over canonical chunks.
  - `rehearse` measures the report size with a chunked canonical encoder instead of materializing it.
- **B = A plus slotted `Span`, `DecisionEvent` and `QuoteDecision`, and a shared `Decimal(0)` reserve.** These are in
  `engine.py` and `policy.py`, so the exporter closure changes.

| Variant (full day, 2026-09-27) | `rehearse` peak above baseline (MiB) | Margin vs 546 MiB | Report JSON / MD SHA-256 (`multi`) |
| --- | ---: | ---: | --- |
| Exam tree `37092926` | 2,616 (`multi`: 2,514) | −2,070 | `8355bdb9def0b170…` / `0451b3550d64a7cc…` |
| A without streamed decision digest | 1,533 | −987 | identical |
| B without streamed decision digest | 1,304 | −758 | identical |
| **A (final)** | **1,006** | **−460** | identical report bytes (225,628,370) |
| **B (final)** | **777** | **−231** | identical (`multi`, full render: 1,337 MiB) |

**Caveat on the "final" rows.** They count report bytes with the chunked encoder. Today the scored run's
`write_report` still materializes `report_bytes`. With that full render, B peaks at 1,337 MiB (`multi`). Landing A or B
honestly therefore also needs a chunked two-pass `write_report` (size check, then write). Otherwise the rehearsal would
under-measure the scored run it is meant to bound.

Every variant keeps the same pass counts (events 42,281; decisions plus spans 884,952) and the same report byte count.
The chunked encoder and the streamed digest were also checked equal to `canonical_bytes` and `digest` on randomized
nested structures and on `DecisionEvent` tuples.

**What still holds memory at 777 MiB.** About 140 MiB of loaded bundle, which `bundle.py` owns, inside the closure.
About 235 MiB per retained result, even slotted. Informed-v0 and the clock result are alive together for
`pull_efficiency`. On top come the report's score rows and excluded-interval records. The next step down is not
compaction. The engine would have to stop retaining spans and decisions and feed incremental scorers instead, which is
Option A in the Clarification 4 option. That is a re-implementation of the hashed engine and scoring path, and
byte-identity has to be proven against the current code. It is not something to land under exam-period time pressure
without an owner decision. Reaching 546 MiB at D = 12 would still leave no margin at D ≈ 120.

## 4. Hashed files

None changed on this branch. `execution_manifest.source_hashes()` and the exporter module hash
(`1f0085ab…22b5d`, 54 files) are unchanged, and production needs no re-pin for this branch. A landing of prototype A
would change `src/maker_core/replay/{report,baselines,pack_cli}.py`. Those are in `source_hashes()` only: re-pin the
replay tree, while the exporter hash stays unchanged. Prototype B would also change `src/maker_core/replay/engine.py`
and `src/maker_core/quoting/policy.py`. Those are in both: re-pin both, and the exporter module hash changes. The
ceilings-leak fix would change `src/maker_core/replay/ceilings.py`, also in both.

## 5. Per-file roll verdict

| File | Closures entered |
| --- | --- |
| `docs/roadmap/agent-report-2026-10-03-replay-memory.md`, `…-prototype-a.patch`, `…-prototype-b.patch`, `…-replay-memory.json`, `docs/research/maker-replay-clarification-4-memory-option-draft.md`, `docs/roadmap/correspondence-index.md` | none (docs) |
| `tools/research/replay_memory/{fixture,gen,prof}.py` | none (research scripts, not under `src/`) |

The branch is roll-free. Confirm with `scripts\ops\roll_verdict.ps1 -Branch codex/replay-memory-20261003`.

## 6. What was NOT done

- No code change to the exam tree, and no re-pin needed.
- No production data, credentials, `.env` or venue calls.
- No registration, Scheduler change, restart, merge or order.
- No signature: the Clarification 4 option is unsigned.
- Not measured: the scored `run --compare` CLI end to end. It needs a signed manifest. Its scoring and rendering are
  the same `comparison_report` and `report_bytes` that `multi` runs, plus the three calibration bundles that
  `verify_manifest` keeps loaded, about 140 MiB each at this density. Also not measured: real 88a bundles, and any
  date with bisection in `matched_clock`.

## 7. Reproduce (workstation, or the capture host only inside its admitted window)

```powershell
$env:PYTHONPATH = "<exam worktree at 37092926>\src"
$fx = "<new scratch folder>"
.\venv\Scripts\python.exe tools\research\replay_memory\gen.py $fx\fx 2026-09-27 2026-09-28 2026-09-29
'{"format":"maker_core.replay.calibration.v1","hazard_per_minute":0.01}' | Set-Content -Encoding ascii $fx\fx\calibration.json
.\venv\Scripts\python.exe tools\research\replay_memory\prof.py --mode rehearse --bundle $fx\fx\2026-09-27\bundle --calibration $fx\fx\calibration.json --out $fx\rehearse.json
.\venv\Scripts\python.exe tools\research\replay_memory\prof.py --mode multi --bundle $fx\fx\2026-09-27\bundle --bundle $fx\fx\2026-09-28\bundle --bundle $fx\fx\2026-09-29\bundle --calibration $fx\fx\calibration.json --out $fx\multi3.json
# 3-hour days: $env:MINUTES = "180" before gen.py. Prototypes: git apply docs\roadmap\agent-report-2026-10-03-replay-memory-prototype-b.patch in a scratch copy of the exam tree.
```

Per-run figures are in [`agent-report-2026-10-03-replay-memory.json`](agent-report-2026-10-03-replay-memory.json).

Commit: see the PR head on `codex/replay-memory-20261003`.
