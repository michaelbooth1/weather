# Workstation release-one blocker report — 2026-07-29

This work used topic branch
`codex/workstation-release-one-blockers-2026-07-29` from exact
`origin/master` commit `51d53b69ae44b5c521834d3dc1f37c7d99e29795`.
All rehearsal output stayed under the declared root
`C:\Users\Michael\Documents\github\weather\scratch\r30b`. No production
pointer, promotion, serving process, trading mode, or file below `data/` was
changed.

## 1. Atlanta is a genuine quality block

The exact decision in `qualification/promotion/promotion_refresh.json` is:

- market: `atlanta`;
- action/verdict: `BLOCK_CANDIDATE` / `BLOCK`;
- gate: `blocked_candidate_validation_gate_v0.1`;
- evaluation: `daily_first_market_day`;
- reason: `blocked validation failed: daily-first candidate is not within
  market tolerance`.

The result is not an evidence gap. The gate evaluated 38,170 candidate band
rows over 28 settled days. Its split audit passed with zero leaks across 35
split scopes. Daily-first Brier results were:

| Comparator | Brier / delta |
| :--- | ---: |
| Candidate | `0.05058158564496324` |
| Market | `0.03829101273579536` |
| Current model | `0.05950884291156679` |
| Candidate minus market | `+0.01229057290916788` |
| Candidate minus current | `-0.008927257266603546` |
| Allowed market tolerance | `+0.003` |

The candidate improves the incumbent by about `0.00893` Brier, but it is
about `0.01229` worse than market and misses the allowed market tolerance by
about `0.00929`. The aggregate result agrees: candidate
`0.05326457697974545`, current `0.06370289967052702`, market
`0.03997973599685617`, and candidate minus market
`+0.013284840982889283`. The weather-only model-skill claim therefore
correctly says `daily_first_passed=false` and
`broad_market_skill_claim_allowed=false`.

The smallest honest fixes are to improve and requalify Atlanta or exclude it
from candidate serving. There is no evidence-only repair for this result, and
the gate was not weakened.

There are currently **no passing F-family markets** to place in a narrower
promoted release. The allowlist has `promote_count=0`, Atlanta blocked, and
these ten markets restricted to `KEEP_SHADOW` because each has zero pinned
candidate rows/days:

`austin`, `chicago`, `dallas`, `denver`, `houston`, `los-angeles`, `miami`,
`nyc`, `san-francisco`, and `seattle`.

Consequently, the smallest existing non-Atlanta artifact is a ten-market
**shadow-only** release. It would contain the verified common/base artifact
graph plus those ten shadow routes, but no `PROMOTE_CANDIDATE` route and no
candidate serving permission. Calling those markets “passing” would overstate
the evidence. To make any of them eligible for a scoped production release,
the honest evidence fix is to collect manifest-pinned point-in-time candidate
rows and settled days, then run the unchanged daily-first and aggregate gates.
The release scope decision therefore remains with the operator, with zero
currently qualified promotion markets.

## 2. First-release rollback is explicit and exercised

The rollback contract now represents the pre-release state with the shared
constant `NO_ACTIVE_POINTER`. A null rollback is eligible only for a verified
sequence-1 `PROMOTE` pointer whose immutable manifest has null
`parent_release` and `rollback_target`.

For that one transition, rollback:

1. requires a fresh boundary proof bound to the active source release;
2. writes a durable, self-hashed intent bound to the source pointer SHA and
   sequence before removing the pointer;
3. removes the pointer;
4. calls the canonical serving resolver and requires
   `RESEARCH_UNBOUND` / `research_unbound_non_countable`;
5. records a null restored release, absent pointer, source-release evidence
   scope, and post-deactivation serving proof; and
6. recovers an interrupted finalization only from the exact pending intent
   while the pointer remains absent. Recovery never recreates or toggles the
   pointer.

The ordinary predecessor rollback path remains unchanged. The readiness
validator accepts the no-pointer drill shape only when all null-target,
absent-pointer, serving-status, reason, and source-scope checks pass. As with
every real rollback, coordinated worker restart and post-restart health remain
manual gates; code does not fabricate their completion.

