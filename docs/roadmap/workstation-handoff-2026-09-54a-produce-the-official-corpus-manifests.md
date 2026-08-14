# Workstation handoff 2026-09-54a — produce the official base and PIT corpus manifests

Written 2026-08-09 by the production agent. Read on `origin/master` and execute.

## 1. Where the chain stands

`-09-53a` **closed the circularity**: first-party lineage bound all **12,600 / 12,600** cells, a
scratch parent verified as `research_only` (12 shadow markets, 84 base roles, no pointer), and
**`base_retrain` accepted it and reached preflight for the first time in this project's life.**

**It then blocked on the missing official base and PIT forecast corpus manifests.** That is now the
binding blocker on objective #2, and it is the fifth in this chain. `-09-50a` saw the same defect
from the other side: *"the only retained research corpus manifest has the wrong schema and target,
and it is rejected outright by the immutable PIT-corpus verifier."*

`base_retrain` consumes them as `--base-retrain-corpus-manifest` and
`--base-retrain-pit-forecast-corpus-manifest`.

## 2. P0 — what produces these, and can it run here?

**Answer in this order.**

1. **What is the official producer of each manifest?** Name the module and command, not a
   description. Candidates already in the tree: `pooled_feature_assembly.py`,
   `pooled_feature_cli.py`, `base_model_candidate.py`, and the
   `point_in_time_preselection` / `point_in_time_production_qualification` steps in
   `nightly_retrain.py`. **Read them; do not infer from names.**
2. **What exactly is wrong with the retained one?** `-09-50a` says wrong schema *and* wrong target.
   Separate those: a wrong **target** is regenerable, a wrong **schema** may mean the producer
   itself is stale. State which, with the expected-vs-actual schema id.
3. **Can the producer run on current master with current data?** If it needs the extended forecast
   archive, **say so** — production runs that backfill and it changes the sequencing. If it needs
   something that does not exist, that is the sixth blocker and the finding.

## 3. P1 — produce them to a scratch root and get past preflight

If the producer can run, **run it to a scratch root** and carry `-09-53a`'s rehearsal one step
further: **does `base_retrain` clear preflight with these manifests?**

- If yes and it proceeds to fit: **report the fit stage's wall-clock and peak RSS.** That number is
  still unmeasured and it decides whether the retrain can ever run on the 16 GB capture host.
  Corpus assembly was 315.83 MiB; the fit is the unknown.
- **You do not have to complete a full retrain.** Clearing preflight is the win.
- If a sixth blocker appears, **name it and stop.** Diagnosing it is worth more than fixing it.

## 4. The trap to avoid, stated plainly

**Do not hand-author a manifest to get past the gate.** These manifests are the lineage record that
makes a candidate auditable; a hand-made one produces a candidate that *looks* qualified and is not.
If the only way past is to write one by hand, **that is the finding — report it and stop.**

Equally: **do not weaken the PIT verifier.** `-09-53a` set the standard here by generalizing a
contract without relaxing it — the old branch preserved verbatim, the new branch stricter, unknown
inputs fail-closed. **Match that standard.** A check that rejects our input may be correct.

## 5. What would falsify this mission

- **The producer needs the extended archive.** Then this is sequenced behind production's backfill
  rather than blocked, and saying so promptly is the whole value.
- **The retained manifest's schema is stale because its producer was superseded.** Then the fix is
  identifying the current producer, not regenerating with the old one.
- **Preflight clears and a sixth blocker appears.** Expected; name it precisely.
- **It clears entirely and the fit begins.** Then report resources and stop at a sensible boundary —
  do not let an unbounded fit run on a host you are also measuring.

## 6. Context you should not re-derive

- **`COMPLETE_DAY_MIN_ROWS = 18` is not a knob.** It also decides settlement trust and streak-day
  completeness.
- **Never pool across `2026-07-31`** (artifact provenance boundary, anchor `b77cfbed`).
- **Nothing is reserved.** `reserved-confirmation-window.md` wins over every other document; check it
  at run time and declare no reservation.
- `-09-49a` (queued) drops `pressure`/`pressure_trend_3h` from **F-market training** via the registry
  unit; Toronto, the only C market, keeps them. If it has landed when you run, feature counts differ
  per market — **record which state you ran in.**

## 7. Boundaries

`DELEGATION_CONTRACT.md` §2 in full, with the same narrow exception as `-09-53a`: **you may run
producers and any fitting they require, against SCRATCH roots only, stated explicitly.**

- **The production release store must stay empty and its pointer absent.** Verify and state it.
- Nothing under production `data/`. No promotion, no activation, no order, no live trading, no chain
  run, no settlement, no loop restart. **Never weaken the serving floor.**
- Call no weather-provider endpoint. If a producer tries to fetch, **stop and report** — production
  owns the archive backfill.

## 8. Branch and report

- Branch: `codex/workstation-produce-the-corpus-manifests-2026-09-54a`
- Report: `docs/roadmap/agent-report-2026-08-17-workstation-corpus-manifests.md`

Base on `origin/master`. Per `DELEGATION_CONTRACT.md` §5, with production-host reproduction paths and
a per-file roll verdict from `scripts\ops\roll_verdict.ps1 -Branch <branch>` — **never hand-derived.**
**Commit and push whenever you finish, at whatever hour.**
