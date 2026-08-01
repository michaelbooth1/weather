# Workstation release consolidation and prelock rehearsal — 2026-07-31

## Mission 1 — consolidated release path

### Outcome

The release-critical code is consolidated on one branch based on exact
`origin/master` commit `0385da72427b9cc4d556e655eedec45a49ddd253`:

```text
codex/workstation-release-consolidation-2026-08-01b
```

The branch was pushed at the untouched base before integration and pushed
again at handback. It contains the four unique second-clock/bootstrap commits
and the one unique release-one-blocker commit as one linear stack. The source
commits were replayed with `-x`, preserving their source SHAs in commit
provenance without rewriting either published source branch.

| Source branch | Source commit(s) retained | Disposition |
| --- | --- | --- |
| `codex/workstation-second-clock-bootstrap-2026-07-30f-keystone` | `deceddc7`, `63e25866`, `d8806fac`, `eadcd4b1` | Retained: release-admissibility clock, reviewed all-shadow bootstrap, verified model/corpus lineage, tests, runbook, and historical handback. |
| `codex/workstation-release-one-blockers-2026-07-29` | `0beb40b8` | Retained: first-release rollback, inactive-release forward shadow, lifecycle/serving/gate fixes, tests, runbook, and historical handback. |
| `codex/workstation-strict-parity-2026-07-29` | none | Dropped as dead for consolidation. Its code dependency is the same `0beb40b8` commit already retained above; its only unique commit, `0591e4c2`, adds a dated report and no code, tests, config, or runbook behavior. |

This is the explicit owner-approved exception to the ordinary no-cherry-pick
default: the handoff requested one rebased stack instead of three stale,
overlapping branch histories immediately before the lock. The original source
branches were not rebased, force-pushed, amended, or deleted.

### Conflict and decision log

There were **zero textual conflicts**. Every retained commit applied cleanly.
Two paths were auto-merged and received an explicit semantic review:

1. `docs/operations/NIGHTLY_RETRAIN_RUNBOOK.md`
   - Git combined non-overlapping additions from the second-clock/bootstrap
     series and the release-one-blocker commit.
   - Decision: retain both the reviewed all-shadow bootstrap procedure and the
     first-release rollback/inactive-forward-shadow procedures. No section was
     chosen over or deleted in favor of another.
2. `src/weather/schema_registry_recent_data.py`
   - Git combined non-overlapping schema registrations.
   - Decision: retain `inactive_release_forward_shadow_v0.1` together with
     `release_admissibility_receipt_v1`, `release_admissibility_clock_v1`, and
     `all_shadow_release_bootstrap_receipt_v1`. The registry test and full
     suite verify that the additive result is valid.

The overlap predicted for `src/weather/collection/snapshot_store.py` was stale
branch ancestry, not unique release-path work. Its captured-input-hash changes
are already on `origin/master`; none of the five retained source commits
changes that file. No conflict resolution or additional edit was needed.

### Roll-sensitive file set

The combined branch changes exactly one roll-sensitive file relative to
`origin/master`:

```text
src/weather/schema_registry_recent_data.py
```

It does **not** change `src/weather/collection/snapshot_store.py`. The final
branch otherwise changes 24 release-path source, test, runbook, and historical
report files before this handback report is counted.

### Verification

The repository venv still points at the removed
`C:\Users\Michael\AppData\Local\Programs\Python\Python311` installation. An
isolated Python 3.11.9 runtime and the exact pinned dependencies were therefore
installed below the declared scratch run root. Windows long paths are disabled
on this host; the final full run used an external untracked pytest fixture that
only shortened `tmp_path` directory names. It changed no repository code,
inputs, assertions, or test behavior.

| Check | Result |
| --- | --- |
| Focused release-path integration suite | **99 passed** |
| Full repository suite | **3273 passed, 4 skipped, 820 subtests passed** in 327.90s; 13 warnings |
| `python -m compileall -q app src tests` | **PASS** |
| `python -m weather.operations.agent_docs_audit` | **PASS** — 18 agent files, 542 Markdown files |
| `git diff --check origin/master...HEAD` before handback report | **PASS** |

The focused suite covered both new release-path modules, release lifecycle,
schema registry, model blend, inactive forward shadow, production readiness,
and strict release serving. The full suite was run only after separating three
host artifacts from code signal: a missing original Python 3.11 base, an
ACL-denied default pytest temp directory, and legacy Windows `MAX_PATH`.

