# Agent Report — 2026-07-19a

## Handoff

- Branch: `maker-projection-2026-07-19`
- Base `master`: `c4e88aad07a991f8b79b603d4112e565028e91e6`
- Implementation commit: `d587c9a4249656e7905c9a9f4b95ebaca372c5d2`
- Report commit: the commit containing this document (see branch HEAD at handoff;
  a commit cannot embed its own final object ID)
- Merge/push: not performed
- Runtime actions: no backfill against `data/`, scheduler/loop invocation,
  release action, promotion, or live-trading action was performed
- Main-worktree state: the pre-existing modifications to
  `config/location_market_events.json` and `config/locations.json` were
  preserved and never staged or edited here

## Result

The maker scorer now selects a source-bound compact projection independently
for each selected run. A valid run supplies an atomic base/variant
`mm_scoring_projection_v0.1` pair; if either member or binding is missing,
stale, corrupt, schema-incompatible, or contains a supported legacy scoring
alias, both inputs for that run fall back to the canonical quote tapes.

The preflight measures the exact selected paths, passes their bindings into the
existing streaming scorer, and records selected bytes, canonical bytes, their
ratio, projection/fallback run counts, and per-run receipts. The scorer checks
size/mtime bindings and projection hashes before ingestion and verifies input
stability after streaming, so an admitted input cannot silently disappear,
change, or grow between preflight and scoring.

Canonical tapes remain unchanged and retain the required runtime identity,
lineage, release, and CLOB provenance. Projection publication uses same-folder
atomic CSV writes and publishes the manifest last. Daily-run finalization writes
the projection receipt into `run_summary.json`; day-roll finalization waits for
the superseded target-matched worker to be observed exited before reading its
tapes. Failure leaves canonical fallback in force.

The idempotent CLI is:

```powershell
.\venv\Scripts\python.exe -m weather.market.mm_scoring_projection backfill
```

It discovers existing run folders, streams canonical rows with
`weather.io.iter_csv_rows`, skips already-valid pairs by default, never edits a
canonical tape, and reports per-run errors. `--run-folder` narrows the target;
`--force` explicitly rebuilds a valid pair. Per the work order, the CLI was not
run against `data/` on this branch.

## Reader audit and projection schema

The audit followed the complete `mm_paper_v0.1` output path rather than only
fill construction:

| Reader path | Fields retained for it |
| --- | --- |
| `mm_paper_scoring.quote_id`, `load_quote_rows`, and `quote_legs` | run/market/token keys; quote timestamps; permission; fair/market probabilities and edge; bid/ask prices and sizes; model-variant identity; bin metadata |
| `mm_paper_scoring` TTL/expiry, fill, queue, markout, and reward accounting | `generated_at_utc`/`captured_at_utc` plus bid/ask prices and sizes; TTL itself remains scorer config (`quote_ttl_seconds`), and rewards are derived from legs plus trade/book inputs |
| `mm_paper._build_paper_payload`, `quote_uptime_summary`, `anti_overfit_summary`, and blocker diagnostics | live/quote permission, reason/regime, capture hour, policy/model/source state, spread/imbalance, known-edge taxonomy and match dimensions |
| `info_event_calendar.score_event_gate_decisions` | event-gate status/action/reason, event class/id/next time/exception, market/event keys, and timestamps |
| `mm_policy.early_hour_guardrail_state` and guardrail exposure summaries | all current early-hour guardrail decision, threshold, multiplier, widening, override, and market-weight fields |
| model-variant and market-aware diagnostics | served/variant family, role, basket, probability source, counterfactual flag, promotion state, and market-aware overlay probability/edge/risk-only flag |

The projection contains 69 current `mm_run_v0.2` columns. This is above the
work order's preliminary 25–35 estimate because byte-identical full
`mm_paper_v0.1` output also depends on uptime, blocker, known-edge, event-gate,
guardrail, and model-variant diagnostics. Provenance-only runtime identity and
lineage fields remain excluded.

```text
run_id
target_date
run_mode
generated_at_utc
captured_at_utc
capture_hour_local
policy_hash
live_trade_permission
quote_permission
regime
reason_code
market_id
event_slug
range_label
bin_kind
bin_value
bin_value_hi
clob_token_id
fair_probability
market_mid
market_yes
edge
bid_price
bid_size
ask_price
ask_size
book_spread
book_imbalance_1pct
source_fresh
source_freshness_state
model_version
served_model_version
model_variant_id
model_variant_family
model_variant_role
model_variant_basket_id
model_variant_probability_source
model_variant_counterfactual
promotion_state
known_edge_taxonomy
known_edge_allowed
known_edge_permission
known_edge_reason
known_edge_match_cutoff
known_edge_match_hour_utc
known_edge_match_band_distance_bucket
known_edge_match_band_type
known_edge_match_casebook_taxonomy
known_edge_match_regime
known_edge_match_source_fresh
known_edge_match_source_freshness_state
known_edge_match_book_imbalance_bucket
event_gate_status
event_gate_action
event_gate_reason_code
event_gate_event_class
event_gate_event_id
event_gate_next_event_at_utc
event_gate_exception_id
early_hour_guardrail_status
early_hour_guardrail_reason
early_hour_guardrail_min_edge
early_hour_guardrail_size_multiplier
early_hour_guardrail_quote_widen_buffer
early_hour_guardrail_override_allowed
early_hour_guardrail_market_weight
market_aware_overlay_probability
market_aware_overlay_edge
market_aware_overlay_used_for_risk_only
```

