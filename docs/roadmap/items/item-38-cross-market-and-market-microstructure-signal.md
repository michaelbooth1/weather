# 38. Cross-Market And Market-Microstructure Signal [PARTIAL 2026-06-14 - TAXONOMY-GATED CLOB OVERLAY]

Goal: squeeze the last edge once per-market models are solid.

- [ ] Borrow strength across correlated cities (regional heat waves / shared
  synoptics).
- [x] Persist CLOB token ids/condition ids into the market snapshot artifacts.
- [x] Capture full CLOB order-book depth per weather-market token:
  timestamp/hash, top levels, cumulative depth, spread, midpoint, imbalance,
  executable price for fixed trade sizes, and last trade metadata.
- [x] Add a market-book loop or WebSocket recorder with 30-60 second baseline
  cadence and 10-15 second near-close/large-edge-change cadence.
- [ ] Model Polymarket price dynamics (stickiness, liquidity, book depth,
  spread, trade flow) toward edge/P&L, not just calibration.

Acceptance: cross-market structure or microstructure adds settlement-scored or
P&L value over independent per-market models.

Data-layer audit result (2026-06-12): `src.data_layer_audit` confirmed the
project currently captures Gamma yes/no prices, best ask, last trade, volume,
liquidity, and status, but it does **not** persist CLOB token ids, order-book
levels, book hashes, book imbalance, executable depth, or a trade stream.
Gamma `best_bid` is only `48.0%` filled across existing snapshot rows. The
Gamma event payload already exposes `clobTokenIds` and `enableOrderBook`, and
Polymarket's public CLOB docs expose `/book`, `/books`, `/prices-history`, and
the public market WebSocket, so this is an implementation gap rather than a
market-discovery blocker. Because historical order-book depth cannot be
reconstructed reliably later, this item is now an immediate data-capture
priority, not merely a future modeling flourish.

Implementation update (2026-06-12): `src.market_microstructure` adds the fast
CLOB capture path. It discovers tokens from Gamma `clobTokenIds`, writes
`clob_tokens.csv/jsonl`, batches REST order books through `/books` with `/book`
fallback, persists raw books plus `order_books_summary.csv` and
`order_books_long.csv`, optionally captures `/prices-history`, and records the
public market WebSocket to `market_ws.jsonl` / `market_ws_events.csv`.
`src.snapshot_tracker` now persists `condition_id`, `polymarket_market_id`,
`clob_token_ids`, and yes/no token IDs in new slow snapshot rows. The model loop
should remain at 5-10 minutes; run the book loop separately at 30-60 seconds
baseline and 10-15 seconds after local 15:00, near close, or after large
top-of-book midpoint moves. Remaining item-38 work is to learn and validate
microstructure signals against settlement/P&L, not merely to collect them.
The loop is now supervised through item 37's `market_microstructure ensure`
path, so the next item-38 step can assume durable book tapes are available.

Cadence-audit update (2026-06-12 late evening): the book tape now has its own
acceptance instrument. `src.market_microstructure audit [--strict]` audits the
active market day's tape per registered market (captures, median/max gap,
gaps over a 120-second threshold, trailing freshness) and exits non-zero in
strict mode on any gap or stale/missing tape. `src.fleet_observability` now
includes a `clob` payload section, a "CLOB Book Capture" report table, and
fail-closed alerts: a DEAD/UNKNOWN/ERRORING book loop or an active-day tape
gap is critical, while PAUSED/DEGRADED warns. Validation: live fleet audit
passed with all 12 markets OK (median gap 15.0s in fast mode, max gap 90.9s,
trailing freshness under 15s); `pytest -q` passed 349 tests + 34 subtests;
`compileall src tests` passed. The docs/research/MARKET_MAKING_PLAN.md Stage-0 acceptance
clock (7 consecutive gap-free days) starts with the first full capture day,
2026-06-13.

Startup-gap policy update (2026-06-14 UTC): the active-day book audit now
distinguishes loop startup gaps from ongoing recorder failure. Gaps ending
before the CLOB loop's `started_at` plus a 180-second grace are recorded as
`startup_gaps_ignored`; post-start gaps and stale trailing captures still fail
strict mode. Live validation: `src.market_microstructure audit --strict` passes
all 12 active markets. The fleet report no longer has CLOB, artifact-schema, or
redundant historical-source blockers, but it still correctly fails strict when
the main snapshot tapes have real active-day collection gaps.

