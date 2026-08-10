# Agent report 2026-08-15 — held release-branch audit

## Verdict

**NO: `codex/workstation-research-2026-07-22` does not close any of the three
release-bootstrap causes, and it must not be landed or mined as the fix for this
gap.** Its first-release path is explicitly production-only, it has no
research-parent bootstrap, and it predates the entire `base_retrain` lane. A
no-write rehearsal against an absent scratch release store therefore cannot
reach a `base_retrain` at all, much less one that accepts its parent.

The branch is not a small dormant release fix. It is a 191-file cumulative
research program: 72,114 insertions, 1,365 deletions, 90 importable files, six
files in live capture closures, and real serving/promotion changes. Git's
current non-checkout merge simulation reports **32 conflicts** against
`origin/master`. The original calendar reason for not landing it before the
lock has expired, but its substantive migration, serving, review, and conflict
risks have not.

The useful process finding is narrower than the handoff's first falsifier. The
branch deserved this fresh audit when Release #1 was deferred; the stale
"pre-lock" label hid that obligation. The audit shows that the branch was not a
three-week-old solution waiting to be released. The current fix still needs to
be written, but it should be a small current-master research-parent bootstrap,
not a resurrection of this branch.

## Identities and safety boundary

| Role | Identity |
| --- | --- |
| Audit base | `origin/master` at `cc71108bcebd14c0d53123d0c5cf39db7b0cb345` |
| Held branch tip | `423eaa59beee83b0345ace0027b97d4df09a0254` |
| Held branch merge base | `99c0616419ce75a402e5b752fc87b4f9bebec54c` |
| Commits on held branch | `8660df39`, `5a572372`, `423eaa59` |
| Master commits since merge base | 473 |
| Audit branch | `codex/workstation-audit-the-held-release-branch-2026-09-52a` |

`git cherry origin/master codex/workstation-research-2026-07-22` marks all
three held commits `+`; none is patch-equivalent to a commit on current master.
That does not mean none of the ideas was reimplemented. Current master and
later branches independently absorbed and evolved many release/PIT contracts.

The current confirmation reservation was checked before research: no dates are
reserved; the window is armed but undated. No target-date evidence was read.

## P0 — cause-by-cause result

| Cause from `-09-51a` | Result on held tip | Exact reason |
| --- | --- | --- |
| 1. Production bootstrap cannot be the research-only base parent | **Does not address it** | `release_bootstrap.py:177-181` rejects every candidate mode other than `production`; `:495-498` post-freeze verification again requires `candidate_mode=production` and `production_capable=true`. The branch strengthens the production bootstrap's shadow-only route but never adds a research-parent mode. |
| 2. Research bootstrap has no lineage source in an empty store | **Does not address it** | The held tree has no `all_shadow_release_bootstrap.py`. Its `_corpus_manifest()` in `release_candidate_contract.py:1062-1088` accepts lineage from the candidate bundle and raises when `selection_training`, `evaluation`, `final_refit`, or `model_input_fields` is missing. It has no current-master `--model-source-release` / verified-immutable-release override and no code-owned empty-store lineage source. |
| 3. Base retrain runs before candidate construction | **Does not address it** | The held tree has no `base_retrain.py`, no `all_market_base_retrain` command, and no base-retrain step in `nightly_retrain.planned_steps()` at `:995`. Candidate construction occurs only after the plan at `nightly_retrain.py:2449`. Removing the consumer is not sequencing it correctly. |

### Composite answer

**No supported path exists on the held branch from an empty release store to a
`base_retrain` that accepts a parent.** The branch cannot execute the named
terminal operation because the module does not exist. If its production
bootstrap were transplanted onto current master, the resulting
production-capable parent would still be rejected by current
`base_retrain.load_parent_contract()` at `base_retrain.py:499-503`, which
requires `RESEARCH_ONLY_CANDIDATE_MODE`.

This is stronger than a failed happy-path test: each available route terminates
at the same contract boundary before a model fit or release write could help.

## Empty-store conditional rehearsal

The probe ran the held tip's own parser, output guards, bootstrap evaluator,
candidate corpus contract, and module discovery against:

```text
C:\tmp\rb52a-held-empty-cc71108b\releases
C:\tmp\rb52a-held-empty-cc71108b\releases\current_release.json
```

Both paths were absent before and after. The probe made no directory and wrote
no file.

