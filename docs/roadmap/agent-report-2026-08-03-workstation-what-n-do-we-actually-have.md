# Workstation report — what N do we actually have? — 2026-08-03

## Verdict

**The defensible fleet answer is 34 independent date clusters, not 39. The
09:00–14:00 objective is therefore not measurable today at the propagated
point effect.** At `N=34`, its one-sided point power is **75.76%**, its MDE is
**19.44% of the market-gap baseline**, and the crossed interval still includes
zero. The cleaner balanced all-12-market sensitivity is `N=30` and 71.13%
point power.

There are 41 dates with at least one promotion-countable replayable market,
which would mechanically reach 82.32% power. That is not an honest fleet
estimand: seven of those dates contain only 1, 1, 1, 3, 3, 7, and 1 markets.
Lowering the admission bar to manufacture `N >= 39` is rejected.

The five-date window was an inherited experimental convention, not a genuine
history limit and not a power-derived choice. It has nevertheless become a
real contamination block for the two held continuation artifacts: both
serialize 2026-07-22 through 2026-07-26 as fit/selection dates. Those five
dates cannot be reclaimed for either held candidate.

This was inventory, contamination audit, and power arithmetic only. No model
was fit or retrained; no held candidate was scored; no reserved date was read;
and nothing under `data/` was written.

## Source and immutable boundary

| Field | Value |
| :--- | :--- |
| Exact base | `a2ce353f9662a54b43fd262df4cd7e56387d045f` |
| Topic branch | `codex/workstation-what-n-do-we-actually-have-2026-09-07a` |
| Declared run root | `C:\Users\Michael\Documents\github\weather\scratch\runs\what-n-do-we-actually-have-2026-09-07a` |
| Primary fleet bar, declared before inspection | at least 8 promotion-countable replayable markets on a date |
| Reserved source of truth | 2026-08-06 through 2026-11-03; no date in that interval appears in the inventory |
| Burned | 2026-07-27 through 2026-07-31 |
| Declared to `-08-16a` | 2026-08-01 through 2026-08-05 |
| Label receipt before and after | 994,940 bytes; `831598f2787d3131e044790124299c17068227a38b7dadfe36d844431f4a6e65`; last write 2026-08-02 13:48:07Z |
| OS protection | explicit inheritable deny of write/delete/ACL-changing rights for the operator and sandbox identities remained in force |

The handoff's production-host receipt was 705 rows across 67 dates through
August 2. The workstation mirror available to this audit was 693 rows across
66 dates through August 1: exactly one 12-market day behind. August 2 belongs
to the already-declared exclusion range, so the required 67-date disposition
adds only its identity and declared reason; none of its cells was read or
fabricated. This lag does not change any admissible set.

## Admission sets and the cost of each bar

The canonical label bar is `promotion_countable`, not the prose value
`quality_grade=complete`. It admits reconciled strict-complete labels and
non-decisive minor-gap labels, while rejecting decisive coverage gaps and low
capture. A cell must also have nonempty captured replay input, snapshot tape,
and endpoint feature hours. Older folders that predate event-day manifests
are admitted only after direct file, target-date, feature-row, and feature-hour
checks; a missing modern manifest is not silently treated as a failed old
tape.

| Bar | Fleet date N | Interpretation and bias cost |
| :--- | ---: | :--- |
| All 12 `quality_grade=complete` and replayable | **9** | Overly strict selection on perfect capture; discards 21 balanced dates that the canonical settlement contract says are countable. |
| All 12 `promotion_countable` and replayable | **30** | Balanced fleet sensitivity; cleanest composition comparison. |
| At least 8 `promotion_countable` and replayable | **34** | Predeclared primary bar; keeps a majority fleet cell, but adds four dates with nonrandom missing cities. |
| At least 1 `promotion_countable` and replayable | **41** | Not accepted for fleet inference; seven sparse dates make calendar N look larger while changing the market composition. |
| At least 8, after the June 13 marine horizon | **29** | Costs five dates; reported as sensitivity, not imposed, because marine is absent from the incumbent lineage. |
| Toronto promotion-countable and replayable | **38** | A legitimate single-market set; not a substitute for the fleet objective. |

The 34-date primary set is:

