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
  --point-in-time-source-manifest <preselection-source-v1-manifest.json> `
  --point-in-time-source-replay-manifest <promotion-corpus.json>
```

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

## 8. Still unrehearsed

Nothing past preselection has ever run on real evidence. The workstation's synthetic rehearsal
(handoff `-08-01c`) is in flight to find those failures before the window opens. Read its ordered
failure list — classified real-defect / missing-prerequisite / synthetic-artifact — before starting
the real build, and fold anything it finds into §7.
