# Workstation handoff 2026-08-28a — scope the forecast archive extension

Run this now. **Design and feasibility only: no fetch, no network writes, no archive extension, no
fit, no candidate, no fresh dates.** `-08-16a` remains queued for 2026-08-05 04:30.

## Why this one is next

Of the three preflight blockers your own `-08-25a` found, one is now built (contiguous serving
support, in `-08-26a`), one is specified (WU parity, in `-08-21a`), and **one has never been
scoped at all**: the forecast archive.

I confirmed it directly in the manifests rather than take it on report. Every
`data/forecast_history/*/manifest.json` declares `season_window` = **May 10 → June 30**, 52 days per
year, 9 years, 226.8 MB total, all 12 generated 2026-06-23. A late-July-aligned training window gets
**0 rows** for parent-selected `forecast_high` / `forecast_gap` — fields the trees split on in
154/168 bundles. Training them missing while serving has them populated is a worse skew than the WU
defect we already know about.

So the first retrain cannot run until this is fixed, and nobody has established whether fixing it is
a morning's work or a month's.

## 1. Can it even be extended?

- Does the Open-Meteo historical-forecast API actually hold late-July/August data for the covered
  years 2018–2026, at the same variables, resolution and lead structure the current archive uses?
  `previous_runs` only starts in 2021 — say what that implies for the earlier years.
- Rate limits, request volume, wall-clock time, and failure/resume behaviour for a 12-market fetch.
- Disk. Current 226.8 MB covers 52 days/year. What does covering the serving season actually cost?
  This host has ~105 GB free and loses ~9.6 GB/day, so give me a real number, not a ratio.
- **No paid provider.** If any part of this needs one, stop and say so.

If the answer is "the data does not exist for some years", that is a finding, not a failure — the
support contract may have to be asymmetric by year, and I would rather know now.

## 2. What does extending it change at serving time?

This is the part I care most about, and the part that makes it **not** a free chore.

`model_features.py:1636` calls `load_forecast_daily(daily_path_for(self.spec))` on the **analog**
path. The archive is not training-only. Widening the season window changes which historical days are
available for analog matching, which changes live served output.

Establish precisely:

- Which served quantities move, by how much, and in which direction.
- Whether the change is confined to analog features or reaches the base feature matrix.
- **What gate this needs before it can land.** A serving-input change with no gate is exactly the
  class of thing that produced the defects we spent this week diagnosing.

If the honest answer is that the extension must be split — a training-only corpus now, the analog
widening later behind its own gate — say that. Splitting it is allowed and may well be right.

## 3. Point-in-time correctness

The archive's value depends entirely on it being what was *forecast at the time*, not what was
*observed later*. Specify:

- Issue-time provenance for every added row, and how a lookahead row would be detected rather than
  trusted.
- How the fetch avoids contaminating the reserved windows. The trainer excludes the target year, so
  establish whether 2026 rows are needed at all — if they are not, the cleanest answer is not to
  fetch them.
- The frozen missingness policy: parent-selected fields need 100% date-level coverage or an
  explicitly frozen policy proven equal at train and serve. Your `-08-25a` preflight already demands
  this; specify what satisfies it.

## 4. Give it an owner

The June freeze happened because forecast history, reanalysis and marine were **one-shot corpora
with no daily owner** — generated once on June 23, then silently aged into uselessness while
everything downstream assumed they were current.

Extending the window without fixing that just resets the same clock. Specify the ownership: what
refreshes it, on what cadence, what proves it is current, and **what fails loudly when it is not**.
A staleness check that nobody reads is not an owner.

## What I want back

1. Feasible or not, with volume, time and disk in real numbers.
2. The serving-impact analysis and the gate it requires — including a split plan if that is safer.
3. The PIT contract, including reserved-window avoidance.
4. The ownership and staleness-alarm design.
5. Your recommendation on sequencing against the WU parity repair: which of the two should be done
   first, and whether either can be done independently or they have to land together.
6. Anything suggesting this is harder than it looks. A "this is a month of work" answer is far more
   useful to me now than after we have spent the release on it.

## Sequencing

Design only. Nothing here executes before release #1 is built and the lock window closes. I am not
adding a candidate and not touching the release path while the build window is open.

## Constraints — unchanged

- Base on `master` @ `3eb4305a`.
- **Do not read, enumerate, evaluate, or substitute 2026-07-27 → 07-31, 2026-08-01 → 08-03, or
  2026-08-06 → 08-19.**
- **Do not fetch, backfill, refresh, or write any archive, artifact, sidecar, prior, cache, or marine
  path.** No network writes. Reading existing manifests and code is fine.
- **POST-regime rows only.** `2026-07-31` is a `rows[-1]` regime boundary.
- **Never weaken the trusted observed-high floor.**
- `data/` strictly read-only with the OS-level deny-write ACL; all output under one declared run root
  outside the mirror.
- **No** promotion, pointer change, serving change, scheduler change, capture restart, PR, merge, or
  master push. **No** mirror topology change, **no** ACL change, **no** paid-provider change.
- Topic branch only. Do not access the production host or the mirror sync credential.

## Handback

Push the topic branch and report the branch and commit. The answer I need most is question 2: if
widening the archive silently changes served output, that governs how — and whether — this ships at
all.
