# Workstation addendum — 2026-08-01d: the clean-tree gate (read mid-mission, do NOT restart)

**This is additive to handoff `-08-01c`. Your mission is unchanged: the synthetic post-preselection
rehearsal is still the only mission.** Do not restart your run, re-baseline, or re-plan because of
this. Read it only so you do not spend rehearsal time rediscovering something already measured here,
and so you classify it correctly if you hit it.

## What I found on the production host tonight

Release #1's build fails on its **first** command, and not for any reason your rehearsal would call
interesting:

```python
# src/weather/operations/release_candidate_build.py
code = code_identity_provider(repo_root=args.repo_root)
if code.get("git_dirty") is not False:
    raise ReleaseLifecycleError("nightly release build requires a clean source tree")
```

`capture_code_identity` derives that from `git status --porcelain --untracked-files=all` excluding
**only** `artifacts/releases/**`, `artifacts/candidates/**`, and `data/**`. So `config/` and repo-root
`logs/` both count. Measured against the live production repo: `git_dirty: true`, gate `False`.

Two notes that will save you time:

1. `capture_code_identity` is in **`weather.operations.release_manifest`**, not
   `weather.release_artifacts`. Importing it from the latter raises `ImportError` — I hit it.
2. The production host's `config/locations.json` and `config/location_market_events.json` are
   rewritten by a scheduled 6-hourly task, so that tree is dirty most of the time by design. On your
   host the cause will differ, but the gate is the same.

## How to classify it if your rehearsal hits it

**Real defect — but an operational one, already fixed on the production side**, not a code defect in
the release path. The gate is correct to demand a clean tree; what was wrong was the tree.

- The `logs/` half was a permanent blocker (`.gitignore` covered `*.log` but not the `.err`/`.json`
  pair left by the 07-21 backfill). Fixed on master at `aaf8252b`.
- The `config/` half is recurring and **must not** be fixed by ignoring — config hashes are
  legitimately attested in the release manifest. Committing the drift is therefore a *step of the
  build*, which is now written into `docs/operations/RELEASE_ONE_BUILD_RUNBOOK.md` §1.

So if you hit it: note it, satisfy it in your own run root the same way (commit or clean, never by
editing the contract), and keep going. **It does not count as one of the downstream failures I asked
you to find** — it is upstream of the stages you are rehearsing.

## Two more verifications you can rely on rather than repeat

- `artifacts/releases/` and `current_release.json` are both absent on production, which is exactly
  what `--bootstrap-first-inactive-release` requires. Nothing should ever be hand-created there.
- `current_code_soak` does **not** participate in `release_admissibility_clock` grading — the clock
  keys on ledger `quality_grade == "complete"` plus source checks. Merge-driven fleet rolls cost
  promotion-evidence countability, not the streak and not the lock.

## Also recorded, in case it reframes anything you see

The weather-only proof packet had never been generated as JSON (only a June `.md`), which is why the
claim gate reported it "missing or unreadable". Regenerated, it is BLOCK with 9 blockers — and every
one reduces to the model trailing the market, not to plumbing. Widest is winner-rank parity at 0.1698
top-hit against a 0.0200 tolerance.

Caveat worth carrying: `hourly_model_performance` and `ten_minute_model_performance` were regenerated
today but score a corpus that ends 07-30 — entirely **before** the serving-floor fix landed. They
describe the old serving code and will not move for weeks. Do not read them as evidence about the
floor fix.

## Guardrails

Unchanged from `-08-01c`. Handback unchanged. Push before you start and again at handback.
