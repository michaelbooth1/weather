# 36. Production Validation, Gating, And Promotion [COMPLETE]

Goal: a model change ships only if it provably beats the incumbent, per market.

- [x] Replay fidelity identity canary: captured replay inputs now store a
  deterministic model identity (model version, market, active kind,
  distribution-code hash, and per-market artifact hash). The replay report no
  longer treats same-label artifact changes as "same version"; those legacy
  rows are reported separately and excluded from the exact canary.
- [x] Pinned promotion corpora: `src.promotion_corpus` freezes settled
  market-day folders, accepted settlement labels, exact snapshot IDs, replay
  input hashes, tape-row hashes, and a corpus hash so promotion gates never
  compare against a silently changed corpus.
- [x] One promotion gauntlet across markets:
  `src.promotion_gauntlet` runs pinned-corpus replay, corpus-pin verification,
  exact replay-identity fidelity, regression gating, settlement
  Brier-skill-vs-market, trust context, and forecast-tracker presence in one
  report.
- [x] Per-market promotion status: the gauntlet classifies each corpus market
  as `PASS`, `SHADOW`, or `BLOCK`, so a build can be production for one market
  while remaining shadow-only elsewhere.
- [x] Failure decomposition: promotion reports now slice code-effect by market,
  capture hour, bin type, forecast-gap bucket, live-reading-gap bucket, and
  settlement-distance bucket, with blocker-market drilldowns.
- [x] Partial per-market promotion semantics: global corpus/fidelity/regression
  failures still block all markets, but a market-level block no longer erases a
  separate market's `PASS`; the gauntlet can return `PARTIAL_PASS`.
- [x] Record model cards + data snapshot + gate results for every promotion:
  replay baselines now carry corpus hash/count metadata, replay reports include
  the pinned corpus section, and the gauntlet writes a durable promotion report.

Acceptance: no model reaches a market's live serving without passing that
market's gate.

Replay fidelity increment (2026-06-11): `src.model_identity` fingerprints the
distribution-affecting code and artifacts, `snapshot_tracker` writes that
identity into `snapshots.jsonl` and `replay_inputs.jsonl`, and
`replay_backtest` gates only exact identity matches as the fidelity canary. A
forced all-market capture on the patched writer seeded exact-identity replay
records, and the next loop tick confirmed the path stayed deterministic; the
live-corpus replay report now shows Same replay identity `24`, mean L1
`0.0000`, max L1 `0.0000`, verdict `FAITHFUL`. The old June-10
same-label rows are now correctly labelled as unversioned legacy diagnostics
(mean L1 `0.0815`, max `1.0711`) instead of failing the canary. The saved
baseline-era 69-folder gate still passes at replayed Brier `0.0386` versus
baseline `0.0386`; the full 81-folder live corpus includes unfinished June 11
snapshot-high settlements and should not be compared to the older baseline
without a corpus pin.

Promotion-corpus increment (2026-06-11): `src.promotion_corpus` now builds an
auditable manifest over settled folders only, pinning accepted quality labels,
snapshot IDs, replay-input hashes, tape-row hashes, and the corpus hash.
`src.replay_backtest --corpus ...` replays only those pinned rows and uses the
manifest settlement label rather than recalculating from mutable current files.
`src.promotion_gauntlet` consumes the manifest and produces the promotion
decision: corpus pin, replay fidelity, regression gate, model-vs-market skill,
location trust, forecast tracker, and per-market `PASS` / `SHADOW` / `BLOCK`.
After June 11 settles and exact-identity rows are no longer current-day-only,
run the gauntlet with `--require-exact-identity` to make the canary mandatory
for every promotion corpus.

Decomposition increment (2026-06-11): `src.replay_backtest` now attaches
feature vectors and settlement-distance buckets to replay rows; the regenerated
promotion gauntlet report keeps the current decision at `BLOCK` but explains
why. Current promote list is empty; shadow markets are Austin, Chicago, Dallas,
Houston, NYC, San Francisco, Seattle, and Toronto; blocked markets are Atlanta,
Denver, Los Angeles, and Miami. The largest positive code-effect slice is still
market-specific rather than a corpus-pin issue.

## Completion Notes

Validated in the 2026-06-24 complete-roadmap sweep:

- `ROADMAP.md` and this item file both mark the item `COMPLETE` with status text `COMPLETE`.
- The file contains 7 checked implementation checklist item(s); no unchecked implementation checklist items remain.
- Validation result: accepted as properly implemented for this completed disposition based on the existing checked implementation evidence; no active roadmap work was reopened for this item.
- Future validation should rerun `python -m weather.reporting.roadmap_backlog --fail-on-lint` and the referenced modules, generated artifacts, and checked implementation bullets in this file.