### Isolated rehearsal proof

The rehearsal copied the exact prior 220-file inactive release into the
declared output root and used its verified manifest:

- release: `r1-rehearsal-20260729`;
- manifest SHA-256:
  `4865ab19b9a84e7d54a249ecda3c26097bde7003ddbb1e0d25a4830c8e5fcc6a`;
- verified serving roles: 128;
- scratch activation serving status: `BOUND`;
- rollback result: `ROLLED_BACK`;
- rollback target: `NO_ACTIVE_POINTER`;
- scratch pointer after rollback: absent;
- canonical post-rollback serving status: `RESEARCH_UNBOUND`;
- canonical identity reason: `research_unbound_non_countable`;
- legacy `TorontoHighTempModel` construction after rollback: pass;
- real production pointer before and after rehearsal: absent.

The receipt is
`C:\Users\Michael\Documents\github\weather\scratch\r30b\rehearsal\first_release_rollback_receipt.json`.
The self-hashed drill is
`C:\Users\Michael\Documents\github\weather\scratch\r30b\rehearsal\release_rollback_drill.json`,
with record SHA-256
`02e575a3974dcbc7b42e0eb728a7a7e88ae54df1bee24bc5bab60e4fb3e1c33e`.
Its status is truthfully `PENDING_MANUAL_RESTART`, because this isolated
rehearsal proves activation, deactivation, resolver behavior, and recovery—not
a coordinated production worker restart.

This clears the first-release rollback implementation gate. It does not
authorize a real activation.

## 3. Inactive-release forward shadow

The new command is:

```powershell
python -m weather.reporting.scorecards.inactive_release_forward_shadow `
  --release-dir <immutable-release-dir> `
  --manifest-sha256 <expected-manifest-sha256> `
  --market-id <market> `
  --target-date <yyyy-mm-dd> `
  --captured-inputs <replay_inputs.jsonl> `
  --snapshot-tape <snapshots.jsonl> `
  --window-start <iso-8601-utc> `
  --window-end <iso-8601-utc> `
  --output-root <declared-output-root>
