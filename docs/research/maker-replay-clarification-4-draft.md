# Maker replay Clarification 4 — one engine-events ceiling for both of its uses (DRAFT)

**Status: prospective, UNSIGNED DRAFT for owner review. Not signed, not approved, not bound by any authorization.**
It would add to the frozen registration (`maker-replay-hurdles-preregistration-2026-09-27.md`), the frozen execution
addendum (`maker-replay-execution-addendum-2026-09-27.md`) and Clarifications 1, 2 and 3
(`maker-replay-clarification-{1-2026-09-27,2-2026-09-29,3-2026-10-01}.md`). Those documents are in `docs/research/` on
the exam tree (`origin/codex/integration-exam-20261002`), not on `master`. All five would stay unchanged. This is not an execution approval, and this draft changes no code.

No quote-panel, settlement, wallet, calibration or replay-result data was read to write this. It comes from the exam
tree at `37092926` and from fixture measurements in
[the pull-cap precheck report](../roadmap/agent-report-2026-10-03-pull-cap-precheck.md).

## Problem

Clarification 2 measures one quantity, "engine events", on each calibration date. The ceiling rule makes it
`max_events`: the largest date x 15, rounded up to a power of two. The exam code uses `max_events` for two different
counts:

1. **Heap pops.** The replay engine refuses when it pops more than `max_events` distinct clocks. The rehearsal measures
   this count, and it is the count the multiplier was designed for.
2. **Pull-opportunity candidates.** The pull endpoint counts the minute starts inside every band's active windows. It
   refuses when that count exceeds `max_events`. The scored run checks this at `engine_preflight`, before the look is
   reserved. The rehearsal never measures it, because it runs with `max_events = 2^31`.

The two counts grow differently. Candidates follow the day's **union** of captured bands: 1,260 per band per quote day
(24 h minus the 05:00–08:00 UTC maintenance window). 88a capture clocks drive heap pops. Each selected band has one
reward row a minute, plus the shared book captures and trade-stream rows. So heap pops follow the **instantaneous**
selected universe. Fixture measurements on the exam tree's own engine show that the preflight refuses when:

- **Universe churn** is high: the union of bands captured over a UTC day is about 4x or more the bands selected at any
  one instant. At the least favourable rounding the threshold is about 2.5x.
- **The panel universe outgrows the calibration universe.** With calibration churn 1.5, a panel union of 4.5x the
  instantaneous universe refused.
- **Calibration days lack per-band reward clocks.** Without them, a 12-band day refuses at a ratio of 1.58.

Any of these refusals is operational: it does not consume the look. But it stops the exam on a ceiling that no one
measured, and no rule allows raising the ceiling afterwards.

## Proposed clarification

- **Measured quantity.** For each calibration date, the rehearsal records
  `engine_events = max(largest heap pops over the rehearsal's engine passes, opportunity candidates)`.
  "Opportunity candidates" is `pull_efficiency.opportunity_candidates` over that date's rehearsal engine windows. These
  are the panel-format windows with 05:00–08:00 UTC removed, which are the windows the rehearsal already replays. Both
  terms are kept in the rehearsal record, along with which term was larger.
- **Unchanged.** The ceiling rule (largest date x 15, next power of two), the host limits, `max_outputs`, look
  protection, every hurdle, estimator, policy and report field.
- **Effect.** `max_events` is then at least 15 x the busiest calibration date's candidates. The panel's 14 quote dates
  fit when their average candidate count is at most 15/14 of that date's count. The power-of-two rounding adds up to 2x
  more. A panel that grows past this bound still refuses at `engine_preflight`, before reservation. That refusal stays
  operational, and its record names the larger universe.

## What this clarification does not do

- It does not lower or remove the pull endpoint's cap, and it does not change `opportunity_candidates`.
- It does not sample, truncate or reorder panel minutes.
- It does not decide when a code change lands. Recording the second term changes `maker_core/replay/pack_cli.py`,
  which is inside `execution_manifest.source_hashes()`. So the change would have to land and be re-pinned before the
  calibration rehearsal, and the owner decides that under the exam-period merge policy. Until then,
  `tools/exam_pull_cap_precheck.py` reports the same comparison read-only.

## Owner decision required

Sign, amend or reject. If rejected, the precheck tool stays the only guard, and its `PREFLIGHT_WOULD_REFUSE` verdict on
the calibration projection is the signal to stop before panel exports.
