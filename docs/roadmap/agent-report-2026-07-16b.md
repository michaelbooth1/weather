# Bounded Maker-Paper Scorer Agent Report — 2026-07-16b

## Handoff identity

- Branch: `maker-bounded-2026-07-16`
- Worktree: `C:\Users\micha\Desktop\github\weather-maker-bounded`
- Base `master` commit: `74a86274746d743d7834ff3f0946d6b24ffe2d3b`
- Implementation commit: `63784643f9479f56fffb8af74b91b2e5edc54970`
- Report commit: the follow-up commit containing this file; its final object ID
  is recorded in the operations handoff because a commit cannot contain its own
  final ID.

No merge, push, scheduler change, capture-loop action, release-state mutation,
or runtime `data/` write was performed. The main worktree was not edited and
was clean at the final read-only status check. The only `data/` access was the
required read of `data/logs/memory_commit_guard_status.json` before each test,
compile, and documentation-audit batch.

## What changed

The scheduled `maker_paper_score` step now binds scoring to the exact folders
that passed its input-byte preflight and uses the bounded path explicitly. The
latest-active-day selection contract remains the default 14 runs, and the
preflight remains fail closed at 512 MiB.

`weather.market.mm_paper_aggregation` is the new bounded owner for retained
scorer state:

- base quote rows and model-variant rows are decoded, leg-scored, spilled, and
  released one selected run at a time;
- quote rows, legs, queue companions, fills, and guardrail-shadow detail rows
  use re-iterable SQLite stores with a two-MiB SQLite page cache and file-backed
  temporary state;
- trades, books, and marks are loaded and spilled one event at a time; global
  trade capacity and cumulative per-leg fill size are disk-backed;
- exact quote-to-leg membership, source order, global fill order, queue-map
  overwrite order, duplicate-run expiry/reward regrouping, and event-tape range
  lookups are represented in indexed SQLite columns rather than Python row
  populations;
- all spill ownership closes deterministically on build or artifact-write
  errors, and normal scheduled completion closes it after the result summary is
  detached.

All maker quote, trade, book, mark, and JSONL tape readers now consume the
repository streaming iterators where row-at-a-time parsing is possible.
`weather.io.iter_csv_rows(..., attach_diagnostics=True)` retains the existing
legacy-encoding fallback and diagnostics behavior.

Reducers that formerly constructed corpus-sized helper lists now retain fixed
counts, sums, bounded samples, and grouped sufficient statistics. This covers
event-gate scoring, quote uptime/blockers, reward diagnostics, markout slices,
model-variant clusters, fill-evidence checks, decisive-resting diagnostics, and
early-hour guardrail summaries. Markout confidence intervals retain exact
float-ratio variance partials so the existing rounded field semantics are
preserved without retaining fill values.

The scheduled adapter and CLI defer the four detail arrays until artifact
writing. JSON arrays and the fills CSV are emitted row at a time from SQLite;
JSON is written to a same-directory temporary file and atomically replaces the
canonical artifact only after complete serialization. Direct library callers
retain the prior ordinary-list payload contract by default.

The declared resource budgets are unchanged:

- latest active runs: 14;
- selected quote/variant input: 512 MiB;
- private memory: 4,096 MiB;
- working set: 3,072 MiB.

The output schema remains `mm_paper_v0.1`. No schema version was bumped because
fields, row semantics, grouping, evidence windows, thresholds, countability,
and gate decisions did not change.

## Equivalence argument

The daily step performs latest-N active-day selection once, records the exact
selected paths in `input_preflight`, and passes both those paths and their
selection receipt into the builder. The builder therefore cannot discover a
different corpus between preflight and scoring. Eligibility filtering and
run-folder ordering remain unchanged.

Within a selected run, the existing `load_quote_rows` and `quote_legs`
functions still assign quote IDs, construct YES bid/ask legs, attach TTL/next
quote expiry, and calculate reward estimates in their original order. A run is
spilled only after those operations finish. If a duplicate `run_id` appears in
more than one folder, the disk-backed finalizer replays the original global
`(run_id, event, token, side, quote_time)` expiry grouping and quote-ID reward
grouping before fill scoring.

Conservative fills still traverse legs by `(quote_time, leg_id)` over the full
selected corpus. Trade IDs retain their existing filename/index identity, and
their last-write initialization plus cross-event depletion is held in one
disk-backed capacity table for each base or variant population. Queue rows
retain Python-dict semantics: the first insertion fixes output position and a
later duplicate leg ID replaces the value. Event queries preserve the original
boundaries: nearest book at or before quote time, subsequent books and trades
in `(quote_time, quote_expires_at]`, and the first mark at or after each markout
horizon.

The multi-run equivalence regression compares the complete streamed payload
with the legacy materialized path, including cross-run competition for one
strict-trade-through fill. It then writes a deferred streamed artifact and a
materialized artifact and asserts their parsed JSON payloads are identical.
It also re-iterates deferred fills and queues after writing, proving that writer
consumption does not alter row order or payload usability.

## Memory regression

The driver-level `tracemalloc` regression runs the complete bounded builder and
artifact writer on synthetic corpora of 5 and 50 market-days. Every run has 256
base rows and 256 model-variant rows, with 32 permitted quotes per file. The
50-run case therefore processes 12,800 base rows, 12,800 variant rows, 3,200
base legs/queues, and 3,200 variant legs/queues while exercising the deferred
JSON and CSV path.

The test asserts all input, leg, and output counts and requires the 50-run peak
to be no more than two MiB above the 5-run peak. This fails if corpus-wide input
rows or the growing queue-detail arrays are restored to Python lists.

## Verification

Every batch read a live guard status with `commit_percent < 70`; final guard
readings were between 41.9% and 42.8%.

- Focused maker, streaming-I/O, event-calendar, daily-refresh, resource, and
  import-architecture suites:
  `python -m pytest tests/market/test_mm_paper.py tests/market/test_info_event_calendar.py tests/test_io_streaming.py tests/operations/test_import_architecture.py tests/operations/test_daily_refresh.py tests/operations/test_daily_refresh_resources.py -q`
  — **175 passed, 4 subtests passed** in 55.36 seconds.
- Inherited bounded-scorer reference suites:
  `python -m pytest tests/reporting/test_hourly_model_performance.py tests/reporting/test_ten_minute_model_performance.py -q`
  — **13 passed** in 5.23 seconds.
- `python -m compileall -q src tests` — **PASS**.
- `python -m weather.operations.agent_docs_audit` — **PASS** (18 agent files
  and 443 Markdown files audited).
- `git diff --check` and the implementation staged-diff check — **PASS**.

No production scorer, barrier resume, runtime adoption, or representative
11/14-run operational soak was run. The operations master agent retains
ownership of audit, merge, the July 15 barrier resume, and the queued July 14
and July 12 historical completions.
