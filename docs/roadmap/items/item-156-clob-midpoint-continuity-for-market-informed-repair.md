# 156. CLOB Midpoint Continuity For Market-Informed Repair [OPEN 2026-06-20 - LOCAL RAW RESTORE ABSENT, FUTURE TRAIN DAYS NEEDED]

Goal: make market-informed CLOB repairs usable as split-stable evidence by
collecting and auditing raw token/book tapes with enough midpoint coverage on
the training side of chronological validations.

Source: Items 35, 48, and 147 all found the same blocker. Market-informed
anchors show value on later rows when CLOB midpoints exist, but selection splits
have little or no train-side midpoint coverage. Existing generated
`clob_features_long.csv` rows are not enough; the raw token map and raw
order-book tapes must be present so midpoint availability can be audited and
replayed from source evidence.

Current evidence:

- Item 35 blocked-market CLOB audit:
  `data/backtest/item35_exact_source_guard_recent40_clob_coverage_audit_report.md`
  has 15 folders, 5 with midpoint availability, 9 missing raw tape/token maps,
  and 1 one-sided/no-midpoint folder. Train-side CLOB midpoint coverage was
  `0.0000` while eval-side coverage was `0.1761`.
- Item 147 blocked-market CLOB audit:
  `data/backtest/item147_blocked_markets_clob_coverage_audit_report.md` has 20
  folders, 8 with midpoint availability, 10 missing raw tape/token maps, and 2
  one-sided/no-midpoint folders. Train-side CLOB midpoint coverage was `0.0000`
  while eval-side coverage was `0.2413`.
- Fleet data-layer audit now surfaces this as a durable raw-artifact count:
  `96/177` snapshot folders have token artifacts and `84/177` have raw-book
  artifacts; among `165` training-ready folders, only `84` have token artifacts
  and `72` have raw-book artifacts.
- The combined Item 32/35/48 v0.3 CLOB audit:
  `data/backtest/item32_35_48_combined_replay_clob_coverage_audit_report.md`
  source; all `24` June 12/13 eval folders do have full raw restore sources.

Why this matters: CLOB/market-informed policies can be valid quote-time
stabilizers, but they cannot prove no-market model edge. They also cannot be
selected safely when the earlier-date split has no raw midpoint evidence. This
item owns the collection continuity needed before Items 35 or 48 can use CLOB
midpoint anchors as promotion-supporting market-informed evidence.

## Design

1. Keep the fast CLOB book supervisor and token discovery running for every
   active weather market from market open through settlement.
2. Require raw `clob_tokens` and raw `order_books` evidence before a day can be
   used for market-informed anchor selection.
3. Report midpoint coverage by market, target date, chronological split, and
   blocked-market cohort.
4. Return `BLOCK` for market-informed selector reports when train-side midpoint
   coverage is below the declared threshold, even if eval-side CLOB appears
   useful.
5. Keep no-market weather candidates and market-informed quote/risk overlays
   separated in promotion reports.
   rerun the selector from source tapes.

- [x] Define the minimum train-side midpoint coverage threshold for split-safe
  market-informed selector evidence.
- [x] Add or refresh a CLOB continuity report that summarizes midpoint coverage
  by chronological split for Items 35/48/147 blocker cohorts.
- [ ] Keep the active CLOB supervisor green through enough future settled days
  to create train-side midpoint coverage for NYC, Seattle, San Francisco,
  Austin, Los Angeles, Toronto, and Chicago repair cohorts.
- [ ] Rerun market-anchor validation only after train-side coverage clears the
  threshold.
- [x] Keep market-informed repair output classified separately from no-market
  model-promotion evidence.

Acceptance: a market-informed anchor or CLOB midpoint repair may support Items
35 or 48 only when the selector report proves nonzero, threshold-clearing
train-side midpoint coverage from raw token/book tapes, passes chronological
validation without eval-only selection, and its promotion report preserves
market-informed classification.

## 2026-06-19 split coverage gate implementation

`weather.reporting.clob_coverage_audit` now emits
`clob_coverage_audit_v0.2`. It parses market and target date from snapshot
folder slugs, builds the same earlier-date/later-date chronological split used
by the market-anchor validators, and writes a `split_coverage_gate`. The gate
defaults to requiring at least `0.0500` train-side midpoint coverage and at
least one train folder with midpoint evidence before market-informed anchors
can be treated as split-stable development evidence.

Regenerated blocker-cohort evidence:

- Item 35:
  `data/backtest/item35_exact_source_guard_recent40_clob_coverage_audit_report.md`
  now reports split gate `BLOCK`: train folders `7`, train midpoint coverage
  `0.0000`, train midpoint folders `0`; eval folders `8`, eval midpoint
  coverage `0.1761`, eval midpoint folders `5`.
- Item 147:
  `data/backtest/item147_blocked_markets_clob_coverage_audit_report.md` now
  reports split gate `BLOCK`: train folders `10`, train midpoint coverage
  `0.0000`, train midpoint folders `0`; eval folders `10`, eval midpoint
  coverage `0.2413`, eval midpoint folders `8`.

Verification:
`python -m pytest tests\reporting\test_clob_coverage_audit.py -q` passed with
`6 passed`.

