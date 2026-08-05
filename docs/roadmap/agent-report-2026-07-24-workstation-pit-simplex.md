# Agent report — 2026-07-24 workstation PIT simplex and trust parity

This report executes
`docs/roadmap/workstation-handoff-2026-07-24b-pit-simplex-and-parity.md`.
It distinguishes the A1–A6 candidate baseline at `09756227`, the newly isolated
simplex repair, and evidence that still cannot exist before a real lock.

The handoff's independent A1 production-ledger check is accepted input and was
not rerun: zero current labels across all 12 markets lack a tape hash, 45
hashless Toronto rows are superseded revisions rather than current labels, and
20/20 recent Toronto tapes re-hash to the recorded value. This mission supplies
the A6 parity evidence that the handoff still required.

## Lock-plan change

**Do not merge `09756227` alone as the complete pre-lock repair.** Its bounded
candidate replay can emit non-simplex probability partitions from genuinely
`complete` production-shaped inputs. The synthetic quality override did not
manufacture the blocker: 93 of the 149 rejected cutoffs came from five
genuinely complete Atlanta source days.

The defect is the order of two real serving stages. The band candidate is
normalized, then a contextual incumbent blend applies a different alpha to
different bands without restoring categorical probability mass. The same order
exists in live serving and replay. A separate reviewable repair is isolated on
`codex/workstation-pit-simplex-fix-2026-07-24`: `d448302f` renormalizes after
contextual blending in both paths, and follow-up `9abba9db` preserves the exact
pre-blend partition for validator provenance. Final follow-up `55fcc7b9`
requires exact provenance and artifact bindings for mass-restored validation.
Direct live/replay parity and time-split validation coverage protect both
stages.

## Executive verdict

| Decision | Verdict | Basis |
| :--- | :--- | :--- |
| Real defect versus compatibility-lane artifact | **REAL DEFECT** | 93 failures were on genuinely complete source days; 56 were on source-partial days synthetically declared complete. |
| `09756227` as the complete pre-lock fix | **NO-GO** | The probability producer can violate the simplex on complete-grade data. |
| Isolated simplex repair | **FOCUSED TESTS GREEN, REVIEW REQUIRED** | Focused live/replay/PIT coverage passes. The paired positive control did not reach PIT because exact accepted code cannot combine the required routing artifact with the strict no-promotion interpretation used for this mission. The full repository suite was not run. |
| Genuine-only 14-day control on `09756227` | **PREFLIGHT PASS; PIT NOT-RUN** | Frozen staging and family-secondary preflight passed. The held full runner would lack the routing artifact that exact accepted code requires before PIT. |
| Will a future real 14-day Toronto lock pass PIT? | **UNKNOWN** | No real contiguous 14-day complete-grade window exists yet. The strongest available genuine-only control requires an explicitly declared calendar remap. |
| A6 frozen trust scoring | **PASS** | On identical tape-derived tuples and target-date sets, the complete trust row is exactly equal. The intended difference is a frozen, manifest-admitted input universe rather than an ambient filesystem scan. |
| Fresh pooled H2 artifact | **NOT-DONE** | Missions 1 and 2 plus the required blocker repair consumed capacity; rushing H2 would weaken the lock-critical result. |

No promotion, release build, release pointer, serving, scheduler, collector,
sizing, trading, or production-host action was performed. No consumed panel
was reused.

## Identity, containment, and mirror guard

| Purpose | Identity |
| :--- | :--- |
| Pulled `origin/master` | `8e03914b60a60065864923e127d13eed1b143bdb` |
| Accepted A1–A6 code baseline | `0975622723129f47e179a4a188017773fbfa95fd` |
| Report/parity topic | `codex/workstation-pit-simplex-2026-07-24`, stacked directly on `09756227`; A6 regression commit `455e2daca56ce506414f47df8f5bb3f8c18df234` |
| Separate simplex repair | `codex/workstation-pit-simplex-fix-2026-07-24` at `803b3de6`; executable repair code ends at `55fcc7b9` (`d448302f` plus two validator-provenance follow-ups), followed only by the owning runbook update |
| Declared single run root | `C:\Users\Michael\Documents\Codex\w24b` |
| Protected mirror | `C:\Users\Michael\Documents\github\weather\data` |

