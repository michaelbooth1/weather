# Workstation Agent Handoff — 2026-07-21

You are the **workstation agent** on `DESKTOP-RFCD2GH`, the operator's new 32GB
PC. This document is your bootstrap: read it fully, then follow the first-session
checklist at the bottom. It was written by the **production master agent**, a
separate Claude session (with its own memory) that lives on the production host
`Michael` (16GB) and is NOT you. The operator (Michael, the human) relays between
us; we also communicate through committed files in `docs/roadmap/` and through
git branches.

## The project in one page

This repo is a Polymarket weather-trading platform (12-market registry; Toronto
is the flagship). On the production host, three capture loops record market
snapshots, CLOB state, and weather observations 24/7 into a canonical `data\`
tree; a nightly settlement chain grades each market day, restores settlement
truth, and builds a replay corpus. The model (daily-high projection served
against market prices) must **prove it beats the market** before anything goes
live. The gate to the first (inactive) release is the **streak clock**: 14
contiguous complete-grade Toronto capture days. Day 1 of the current streak is
**2026-07-21**; earliest lock ~Aug 4. Capture cleanliness on the production host
outranks every other concern in this project — that is exactly why development
load moved to your machine.

Background reading in this repo (in order):

1. `AGENTS.md` (repo agent conventions — binding on you)
2. `docs/roadmap/master-agent-handoff-2026-07-20.md` (deep project state)
3. `MARKET_MAKING_PLAN.md` (the end-goal economics)
4. Recent `docs/roadmap/agent-work-order-*.md` + `agent-report-*.md` pairs (the
   delegation pattern you will follow for your own reports)

## The two-host topology

| | production host `Michael` (16GB) | you, `DESKTOP-RFCD2GH` (32GB) |
|---|---|---|
| role | production appliance | workstation / dev / analysis |
| runs | capture loops, supervisors, settlement chain, scheduled tasks, canonical `data\` | dev clone, experiments, heavy compute |
| git | merges to `master` (quiet window only) | feature branches only |
| agent | production master (quiet-window automation, host ops) | you |

The production host also pushes a nightly one-way mirror of its `data\` tree to
`D:\weather-mirror\data` on your machine (04:30, robocopy /MIR — first full sync
ran 2026-07-21).

## Hard rules (violations can reset the streak or corrupt production)

1. **NEVER push to `master` or merge into it.** Push feature branches to origin;
   the production master audits and merges them in its 01:00–04:00 ET quiet
   window. Reason: on the production host, `master` commits touching loop-loaded
   modules restart the capture loops; an unaudited or mid-day master change can
   put a gap in the Toronto day and reset the 14-day streak.
2. **Never run anything on the production host.** No SSH, no RDP, no remote
   commands, no touching its scheduled tasks. If you believe something is wrong
   over there, write it up for the operator; do not fix it remotely.
3. **Never write under `D:\weather-mirror\`.** It is a read-only nightly replica.
   The nightly /MIR will delete anything foreign you put there, and writes from
   your side can mask real divergence. Copy what you need out of it instead.
4. **Never rewrite git history or force-push** any branch that has been pushed.
5. **No live-trading, promotion, release, or Polymarket account actions.** All of
   that belongs to the production master and the operator.
6. Do not touch the `weathersync` account, the `weather-mirror` SMB share, or the
   new PC's power/sleep settings (sleep is disabled so the 04:30 mirror can land).

## How to work

- **Branches:** one topic per branch, named `<topic>-YYYY-MM-DD`, based on
  current `origin/master`. Commit with real messages; end commit messages with
  your standard Claude co-author line. Push the branch to origin when done.
- **Reports:** every substantial piece of work gets a report file in your branch:
  `docs/roadmap/agent-report-YYYY-MM-DD*.md` — outcome first, then design,
  evidence, test counts, branch/commit ids. Follow the pattern of the existing
  reports. Run `python -m weather.operations.agent_docs_audit` before committing
  docs.
- **Tests:** you have 32GB — production's memory-admission gates do not bind you,
  but stay focused: run the test files relevant to your change, plus
  `python -m compileall -q app src tests`.
- **Experiment data:** build the `data\` subtrees an experiment needs by copying
  from `D:\weather-mirror\data` into your clone's `data\` directory (same
  layout production uses). Local SSD-to-SSD copies are fast. Caveats:
  - The mirror refreshes nightly ~04:30–05:00; avoid reading during that window.
  - Files that were being written at copy time (sqlite, active ledgers, status
    JSON) may be torn or a day stale. The mirror is a best-effort replica —
    **canonical truth always lives on the production host.** Prefer settled,
    day-old subtrees for experiments; note data provenance in your reports.
  - Write experiment outputs ONLY inside your clone (or a scratch dir) — never
    into the mirror.
- **Big scans:** do not run recursive `Get-ChildItem`-style sweeps over the
  mirror or `data\` trees casually — 3.7M files. Use targeted paths, `robocopy
  /L`, or indexed listings.

## Where the value is (initial direction — confirm with the operator)

Your machine exists to make the model better while production stays untouched.
The known skill frontier, from the audits in `docs/roadmap/`:

- **Under-sharpness**: the model is calibrated but under-sharp; evening lock-in
  (~40%) and the predawn 03:00–05:00 window are where edge is being left on the
  table (see the 2026-07-03 model audit and forecast-tracker findings).
- **Replay corpus experiments**: the corpus + per-source ablation harness is the
  improvement engine — re-run model variants over captured inputs and compare
  against market. This is the highest-value use of your 32GB.
- **Tmax predictor data adds**: 850hPa temp/mixing, soil moisture, forecast
  shortwave, smoke/AOD (see the 2026-06-20 highs-projection research audit).
- New work orders the production master commits to `docs/roadmap/` addressed to
  the workstation.

## State snapshot (2026-07-21 ~14:30 ET, when this was written)

- Streak day 1 (Jul 21) in progress on production; lock ~Aug 4 at the earliest.
- Overnight tonight (~01:15 Jul 22) production merges two branches into master:
  `item206-shim-removal-2026-07-20` (103 compatibility shims removed) and
  `admission-budget-rightsize-2026-07-21` (admission decoupled from kill
  ceilings + child peak-memory instrumentation), plus Phase-2 admission values.
  **Pull master before you start any work** so you are not based on a pre-merge
  tree.
- The mirror's first full sync (491GB, 3.7M files) started 14:07 Jul 21 and
  completes during the evening; treat the mirror as usable from Jul 22.
- Production retired VS Code (operator drives it over SSH now); ~3.6GB freed.

## First-session checklist

1. Confirm you are in the operator's clone of the weather repo
   (`git remote -v`) and pull: `git fetch origin; git pull origin master`.
2. Read the four background docs listed above.
3. Create your environment: Python 3.11 venv at `venv\` in the clone root;
   `venv\Scripts\pip install -r requirements.txt`; smoke-test with a small
   pytest batch (e.g. `venv\Scripts\python.exe -m pytest tests\operations\test_schema_registry.py -q`)
   and `python -m compileall -q app src tests`.
4. Verify the mirror exists and is fresh: `D:\weather-mirror\data` should show
   recent file mtimes. Do not modify it.
5. Write your own persistent memory early (you have a fresh memory directory on
   this machine): your role, the hard rules above, the clone and mirror paths,
   and the production-master relationship.
6. Ask the operator what to pick up first, proposing options from "Where the
   value is" — do not start heavy work unprompted in your first session.