## 2026-06-19 market-anchor selector gate

`weather.reporting.market_anchor_validation` now emits
`market_anchor_time_split_validation_v0.2` and returns readiness `BLOCK` when
`clob_midpoint` is part of the evaluated source set but train-side midpoint
coverage is below the configured selector threshold. The default threshold is
`0.0500`, exposed as `--min-train-clob-anchor-coverage`.

Regenerated Item 147 anchor evidence:

- `data/backtest/item147_blocked_markets_clob_anchor_validation_report.md`
  stays `BLOCK`. The selected daily-first holdout is unchanged at candidate
  `0.0465` versus market `0.0359` (`+0.0106`), and the new train-side CLOB
  anchor gate is `BLOCK`: coverage `0.0000`, train anchor rows `0`, minimum
  `0.0500`. Eval-side CLOB remains useful when present: CLOB Brier `0.0538`
  versus candidate `0.0780`, oracle daily-first gap `+0.0044`.
- `data/backtest/item147_blocked_markets_market_anchor_validation_report.md`
  also stays `BLOCK`. Market-price anchoring shrinks selected daily-first gap
  to `+0.0035`, but Los Angeles and NYC still block, the report remains
  no-edge serving-safety evidence, and the CLOB train-side gate still blocks
  because `clob_midpoint` is evaluated.

Verification:
`python -m pytest tests\reporting\test_market_anchor_validation.py tests\reporting\test_clob_coverage_audit.py -q`
passed with `14 passed`.

## 2026-06-19 promotion-readiness market-informed guard

`weather.reporting.promotion_refresh.promotion_readiness` now adds a blocking
`market_informed_candidate` readiness row when the replayed candidate shadow
variant declares `uses_market_features=true`. This keeps CLOB/market-informed
lanes usable for shadow reports, quote/risk gates, and serving-safety
diagnostics, but prevents them from satisfying the weather-only core promotion
readiness artifact.

Verification:
`python -m pytest tests\calibration\test_promotion_refresh.py -q` passed with
`30 passed`.

## 2026-06-19 capture-status tape implementation

The CLOB capture path now writes a per-folder append-only
`clob_capture_status.jsonl` row for each token/book capture attempt. The status
row uses schema `clob_capture_status_v0.1` and records the event, market,
capture time, selected outcomes, token count, book count, level count,
price-history rows, WebSocket rows, derived CLOB feature rows, artifact paths,
and any failure stage/error. Book-fetch and price-history exceptions still
re-raise, but the folder now retains enough evidence to tell whether a missing
raw tape means capture never ran, no active tokens were discovered, no books
were returned, or the capture errored.

`data_layer_audit` now counts `clob_capture_status.jsonl` separately from raw
token and raw-book artifacts, and the Markdown report renders a `CLOB Status`
column by market. Fresh fleet evidence:
`data\backtest\data_layer_audit_after_clob_capture_status_report.md` is
`WARN` and reports `12/177` folders with capture-status rows, but `0/165`
training-ready folders with capture-status rows. Token and raw-book coverage
remain unchanged from the prior blocker boundary: `96/177` token-artifact days
and `84/177` raw-book artifact days; among training-ready folders, `84/165`
and `72/165`.

This is a forward logging/diagnostics fix, not a retroactive CLOB continuity
unblock. It prevents future ambiguous `missing_raw_clob_tape_and_token_map`
cases, but Item 35/48 market-informed selectors still need new settled days or
backfilled raw token/book evidence with train-side midpoint coverage above the
declared threshold.

Verification:
`python -m pytest tests\market\test_market_microstructure.py tests\reporting\test_data_layer_audit.py tests\operations\test_schema_registry.py -q`
passed with `50 passed`.

## 2026-06-20 local source-verification audit

`weather.reporting.clob_coverage_audit` now emits
CLOB restore sources. I regenerated the combined Item 32/35/48 audit with all
`data/backtest/item32_35_48_combined_replay_clob_coverage_audit_report.md`.

The continuity blocker is now sharper. The split gate remains `BLOCK`: train
folders `24`, train midpoint coverage `0.0000`, and train classifications
`{"missing_raw_clob_tape_and_token_map": 24}`. The source-verification audit proves
have `clob_features*` feature shells in the manifests, but `0/24` have raw-book
restore paths, `0/24` have token-map restore paths, and `0/24` have full raw
source availability. By contrast, all `24` June 12/13 eval folders have full
raw restore sources, which explains why eval-side CLOB can look useful while
the selector remains split-unsafe.

Item 156 therefore stays `OPEN`. The next unblock is not another local restore
predeclared train/eval market days with raw `clob_tokens*`,
`order_books*`, and `clob_capture_status.jsonl` continuity, then rerunning the
v0.3 coverage audit before any Item 35/48 market-informed repair is tried.

Verification:
`python -m pytest tests\reporting\test_clob_coverage_audit.py tests\operations\test_schema_registry.py -q`
passed with `9 passed`, and strict schema audit for
`clob_coverage_audit.py` plus `schema_registry.py` reported
`registered=201 discovered=215 unregistered_versions=0`.