Before mission execution, the existing non-inherited deny ACL was re-read and
a new canary write was attempted at
`data\.codex-positive-control-write-canary-20260724b.txt`. Its ACL-receipt
file SHA-256 is
`0c5e50d24e1b3bc1e475f6a76bfed21e7c8344b8c27c6c81dcf3e764be8cce85`.

- Explicit non-inherited deny ACEs remain for `DESKTOP-RFCD2GH\Michael` and
  `DESKTOP-RFCD2GH\CodexSandboxOffline`.
- Denied rights remain
  `DeleteSubdirectoriesAndFiles, Write, Delete`.
- The probe raised `System.UnauthorizedAccessException`.
- The canary was absent afterward.
- Every execution worktree uses a Windows junction targeting that protected
  mirror.
- The ACL remains installed at handback.

All retained runtime, test, staged-input, and temporary outputs are below the
one declared `w24b` root. The root is outside the mirror. Test and compile
commands transiently created ignored `.pytest_cache` and `__pycache__`
directories in the two mission worktrees; the exact agent-created directories
were audited and removed before handback. No particular
`scratch\workstation-research-output` subtree is claimed or required under the
revised guardrail.

## Mission 1 — classify the 149 failures

The accepted fixed-master evaluation is:

`C:\Users\Michael\Documents\Codex\w24\r\synthetic_compatibility\m-s\artifacts\candidates\nightly-20260724T033000000000Z\qualification\point_in_time\streaming_evaluation.json`

Its canonical row source is
`C:\Users\Michael\Documents\Codex\w24\r\synthetic_compatibility\m-s\artifacts\candidates\nightly-20260724T033000000000Z\qualification\point_in_time\corpus.parquet`,
file SHA-256
`8a5d03748ca7d9d407282d65a2fac22f1b47de259fde7781bf3ff48faf94eafb`.
The streaming-evaluation file SHA-256 is
`80a773c914c4e7fa650158f0d6d22ceea3302cea23a1eca30e010a33f47e77ad`.

It contains 23,518 locked-window band rows, exactly 2,138 eleven-band cutoffs:
1,989 scored and 149 excluded as `probability_simplex_failure`.

### Cutoff-level 2×2

| Source-ledger grade | Simplex failure | Simplex pass | Total cutoffs |
| :--- | ---: | ---: | ---: |
| Genuinely `complete` | **93** | 927 | 1,020 |
| Source `partial`, synthetically declared complete | **56** | 1,062 | 1,118 |
| **Total** | **149** | **1,989** | **2,138** |

### Source-day 2×2

| Source-ledger grade | Day has ≥1 simplex failure | Day has no simplex failure | Total days |
| :--- | ---: | ---: | ---: |
| Genuinely `complete` | **5** | 1 | 6 |
| Source `partial`, synthetically declared complete | **4** | 4 | 8 |
| **Total** | **9** | **5** | **14** |

### Per-market-day attribution

| Source market | Source date | Genuine source grade | Failed cutoffs | Passing cutoffs |
| :--- | :--- | :--- | ---: | ---: |
| Atlanta | 2026-07-08 | partial | 2 | 164 |
| Atlanta | 2026-07-09 | partial | 0 | 151 |
| Atlanta | 2026-07-10 | partial | 0 | 136 |
| Atlanta | 2026-07-11 | partial | 0 | 130 |
| Atlanta | 2026-07-12 | partial | 3 | 60 |
| Atlanta | 2026-07-13 | partial | 50 | 100 |
| Atlanta | 2026-07-14 | **complete** | **49** | 111 |
| Atlanta | 2026-07-15 | **complete** | 0 | 174 |
| Atlanta | 2026-07-16 | **complete** | **21** | 154 |
| Atlanta | 2026-07-17 | **complete** | **7** | 157 |
| Atlanta | 2026-07-18 | **complete** | **1** | 183 |
| Atlanta | 2026-07-19 | partial | 1 | 153 |
| Atlanta | 2026-07-20 | partial | 0 | 168 |
| Atlanta | 2026-07-21 | **complete** | **15** | 148 |

The source grades come from the manifest-bound `folder_inventory` in
`C:\Users\Michael\Documents\Codex\w24\e\inputs-synthetic-compatibility\input-manifest.json`,
which retains each exact current source revision and explicitly records the
synthetic override. The failure counts come from the frozen canonical parquet
and reproduce the evaluation JSON exactly.

## Exact mechanism

This is only a probability-mass failure:

- every rejected row probability is finite and in `[0, 1]`;
- every rejected cutoff has 11 distinct bands;
- every label partition sums to exactly one;
- no band is missing or duplicated; and
- only the prediction sum breaches the evaluator's `1e-6` tolerance.

Across the 149 failures, probability sums range from `0.4327776514` to
`1.0012104125`: 140 are mass-deficient and 9 have excess mass. Mean signed
error is `-0.0164685392`.

The fixed-master producer path is:

1. `attach_band_candidate_probabilities()` predicts each band at
   `src/weather/calibration/pooled_candidate_replay.py:1201`, then normalizes
   the whole snapshot partition at line 1214.
2. It next calls `apply_current_blend_guardrail()` at line 1219.
3. That function loops band by band and calls `blend_with_current()` at
   `src/weather/calibration/pooled_candidate_replay.py:1381`.
4. The live path has the same ordering: initial normalization at
   `src/weather/collection/live_variant_predictions.py:847`, followed by the
   row-level blend at line 852.
5. `resolve_current_blend_alpha()` explicitly resolves one alpha per row in
   `src/weather/model/current_blend.py:212`. The production artifact policy is
   created in `src/weather/calibration/pooled_training.py:1753`; warm-tail
   context rules set alpha to `0.35` at lines 1767–1786 while ordinary Atlanta
   bands retain the default `1.0`.
6. PIT correctly rejects `abs(sum(probabilities) - 1.0) > 1e-6` at
   `src/weather/reporting/validation/point_in_time_evaluation.py:2756`.

For a representative genuinely complete 2026-07-14 cutoff
`20260714T000040565098-0400`, both the normalized candidate and incumbent sum
to one. The first four bands retain alpha `1.0`; the seven warmer bands use
alpha `0.35`. The resulting partition sums to `0.9937518164`. Algebraic
recovery over the configured alpha set found a unique band-alpha pattern for
148 failures; one cutoff is numerically ambiguous because candidate and
incumbent values coincide, not because another mechanism is present.

This state can arise from complete-grade production data. Label quality only
controls admission and countability; it is not an input to the contextual
blend ordering. Forecast-relative band pressure and current-max context drive
the per-band alpha. The five genuinely complete failing source days are direct
production-shaped examples.

## Separate simplex repair

The repair beginning at `d448302f` does not tune the lane or change blend
policy. It restores the categorical invariant after the existing policy has
run:

- replay calls `normalize_partition_probabilities(..., gamma=1.0)` after
  contextual blending;
- live serving calls its equivalent partition normalizer at the same stage;
- normalization remains conditional on the artifact's existing
  `partition_normalization_enabled` contract; and
- a three-band regression uses the production `gamma=1.25`, triggers a
  warm-tail-only alpha, proves the pre-restoration mass is non-unit, and
  asserts an exact live/replay unit-mass result.

Independent review found that final partition normalization makes the old
row-wise inverse in `current_blend_validation.py` mathematically invalid.
Follow-up `9abba9db` therefore retains the normalized candidate probability
immediately before incumbent blending, exports it as an optional provenance
column, and makes the validator prefer that exact value. Older exports retain
their legacy reconstruction path. The replay report now discloses both the
normalization gamma and the post-blend mass-restoration stage. Final follow-up
`55fcc7b9` makes this fail closed: a mass-restored base report requires every
scoreable row to carry the exact pre-blend probability plus artifact and
postprocess hashes matching that report. Only explicitly legacy inputs may use
legacy reconstruction, and JSON/Markdown expose the provenance counts.

Focused repair verification:

- `tests/model/test_current_blend.py`: `23 passed`;
- affected live/replay/PIT selection: `113 passed, 2 subtests passed`.
- final replay/live/PIT/validator/schema selection at `55fcc7b9`:
  `142 passed, 8 subtests passed`.

The full repository pytest suite was **NOT-RUN**. Proportional verification
also passed `compileall` on both topic worktrees and the repository-owned
agent-docs audit (`18` agent files and `465` Markdown files on the parity
worktree; `18` and `464` on the repair worktree).

## Genuine-only positive control

The audited population covers 141 genuine F-family candidates across all 11
F-unit registry markets plus separately verified Toronto candidates. It
contains no available 14-day contiguous `complete` and promotion-countable
run; the longest observed run is five days. Toronto has enough genuine days in
total, but they are non-contiguous. The F eligibility audit is
`positive-control-v3\eligibility-audit.json`, file SHA-256
`4374e919e320c1d30dda45e58ed51797954edb87cc3ae635d8c6069101e41129`.

