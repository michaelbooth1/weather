# Workstation handoff 2026-09-80a — build the bounded production v2 PIT collector

Written 2026-08-31 by the production agent. Read from
`origin/codex/pit-v2-collector-handoff-20260831` and execute on the assigned
32 GB workstation. This is implementation and offline verification only; the
workstation must not contact a weather provider.

## 1. Goal

> Close P2 by building a bounded, fail-closed production-host collector that
> consumes an immutable v2 PIT plan and passes exact raw response bytes plus
> request/issue evidence into `stage_response`, while keeping collection
> impossible from the workstation and leaving corpus materialization separate.

Also open the reviewed foundation PR so collector work is visibly stacked and
does not delay P0/P1 review.

## 2. Exact source and branches

- Accepted parent branch:
  `origin/codex/workstation-model-pit-foundation-2026-09-79a`
- Exact parent commit: `6e23e756f8a2c620df4d821411c923a77afb0553`
- Exact parent tree: `e1a1ddd09edb8e97131a74592c05235e44965c99`
- Create collector branch:
  `codex/workstation-pit-v2-collector-2026-09-80a`
- Report:
  `docs/roadmap/agent-report-2026-09-04-workstation-pit-v2-collector.md`

Fetch and verify the exact parent, then create the collector branch from that
commit in a separate development worktree. Do not touch the portable live
checkout. Preserve published history and use descendant commits only.

## 3. First action — foundation PR and CI

Under the operator's explicit source-control authority, open a **draft** PR for
`codex/workstation-model-pit-foundation-2026-09-79a` targeting `master`.

- Use a merge-commit disposition; no squash, rebase, or force push.
- Include exact tip/tree, the 4,299-pass workstation suite, P0/P1 PASS, P2
  NO-GO, production `ROLL-SENSITIVE` exit 3, and the statement that no model
  was fitted or live authority created.
- Do not merge. Return the PR URL, exact-head CI run/status, and review state.
- If GitHub says the branch is not mergeable or CI is not exact-head green,
  report that blocker before collector publication.

The collector branch is stacked on the accepted parent. If you open a second
draft PR, target the parent branch and state that it must be retargeted to
`master` only after the foundation merges.

## 4. Start from this; do not re-derive it

Read `STATE_OF_PLAY.md`, `MODEL_SYSTEM.md`,
`PIT_FORECAST_TRAINING_CORPUS.md`, `HOST_LOAD_POLICY.md`,
`DELEGATION_CONTRACT.md`, item 330, and the `-09-79a` report first.

- P0/P1 at `6e23e756` are accepted for PR/production review. Do not rebuild the
  BOM or identity again unless a collector change exposes a direct regression.
- The v2 plan requests exactly 12 proved free Previous Runs fields. Nine fields
  remain explicit unavailable dispositions. Never query or synthesize them.
- `weather.sources.forecast_training_corpus` remains network-free. Keep it that
  way. Its `stage_response` is the only accepted raw-byte publication boundary.
- P2 is a precise structural NO-GO: no non-test caller of `stage_response`
  exists; `forecast_history` does not satisfy the immutable plan/receipt
  contract; long CSV projections are not raw provider evidence.
- The workstation may implement and test an injected transport but may not
  contact Open-Meteo or any other provider. Actual collection belongs on the
  dedicated production host in an admitted 00:30-09:00 window after code
  adoption and explicit execution authority.
- No dates are reserved, no alpha is allocated, no model may be fitted, and no
  release or pointer may be created in this mission.

## 5. P0 — prove the issue-evidence contract before writing HTTP code

Trace the existing `fixed_lead_day_offset` / `fixed_lead_offset` producer and
normalizer paths and answer:

1. For every requested target date, what exact `issue_time_utc` is licensed by
   `<field>_previous_day1`?
2. What exact evidence licenses `available_at_utc`?
3. Is either timestamp returned by the provider, derived by a code-owned
   deterministic contract, or merely assumed?

The collector may derive timestamps only from an already adopted, testable
provider contract whose semantics are explicit in the immutable plan. If the
current repository cannot truthfully establish either timestamp, return
`NO_GO_ISSUE_EVIDENCE_NOT_IDENTIFIED`. Do not invent 00:00/06:00, copy dates
from old staged CSVs, or relax `stage_response`.

This P0 must be able to stop the mission before an HTTP transport is built.

## 6. P1 — collector implementation

If P0 passes, add the smallest owner-correct surface:

```text
src/weather/sources/forecast_training_corpus_collector.py
tests/sources/test_forecast_training_corpus_collector.py
```

Add a narrow PowerShell execution wrapper under `scripts/ops/` only if needed
to acquire the existing capture-host workload lease and Job containment. Do
not add a scheduled task or registrar in this mission.

### Required collector contract

- Accept only an existing immutable `pit_forecast_corpus_plan_v2` file and a
  new staging root outside the active `data/forecast_history` archive.
- Re-run `load_plan`/`verify_plan`; never accept caller-supplied endpoint,
  variables, market, dates, model, units, or request hashes outside the plan.
- Require the current Windows installation to match the configured dedicated
  capture host. Explicitly refuse the assigned portable/workstation host.