> 2026-06-07, 06-08, 06-11, 06-12, 06-13, 06-14, 06-16, 06-17,
> 06-19, 06-20, 06-21, 06-22, 06-26, 06-28, 06-29, 06-30,
> 07-01, 07-02, 07-03, 07-04, 07-05, 07-07, 07-08, 07-09,
> 07-10, 07-11, 07-14, 07-15, 07-16, 07-17, 07-18, 07-19,
> 07-20, 07-21.

The all-12 countable set removes June 16, June 17, July 4, and July 11.
Their missing cells are not random: June 16 lacks Houston and Los Angeles;
June 17 lacks Chicago, Los Angeles, and San Francisco; July 4 lacks Atlanta,
NYC, and Seattle; July 11 lacks Seattle. All are non-countable labels, mostly
decisive gaps, with Seattle July 11 rejected for low capture. The crossed
date/market design remains mandatory, but it cannot erase this composition
caveat.

## Endpoint answer and recomputed power

The three fleet endpoints have the same **input-admissible** 34-date set:
the audited cells contain captured replay inputs and both the 09:00–14:00 and
07:00–20:00 feature support. Toronto has 38 dates.

For severe tail, `N=34` is explicitly an input-eligible ceiling. Realized
tail-bearing date support and a held-candidate tail effect cannot be established
without a score. This mission did not score either held candidate, as required.
The severe power row is therefore only the frozen, unrelated direct-served OOF
proxy sensitivity; it is not candidate power.

| Endpoint | Available N | SD receipt | MDE / baseline | Point power | Lower-bound power | Honest status |
| :--- | ---: | ---: | ---: | ---: | ---: | :--- |
| Severe tail | **34 input-eligible ceiling** | 0.080195 | 7.63% | ~100% | 98.80% | Proxy only; realized tail N and frozen-candidate effect unknown. |
| Pooled all-hour | **34** | 0.003151 | 6.72% | unknown | unknown | No endpoint-native effect; the SD is the weak three-date analytical proxy from `-09-06a`, not a crossed bootstrap. |
| Fleet 09:00–14:00 | **34** | 0.009119 | **19.44%** | **75.76%** | unknown | Propagated diagnostic point only; crossed interval includes zero. |
| Toronto 09:00–14:00 | **38** | 0.003066 | 11.77% | unavailable | unavailable | The measured diagnostic point worsens; there is no positive effect to power. |

Fleet 09:00–14:00 sensitivity by admission bar:

| Bar | N | MDE / baseline | Point power |
| :--- | ---: | ---: | ---: |
| All-12 complete | 9 | 38.80% | 32.06% |
| All-12 promotion-countable | 30 | 20.69% | 71.13% |
| Primary at-least-8 | 34 | 19.44% | 75.76% |
| Any-market, rejected for fleet inference | 41 | 17.70% | 82.32% |
| Post-marine at-least-8 | 29 | 21.05% | 69.85% |

Power uses a one-sided noncentral t test over fleet-date equivalents,
`alpha=0.05`, target power 0.80, and degrees of freedom capped at 11. Morning
fleet and Toronto retain the exact `-09-06a` 2,000-replicate seed-90501
receipts. The audit found that `-09-06a` documented seed 90501 globally but
actually called seed **90502** for severe tail. This mission independently
reran the already-frozen unrelated severe diagnostic at the requested seed
90501: SD changed from 0.082122 to 0.080195. Pooled all-hour cannot honestly be
called crossed-bootstrap power because `-09-06a` produced no endpoint-native
score; only its explicitly weak MDE sensitivity is retained.

## Explicit 67-date endpoint map

`Fleet disposition` applies identically to severe-tail input eligibility,
pooled all-hour, and fleet 09:00–14:00. For severe tail, `admissible` means
input-eligible only, subject to the no-score limitation above. Every omitted
fleet date has the literal reason shown. Toronto uses its own single-market
bar.