A calendar fiction is therefore unavoidable. It is the sole data deviation:
each source market-day is used once, all parsed timestamps and date identities
move by one uniform per-day delta, and every non-calendar byte must reverse
exactly.

### Preserved superseded attempts

1. `positive-control` stopped before official preselection in 22.406 seconds
   because literal date replacement left adjacent UTC timestamps implausible
   for their destination dates. It performed no training or PIT evaluation.
2. `positive-control-v2` fixed uniform timestamp shifting and verified 50
   source plus 50 destination ledger authorities, but its minimal four-file
   folder staging omitted raw observation evidence. Official preselection
   admitted 6/36 folders and quarantined 30 as
   `feature_quality_quarantine_excluded`; it stopped before training.
3. `positive-control-v3` selected 36 genuine complete/countable,
   raw-evidence-complete F days without reuse from Atlanta, Austin, Dallas, and
   Denver, plus 14 distinct genuine Toronto authority days. It verified 50/50
   source and destination ledger authorities, 72 F raw-evidence files, 290
   reverse-verified transformed files, and zero prohibited mutations. Its
   semantic identities are manifest
   `c65a96dab305330d609f6df91913e7e8edfbe2ddd4c3492f71befe512f0d2213`,
   mapping
   `94c2f4fe77b2ae00ddca33b34c5a11d88c9a62ce1cb72b6125d2fd24194f120c`,
   and Toronto receipt
   `aa017b35a85e912419043afcf6ab71bfb898d90aa2ef44f64201b1f20fa0b700`.
   Official staging passed, but the exact `09756227` nightly exited 1 after
   105.696 seconds in `family_secondary`:
   `empty selection stage: ('probability_calibration', 'family:F', 'nyc')`.
   The first error masked 36 empty entries across the required 66-entry family
   inventory. No pooled training, PIT evaluation, release, or promotion ran.
4. `positive-control-v4` was stopped before any signed input, build, or staging
   receipt after review found an incomplete context-date disclosure. Its 78
   partial files remain untouched.
5. `positive-control-v4b` transformed and authority-checked all 22 added
   context days, then failed closed when the inherited exclusive JSON writer
   correctly refused to replace its intermediate V3 mapping receipt. No
   staging or model stage ran; the root remains untouched.

### Final V4c construction

`positive-control-v4c` is a fresh exact-`09756227` rebuild. It retains the V3
PIT and Toronto populations and adds only excluded-from-PIT, calendar-remapped
training context needed by the production family-secondary contract:

- 36 genuine complete/countable and raw-evidence-complete F PIT source days,
  mapped one-to-one to `2026-06-17..2026-07-22`;
- 14 distinct genuine complete/countable Toronto authority source days,
  mapped to the hard-bound `2026-07-09..2026-07-22` lock;
- 22 genuine complete/countable context source days, two for every one of the
  11 F markets, mapped without collision to `2026-06-17..2026-06-19` and
  excluded from the 36 PIT folder arguments; and
- 72/72 unique source and destination ledger authorities, 378/378
  reverse-verified transformed files, zero source reuse, and zero quality,
  value, settlement, market-identity, timezone-offset, non-calendar, or
  unrelated-byte mutations.

The 22 context days retain 577 ordinary feature-quality snapshot exclusions;
the count is bound in the manifest and was not overridden. All 22 source days
remain eligible, genuinely `complete`, promotion-countable, and authority
verified.

V4c evidence under
`C:\Users\Michael\Documents\Codex\w24b\positive-control-v4c`:

- input-manifest semantic SHA-256:
  `8b028ef230aa01a0e4d6e8e46f90bf05c740236d450ecfa31961096e214e5493`;
- source-to-fictional mapping semantic SHA-256:
  `8b2230c85329eb7e4bcba4191cf7d3853f53ecf7105b53cd4ca43e14fa7a6c7e`;
- Toronto authority-receipt semantic SHA-256:
  `604f7f55f54c6ecef745780ac74ea5147024b3a202cd858873a9e8f375f39a2d`;
- source eligibility-audit file SHA-256:
  `4374e919e320c1d30dda45e58ed51797954edb87cc3ae635d8c6069101e41129`;
  and
- build-verification file SHA-256:
  `160f145f8e593f767e8ac9220ec0396d4b3e34f8bbb84a54fd65bde56c3e37af`.

Official pre-lock staging passed on exactly `2026-07-09..2026-07-22`:

