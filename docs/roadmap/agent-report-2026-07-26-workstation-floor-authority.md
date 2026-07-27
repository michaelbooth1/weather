# Agent report - 2026-07-26 workstation floor authority

Status: **MISSION 1 COMPLETE - THE BAND-BINARY LIVE CAPTURE PATH IS
STRUCTURALLY AFFECTED, BUT ACTIVE SERVING BLEED IS NOT ESTABLISHED; MISSION 2
STOPPED NEGATIVE BEFORE IMPLEMENTATION; MISSION 3 PARTIALLY CHARACTERISED**.

This report executes
`docs/roadmap/workstation-handoff-2026-07-27-floor-authority.md` from exact
`origin/master` commit
`fdacd4dbea0bca53f8623e89ae397b9bc87e9597`.

## Executive verdict

| Question | Verdict | Evidence |
| :--- | :--- | :--- |
| Does the live path reproduce the post-blend floor violation? | **YES for the band-binary live capture adapter; NO for the continuous-density adapter.** | Band-binary capture applies the floor, normalizes, applies `current_blend`, and normalizes again without reapplying the floor. Continuous-density capture does not call that blend. |
| Is this proven to be an active headline, release, or trading bleed? | **NO.** | The recent affected records are `research_unbound_non_countable`, `shadow`, and `active_for_headline=false`; no active release pointer is present in this checkout. |
| Does authoritative WU freshness separate the frozen 86/38 populations? | **NO. STOP.** | The failed WU state shared by all 38 misses also covers 76 of the 86 aligned cases. Exact accepted-print and last-success ages are unavailable in all 124. |
| Was `authoritative_wu_print_freshness_v0.1` implemented or fit? | **NO, by the frozen stop rule.** | Retrospective construction would either be constant/missing or would require future or failed-request timestamps. The untouched confirmation panel is 0/14 complete dates. |
| What did the market know in the 38 misses? | **The market already identified the winner; our captured authoritative WU path did not.** | The realised band is market-top in 38/38 with mean top probability `0.994001`. No higher authoritative WU print is captured. One inspected case contains a time-valid METAR six-hour maximum and guidance that already identify the higher regime; 37 remain unclassified. |

The correct outcome is therefore a negative Mission 2 result, not a tuned
candidate. The evidence supports adding explicit immutable WU authority
provenance to future captures. It does not support inferring it retrospectively
from this settled cohort.

## Identities and containment

| Purpose | Identity |
| :--- | :--- |
| Refreshed `origin/master` and integration base | `fdacd4dbea0bca53f8623e89ae397b9bc87e9597` |
| Topic branch | `codex/workstation-floor-authority-2026-07-27` |
| Accepted evidence dependency | `codex/workstation-profit-edge-2026-07-26` through `42cacfec` |
| Declared output root | `C:\Users\Michael\Documents\github\weather\scratch\workstation-research-output\floor-authority-20260727` |
| Protected data root | `C:\Users\Michael\Documents\github\weather\data` |
| Mission 1 read-only audit harness | SHA-256 `71f8bf6754b963153355847a3f449808667474d37de184cd5890d1582ebd87ba` |
| Mission 1 result JSON | SHA-256 `2a0209df23a960102b6ef8ea5818839065daf2944d671183a8effe68a72c7370` |
| Mission 2 feasibility receipt | SHA-256 `16f3e855e9dc800a01d966587eafdca1f91383c6f7dc6e95f4587fad7b99697b` |
| Mission 3 characterisation receipt | SHA-256 `8f59cb76432e421f3fa5826aa630e8f972be088a776f0fcee4bf565c81e0039a` |
| Frozen hour-20 case CSV | SHA-256 `62098846077d58c89caf500488d9d24e6db207905804fe0584377bdf94de98c8` |
| Frozen hour-20 diagnosis JSON | SHA-256 `62d62a6df7dada26d228c4a470c0e2b508d2197fc8289eedbc149fd4cd4de45a` |