## Mission 2 — current-evidence prelock rehearsal

### First failure

**BLOCK at production preselection.** The owning command read and hash-bound
the current evidence, wrote a valid candidate-independent source and replay
manifest, then refused to create the preselection lock:

```text
ContractViolation: production preselection requires a contiguous 14-day window
```

No downstream stage was run. Candidate fit, locked replay, PIT qualification,
promotion qualification, immutable training-graph verification, and the
research-only all-shadow release all depend on a valid prelock. Continuing
would require synthetic grade changes or a contract bypass, neither of which
is valid current evidence.

### Inputs and scope

| Item | Value |
| --- | --- |
| Code | Combined branch above, based on `0385da72` |
| Declared run root | `C:\Users\Michael\Documents\github\weather\scratch\runs\release-consolidation-2026-08-01b` |
| Rehearsal output | `<run-root>\rehearsal\prelock` |
| Snapshot input | Main repository `data\snapshots`, read-only |
| Settlement authority | Main repository `data\settlements`, read-only |
| Explicit folders | Toronto `2026-07-14` through `2026-07-29` inclusive, 16 folders |
| `as_of` | `2026-07-31` |
| requested `window_end` | `2026-07-29` |
| admitted grades | `complete,manual_override` |
| resource bounds | 60 market-days, 250,000 rows/market-day, 65,536-row batches |

The workstation settlement ledger is one date behind the production-host
clock described in the plan of record: its latest current Toronto revision is
`2026-07-29`, not `2026-07-30`.

### What the prelock admitted

The source materialization itself passed and admitted 13 Toronto market-days:

```text
2026-07-14, 2026-07-15, 2026-07-16, 2026-07-18,
2026-07-21, 2026-07-22, 2026-07-23, 2026-07-24,
2026-07-25, 2026-07-26, 2026-07-27, 2026-07-28,
2026-07-29
```

The replay manifest skipped exactly:

| Date | Reason |
| --- | --- |
| `2026-07-17` | `quality:partial` |
| `2026-07-19` | `quality:partial` |
| `2026-07-20` | `quality:partial` |

The trailing contiguous admitted run is therefore only `2026-07-21` through
`2026-07-29` on this workstation. The source contains 26,884 band rows and
2,444 captured-input identities. All 13 accepted labels came from the ledger;
there was no sidecar fallback and no feature-quality exclusion.

### Preserved artifacts

| Artifact | Bytes | SHA-256 / self-hash |
| --- | ---: | --- |
| `preselection-source.parquet` | 101,751 | `8dda2cecbf6454fadfafa0691ed47eccf4d806428085b6336428b849fb94a051` |
| `preselection-source-manifest.json` | 5,885 | file `320eb40d203f64bd7b39d9da3e5cc39c547112d938d1027aba933b9433c95907`; manifest `32bfe4f27675c5414110e002476be572e334baa68b1696c04f191a430414c202` |
| `replay_manifest.json` | 665,506 | file `6573ee2a0bdaff90daef39d395b86c85d11962de96a25eec6ea98fc458b6f825`; corpus `e1cd91962ae8c2a0425f5babd957f55e05aac3bd89c8e2494a407677fe946023` |

`preselection_lock.json` does not exist, as required after the failed lock.
There is no rehearsal candidate directory, release directory, or run-root
pointer. The real `artifacts/releases/current_release.json` pointer was absent
before and after. No promotion, serving, restart, scheduler, capture, mirror,
ACL, paid-provider, or trading change occurred.

## Handback

- Merge one branch, not the three source branches:
  `codex/workstation-release-consolidation-2026-08-01b`.
- Time one roll-sensitive file:
  `src/weather/schema_registry_recent_data.py`.
- Retire the strict-parity branch as report-only/dead for code integration.
- Treat the rehearsal as **BLOCKED BEFORE TRAINING** on current workstation
  evidence. Do not reuse the generated source as a valid prelock; preserve it
  only as evidence of the first failure.
- Regenerate both sides of the `2026-07-31` non-strict `rows[-1]` boundary when
  the real lock exists; this rehearsal did not reach candidate replay and did
  not mix artifacts across that boundary.