- window-lock ID
  `8e93bea23675483dd24fa62c0cd00974ab6a0fb2ce9873b9cbdf36f25b3ef856`;
- preselection hash
  `1556887995ca0fe30d70c431f50db7731166b1951cd0cf232d8f15261baf4ea2`;
- staging-receipt semantic SHA-256
  `5bd6cdc45024fec9c3d7b4997dc0cd7ddee724ee1d580cf78dc9894cee3d41ab`;
  and
- source corpus/manifest/replay-manifest file SHA-256 values
  `2802cb6736a6a2c2038c370f52d8ff73f64b29382ef8a056bfaa4c6879a29338`,
  `6575113f209b611547f4812e37fc28c35d6db56ffb6f64e6b640e07e141da7c4`,
  and
  `c46cdb9c09715464d36fe4a614b352d1d29a8d6b69e596c2f516144f203202b0`.

Before the full run, an exact-`09756227` family-secondary-only production
preflight passed in 80.157 seconds: 11/11 markets were ML-capable, all 66/66
expected market/family-by-kind source inventory entries were present, unique,
and nonempty, and all 36/36 output artifacts were produced. Row totals in both
market and family:F scopes were 71,555 probability-calibration, 56
forecast-error, and 4,439 settlement-lag rows. Its manifest file SHA-256 is
`e185467b629ac46cdff25cf1f582788bfc07b2d270b1b3e09b9c0b6929bfd57a`;
verification file SHA-256 is
`db510629e4a07acc45742504ea3f5dab797c0c5dd1ac63bfbaf0285144250330`.

The production family manifest does not hash the ambient per-market forecast
and daily-summary support it reads from the protected mirror. A separate
attestor bound all 22/22 files around the preflight; the after comparison
passed with zero changes. This is a reproducibility limitation in the existing
production contract, not another synthetic mutation.

### V4c full-run result and V5 non-run

The exact-`09756227` V4c nightly was invoked with 2,000 bootstrap
iterations, the evaluator's default bootstrap seed `31415`,
`--skip-promotion-refresh`, and `--skip-candidate-release-build`. It exited 1
after 92.537 seconds. Preselection and all 11 family-secondary markets passed,
but pooled feature assembly stopped before model fitting or PIT:

`pooled training corpus does not cover every preselected fleet date:
2026-06-18, 2026-06-24, 2026-06-25, 2026-06-26`

The pooled trainer does not consume the staged snapshot population for this
coverage check. It independently builds its historical cache from canonical
Weather Underground daily and hourly files. Those four fictional destination
dates have no qualifying daily-summary row across any of the 11 F markets.
This is a control-construction topology failure, not evidence for or against
the simplex repair.

The V4c run's file SHA-256 values are:

- runtime: `78663c6a31b2bd6ebf5cd8e20f6faa4291c01a35046dc2db24875a4aa62a1964`;
- status: `9823fbac08a345783c6cc4621eedd5d85b4e3be1503e9f01ba57f23c331d67ac`;
- report: `99e6d6dc1465262b9959b599f8d981aa9a8eea597b8ee3e5de490bb2468e9e89`;
- console: `b2d75f4deffef11df1793398e49f14499a3b4751d70809abe27a1b61f25598c1`;
- invocation: `9ddbef62ffd04b55a261558cc4d60b2a9746a0b9488ec0299c35d6b3c3764d62`;
  and
- mirror ACL gate:
  `71e99d858b44aebefaee927522258815776bc6b7e629320792d70e542fcb470f`.

Promotion remained `not_run`; candidate-release construction was disabled;
no release or pointer output exists.

V5 built a complete 36-day WU overlay as a possible coverage repair, then was
deliberately marked **BUILD-ONLY, NOT-RUN** before a data junction, ACL freeze,
staging, or model execution. Its semantic receipt is
`1d38fab30a6b561009aebc643f89da51b455a403f36298517684ca99fd53234a`;
the marker file SHA-256 is
`e7eb514dad0e2887b749d616e6074ccd44f9ac43dccdfc4e8bfdd7485f205680`.
Review found that remapping WU outcomes without corresponding source-day
forecast rows would pair shifted weather with unrelated destination-day
forecasts. That would introduce a second semantic deviation, so V5 was
preserved but rejected.

### Final V6b frozen control and execution blocker