The accepted profit-edge topic owns the preregistration and exact diagnosis
harness consumed here. The published floor-authority topic remains based
directly on `fdacd4db`; the operator retains integration ordering and no
merge-readiness claim is made. During setup, a local, unpushed dependency merge
was created to expose the accepted files. It was removed from the published
topic history before validation and push.

The main `data/` mirror remained under its existing deny-write ACL. All actions
in this queue were reads of captured evidence or writes under the declared
research output root and this topic worktree. No protected tape, ledger,
collector state, release state, or trading state was changed. No Windows
Job/process-tree peak receipt was produced, so resource enforcement is not
claimed.

## Mission 1 - live-path answer

### Executable path

The live implementation has two materially different adapters.

| Adapter | Executable order | Result |
| :--- | :--- | :--- |
| Band-binary | `apply_band_postprocessing` at `live_variant_predictions.py:845` -> partition normalization -> `_apply_current_blend` at line 856 -> final simplex cleanup | **Affected.** The hard floor can be undone by the blend and is not reapplied. |
| Continuous-density | density calibration and density-specific band postprocessing beginning at `live_variant_predictions.py:874`; no `_apply_current_blend` call | **Not affected by this specific post-blend defect.** |
| Frozen band-binary replay | the same floor-before-blend sequence in `pooled_candidate_replay.py:1189-1235` | **Parity with the affected live adapter.** |

The floor primitive itself lives in
`variant_prediction_runtime.py:866-918`. The live defect is therefore not a
replay-only artefact. It is executable in the band-binary capture lane whenever
an artifact enables the incumbent blend.

### Recent occurrence

A read-only scan of recent band-binary dynamic-candidate captures used:

- artifact SHA-256
  `ee7b65d078961bf21c3f89ff6e359d0acca5f3fedc90e456bf0192e4656867e9`;
- variant `pooled_f_dynamic_source_state_v0_1`;
- recorded runtime commits `4041d358241e` and `008a0b82a6f7`;
- captures from 2026-07-25 22:32:29 ET through 2026-07-26 05:18:52 ET.

The final audit read 5,896 prediction rows from 24 event directories and found
269 of 535 complete partitions with more than `1e-9` probability below the
code-effective `high_so_far` floor: 50.28%. Mean impossible mass among
affected partitions is `0.277110`; the maximum is `0.996560`. Every selected
partition retains unit mass within floating tolerance.

For built-in F markets, 259/484 partitions are affected. All 206 selected F
partitions at target-local hours 18-23 are affected, with mean impossible mass
`0.361722`; all 24 F hour-20 partitions are affected, with mean `0.398792`.
Across native units, all 216 selected 18-23 partitions are affected, with mean
`0.345010`. Dallas snapshot
`20260725T223229609744-0400` is a concrete trace: code-effective
`high_so_far=98.06 F` produces a floor of 98 F, yet the final candidate assigns
`0.825196054` below that floor while total mass remains one.

These are occurrences relative to the numeric floor the code actually used,
not proof of an authenticated WU fact. The scanned records contain no
timestamped accepted WU-history row. Recent Dallas and Toronto examples have
null WU history/current values and a support-only or otherwise unauthorised
current maximum. The authoritative-WU denominator in the sampled tape is
therefore zero, so an authoritative-floor occurrence rate is **N/A**, not
zero.

### Operational boundary

At `fdacd4db`, this checkout has no
`artifacts/releases/current_release.json`. The affected recent rows carry empty
`release_id`, `release_identity_status=research_unbound_non_countable`,
`registry_lifecycle=shadow`, and `active_for_headline=false`.

The narrow answer is:

> **The band-binary live capture code reproduces the defect, and recent shadow
> captures exhibit it frequently. The continuous-density adapter differs.
> The available tape does not establish that an active headline release or a
> price-taker emitted or acted on these rows.**

The prior `0.468218` loss over 735 opportunities remains retrospective
repaired-replay sizing. It is not transferred to these release-unbound shadow
captures.

