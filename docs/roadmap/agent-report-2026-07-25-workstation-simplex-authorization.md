# Agent report — 2026-07-25 workstation simplex authorization

Status: **COMPLETE**. The literal residue qualification, authorized paired
PIT, full-suite classification, frozen remeasurement input materialization,
repair-active pooled replay, recorded-hourly control, source ablation,
comparator, and containment checks are terminal.

This report executes
`docs/roadmap/workstation-handoff-2026-07-25-simplex-authorization.md`,
file SHA-256
`93dd938c80fea03e15b3e480b8de9304dadfa1d55accc18a45d06f5b50dcf1f5`.
It is the dated successor to
`docs/roadmap/agent-report-2026-07-24-workstation-pit-simplex.md`, file
SHA-256
`35c2f2009449dd883f82b1bf519f9fcfe85fee03327ebf3e11773e2d0d96ccae`.

The remeasurement and paired-PIT expectations were frozen before observing
either result in
`docs/roadmap/simplex-remeasurement-preregistration-2026-07-25.md`, file
SHA-256
`7e807b2d59e492b154db5e5fb3a1136deeca3b70e5defdbe21893237d0963254`,
committed as `c5345de9`.

## Executive verdict

| Question | Verdict | Basis |
| :--- | :--- | :--- |
| Is the live path currently emitting mass-violating probabilities? | **NO EVIDENCE OF AN ACTIVE LIVE FAILURE** | The production-host measurement supplied by the handoff found every nondegenerate recorded partition unit-mass. The code defect is latent in live serving because the contextual blend is currently disabled there. |
| Is the replay defect real? | **YES** | Pooled artifacts enable the contextual blend, and the accepted baseline replay produced simplex failures on genuinely complete source days. |
| Did the literal 93 genuine-day failures survive the repair? | **NO — ZERO RESIDUE** | Repaired qualification changed 93 genuine plus 56 synthetically admitted simplex failures to zero, with the same 23,518-row evaluation window. |
| Did the repair introduce a repository-test regression? | **NO NEW REPAIR REGRESSION FOUND; SUITE NOT GLOBALLY GREEN** | The raw suite had 52 failures. Convergence left the five preregistered pre-existing nodes, six preregistered Windows executor nodes, and seven ledger-fixture failures reproduced unchanged on exact baseline `09756227`. |
| Does the V6b paired PIT change from `BLOCK` to `PASS`? | **YES — `BLOCK -> PASS`** | From the same 26,840-row evaluation window, exact `09756227` rejects 114 simplex cutoff partitions containing 1,254 rows and scores 25,586; exact `803b3de6` rejects none and scores all 26,840. |
| Does repaired pooled replay materially change model-versus-market or source-ablation conclusions? | **NO — STANDING CONCLUSION UNCHANGED** | The final comparator is `PASS`. On 206,745 identical scored rows, candidate Brier improves by only `0.0001689706` and closes 0.68% of the still-positive market gap; source-ablation semantic delta is zero. The result is preregistered `IMMATERIAL`, triggers no leakage audit, and the model still loses to market. |
| Did candidate-local routing generation authorize promotion? | **NO** | The narrow authorization permits only the routing artifact needed as PIT input. Any such artifact is evidence-only and non-authorizing. |

No release construction, release pointer, registry activation, serving binding,
scheduler, collector, sizing, trading, pull request, merge to `master`, or
production-host action is authorized by this evidence.

## Production truth: latent live defect, active replay defect

The handoff's production-host measurement is accepted input and was not
rederived on this workstation. It parsed real recorded Toronto output, grouped
rows by `(snapshot_id, variant_id)`, and summed both `variant_probability` and
`serving_model_probability` across bands. All nondegenerate partitions were
exactly `1.000000000`: seven variants across 25 snapshots, with zero deviations
in either probability field. Variants that emitted all zeros were a separate
condition rather than probability-mass drift.

The implementation contains the same ordering defect in live and replay
paths, but `current_blend_enabled` is effectively off in recorded live
serving while pooled artifacts bake it on. The live defect is therefore
**latent, not currently active**. There is no evidence of production
contamination on this axis, and the recorded live probabilities remain
trustworthy on it. The defect becomes active in live serving only if a pooled
artifact carrying the enabled blend is bound there. The repair remains a
pre-lock requirement; this finding changes the urgency classification, not
the need for the lock gate.

## Identities, containment, and mirror guard

| Purpose | Identity |
| :--- | :--- |
| Pulled `origin/master` | `8f816f56f58b01be49290addbcbc94b64bbc542c`, containing the handoff's stated host-operations commit `5093af0b` |
| Baseline code | `0975622723129f47e179a4a188017773fbfa95fd` |
| Repaired code and owning documentation | `803b3de68e7de35bc9213aff5d94d6479b002ba6`; executable repair code ends at `55fcc7b9` |
| Fix topic | `codex/workstation-pit-simplex-fix-2026-07-24` |
| Declared single output root | `C:\Users\Michael\Documents\Codex\w24b` |
| Authorization mission root | `C:\Users\Michael\Documents\Codex\w24b\authorization-20260725` |
| Protected mirror | `C:\Users\Michael\Documents\github\weather\data` |

The pre-execution ACL receipt is
`C:\Users\Michael\Documents\Codex\w24b\authorization-20260725\pre-execution-mirror-acl-gate.json`,
file SHA-256
`330ed6d1e2def87c6e7d7302bd0f2be1c1291d68013f25c9689e2d6294361f45`.
The fresh canary write raised `System.UnauthorizedAccessException`, and the
path was absent afterward. The two explicit non-inherited deny ACEs for
`DESKTOP-RFCD2GH\Michael` and
`DESKTOP-RFCD2GH\CodexSandboxOffline` continued to deny
`DeleteSubdirectoriesAndFiles, Write, Delete`.