| Probe | Result |
| --- | --- |
| Scratch release store | `ABSENT` before and after |
| Scratch active pointer | `ABSENT` before and after |
| Production first-inactive bootstrap contract | `PASS`; candidate mode `production` |
| Research-only first-inactive bootstrap contract | `BLOCK`; `production_candidate_mode_required` |
| Empty candidate-bundle corpus lineage | `BLOCK`; all three partition hashes and `model_input_fields` missing |
| `weather.operations.all_shadow_release_bootstrap` | module absent |
| `weather.operations.base_retrain` | module absent |
| Production planned steps | settled freshness → daily learning → experiment queue → PIT prelock → family → pooled → registry → promotion → PIT qualification → shadow; no base retrain |
| Research planned steps | settled freshness → daily learning → experiment queue → family → pooled → registry → promotion → shadow; no parent bootstrap or base retrain |

The production output guard also reported the deliberately omitted explicit
PIT input. That is not counted as a fourth bootstrap cause: this was a
no-input, no-write route probe, not a synthetic production-corpus rehearsal.
Supplying PIT input would not change the production candidate mode or create the
missing base-retrain module.

No fit was required or performed. The cheapest falsifier was the held branch's
own explicit contract plus the absent terminal module.

## P1 — what landing the held branch would cost

### Whole-branch scope

Against its merge base, the branch changes **191 files: 72,114 insertions and
1,365 deletions**.

| Area | Files |
| --- | ---: |
| `docs/operations` | 2 |
| `docs/roadmap` | 24 |
| `src/weather/backtesting` | 5 |
| `src/weather/calibration` | 2 |
| `src/weather/market` | 3 |
| `src/weather/model` | 2 |
| `src/weather/operations` | 10 |
| `src/weather/reporting` | 61 |
| Other importable `src/weather` files | 7 |
| Tests | 76 |

The three files named in the handoff are only 1,056 added and 41 deleted lines
of this program:

| File | Added | Deleted |
| --- | ---: | ---: |
| `src/weather/operations/nightly_retrain.py` | 273 | 12 |
| `src/weather/operations/release_bootstrap.py` | 122 | 22 |
| `src/weather/operations/release_candidate_contract.py` | 325 | 7 |

Other release files alone add another 548 lines and delete 86:

| File | Added | Deleted | Material behavior |
| --- | ---: | ---: | --- |
| `release_candidate_build.py` | 126 | 19 | candidate-root and release handoff changes |
| `release_manifest.py` | 75 | 10 | link/reparse ancestry checks during immutable release creation |
| `release_artifacts.py` | 194 | 19 | pointer/release/served-artifact path verification; live closure file |
| `release_contract.py` | 5 | 0 | declares no detached promotion schema authorizing; live closure file |
| `release_serving.py` | 148 | 38 | changes actual active-release loading/deserialization; live closure file |

### Serving and promotion impact — the loud warning

**The branch changes the serving path.** `release_serving.py` adds opened-file
identity checks, reparse/symlink ancestry rejection, manifest re-reading after
verification, and an option to stop before model deserialization. Those are
plausible integrity hardenings, but they change the loader imported by live
snapshot and observation-trigger closures. The file now conflicts with current
master, which has since added inactive shadow bundle behavior. Landing the old
file or resolving it by choosing a side can remove current serving semantics.

It also changes promotion behavior:

- `release_contract.py:35` makes the supported promotion-authorization schema
  set empty.
- `nightly_retrain.py:1092-1185` projects every detached promote
  recommendation through that code-owned authorization gate.
- Unauthorized promote recommendations are converted to shadow routes;
  `nightly_retrain.py:2411-2449` then permits only an inactive production
  bootstrap build in that special shadow state.
- `release_bootstrap.py:396-442` and `:448-516` require the frozen route to be
  entirely shadow-only and continue to prohibit activation, serving, and
  promotion.

This strengthens rather than weakens the historical gate, but it is still a
behavior change to promotion and release construction. It is orthogonal to the
missing research parent.

### Does it merge now?

**No.** `git merge-tree --write-tree origin/master
codex/workstation-research-2026-07-22` reports 32 conflicts without touching a
working tree:

- 15 documentation conflicts: `NIGHTLY_RETRAIN_RUNBOOK.md`,
  `module-ownership-map.md`, generated `active-backlog.md`, and twelve add/add
  historical research reports;
- 9 source conflicts: `replay_backtest.py`, `pooled_feature_assembly.py`,
  `io.py`, `daily_refresh.py`, `daily_refresh_reporting_steps.py`,
  `nightly_retrain.py`, **`release_serving.py`**, `promotion_corpus.py`, and
  `schema_registry_data.py`;