| Target date | Countable replayable fleet cells | Fleet disposition | Toronto disposition |
| :--- | ---: | :--- | :--- |
| 2026-05-27 | 0 | only 0 promotion-countable replayable markets, below 8 | promotion-countable morning replay missing |
| 2026-05-28 | 0 | only 0 promotion-countable replayable markets, below 8 | promotion-countable morning replay missing |
| 2026-05-30 | 0 | only 0 promotion-countable replayable markets, below 8 | promotion-countable morning replay missing |
| 2026-05-31 | 0 | only 0 promotion-countable replayable markets, below 8 | promotion-countable morning replay missing |
| 2026-06-01 | 0 | only 0 promotion-countable replayable markets, below 8 | promotion-countable morning replay missing |
| 2026-06-02 | 0 | only 0 promotion-countable replayable markets, below 8 | promotion-countable morning replay missing |
| 2026-06-03 | 1 | only 1 promotion-countable replayable market, below 8 | admissible |
| 2026-06-04 | 1 | only 1 promotion-countable replayable market, below 8 | admissible |
| 2026-06-05 | 1 | only 1 promotion-countable replayable market, below 8 | admissible |
| 2026-06-06 | 0 | only 0 promotion-countable replayable markets, below 8 | promotion-countable morning replay missing |
| 2026-06-07 | 12 | admissible | admissible |
| 2026-06-08 | 12 | admissible | admissible |
| 2026-06-09 | 3 | only 3 promotion-countable replayable markets, below 8 | promotion-countable morning replay missing |
| 2026-06-10 | 3 | only 3 promotion-countable replayable markets, below 8 | promotion-countable morning replay missing |
| 2026-06-11 | 12 | admissible | admissible |
| 2026-06-12 | 12 | admissible | admissible |
| 2026-06-13 | 12 | admissible | admissible |
| 2026-06-14 | 12 | admissible | admissible |
| 2026-06-15 | 7 | only 7 promotion-countable replayable markets, below 8 | admissible |
| 2026-06-16 | 10 | admissible | admissible |
| 2026-06-17 | 9 | admissible | admissible |
| 2026-06-18 | 0 | only 0 promotion-countable replayable markets, below 8 | promotion-countable morning replay missing |
| 2026-06-19 | 12 | admissible | admissible |
| 2026-06-20 | 12 | admissible | admissible |
| 2026-06-21 | 12 | admissible | admissible |
| 2026-06-22 | 12 | admissible | admissible |
| 2026-06-23 | 0 | only 0 promotion-countable replayable markets, below 8 | promotion-countable morning replay missing |
| 2026-06-24 | 0 | only 0 promotion-countable replayable markets, below 8 | promotion-countable morning replay missing |
| 2026-06-25 | 0 | only 0 promotion-countable replayable markets, below 8 | promotion-countable morning replay missing |
| 2026-06-26 | 12 | admissible | admissible |
| 2026-06-27 | 1 | only 1 promotion-countable replayable market, below 8 | promotion-countable morning replay missing |
| 2026-06-28 | 12 | admissible | admissible |
| 2026-06-29 | 12 | admissible | admissible |
| 2026-06-30 | 12 | admissible | admissible |
| 2026-07-01 | 12 | admissible | admissible |
| 2026-07-02 | 12 | admissible | admissible |
| 2026-07-03 | 12 | admissible | admissible |
| 2026-07-04 | 9 | admissible | admissible |
| 2026-07-05 | 12 | admissible | admissible |
| 2026-07-06 | 0 | only 0 promotion-countable replayable markets, below 8 | promotion-countable morning replay missing |
| 2026-07-07 | 12 | admissible | admissible |
| 2026-07-08 | 12 | admissible | admissible |
| 2026-07-09 | 12 | admissible | admissible |
| 2026-07-10 | 12 | admissible | admissible |
| 2026-07-11 | 11 | admissible | admissible |
| 2026-07-12 | 0 | only 0 promotion-countable replayable markets, below 8 | promotion-countable morning replay missing |
| 2026-07-13 | 0 | only 0 promotion-countable replayable markets, below 8 | promotion-countable morning replay missing |
| 2026-07-14 | 12 | admissible | admissible |
| 2026-07-15 | 12 | admissible | admissible |
| 2026-07-16 | 12 | admissible | admissible |
| 2026-07-17 | 12 | admissible | admissible |
| 2026-07-18 | 12 | admissible | admissible |
| 2026-07-19 | 12 | admissible | admissible |
| 2026-07-20 | 12 | admissible | admissible |
| 2026-07-21 | 12 | admissible | admissible |
| 2026-07-22 | — | held-candidate fit/selection contamination | held-candidate fit/selection contamination |
| 2026-07-23 | — | held-candidate fit/selection contamination | held-candidate fit/selection contamination |
| 2026-07-24 | — | held-candidate fit/selection contamination | held-candidate fit/selection contamination |
| 2026-07-25 | — | held-candidate fit/selection contamination | held-candidate fit/selection contamination |
| 2026-07-26 | — | held-candidate fit/selection contamination | held-candidate fit/selection contamination |
| 2026-07-27 | — | burned | burned |
| 2026-07-28 | — | burned | burned |
| 2026-07-29 | — | burned | burned |
| 2026-07-30 | — | burned | burned |
| 2026-07-31 | — | burned; also the `rows[-1]` artifact-provenance boundary | burned; also the `rows[-1]` artifact-provenance boundary |
| 2026-08-01 | — | declared to `-08-16a` | declared to `-08-16a` |
| 2026-08-02 | — | declared to `-08-16a`; production-only identity, cells not read locally | declared to `-08-16a`; production-only identity, cells not read locally |