The exact-`803b3de6` worktree data-junction receipt has file SHA-256
`79248180421cbf7408a472195f2f24dbc276cbe7ec71ce4362475182885405d1`.
It records a Windows junction to the protected canonical mirror, unchanged ACL
SDDL before and after, a denied write canary, and a denied delete-access probe
that did not issue a destructive delete.

The repository's frozen promotion-output containment regression passed:

```text
tests/calibration/test_promotion_output_containment.py::TestPromotionOutputContainment::test_frozen_promotion_tree_writes_only_below_output_root
1 passed in 1.82s
```

Its console file SHA-256 is
`b3be24d39576b31ce84c3f44fb615b9d8b334e5361a75a5e9c06d166af968fc6`.
The paired-run receipts must additionally prove that the actual authorized
routing-generation writes stayed below each candidate run root.

## Narrow authorization boundary

The authorization permits candidate-local `promotion_refresh` only to emit
the frozen routing artifact required by PIT. It does not permit release
construction, a release or active-pointer write, registry promotion, serving
adoption, or any scheduler, collector, sizing, or trading change.

For each paired side, this report will record the exact command, run root,
artifact path and hash, and observed output containment. The term
`promotion_refresh` below names the implementation step; it does **not** state
that a promotion occurred. Every generated routing artifact remains
evidence-only and non-authorizing.

## Authorized paired V6b PIT

The paired input contract is already frozen:

| Binding | Value |
| :--- | :--- |
| Staging-receipt semantic SHA-256 | `f2b05a343005084bab6cd3528a032422d545945d38c5ccc9586011bc8e59a952` |
| Staging-receipt file SHA-256 | `b34533452e1d63699cbe1fee93a4fdb56a2b84ae92e908fbc9f938095f598f09` |
| Preselection hash | `e398abf58b43d2889a0faf4fdd43ad7633bc6d228bc00c5556e4a7c49610422c` |
| Window-lock ID | `9d3be4615516039bb61697f28c44dfcfdac201d58276d9260632abc63b7722d9` |
| Locked dates | `2026-07-09..2026-07-22` |
| V6b input-manifest semantic SHA-256 | `842b9cac8a96e34bf352451f3c0f77d9bab00157c001a45172b6ac249d34d3b4` |
| Frozen harness inventory SHA-256 | `7f35a0f235838ab3e7c52385cef43c120b587812a67cdf183bfa11876e5bed2c` |

### Formal baseline terminal evidence

The formal baseline ran below
`C:\Users\Michael\Documents\Codex\w24b\positive-control-v6b\run\baseline-09756227-v6b-authorized`
on exact `0975622723129f47e179a4a188017773fbfa95fd`. The reviewed paired
runner SHA-256 is
`0201e97d199801f79f8780dec3be8dd9cd572d5eb12f7f74e8a35a9c9794f93c`,
and the path-normalized paired argv SHA-256 is
`ab0786b2740402d3427b1eaaa77b12a46a00738cbd01b95c3029b045ef6a4eb9`.
The invocation and runtime file SHA-256 values are respectively
`419cdb72f787a0bee72881a521eb3a70c994d413b9b008e676d379a3f058a915`
and
`319016b7c6f8b85b24ecd790a96224eb12100e8fb0248db85fcc2d6954e88d27`.

PIT reached terminal `BLOCK` with 114 cutoff partitions rejected as
`probability_simplex_failure`. Those partitions contain 1,254 of the common
26,840 evaluation-window rows, leaving 25,586 scored rows across 2,326
cutoffs. The evaluator's distinct top-level `excluded_rows` metric is zero.
The streaming-evaluation file SHA-256 is
`fe834fddd4832a35aaaeae944f9311993901928e9aff951bea10eaff61a37b68`.
All four bootstrap configurations used exactly 2,000 iterations and seed
`31415`; the wrapper's bootstrap assertion was `PASS`.

The native nightly exit was `1`, as expected from `--fail-on-block` after a
terminal PIT block. The wrapper recorded no primary or postflight error.
Nightly evidence, code-surface cleanliness, ambient-support before/after
equality, promotion-output containment, and declared-state postflight all
passed.

### Authorized baseline routing-generation record

The exact `promotion_refresh` step returned `0` after 619.96 seconds. Its
command array rendered as one command is:

```text
C:\Users\Michael\Documents\github\weather\venv\Scripts\python.exe -m weather.reporting.promotion.promotion_refresh --family-unit F --output-root C:\Users\Michael\Documents\Codex\w24b\positive-control-v6b\run\baseline-09756227-v6b-authorized\artifacts\candidates\nightly-v6b-baseline-09756227-authorized\qualification\promotion --snapshots-root C:\Users\Michael\Documents\Codex\w24b\positive-control-v6b\inputs\snapshots --quality-grades complete,manual_override --artifact C:\Users\Michael\Documents\Codex\w24b\positive-control-v6b\run\baseline-09756227-v6b-authorized\artifacts\candidates\nightly-v6b-baseline-09756227-authorized\model\feature_model_hgb_f_pooled_v0_3.pkl --out C:\Users\Michael\Documents\Codex\w24b\positive-control-v6b\run\baseline-09756227-v6b-authorized\artifacts\candidates\nightly-v6b-baseline-09756227-authorized\qualification\promotion\promotion_refresh.json --report C:\Users\Michael\Documents\Codex\w24b\positive-control-v6b\run\baseline-09756227-v6b-authorized\artifacts\candidates\nightly-v6b-baseline-09756227-authorized\qualification\promotion\promotion_refresh_report.md --long-job-state C:\Users\Michael\Documents\Codex\w24b\positive-control-v6b\run\baseline-09756227-v6b-authorized\long-job-state.json --long-job-lock C:\Users\Michael\Documents\Codex\w24b\positive-control-v6b\run\baseline-09756227-v6b-authorized\long-job.lock --long-job-priority below_normal --frozen-corpus C:\Users\Michael\Documents\Codex\w24b\positive-control-v6b\run\baseline-09756227-v6b-authorized\artifacts\candidates\nightly-v6b-baseline-09756227-authorized\qualification\point_in_time\work\promotion_selection_corpus.json --frozen-corpus-sha256 1e0c18b8a1ba379060ed6ccfa3be55e29b81abc18c0c034e8997727e16e9995b --frozen-corpus-hash fecb79fad291e1097ad79bb4645030208c8e47529b61c8ede7923ccee575d73f
```

