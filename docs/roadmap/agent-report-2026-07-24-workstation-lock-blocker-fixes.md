# Agent report — 2026-07-24 workstation lock-blocker fixes

This report executes `docs/roadmap/workstation-handoff-2026-07-24-lock-blocker-fixes.md`.
It separates code readiness, rehearsal completeness, and release readiness. Those
are different decisions.

## Executive verdict

| Decision | Verdict | Basis |
| :--- | :--- | :--- |
| Mission 1 A1–A6 code contracts | **GREEN** | The prescribed invariants and integrated no-shim regression are implemented at `0975622723129f47e179a4a188017773fbfa95fd`; focused and affected suites passed, and independent review found no P1/P2 defect. |
| Release #1 on exact current evidence | **NO-GO** | Both fixed-master and final fixed-hardened exact lanes fail closed before training: `ContractViolation: production preselection requires a contiguous 14-day window`. Candidate status is `NOT_BUILT`; no release or pointer exists. |
| Conditional 2,000-iteration code path | **MEASURED, NON-PRODUCTION** | Both synthetic compatibility lanes exercised the repaired stages and completed the configured 2,000-iteration PIT evaluation in about 20 minutes, then correctly returned `BLOCK` on 149 probability-simplex failures. The input manifest explicitly says `conditional_evidence_only=true` and `production_evidence_authorized=false`. |
| Round-2 “both paths runnable to completion” criterion | **NOT MET** | Exact evidence stops at the missing contiguous window. Synthetic evidence is nonauthorizing and stops before candidate construction. The final runs also used the noncompliant short `w24` output root described below. They must not be substituted for the requested production-evidence comparison. |
| Mission 1 merge timing | **PRE-LOCK MERGE RECOMMENDED** | These are the accepted release blockers. Merge only in a production-host quiet window after the review guide below and the known Windows-suite qualifications are accepted. |
| Hardening merge timing | **POST-LOCK MERGE RECOMMENDED** | B1–B3 are code-green, but the exact two-identity completion criterion remains unmet and B1 adds a large migration implementation to a 1,928-line module. That review burden is not justified in the pre-lock critical path. |
| Mission 3 | **NOT-DONE** | Capacity was consumed by A1–A6, B1–B3, two final-identity lanes, and the actual migration exercise. |

Code-merge recommendations do not override the release verdict. Release #1 remains
NO-GO until exact current production evidence supplies an admissible contiguous
14-day window and the resulting PIT evaluation passes.

No release, promotion, active-pointer, serving, scheduler, collector, sizing, or
trading mutation was performed.

## Identity and branch provenance

| Purpose | Branch / identity | Commit |
| :--- | :--- | :--- |
| Pulled base | `origin/master` | `1cdb12a4a562e1992fbf491158d4e28824b91f2d` |
| Mission 1 fix branch | `codex/workstation-lock-blocker-fixes-2026-07-24` | `0975622723129f47e179a4a188017773fbfa95fd` — `Fix workstation release lock blockers` |
| Hardening baseline | supplied unmerged branch identity | `423eaa59beee83b0345ace0027b97d4df09a0254` |
| Mission 1 integration into the Mission 2 hardening topic branch | `codex/workstation-hardening-lock-blocker-fixes-2026-07-24` | `d3890f3db8fec6f7289b06027c0eb0c5e58c61fb` |
| B1–B3 hardening | same hardening topic branch | `0d2535855b3293c080eb1d762408aca4570baa7b` |
| Junction-root migration correction and final hardening identity | same hardening topic branch | `1d9d58d37420c5794c266dfc27c714e2e4bb06b6` |

The merge at `d3890f3d` was performed only to create the fixed-hardened identity
required by Mission 2. It merged Mission 1 into the separate branch based on
`423eaa59`; it did not merge either topic branch to `master`.

Both reported final executions started from clean tracked worktrees. Untracked
harness and evidence files were intentionally excluded from code commits.

## Non-negotiable mirror guard

The mirror was write-protected at the Windows ACL layer before any mission
execution.

