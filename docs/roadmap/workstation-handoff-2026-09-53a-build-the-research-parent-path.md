# Workstation handoff 2026-09-53a — build the missing research-parent path

Written 2026-08-09 by the production agent. Read on `origin/master` and execute.
**This is the first build mission in this chain; the four before it were all diagnosis.**

## 1. The target, stated exactly

> **A small current-master path that creates a verified research-only parent with first-party corpus
> lineage, before `base_retrain` runs — so that a host with an empty release store can reach the
> first base retrain.**

That sentence is `-09-52a`'s conclusion and it is the acceptance criterion. **Small is part of the
spec, not a nicety.**

## 2. What is already done, so you do not rebuild it

**Start from `src/weather/operations/all_shadow_release_bootstrap.py`.** Its docstring is already
*"Build one immutable research-only all-shadow release without a pointer"*, it emits
`RESEARCH_ONLY_CANDIDATE_MODE`, and it constructs and verifies an immutable release.

**The single blocking gap is localized to one function.** `_verified_release_research_lineage()`
derives `corpus_lineage` from a **prior verified release's** `training_evaluation_corpus` role. On an
empty store there is no prior release, so lineage cannot be sourced. **That is cause 2, and it is
the thing to fix.**

`-09-50a` already proved the raw material exists: the corpus assembles **12,600 / 12,600 cells** at
**315.83 MiB peak RSS**. **First-party lineage means binding the corpus we assemble ourselves**,
rather than inheriting it from a release that does not exist.

## 3. The three causes, and which you must close

From `ESTABLISHED_FINDINGS.md` §4a-bis:

1. **The nightly bootstrap builds production-capable; `load_parent_contract` demands
   `RESEARCH_ONLY`.** `all_shadow_release_bootstrap` already emits research-only, so **using it
   instead of the nightly production bootstrap closes this.** Confirm that.
2. **No empty-store research-lineage source.** ← **the real work.**
3. **`base_retrain` runs before candidate release construction** (plan step
   `nightly_retrain.py:1327` vs `run_candidate_release_step` at `:2588`). **You do not need to
   re-order the nightly plan** — you need a path where the parent already exists before
   `base_retrain` is invoked. Say explicitly which you did.

## 4. The pointer question — resolve it, and prefer not changing `base_retrain`

`load_parent_contract` calls `load_active_release_pointer(active_pointer)` and requires
`pointer["active_release_id"] == parent_release_id`. But the bootstrap builds **without a pointer**,
deliberately.

`--active-release-pointer` **is a parameter**. So a research pointer distinct from the production
pointer may be the intended design.

**Strong preference: satisfy the existing contract rather than relax it.** If you conclude
`base_retrain`'s contract must change, that is a much bigger claim — **argue it explicitly and say
what it would permit that is currently forbidden.** Never weaken a check to make a path succeed.

## 5. Hard constraints

- **The production release store must remain empty and the production pointer absent.** Verify and
  state it at the end. All work goes to a **scratch releases root**.
- **Do not resurrect `codex/workstation-research-2026-07-22`.** It is a no-go: 191 files, 72,114
  insertions, 32 conflicts, it modifies the live serving loader and promotion contracts, and it does
  not contain `base_retrain.py` at all. Do not port from it without saying exactly what and why.
- **Do not touch the serving path or promotion contracts.** If your change appears to require it,
  **stop and report** — that is a scope change, not an implementation detail.
- **Expect ROLL-SENSITIVE** and keep the blast radius minimal. Report the per-file verdict from
  `scripts\ops\roll_verdict.ps1` — never hand-derived.

## 6. Proof required

A **scratch-root** rehearsal demonstrating, end to end: empty store → research-only parent built and
verified → **`base_retrain` accepts that parent and proceeds past `load_parent_contract`.**

You do **not** need to complete a full retrain. **Getting past the parent contract is the win**; if
you continue and hit a fourth blocker, report it as a finding rather than fixing it here.

Fitting is authorized **only** if a rehearsal step genuinely requires it, to a scratch root, stated
explicitly. `-09-50a` measured corpus assembly at 316 MiB; **the fit stage remains unmeasured, so
report its resources if you reach it.**

## 7. What would falsify this mission

- **First-party lineage cannot satisfy the contract** without weakening a verification. **Then stop
  and report** — the honest answer is that the retrain needs a contract change, and that is the
  operator's call, not a thing to slip into an implementation.
- **The change cannot stay small** — it spreads into serving or promotion. Report the minimal
  boundary you found and stop at it.
- **It works, and a fourth blocker appears immediately behind it.** Fine, and expected; name it.

## 8. Boundaries

`DELEGATION_CONTRACT.md` §2 in full, with the scratch-root fitting exception above. **Promote
nothing, activate nothing, write no production pointer, place no order, enable no live trading, call
no weather-provider endpoint.** Nothing under production `data/`. No chain run, no settlement, no
loop restart. **Never weaken the serving floor.** Never pool across `2026-07-31`.

## 9. Branch and report

- Branch: `codex/workstation-build-the-research-parent-path-2026-09-53a`
- Report: `docs/roadmap/agent-report-2026-08-16-workstation-research-parent-path.md`

Base on `origin/master`. Per `DELEGATION_CONTRACT.md` §5, with production-host reproduction paths.
**Commit and push whenever you finish, at whatever hour.**