The evidence-only routing artifact is 7,057,361 bytes with file SHA-256
`73ca03c75101e222ed509dec64bf73e2cd1063aefcedb67305be984c56d6369f`.
It was one of 37 files added below the exact authorized candidate-local
promotion root. Zero files escaped that root; changed-prior and removed counts
were also zero. Forbidden-promotion, release, and pointer counts were zero.
This candidate-local computation emitted PIT input evidence; it did not
authorize or perform promotion.

The formal baseline and formal repair are learned-model equivalent across the
actual pair. Their shared prediction-relevant derived-model semantic SHA-256
is
`96c725fd9d72a2a56f72f9eb533e669314b86dd5df742b920a00227b8131ad92`,
their shared learned-state SHA-256 is
`15b6e685e34d9cb56e230306f22583b6a1aff2ecfa6d60e6f2dce2ce42ffb4e1`,
and their shared exact 14,336-row prediction-probe SHA-256 is
`eb6fe985d14bb66fab69db53c27d4c3b6f79e0e839f6f37802fe66ef7faeca5e`.
The probe's maximum cross-side prediction difference is exactly zero. Their
raw serialized artifact file hashes differ because serialization and runtime
metadata differ, not because the learned state or predictions differ.

The formal baseline and repeated attempt-2 baseline are also prediction-
equivalent despite enumerated volatile routing fields. After removing those
fields, the two baseline routing artifacts have semantic SHA-256
`d38785179f2b16be5b782f7a9d602f71d516f989c461cd1282a383cd332bd8e5`.

### Paired routing causal gate

The completed routing-level causal comparison isolates the repair. Both sides
contain 38,027 rows in the exact same key order. Their projection over all
invariant fields is exactly equal, and their normalized secondary-artifact
semantic SHA-256 is identically
`ff4d943214bf4001487a410595d099ed65becb6b695c769fc5ea01860148aaa1`.

The repair adds the exact `candidate_preblend_probability` provenance field
on all 38,027 rows. Across 3,457 probability partitions, the baseline has 609
non-unit partitions and the repair has zero; the maximum repaired mass
residue is `5.55e-16`. For every row, the repaired final probability equals
the baseline final probability divided by the baseline partition sum, with
maximum absolute error `3.03e-12`.

There is no upstream candidate, current/incumbent, recorded-market,
market-price, outcome, feature, key, or ordering drift. The causal delta is
therefore exactly the intended post-blend categorical mass restoration plus
its provenance column. The terminal PIT below independently closes the
lock-control result; neither result authorizes any promotion action.

### Formal repair terminal evidence

The repair ran below
`C:\Users\Michael\Documents\Codex\w24b\positive-control-v6b\run\repaired-803b3de6-v6b-authorized`
on exact `803b3de68e7de35bc9213aff5d94d6479b002ba6`. Its invocation,
runtime, and nightly-status file SHA-256 values are respectively
`aa22929c92eb309eeeaf2a88da4324d186cf745e3fbae9e646188bb575071c9e`,
`cb833c5eb1bca2dc6bf81ef4f28aa1143dbc687a155e6e4c28f2c784c1acfdca`,
and
`8771b7ee5bbc67e1dd2d65b9393a839ba0ebd26028281a8238568ec0794b1291`.

The pair binding is `PASS`: the repair used the same runner SHA-256
`0201e97d199801f79f8780dec3be8dd9cd572d5eb12f7f74e8a35a9c9794f93c`,
the same path-normalized argv SHA-256
`ab0786b2740402d3427b1eaaa77b12a46a00738cbd01b95c3029b045ef6a4eb9`,
and the same frozen input identity as the formal baseline. Both streaming
evaluations bind selection-universe SHA-256
`a15fdd398a051cbfd491488372431845c55ad89e605b84e1870b07645e41bf73`:
64,867 input rows, 38,027 outside-window rows, and the same 14 target dates.

| PIT result | Baseline `09756227` | Repair `803b3de6` |
| :--- | ---: | ---: |
| Terminal state | `BLOCK` | `PASS` |
| Simplex-excluded cutoffs | 114 | 0 |
| Common evaluation-window rows | 26,840 | 26,840 |
| Rows omitted from scoring because their cutoff partition was simplex-rejected | 1,254 | 0 |
| Evaluator top-level `excluded_rows` | 0 | 0 |
| Scored cutoffs | 2,326 | 2,440 |
| Scored rows | 25,586 | 26,840 |
| Streaming-evaluation SHA-256 | `fe834fddd4832a35aaaeae944f9311993901928e9aff951bea10eaff61a37b68` | `f1e9d15e61c49626763f6ddac0e8bcdd1df3b1811fead4d0138053ddba2218b4` |

