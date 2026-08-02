# Release #1 build runbook

Written 2026-07-31, before the lock, so the 7-day build window is **execution, not discovery**.

Everything here was verified against the live repository and the consolidated release branch
(`codex/workstation-release-consolidation-2026-08-01b` @ `44ef1b2a`, armed to merge 2026-08-01 01:15).
Commands are quoted from `docs/operations/NIGHTLY_RETRAIN_RUNBOOK.md` on that branch; preconditions
were tested by running the real gate functions, not by reading them.

This is the *first* release the project has ever built. There is no prior run to copy.

---

## 0. Preconditions — check ALL of these before spending window time

| # | Precondition | State as of 2026-07-31 | How to check |
| :-- | :--- | :--- | :--- |
| P1 | Both clocks read 14 from the same start date | 10/14, day 1 = 07-21 | `.\scripts\ops\streak.ps1` and `release_admissibility_clock grade-range` |
| P2 | `artifacts/releases/` absent **and** `current_release.json` absent | ✅ both absent | `Test-Path artifacts\releases` |
| P3 | **Clean source tree** | ⚠️ **see §1 — this fails right now** | see §1 |
| P4 | Preselection can form a contiguous 14-day window | opens 2026-08-03 | rehearsal already proved every upstream stage |
| P5 | Consolidated release branch on master | armed 01:15 tonight | `git log --oneline -1` |

P2 is required specifically by `--bootstrap-first-inactive-release`: the contract passes only when the
releases root is absent or completely empty. **Do not create anything under `artifacts/releases/`
by hand** — an existing directory, file, symlink or lock blocks the bootstrap before candidate prep.

---

## 1. The clean-source-tree gate — the first thing that will stop you

`src/weather/operations/release_candidate_build.py`:

```python
code = code_identity_provider(repo_root=args.repo_root)
if code.get("git_dirty") is not False:
    raise ReleaseLifecycleError("nightly release build requires a clean source tree")
```

`capture_code_identity` (`src/weather/operations/release_manifest.py`) computes that from:

```
git status --porcelain=v1 -z --untracked-files=all --
    . :(exclude)artifacts/releases/** :(exclude)artifacts/candidates/** :(exclude)data/**
```

Only those three paths are excluded. **`config/` and repo-root `logs/` are not.** Measured on the live
repo on 2026-07-31 before any change:

```text
git_dirty: true    →  RELEASE BUILD GATE PASSES: False
 M config/location_market_events.json
 M config/locations.json
?? logs/backfill_19a.err
?? logs/backfill_19a.json
```

Two different problems, with two different fixes:

**(a) `logs/` — permanent, fixed 2026-07-31.** Residue from the 07-21 19a backfill. Nothing in the tree
references it and nothing regenerates it, but `.gitignore` covered `*.log` and not `.err`/`.json`, so
it sat dirty forever. Now ignored (commit `aaf8252b`); the files remain on disk.

**(b) `config/` drift — recurring, and it cannot be ignored away.** `WeatherLocationConfigRefresh`
rewrites `config/locations.json` and `config/location_market_events.json` every six hours
(00:00 / 06:00 / 12:00 / 18:00). Config hashes are legitimately attested in the release manifest
(`release config hash index`), so excluding `config/` from the gate would be wrong.

> **Therefore committing the config drift is a step of the build, not a state you arrange in advance.**
> Any lead time longer than six hours is guaranteed to be re-dirtied before you start.

Immediately before the build:

```powershell
cd C:\Users\micha\Desktop\github\weather
git add config/locations.json config/location_market_events.json
git commit -m "config: scheduled location refresh drift (pre-release-build, automated)"
# then PROVE the gate is satisfied before spending window time:
$env:PYTHONPATH="$PWD\src"
.\venv\Scripts\python.exe -c "from weather.operations.release_manifest import capture_code_identity as c; d=c(repo_root=r'C:\Users\micha\Desktop\github\weather'); print('GATE PASSES:', d.get('git_dirty') is False)"
```

Do not proceed until that prints `GATE PASSES: True`. Note this commit changes no loop-loaded module,
so it is roll-free.

---

## 2. Lock day (~2026-08-03) — confirm, then freeze

1. Both clocks read **14** from the same start date. They must agree; if they disagree, stop.
2. Snapshot `clock.json` plus the receipt hashes as lock evidence before anything else runs.
3. **Regenerate both sides of the `2026-07-31` non-strict `rows[-1]` boundary.** Never mix artifacts
   across it — the boundary is a code change in `model_features.py`, so artifacts built before and
   after it are not comparable.