The inventory enumerates the 67 label dates in the production receipt, not
every calendar day; no absent calendar date was inferred or synthesized.

## How five dates became conventional, then contaminated

1. Commit `9c50befd` (July 22) retargeted the research program to the
   09:00–14:00 market gap and required selection and confirmation windows to
   be disjoint. It imposed no five-date limit.
2. Commit `83f386b2` (August 1) chose July 22–30 for the disagreement map
   because Miami July 21 was `partial` and July 22 was the first recent date
   with all 12 markets `quality_grade=complete`. That was a recency/perfect-
   capture convenience, not an inventory of canonical countable history.
3. Commit `7c67f6c2` split those nine dates into fit July 22–26 and a one-time
   chronological test July 27–30. No power derivation for the 5/4 split was
   recorded.
4. The base candidate then serialized July 22–26 as `fit_dates` and July
   27–30 as `score_dates`. The repaired artifact retained the same five fit
   dates and binds to the exact base candidate. From that moment, five dates
   were no longer merely convention: they were contaminated for these held
   artifacts.
5. Later missions inherited `N=5` for diagnostic power without inventorying
   earlier replayable dates. The convention made the planning N artificial;
   it did not make the current clean budget unlimited. The honest reconstruction
   raises the primary fleet N to 34, still below 39.

The post-July-31 `rows[-1]` rule concerns artifact provenance, not target-date
age. These older captured inputs are eligible to pass through a post-boundary
pipeline; they are not excluded merely for being old.

## Artifact contamination map

| Artifact | Provenance and date disposition |
| :--- | :--- |
| Base continuation candidate `d542ec09…8275c85` | 168 model groups; generated 2026-08-02 15:54Z; serialized fit/selection dates July 22–26 and prior score dates July 27–30. |
| Repaired continuation candidate `ba6cd8b7…4970ef` | 168 groups; generated 2026-08-02 18:07Z; same fit dates; exact base identity `d542ec09…8275c85`; post-blend D1 valley-pool smoothing, strength 1.0. |
| Frozen per-market HGBs | Twelve artifact hashes verified. First artifact content dates range June 9–14, 2026. The trainer excludes the target year; forensic reconstructed fit dates end in 2025, with zero overlap against the 2026 label inventory. |
| `forecast_high` fit input | The stitched trainer value was not point-in-time, so the fit itself is contaminated. Evaluation through captured `replay_inputs` is cutoff-time and does not expose settlement; this defect adds no evaluation target-date exclusion. |
| Marine sidecar | One-shot horizon June 13. Prior lineage shows the incumbent HGB selects zero marine features, and the held continuation artifacts are derived transforms rather than marine refits. Primary N does not drop pre-horizon dates; the post-horizon sensitivity costs five dates. |

