# Workstation handoff — 2026-08-11a: red-team the release path you built

**This amends the stand-down (`-08-10a`) with one bounded, docs-only mission.** Everything else in the
stand-down holds: no candidate work, no harness changes, no reserved-window read. This exists because
tonight's pre-release audit (`docs/roadmap/pre-release-audit-2026-08-01.md`) found exactly one gap
that is (a) on the build-window critical path and (b) workable before release #1 exists — and you are
the right agent for it, because you consolidated the release code.

## The gap

`release_lifecycle_cli promote` requires two operator-authored files:

```powershell
python -m weather.operations.release_lifecycle_cli promote <release-id> `
  --decision <reviewed-promotion-decision.json> `
  --market-day-boundary <fresh-boundary-proof.json> `
  --bootstrap-first-release
```

The code contains **fail-closed validators only** — `validate_promotion_decision` and
`validate_market_day_boundary` in `src/weather/operations/release_promotion.py` — and **no
generator**. The boundary proof has a staleness limit, so it must be authored at promotion time,
under time pressure, inside the 7-day window. As things stand we would be hand-writing JSON against a
rejecting validator by trial and error on the most important day of the project. Every rejection
found now is free; every one found then is paid from the window.

## Mission (docs-only handback)

1. **Extract the exact schemas.** From the validators as merged on master, derive the complete
   field-by-field contract for both files: required fields, types, formats, the staleness rule and its
   clock, hash fields and what they hash, and every failure string the validator can emit. For the
   decision file include the `--bootstrap-first-release` specifics: `release_kind:
   serving_identity_bootstrap`, `decision=PROMOTE`, `gate_status=PASS`, exact release/manifest
   identity, review fields, and the candidate-only-build proof.
2. **Write fill-in-the-blanks templates** for both files, with each placeholder annotated: where the
   value comes from on build day (which artifact, which command output, which hash), and which values
   must be generated at promotion time versus staged in advance.
3. **Prove the templates against the real validators.** In a worktree, drive
   `validate_promotion_decision` / `validate_market_day_boundary` directly with your filled examples —
   synthetic identities clearly marked — and show one passing run and, for each distinct failure
   branch, one intentionally failing run with the validator's actual message. This is the same
   build-the-judge-first logic as the harness: we learn the rejection surface before we need to pass
   it. Nothing here creates a release, decision authority, or promotion evidence — synthetic marker in
   every example, and no possibility of reuse.
4. **Write the §4a cutover verification checklist** the runbook now stubs: after `promote`, exactly
   what must restart (which workers bind via `worker_release_binding`), what proves binding (runtime
   identity carrying the release; zero unbound/global-fallback rows), and the three unlock checks —
   nightly retrain proceeding past `captured_input_replay_parity_blocked`, the settlement scorecard
   binding to the release identity instead of `legacy-runtime:*`, and `replay_cache_retention`
   becoming able to classify. For each: the command, the field to read, and the value that means
   "worked".
5. **Red-team the rest of the runbook** (`docs/operations/RELEASE_ONE_BUILD_RUNBOOK.md`) against the
   code as merged — you wrote most of the code it describes. Note tonight's correction already made:
   §3b must NOT pass the July-11 `promotion_corpus.json` (pre-boundary, stale); staged sources omit
   the flag so the prelock copies the manifest hash-bound by the source. Flag anything else where the
   runbook and the code disagree, with file/line evidence.

## Constraints

- **Docs and read-only validation runs only.** No release, no candidate, no artifact, no `data/`
  write, no production change. Synthetic examples must be incapable of later reuse as evidence.
- Do not read or evaluate **2026-08-06 → 08-19**; do not swap it.
- Topic branch; push before starting and at handback. The handback must be mergeable as docs-only —
  keep any helper scripts inside your run root, not the repo tree.

## Guardrails

Unchanged. `data/` read-only, one declared run root outside the mirror, topic branches only, no PR, no
merge, no master push, no promotion/pointer/serving/scheduler/capture/mirror/ACL change, never read or
expose the sync credential.

**Timing:** the lock lands ~2026-08-03; the build starts on the production host no earlier than
2026-08-04 after ~10:00. This handback is most valuable if it lands **before 08-04**; if you cannot
finish step 5 in time, hand back steps 1–4 alone — the promotion templates are the part the window
cannot do without.

## Handback

`docs/roadmap/agent-report-<date>-workstation-promotion-evidence.md`: the two field-by-field
contracts, the filled templates with provenance annotations, the validator pass/fail transcript
matrix, the §4a cutover checklist, and any runbook-versus-code discrepancies with evidence. After this
lands, the stand-down resumes until release #1 exists.