- 8 test conflicts: app architecture, pooled preselection, module-size,
  nightly retrain, daily learning, promotion corpus, WU max-since-07:00, and
  release serving.

The 2026-08-05 held-backlog audit counted 18 conflicts and 285 intervening
master commits. The current counts are 32 and 473. The branch has become less,
not more, suitable for a wholesale merge.

## The original hold: what was real and what expired

The original record is sufficient to recover the hold's purpose:

1. The 2026-07-23 bootstrap handoff said the production host would not merge
   `423eaa59` before the streak lock because it changed the release path and
   would roll capture at the worst moment. It required an identical-input
   master-versus-hardened rehearsal first.
2. The 2026-07-24 rehearsal found the hardened branch not merge-ready: it
   required a v0.1→v0.2 operational-manifest migration (B1), its 240-character
   path ceiling rejected the long workstation layout (B2), and an unreceipted
   physical-ratchet payload caused an unhandled exception instead of a
   structured block (B3).
3. Those B1-B3 repairs landed only on the separate descendant hardening branch
   ending at `1d9d58d`; they are not in held tip `423eaa59`. The later report
   recommended that descendant only after lock and further review.
4. The 2026-08-05 backlog audit explicitly excluded the original held branch
   from the Release #1 plan because it was a broad release/PIT rewrite, not a
   focused pending fix.

The *calendar* half of the hold expired when Release #1 was deferred. The
*technical* half did not. Current master owns later A1-A6 release fixes and new
bootstrap/retrain contracts; the held tip still carries the older migration
and failure modes, plus the serving conflict. It is therefore wrong both to
keep saying only "pre-lock" and to infer that expiration makes the branch safe.

## Mechanical roll verdict for the held branch

Repository-owned result:

```text
changed: 191 file(s); 90 importable
closures: loop, clob_loop, observation_trigger
VERDICT: ROLL-SENSITIVE
```

The exact roll-sensitive files reported by
`scripts\ops\roll_verdict.ps1` are:

| File | Live closures |
| --- | --- |
| `src/weather/io.py` | `clob_loop`, `loop`, `observation_trigger` |
| `src/weather/model/model_sources.py` | `loop`, `observation_trigger` |
| `src/weather/release_artifacts.py` | `loop`, `observation_trigger` |
| `src/weather/release_contract.py` | `loop`, `observation_trigger` |
| `src/weather/release_serving.py` | `loop`, `observation_trigger` |
| `src/weather/schema_registry_data.py` | `clob_loop`, `loop`, `observation_trigger` |

The script classified the other 84 importable files as `free`. The remaining
101 changed files are non-importable documentation/tests. It warned that the
dormant `clob_enrichment` closure was fully subsumed by a live closure, so its
dormancy could not change the verdict.

## Minimal current-master fix required

There is **no extractable subset of the held branch that closes this gap**. The
minimal fix belongs on current master and should preserve the code already
proved by `-09-51a`:

1. **Cause 1 — choose the existing research route, not the production
   bootstrap.** Keep `release_bootstrap.py` production-only. Extend the current
   `all_shadow_release_bootstrap` path (or a small adjacent one-shot command) to
   create the first immutable `research_only`, `production_capable=false`
   parent from an empty store. It must remain all-shadow and non-promotable as
   production.
2. **Cause 2 — give that route a first-party lineage source that does not
   require a prior release.** Produce and verify complete
   `selection_training`, `evaluation`, `final_refit`, and
   `model_input_fields` lineage from code-owned fit/corpus receipts for the
   tracked base graph. Do not weaken `_corpus_manifest()` and do not accept an
   unauthenticated arbitrary override. Current `--model-source-release` remains
   valid for later copies but cannot bootstrap an actually empty store.
3. **Cause 3 — make parent creation/activation an explicit prerequisite before
   `all_market_base_retrain`.** The supported one-time sequence is: build the
   research parent → verify it → separately review and establish the existing
   `serving_identity_bootstrap` pointer → verify active identity → run base
   retrain. This may be an operator-owned preflight command or a fail-closed
   pre-base nightly step, but candidate construction after base retrain cannot
   satisfy the prerequisite.

The existing Release #1 deferral remains untouched. The first parent is
research scaffolding; building it does not fit the new candidate, declare a
confirmation window, or authorize the deferred production release.

## Verification

Held-tip focused suite:

```text
137 passed, 3 skipped, 14 subtests passed in 21.83s
```