- Require an exact, named confirmation such as
  `AUTHORIZE_FREE_PIT_V2_RAW_COLLECTION`; it grants only the plan's free
  Previous Runs GET requests and no other provider or exchange call.
- Use one request unit at a time. Bound request count, response bytes, timeout,
  redirects, retries, retry delay, total elapsed time, and aggregate bytes from
  constants checked before the first call.
- Permit only the exact HTTPS Previous Runs host/path and GET method from the
  verified plan. Refuse credentials, authorization headers, custom CA/proxy
  environment, alternate models, and endpoint drift.
- Use an injected transport in tests. The production transport returns the
  exact status, allowlisted response headers, final URL, retrieval timestamp,
  and untouched body bytes.
- Pass the exact body bytes directly to `stage_response` with the immutable
  request hash and truthful per-date issue evidence. Do not parse/re-encode the
  body before hashing/publication.
- Resume only through `inspect_staged_unit`; skip only a hash-verified complete
  unit. An existing failed, partial, changed, redirected, or ambiguous unit is
  preserved and fails closed unless the owning corpus contract already defines
  a create-new retry namespace.
- Do not materialize automatically. A successful collection ends with a
  complete resume ledger and a self-hashed collector receipt; the separately
  invoked existing `materialize` command remains the publication boundary.
- Emit no secret, IP address, proxy value, response body, or query credential.
  The plan and body SHA-256 are sufficient evidence.
- The module remains unusable for paid providers and never reads
  `.weathersync.cred`.

### Resource/host wrapper

If a wrapper is required, it must:

- run only 00:30-09:00 America/Toronto on the dedicated capture host;
- hold the shared repository workload lease through child cleanup;
- bind the exact plan hash, staging root, collector source, Python, working
  directory, timeout, and confirmation;
- use a kill-on-close Job with conservative memory and total-runtime bounds;
- stop without touching capture supervisors;
- write a create-only execution receipt and prove lease/child cleanup.

Do not classify the network fetch as a reason to stop capture. Measure it first;
capture interruption requires a separate operator decision.

## 7. P2 — adversarial tests and offline functional proof

At minimum prove:

- wrong host/profile, wrong confirmation, v1 plan, changed plan hash, wrong
  endpoint/method/model/fields, proxy/custom trust, or non-new staging root
  refuses before transport;
- workstation identity refuses even when the fake transport would succeed;
- redirect, oversized body, timeout, HTTP error, invalid JSON, missing unit,
  missing date/hour/field, false issue evidence, and post-fetch plan mutation
  preserve evidence and fail closed;
- a valid fake 12-field response publishes byte-for-byte through
  `stage_response`, including raw SHA-256 and per-date issue evidence;
- restart skips only the exact complete unit and never calls transport again;
- a complete fake multi-unit collection produces a complete resume ledger but
  does not materialize automatically;
- no test opens a network socket. Add a socket/transport tripwire.

Run focused source/corpus/contract/base-retrain/schema/import tests, wrapper
tests if applicable, compileall, roadmap/docs checks, and the full workstation
suite serially through `workstation_heavy.ps1`. Record exact counts and shared
lease/poison cleanup.

## 8. Falsification

Return NO-GO rather than code when:

- exact issue or availability timestamps are not identified;
- truthful collection requires reconstructing provider bytes from projections;
- the provider's response does not expose enough information to satisfy
  `stage_response` without an assumption outside the plan;
- host identity cannot prevent workstation/provider contact before transport;
- retries require overwriting a partial immutable namespace;
- safe bounds cannot cover one real planned response;
- the collector would need to weaken the v2 field, unit, date, cutoff, raw-hash,
  or issue-provenance gates.

A P0 NO-GO is a valid and valuable handback. Do not perform a live probe to
resolve ambiguity.

## 9. Standing boundaries

`DELEGATION_CONTRACT.md` §2 binds in full.

- No provider/exchange call, credential read, live mutation, Scheduler change,
  production write, frozen-mirror write, branch deletion, history rewrite,
  release creation/promotion, model fit, candidate score/freeze, alpha
  allocation, or reserved-date read.
- Keep the portable live checkout clean and unchanged. Stop offline work before
  any live attempt is sealed; the shared host-global mutex remains binding.
- Commit no raw response, corpus, data tree, venv, SDK, binary, or Git LFS
  content. Use deterministic small fixtures only.
- Do not grow provider network logic inside
  `forecast_training_corpus.py`; the collector is a separate owner module.
- Do not merge either PR. Production owns final review and quiet-window adoption.

## 10. Handback

Verdict first. Include:

1. foundation PR URL, exact-head CI/review status, and mergeability;
2. branch/tip/tree and exact parent ancestry;
3. P0 issue/availability evidence trace with source locations;
4. collector/wrapper contract, bounded constants, and one fake functional
   receipt with no network;
5. every falsifier and adversarial-test result;
6. focused/full counts and wrapper lease/poison cleanup;
7. complete changed-file list and cumulative diff;
8. explicit `provider_contacted: false`, plus every other action not done;
9. reproduction commands using repository-relative paths;
10. push proof and the repository-owned roll verdict if production closure
    evidence is available; otherwise require production to derive it.

Commit and push `codex/workstation-pit-v2-collector-2026-09-80a`. Do not merge.
