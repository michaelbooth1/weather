# 282. Maker Parallel CLOB Raw-Book Refresh SLA [COMPLETE 2026-06-24 - PARALLEL RAW-REFRESH AND SPLIT FRESHNESS LANDED]

Goal: make all-market CLOB raw-book freshness fast enough for maker evidence
without manual per-market refreshes.

Source: item 277 recovery proved two consecutive all-market maker sessions can
pass after fresh raw CLOB books are written, but the operational path was still
too manual. A direct all-market CLOB capture with derived feature refresh ran
longer than the freshness SLA and timed out during audit. Parallel per-market
captures that skipped derived CLOB feature refresh completed quickly and allowed
the proof runs to pass.

Why this matters: market-making evidence depends on current books across all 12
markets. If raw-book refresh competes with heavier derived feature generation,
the maker can lose countable active-day evidence even when the exchange data is
available. Faster collection gives model-variant bakeoffs and clustered
promotion gates more independent market-time slices per day.

## Design

1. Split raw CLOB book capture from derived feature refresh in the supervisor
   contract: raw books own the sub-120-second maker freshness SLA, while band
   features run asynchronously and cannot block raw-book writes.
2. Add a parallel all-market raw-book refresh command or supervisor mode that
   captures each active market independently, caps per-market latency, and
   reports slow or failed markets explicitly.
3. Teach the CLOB loop status to expose per-market raw-book age, last useful
   raw-book write, useful raw-book iteration count, and derived-feature lag as
   separate fields.
4. Have maker preflight/liveness remediation prefer the fast raw-book refresh
   path when only CLOB books are stale, instead of invoking the heavier
   all-market derived feature path.
5. Preserve derived CLOB feature coverage for paper scoring and diagnostics,
   but gate maker countability on raw-book freshness first and derived-feature
   freshness only where a quote decision actually consumes those features.

- [x] Add an operator-accessible capture flag that can skip derived CLOB feature
  refresh for fast raw-book collection.
- [x] Add a parallel all-market raw-book refresh command or CLOB supervisor mode
  with per-market timeout and failure accounting.
- [x] Separate raw-book freshness and derived-feature freshness in CLOB loop
  status artifacts.
- [x] Wire maker preflight remediation to use the fast raw-book refresh path for
  stale-book-only failures.
- [x] Add tests proving all-market raw-book refresh stays independent from
  derived feature generation failures and reports per-market lag.

Completion note (2026-06-24): `weather.market.market_microstructure raw-refresh`
now performs parallel raw CLOB book refresh with per-market timeout/failure
accounting and skips derived feature work. CLOB loop health/status separates
raw-book age/useful iterations from derived-feature lag/errors, and maker
preflight remediation now points stale CLOB book blockers at the fast raw-refresh
path.

2026-07-12 supervisor-contract closure: the managed loop now uses the bounded
parallel raw-refresh path by default, with at most 12 workers, a 20-second
per-market deadline, strict `<120s` normal and `<30s` near-close fleet
contracts, named timeout/failure markets, and a non-overlap lock that prevents
a timed-out market worker from racing a later raw-tape writer. Enrichment flags
are rejected in the critical loop rather than silently restoring the previous
mixed path. The separate enrichment loop cannot write token/book tapes or the
raw loop status. Deployment and a clean forward cadence proof remain Item 321
operational evidence; no live task was manually restarted for this
implementation (the existing supervisor may re-adopt changed code on its own).

Acceptance: an unattended all-market CLOB supervisor or remediation command
keeps all 12 active markets' raw CLOB books within the maker freshness SLA
without manual per-market shell fan-out, surfaces any slow markets by name, and
does not let derived feature generation delay raw-book writes needed for
countable maker evidence.

Related: items 66, 124, 202, 220, 260, 277, 280.

## Completion Notes

Validated in the 2026-06-24 complete-roadmap sweep:

- `ROADMAP.md` and this item file both mark the item `COMPLETE` with status text `COMPLETE 2026-06-24 - PARALLEL RAW-REFRESH AND SPLIT FRESHNESS LANDED`.
- The file contains 5 checked implementation checklist item(s); no unchecked implementation checklist items remain.
- Validation result: accepted as properly implemented for this completed disposition based on the existing checked implementation evidence; no active roadmap work was reopened for this item.
- Future validation should rerun `python -m weather.reporting.roadmap.roadmap_backlog --fail-on-lint` and the referenced modules, generated artifacts, and checked implementation bullets in this file.