Every restored repair cutoff and row maps exactly to a baseline
simplex-rejected cutoff partition. In the table, “restored rows” means rows
returned to the scored population, not the evaluator's top-level
`excluded_rows` metric:

| Target date and market | Restored cutoffs | Restored rows |
| :--- | ---: | ---: |
| 2026-07-09 Dallas | 48 | 528 |
| 2026-07-10 Denver | 3 | 33 |
| 2026-07-11 Atlanta | 1 | 11 |
| 2026-07-13 Dallas | 7 | 77 |
| 2026-07-14 Denver | 1 | 11 |
| 2026-07-15 Atlanta | 15 | 165 |
| 2026-07-17 Dallas | 1 | 11 |
| 2026-07-18 Denver | 17 | 187 |
| 2026-07-19 Atlanta | 1 | 11 |
| 2026-07-21 Dallas | 20 | 220 |
| **Total** | **114** | **1,254** |

The normalized materialization-manifest semantic SHA-256 is identically
`fae4983039001377f77be04a7fe48dcd5b14f91944802f5f775644c235a5ba63`;
all 169 run-derived differences are accounted for and none are unknown. The
normalized validation-plan semantic SHA-256 is identically
`2399b21c884d3194511fa2df6dd3e36a449883a57696ccbbc8af8a51dd0ce402`;
all 144 run-derived differences are accounted for and none are unknown. The
pre-input replay manifest and frozen selection corpus are identical. These
facts establish contract, topology, and source-universe equality, not
output-byte equality: the raw PIT corpus necessarily differs because the
repair changes the final probabilities and adds provenance.

All four repair bootstrap configurations used exactly 2,000 iterations and
seed `31415`; the wrapper assertion is `PASS`. The runtime has
`primary_error: null` and an empty `postflight_errors` list. Its code-surface
postflight is clean on exact `803b3de6`. Ambient-support receipts before and
after have file SHA-256 values
`8da06c221adde688102a9e90f008bc70dc19e6f754bc4dccbfd37c1870a72db7`
and
`171a0850757fe730f249daebe688d0e306ce18620cc890088294bfb52440d9dc`;
the after receipt compares `relative_path`, existence, bytes, and SHA-256
against the before receipt with zero mismatches.

The requested PIT component changes from terminal `BLOCK` to terminal `PASS`,
but the repair nightly as a whole does not pass: its native exit is `2` and
`nightly-status.status` is `blocked`. This intentionally non-authorizing lane
disabled candidate release construction, has release identity
`RESEARCH_UNBOUND`/`BLOCK`, and has no active release pointer; its
model-quality/routing result also remains `DO_NOT_CUT_OVER`. The nonzero
overall exit is therefore distinct from the PIT result, is not a repair
execution error, and must not be read as release or cutover readiness.

### Authorized repair routing-generation record

The exact repair `promotion_refresh` step returned `0` after 580.51 seconds.
Its command array rendered as one command is:

```text
C:\Users\Michael\Documents\github\weather\venv\Scripts\python.exe -m weather.reporting.promotion.promotion_refresh --family-unit F --output-root C:\Users\Michael\Documents\Codex\w24b\positive-control-v6b\run\repaired-803b3de6-v6b-authorized\artifacts\candidates\nightly-v6b-repaired-803b3de6-authorized\qualification\promotion --snapshots-root C:\Users\Michael\Documents\Codex\w24b\positive-control-v6b\inputs\snapshots --quality-grades complete,manual_override --artifact C:\Users\Michael\Documents\Codex\w24b\positive-control-v6b\run\repaired-803b3de6-v6b-authorized\artifacts\candidates\nightly-v6b-repaired-803b3de6-authorized\model\feature_model_hgb_f_pooled_v0_3.pkl --out C:\Users\Michael\Documents\Codex\w24b\positive-control-v6b\run\repaired-803b3de6-v6b-authorized\artifacts\candidates\nightly-v6b-repaired-803b3de6-authorized\qualification\promotion\promotion_refresh.json --report C:\Users\Michael\Documents\Codex\w24b\positive-control-v6b\run\repaired-803b3de6-v6b-authorized\artifacts\candidates\nightly-v6b-repaired-803b3de6-authorized\qualification\promotion\promotion_refresh_report.md --long-job-state C:\Users\Michael\Documents\Codex\w24b\positive-control-v6b\run\repaired-803b3de6-v6b-authorized\long-job-state.json --long-job-lock C:\Users\Michael\Documents\Codex\w24b\positive-control-v6b\run\repaired-803b3de6-v6b-authorized\long-job.lock --long-job-priority below_normal --frozen-corpus C:\Users\Michael\Documents\Codex\w24b\positive-control-v6b\run\repaired-803b3de6-v6b-authorized\artifacts\candidates\nightly-v6b-repaired-803b3de6-authorized\qualification\point_in_time\work\promotion_selection_corpus.json --frozen-corpus-sha256 1e0c18b8a1ba379060ed6ccfa3be55e29b81abc18c0c034e8997727e16e9995b --frozen-corpus-hash fecb79fad291e1097ad79bb4645030208c8e47529b61c8ede7923ccee575d73f
```

The evidence-only routing artifact is
`C:\Users\Michael\Documents\Codex\w24b\positive-control-v6b\run\repaired-803b3de6-v6b-authorized\artifacts\candidates\nightly-v6b-repaired-803b3de6-authorized\qualification\promotion\promotion_refresh.json`.
It is 7,055,741 bytes with SHA-256
`465ee67df64a0bdf5d1e0480d732df67e2e890bed2f5a8d2c2c1a75fe3d5a692`.
Exactly 37 files were added below the authorized repair promotion root, with
zero escaped additions, changed prior files, or removals. Across the complete
pair, 74 promotion files are declared: 37 under each authorized candidate
root. Release, active-pointer, forbidden-promotion, canonical-registry, and
serving-surface write counts are zero.