## Mission 2 - freshness-conditional floor

### Frozen feasibility result

The preregistered discriminator does not separate the frozen population:

| Captured source state | Floor aligned | Settlement above floor |
| :--- | ---: | ---: |
| Failed `weather_forecast`, `wu_current`, and `wu_history` | 76 | 38 |
| Other truncated failed groups | 10 | 0 |
| Total | 86 | 38 |

The state that contains every miss also contains 76 aligned cases. Within that
state, only 38 of 114 cases are above-floor misses. Treating failure as "floor
inactive" would discard a nearly perfect preblend result in 76 aligned cases;
treating it as "floor active" repeats the catastrophic mistake in all 38
misses. This is not a usable discriminator.

The exact preregistered numeric signals are also unavailable:

- `latest_wu_history_time` is present in `0/124`;
- the hour-20 artifact contains neither the latest WU time nor minute;
- captured `sources.wu_history` rows are failed requests with
  `status=settlement_source_auth_failure`, `ok=false`, and empty data;
- their `fetched_at` records the failed request, not the most recent successful
  acquisition;
- no separate immutable last-successful-acquisition timestamp is retained.

`pooled_feature_source_state.source_age_minutes()` currently derives age from
the envelope `fetched_at`. For a failed request this can appear nearly fresh.
Reinterpreting it as an accepted-print or successful-acquisition age would be
both semantically wrong and a leakage/provenance failure.

### Stop decision and candidate metrics

The handoff says to stop if freshness does not separate the 86 from the 38.
That condition is met before implementation or fitting. Building a
retrospective candidate from later caches, settlement summaries, later tape
rows, or outcomes would violate the frozen preregistration.

| Required result | Status |
| :--- | :--- |
| Candidate implementation | **NOT-DONE - stopped negative** |
| Frozen 86 aligned score | **NOT-SCORED** |
| Frozen 38 above-floor score | **NOT-SCORED** |
| Pooled score | **NOT-SCORED** |
| Fresh-authoritative partitions with impossible mass | **N/A - zero reconstructible fresh-authoritative partitions** |
| Untouched confirmation panel | **0/14 complete dates; begins 2026-07-27** |
| Fitting, tuning, threshold search, or outcome opening | **NONE** |

The untouched window cannot be evaluated on 2026-07-26. No
`*july-27-2026` snapshot directory exists yet, and no eligible date can already
be complete and settled. Freezing a date/hash panel or reporting a score now
would fabricate evidence.

### Safe future-only candidate contract

The negative historical result still identifies the minimum future capture
contract:

1. retain the accepted WU observation timestamp used by `high_so_far`;
2. retain an explicit last-successful WU-history acquisition timestamp,
   separate from the current request timestamp;
3. retain a fail-closed authority enum and missing flags;
4. when fresh and authoritative, enforce the native-unit floor after blending
   and renormalize;
5. when stale, failed, or missing, apply no floor before or after blending;
6. keep the gate dormant and candidate-only until a sealed future panel exists.

This should be a deterministic postprocessor gate before it is considered as a
fitted model feature. Required future tests include malformed/future timestamp
failure, failed-request timestamps never counting as success, capture
round-trip, live/replay parity, native F/C boundaries, zero fresh-floor
impossible mass with unit mass, inactive failed/missing floors, and unchanged
legacy-artifact probabilities.

No code was added for that contract in this queue because the requested
historical discriminator failed and the confirmation data does not yet exist.

## Mission 3 - what the market knew

### Population result

The 38 above-floor cases settle 1-11 F above the numeric printed floor:
median 5 F, mean `5.4211 F`. At the captured hour-20 instant:

- the eventual winner is already the market-top band in `38/38`;
- mean market-top probability is `0.994001`;
- market categorical Brier is `0.000009559`;
- candidate-preblend mean winning-band probability is
  `0.0000002058`, with categorical Brier `1.999904571`;
- all 38 report failed weather forecast, WU current, and WU history;
- none has a trusted current maximum or a captured eligible maximum above the
  stale numeric floor;
