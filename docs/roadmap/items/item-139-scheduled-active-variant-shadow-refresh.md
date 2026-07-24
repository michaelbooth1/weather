# 139. Scheduled Active Variant Shadow Refresh [COMPLETE 2026-06-21 - INLINE REGISTRY EXECUTION LIVE]

Goal: make the daily refresh generate a fresh canonical multi-variant shadow
artifact for the active registry instead of reading a stale prebuilt bakeoff
CSV.

Source: 2026-06-18 model-variant data audit. `daily_refresh` currently runs
`model_variant_evidence_growth`, but the default input is the preexisting
`item86_no_market_bakeoff_multi_variant_shadow_long.csv`. If that file is
missing the step skips; if it is stale, the run still reports against stale
variant evidence. The latest local evidence showed `ALERT`: scored variant rows
grew by 269,720 while unique observations and market-days grew by 0.

Why this matters: model improvement depends on knowing how every active
variant performed on the freshest settled corpus. Reusing historical bakeoff
exports makes the learning loop look busier than it is and can mask that no new
independent evidence was collected.

## Design

1. Add a scheduled `active_variant_shadow` step before
   `model_variant_evidence_growth` in `weather.operations.daily_refresh`.
2. Load `config/model_variant_registry.json` and select active variants by
   lifecycle, track, and role.
3. Run/export each active variant against the current promotion corpus or
   replay inputs with stable observation keys.
4. Combine the exported rows through `weather.reporting.candidate_lifecycle.multi_variant_shadow`
   with shared-control deduplication enabled.
5. Write canonical outputs under `data/backtest`:
   `active_variant_shadow_long.csv`, `active_variant_shadow.json`, and
   `active_variant_shadow_report.md`.
6. Make `model_variant_evidence_growth` consume the new canonical long table by
   default, with explicit CLI overrides retained for research comparisons.

- [x] Add the daily-refresh runner and CLI flags for active variant shadow
  refresh.
- [x] Generate active no-market and market-informed shadow rows from the
  current corpus without relying on item-specific historical CSVs.
- [x] Deduplicate shared controls before scoring.
- [x] Preserve current manual `--variant-evidence-current` and
  `--variant-evidence-baseline` override behavior.
- [x] Add tests proving a daily refresh writes fresh active-variant outputs and
  evidence growth reads them by default.

Acceptance: a normal daily refresh produces a fresh active-variant shadow long
table from the current corpus, evidence-growth reporting uses that table by
default, and stale item 86 artifacts are no longer part of the scheduled
evidence path unless explicitly requested.

## 2026-06-18 implementation update

Added `weather.reporting.candidate_lifecycle.active_variant_shadow_refresh`, schema
`active_variant_shadow_refresh_v0.1`, and wired a new
`active_variant_shadow` step into `weather.operations.daily_refresh` before
`model_variant_evidence_growth`. The scheduled evidence-growth default now
reads `data/backtest/active_variant_shadow_long.csv`; manual
`--variant-evidence-current` and `--variant-evidence-baseline` overrides are
still preserved.

Generated from the current available June 18 active exports:

- `data/backtest/active_variant_shadow_long.csv`
- `data/backtest/active_variant_shadow.json`
- `data/backtest/active_variant_shadow_report.md`

The generated active-shadow status is `BLOCK`, not `OK`: it canonicalized
221,958 rows across 67,430 unique observations and deduplicated 67,430 shared
control rows, but only three active registry variants were present:
`clob_overlay_gated_taxonomy`, `clob_overlay_raw_oof`, and
`conservative_bridge_policy_v0_1`.

The active registry variants still missing from the canonical output are:

- `item50_pooled_forecast_v3_candidate`
- `pooled_continuous_density_hgb_v0_1`
- `pooled_f_candidate_miami_current_fallback_v0_1`
- `pooled_f_dynamic_source_state_v0_1`
- `pooled_f_exact_winner_catchup_v0_1`

Refreshed `data/backtest/model_variant_evidence_growth.json` and report now use
`data/backtest/active_variant_shadow_long.csv` as current evidence. The result
is still `ALERT`: scored rows increased by 87,098 versus the baseline, while
unique observations and market-days increased by 0, so broad promotion claims
remain blocked.