4. No roll-sensitive merge armed on lock night.
5. Flip the observed-floor safety monitor from alert-only to fail-closed.

---

## 3. Build the release

### 3a. Preselection source (candidate-independent)

Production mode requires the narrow `production_point_in_time_preselection_source_v1` source. The
generic candidate-scoring materialization schema is **rejected**. Two ways in — folder mode builds the
staged source for you:

```powershell
python -m weather.operations.nightly_retrain run `
  --release-candidate-mode production `
  --point-in-time-folder <snapshots-root>/<settled-event-1> `
  --point-in-time-folder <snapshots-root>/<settled-event-2>
```

The workstation rehearsal already proved this stage works on real evidence: source materialization,
hash-binding, and a valid manifest (26,884 band rows, 2,444 captured-input identities), all labels
from the ledger with no sidecar fallback. It then correctly refused to lock with only 13 days.

Ordering is fail-closed and the source's latest target date must be **no more than seven days old** —
so the source must be built inside the window, not staged early.

### 3b. First inactive release (the bootstrap)

Captured-input parity ordinarily binds the active release, which cannot exist yet. There is exactly
one sanctioned bootstrap. **Do not use `--skip-captured-input-replay-parity` to get around it** — that
generic switch hides the condition rather than attesting it.

```powershell
python -m weather.operations.nightly_retrain run `
  --release-candidate-mode production `
  --bootstrap-first-inactive-release `
  --point-in-time-source-corpus <preselection-source-v1.parquet> `
  --point-in-time-source-manifest <preselection-source-v1-manifest.json>
```

> **CORRECTED 2026-08-01 — do NOT pass `--point-in-time-source-replay-manifest
> data/backtest/promotion_corpus.json`.** That file is dated **2026-07-11**: it predates the
> `2026-07-31` `rows[-1]` boundary, so pinning it would mix artifacts across the boundary, and it is
> three weeks stale against the lock window. The sanctioned path is to **omit the flag**: for a staged
> source the prelock then copies the exact replay manifest already hash-bound by that source (the one
> §3a just built). Only pass an explicit replay manifest if it was itself generated inside the window
> and reviewed.

Success creates `IMMUTABLE_CANDIDATE` with activation `NONE`. That is the correct and complete
outcome of this step — promotion and serving stay unauthorized.

Expected outputs: `data/backtest/nightly_retrain_status.json`, `..._report.md`,
`artifacts/candidates/nightly-<UTC>/…`, and `artifacts/releases/nightly-<UTC>/release_manifest.json`.

### 3c. Verify

```powershell
python -m weather.operations.release_lifecycle_cli verify <release-id>
```

Verification independently rechecks every release file and manifest hash, the production semantic
contract, null parent and rollback target, and that the release store holds exactly one directory —
then confirms again at finalization that the active pointer is still absent.

---

## 4. Promotion (separate, reviewed, and NOT part of the build)

Promotion needs a matching promotion-decision proof **and** a fresh market-day-boundary proof:

```powershell
python -m weather.operations.release_lifecycle_cli promote <release-id> `
  --decision <reviewed-promotion-decision.json> `
  --market-day-boundary <fresh-boundary-proof.json> `
  --bootstrap-first-release
```

`--bootstrap-first-release` is the one exception for establishing a first serving identity on a
repository with no pointer. It requires the decision to declare
`"release_kind": "serving_identity_bootstrap"` alongside `decision=PROMOTE`, `gate_status=PASS`, the
exact release/manifest identity, review, and candidate-only-build proof.

Rollback is proven and available: `release_lifecycle_cli rollback --market-day-boundary <proof>`
returns a first release to the verified no-pointer state.

**Authoring the two required files:** the code contains fail-closed *validators* only
(`validate_promotion_decision`, `validate_market_day_boundary` in
`src/weather/operations/release_promotion.py`) — there is no generator. The boundary proof has a
staleness limit, so it must be written at promotion time, not staged. Field-by-field templates and a
worked validation walkthrough are the deliverable of workstation mission `-08-11a`; do not attempt
promotion before that handback is merged.

## 4a. Post-promotion cutover — the part that makes release #1 worth having

Promotion writes the pointer; nothing reloads it by itself. Long-running workers bind the release via
`worker_release_binding` and must restart to adopt it. After `promote` succeeds:

1. Restart the capture/serving workers in a controlled slot (never inside 12:00–18:00).
2. Verify binding: runtime identity carries the release, zero unbound/global-fallback rows.
3. Verify the unlocks actually unlocked — nightly retrain proceeds past
   `captured_input_replay_parity_blocked`; the settlement scorecard begins binding predictions to the
   release identity instead of `legacy-runtime:*`; `replay_cache_retention` can now classify.
4. Only then take the 32.3 GB replay-cache reclaim and CLOB tiering.

The verification checklist details are part of the `-08-11a` handback.

---

## 5. What the pointer unblocks (why this is the whole critical path)

| Blocked today | Unblocks because |
| :--- | :--- |
| Nightly retrain (`captured_input_replay_parity_blocked`, no model update since 07-12) | parity can finally bind a release identity |
| Live variant settlement scorecard (BLOCK, 0 of 41,264 partitions, fragmented `legacy-runtime:*` identities) | predictions bind to one release identity instead of per-commit pseudo-identities |
| `replay_cache` 32.3 GB reclaim (`reachability_incomplete: FileNotFoundError current_release.json`) | reachability becomes computable |
| CLOB tape gzip tiering (~15 GB/day) | same |
| MM promotion gate (`promotion_state: BLOCK` on all intents) | a promoted identity exists to gate against |

---

## 6. Known-stale gates — do not misread these as build failures

The weather-only proof packet (regenerated 2026-07-31) reports **BLOCK with 9 blockers**. Every one is
the same underlying fact — *the model trails the market* — not a plumbing defect:

| Gate | Reading |
| :--- | :--- |
| promotion refresh readiness | trails market Brier by +0.0160 |
| hourly | early-hour trails by 0.0203 (tolerance 0.0030) |
| ten-minute weak-slot | trails by 0.0176 |
| exact-band / distance-0 | trails by +0.0047 |
| source/missingness (miami) | trails by +0.0128 |
| winner-rank parity | top-hit trails by **0.1698** (tolerance 0.0200) |
| served-distribution contract | `row_export_surrogate`, `DO_NOT_CUT_OVER` |
| positive daily-first | non-countable until fleet observability is OK/PASS |

**Critical caveat:** `hourly_model_performance` and `ten_minute_model_performance` were regenerated
today but score a corpus spanning 2026-05-28 → 07-30 — entirely **before** the serving-floor fix
landed (07-31 01:15). Those historical snapshots were written by the old serving code. These gates
will keep reporting pre-fix numbers until enough post-fix days accumulate or they are measured by
replay. Do not read them as evidence the floor fix underperformed.

`fleet_observability` is CRITICAL on two alerts, and both are **stale rather than live**: the MM
evidence-starvation alert describes 2026-07-21 (before the Phase 1 schedule fix), and the
`current_code_soak` alert is the rolling restart budget (8 > 6), which ages out at 05:00 UTC.

Verified 2026-07-31: `current_code_soak` does **not** participate in `release_admissibility_clock`
grading, which keys on ledger `quality_grade == "complete"` plus source checks. **Merge-driven fleet
rolls cost promotion-evidence countability, not the streak and not the lock.**

---

## 7. Failure playbook

| Symptom | Cause | Action |
| :--- | :--- | :--- |
| `nightly release build requires a clean source tree` | config drift or new untracked file | §1 — commit drift, re-prove the gate |
| `ContractViolation: production preselection requires a contiguous 14-day window` | fewer than 14 contiguous complete days | not a defect; the window is the gate |
| bootstrap refuses before candidate prep | something exists under `artifacts/releases/` | P2 — the store must be empty |
| generic materialization schema rejected | wrong source type | use `production_point_in_time_preselection_source_v1` |
| parity blocks with no active release | expected on a new store | use `--bootstrap-first-inactive-release`, never `--skip-captured-input-replay-parity` |

## 7a. Budget the build in HOURS, not minutes

Measured on the workstation's synthetic rehearsal, 2026-08-01, on real-shaped data. **The build is a
multi-hour operation. Do not start one late in the day and expect it to finish.**

| Stage | Measured |
| :--- | ---: |
| Pooled F-band model fit | 1,499 s (~25 min) |
| Family-secondary graph | 1,853 s (~31 min) |
| Frozen promotion-corpus replay | 915 s (~15 min) |
| **One clean pass, minimum** | **~71 min** |

That is the *no-retry* floor. The rehearsal actually burned two additional family fits (1,769 s and
1,578 s) discovering input gaps before a pass, so budget several hours for a first real build and
expect at least one retry cycle.

## 7a-bis. THE BUILD CANNOT START BEFORE 2026-08-04

