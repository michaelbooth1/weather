# Agent report - 2026-07-27 workstation authoritative observed maximum

Status: **COMPLETE MEASUREMENT; STRICT HISTORIC READABILITY UNRESOLVED; NO
MODEL OR AUTHORITY CHANGE.**

This report executes
`docs/roadmap/workstation-handoff-2026-07-28-authoritative-observed-max.md`,
file SHA-256
`ac0d89a28d2f85ad8f1641c12658681dbc9b93e7a054f8b5825fc6c3294e9345`,
from exact `origin/master`
`64fb31f278ee2b6a4c4463b10b46570781da7e29` on topic branch
`codex/workstation-observed-max-2026-07-28`.

The information contract was frozen before the IEM request or any new
outcome join in
`scratch/workstation-research-output/observed-max-20260728/predeclaration.md`,
SHA-256
`ae15d8f9400eb806aad70675918fdd53f34fedf12c6c951b96723e81357da6ce`.

## Executive verdict

| Mission | Verdict | Decision |
| :--- | :--- | :--- |
| 1. Were the accepted 37 knowable at hour 20? | **0/37 are proven historically readable; 37/37 remain unresolved.** Raw six-hour support is present by the cutoff in all 37 under both the source-issued and issue-plus-10-minute scenario clocks, but the retrospective IEM rows carry no row-ingestion timestamp. Only 19/37 source-issued and 20/37 proxy support maxima bracket the final WU whole-degree high. | The archive contains useful support, but this measurement does not recover authoritative timestamped settlement evidence. Stop before modelling. |
| 2. Is the same observation useful in the uncertain 09:00-14:00 window? | **A small support-only captured-feature discrepancy exists, but no authority, causal consumption result, or tradeable edge is established.** In the frozen market-top-share `<0.95` cohort, 625/758 partitions have issue-plus-10-minute support. Only 347 also have a materialized `features_long.csv::high_so_far`; 37/347 exceed that value and 10/347 cross at least one additional displayed band. Strict readability is 0/758. The model's raw categorical Brier is `0.741867` versus the market's `0.568883`. | Retain as descriptive captured-feature evidence only. Do not infer what runtime consumed, fit, promote, mask bands, or claim P&L. |
| 3. What would a correct floor require? | **A timestamped, settlement-compatible authority record applied after blending.** ASOS/METAR is support-only under the current contract, so the measured authority gate activates on 0/86 aligned and 0/38 above-floor cases. | The final-face projection is identity and changes no probability. The full preblend-disabled counterfactual is not identifiable from retained rows and is NOT-DONE. |

No collector, model, replay, serving, scheduler, release, promotion, pointer,
sizing, trading, pull request, merge, or `master` change was made.

## Identities, containment, and host admission

| Purpose | Identity |
| :--- | :--- |
| Declared output root | `C:\Users\Michael\Documents\github\weather\scratch\workstation-research-output\observed-max-20260728` |
| Final standalone harness | SHA-256 `eb2da53ded644cbf2efc9903eec4b1a0d5789329522ffb4cad6dd762dd592532` |
| Frozen hour-20 cases | SHA-256 `62098846077d58c89caf500488d9d24e6db207905804fe0584377bdf94de98c8` |
| Frozen candidate rows | SHA-256 `cf661e9fb396e95db4e98f2aa29fd32dda2fb9b992099e4d0d6fcfea89b68a4b` |
| Frozen promotion-corpus manifest | SHA-256 `128db63ec78c92a4126f886caec078dcab6786b47d0d65ad0aff10f5f1dc1dc5` |
| Retained IEM response | 455,331 bytes; SHA-256 `65a4b87651119c705736e493505deb1ce259305e8a5682621aa3b91bbd88ca10` |
| Emitted-output hash receipt | SHA-256 `0efff5481ebae9557fe52e76bf29f20e54d0a000edef7ae6cf67cf64f19c1e9c` |
| Protected inputs, before and after | Both SHA-256 `d2a0aad3fce3730019d8f6d412391d56f8f18a043b7eee186227c4981ec53ea3` |

