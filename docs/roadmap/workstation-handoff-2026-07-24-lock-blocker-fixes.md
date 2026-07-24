# Workstation handoff — 2026-07-24: Fix the release-#1 lock-blockers (A1–A6), then re-rehearse

From the production-host master agent. Your 2026-07-24 bootstrap rehearsal
(`codex/workstation-bootstrap-rehearsal-2026-07-23` @ `b6aa1c11`) is accepted in
full: the NO-GO verdict, the A/B/C classification, and the disclosure quality.
This handoff is the follow-through: **make the A-list fixable-by-code findings
actually fixed, prove it with the test the report itself prescribed, and
re-rehearse to a fresh verdict.** The streak is the clock — earliest lock
~2026-08-03; every fix must be mergeable on the production host in a quiet
window before then, so minimal reviewable diffs matter as much as correctness.

Status facts you need:

- The 12 mirror paths your rehearsal wrote were restored by the 04:30
  production→workstation `robocopy /MIR` refresh on 2026-07-24 (exit 3 =
  copied + extras purged; overwrites re-copied from production truth, the three
  created files deleted). You may re-hash them against your report's inventory
  to confirm before relying on them.
- Master HEAD has moved (ops tooling only); base all work on current
  `origin/master`.
- The hardening branch `423eaa59` remains unmerged; the merge-timing decision
  waits on this mission's two-identity re-comparison.

## Mission 1 (primary): fix A1–A4 + A6 on a topic branch off master

One topic branch off current `origin/master`
(suggested: `codex/workstation-lock-blocker-fixes-2026-07-24`). Surgical,
minimal diffs — no drive-by refactors, no formatting churn, nothing beyond the
finding being fixed. Every fix ships with its regression test in the same
commit. Code anchors are the ones your own report established.

- **A1 — fail-closed ledger authority**
  (`pooled_candidate_replay.py:2397-2409`, `settlement_io.py:131-152`).
  Invariant to implement: **a ledger row that exists for the slug/date must
  either be used or abort the run with an explicit authority error — it must
  never be silently bypassed for `folder/settlement.json`.** Make the
  tape-identity binding portable (repo-relative path or content identity, not
  absolute-path equality) so host/root relocation cannot flip authority.
  Sidecar fallback remains legal only when NO ledger row exists for the date,
  and must be loudly recorded in the run status. Regression: a fixture where
  the ledger row's recorded root differs from the current root must FAIL, not
  fall back.

- **A2 — one canonical winning-band spelling at the ledger→source boundary**
  (`point_in_time_evaluation.py:1507-1562`). Normalize on read at the boundary
  with an explicit, tested normalizer. The ledger is append-only: do NOT
  rewrite ledger rows; the materialized side and the verifier must agree on a
  single canonical form. The regression test must use **real current ledger
  spellings** (`86-87 F` style) read from real Toronto/Atlanta rows, not
  synthetic pre-normalized fixtures — your rehearsal proved synthetic
  normalization masks this class.

- **A3 — current-year lock coverage**
  (`model_climatology.py:96-104`, `model_constants.py:25`
  [`HISTORY_WINDOW_DAYS=7`], `pooled_feature_assembly.py:897-912`).
  The PIT trainer's every-locked-date requirement and the cache's
  current-year exclusion + 7-day window contradict; a real 14-day current-year
  lock must be trainable. Design carefully: the current-year exclusion is
  anti-leakage in intent, so document the chosen semantics explicitly and do
  not weaken any PIT cutoff — the fix is about which dates the cache must
  *cover*, never about what future information a feature row may *contain*.
  Regression: a synthetic current-year 14-day lock trains end-to-end.

- **A4 — one field contract for feature-row dates**
  (`feature_store.py:1368-1370` emits `date`;
  `pooled_training.py:296-306` requires `target_date`). Pick one contract
  (prefer `target_date`), fix emitters/readers coherently, and grep for other
  consumers of the old field before renaming.

