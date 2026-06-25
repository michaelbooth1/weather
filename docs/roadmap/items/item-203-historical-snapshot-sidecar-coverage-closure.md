# 203. Historical Snapshot Sidecar Coverage Closure [COMPLETE 2026-06-21 - SIDECAR ELIGIBILITY AND PROMOTION EXCLUSIONS LIVE]

Goal: close or explicitly quarantine historical snapshot sidecar gaps so model
training and improvement claims know which older days are fully explainable,
replayable, and promotion-eligible.

Source: the June 21 log audit found strong current-day coverage, but incomplete
sidecars across the full snapshot corpus: features on 198/201 folders,
components on 197/201, replay inputs on 195/201, variant predictions on 48/201,
CLOB books on 108/201, and price history/WebSocket events on 12/201. The data
layer audit already tracks related artifact rates, but the missing sidecars are
not yet resolved into a deterministic backfill versus evaluation-only decision.

Why this matters: the model can be scored on many legacy days, but not every
legacy day can support the same root-cause, feature, variant, or market-aware
analysis. Mixing fully instrumented and partially instrumented days without an
explicit eligibility label can make candidate comparisons and broad improvement
claims look more certain than the evidence supports.

## Design

1. Build a per-folder sidecar coverage manifest with eligibility labels:
   training-ready, replay-only, score-only, market-aware-ready, and
   explanation-ready.
2. Add deterministic backfill commands for sidecars that can be reconstructed
   from existing `snapshots_long.csv`, `snapshots.jsonl`, replay inputs, or raw
   CLOB artifacts.
3. Mark non-reconstructable legacy gaps as evaluation-only with explicit
   reasons and exclusions.
4. Require promotion/candidate reports to show coverage mix by market, date,
   sidecar class, and model variant.
5. Add data-layer gates so new active days cannot regress current sidecar
   coverage.

- [x] Add sidecar coverage eligibility labels to data-layer audit output.
- [x] Backfill reconstructable features, components, replay inputs, and variant
  prediction sidecars for legacy folders.
- [x] Mark non-reconstructable CLOB/event-stream gaps as evaluation-only where
  appropriate.
- [x] Teach candidate replay and daily learning to summarize sidecar coverage
  mix before broad claims.
- [x] Add tests for eligibility labels and promotion exclusions.

Completion notes (2026-06-21):
- Data-layer audit now emits per-folder sidecar eligibility, primary labels,
  readiness counts, deterministic backfill commands, non-reconstructable gap
  reasons, promotion exclusion samples, and an active-day sidecar regression
  WARN gate.
- Snapshot store can reconstruct core feature/component sidecars from existing
  `snapshots.jsonl` via `backfill-core-sidecars`, alongside replay,
  explanation, observation-payload, and CLOB-feature backfill recommendations.
- Daily learning and pooled candidate replay reports summarize sidecar coverage
  mix before broad model-improvement or promotion claims; candidate replay JSON
  also carries the compact sidecar eligibility payload by market and candidate
  variant.
- Tests cover eligibility labels, active-day regression gates, core sidecar
  backfill, daily-learning sidecar mix, and candidate replay promotion
  exclusion rendering.

Acceptance: every snapshot folder has an explicit sidecar eligibility class,
and broad model-improvement claims can separate fully explainable evidence from
score-only or evaluation-only legacy evidence.

## Completion Notes

Validated in the 2026-06-24 complete-roadmap sweep:

- `ROADMAP.md` and this item file both mark the item `COMPLETE` with status text `COMPLETE 2026-06-21 - SIDECAR ELIGIBILITY AND PROMOTION EXCLUSIONS LIVE`.
- The file contains 5 checked implementation checklist item(s); no unchecked implementation checklist items remain.
- Validation result: accepted as properly implemented for this completed disposition based on the existing checked implementation evidence; no active roadmap work was reopened for this item.
- Future validation should rerun `python -m weather.reporting.roadmap.roadmap_backlog --fail-on-lint` and the referenced modules, generated artifacts, and checked implementation bullets in this file.