Follow-up after item 142: registry export contracts now exist for every active
headline variant and the no-argument active-shadow refresh resolves the
registry paths itself. A refreshed run wrote `active_variant_shadow_long.csv`
with status `OK`, 8 active variants reported, 0 missing active variants,
568,557 canonical rows, 76,879 unique observations, and 51 market-days.
`model_variant_evidence_growth` now reports `WARN` with the independent
evidence SLA passing.

Remaining acceptance blocker: the daily step still composes configured active
exports instead of executing every registry prediction function inline from the
current promotion corpus. Stale item 86 is no longer the scheduled default, but
full per-contract execution orchestration remains to close this item.

## 2026-06-21 completion update

`weather.reporting.candidate_lifecycle.active_variant_shadow_refresh` now has an inline active
registry execution runner. During a normal `daily_refresh`, when no explicit
`--active-variant-shadow-sources` override is supplied, the
`active_variant_shadow` step executes active registry contracts against the
current `promotion_corpus.json`, writes fresh registry export paths, and then
builds the canonical `active_variant_shadow_long.csv`,
`active_variant_shadow.json`, attribution sidecar, and Markdown report from
those generated paths.

The runner handles `pooled_candidate_replay` contracts directly. Derived
`conservative_bridge_policy` and `microstructure_shadow_report` runtimes are
emitted from the first successful pooled replay source in the same refresh and
are recorded in the execution provenance table. If inline execution fails to
produce source paths, the scheduled step now fails closed instead of falling
back to stale registry exports. Manual source overrides still bypass execution
for research comparisons.

Verification:

- `python -m pytest tests\operations\test_daily_refresh.py -q`
- `python -m pytest tests\reporting\test_variant_registry.py tests\reporting\test_multi_variant_shadow.py tests\operations\test_schema_registry.py tests\operations\test_import_architecture.py -q`
- `python -m py_compile src\weather\reporting\active_variant_shadow_refresh.py src\weather\operations\daily_refresh.py tests\operations\test_daily_refresh.py`

## 2026-07-23 immutable-generation hardening

Scheduled refreshes now publish the promotion corpus beneath
`promotion_corpus_generations/` using a bounded, sanitized, hash-suffixed run
identity. Reusing a run identity never overwrites evidence: the next absent
`-retry-NNNN` leaf is selected and the existing bytes remain unchanged. The
promotion step reports its exact `corpus_path`; inline active-variant execution
uses that same-run path or the exact path carried in a resume ledger, rather
than reopening the fixed legacy filename. Its window manifest is likewise
generation-scoped. Scheduled chains therefore preserve an immutable evidence
history and cannot silently mix a new shadow run with an older corpus. Direct
manual research calls may still read a deliberately supplied legacy corpus.

The scheduled promotion result also records a stable corpus receipt binding
the resolved path, byte size, SHA-256, manifest schema, semantic corpus hash,
and producing daily-refresh run. Active shadow requires exactly one successful
promotion step and re-verifies that receipt immediately before constructing its
command. Resumed runs additionally bind carried steps to the exact prior status
ledger bytes and preserve an ordered ledger-hash chain across repeated resumes.
Missing or modified corpus bytes, stale producer identity, path-only private
state, ambiguous step/result status, and duplicate or non-finite resume JSON
all fail closed before shadow execution. The legacy path-only fallback remains
available only to direct/manual research calls outside a scheduled run.

## Completion Notes

Validated in the 2026-06-24 complete-roadmap sweep:

- `ROADMAP.md` and this item file both mark the item `COMPLETE` with status text `COMPLETE 2026-06-21 - INLINE REGISTRY EXECUTION LIVE`.
- The file contains 5 checked implementation checklist item(s); no unchecked implementation checklist items remain.
- Validation result: accepted as properly implemented for this completed disposition based on the existing checked implementation evidence; no active roadmap work was reopened for this item.
- Future validation should rerun `python -m weather.reporting.roadmap.roadmap_backlog --fail-on-lint` and the item-specific `Verification:` command(s) or artifact checks listed above.