```

It fully verifies an inactive production-capable release without pointer
authority and refuses to shadow a release that is active. It also verifies
captured-input self-hashes and source-tape hashes before and after the run.
For every instant it records:

- captured-input, recorded model/release/runtime, inactive
  release/manifest/candidate, artifact, and postprocessor identities;
- exact recorded and inactive feature-vector hashes, including the first
  differing feature field;
- the first differing base-distribution component;
- inactive incumbent band projection; and
- candidate raw, postprocessed, preblend, current-blend, and final
  probabilities alongside
  `snapshots.jsonl.bands[].model_probability`.

The output separates instrument completion (`status`) from parity
(`comparison_status`) and reports exact and tolerance whole-partition counts.
It is shadow evidence only and cannot activate or promote a release.

### Strict Austin run: blocked at captured-input identity

The declared read-only window was Austin, target 2026-07-29,
`2026-07-29T05:00:00+00:00` through
`2026-07-29T08:33:00+00:00`. The exact release above passed inactive artifact
verification, but strict replay correctly blocked before inference:

```text
captured input 20260729T010032120598-0400 has an invalid self-hash:
claimed=2a0d07d3208ae057e918ab36b01b3c5f0059293a4b0a1d77876c060fd30a2b67,
canonical=210191e1dd9796605172df6f32333e4327af01500ae01a334fc2719b7f904dec,
claimed_matches_noncanonical_insertion_order=true
```

All 24 rows in the window have the same contract defect: their
`captured_input_hash_algorithm` claims canonical sorted JSON, while every
claimed hash instead matches compact insertion-order JSON. The verifier does
not waive this or repair `data/`. This is now the first strict forward-shadow
blocker and an upstream capture/runtime identity defect. A stale producer is a
plausible cause, but the tape alone does not prove that cause.

### Derived-input diagnostic: divergence localized

For diagnosis only, a copy under the declared scratch root changed only those
24 self-hash fields to their canonical values. The original tape was unchanged
across the copy:

- source SHA-256 before and after:
  `1ed8a47c0d3db6d9a911e8eba54de3fb3e8c920e26c36b454a476adf854e80a9`;
- derived tape SHA-256:
  `c7c725535ff4458370302edeb7a9d5d9a6276a0aec73e30daae882e820855159`;
- diagnostic receipt SHA-256:
  `14cab879365870c17751f6045cc570c25a6f11fef878a7610c9c7af7b678450b`.

The derived run completed 24 instants and 264 band rows:

| Output | Exact whole partitions | Within `1e-12` | Maximum absolute delta |
| :--- | ---: | ---: | ---: |
| Inactive incumbent | 0 / 24 | 24 / 24 | `2.220446049250313e-16` |
| Candidate raw | 0 / 24 | 0 / 24 | `0.48614994669829825` |
| Candidate postprocessed | 0 / 24 | 0 / 24 | `0.48614994669829825` |
| Candidate preblend | 0 / 24 | 0 / 24 | `0.42291107749007617` |
| Candidate current blend | 0 / 24 | 0 / 24 | `0.14801887712152678` |
| Candidate final | 0 / 24 | 0 / 24 | `0.14801887712152673` |

The earliest exact divergence is the feature vector on every instant. For 20
instants the first field is `forecast_925_to_850_lapse_proxy`; the first pair
is `7.729411764705873` recorded versus `7.729411764705887` inactive. For the
last four it is `forecast_remaining_aerosol_optical_depth_mean`; the first
pair is `0.1376470588235294` versus `0.13764705882352943`. Those floating-point
differences propagate into strict hash inequality, while the incumbent band
partition still reproduces recorded production within `2.23e-16` on every
instant. The candidate becomes materially different at `candidate_raw` and
remains different through `candidate_final`.

The diagnostic evidence is
`C:\Users\Michael\Documents\github\weather\scratch\r30b\forward-shadow-diagnostic\results\austin\2026-07-29\forward_shadow.json`,
SHA-256
`9b708b195aa8470f069bf23f0c6c84bd2e5397f1772295a8a8ba1c8943d8bd32`.

Therefore `NOT_ACCOUNTED_FOR` is **not strictly closed**: the live captured
inputs fail their declared self-hash contract and no output is bit-exact.
It is substantially narrowed: the inactive incumbent reproduces all 24
recorded production partitions to numerical precision, exact drift begins in
two forecast feature calculations, and material candidate divergence begins
at the raw candidate stage. Fresh canonically hashed capture after the
producer is restarted or corrected is the smallest honest next run.

## Mission 0 and handoff state

Before this work, commit
`e13851ccf44777839785b2a2868245abbd500e80` was pushed to
`origin/codex/workstation-release-one-rehearsal-2026-07-29`. No pull request
was opened.

This blocker branch does not activate, promote, merge, or push `master`.

## Verification

- focused release, rollback, residual-release, collection, model-stage,
  readiness, forward-shadow, and schema suites: 128 passed and 2 subtests
  passed;
- import architecture and release import boundaries: 22 passed;
- `compileall`: passed;
- agent documentation audit: passed (18 agent files and 522 Markdown files);
- isolated rollback rehearsal: passed;
- strict Austin forward shadow: expected fail-closed BLOCK described above;
- derived-input Austin diagnostic: completed with `comparison_status=DIVERGED`.

The broad local suite completed with 3,213 passed, 4 skipped, 820 subtests
passed, and 37 failures. One failure was a compatibility assertion affected by
this branch; it was corrected and its 42-test release suite then passed. A
second was the architecture ratchet rejecting the three new unstaged files;
after exact staging, all 22 architecture tests passed. The remaining 35 are in
untouched baseline/environment-sensitive groups: long Windows temporary paths,
PowerShell execution policy, child-process/sandbox execution, cross-process
fanout, and one memory-threshold test. They do not overlap the focused owners,
but the broad local suite is not represented as green.