The current canonical writer contains all 69 fields and none of the 43
supported-but-noncurrent aliases. The scorer still accepts historical aliases
such as `model_probability`, `candidate_p`, `quote_size`, and
`min_order_size`; projecting a tape with any such header could change a score.
The writer therefore refuses that projection and the resolver selects both
canonical tapes for the run. This makes schema evolution fail closed rather
than silently dropping scoring-significant legacy data.

## Equivalence and budget evidence

`test_scoring_projection_is_byte_equivalent_to_canonical_inputs` constructs a
current-schema synthetic run with served and shadow model variants, event-gate
timing, capture-hour diagnostics, and a deliberately fat 2,048-byte runtime
identity per row. It writes the canonical score and the projection score with
the normal JSON writer and asserts byte-for-byte equality. The same test then
changes an admitted projection after binding capture and proves scorer
ingestion rejects it.

A separate synthetic projection-size probe with a 16 KiB runtime-identity blob
measured:

- canonical base + variant input: 37,169 bytes
- projection base + variant input: 3,807 bytes
- projected/canonical ratio: `0.10242406306330544` (10.24%)
- projection columns: 69
- current-writer missing columns: none
- current-writer compatibility-alias conflicts: none

The 10.24% result is a deliberately provenance-heavy synthetic fixture, not a
claim about the live evidence window. Applying the requested 15–25% operating
estimate to the reported 814,672,216 canonical bytes gives approximately
122.2–203.7 MB (116.5–194.2 MiB), comfortably below the unchanged 536,870,912
byte preflight cap. The real evidence-window ratio will be recorded
automatically by the adoption-day preflight/backfill receipts; it was not
measured here because the delegate was explicitly prohibited from running the
backfill against `data/`.

Unchanged limits are covered by regression assertions:

- selected active-run window: 14
- maker input cap: 512 MiB (`536,870,912` bytes)
- isolated scorer private-memory cap: 4 GiB
- scorer working-set cap: 3 GiB

## Quote-intent volume diagnosis

The volume increase is tick count, not per-tick row duplication:

| Date | Rows | Rows/tick | Captured ticks |
| --- | ---: | ---: | ---: |
| 2026-07-15 | 15,048 | 132 | 114 |
| 2026-07-17 | 30,228 | 132 | 229 |
| 2026-07-18 | 29,436 | 132 | 223 |

The construction audit found that `assemble_policy_inputs_for_market` emits one
policy input per snapshot band and `build_run_once` maps every input to exactly
one quote-intent row, including explicit no-quote decisions. Event-gate logic
changes action/permission fields but does not add rows. TTL controls scorer and
lifecycle expiry, not intent generation. The worker cadence remained 60
seconds. The constant 132 rows/tick therefore shows no quote-construction,
event-gate, TTL, or re-quote doubling defect: July 15 captured 114 ticks while
July 17/18 captured 229/223 ticks. No generation fix or separate defect receipt
was warranted.

The independent width increase remains intentional. The release-binding change
was introduced by `62a89230c2db9a7db80ae65031e571e9233a8612` and merged by
`85c28aba7273f2bb44390b459295f19648ae8529`; the new projection removes those
provenance blobs only from the derived scoring input, never from canonical
tapes.

## Verification

All test commands were focused on the changed owners, as required by the work
order. Every batch was admitted with host `commit_percent < 70` (observed range
51.8–59.6%; final staged batch 52.0%) and more than 218 GB free on `C:`.

- Final staged focused suite: **100 passed in 16.65s**. It covered projection
  writer/backfill/idempotence, malformed/legacy fail-closed fallback,
  canonical/projection byte equivalence, binding mutation rejection, corrupted
  pair preflight integration, exact selected-path receipts, run finalization,
  superseded-worker exit ordering, existing streaming/materialized
  equivalence, schema registration, import architecture, and unchanged budget
  limits.
- Review-fix subsets: **6 passed in 5.94s** and **5 passed in 5.47s** (subsets
  of the final suite, not additional unique tests).
- `python -m compileall -q app src tests`: PASS.
- `python -m weather.operations.agent_docs_audit`: PASS (18 agent files, 449
  Markdown files).
- `git diff --cached --check`: PASS before the implementation commit.

No full-suite claim is made; the work order requested focused tests. Two
independent review passes were completed before the final suite. Their findings
produced the scorer binding revalidation, bounded rollover exit proof, and the
direct regressions described above.