- **A6 — freeze once, one output root**
  (`nightly_retrain.py:793-944`, `promotion/orchestration.py:282-295`).
  Promotion/qualification must consume the already-verified frozen generation
  (no post-freeze rebuild from live folders with promotion-countable admission
  re-enabled), and every derived output path must resolve under the
  candidate/run root and be checked before heavy work. Regression: run the
  promotion tree in a sandbox and assert **zero writes escape the run root** —
  this is the code-level fix for the exact mechanism that caused your mirror
  breach.

- **A5 — staging receipt binding (code half only).** Implement the receipt
  mechanism: a staged F-family source trio must carry a receipt binding the
  exact Toronto lock dates and latest ledger revisions, and the wrapper must
  refuse a trio whose receipt does not match the lock it is serving (the
  hardcoded `production_source_2026-07-16` must fail this check). The actual
  fresh staging decision at lock time is production-host work — do not attempt
  it from the workstation.

- **The end-to-end test your report prescribed:** one suite-runnable test that
  stages from current ledger rows through pooled training **without shims** —
  real spellings, current-year window, fail-closed authority, contained
  outputs. This is the regression that keeps all of the above fixed.

## Mission 2: re-rehearse to a fresh verdict

After Mission 1 is green:

1. **Master-identity re-rehearsal** on the fix branch: same harness as before,
   with two upgrades — **production-scale bootstrap iterations (2,000)** so the
   SLA is finally measured (production context: nightly training runs in a
   01:00 window with a 3h cap and an 04:15 dead-man; report the measured
   runtime against that), and **the mirror write-protected at the OS level
   before any execution** (deny-write ACL for the executing account on
   `data\`, verified by a canary write that must fail). Deliverable: updated
   GO/NO-GO for release #1 on the fixed master path.
2. **Hardening-branch prep** on a separate topic branch off `423eaa59`:
   fix B3 (unhandled `ValueError` in
   `physical_feature_family_ratchet.build_ratchet()` on an unreceipted legacy
   payload → must return a structured unauthorized/BLOCK result, never crash),
   implement the B1 v0.1→v0.2 operational-manifest migration path, and verify
   the B2 240-character budget against the real production layout
   (`c:\Users\micha\Desktop\github\weather\...`) rather than the workstation's.
3. **Two-identity comparison, round 2:** fixed-master vs fixed-hardened on
   identical inputs. Deliverable: the pre-lock vs post-lock merge
   recommendation, now with both paths runnable to completion.

## Mission 3 (only if capacity remains): fresh pooled H2 artifact

Carried unchanged from the 2026-07-23 handoff (it was not reached): corrected
blocked/nested H2 retrain, full training receipt (code/input/model/calibration/
nested-counter hashes), train/serve parity and replay-identity proof, then
STOP — no opened-window outcome evaluation; preregister the future confirmation
panel (unrealized dates only; joint Brier/log-loss/winner-mass/market-gap;
09:00–14:00 as a named reporting cut).

## Guardrails (the breach tightened them — non-negotiable)

- **Before ANY execution: write-protect the `data/` mirror at the OS level**
  and prove it with a failing canary write. Your report's own action item.
- `data/` strictly read-only; all outputs under
  `scratch/workstation-research-output/`; every derived path under the run
  root (Mission 1 makes the code enforce this — until it does, the ACL is the
  backstop).
- Topic branches only; push branches, never master; no PR creation, no merges,
  no cherry-picks between the fix branches and the hardening branch beyond
  what Mission 2 specifies.
- Minimal-diff discipline: production will review and quiet-window-merge these
  under time pressure; every unnecessary hunk slows the lock.
- No promotion, release-pointer, serving, scheduler, collector, sizing, or
  trading surface. No production-host access. No consumed-panel reuse.
- Honest reporting: NOT-DONE and NOT-REHEARSED lists are first-class results;
  if a fix turns out to need production-side state, say so rather than shim it.

## Handback

Report to
`docs/roadmap/agent-report-<date>-workstation-lock-blocker-fixes.md` on the
Mission-1 branch: per-finding fix summary with the exact commits, test
evidence, the measured 2,000-iteration SLA, the re-rehearsal comparison table,
the fresh GO/NO-GO, the round-2 merge recommendation, and a **merge-review
guide for the production host** — for each fix, what the reviewer should
scrutinize and what could regress. Push all topic branches; the production
host schedules review and quiet-window merges from there.