The workstation's lock-window sweep (2026-08-02) reported the window "NOT CLEAN" on an F-family
coverage gap for `2026-07-31` → `2026-08-03`. **Checked on the production host: that is an evidence-
horizon artifact, not a defect.** `build_family_dataset` computes live from settled market data — it
is not a cached corpus needing a manual rebuild — so a date is "missing" precisely until it settles.

Verified here: `2026-07-31` has **all 12 markets settled**, F markets included, at
`quality_grade=complete`, `settlement_source=daily_summary`,
`resolution_source_type=wunderground_history`. The sweep ran against a mirror up to 24 h stale, which
is why its FAIL begins exactly at the horizon. Its own report says the finding "begins at the mirror's
current evidence horizon; it is not a scattered recurrence" — that is the tell.

**But the real constraint it exposes is a scheduling one, and it is easy to get wrong:**

> Every locked date must be **settled** before the build, because pooled fitting refuses preselected
> dates absent from the F-family corpus. The 14th locked day is `2026-08-03`, which settles on
> `2026-08-04`. **Therefore the earliest possible build start is 2026-08-04, not lock day.**

Do not read "lock ~08-03" as "build on 08-03". On 08-03 the 14th day merely *occurs*; both clocks read
14 and the F corpus covers the whole window only the following morning. Sequence: last day settles →
confirm both clocks at 14 → confirm F coverage across all 14 dates → then build.

## 7b. Pre-lock input check — run this BEFORE lock day

The rehearsal found three defect classes in its (June) synthetic universe. **None is known to affect
the lock window, because the rehearsal never covered those dates.** Each one fails the build if it is
present, so the lock window `2026-07-21 → 2026-08-03` must be checked for all three in advance:

1. **Duplicate pinned replay identities.** Seven June folders (`06-17`, `06-18`, `06-19`, `06-20`,
   `06-22`, `06-25`, `06-28`) each contain duplicates; the bounded reader correctly refuses on the
   first one. A single duplicate inside the lock window stops the build.
2. **`too_few_replay_inputs`.** `2026-06-01` and `2026-06-02` lack the captured replay prerequisite.
3. **F-family training-corpus coverage gaps.** `06-15`, `06-16`, `06-18`, `06-24`, `06-25`, `06-26`
   are absent from the F-family corpus and were refused by pooled fitting.

Finding any of these on lock day costs the window. Finding them now costs nothing.

> **2026-08-01 status:** the workstation sweep verified 07-14 → 07-30 clean on all three classes, and
> 07-31/08-01 clean on the two replay classes. The remaining dates (08-01 F-coverage, 08-02, 08-03)
> can only be checked on the production host — mirror lag makes the workstation structurally too late.
> **No extra tooling is needed: preselection itself is the verifier.** On build day, run §3a first and
> read its exclusion list (the rehearsal proved it materializes, hash-binds, and fails safe); pooled
> fit then names any F-family coverage gap ~25 minutes in. Budget for that instead of pre-checking.

## 7c. Known diagnostic defect (real, unfixed)

`src/weather/reporting/validation/point_in_time_evaluation.py` (~line 1111):

```python
if not entries or len(entries) > max_market_days:
    raise BoundedReadError(f"market-day bound exceeded: {len(entries)} > {max_market_days}")
```

Two unrelated conditions share one message. An **empty** manifest raises the self-contradictory
`market-day bound exceeded: 0 > 60`, pointing at bounds when the real cause is an empty input.

If you see `0 > <anything>`, the manifest is empty — do not go looking at bounds.

**A reviewed fix exists** on `codex/workstation-lock-window-sweep-2026-08-02a` (`b28efa54`): it splits
the condition so an empty manifest says `replay manifest is empty`, changing no bounds, output, or
admission semantics (61 passed, 1 skipped). It is **deliberately unmerged before the lock.** The
workstation declared the roll footprint itself — `calibration/residual_distribution_v1.py` imports
`RollingOriginFold` and the fold builders from this module, putting it on the calibration path — and
taking a fleet roll for a cosmetic message, for a defect that cannot fire on a real non-empty lock, is
pure downside this close to a lock. The line above already captures its full operational value. Merge
it after the lock, in a quiet window.

## 8. Still unrehearsed

Nothing past preselection has ever run on real evidence. The workstation's synthetic rehearsal
(handoff `-08-01c`) is in flight to find those failures before the window opens. Read its ordered
failure list — classified real-defect / missing-prerequisite / synthetic-artifact — before starting
the real build, and fold anything it finds into §7.
