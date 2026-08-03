# Workstation handoff 2026-09-03a — build the gate that would have caught all of it

Run this now. **Build and prove: no fit, no retrain, no candidate, no fresh dates, no network, no
release-path wiring.** `-08-16a` remains queued for 2026-08-05 04:30 and takes priority.

## The observation this is built on

Look at what this month actually found:

| Defect | Class |
| --- | --- |
| 9 of 19 base features empty at 09:00–14:00 | train/serve skew |
| `forecast_high` fitted on stitched rows with no provable issue time | train/serve skew |
| Forecast-profile provenance discarded by `load_profiles` | train/serve skew |
| WU surface fields median-imputed into plausible fakes | train/serve skew |

**Four for four.** Every significant model defect this project has found in a month is the same
class: training saw one thing, serving sees another, and nothing noticed.

Now look at the check that is supposed to notice.
`reporting/scorecards/captured_input_parity_evidence.py` calls `compare_replay_to_served`. It proves
**replay reproduces serving output**. That is a reproducibility check. When serving is missing a
feature, replay is missing it identically, so the gate passes — it reported
**28,680 / 28,680 cells matching while nine of nineteen features were empty.**

We are about to lock a release whose central input-integrity check cannot see the defect class that
accounts for everything we have found. Every one of those four was caught by a human deciding to go
look. That does not scale, and it is not a control.

**Build the control.**

## You already invented the technique

`-08-30a` is the proof method, and it worked: take **one captured raw payload**, push it through the
**training-time** feature construction and the **serving-time** feature construction independently,
and compare values, units, categories and missingness field by field — plus an availability test
against the row's cutoff. That is what turned "WU parity probably holds" into a decisive answer in
one mission.

Generalize it from one market and ten fields into a standing harness over **every feature and every
registered market**.

## What it must do

1. **Same input, both paths.** For a captured payload and cutoff, construct the feature record the
   way training does and the way serving does, and diff them.
2. **Compare four dimensions, not a boolean:** value, unit, category, missingness. A boolean receipt
   is exactly what let this hide for two months.
3. **Availability, not just equality.** A field that matches but was not knowable at the row's cutoff
   is a failure, not a pass. That distinction is the entire content of `-08-30a`.
4. **Provenance, not just presence.** A field whose issue time or source identity is discarded before
   use cannot be verified later — flag it. That is how `forecast_high` stayed invisible.
5. **Name the defect.** Output should say *which field, which market, which cutoff, which dimension,
   and which direction* — not a score. Someone reading it should know what to fix.

## The acceptance test I actually care about

**Point it at the four known defects and prove it rediscovers them.**

It must independently flag: the nine empty base features at 09:00–14:00; the stitched
`forecast_high`; the discarded profile provenance; and the WU surface fields. Use the existing
evidence as ground truth — those investigations are on held branches and in the reports.

If it misses one, the harness is not finished. If it flags something we have **not** found by hand,
that is the most valuable output this mission could produce and I want it called out at the top of
the report.

Also report its false-positive behaviour honestly. A gate that cries wolf gets ignored, and an
ignored gate is worse than no gate because it looks like coverage.

## What I am not asking for

**Do not wire it into the release path.** The build window is open and I want that code still. Build
it standalone, prove it, and **propose** where it should bind and with what severity — advisory
first or blocking immediately, and what a legitimate exception looks like. I will decide the binding.

Do not fix any defect it finds. Report them.

## What I want back

1. The harness and gate, with tests, on a branch off `master` @ `9275a41e`.
2. Proof it rediscovers all four known defects, independently.
3. Anything it found that we did not already know.
4. Honest false-positive characterisation.
5. Your binding proposal, with severity and exception semantics.
6. Which files are roll-sensitive under the **loaded-module closure** — note that
   `SOURCE_PATTERNS` overstates this; the three capture loops' actual scopes are in
   `data/snapshots/*_status.json` under `runtime_identity.source_scope_files`.

## Sequencing

This is the one piece of work that makes the next defect cheaper to find than the last four were. It
does not depend on release #1, the retrain, the corpus build, or any held branch.

## Constraints — unchanged

- Base on `master` @ `9275a41e`.
- **No network access.**
- **Do not read, enumerate, evaluate, or substitute 2026-07-27 → 07-31, 2026-08-01 → 08-03, or
  2026-08-06 → 08-19.** The development window and prior-year data are sufficient.
- **Do not fetch, backfill, refresh, or write any archive, artifact, sidecar, prior, or cache. Do not
  delete anything under `data/`.**
- **POST-regime rows only.** `2026-07-31` is a `rows[-1]` regime boundary.
- **Never weaken the trusted observed-high floor** — and note that a naive parity check may flag the
  floor's deliberate serve-time behaviour as a mismatch. If so, that is a finding about the harness,
  not licence to touch the floor.
- `data/` strictly read-only with the OS-level deny-write ACL; all output under one declared run root
  outside the mirror.
- **No** promotion, pointer change, serving change, scheduler change, capture restart, PR, merge, or
  master push. **No** mirror topology change, **no** ACL change, **no** paid-provider change.
- Topic branch only. Do not access the production host or the mirror sync credential.

## Handback

Push the topic branch and report the branch and commit. Lead the report with item 3 — anything it
found that we did not already know. That is the number that tells us whether this was worth building.