- Protected mirror: `C:\Users\Michael\Documents\github\weather\data`.
- Explicit non-inherited `Deny` ACEs remain installed for
  `DESKTOP-RFCD2GH\Michael` and
  `DESKTOP-RFCD2GH\CodexSandboxOffline`.
- Denied rights are `DeleteSubdirectoriesAndFiles, Write, Delete`, inherited by
  child containers and objects (`ContainerInherit, ObjectInherit`).
- Direct canary:
  `C:\Users\Michael\Documents\github\weather\data\.codex-write-canary\nested\probe.txt`.
  Every probe raised `System.UnauthorizedAccessException`; the nested canary
  file and directory were absent afterward.
- The harness independently attempted
  `.codex-rerehearsal-write-canary-20260724.txt` through each worktree's
  `data` junction. Its persisted ACL gate records
  `canary_write_denied=true` and `canary_path_absent=true` while executing as
  `DESKTOP-RFCD2GH\Michael`.
- Both worktree paths are Windows junctions targeting the protected mirror:
  `weather-lock-blocker-fixes\data` and
  `weather-lock-blocker-hardening\data`.
- The ACL remains installed at handback.

The final short evidence root was
`C:\Users\Michael\Documents\Codex\w24`. The longer in-repository
`scratch\workstation-research-output\...` topology exceeded Windows path limits
in child-process fixtures, so the root was shortened. This is a **guardrail
deviation**, not a compliant accommodation: `w24` is outside the handoff's
non-negotiable `scratch\workstation-research-output\` subtree. All generated
files still remained under the declared `w24\e`, `w24\r`, or
`w24\mig-final-1` subtree, every candidate-derived path was contained under its
run root, and nothing was written to `data`, but location containment alone
does not cure the deviation. The four runtime lanes are therefore diagnostic
evidence, not a fully handoff-compliant Mission 2 rehearsal. A rerun from the
required output subtree (or a production-host topology explicitly accepted as
equivalent) remains required.

A recursive audit of `w24` found zero `current_release.json` files and zero
files under any run's `artifacts\releases` directory. Direct and harness canary
paths were absent at the end. The optional post-refresh mirror inventory
re-hash was not performed; the ACL was treated as the required backstop.

## Mission 1 — A1–A6

All Mission 1 changes and their regressions are in `09756227`. The commit
touches 41 files (`5,316` insertions, `206` deletions). The volume is a review
risk despite the absence of an unrelated refactor; most of it is strict
contract code and regression coverage.

| Finding | Implemented invariant | Principal files and regression evidence | Production-host review concern |
| :--- | :--- | :--- | :--- |
| A1 — ledger authority | An existing slug/date ledger row is authoritative: it is used or the run aborts explicitly. It cannot silently fall back to `folder/settlement.json`. Tape identity is content/portable-root based. Sidecar fallback remains legal only when no ledger row exists and is loudly surfaced. | `settlement_io.py`, `pooled_candidate_replay.py`, `promotion_corpus.py`; `test_settlement_authority.py`, `test_pooled_candidate_replay.py`, `test_promotion_corpus.py`. Relocated-root and ambiguous/mismatched authority cases fail closed. Focused A1 selection: **16 passed**. | Check that every “row exists” state is distinguished from “row absent”; confirm portable identity cannot legalize the wrong tape and the sidecar path remains impossible after an authority error. |
| A2 — winning-band spelling | One idempotent boundary normalizer canonicalizes ledger spellings for both materialization and verification without rewriting the append-only ledger. | `point_in_time_evaluation.py`, settlement boundary helpers; `test_winning_band_normalization.py` uses real Toronto/Atlanta `86-87 F`-style spellings rather than pre-normalized shims. | Verify all verifier/materializer paths call the same normalizer and that unknown/ambiguous spellings fail rather than broaden. |
| A3 — current-year coverage | The climatology/cache contract covers every date in a real current-year 14-day lock while preserving point-in-time cutoffs. Current-year cache coverage does not permit a feature row to contain future observations. | `model_climatology.py`, `pooled_feature_assembly.py`; `test_climatology_cache.py`, `test_pooled_feature_preselection_exclusion.py`, and the integrated lock-blocker test. | Scrutinize coverage versus information availability: cache presence is not permission to read after a row's cutoff. |
| A4 — feature-row date contract | Emitters and readers use `target_date` coherently; consumers of the former `date` spelling were inventoried and updated. | `feature_store.py`, calibration/feature assembly consumers, related model and calibration tests. | Search downstream consumers and serialized fixtures for implicit `date` compatibility assumptions. |
| A5 — staging receipt | The staged F-family trio must carry a receipt binding exact Toronto lock dates and latest ledger revisions. A stale or mismatched receipt, including the hardcoded `production_source_2026-07-16`, is rejected. | New `point_in_time_staging_receipt.py`, `nightly_retrain.py`, `training_window.ps1`, schema registration; `test_point_in_time_staging_receipt.py`, `test_training_window_script.py`. Focused A5 selection: **18 passed**. | Review date/revision serialization, hash binding, stable reads, and the wrapper's fail-closed behavior. Fresh lock-time staging remains production-host work. |
| A6 — freeze once / one output root | The verified generation is frozen once and loaded by pin downstream. Promotion does not rebuild from live folders. Candidate/run containment is checked before heavy work, including resolved/reparse paths. | `nightly_retrain.py`, `promotion/orchestration.py`, CLI/gauntlet/trust readers; `test_promotion_output_containment.py`, `test_promotion_gauntlet_frozen_trust.py`. | Look for TOCTOU between preflight and use, junction/reparse escapes, any code path that re-enables live admission, and any derived output not rooted at the candidate. |
| Integrated regression | Current ledger rows flow through pooled training without shims, using real spellings, a current-year window, fail-closed authority, a pinned frozen generation, and contained outputs. | New suite-runnable `tests/calibration/test_lock_blocker_end_to_end.py`. | Confirm it still exercises production spellings and real contract boundaries rather than helper-only mocks. |

### Mission 1 verification

| Suite | Result |
| :--- | :--- |
| Focused A1 authority selection | `16 passed` |
| Focused A5 receipt selection | `18 passed` |
| Affected regression suite | `509 passed, 1 skipped, 12 warnings, 68 subtests passed` |
| Syntax/static checks | Python AST checks passed; `training_window.ps1` parsed; `git diff --check` passed |
| Independent review | A1–A6 and the integrated contract were clean at P1/P2 |

The repository-wide run was not globally green:

`72 failed, 3044 passed, 3 skipped, 13 warnings, 804 subtests passed in 585.58s`.

Classification:

- 5 failures reproduced as known pre-existing failures on the pulled master
  baseline.
- 67 failures were Windows extended-path fixture failures.
- Short-root reruns cleared 38; an extended-path rerun cleared 22 more.
- The remaining 7 were executor child-working-directory fixture limitations
  under Windows. Product code was not changed to mask them.

This qualification is why “Mission 1 code-contract green” is not reported as
“the entire repository suite passed.”

## Mission 2 hardening — B1–B3

### Fixed-hardened integration

The `d3890f3d` integration resolved seven conflicts while retaining the supplied
hardening v0.2/history contracts and Mission 1 authority, containment, and
pinning:

- `pooled_feature_assembly.py`
- `daily_refresh_reporting_steps.py`
- `nightly_retrain.py`
- `promotion_corpus.py`
- `test_pooled_feature_preselection_exclusion.py`
- `test_nightly_retrain.py`
- `test_promotion_corpus.py`

The first focused merge run was
`3 failed, 258 passed, 1 skipped, 37 subtests passed in 150.20s`. All three
failures were stale test fixtures under the stricter merged contracts. The
fixture-only corrections were included in the merge identity; all three
regressions passed on rerun.

### B findings

| Finding | Result | Verification / risk |
| :--- | :--- | :--- |
| B1 — v0.1→v0.2 operational migration | Added an explicit, hash-pinned migration API and CLI. Ordinary loading rejects operational v0.1. Migration uses bounded duplicate-safe/finite JSON parsing, stable reads, file/schema/corpus pins, full inventory validation, portable semantic projection, exclusive output-first publication, pinned reload, and a final self-hashed PASS evidence record. It rejects serialized `_path`, research markers, symlinks, hard links, aliases, pre-existing outputs, and ancestor/output conflicts. | Full promotion-corpus suite before the final junction correction: `35 passed, 39 subtests passed`; focused migration: `8 passed, 12 subtests passed`. Final filter at `1d9d58d`: `8 passed, 1 skipped, 27 deselected, 12 subtests passed in 7.89s`. The skip is the Windows symlink-alias regression. Independent review found no P1/P2 issue. The actual exercise exposed a junction-root relocation bug; `1d9d58d` resolves both folder and root before portable comparison and adds the alias regression. `promotion_corpus.py` is now 1,928 lines, 72 below the 2,000-line warning threshold. Minor CLI sharp edge: migration-only/build-only options can be accepted in the wrong mode and ignored. |
| B2 — 240-character budget | The existing allocator required no production change. A regression uses the exact `C:\Users\micha\Desktop\github\weather` root, 30-character scheduler candidate ID, and 436-character unsafe generation ID. | First path is 239 characters; deterministic collision retry is 240. Both retain digest `8272abb270af`; retry ends `-retry-0002`; mocked probes prove zero writes. Adjacent selection: `2 passed in 1.18s`. Independent review found no P1/P2 issue. |
| B3 — unreceipted legacy payload | Payload-without-receipt now synthesizes a structured, nonauthorizing `BLOCK` receipt. Receipt-without-payload remains a programmer-error `ValueError`. The reader emits `BLOCK_UNAUTHORIZED_ARTIFACT`, an empty ready set, and `serving_or_release_authorization=false`. | Full ratchet suite: `71 passed, 8 subtests passed in 325.28s`. Combined B2/B3 selection: `4 passed, 4 subtests passed in 47.19s`. Independent review found no P1/P2 issue. |

Architecture and module-size ratchets passed:
`25 passed in 4.76s`. Python AST checks over the seven B1–B3 files and
`git diff --check` passed.

### Actual B1 migration exercise

Inputs were the actual fixed-master synthetic replay v0.1 and the final
fixed-hardened replay v0.2. The first pre-correction exercise exposed the
worktree-junction root mismatch and produced no authoritative PASS. The
post-correction exercise at `1d9d58d` passed:

| Identity | Schema | File SHA-256 | Bytes | Corpus hash |
| :--- | :--- | :--- | ---: | :--- |
| Legacy source | `promotion_corpus_v0.1` | `7d137cc8340b4e804dadfcc271d40c8e366c0c78fe0cae496b47045b353fee13` | 1,319,243 | `906994c8dbd533e668083fdbcb77c231fa56ddd2aab8e4c2e0e90a9414006826` |
| Native rebuilt input | `promotion_corpus_v0.2` | `cb08dd11fbaf20a493345a8caaefe816a49a9bba817d48c4a05c8f34d63d6e0a` | 1,319,247 | `afcffc534beca3e667c4c18ea04ff316bd22f0f00678dd6ada8d61d24d195f93` |
| Exclusively published output | `promotion_corpus_v0.2` | `4f78b7bf7a5382d59521746da2ba6ece100a427131ca8b2305718d319fb76fba` | 1,301,373 | `afcffc534beca3e667c4c18ea04ff316bd22f0f00678dd6ada8d61d24d195f93` |

- Entry count: 36.
- Portable semantic projection:
  `f98144a5f59db2c159b164595f9c0751f6a60a5bc489e7d3310eb6d7a9ff5319`.
- PASS evidence self-hash:
  `10cd2affaf389e383cd9057527759305d4291f5b922264436de196c46b053bc3`.
- Output:
  `C:\Users\Michael\Documents\Codex\w24\mig-final-1\promotion-corpus-v0.2.json`.
- Evidence:
  `C:\Users\Michael\Documents\Codex\w24\mig-final-1\migration-evidence.json`.
- Loader probe:
  ordinary v0.1 → rejected with
  `research-derived or legacy corpus is not an operational promotion corpus`;
  pinned migrated v0.2 → accepted with 36 entries.

## Rehearsal inputs

Each master/hardening pair used an identical verified input manifest.

| Lane | Manifest identity | Population | Authority |
| :--- | :--- | :--- | :--- |
| Exact current ledger | `be56d2e5a9cd14ddc20020d8d676fd1bb4ac22c31b6554d2595d87a3fb8d5f9b`; 206 checked files; `BYTE_EXACT_FULL_SOURCE_LEDGER` | Toronto latest 14: 2026-07-09…2026-07-22, 6 complete / 8 partial. Atlanta selected 36: 2026-06-06…2026-07-21 with declared exclusions, 13 complete / 23 partial. | Production-shaped exact input. It truthfully lacks an admissible contiguous 14-day lock. |
| Synthetic compatibility | `ccfa61d25a35f08bea34819a5891c1e9442fc86747185676c41eaf5ece455ea1`; 206 checked files; `DECLARED_SYNTHETIC_COMPATIBILITY_ROWS` | Toronto fixed 14: 2026-07-08…2026-07-21, source 5 complete / 9 partial, synthetically declared 14 complete. Atlanta same selected 36, source 13 complete / 23 partial, synthetically declared 36 complete. | `conditional_evidence_only=true`; `production_evidence_authorized=false`. Record/quality metadata was explicitly overridden; this lane cannot support a GO. |

The synthetic range deliberately differs from the exact latest-Toronto range.
Identity claims are only within each fixed-master/fixed-hardened pair, never
between the two lanes.

## Round-2 comparison

### Headline lanes

| Lane / run | Code identity | Input | Stage durations (seconds) | Wall time | Terminal result | Candidate / release / pointer |
| :--- | :--- | :--- | :--- | ---: | :--- | :--- |
| Exact fixed master `m-e` | `0975622723129f47e179a4a188017773fbfa95fd` | exact `be56d2e5…`; 2,000 configured but not reached | preselection `40.832`; build skipped | `41.264` | `ContractViolation: production preselection requires a contiguous 14-day window` | `NOT_BUILT` / none / absent |
| Exact final fixed hardening `hf2-e` | `1d9d58d37420c5794c266dfc27c714e2e4bb06b6` | exact `be56d2e5…`; 2,000 configured but not reached | preselection `46.044`; build skipped | `46.461` | Same exact contract block | `NOT_BUILT` / none / absent |
| Synthetic fixed master `m-s` | `0975622723129f47e179a4a188017773fbfa95fd` | synthetic `ccfa61d2…`; 2,000 completed | preselection `80.752`; family `146.659`; pooled `294.821`; registry `0.441`; promotion `348.465`; PIT `325.792` | `1198.225` | PIT `BLOCK`; `ContractViolation: evaluation is not PASS` | `NOT_BUILT` / none / absent |
| Synthetic final fixed hardening `hf2-s` | `1d9d58d37420c5794c266dfc27c714e2e4bb06b6` | synthetic `ccfa61d2…`; 2,000 completed | preselection `84.737`; family `142.947`; pooled `294.028`; registry `0.453`; promotion `354.335`; PIT `314.895` | `1192.733` | PIT `BLOCK`; `ContractViolation: evaluation is not PASS` | `NOT_BUILT` / none / absent |

The final hardening conditional lane was 5.492 seconds faster than the
fixed-master conditional lane. This is not evidence of a meaningful
performance difference; it only shows no material regression in this pair of
single workstation runs.

### Common synthetic result

Both synthetic lanes produced the same decision-level result:

- promotion: 0 promote, 10 shadow, 1 blocked (Atlanta);
- readiness: `OPEN`;
- serving gauntlet: `PASS_WITH_SHADOWS`;
- serving/release authorization: false on the v0.2 hardening result;
- PIT status: `BLOCK`;
- 52,932 input rows, 23,518 rows in the locked 14-date window, 29,414 outside;
- 149 excluded cutoffs, all
  `probability_simplex_failure`;
- source-quality target: `PASS`;
- window: 2026-07-08…2026-07-21;
- window lock:
  `75b1b905079fe494a3df5809556606f0c39de20be48fb8b6e1d2a8fd1d4bc74b`.

The fixed-master replay was v0.1 with 36 entries and corpus
`906994c8…`; the final hardening replay was v0.2 with 36 entries and corpus
`afcffc53…`. The successful B1 projection proves their portable operational
semantics are equivalent. Source manifests differ in schema/path identity but
both contain 52,932 accepted rows across 36 market days.

### SLA and resource interpretation

The 3-hour limit is 10,800 seconds; the 04:15 dead-man from a 01:00 start is
11,700 seconds.

| Conditional lane | Wall time | Margin to 3h | Margin to 04:15 |
| :--- | ---: | ---: | ---: |
| Fixed master `m-s` | 1,198.225 s | 9,601.775 s (`2:40:01.775`) | 10,501.775 s (`2:55:01.775`) |
| Final hardening `hf2-s` | 1,192.733 s | 9,607.267 s (`2:40:07.267`) | 10,507.267 s (`2:55:07.267`) |

These are conditional code-path SLA measurements. Exact production-evidence
2,000-iteration completion remains NOT-REHEARSED because both exact lanes stop
before that work.

The harness resource admission passed. Earlier equivalent heavy lanes were
observed between approximately 2.5 and 3.44 GiB private memory, below the
4 GiB workstation target, and the final run began with about 12.57 GB
available. The final `1d9d58d` run did not persist a peak-private-bytes metric,
so a formal final-identity 4 GiB cap proof is NOT-REHEARSED.

All run output stayed below its declared candidate/run root; the integrated A6
regression asserts zero escaped writes. The ACL independently prevented mirror
writes. Pointer and release-store audits were empty.

## Fresh recommendation

### Mission 1: pre-lock quiet-window merge recommended

The production host should review and merge `09756227` before the earliest lock
only if:

1. each A1–A6 review item below is accepted;
2. the 41-file / 5,316-insertion scope is considered reviewable under the
   quiet-window policy;
3. the seven residual Windows child-CWD fixture failures are accepted as
   harness limitations rather than hidden product regressions; and
4. the host performs fresh lock-time F-family staging and an exact
   current-ledger re-rehearsal after an admissible window exists.

The fix commit removes the accepted code blockers. It does not manufacture the
missing production evidence.

### Hardening: post-lock merge recommended

The hardening branch is code-green for B1–B3 and did not materially regress the
conditional runtime. It is not recommended for the pre-lock critical path:

- exact fixed-master versus fixed-hardened completion is still unavailable;
- B1 contributes 969 production lines and leaves its module at 1,928 lines;
- seven merge conflicts require focused production review; and
- the Windows symlink-alias regression is skipped on this host.

Production may schedule the branch after lock once it can run the exact
comparison and review B1's migration surface. B2 and B3 passing does not
convert this branch into release authorization.

## Merge-review guide

| Area | What the production reviewer should scrutinize | What could regress |
| :--- | :--- | :--- |
| A1 | Ledger-row state machine, portable tape/content identity, legal no-row fallback, loud status projection | An unreadable/mismatched authoritative row silently falling through to a sidecar |
| A2 | Single idempotent normalizer used by materializer and verifier; no ledger writes | Split spellings, permissive unknown-band parsing, or append-only ledger mutation |
| A3 | Current-year cache coverage versus each row's PIT cutoff | Future-data leakage hidden by broader cache coverage |
| A4 | All serialized/consumer date fields and backward-compatibility boundaries | A remaining reader expecting `date` or interpreting `target_date` differently |
| A5 | Exact date ordering, latest revision binding, receipt hashes/stable reads, wrapper refusal | A stale trio being accepted because dates or revisions serialize differently |
| A6 | Freeze/load pin, no post-freeze live rebuild, pre-heavy path validation, junction/reparse and TOCTOU handling | Live data entering after verification or output escaping the candidate root |
| Integrated test | Current ledger rows, real spellings, no shims, full contract boundary | A test becoming green through a helper mock while production composition breaks |
| Hardening merge | All seven conflict resolutions preserve both v0.2 history rules and A1–A6 | Either branch's stronger contract being accidentally discarded |
| B1 | Byte/line bounds, duplicate/nonfinite rejection, stable pinned reads, portable projection exclusions, exclusive publication order, pinned reload, self-hash, junction resolution, CLI mode separation | Migrating semantically different data, path-root false negatives, partial evidence, output aliasing, or maintenance pressure near module ratchet |
| B2 | Exact production-root arithmetic and deterministic collision retry | A later path segment or suffix exceeding 240 characters |
| B3 | Non-authorizing receipt synthesis and reader propagation; retained receipt-without-payload error | A legacy payload crashing again or being treated as authorized |

## NOT-DONE / NOT-REHEARSED

- Exact-current end-to-end completion through a candidate: **NOT-DONE**.
- Exact production-evidence 2,000-iteration SLA: **NOT-REHEARSED**.
- The requested fixed-master/fixed-hardened comparison with both paths runnable
  to completion: **NOT-REHEARSED**.
- A final rerun whose physical outputs remain under the handoff-mandated
  `scratch\workstation-research-output\` subtree: **NOT-REHEARSED**. The
  analyzed `w24` lanes are diagnostic because of this guardrail deviation.
- Formal final-identity peak-private-memory proof below 4 GiB:
  **NOT-REHEARSED**.
- Fresh lock-time F-family source trio and matching production receipt:
  **NOT-DONE**; production-host responsibility.
- Production-host execution, task lineage, scheduler attestation, live
  collector health, serving parity, and other host-specific gates:
  **NOT-REHEARSED**.
- Windows symlink-alias execution for the B1 migration regression:
  **NOT-REHEARSED** (test skipped on this host).
- Quiet-window review/merge and live lock acceptance: **NOT-DONE**.
- Release construction, promotion, pointer activation, serving, scheduler,
  collector, sizing, trading, or consumed-panel work: **NOT-DONE by design**.
- Optional mirror inventory re-hash after the production refresh:
  **NOT-DONE**.
- Mission 3 in full — corrected pooled H2 retrain, complete
  code/input/model/calibration/nested-counter receipt chain, train/serve parity,
  replay identity, and future confirmation-panel preregistration:
  **NOT-DONE**.

## Evidence inventory and exclusions

Final analyzed evidence (diagnostic, not fully handoff-compliant because of the
`w24` output-root deviation):

- exact fixed master:
  `C:\Users\Michael\Documents\Codex\w24\r\exact_current\m-e`;
- exact final fixed hardening:
  `C:\Users\Michael\Documents\Codex\w24\r\exact_current\hf2-e`;
- synthetic fixed master:
  `C:\Users\Michael\Documents\Codex\w24\r\synthetic_compatibility\m-s`;
- synthetic final fixed hardening:
  `C:\Users\Michael\Documents\Codex\w24\r\synthetic_compatibility\hf2-s`;
- final migration:
  `C:\Users\Michael\Documents\Codex\w24\mig-final-1`.

The harness is untracked under
`scratch\workstation-research-output\lock-blocker-rerehearsal\harness` on the
Mission 1 worktree. It records code branch/commit, verifies inputs, performs
the ACL gate, confines outputs, and records the configured 2,000 iterations and
wall time.

Excluded/superseded evidence:

- earlier long-root `lr2`/`lr3` path-preflight attempts;
- `hf-e`, which is a sandbox-Python preflight-only directory;
- hardening `h-e`/`h-s` at `0d253585`, superseded after the actual migration
  exercise found the junction-root issue;
- the earlier pre-correction migration directory `w24\mig`.

None is used for the final verdict.

## Handback

- Required tracked report:
  `docs/roadmap/agent-report-2026-07-24-workstation-lock-blocker-fixes.md`.
- Topic branches to publish:
  `codex/workstation-lock-blocker-fixes-2026-07-24` and
  `codex/workstation-hardening-lock-blocker-fixes-2026-07-24`.
- `master` was neither merged nor pushed.
- No pull request was created.
- Remote push confirmation and the final Mission 1 report-commit SHA are
  supplied in the agent handback after this report is committed.
- The mirror deny ACL remains installed and should be removed only by an
  authorized operator after the production host has consumed the evidence.
