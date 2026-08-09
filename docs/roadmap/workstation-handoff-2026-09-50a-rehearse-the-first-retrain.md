# Workstation handoff 2026-09-50a — rehearse the first retrain and enumerate every blocker that is NOT the archive

Written 2026-08-09 by the production agent. Read on `origin/master` and execute.

## 1. The question nobody has asked yet, created 12 hours ago

`-09-42a` — the code-owned station-day exclusion list — **landed on master at 01:20 today.** It
exists to clear the retrain's only known blocker: Denver `2025-07-28` has 17 WU hourly rows against
a floor of 18, unfillable from WU, METAR or GHCN, and it was failing **14 of 12,600 cells**
(`BLOCK 12586/12600`).

**Nobody has re-run the retrain since it landed.** So the single most important fact about this
project's #2 objective — *does the retrain corpus now complete?* — is unknown, and has been
answerable for twelve hours.

**And the retrain has never run to completion in its life.** Every attempt stopped at the corpus
gate. So beyond that gate is unmapped: nobody knows what the second blocker is, or whether there is
one, or how long the thing takes.

## 2. Why this is dispatched now instead of after the archive is extended

Production extends the forecast archive tonight (`-09-33a` made the window target-derived; the
~60-call backfill runs after 18:00). That unblocks a retrain for a **real** target like
`2026-07-31`.

> **If the archive lands and the retrain then fails for five reasons nobody enumerated, we burn days
> in round-trips at exactly the moment the critical path finally opens.** This mission converts that
> unknown into a list, in parallel, tonight.

**Do not wait for the archive. Do not use an out-of-season target.**

## 3. The trick that makes this runnable today

The current archive covers **05-10 → 06-30 only**, 52 month-days per year for 2018–2026 (verified on
production: `total_days 461`, `per_year_days` 52 except 45 for 2026). An August target gets **zero**
rows — that is the known blocker and re-proving it teaches nothing.

**So rehearse on an in-season target, where the archive genuinely has data, and the archive stops
being the blocker.** Suggested: **`2026-06-10`**. Its ±7-day target window plus history radius sits
comfortably inside 05-10 → 06-30 in every covered year. **Verify that containment yourself before
running** and state the radius you used; if you pick a different target, justify it the same way.

**This produces a throwaway candidate, not the real one.** The real first candidate targets
`2026-07-31` and needs the extended archive. **The deliverable here is the blocker list and the
runbook, never the artifact.**

## 4. P0 — run it end to end and enumerate every blocker in order

`python -m weather.operations.base_retrain --target-date <d> ...` (it requires `--target-date`).
**Everything goes to a scratch root. Nothing may be written under production `data/`.**

1. **Does the corpus now complete?** Report the cell count against 12,600 and whether the
   `-09-42a` exclusion list actually excluded Denver `2025-07-28`. **If it still blocks, that is the
   headline** and the rest of this mission is secondary.
2. **Then keep going and record every subsequent blocker in order** — the exact failure, the stage,
   and what would fix it. **Do not fix them.** One-line diagnoses of five blockers are worth far
   more than one blocker fixed, because production can then sequence the repairs.
3. **If it completes**, say so plainly and report what the run produced: stages, artifact shapes, and
   whether the outputs look structurally sane. **Do not score it, do not compare it to the
   incumbent, and do not treat any number from an in-season throwaway as evidence about the model.**

## 5. P1 — measure the resource envelope, because it decides WHERE this can ever run

Nobody knows what a retrain costs. Report **per stage**: wall-clock, peak RSS, and peak disk.

This is decision-relevant, not curiosity: the production host has **16 GB** and a live capture fleet
with a **3.49 GB per-worker** admission bar, and `maker_paper_score` already needs ~4,831 MB free to
admit. **If a retrain stage needs more than the capture host can spare, the retrain lives on the
workstation permanently and that changes the release plan.** Say which it is.

## 6. What would falsify this mission

- **The corpus still blocks.** Then `-09-42a` did not do its job, and that is the most important
  thing anyone learns today. Report it first and stop chasing later stages.
- **It completes cleanly with no second blocker.** Excellent, and say so without hedging — it means
  the archive really was the last thing.
- **The in-season target is not a valid rehearsal** — e.g. a stage hard-codes assumptions that only
  hold for the real target, so the rehearsal cannot generalize. **Then say that clearly**; a
  rehearsal that cannot predict the real run is worse than none, and knowing that is the finding.

## 7. Context you should not re-derive

- **`COMPLETE_DAY_MIN_ROWS = 18` is NOT a knob.** It also decides settlement trust and streak-day
  completeness. The fix for a short station-day is the exclusion list, **never a lower floor.**
- **`-09-49a` merges at 05:15 today** and drops `pressure`/`pressure_trend_3h` from **F-market**
  training via the registry unit (Toronto, the only C market, keeps them). Depending on when you
  start, your run may or may not include it — **record which, because it changes feature counts per
  market.** Neither state invalidates the blocker enumeration.
- **Never pool across `2026-07-31`.** For an in-season rehearsal this should not arise; say so if it
  does.
- The gap the retrain is meant to attack is the **centre**, not resolution — and §1's `74.97%` is
  **retired with no replacement**, so do not cite a payoff figure for the retrain at all.

## 8. Boundaries

`DELEGATION_CONTRACT.md` §2 in full, with **one explicit exception: fitting IS authorized for this
rehearsal**, because the mission is the run itself. That authorization is narrow:

- **Scratch root only.** Nothing under production `data/`, no pointer updated, no release touched.
- **Register nothing, promote nothing.** The candidate produced here must not be referenced by any
  manifest, pointer, or gate, and must not be offered as the first retrained candidate.
- Place no order, enable no live trading, call no exchange or weather-provider endpoint beyond what
  the retrain itself performs from the **existing local archive** — and if a stage tries to fetch
  from a provider, **stop and report it** rather than letting it run.
- Do not run the chain, settle a date, or restart a loop. **Never weaken the serving floor.**

## 9. Branch and report

- Branch: `codex/workstation-rehearse-the-first-retrain-2026-09-50a`
- Report: `docs/roadmap/agent-report-2026-08-13-workstation-retrain-rehearsal.md`

Base on `origin/master`. Per `DELEGATION_CONTRACT.md` §5, with production-host reproduction paths and
a per-file roll verdict from `scripts\ops\roll_verdict.ps1 -Branch <branch>` — **never hand-derived.**
A report-only branch should come back ROLL-FREE; if you add code, expect otherwise.
**Commit and push whenever you finish, at whatever hour.**