The first V6 build was stopped and preserved after 455.351 seconds, before
completion, staging, or model execution. Static review found that its
inherited V3 manifest updated the total file count after adding 22 context
mappings but retained replacement aggregates over the original 50 mappings.
The stopped root was not repaired in place. Its sibling superseded marker
SHA-256 is
`faab94f00bc7588de1d1eb66c47c86decff15a5ec93a45a0a3659a3800a56fee`.

Fresh V6b instead keeps the same 36 genuine F source market-days, 14 Toronto source
days, and 22 genuine family-context source market-days, while changing only
four pre-lock fictional destination dates:

| Removed destination | Substituted destination |
| :--- | :--- |
| 2026-06-18 | 2026-06-09 |
| 2026-06-24 | 2026-06-10 |
| 2026-06-25 | 2026-06-11 |
| 2026-06-26 | 2026-06-12 |

All 11 F markets have qualifying canonical WU daily and hourly coverage on
each substituted date (44/44 market-dates). The 36-date fitting fleet is
therefore intentionally non-contiguous, while the unchanged latest 14 dates
remain the contiguous `2026-07-09..2026-07-22` lock. The separately staged
family context uses only June 9, 17, and 19, all within the V6 fleet, and has
zero same-market collision with the 36 PIT folders. No canonical support
forecast rows were synthesized or modified; staged source forecast timestamps
and date identities received only the declared uniform calendar shift.

V6b also recomputes transformation aggregates across all 72 mappings, rejects
any incomplete reverse verification, never overwrites an existing staged
ledger, rechecks every final ledger binding, asserts detached code identity,
and binds the actual imported module and builder paths in its manifest.

The reviewed builder SHA-256 is
`5a96e9d781eba545f171dfab9f63bef990d4bd796e3983bade228ad10fee7025`.
It completed in 635.078 seconds. Independent post-build recomputation found
72/72 unique source and destination market-days, 378/378 reverse-verified
files, exact equality between the raw per-file and declared replacement
aggregates, and 12/12 staged-ledger hashes still bound.

V6b semantic identities are:

- input manifest:
  `842b9cac8a96e34bf352451f3c0f77d9bab00157c001a45172b6ac249d34d3b4`;
- source-to-fictional mapping:
  `d2da7e952ecdc456504c88cea58e9d9c3573a5d948f45ae31083d0dcdd05390b`;
  and
- Toronto authority receipt:
  `ed020b37a6b76d4f23bd69657380d089252ee65f8562c36b86bfb8bb7eaad71b`.

The corresponding build-verification, input-manifest, mapping, Toronto
receipt, import-provenance, substituted-date-support, and ACL-gate file
SHA-256 values are respectively
`536f6588951a7bda9b0d02d0503ad0740d1ea3d81265c139353a9c962767c572`,
`5d65a937bb33d94587860d18590224e4822e7e64950c4a5c466369776441328e`,
`1f161eeaca61aa91760cf34175ddc00316dbec2777549daa1ae9e5247486a2f9`,
`e319fcfae8845dce92586a24e5770611d5078d74d9148fd9603544d9406b9917`,
`c239128d17fc208b23ce30b03d24cd9887e73a7b8af68a081181543429b2ca29`,
`b3e09edb266745ba97db72d3fdc83f1aa7e3dd0b5ed95e10b69e6c4909dcbe84`,
and
`fbc56ed29d5106a8f3af49845d4985877b4ade7632378475c5dbfce0636d2989`.

Official frozen staging then passed on exact
`0975622723129f47e179a4a188017773fbfa95fd`:

- 36/36 folders and 64,867 rows covered the 36-date fitting fleet;
- the hard lock remained the contiguous 14 dates
  `2026-07-09..2026-07-22`;
- window-lock ID:
  `9d3be4615516039bb61697f28c44dfcfdac201d58276d9260632abc63b7722d9`;
- preselection hash:
  `e398abf58b43d2889a0faf4fdd43ad7633bc6d228bc00c5556e4a7c49610422c`;
- staging-receipt semantic SHA-256:
  `f2b05a343005084bab6cd3528a032422d545945d38c5ccc9586011bc8e59a952`;
- source corpus, source manifest, replay manifest, preselection lock, and
  staging-receipt file SHA-256 values:
  `9525bff54f704380892e8e1fb712b670b335480d708a011b54e2aeaa9ec2503a`,
  `14f56e0cb824615383ef9e79858a12fa9990c137951cb168c54d8183d342a7f2`,
  `06a7b87b9ab0f95ee58abaeff53aaa0a24b682e26f20059b46d4c8c4f6dbea9d`,
  `d3d9d71a64929c8741f657d76ca97158dc804b7311d8fc43d8a037110a0e751a`,
  and
  `b34533452e1d63699cbe1fee93a4fdb56a2b84ae92e908fbc9f938095f598f09`;
  and