- captured higher authoritative WU evidence is `0/38`.

The market plainly had point-in-time information that our candidate path did
not consume. Market price alone cannot identify the information source, so it
does not prove that a WU print existed elsewhere.

### A recoverable concrete case

Atlanta for 2026-06-28, captured at
`2026-06-29T00:03:49Z` (`20:03:49` local), has:

- model floor/current temperature `89.06 F`;
- eventual WU settlement `93 F`, winner `92-93 F`;
- retained METAR
  `METAR KATL 282352Z ... 32/19 ... T03170194 10344 ...`;
- NWS grid high `94 F`;
- global-ensemble high interval `90.5-95.33 F`.

The METAR `10344` remark is a six-hour maximum of `34.4 C`, or `93.92 F`,
observed before the scored capture. This is conclusive supporting evidence
that the higher regime was already observable in at least this case. The
feature path consumed the instantaneous `32 C / 89.06 F` value but not that
maximum remark.

This does not make METAR the settlement authority; WU history remains the
configured settlement proxy. It does prove that this miss was not genuinely
unknowable at 20:00 and that some of the gap is recoverable through better
point-in-time supporting-observation parsing.

### Defensible classification

| Classification | Count |
| :--- | ---: |
| Market already near-certain on realised band | 38/38 |
| Higher authoritative WU print captured by this pipeline | 0/38 |
| Higher time-valid supporting observation conclusively demonstrated | at least 1/38 |
| Genuinely unknowable established | 0/38 |
| Requires the same raw, timestamp-valid source audit | 37/38 |

The frozen case CSV does not materialize raw METAR maximum remarks or every
prior observation. Assigning the remaining 37 to "observed",
"trajectory-only", or "unknowable" without that audit would invent a result.
This queue therefore bounds the answer but does not pretend to close it.

## Validation

| Check | Result |
| :--- | :--- |
| Mission 1 code-path inspection | **PASS - affected band-binary and unaffected density adapters identified** |
| Recent shadow-tape mass audit | **PASS - unit mass retained; post-floor impossible mass reproduced** |
| Mission 2 exact-field/source-state inventory | **PASS - negative stop condition established** |
| Mission 3 exact snapshot inspection | **PASS - one recoverable point-in-time miss demonstrated** |
| Agent documentation audit | **PASS - 18 agent files, 474 Markdown files** |
| `git diff --check` | **PASS** |
| Protected-data writes | **NONE** |

The queue deliberately did not start the heavy modelling or full replay suite:
the Mission 2 stop condition fired, the confirmation window is unavailable,
and the workstation was outside the documented heavy ad hoc compute window.

## First-class NOT-DONE and NOT-REHEARSED

### NOT-DONE

- No implementation, fitting, tuning, threshold search, ablation, or
  retrospective relabelling of `authoritative_wu_print_freshness_v0.1`.
- No candidate score, 86/38 score delta, pooled score delta, or future-panel
  score; the correct values are NOT-SCORED.
- No mechanical post-blend floor fix.
- No full raw-source classification of the remaining 37 above-floor cases.
- No claim that any higher WU print existed outside the captured pipeline.
- No promotion, release, pointer, activation, serving, scheduler, collector,
  sizing, trading-surface, pull-request, master-push, or remote merge action.
- No claim of active headline bleed, executable loss, profit, deployment
  readiness, merge readiness, or resource enforcement.

### NOT-REHEARSED

- The future capture schema, deterministic authority gate, live/replay parity,
  native-unit boundary cases, and sealed confirmation evaluation were not
  rehearsed.
- The untouched 14-date panel was not opened, scored, or sequentially peeked.
- Promotion, release, serving, scheduler, collector, sizing, and trading paths
  were not rehearsed.
- CLOB depth, spread, slippage, queue position, fills, maker eligibility,
  capacity, and live execution were not rehearsed.

All retained evidence is read-only diagnostic/research evidence. It authorizes
no model change, cutover, or live action.