Serial fleet-cycle update (2026-06-15 UTC): the CLOB loop now heartbeats after
each market inside a long all-market capture and records
`last_iteration_elapsed_seconds`; the active-day book audit derives its fleet
gap threshold from that measured cycle plus configured sleep and buffer. This
prevents the supervisor and observability report from treating a healthy
serial 12-market capture cycle as a dead loop while preserving strict stale
tail and post-cycle gap checks. Validation:
`src.market_microstructure audit --strict` passed all 12 active markets during
that validation window, and the then-current fleet observability report was
collection-only critical. The later strict report regenerated at
`2026-06-15T04:08:04Z` found post-startup CLOB book-tape gaps too; the current
state is recorded in the CLOB tape-audit update below.

Feature-wiring update (2026-06-14 UTC): `src.market_microstructure_features`
now converts the fast CLOB book tape into band-level model features for book
age, midpoint, spread, depth, imbalance, liquidity, midpoint change, stickiness,
model edge to midpoint, and market-vs-midpoint residual. `src.pooled_candidate_replay`
joins those features into band-binary candidate rows through a normalized
market/snapshot/band key. A live active-tape audit found an F-market coverage
bug: snapshot rows used labels like `82-83 F` while leaving `bin_value_hi`
blank, so only threshold bands matched the CLOB book key. The feature key now
derives the missing high value from the label; direct pooled replay also uses
that normalized high bound, and `src.promotion_refresh` forwards the CLOB
max-age window into candidate replay. Active June 13 tapes now produce
`17,380 / 17,380` CLOB feature rows with available book data, and
`src.market_microstructure_features --market all --json` materializes
`clob_features_long.csv/jsonl` for all active markets. Focused validation:
`pytest tests\market\test_market_microstructure_features.py tests\calibration\test_pooled_feature_model.py tests\calibration\test_pooled_candidate_replay.py -q`
passes, and `compileall` passes for the changed modules. Remaining item-38
acceptance is to train/shadow-score a microstructure-aware artifact and prove
settlement or P&L lift on the casebook market-lead/overreaction slices.

Microstructure scoring update (2026-06-14 local): `src.pooled_candidate_replay`
now trains a non-serving CLOB overlay behind the promotion gauntlet. The overlay
uses only replay rows with fresh book features, scores out-of-fold by held-out
target date, writes the shadow artifact
`artifacts/models/hgb/feature_model_hgb_f_pooled_clob_overlay_v0_2.pkl`, and
adds an Item 38 section to both `pooled_candidate_replay_latest_report.md` and
`f_family_promotion_refresh_report.md`. The current refresh scored 19,668 CLOB
rows with zero skipped folds: raw overlay Brier `0.0303` versus base candidate
`0.0376`, current replay `0.0389`, and market `0.0299`.

Taxonomy-gate update (2026-06-14 local): the overlay now has an explicit
replay-derived allowlist. It can affect only target taxonomies that beat both
the base candidate and market on the same out-of-fold slice; all other rows
fall back to the base candidate as `micro_gated_candidate_p`. The current gate
allows `market_lead` and `book_liquidity_artifact`, and blocks
`market_overreaction` because it regresses the base candidate (`0.1700` vs
`0.0983`). The gated overlay changes 437 rows and leaves 66,993 rows on the
base candidate; aggregate gated Brier is `0.0436` versus base `0.0436`.

Fleet critical follow-up (2026-06-14 UTC): the observation-trigger watcher made
urgent recomputes first-class evidence, but active CSV tapes created before the
new cadence column could make scheduled captures appear gappy late at night.
`SnapshotStore` now measures scheduled due time against the last scheduled
capture, and `src.collection_health` scopes strict gap detection to the 12:00-
18:00 settlement-decisive window while still requiring the tape to span that
window. Covered WU historical gaps and recognized legacy artifact schemas no
longer produce fleet warnings. `src.fleet_observability report --strict` remains
critical, as intended, when the active day's immutable snapshot tapes contain
true collection gaps; the 2026-06-14 report is collection-only critical after
the CLOB loop was restarted and validated.
