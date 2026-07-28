# Workstation handoff — 2026-07-28c: the manifest mismatch is my host's, not yours

Your gate stopped correctly twice. The second stop found a real defect on this host, and it is
worth more than the mission it blocked. Missions 2 and 3 of `-27g` remain unrun and still wanted.

## What I found, chasing your Dallas mismatch

`20260701T002709-0400` is the Dallas market-day `2026-06-30`. In that folder,
`settlement.json` was rewritten **today at 09:46**, while every other file dates from July 1.

That is not isolated. **633 of 646 snapshot folders had `settlement.json` rewritten this
morning between 09:44 and 09:46**, by the daily chain. Median `revision_number` across those
records is **17**, and 525 of 633 sit at 10 or above — a month-old settled day is being
re-revised on essentially every run.

The cause is precise. The latest Dallas revision changed exactly three things:

| Field | Change |
| :--- | :--- |
| `finalized_at_utc` | timestamp |
| `evidence.five_time_provenance.label_finalized_at` | timestamp |
| `evidence.raw_resolution_hashes.daily_summary_sha256` | `89d8ddb9…` → `a23fcea9…` |

The third is the engine. Settlement evidence pins a **whole-file SHA-256 of
`data/wunderground/<station>/daily/daily_summary.csv`** — and `public_wu_settlement_restore`
rebuilds that file every run, appending each new day. So the hash of a growing file is being
used as evidence for a single historical day's settlement. It cannot help but change daily,
which manufactures a revision for every settled day, forever.

`settlement_bucket`, `settlement_high`, `winning_band` and `reconciliation_status` did **not**
change. The substance is stable; the evidence hash is not.

## What this means for you

Your frozen corpus cannot pin `settlement.json` bytes, or any hash derived from them, because
this host rewrites them daily. That is my defect, not a flaw in your method, and it will keep
breaking gates until it is fixed.

Until then, freeze settlement **semantically**:

- Pin the values you actually need — `target_date`, `settlement_bucket`, `settlement_high`,
  `winning_band`, `winning_band_kind`, `reconciliation_status`. Those appear stable across
  revisions, but **verify that across the revision history rather than taking my word for it**;
  if any of them move, that is a much more serious finding and I want to know immediately.
- Do **not** pin `finalized_at_utc`, `label_hash`, `previous_label_hash`, `revision_id`,
  `revision_number`, or anything under `evidence.raw_resolution_hashes`.
- Better still, copy what you freeze into your own declared output root at freeze time, so a
  corpus is genuinely immutable rather than a set of pointers into a live tree I am mutating.

Then resume `-27g` Missions 2 and 3 under the `-27b` gate, which stands unchanged.

## The question I actually want answered

Does this churn explain `NOT_ACCOUNTED_FOR`?

If artifacts are revised daily, a replay reconstructed from *today's* evidence is not
reconstructed from what existed when the output was recorded. That would make the recorded
vector unreproducible from current inputs by construction — which is exactly what you measured.

**This is a hypothesis and I have been wrong four times this week proposing exactly this kind
of tidy mechanism. Test it, do not adopt it.** A cheap first cut: for a handful of the frozen
snapshots, does the settlement evidence available *at the recorded instant* differ from what
is on disk now, and is the difference confined to the volatile fields above? If the substantive
values are stable across revisions, then revision churn **cannot** explain a changed output
vector, and this hypothesis dies immediately. Say so if it does.

## What I am not doing

I am not fixing the evidence-hash defect yet. The fix belongs in settlement finalization, which
is the code path the streak depends on, and we are 7/14 with the lock around 2026-08-03. It
lands after the lock unless the operator decides otherwise. Recording it so it is not lost.

## Guardrails

Unchanged. `data/` read-only, single declared output root, no model/blend/serving/config/
release change, topic branches only, no PR/merge/master push, NOT-DONE first-class.

## Handback

`docs/roadmap/agent-report-<date>-workstation-floor-attribution.md`: the semantic-freeze
verification (are the substantive settlement fields stable across revisions?), the churn
hypothesis result, and then `-27g` Missions 2 and 3.

Context: master `c0a57825` carries all your reports. Streak 7/14. Storage merges here at 01:15
tonight; disk recovered to 173.9 GB after the tiering fix took effect this morning.
