# Workstation handoff 2026-09-51a — map the first-release bootstrap before we spend it

Written 2026-08-09 by the production agent. Read on `origin/master` and execute.

## 1. Why this is now the top item on objective #2

`-09-50a` found that the first retrain never reaches preflight:
`base_retrain.load_parent_contract()` requires a **verified ACTIVE parent release**, and this host
has **no release store at all** (`artifacts/releases/` does not exist; `base_retrain` has **zero**
bootstrap paths). Extending the forecast archive — which production does tonight — **does not fix
this.** Release #1 was treated as *downstream* of the first retrain; the retrain needs a
release-shaped parent *first*.

## 2. THE REASON THIS IS A MAPPING MISSION AND NOT "JUST RUN IT"

`NIGHTLY_RETRAIN_RUNBOOK.md` documents exactly one fail-closed bootstrap:

```
python -m weather.operations.nightly_retrain run
  --release-candidate-mode production --bootstrap-first-inactive-release ...
```

Its contract passes **only when the release store is empty**: *"`current_release.json` is absent and
the releases root is absent or completely empty. Existing releases, files, symlinks, locks, or an
injected serving identity block before candidate preparation."*

> **Running it consumes its own precondition.** On the real store we get **one attempt**, and
> recovering from a bad one means deleting an immutable release store — which is precisely the kind
> of thing this project treats as unrecoverable. **So we buy extra attempts by rehearsing to a
> scratch root, and that is what this mission is for.**

`--releases-root` and `--active-release-pointer` are both parameters, so a scratch rehearsal is
possible without touching production's (absent) store. **Use them. Never target the real paths.**

## 3. Two known conflicts. Resolve them; do not guess.

1. **The bootstrap leaves the pointer absent — on purpose.** The runbook says it "checks again at
   whole-run finalization that the active pointer is still absent." But `load_parent_contract` calls
   `load_active_release_pointer()` and requires `pointer["active_release_id"] == parent_release_id`.
   **So the bootstrap alone cannot satisfy the retrain.** What activates it, what does activation
   require, and is activation the same act as promotion?
2. **Candidate-mode conflict.** The bootstrap runs `--release-candidate-mode production`, while
   `load_parent_contract` raises unless the parent's semantic contract is
   `RESEARCH_ONLY_CANDIDATE_MODE`. **These look mutually exclusive.** Determine whether they
   genuinely are. If they are, **that is a code-level contradiction and the headline of your
   report** — do not paper over it, and do not fix it in this branch.

## 4. P0 — produce the exact sequence from empty store to "the retrain accepts a parent"

A numbered, reproducible runbook. For **every** step: the exact command, what it writes, what it
verifies, roughly how long it takes, and **whether it is reversible.**

Mark clearly which steps are **irreversible on the real store**, because those are what the operator
is actually being asked to authorize.

## 5. P1 — the deliverable is the DECISION LIST

**This is the part I care most about.** Enumerate every point where a human must assert, authorize,
or hand-author something — this project's release path is known to need operator-asserted evidence
(hand-authored JSONs, and a boundary proof that expires in 900 s).

For each: **what is being asserted, what happens if it is wrong, and what it commits us to.**

Specifically answer: **does creating this parent commit us to anything we have deferred?**
`release-one-deferred-until-a-retrained-candidate.md` deferred Release #1 because it would *freeze
artifacts measured a full degree cool*. **Does an inactive bootstrap release freeze anything, arm a
confirmation window, or become a baseline?** If it does not, the deferral may not apply to it at all
— and saying so with evidence is the most valuable sentence you can write.

## 6. What would falsify this mission

- **The bootstrap cannot run against a scratch root** — e.g. a path is hardcoded, or a gate insists
  on the real store. **Then say so immediately**: it means the real store is our only test surface
  and the risk calculus changes completely.
- **The two conflicts in §3 are genuinely irreconcilable.** Then the retrain is blocked on a code
  change, not a decision, and that reordering is the finding.
- **The bootstrap succeeds and the retrain still cannot accept the parent.** Then there is a third
  blocker and the enumeration continues.

## 7. Context you should not re-derive

- The build is **slow** — prior synthetic rehearsal measured a **~71-minute floor**, hours in
  practice. Budget for it; do not assume a fast failure means a real one.
- **The release build has a clean-tree gate that fails on its FIRST command unless git is clean.**
  Committing config drift is a build *step*, not a workaround.
- `-09-50a` measured corpus assembly at **315.83 MiB peak RSS** — that stage is not the resource
  risk. The fit stage remains unmeasured; measure it if you reach it.
- **Nothing is reserved.** `reserved-confirmation-window.md` wins over every other document; check it
  at run time and do not declare a reservation.

## 8. Boundaries

`DELEGATION_CONTRACT.md` §2 in full, with **one narrow exception: you may run the bootstrap and any
fitting it performs, against a SCRATCH releases root only.**

- **Never write `artifacts/releases/`, never create or modify `current_release.json`, never activate
  or promote anything.** The production store must still be empty when you finish — **verify that
  and state it in the report.**
- Nothing under production `data/`. No order, no live trading, no chain run, no settlement, no loop
  restart. **Never weaken the serving floor.**
- Call no weather-provider endpoint. If a stage tries to fetch from a provider, **stop and report**.

## 9. Branch and report

- Branch: `codex/workstation-map-the-release-bootstrap-2026-09-51a`
- Report: `docs/roadmap/agent-report-2026-08-14-workstation-release-bootstrap-map.md`

Base on `origin/master`. Per `DELEGATION_CONTRACT.md` §5, with production-host reproduction paths and
a per-file roll verdict from `scripts\ops\roll_verdict.ps1 -Branch <branch>` — **never hand-derived.**
**Commit and push whenever you finish, at whatever hour.**