The routing disposition projection is identical on both sides with semantic
SHA-256
`3c2767c99708a14441764b9d7ffd9ac07c075a1e9ae5614fceaa099fc74097cf`;
each result has zero `promote`, seven `shadow`, and four `blocked`
dispositions. One disclosed near-threshold Austin missingness slice
(`n=8,459`, feature-missingness SHA-256
`eafba610ce2e37395319a2711e7170d572aec98345d7e9b2fa9fb476f523bb43`)
moves from candidate-minus-market Brier `0.0030275592096254064` and `BLOCK`
to `0.0027297253988089742` and `PASS` after normalization. The overall
model-quality gate and routing dispositions remain unchanged. This
candidate-local computation produced required PIT evidence only; it neither
performed nor authorized promotion.

### Preserved paired attempts

#### Attempt 1: stale ambient-support anchor

The first authorized baseline attempt is preserved at
`positive-control-v6b\run\failed-attempt1-baseline-09756227-v6b-authorized-stale-ambient-anchor`.
It stopped in preflight before nightly execution, routing generation, model
training, or PIT. Its ambient-support inventory was incorrectly compared
against the older family-preflight anchor. Twenty-two legitimate canonical
Weather Underground paths had grown since that anchor, so the receipt blocked
with `mismatch_count: 22` and the runtime recorded
`Ambient support before inventory failed`.

This is an orchestration-anchor failure, not a model or PIT result. The
preserved runtime has no native nightly exit, no PIT terminal state, no
routing artifact, zero promotion files, zero release files, and zero pointer
files. Its code-surface postflight was clean and unchanged. The failed
attempt's runtime file SHA-256 is
`dfba72694df35d7bd124e414482de2fa05e9a36e70e14df17ffb9fdf9d1f2d27`;
the preserved stale-anchor support receipt SHA-256 is
`d047d0535338aeb5bca0a34b9475b0b36079b2d64dca2b14f5e773c44927e219`.
It is retained as failed-attempt evidence and is excluded from the paired
verdict.

#### Attempt 2: wrapper postflight type failure

The second baseline attempt completed the underlying exact-`09756227` nightly
run. PIT reached terminal `BLOCK` with 114 excluded cutoffs, all classified as
`probability_simplex_failure`. Its candidate-local `promotion_refresh`
artifact is 7,057,361 bytes with SHA-256
`1f78ebd2ea6c3e03499c34d5eb21e168c190ce4b7059a75cb60ecd391e5df53d`.
The promotion-output delta contained 37 added files, zero changed prior files,
zero removed files, and zero files outside the authorized candidate-local
root. Release-file and pointer counts remained zero.

The wrapper nevertheless failed after that underlying result. Its bootstrap
receipt remained null because PowerShell's `return @($Found)` hit a collection
binder error, surfaced as `Argument types do not match`. This was a postflight
harness failure: it did not change the already written PIT result or routing
artifact, but it prevented the wrapper from producing a complete paired
receipt. The attempt is therefore preserved at
`authorization-20260725\preserved-paired-attempts\failed2-baseline-postflight-type`
and excluded from the formal pair rather than repaired in place. Its runtime
file SHA-256 is
`7b237716e01e4d96b2b44a6a584e46374466eebd82548504683600779f83ac68`.

The binder defect was corrected and reviewed before a clean rerun. The rerun
uses runner SHA-256
`0201e97d199801f79f8780dec3be8dd9cd572d5eb12f7f74e8a35a9c9794f93c`.
Attempt 2 is useful reproduction and containment evidence, but it is not
substituted for the completed formal paired verdict.

#### No-run preflight launches

Two intervening launcher preflights stopped before creating a run root. One
rejected an overlong archived-attempt path; the other correctly treated the
historical `promotion_refresh` files still visible inside the active paired
namespace as forbidden prior promotion output. Moving preserved attempt 2 to
the shorter
`authorization-20260725\preserved-paired-attempts\failed2-baseline-postflight-type`
path outside the active pair namespace resolved both conditions. Neither
preflight launched nightly, ran routing generation, trained a model, or
reached PIT, so neither is a model result or part of the formal pair.

## Literal 93 genuine-day residue

**PASS: zero simplex residue.** The repaired qualification ran on exact
`803b3de68e7de35bc9213aff5d94d6479b002ba6`, exited `0` after 331.513
seconds, and recorded `integrity_status: PASS` with every declared output
below
`C:\Users\Michael\Documents\Codex\w24b\simplex-residue-93\fix803`.

The exact full argv is retained in that root's `invocation.json`. The command
used the production `qualify-production` evaluator with candidate and release
ID `nightly-20260724T033000000000Z`, the same frozen model, calibration,
routing, preselection, replay manifest, source corpus, and source manifest as
the accepted baseline lane, 2,000 bootstrap iterations, `--as-of 2026-07-23`,
and `--window-end 2026-07-21`. All mutable outputs and runtime directories
were below the declared root.

| Population | Baseline simplex failures | Repaired simplex residue |
| :--- | ---: | ---: |
| Genuinely complete source days | **93** | **0** |
| Source-partial days synthetically declared complete | **56** | **0** |
| **Total** | **149** | **0** |

Both sides use the same 52,932 source rows and 23,518 evaluation-window rows.
The baseline was `BLOCK` with 149 excluded cutoffs. The repair was `PASS` with
zero excluded cutoffs and an empty exclusion-reason map. The evaluation still
contains 2,138 cutoffs across the 14 locked Atlanta dates. No second defect
survived.