The `data\` ACL explicitly denied
`DeleteSubdirectoriesAndFiles, Write, Delete` to both the interactive account
and the offline sandbox. Mission 1 admission measured 38.64% commit and
71.75 GiB free on `C:`. The exact eleven WU daily summaries were unchanged
across a targeted hash/metadata stability check. Mission 2 admission at
08:24 ET measured 36.97% commit and 69.27 GiB free, with no local `robocopy`
process. More importantly, every manifest-bound feature file, WU summary,
frozen input, and retained archive identity was captured before and after the
analysis; the two complete protected-input receipts are byte-identical. The
analysis therefore did not read a torn mirror view.

The repository `venv` launcher pointed to a removed Python 3.11 executable.
The standard-library-only harness instead ran with the bundled Codex Python.
Its first synthetic run caught a false extrema-attempt classification:
ordinary slash-form temperature/dewpoint text such as `23/12` could poison a
six-hour token. The parser was corrected before the network request to exclude
slash-form observation tokens while retaining malformed non-slash attempts.
Min- and max-side fixtures passed, and an independent static review approved
the final harness hash above. That review is retained in the task transcript,
not as a separate packet file.

Exactly one network request was made. It covered the eleven registered US
stations from 2026-06-28 through 2026-07-10, with one UTC end-padding day,
requested only `tmpf` and raw `metar`, and retained report types 3 and 4. IEM
returned HTTP 200 with exactly:

```text
station, valid, tmpf, metar
```

The retained archive has 3,876 station rows, 571 decoded six-hour maximum
groups, 571 decoded six-hour minimum groups, and 143 decoded daily extrema
groups. All 3,876 issue tokens resolved; there were zero malformed or
ambiguous six-hour groups and no unexpected stations. The 101 correction rows
were flagged and excluded from eligible support.

## Leakage and source-role contract

Eligibility was frozen without outcome or probability fields in
`primary_observation_eligibility.csv`: 771 rows, SHA-256
`f68d83be43f2836546a7378f879a553a185fc76b3009b4135df2127277fa2074`.
Its receipt explicitly records that it was created before outcome scoring and
contains no outcome or probability fields.

Three clocks remain separate:

1. raw METAR `DDHHMMZ` source issue time;
2. source issue time plus the frozen ten-minute operational proxy;
3. strict proof that the historical archive row was readable by the cutoff.

IEM `valid` was never relabelled as receipt time. A six-hour interval had to
lie wholly within the target market's civil target date. `COR` rows failed
closed. Daily `4` groups were decoded but never admitted: they refer to a
local-standard-time calendar day that was not mapped to the civil/DST market
date. WU daily summaries were joined only after eligibility was fixed and
were used for settlement and occurrence-time evaluation, never row admission.

ASOS/METAR remains supporting evidence. WU history remains the configured
settlement proxy. Same-airport location does not prove that a continuous ASOS
maximum is a hard lower bound for a WU whole-degree settlement.

## Mission 1 - the accepted 37

The denominator is the 37 accepted above-floor cases. Atlanta 2026-06-28 is a
separate parser and interpretation validation case.

| Availability/compatibility level | Accepted cases |
| :--- | ---: |
| Any six-hour maximum in retained archive | 37/37 |
| Source-issued support by exact cutoff | 37/37 |
| Source-issued maximum brackets final WU whole-degree high | 19/37 |
| Issue-plus-10-minute support by exact cutoff | 37/37 |
| Issue-plus-10-minute maximum brackets final WU whole-degree high | 20/37 |
| Strict historical row-readable proof | **0/37** |
| Strict readability unresolved | **37/37** |

Under the proxy conservative-floor display scenario, 25/37 floors remain
consistent with the WU winner, six are above it, and six are below it. This
scenario is descriptive; it neither identifies the true WU maximum nor
authorizes a floor.

The six-hour group identifies an interval, not the true occurrence instant.
The defensible inherent latency bounds are therefore 0-360 minutes from
occurrence to source issue and 10-370 minutes under the operational proxy.
Exact archive-readability latency is not recoverable from this endpoint. WU
occurrence-time point estimates remain evaluation-only: 23 cases yielded
nonnegative estimates from 70 to 490 minutes, while the remaining cases were
unresolved because no bracket-compatible report existed or the parsed WU
occurrence followed an already-available report.

Atlanta reproduces the precision warning. The raw maximum is `34.4 C =
93.92 F`, while the configured WU high is `93 F` and the winner is `92-93`.
Conservative flooring to `93 F` preserves the winner. Half-up display to
`94 F` would exclude it. This is why support-source rounding cannot silently
become settlement authority.

**Mission 1 answer:** the raw report contains the missing observation, but
zero of the 37 cases is proven knowable from the historical archive at the
cutoff. The operational scenarios are useful diagnostics, not authority.

## Mission 2 - earliest local 09:00-14:00 partitions

The frozen selector reproduced 771 earliest target-day partitions, 8,481 band
rows, 129 market-days, eleven US/F markets, and twelve target dates. Toronto
is not present in this F artifact and is not pooled.

The accepted prior floor-authority diagnosis established that a materialized
feature view is not a causal trace of runtime consumption. This audit therefore
uses manifest-bound `features_long.csv::high_so_far` only as a captured-feature
comparison. It does not claim that the candidate actually consumed that value,
or that a difference caused any Brier result. Of 771 partitions, 331 have no
materialized `high_so_far`; 358 have both a proxy-support value and a captured
high and are comparable on this axis.

### Overall US result

| Measure | Result |
| :--- | ---: |
| Issue-plus-10-minute support | 638/771 (82.75%) |
| Source-issued but not plus-ten support | 18/771 |
| Only later six-hour support | 115/771 |
| Strict row-readable proof | **0/771** |
| Missing materialized `features_long.csv::high_so_far` | 331 |
| Comparable proxy-support plus captured-high partitions | 358 |
| Proxy support above captured `high_so_far` | 40/358 |
| Proxy conservative display crosses another captured-feature band | 12/358 |
| Positive support uplift, mean / median / maximum | 1.571 / 1.080 / 5.400 F |
| Raw categorical Brier, model / market / gap | 0.735572 / 0.559357 / +0.176215 |
| Mean normalized mass below support, model / market | 2.164% / 1.076% |

Categorical Brier is the unaveraged sum across the eleven bands. Dividing by
eleven reproduces the accepted per-band scale: model `0.066870` and market
`0.050851`. Raw Gamma probabilities remain raw for Brier. Market-top share
and below-support mass use normalized Gamma mass. Below-support mass is a
physical support scenario, not executable order-book pricing and not hard
impossibility under the current source contract.

### Primary market-uncertain cohort

The preregistered primary subset is market top share `<0.95`:

| Measure | Result |
| :--- | ---: |
| Partitions | 758 |
| Issue-plus-10-minute support | 625 (82.45%) |
| Strict row-readable proof | **0** |
| Missing materialized `high_so_far` | 329 |
| Comparable proxy-support plus captured-high partitions | 347 |
| Support exceeds captured high | 37/347 |
| Support crosses another captured-feature band | 10/347 |
| Raw categorical Brier, model / market / gap | 0.741867 / 0.568883 / +0.172984 |
| Mean normalized mass below support, model / market | 1.479% / 0.626% |

Within the 37 positive-uplift partitions, mean/median uplift is
1.537/1.080 F. Mean model and market mass below the support scenario are
8.614% and 4.028%. Ten cross another displayed band; in that ten-case subset
the corresponding means are 30.30% and 14.50%. Eight of those ten support
floors remain outcome-consistent and two sit above the eventual WU winner.
Those two contradictions are direct evidence against treating the ASOS
display scenario as WU authority.

The accepted market-top-share `>=0.95` cohort has only 13 partitions: all have
proxy support, three positive uplifts, and two displayed-band crossings. This
is the already-priced/loss-avoidance side, not the primary edge cohort.

These Brier values describe the frozen candidate and market on the same
partitions. They are not causally attributed to the captured-feature
discrepancy.

### Hour coverage and scoring

| Local hour | Partitions | Proxy support | Positive captured-feature uplift | Captured-feature band crossings | Model Brier | Market Brier |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 09 | 126 | 78 | 4 | 2 | 0.803498 | 0.613418 |
| 10 | 129 | 81 | 4 | 0 | 0.806858 | 0.610202 |
| 11 | 129 | 106 | 6 | 1 | 0.778956 | 0.596145 |
| 12 | 129 | 118 | 4 | 2 | 0.739971 | 0.570660 |
| 13 | 129 | 127 | 11 | 3 | 0.699072 | 0.511084 |
| 14 | 129 | 128 | 11 | 4 | 0.586660 | 0.455892 |

### Market coverage

| Market | Partitions | Proxy support | Positive captured-feature uplift | Captured-feature band crossings | Model-minus-market Brier |
| :--- | ---: | ---: | ---: | ---: | ---: |
| Atlanta | 65 | 65 | 1 | 1 | +0.155168 |
| Austin | 72 | 72 | 1 | 0 | +0.165219 |
| Chicago | 72 | 72 | 4 | 0 | +0.260931 |
| Dallas | 72 | 72 | 9 | 3 | +0.284890 |
| Denver | 72 | 27 | 4 | 2 | +0.439914 |
| Houston | 72 | 72 | 6 | 2 | -0.125619 |
| Los Angeles | 72 | 43 | 5 | 1 | +0.215831 |
| Miami | 71 | 71 | 3 | 0 | +0.178168 |
| NYC | 65 | 60 | 2 | 2 | +0.134758 |
| San Francisco | 72 | 43 | 3 | 0 | +0.159924 |
| Seattle | 66 | 41 | 2 | 1 | +0.052853 |

The positive-uplift cases begin on 2026-07-03 in this retained panel. Target
date leave-one-out model-minus-market Brier remains positive for every
omission, ranging from `+0.161278` to `+0.188946`; the market conclusion is
not driven by one target date. Full by-hour, by-market, by-target-date, and
leave-one-date-out tables are retained in `observed_max_audit.json`.

### Mission 2 decision

The proxy differs from the manifest-bound captured feature in 37/347
comparable uncertain partitions, and ten cross a displayed band. That is a
captured-feature discrepancy, not proof of unconsumed runtime information and
not a profit finding:

- strict historical authority exists for zero partitions;
- 329/758 uncertain partitions lack materialized `high_so_far`, and the
  captured feature is not a runtime-consumption trace;
- ASOS-to-WU compatibility is not a lower-bound contract;
- two of the ten uncertain crossings would exclude the actual WU winner;
- the market beats the model on the frozen uncertain cohort and every
  leave-one-date-out panel;
- Gamma prices are presentation proxies with no spread, depth, fill, capacity,
  or executable ask evidence.

No fitting or modelling follows from Mission 2.

## Toronto coverage

Toronto is **unavailable in this lane**. The US six-hour group convention,
Fahrenheit bands, and ASOS station mapping are not imputed to Toronto.
Toronto uses native Celsius and ECCC/SWOB support; measuring it requires a
separate preregistered authority/readability contract. No pooled US-plus-
Toronto result is reported.

## Mission 3 - correct floor design

A future authority record must not overload the current numeric support field.
It needs, at minimum:

- authoritative native value, unit, settlement bucket, and explicit state;
- authority source, station, report ID, and payload hash;
- observation aggregation start/end;
- source issue, archive-readable, and capture timestamps;
- explicit missing, stale, malformed, corrected, later-published, and
  settlement-incompatible states.

The gate activates only when the record is both time-valid and contractually
settlement-compatible. A same-airport METAR maximum is not sufficient.

For band-binary output, the correct order is:

1. score the candidate and use support-only values only as ordinary features;
2. apply no hard preblend floor unless the authority gate is active;
3. normalize the candidate simplex;
4. blend candidate and incumbent using the frozen row-specific blend;
5. restore simplex mass;
6. project the complete blended partition onto bands permitted by the
   authoritative native-unit floor;
7. renormalize and assert unit mass plus zero authoritative-impossible mass.

Missing, stale, malformed, corrected-with-unknown-readability,
later-published, support-only, or settlement-incompatible evidence makes the
projection identity and also disables any preblend hard floor.

For the retained historical populations, strict authority activates on 0/86
aligned and 0/38 above-floor cases. The final-face projection therefore
changes zero partitions, removes zero mass, and has zero Brier, log-loss, or
winner-mass effect. Activating an oracle ASOS floor would violate the frozen
source contract.

The full correct-pipeline counterfactual is not identifiable from retained
final or candidate-preblend probabilities because the old unauthenticated
floor already shaped those values before blending. A later no-fit frozen
replay would be required to disable that floor, reproduce every other frozen
step, blend, and then apply the valid postblend projection. That replay is
**NOT-DONE and not authorized here**.

## Evidence packet

The complete ignored local packet is below
`scratch/workstation-research-output/observed-max-20260728`.

| Artifact | SHA-256 |
| :--- | :--- |
| `observed_max_audit.json` | `6ccb8332f2d6c0b3da746bdc75c31359ab129930c92c49528c9b863660cf5215` |
| `observed_max_audit.md` | `943b54d7aad42b3ff009e409c4bc63e2a805701cdc52a8869a52ef4f61a319aa` |
| `primary_window_partitions.csv` | `a55d1446c5310567014029c2d3e49055d274b6c0615d178b9cb1733f8c10e311` |
| `primary_observation_eligibility.csv` | `f68d83be43f2836546a7378f879a553a185fc76b3009b4135df2127277fa2074` |
| `mission1_hour20_resolution.csv` | `c5a038cf5af458abddcafae6eb21757b53db454fd0fd4de2d48d2d59d5d598ae` |
| `parsed_metar_reports.csv` | `ad2fa4b401c23cf838a0c26a649c18a00de4a4a861ba5f6873e1b31eef08a7b7` |
| `provenance/output_hashes.json` | `0efff5481ebae9557fe52e76bf29f20e54d0a000edef7ae6cf67cf64f19c1e9c` |

Every artifact listed by `output_hashes.json` was rehashed successfully.
Protected-input before/after receipts are identical. The full analysis
self-test passed and the output shape matched every frozen expected count.
The repository agent-docs audit passed across 18 agent files and 475 Markdown
files.

## Primary references

- [IEM ASOS download request and field help](https://mesonet.agron.iastate.edu/cgi-bin/request/asos.py?help=)
- [IEM ASOS request backend source](https://github.com/akrherz/iem/blob/main/pylib/iemweb/request/asos.py)
- [IEM ASOS download interface](https://mesonet.agron.iastate.edu/request/download.phtml)
- [NWS ASOS User's Guide](https://www.weather.gov/media/asos/aum-toc.pdf)
- [NWS METAR/TAF decode key](https://www.weather.gov/media/wrh/mesowest/metar_decode_key.pdf)

## NOT-DONE / NOT-REHEARSED

- No production collector field was added.
- No source role was promoted; ASOS remains support-only.
- No floor or blend was implemented, fitted, tuned, replayed, or served.
- No model, P&L, edge, fill, sizing, or execution claim was made.
- No Toronto ECCC/SWOB authority measurement was run.
- No confirmation-panel evidence beginning 2026-07-27 was accessed.
- No release, pointer, registry, scheduler, promotion, trading, PR, merge, or
  `master` action occurred.
