# Workstation handoff `-09-16a` — clear the forecast archive gate (36 of 97 blockers)

Written 2026-08-05 by the operations master agent on the production host. Read this on
`origin/master` and execute it.

## Why this one

`-09-15a` established that **no held branch clears any of the 97 retrain blockers** — all six gates
are genuinely unbuilt work. This mission takes the largest and hardest:

```text
forecast_archive_coverage   36 blockers   <- this mission
point_in_time_forecast_binding  24        <- its seam; see P3
```

Together that is **60 of 97**. It is a hard fail, not a warning:

> `data/forecast_history/*/manifest.json` declares `season_window` = **May 10 → Jun 30**, 52
> days/year, 9 years, 226.8 MB. **A late-July-aligned training window gets ZERO rows**, so
> parent-selected `forecast_high` / `forecast_gap` would **train missing and serve populated** —
> worse skew than the WU defect that started this whole line of work.

Prior scoping is now readable on master (rescued today):
`docs/roadmap/agent-report-2026-08-03-workstation-scope-forecast-archive-extension.md` and
`…-size-the-forecast-lookahead.md`. **Read them first and say what you reused, superseded, or
contradicted.** `-09-15a` judged that neither clears the gate — verify that rather than assuming it.

## ⛔ STOP CONDITION — read before doing anything else

**The archive is NOT training-only.** `model_features.py:1636` calls
`load_forecast_daily(daily_path_for(spec))` on the **analog serving path**. Extending the archive
therefore **changes live serving inputs**. This is not a free pre-release chore.

**And: where does the additional data come from?**

- If the extension can be built from sources already captured or already licensed, proceed.
- **If it requires a new or paid provider, STOP and report.** Provider licensing is the operator's,
  closed, and **no paid-provider change may be made without explicit operator approval.** Do not sign
  up for anything, do not call an unapproved endpoint, do not assume a free tier is acceptable.

Answer the sourcing question **before** building. A beautifully engineered extension we are not
licensed to feed is worthless.

## P1 — establish what coverage is actually required

The training window must align with the target season. Determine, exactly:

- which target dates the first retrain needs forecast rows for;
- which of those the current archive covers (expected: none, given the June 30 season end);
- the precise per-market, per-date, per-cutoff matrix the preflight demands.

`-09-12a`'s preflight already encodes this. **Make it the specification** rather than inventing a
parallel one — if the two disagree, the preflight wins and you have found a second defect worth
reporting.

## P2 — extend coverage, manifest-bound

Coverage must be **cryptographically bound, never self-declared.** This is the exact defect `-09-01a`
found at the seam: a run could *assert* coverage it did not have.

Requirements:

1. An exact manifest-backed **market/date/cutoff matrix**, hash-bound.
2. **Matching feature-record provenance** — the corpus and the manifest must agree by hash, not by
   convention.
3. **Ambient `forecast_daily.csv` stays unreachable.** It is the stitched file that caused
   `forecast_high` to be non-point-in-time in the first place.
4. The extension must be **inert on the serving path until deliberately enabled**, with the enabling
   step separate, named, and reversible. Say exactly what changes for serving and when.

## P3 — the seam with `point_in_time_forecast_binding`

Gate 2 is the same data contract seen from the other side, and `build-pit-forecast-corpus-2026-08-31a`
exists as a held branch (its report is now on master).

**Do not treat these as independent.** `-09-01a`'s hard-won lesson:

> **"Wiring two independently-specified contracts together is where the real defect lives."**
> Neither branch was wrong on its own terms.

State explicitly what happens when archive coverage and PIT binding are wired together, and whether
clearing gate 1 as specified would leave gate 2 satisfiable, harder, or contradicted.

## P4 — prove it

The preflight must move **only for the gate you cleared**. Report the blocker count before and after,
per gate. **If `forecast_archive_coverage` goes to zero and any other gate's count changes without
your intending it, that is a finding, not a bonus** — say so.

The other five gates must still BLOCK. A preflight that suddenly passes is a broken preflight.

## Deliverable

1. The sourcing answer first, and the stop-condition verdict.
2. P1–P4 with evidence.
3. **Per-file roll-safety verdicts** by import closure, not the `SOURCE_PATTERNS` glob.
4. **Exactly what changes for live serving, and how to revert it.**
5. Where this belongs in the merge order — current plan is `-09-11a` → `-09-14a` → `-09-01a` alone →
   `-09-04a` → refreshed `-09-12a` + PIT seam.
6. A `## What would falsify this` section.

## Constraints

**Do not execute a retrain or any model fit. Do not change live serving behaviour in this mission** —
build the capability, leave it inert, and name the separate enabling step.

**Do not touch the release pointer or PIT release path.** The release #1 build runs on this host
tonight.

**Do not weaken the trusted observed-high floor. Do not relax the promotion gate.**

**No paid-provider signup or unapproved endpoint. No new collection without saying so first.**

**Reservation:** re-based 2026-08-04 — nothing reserved today, window armed but undated.
`docs/operations/reserved-confirmation-window.md` is the single source of truth; re-read it.

**Network:** `git fetch` and `git push`. Any other network use must be named and justified in the
report, and must not be a paid or unapproved source.

Push `codex/workstation-clear-the-forecast-archive-gate-2026-09-16a`. **No PR, no merge.** Report to
`docs/roadmap/agent-report-2026-08-05-workstation-clear-the-forecast-archive-gate.md`.

## How to disagree

If the archive cannot be extended from licensed sources, **say so immediately and stop** — that is a
material operator decision and the most valuable thing you could return. If clearing this gate would
require a serving change that cannot be made safely before release #1, say that too: the gate staying
red for a good reason is a legitimate outcome, and far better than a green gate we cannot trust.