### Per-day attribution

| Source date | Source grade | Baseline failures | Repaired residue |
| :--- | :--- | ---: | ---: |
| 2026-07-08 | partial, synthetically admitted | 2 | 0 |
| 2026-07-12 | partial, synthetically admitted | 3 | 0 |
| 2026-07-13 | partial, synthetically admitted | 50 | 0 |
| 2026-07-14 | complete | 49 | 0 |
| 2026-07-16 | complete | 21 | 0 |
| 2026-07-17 | complete | 7 | 0 |
| 2026-07-18 | complete | 1 | 0 |
| 2026-07-19 | partial, synthetically admitted | 1 | 0 |
| 2026-07-21 | complete | 15 | 0 |

### Input-closure qualification

The input audit supports the result but is not a claim of exhaustive
cryptographic closure over every runtime read:

- all 100 manifest-pinned `snapshots_long.csv` and `replay_inputs.jsonl`
  files matched their frozen identities;
- all 50 `features_long.csv` files were independently rechecked and matched;
- the evaluator also read 30 CLOB summary files outside the frozen manifest;
  those files were protected by the stable deny-write ACL, but they do not
  have cryptographic before/after proof in this run; and
- all 50 `settlement.json` sidecars had drifted from the older folder
  inventory, but were not consumed by this qualification because labels came
  from the manifest-pinned replay contract.

Accordingly, this report does not say that every consumed input was
cryptographically pinned. It says the production-manifest tape/replay inputs
and independently checked feature files were exact, the additional CLOB reads
were ACL-protected but incompletely bound, and the drifting settlement
sidecars were not inputs to the result.

The missing historical hashes for those 30 CLOB summaries are not material to
the residue verdict. A semantic dependency audit found zero CLOB features in
the bound artifact, so the summaries cannot change `candidate_p`.
`market_yes` and the one-hot outcome labels are fixed by the manifest-pinned
replay inputs. Candidate Brier is derived from `candidate_p` plus those frozen
labels; market benchmark Brier, where relevant, is derived from `market_yes`
plus the same labels. Simplex classification depends only on the sum of the
candidate probability partition. The CLOB reads therefore cannot affect
`candidate_p`, `market_yes`, the frozen labels, either Brier calculation, or
the simplex pass/exclusion decision for this artifact. Their unbound identity
remains a provenance limitation for exhaustive runtime closure, not a
plausible cause of the observed `149 -> 0` residue transition.

Key evidence hashes:

- baseline corpus:
  `8a5d03748ca7d9d407282d65a2fac22f1b47de259fde7781bf3ff48faf94eafb`;
- repaired corpus:
  `bc17f85ef13f9c6e7cd411b6d8e31664b752ef9f523cab128b221d99846617e7`;
- runtime:
  `04cbd7f84ecee59073bf5d94e0f98f084f561566b842031ead880f42c3abf7e7`;
- residue comparison:
  `e189a767db34b6dae7389f00ecfe90bae08d1ef8ec2e3c8356c979c7d1ac4860`;
- streaming evaluation:
  `51ce7b55699440dddb5906fa83eceb9be516981d4cae1d277f0636a74938f815`;
- input verification:
  `6ffd44c5d9cf4a8b72243525135ea56d29f82255ebea54dc4e509d56688a3354`;
  and
- invocation:
  `4baf00369d030b4072095688462cdbbbb26593c98d34e2817c6ed61ca07df97f`.

## Full repository pytest

The full suite is **not globally green**, but the failures do not identify a
new repair regression.

The exact-`803b3de6` raw run reported:

```text
52 failed, 3063 passed, 3 skipped, 13 warnings,
812 subtests passed in 796.07s
```

Because the prior mission established Windows extended-path and child-working-
directory instability, the failing set was rerun three times:

| Run | Result | Purpose |
| :--- | :--- | :--- |
| Raw | 52 failed, 3,063 passed, 3 skipped, 812 subtests passed | Full repository suite |
| Convergence 1 | 30 failed, 22 passed, 183 deselected | Short external base temp |
| Convergence 2 | 24 failed, 6 passed, 183 deselected | Extended-length base temp |
| Convergence 3 | 18 failed, 6 passed, 183 deselected | Short TEMP and base temp |

The final 18 failures classify as follows:

1. The same five preregistered pre-existing nodes remained:
   the app-architecture wrapper check, both source-cache TTL tests, and both
   module-size ownership tests.
2. Six of the seven preregistered Windows executor fixture nodes remained:
   terminal disposition, timeout tree-kill, unexpected output quarantine,
   absolute serving-mutation denial, undeclared external-read denial, and
   queue-change supersession. The staged-input-mutation node passed; the
   preregistration explicitly allowed a known-failure node to pass.
3. Seven additional fixture cases failed because the protected canonical
   mirror now rejects their stale ledger/tape bindings with
   `SettlementAuthorityError`:
   three `TestSettlementAndTape` cases, the afternoon-residual trainer case,
   the model-ensemble loader case, the daily-refresh live-settlement case, and
   the WU-max-since-7 report case.

The seven ledger cases were then run on exact baseline
`0975622723129f47e179a4a188017773fbfa95fd`. The same seven node IDs failed
with the same authority mechanism in 5.43 seconds, including the same Toronto
May 27, NYC June 22, and Toronto June 3 invalid tape bindings. They are
environment/protected-fixture effects rather than repair regressions.

No calibration, replay, simplex, probability-mass, or changed repair-path
failure survived convergence.

Key full-suite evidence hashes:

- raw invocation:
  `bc6ea5aee7dae315fb79d9d1140ec34cf2afdee77dadf3af1e399ddb31433d14`;
- raw runtime:
  `6d109c15762a4efc3c46922739abafb54304da9ef627fea491839d7b49566720`;
- raw console:
  `217df4db69e8f05e0400ff51edd6ae7c14b059866ab50d4cfe0324685c19cef9`;
- raw JUnit:
  `a0806ec93bd054c962481caa402508dac54ad5a1214b288aab4d3e1890b12205`;
- final convergence runtime:
  `965922953f238333a468dc0e5368507e0e3f83f5946e8db36c93a5ab3e00f080`;
- final converged `lastfailed`:
  `6722a3ad42ff4d63cb16b455851a7d7638898cefaa7220458a6fd90c36ae807f`;
- baseline fixture-reproduction runtime:
  `e1cb246d19065858160f69ce3f5da052805a5d970752701bcd29dc90c85e7aad`;
- baseline fixture-reproduction console:
  `e3d6534bd9e50dc41634b77eb427284bf5f7a58036d4175bd19463de83a3ee4a`;
  and
- baseline fixture-reproduction JUnit:
  `172d5f25b11c292f68d9e6de7fbf05e3a8467ac40608331dc22f62e4d99788eb`.

## Model-versus-market and source ablation

The frozen cohort materialization is complete and warning-free. It wrote only
below
`C:\Users\Michael\Documents\Codex\w24b\authorization-20260725\remeasurement`.

### Frozen headline cohort

- `2026-06-28..2026-07-10`;
- 141 market-days across 12 markets;
- 20,586 snapshots and 226,479 band rows;
- subset corpus hash
  `a59c59a4fcc4071bf707650b859bf3fc7754d79d3d3517f6997c4a8a3d6438a1`;
  and
- materialized file SHA-256
  `128db63ec78c92a4126f886caec078dcab6786b47d0d65ad0aff10f5f1dc1dc5`.

### Frozen ablation cohort

- `2026-06-03..2026-06-13`;
- 51 market-days across 12 markets;
- 5,586 snapshots, 61,446 bands, and 2,623 identity records;
- subset corpus hash
  `5d11e7abb00cb944df8b6b8fd0dde127e39b7bc3d8d5fb3965893a712b7d4336`;
- materialized file SHA-256
  `6ec15cd194de2df0c052b5182d0134f17ee76072171aac32e9d539f83f00995d`;
  and
- sorted key-set SHA-256
  `52d76b22c62c8c7ece138691cdacd1e9974c8145a5b51224b82bb33263642f19`.

The pooled artifact is 6,310,781 bytes with SHA-256
`3b472bd32667256c6605a6f48c2c9c4ba7e58f140a89c504c4b4fbfcac6a497c`.
The cohort receipt SHA-256 is
`a69328c657d745e58a39363a892e1006500df14140eaa0aaa877b3a3e3c9e2ae`;
the materialization-step receipt SHA-256 is
`fe36feee4052bc350f16043c425d92e503975f0fd0ec1b7591a810114ea794f0`.

### Repair-active pooled replay

The frozen headline manifest contains 141 market-days across 12 markets and
226,479 band rows. Under the family-unit contract, the F-family artifact's
repair-active scored lane contains 129 market-days across 11 markets and
206,745 band rows; the 19,734 non-F Toronto rows are excluded. The pooled
levels below therefore must not be compared directly with the 141-day
recorded-hourly control.

The repair-active pooled comparison is terminal on those 206,745 identical
scored rows:

Here, “identical” means the same sorted row-key sequence and order over
`(market_id, target_date, snapshot_id, band_key)`, with unchanged labels
(`outcome`, `range_label`, `bin_type`, and `bin_value`), market probability
(`market_yes`), and current/incumbent values (`current_probability` and
`recorded_probability`), captured time, hour, and regime. The final comparator
is `PASS`; its file SHA-256 is
`4709c10f0ad4c493363b1392378ae0e079b9294dbb94ec922cdbb95ec3e0a7ba`.
The comparison-step receipt is `PASS` with exit `0`, file SHA-256
`6f000f585536b0f402796b435fffb07d4fd1077bbb902facbe017768123d6f56`,
command SHA-256
`4568ce701a33033075efa8e2ceb515d8e4e19a715589cb6b90c3a1327aa5bc6e`,
and input-identity SHA-256
`6df36a295d0fda1167d99817b55c2ac67bdc88e7981564af268061bccf92f037`.
It executes the frozen comparison verifier, file SHA-256
`94bc6046a70db1a768c071eacd80855d6948de47cdc9ab71c388f2b98c2ec21b`,
which fails on any row-count, ordered-key, or stable-field drift. The two
source outputs are additionally bound by baseline and repair pooled-step
receipt SHA-256 values
`71392442410a7cd289392a80369d0b52c85ece5ca6cc9881407561d1f166c5bc`
and
`e383729735b544a3210f6d5e648e66338655b6583b73b5b154e6b4035a36772b`.
The comparator console SHA-256 is
`a4d98153feff2d7c5b8404570bc1d4a5cc17a06b7d154603f472c65e572f7b2a`.

Across the same 18,793 nondegenerate probability partitions, baseline has
5,835 unit-mass violations with maximum absolute deviation
`0.844398950620693`; repair has zero with maximum absolute deviation
`6.661338147750939e-16`.

