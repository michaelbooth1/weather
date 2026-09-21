# Workstation handoff 2026-09-83b — finish the NBM guidance repair, and stop re-downloading the bulletin

Host: the 32 GB workstation (non-capture). Issued by the production operations agent, 2026-09-21.
Follows mission `2026-09-83a` (`codex/nbm-target-fix-20260921` @ `e1b663938`), whose handback is accepted as
**PARTIAL, stopped correctly**. `2026-09-83b` is a mission label.

## 1. Goal

Two deliverables on two branches, so each can land on production by itself:

- **Part A** — make the 83a parser repair ready for host qualification. Two of its three blockers came from errors in
  the 83a handoff and are withdrawn below; what remains is small.
- **Part B** — stop production downloading the same national bulletin about a thousand times a day.

**No forecast candidate is proposed or scored in this mission.**

## 2. Start from this — do not re-derive it

Read `AGENTS.md`, `docs/operations/STATE_OF_PLAY.md`, `docs/operations/FINDINGS_DIGEST.md`, the 83a handoff and the 83a
report. Reviewed by the production agent on 2026-09-21: the version-2 slot rule, the target-aware cycle list, replay by
recorded parser version and the archive immutability checks are accepted as built.

Measured on the production host on 2026-09-21 (light reads of today's event-day `forecast_payloads.jsonl`):

- **The fetch budget in the 83a handoff rested on a cache that does not exist. That was the production agent's error.**
  The fan-out scope is `snapshot-fleet:<pid>:<started_at>:<iteration>` (`src/weather/collection/snapshot_tracker.py`),
  and the markets fall due in different supervisor iterations, so almost nothing is shared. In the first 15 UTC hours
  of 2026-09-21 the 11 US markets wrote 783 NBM manifest rows, of which **729 were distinct network downloads of the
  ~35 MB national bulletin (24.9 GB)**; 54 were reused. Every one of those downloads found its bytes already in the
  shared payload store (`payload_blob_reused = true`, nothing written). Only six distinct cycle files exist per day.
- Production captures NBM for the current local date only: no event-day store for a later date held an NBM row today.
  The "today and tomorrow" doubling in the 83a fetch table therefore does not occur there. **The parser repair adds no
  download on production.** After 12Z it reads the 07Z file all day, which makes the repeated download pure waste.
- The manifest already records `parser_version`, `cycle_key` (issue) and `provider_update_time` (the chosen token's
  valid time); your probe shows version 2 populates `parser_version`. The national bytes are retained.

## 3. Decisions made by the production agent (do not reopen; say so if you think one is wrong)

- **The manifest requirement is withdrawn.** Parser version, issue time and valid time in the manifest, plus retained
  bytes, determine period kind, group and token index and the raw values by replay; cycle age is capture time minus
  issue time. `snapshot_store.py` stays untouched. Part A proves the derivation with a test instead.
- **The fetch-budget rule is withdrawn as a gate on the parser repair.** The waste is older than the repair and is
  fixed separately in Part B.
- **The parity CLI's BLOCK is accepted as the expected result** of the known-defect fixture (four of four defects
  rediscovered, no unexpected finding, no coverage blocker). It is not evidence against this branch. The live-only
  status of NBM fields in the historical extractor is unchanged and is not a blocker for a capture repair.
- **Provenance columns are not model inputs.** They exist so a future study can filter rows. A parser version or a
  valid hour must never be selectable as a predictor.

## 4. Part A — on `codex/nbm-target-fix-20260921`, continue from `e1b663938`

- **A1.** 83a appended the four provenance columns to `NBM_PROB_TMAX_FEATURE_COLUMNS`. That list feeds
  `US_GUIDANCE_FEATURE_COLUMNS` and so `FEATURE_COLUMNS` in `src/weather/model/feature_store.py`, and it is
  `NBM_FEATURES` / `feature_names` in the two reports under `src/weather/reporting/source_gates/`. Keep the four
  columns stored on every feature row, but move them to the category the repository uses for stored, non-selectable
  columns (read `FEATURE_DIAGNOSTIC_COLUMNS` / `FEATURE_AUDIT_COLUMNS` and their consumers first and say which you
  chose and why). Restore `NBM_PROB_TMAX_FEATURE_COLUMNS` to its original 15 names. Add a test that no training
  selection path and neither source-gate report can see the four columns as features. State whether the feature-schema
  version bump is still required after this move; keep it only if a repository rule requires it.
- **A2.** `parse_nbp_station_tmax` version 2 raises `ValueError` when `fetched_at` is naive or earlier than the issue
  time, and the live call in `fetch_nbm_probabilistic_tmax` is outside the `try`. In the live path a bad clock must
  produce `available=False` with a specific reason and a complete payload, never an exception that could cost the
  snapshot its other sources. Replay may still fail loudly. Test both.