- staging verification and invocation file SHA-256 values:
  `f5a48a40e5c74318acf76dc6e9fd5927b018f7f8445c33f996f99fc3b393461a`
  and
  `4f9c179c82a69d047a4d14e869ba49b539f49e5cf258500cd08d00c659528e8b`.

Nightly and pooled training remained unstarted during staging. Release,
promotion, and pointer counts were zero before and after staging, and the
canonical-mirror canary was denied.

The exact-`09756227` family-secondary production preflight also passed
(exit 0 in 76.21 seconds):

- 11/11 markets selected `ml`;
- 66/66 explicit market/family-by-kind source-inventory entries were nonempty
  and unique;
- all 36 expected output artifacts were produced and all 74 candidate files
  remained contained below the declared root;
- both market and family:F scopes contained 71,555
  probability-calibration rows, 100 forecast-error rows, and 5,011
  settlement-lag rows; and
- 5,611/5,611 explicitly enumerated trainer-support paths were hashed before
  and after, with zero mismatch. The covered classes were forecast daily,
  forecast long, WU daily, all WU hourly, and all METAR hourly.

The preflight used the same window-lock ID and staging receipt. Its
verification, invocation, family-manifest, runtime, and family-report file
SHA-256 values are respectively
`21c17fe2112d7bdf26614db77d11d063e476b8448ea5b7f5371d67db9f5eef59`,
`e8e2d6b0261a37cf79fa41e37cf92e35af9e7ba3df20ccccb87be5595b50ad8f`,
`70fbca465a6190e9254c2a356441437f80a5a46739e4b1cc952bd3b8faadaf58`,
`f2dd54865c60ce765f225928b0615cbcfccf4146d53fd28a9dd8a6f12a0a908d`,
and
`64933bd09d923bcac1eafe82446203a45f3b8f8008f3116d9388b286261cd525`.
The selection-binding, source-inventory, and output-inventory semantic
SHA-256 values are respectively
`ba106441ad6598680841682d5a4fb2f6c0a14332002ae195ae6b148bc6c7dff1`,
`529c5f0a322fdb62778c3aa3cd15678ec5c4cc8f1df12dc8d4d359c56957d45d`,
and
`0f5a6a09d8de4f5691481e4b3e36b2a321fa61a19a53c998f36a381c0876f248`.
Release, promotion, and pointer counts again remained zero; the signed
manifest was unchanged and the mirror canary was denied.

This support closure is explicit and reproducible but not exhaustive of every
ambient or pooled-training read: marine and reanalysis sidecars were not part
of the enumerated set. The protected mirror's deny-write ACL reduced mutation
risk, but it does not turn those unbound reads into cryptographic evidence.

The full baseline/repaired pair was deliberately **NOT-RUN**. This is a
contract blocker, not a model result:

1. Exact `09756227`
   `src/weather/operations/nightly_retrain.py:1284-1291` omits only the
   `promotion_refresh` step when `--skip-promotion-refresh` is set; it still
   schedules `point_in_time_production_qualification`.
2. The same file at lines 852-869 unconditionally passes
   `args.promotion_out` as `--routing-artifact`.
3. Exact `09756227`
   `src/weather/reporting/validation/point_in_time_evaluation.py:4782-4790`
   requires that path to exist as a file; its CLI also marks the argument
   required at lines 5459-5463.
4. Under the strict no-promotion interpretation used here, the frozen
   production runner sets `--skip-promotion-refresh`, so the required routing
   artifact is never created. Static execution review proves that, if earlier
   stages succeed, qualification then fails before streaming evaluation
   because that artifact is absent; it does not prove unexecuted pooled
   fitting would succeed.

Creating the missing routing artifact would require enabling the
candidate-local `promotion_refresh` computation. The handoff forbids
promotion, but does not name that implementation step; this report therefore
uses the strict reading and leaves any broader authorization to the user.
No broadened authorization was assumed.
Consequently there is no V6b baseline or repaired PIT verdict: both remain
**UNKNOWN / NOT-RUN**, not PASS and not simplex-blocked. The staged inputs,
preflight evidence, and held runner are preserved below the declared root for
an authorized continuation.