| Metric | Baseline `09756227` | Repair `803b3de6` | Movement |
| :--- | ---: | ---: | ---: |
| Candidate Brier | `0.06222508439159597` | `0.062056113772513084` | `-0.00016897061908288658` |
| Market Brier | `0.03736863079279743` | `0.03736863079279743` | `0` |
| Candidate-minus-market Brier gap | `+0.02485645359879854` | `+0.024687482979715653` | 0.6797857080104699% closure |
| Candidate log loss | `0.219401316451449` | `0.206887436867291` | `-0.012513879584158` |

The repaired log-loss gap to the unchanged market remains positive at
`+0.0891428686413998`. Candidate-minus-market gaps remain positive across all
11 markets, 24 captured-at hours, three regimes, and 12 target-date slices;
there are zero sign crossings. Ten target dates improve and two worsen. The
largest target-date improvement is June 29 at `-0.0011538217`, leaving a
repaired gap of `+0.0764790866` and closing only 1.486253%; the largest
target-date worsening is July 2 at `+0.0002358193`, leaving a repaired gap of
`+0.0269061372`.

The only preregistered slices with absolute movement at least `0.001` are
Chicago (`-0.00172207`, 5.76% closure, repaired gap `+0.02819`), Atlanta
(`-0.00139216`, 4.35%, `+0.03060`), June 29 (`-0.00115382`, 1.49%,
`+0.07648`), and hour 21 (`-0.00106792`, 1.82%, `+0.05756`). The largest
worsenings are Miami `+0.00059432`, July 2 `+0.00023582`, hour 02
`+0.00027499`, and midday `+0.00000863`. None approaches or crosses the
market benchmark.

The absolute Brier movement is below `0.001`, gap closure is far below 20%,
and the gap does not cross sign. Under the frozen decision rule this result is
`IMMATERIAL` to the model-quality conclusion and does not trigger the
mandatory leakage/provenance audit. The larger log-loss movement is disclosed
but does not override the preregistered Brier/gap materiality rule.

### Recorded-hourly control

The recorded-live scorer, which bypasses the repaired pooled replay producer,
passed exact identity on 35,618 rows across 141 market-days. Its input-identity
SHA-256 begins `803498b3`. Both code identities report model Brier/log loss
`0.071913977957193 / 0.240779854090485` and market Brier/log loss
`0.0373369519133628 / 0.118228522818493`; movement is exactly zero. This
control confirms execution identity, not exercise of the repair. The final
comparator records semantic maximum absolute delta `0`.

### Source-ablation comparator

The generic `replay_ablation` path bypasses the repair. The final comparator
records semantic maximum absolute delta `0` across 51 scored days, all 25
requested variants, and the 23 variants with scoreable source support. Every
source value and rank is identical across baseline and repair.

`all_forecasts` and `forecast_baseline` tie for first source value at
`+0.03879678462054881`: on 76,879 rows, base Brier is
`0.04608652858561066`, market Brier is `0.0373228652005099`, ablated Brier is
`0.08488331320615947`, and the source helps on 50 days and hurts on zero.
`wu_history` follows at `+0.025032930320100066`. Thus the source-ablation
ranking and substantive conclusion are unchanged.

The baseline and repair source-ablation JSON files have respective SHA-256
values
`d4f04d8f76574d496bc8c955366226af5fc754b0802761a819e6300798dfc1c7`
and
`5dd8c8fc8bd51ab3c1a7236e14a4d51b0d4567d9dffbbaeba4b3fb1f35785dc1`.
The repair step's `PASS`/exit-`0` receipt has SHA-256
`fea6fdab5fee490cb1b99bb7847f6024cd7806c6548ed97b1aee80ab68594c97`
and input-identity SHA-256
`6356de8c006a3e4bd411b3239f8aadcd2f066eeecf404d8344890bfd45c930b3`.
Their raw hashes differ because generated metadata differs; the terminal
claim is exact semantic equality, not byte identity.

The overall Brier movement remains preregistered `IMMATERIAL`, no
leakage/provenance audit is required, and the source-ablation result is
unchanged. The candidate still loses to the market benchmark, so the standing
model-versus-market conclusion is unchanged.

## Direct answer

The repaired implementation eliminates the literal replay simplex failure:
all 93 genuinely complete-day failures and all 56 synthetically admitted
failures go to zero, with no second simplex defect in that frozen
qualification. Full-suite evidence is non-green but shows no new regression
attributable to the repair.

The formal V6b pair establishes the requested pre-lock PIT
`BLOCK -> PASS`: from the same 26,840 evaluation-window rows, exact
`09756227` rejects 114 cutoff partitions containing 1,254 rows and scores
25,586, while exact `803b3de6` rejects none and scores all 26,840. The
overall repair nightly nevertheless remains intentionally blocked and exits
`2` because this evidence lane is release-unbound and non-authorizing. The
real lock-time PIT gate remains required.

The repaired pooled replay and source-ablation comparator are terminal
`PASS`. The pooled Brier movement is preregistered `IMMATERIAL`, every
preregistered market/hour/regime/target-date gap remains positive, recorded
control and source-ablation semantic deltas are zero, and no leakage audit is
required. The model still loses to the market benchmark; the standing
model-quality conclusion is unchanged.

This report and every retained artifact are evidence-only. They authorize no
promotion, release, pointer, serving, scheduler, collector, sizing, trading,
PR, or merge action.

## Evidence inventory

- Authorization and test evidence:
  `C:\Users\Michael\Documents\Codex\w24b\authorization-20260725`.
- Literal residue:
  `C:\Users\Michael\Documents\Codex\w24b\simplex-residue-93\fix803`.
- V6b paired-control roots and the preserved stale-anchor attempt:
  `C:\Users\Michael\Documents\Codex\w24b\positive-control-v6b`.
- Protected canonical mirror:
  `C:\Users\Michael\Documents\github\weather\data`.
