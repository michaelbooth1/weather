# Workstation handoff — 2026-07-25c: settlement test isolation (fix first, then resume the queue)

Your simplex branch is **merged and on origin**. `origin/master` is `4041d358`; both
`d1815774` and `09756227` are ancestors. The upstream dependency you paused on is satisfied
— rebase and proceed.

Before you resume the skill-gap queue, there is **one defect the merge introduced** that you
should fix, because it is yours and it is small.

## The defect: A1 makes 7 tests fail through ledger-root leakage

Running the full suite on the merged tree (production host, live checkout): **13 failed,
3106 passed, 812 subtests passed**. I isolated the merge's contribution by running the same
13 against the pre-merge parent in a separate worktree: **5 were already failing** (app
architecture, long-job-guard ×2, module-size-audit ×2) and one more
(`test_tracked_artifact_manifests_match_current_repository_identity`) is a pre-existing
host-local condition — `artifacts/candidates/` is gitignored, so it exists in the live
checkout and not in a fresh worktree, and the computed identity differs. Nothing under
`artifacts/` changed today and it is git-clean.

**The remaining 7 are new, and they share one root cause:**

```
SettlementAuthorityError: settlement ledger authority violation:
  ledger row exists but its snapshot tape binding is invalid for
  highest-temperature-in-toronto-on-may-27-2026     (also toronto june-3, nyc june-22, nyc july-1)
settlement_io.py:421  (authoritative_ledger_label)
```

Failing: `test_backtest.py::TestSettlementAndTape` ×3,
`test_afternoon_residual_centering`, `test_model_ensemble::test_load_scored_rows_joins_component_probabilities`,
`test_daily_refresh::test_live_variant_settlement_step_scores_only_pinned_target_date`,
`test_wu_max_since_7_validation::test_builds_payload_from_pinned_corpus_and_writes_outputs`.

Mechanism: these tests build a fixture snapshot folder in a `TemporaryDirectory` using a
**real** event slug, but do not redirect `SETTLEMENT_LEDGER_ROOT`. Under A1,
`ledger_label_matches_folder` now prefers content identity: it finds the real production
ledger row, reads its recorded `snapshot_tape_sha256`, and — because the caller passes no
hash — computes `_file_sha256(folder/"snapshots_long.csv")` against the **fixture** file. The
hashes differ, so what used to be a silent path-based fallback is now a hard raise. One test
in the same file (`test_backtest.py:141`) already sets `SETTLEMENT_LEDGER_ROOT` and passes,
which is the pattern the others need.

**This is test isolation, not a production defect — verified, not assumed.** I re-hashed every
current label against its on-disk tape across all 12 markets:

```
597 current labels: match=597  MISMATCH=0  no_file=0  no_hash=0
```

So A1's strict check passes cleanly on all real production data, and the chain's settlement
step operates on the real `data/snapshots` tree where the tapes match. I briefly reverted the
merge while establishing that, then restored it once the evidence was in.

Fix the isolation (redirect the ledger root in those tests, or stop reusing real slugs).
Do **not** weaken A1's strictness to make tests pass — the strict content-identity binding is
the point of the change.

## Then: resume the standing queue

`docs/roadmap/workstation-handoff-2026-07-25b-skill-gap-decomposition.md` is unchanged and
still the priority once this is fixed: Mission 1 the Murphy/Brier decomposition of the
model-vs-market gap, Mission 2 bounding `price_free_model_learning` memory, Mission 3 the
pooled H2 artifact. Work them in order and do not idle.

## Guardrails (unchanged)

- `data/` strictly read-only with a proven deny-write ACL; single declared run root.
- The 2026-07-25 `promotion_refresh` authorization was single-purpose and is **spent**.
- Topic branches only; never push master; no PRs. Merge timing stays with the production host.
- The hardening branch `1d9d58d` stays unmerged and post-lock, as you recommended.
- Rebase on `4041d358` before any merge-readiness claim.

## Note on master

Master also carries production-host ops work from today: monitoring additions, boot recovery,
off-host mirror restore verification, and a guarded quiet-window merge tool. None of it
touches the model, promotion, or PIT paths. Streak is 4/14, earliest lock ~2026-08-03.
