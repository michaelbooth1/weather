# Workstation handoff 2026-09-111f — competitor-reaction and decidedness-latency diagnostic

Written 2026-09-29 by the production agent; owner approved 2026-09-29 as a pre-registered secondary diagnostic
([Clarification 2 draft](../research/maker-replay-clarification-2-2026-09-29.md), last bullet). Base `origin/master`;
branch `codex/reaction-diagnostic-20260930`. Diagnostic only: it changes no hurdle, estimator or policy, and it must
never read quote-panel dates (2026-09-30..10-14).

## Why

The replay credits reward from captured books that never contained our quote. RE-1 measured our reward share falling
within 2-4 minutes of posting (FINDINGS_DIGEST, EF §10m). The one-sided candidate's only directional signal is
observation decidedness, whose lag to the market is unmeasured.

## Build (tool on fixtures; production runs it)

1. `reaction`: from the RE-1 session journals and 88a books on the same bands where they overlap, estimate our reward
   share over time since posting (share(t), with the number of sessions and bands behind each point). Report the
   implied reward multiplier k over a quoting hour against the replay's assumption of no reaction.
2. `latency`: from calibration dates 2026-09-27..29 only, the lag from each `wu_history_high_increased` trigger capture
   to the first 88a mid move of at least one tick on the affected band, and how often the band's mid was already outside
   [0.10, 0.90] before the trigger.
Both commands take an explicit date allow-list and refuse any panel date; bounded reads with the same caps as the
plugin; output one JSON and one Markdown summary.

## What would falsify this mission

If the RE-1 and 88a data do not overlap enough to estimate share(t) (for example, no 88a books during RE-1 sessions),
report that as the result rather than substituting another source.

## Deliverables

Fixture tests, the repo-wide audits, green CI; report `docs/roadmap/agent-report-2026-09-111f-reaction-diagnostic.md`
with the exact production command (lease, 00:30-09:00 window) and the expected input paths on production.
