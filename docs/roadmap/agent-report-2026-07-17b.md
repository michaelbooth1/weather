# Bounded Taker Tail Casebook Agent Report — 2026-07-17b

## Handoff identity

- Branch: `taker-tail-casebook-bounded-2026-07-17`
- Worktree:
  `C:\Users\micha\Desktop\github\weather\.claude\worktrees\taker-tail-casebook-bounded-2026-07-17`
- Base `master` commit: `37deccce1d3b43cfaa1bc40b55ec4fd27204b893`
- Implementation commit: `41db4bf15bc0daaa717a1015e72a2acf11784a75`
- Report commit: the follow-up commit containing this file; its final object ID
  is recorded in the operations handoff because a commit cannot contain its own
  final ID.

No merge, push, scheduler change, capture-loop action, release-state mutation,
settlement-chain resume, or runtime `data/` write was performed. The only
`data/` access was the required read of
`data/logs/memory_commit_guard_status.json` before verification batches. The
main worktree was not edited; its pre-existing changes to
`config/location_market_events.json` and `config/locations.json` were not
modified, staged, or included.

## What changed

`weather.reporting.casebooks.taker_tail_casebook` now builds the scheduled
multi-run casebook in two bounded tape passes. Both passes consume
`weather.io.iter_csv_rows(..., attach_diagnostics=True)` and retain the same
order-row normalization and source metadata as `read_order_rows`:

- pass one folds every row's corpus-global market-modal candidate into a
  disposable SQLite index keyed by `(market_id, event_slug, snapshot_id)`;
- pass two scores one normalized order row at a time, folds filled-order match
  counts immediately, annotates it against the modal index, and writes a
  selected tail case directly to a source-ordered SQLite row store;
- SQLite uses a two-MiB page cache and file-backed temporary state, with a
  commit between runs and deterministic cleanup on both success and error;
- summary and grouped calibration state are computed by re-iterating the
  spilled case view, and the Markdown report now stops after the first 50
  losing cases without first retaining every loss;
- canonical and target-date JSON artifacts stream atomically from the
  re-iterable case view. The daily adapter and CLI close scratch state only
  after all requested JSON and Markdown artifacts have been written.

The output schema remains `taker_tail_casebook_v0.1`. Fields, ordering,
selection rules, evidence-window discovery, labels, countability, and no-go
decisions are unchanged. The resource declaration is also unchanged at 2,048
MiB private memory, 1,536 MiB working set, and 1,800 seconds.

## Equivalence argument

The old materialized path concatenated normalized rows in supplied-run order
and CSV order, built one corpus-wide modal map, scored that same sequence, and
then selected filled tail cases. The bounded path makes the identical ordered
row stream twice. Its first-pass SQLite key is exactly the legacy modal key.
Replacement keeps the legacy strict raw-probability comparison against the
stored six-decimal compact probability, including first-seen behavior on ties
and the existing zero-probability fallback. Modal context therefore remains
global across runs without retaining the row population.

On the second pass, each one-row scoring call is observationally equivalent to
the corpus call because settlement lookup and scoring use only that row and
the immutable label index. Matched and unmatched filled counts are added in
the same source order; every input contributes exactly one scored row. Legacy
tail inference reads the global modal index, and the unchanged predicates
select the same filled cases. SQLite insertion sequence preserves source
order and does not deduplicate repeated rows.

The summary and calibration reducers replay spilled cases in that same order,
so integer counts, sequential floating-point folds, final six-decimal
rounding, sorted group order, no-go selection, and case order match the
materialized implementation. The regression fixture proves this by comparing
both streamed JSON artifacts after parsing with the complete materialized
payload and by comparing both Markdown reports byte for byte. It also covers
a modal candidate in a later run, rounded modal replacement behavior, an
inferred legacy warm tail, explicit low-tail wins and losses, an unmatched
fill, a skipped row, a repeated fill, and re-iteration for the second artifact
pair.

## Memory regression

The `tracemalloc` regression exercises the complete two-pass builder, two JSON
writes, two Markdown writes, and scratch cleanup for 5 runs versus 50 runs.
Each run contains 256 selected losing tail rows with distinct snapshots and an
unused 512-character source field. It verifies all input, scored, case, and
loss counts (1,280 versus 12,800) and requires the 50-run peak to remain within
two MiB of the 5-run peak. This fails if either raw tape rows, modal contexts,
or selected case rows return to growing Python populations.

## Remaining settlement-chain materialization survey

`price_free_model_learning` still materializes a whole selected historical
snapshot corpus. Its daily adapter invokes the builder without a start/end
window; the owner discovers every eligible labeled snapshot folder, reads each
complete `snapshots_long.csv` into a list, creates scored/current-maximum row
lists, and extends corpus-wide `all_rows` and `all_current_max_rows` before
summarizing. This is an unbounded historical snapshot-tape materializer (not a
taker or variant-order tape) and is a clear candidate for a bounded 17c.

`model_market_disagreement_rehydration` still materializes whole-history audit
populations. The adapter performs target-date rehydration and then a global
rebuild, while the owner reads the complete disagreement JSONL before applying
the target filter, rereads it to build the write index, and rereads it again to
retain raw, deduplicated/latest, enriched, active, resolved, pending, and
grouped collections. Its input is the disagreement audit log rather than a
taker/variant CSV, but it is a clear whole-history row-list materializer for a
bounded 17c.

`live_variant_settlement_scorecard` does not retain the complete selected
target-day corpus across tapes, but it still materializes one entire variant
prediction tape and its sibling snapshot tape at a time. Discovery is bounded
by the existing preflight (at most 24 tapes, 128 MiB per tape, and 512 MiB
combined); the loop loads one tape, builds a second normalized list and its
scorecard, releases those rows, and retains only compact partition scorecards
before opening the next tape. It therefore has per-tape whole-list peaks but
not the corpus-wide accumulation pattern of the first two steps.

## Verification

Every batch read a live memory-guard status with `commit_percent < 70`; the
final implementation batches ran at 46.7% commit.

- Focused casebook equivalence, traced-memory, legacy behavior, and daily-step
  coverage:
  `python -m pytest tests/reporting/test_taker_tail_casebook.py tests/operations/test_daily_refresh.py -k casebook -q`
  — **5 passed, 106 deselected** in 58.04 seconds.
- Import-architecture coverage:
  `python -m pytest tests/operations/test_import_architecture.py -q`
  — **21 passed** in 7.31 seconds.
- `python -m compileall -q src tests` — **PASS**.
- `python -m weather.operations.agent_docs_audit` — **PASS**.
- `git diff --check` and the implementation staged-diff check — **PASS**.

No representative July 12–14 corpus run was performed. The operations master
agent retains ownership of audit, merge, runtime adoption, and the recorded
resume beginning at `--resume-from-step taker_tail_casebook`.