## Mission 2 — A6 trust-scoring parity

**PASS on identical inputs.** `score_replay_rows()` and
`score_all_markets()` both reduce their scored rows through the same
`_trust_row()` function. The parity regression builds one settled tape, lets
the ambient scorer derive its scored tuples, maps those exact
`(market_id, target_date, model probability, market probability, outcome)`
tuples into the replay contract, and compares the complete result row. The
rows are exactly equal, including maturity, ECE, Brier, skill, winner-catchup,
grade, score, and rationale.

The behavior change in A6 is input scope, and it is intentional:

- `score_all_markets(root, as_of=...)` discovers every accepted pre-cutoff
  folder visible under the supplied root and emits all registry markets;
- `score_replay_rows(candidate_rows)` reads no folders, ledgers, registry
  entries, or ambient state, and emits only markets/dates represented in the
  already verified candidate rows.

Those outputs can differ when their input universes differ. The frozen result
is the correct promotion result because trust must bind to the same
manifest-admitted evidence that was replayed and evaluated, not later or
unpinned files that happen to be visible on the host.

Regression:
`tests/reporting/test_location_trust.py::TestTrustFormula::test_replay_trust_matches_live_scan_on_identical_scored_rows`.

Verification:

- `tests/reporting/test_location_trust.py`: `11 passed`;
- focused replay/trust selection: `67 passed`.

## Synthetic-lane fidelity

The `m-s` compatibility lane faithfully reproduces:

- the accepted `09756227` bounded candidate generation;
- the serialized trained artifact and its current-blend configuration;
- the real live/replay ordering of normalization and row-specific blending;
- complete band partitions, captured incumbent probabilities, and settlement
  outcomes from the selected source folders; and
- the production PIT evaluator and its strict simplex check.

It does **not** faithfully reproduce:

- source-ledger quality admission on 8 of the 14 locked Atlanta dates;
- a real contiguous complete-grade Toronto lock;
- production authorization (the manifest correctly says
  `conditional_evidence_only=true` and
  `production_evidence_authorized=false`); or
- future lock-time capture, host identity, and fresh F-family staging.

The quality override broadens the admitted population but does not manufacture
the failure mechanism. Because genuinely complete days fail and the same
ordering exists in live serving, the lane remains valid evidence of the code
defect. It is not release authorization.

## Direct answer

- **On `09756227`: NO-GO.** A real complete-grade input can reach
  `probability_simplex_failure`; merging it alone leaves a seventh lock
  blocker.
- **On the isolated repair: focused-test green, but PIT UNKNOWN.** The
  strongest genuine-only control passed frozen staging and family-secondary
  preflight, then was held before the paired full run at the exact-code
  routing-artifact/no-promotion contract conflict recorded above. Every
  available 14-day control also requires calendar fiction because no market
  has 14 contiguous genuine complete-grade days. A repaired-control or real
  Toronto PASS cannot be asserted until the corresponding PIT run actually
  executes and passes.

The lock plan should therefore review the simplex repair before pre-lock
integration and still retain the real lock-time PIT gate.

## NOT-DONE / NOT-REHEARSED

- Real contiguous 14-day complete-grade Toronto PIT: **NOT-REHEARSED**; the
  evidence does not exist yet.
- Frozen V6b baseline/repaired full PIT pair: **NOT-RUN**; exact accepted code
  requires a routing artifact that the candidate-local promotion-refresh step
  would have produced, and the strict no-promotion reading held that step out.
- Production-host execution, scheduler/task lineage, collector health, and
  fresh lock-time F-family staging: **NOT-REHEARSED**.
- Release construction, promotion, active pointer, serving adoption, sizing,
  or trading: **NOT-DONE by design**. No consumed panel was reused.
- Fresh pooled H2 artifact and future-panel preregistration: **NOT-DONE**;
  lock-critical Missions 1 and 2 consumed capacity.

## Evidence inventory

- Prior accepted synthetic fixed-master lane:
  `C:\Users\Michael\Documents\Codex\w24\r\synthetic_compatibility\m-s`.
- New declared mission root:
  `C:\Users\Michael\Documents\Codex\w24b`.
- Superseded positive-control preflight and final genuine-only controls:
  recorded under the new mission root without reuse or overwrite.
- Protected mirror:
  `C:\Users\Michael\Documents\github\weather\data` (read-only ACL remains).