The legacy HGB pickles retain fitted state and per-tree root-node fit counts,
not raw row-level receipts. Their current-year non-overlap is established by
verified first-content dates plus the trainer's target-year exclusion. The
historical date lists in the evidence packet are fingerprint-matched forensic
reconstructions: for each market/hour, pre-2026 WU target-season rows within
±7 days were ordered exactly as the trainer did and truncated to the exact HGB
root-node fit count. They must not be represented as retained row receipts.

| Market | First content | Reconstructed union N | Historical span | Artifact hash prefix |
| :--- | :--- | ---: | :--- | :--- |
| Toronto | 2026-06-13 | 649 | 1982-06-06 → 2025-06-20 | `bf53fd60db1a` |
| Atlanta | 2026-06-10 | 164 | 2015-06-03 → 2025-06-17 | `9f045926126a` |
| Austin | 2026-06-09 | 165 | 2015-06-02 → 2025-06-16 | `98f5b72b2381` |
| Chicago | 2026-06-09 | 164 | 2015-06-02 → 2025-06-16 | `be24eab615a9` |
| Dallas | 2026-06-10 | 165 | 2015-06-03 → 2025-06-17 | `5ee8722d8610` |
| Denver | 2026-06-10 | 165 | 2015-06-03 → 2025-06-17 | `2047b667fce7` |
| Houston | 2026-06-09 | 165 | 2015-06-02 → 2025-06-16 | `19999a254056` |
| Los Angeles | 2026-06-09 | 164 | 2015-06-02 → 2025-06-16 | `8d9aba849cf9` |
| Miami | 2026-06-14 | 439 | 1995-06-08 → 2025-06-21 | `7b59bc117510` |
| NYC | 2026-06-10 | 164 | 2015-06-03 → 2025-06-17 | `a8efd8067b2f` |
| San Francisco | 2026-06-10 | 165 | 2015-06-03 → 2025-06-17 | `c9b77d8326bf` |
| Seattle | 2026-06-09 | 165 | 2015-06-02 → 2025-06-16 | `ad6229d85148` |

## Evidence and verification

The ignored local packet is rooted only at:

`C:\Users\Michael\Documents\github\weather\scratch\runs\what-n-do-we-actually-have-2026-09-07a`

Principal receipts:

- `date-inventory.csv` — all 67 required target dates and literal endpoint
  dispositions; SHA-256 `bdc1710b689df37b9bc192e8a516af9974623fa4abef324a6ca72099a11a4e34`.
- `market-day-inventory.csv` — 561 pre-exclusion local label-cell/tape checks
  (the other 132 local rows were enumerated by date only and not inspected); SHA-256
  `3683791548dc3df3057142c38c244a7c78d6aa7dac1c856a9532b80532b618f8`.
- `artifact-contamination.json` — held-artifact metadata and 12 HGB forensic
  lineages; SHA-256 `11afe50210bfeefa0d02afa574b4e35926b685e506d8fbc8c1d6d3300ddc97ba`.
- `power-at-available-n.json` — endpoint power and bar sensitivities; SHA-256
  `bbbcb7326ed568d3b1af0841322cea5d06c4d31d56be17f3139ffd61e83a022d`.
- `five-date-window-trace.json` — commit/artifact trace; SHA-256
  `cbac9ccc8b87fb41932ca67f0939e66944e59eb6b85ad819abfafafd1b08230c`.
- `data-safety-receipt.json` — unchanged pre/post label identity plus the
  observed deny-write ACL; SHA-256
  `57b123521ac4ca9c3de612aa78f6d16a083305bc4fed670479b1dd6e8fb3d3cd`.
- `verification.json` — **PASS**, nine independent checks, including a second
  seed-90501 severe bootstrap and unchanged input hashes; SHA-256
  `4b60eeab79342aade37372e7df720774bc11e9206cec08c0eeafb061809719e3`.
- `evidence-manifest.json` — complete path/size/SHA-256 receipt for the local
  packet.

Verification rederived all endpoint sets from the cell inventory; checked the
five fit-contaminated, five burned, and declared dates; proved that no reserved
date entered; verified both candidate identities and all 12 HGB hashes;
rechecked the four partial-fleet missing-market sets; recomputed power math;
and confirmed the label ledger retained its predeclared hash. The final
worktree contains this report only; no runtime, model, release, scheduler,
pointer, capture, or mirror topology changed.