Command:

```powershell
python -m pytest `
  tests\operations\test_release_bootstrap.py `
  tests\operations\test_release_candidate_contract.py `
  tests\operations\test_release_lifecycle.py `
  tests\operations\test_nightly_retrain.py `
  tests\test_release_serving.py -q
```

This establishes that the held branch's own release contracts are internally
consistent. It does not establish compatibility with current master and does
not contradict the absent-module/production-mode no-go.

Documentation audit: **PASS** (18 agent files, 739 Markdown files). Final
report-branch diff checks are repeated after the metadata binding.

## Production-host reproduction

Use the production repository and its existing interpreter. The merge-tree
command writes only temporary Git objects; it does not check out or merge a
working tree.

```powershell
Set-Location C:\Users\micha\Desktop\github\weather
git fetch --prune origin
git rev-parse origin/master
git rev-parse origin/codex/workstation-research-2026-07-22
$heldRange = `
  '99c0616419ce75a402e5b752fc87b4f9bebec54c..423eaa59beee83b0345ace0027b97d4df09a0254'
git diff --shortstat $heldRange
git merge-tree --write-tree `
  origin/master `
  origin/codex/workstation-research-2026-07-22
powershell.exe -NoProfile -ExecutionPolicy Bypass -File `
  .\scripts\ops\roll_verdict.ps1 `
  -Branch origin/codex/workstation-research-2026-07-22
```

For the focused self-consistency suite, use a detached short-path worktree:

```powershell
Set-Location C:\Users\micha\Desktop\github\weather
git worktree add `
  C:\tmp\weather-held-release-audit-09-52a `
  --detach 423eaa59beee83b0345ace0027b97d4df09a0254
Set-Location C:\tmp\weather-held-release-audit-09-52a
C:\Users\micha\Desktop\github\weather\venv\Scripts\python.exe -m pytest `
  tests\operations\test_release_bootstrap.py `
  tests\operations\test_release_candidate_contract.py `
  tests\operations\test_release_lifecycle.py `
  tests\operations\test_nightly_retrain.py `
  tests\test_release_serving.py -q
```

The decisive code checks need no release write:

```powershell
git cat-file -e `
  423eaa59:src/weather/operations/base_retrain.py
git cat-file -e `
  423eaa59:src/weather/operations/all_shadow_release_bootstrap.py
git grep -n "candidate_mode != PRODUCTION_CANDIDATE_MODE" `
  423eaa59 -- src/weather/operations/release_bootstrap.py
git grep -n "candidate bundle has incomplete" `
  423eaa59 -- src/weather/operations/release_candidate_contract.py
git grep -n "def planned_steps" `
  423eaa59 -- src/weather/operations/nightly_retrain.py
```

The two `git cat-file -e` commands are expected to exit nonzero because both
modules are absent on the held tip.

## What was not done

- No merge, PR, cherry-pick, rebase, push to the held branch, branch deletion,
  activation, promotion, rollback, pointer write, scheduler mutation, loop
  restart, chain run, settlement, order, paper order, or live trade occurred.
- No file under production `data/`, the workstation mirror, or
  `D:\weather-mirror` was written. The required roll-verdict script read only
  its retained closure status files; no other production data was used. No
  credential was read.
- No weather-provider or exchange endpoint was called.
- No model was fitted. No candidate or release was built.
- No `artifacts/releases/` directory and no `current_release.json` exists in
  the primary checkout, audit worktree, held-branch worktree, or rehearsal
  scratch root after the mission.
- The production host's store is not visible from this workstation. The
  handoff's verified empty-store fact was not re-measured; it cannot have been
  changed by this mission because no production access occurred.
- No serving or promotion floor was weakened. No source/config/test/release
  implementation was edited; this report is the only branch delta.

## Handback commit and report-branch roll verdict

- Evidence commit: `7d6f1808`.
- Final metadata commit: the pushed branch head is authoritative.
- Report branch: `codex/workstation-audit-the-held-release-branch-2026-09-52a`.
- Report file: `docs/roadmap/agent-report-2026-08-15-workstation-held-release-branch-audit.md`.
- Mechanical report-branch verdict: **`ROLL-FREE`**. The primary checkout's
  local `master` lagged `origin/master`, so the script conservatively counted
  seven changed Markdown files, zero importable files, and explicitly reported
  `(no importable files -- docs/config/tests/ps1 only)`. The actual branch delta
  against `origin/master` is this one report. The mechanical verdict is
  authoritative.