- **A3.** The derivation test for section 3: from one version-2 manifest row written by the real writer plus the
  retained bytes, replay reproduces period kind, group index, token index, the seven raw values and the availability
  decision; a version-1 row reproduces its recorded wrong-period value. Use the 83a fixtures.
- **A4.** Edge of the search window: for a Pacific station late in the local evening the only bulletin carrying the
  day's maximum is 07Z of that UTC date, up to 24 hours old. Table, for each US timezone and each local hour 00-23,
  which cycle version 2 selects on a healthy day and its age, and what happens when that one file is a 404 (the next
  older candidate, or unavailable). No change is required unless the table shows a local hour with no reachable file on
  a healthy day.
- **A5.** Re-run the 83a final checks and the full suite (the workstation may). Update the owning source contract and
  the 83a report's verdict line by appending a dated 83b section; do not rewrite the 83a text.

Owned files for Part A: those 83a owned, plus `src/weather/model/feature_store.py` and the two source-gate report
modules only as far as A1 requires, and their tests.

## 5. Part B — new branch `codex/nbp-bulletin-reuse-20260921`, from `origin/master`

Independent of Part A; do not stack it on the parser branch.

- **B1. Design first, in the report, before code:** how a capture pass learns that the shared payload store already
  holds verified bytes for this `request_key` and `cycle_key`, from any earlier scope or process, without a download.
  A published cycle file is identified by its cycle; a new cycle is a new key, so reuse cannot serve an old forecast as
  a new one. Your 83a report named the two options (a cross-pass request/cycle index, or an explicit prefetch policy);
  choose one and say why.
- **B2. Requirements.**
  - A blob is eligible for reuse only after a completeness check on first fetch (the bulletin's own cycle matches, as
    the existing check does, and every configured US station block is present with its terminal rows). An incomplete
    first fetch is never made reusable; the next pass downloads again.
  - **Truthful attribution.** A reused row says it was reused: no network fetch counted, the original fetch time kept
    as such, and the capture time of this pass recorded separately. Nothing may make a reused row look like a fresh
    download, and cycle age is measured at the time of use.
  - **Fail open.** Any index error, missing blob, hash mismatch or lock timeout falls back to today's behaviour (a
    download). The change must not be able to cost a snapshot. No new long-held lock; no blocking wait beyond the
    fan-out's existing bound.
  - The not-yet-published case (403/404 on the newest cycle) must not be cached beyond the pass.
  - Replay, the forecast-payload migration and the parity tests pass unchanged.
- **B3. Show the effect** with the fixture probe you built in 83a: downloads per N passes and markets before and after,
  and memory held per pass (the 16 GB host decodes ~35 MB per market per pass today; do not make that worse).
- **B4.** State what else uses the same fan-out with the same per-iteration scope (other market-invariant national
  sources), whether each has the same waste, and leave them unchanged unless the change is the same one line. List
  them for the production agent.

Owned files for Part B: `src/weather/collection/forecast_payload_fetch_fanout.py`; the NBM call site in
`fetch_nbm_probabilistic_tmax`; the manifest attribution fields in `src/weather/collection/snapshot_store.py` **only if
B2's truthful-attribution rule cannot be met with the existing columns** (say which column and why); their tests; the
owning documents. Not `snapshot_tracker.py`: do not change the scope string or the supervisor loop.

## 6. Boundaries

`docs/operations/DELEGATION_CONTRACT.md` §2 binds this mission in full. In addition, as in 83a: no candidate, no fit, no
score, no outcome read; never weaken or bypass the observed-high floor; nothing under `artifacts/`; free public sources
only, serial cached requests, no refetch of a national file you hold; no credentials, no exchange calls; heavy commands
through `scripts/ops/workstation_heavy.ps1`; if a gate fails, report it and its cause, never relax or re-baseline it;
push both branches, never merge to `master`. Both branches are roll-sensitive and land in a quiet window after the
production host's own verdict and bounded suite. If a part cannot be finished inside its owned files, finish the rest
and report the exact file and reason.

## 7. What would stop or change the plan

- A1 shows the repository has no stored-but-not-selectable category => report the options; do not invent a category.
- B1 shows reuse cannot be truthful without changing the manifest schema more than one or two attribution columns =>
  stop Part B at the design and report.
- Part B makes any replay, migration or parity test fail => report; do not change the test.

## 8. Report

`docs/roadmap/agent-report-2026-09-83b-workstation-finish-the-guidance-repair.md` on **each** branch (the same file
name; each copy covers its own part), per contract §5: verdict first in bold (READY FOR HOST QUALIFICATION / PARTIAL
and why / BLOCKED and why); A1's chosen category; the A4 table; Part B's design paragraph and before/after table; test
counts; the roll verdict tool's output (the production host re-runs it); what was NOT done; reproduction commands.
