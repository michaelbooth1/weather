# Workstation handback: missing-information completion, mission 2026-09-79a

**DESCRIPTIVE CHECKS EXECUTED. Unused station guidance is the strongest lead;
no parity, causal attribution, or promotion is established.**
The staged export arrived at the requested 03:00 wake-up. This report supersedes
the [preparation checkpoint](agent-report-2026-09-79a-workstation-what-does-the-market-know.md)
without altering that published record. Issued 2026-09-21, America/Toronto.

The [one-page interpretation](../research/missing-information-results-2026-09-79a-completion.md)
classifies all six candidates. The [aggregate evidence](../research/missing-information-summary-2026-09-79a.json)
contains every primary table, hour/peak table, instrument histogram, guidance
coverage/comparison, regime odds ratio, clock curve/histogram and sensitivity,
including date clusters, market clusters, market-days, 95% intervals, power and MDE.
It excludes raw archives, captured rows, trade identities and model input rows.

## Provenance, population and estimand

Branch: `codex/missing-information-checks-20260921`, stacked on
`278c2388b439f71f81233ae96ab3ff0d2d500794` (the handoff branch).
Final analysis implementation: **`855b9cabaec766abad047c34c3210c807e1d6021`**.
Existing draft PR: https://github.com/michaelbooth1/weather/pull/73.
The following evidence-only commit contains this report and the aggregate JSON.

SSH to `production-pc` works. Only the four authorized staged files were
copied, serially, from `C:/tmp/mi-handoff/`; production was not modified.
The manifest records staging at **2026-09-21 02:36:04 −04:00**.
All archive SHA-256 digests matched before extraction:

| Archive | Compressed bytes | SHA-256 |
| --- | ---: | --- |
| mi-core.tgz | 53,427,046 | f96a7114594915d1b761ee39fab37e3b8b13b9775d29a3f897df4d66b2c0df9f |
| mi-tape.tgz | 58,369,984 | 9d225ec40d1160ce261da0a859503fd0af41e777c428f864d532eb030fc2f772 |
| mi-books-sample.tgz | 341,690,746 | c7dc4f4277d505f5755d581e583a93ea78de9fca72cc1978947c91ab1835ef32 |

The frozen plan hash remains
`024dbac70c636e42c4f514d66d79fb955c75362c6534892954c05d0bc9e33a81`.
It was committed before data access; each scoring stage writes the plan and
settings hashes before loading inputs. Final stages also record source-file hashes.
Reservation status read **NONE RESERVED**.

Extraction: 600 folders, **503 admitted market-days / 89,354 snapshots**.
Exactly boolean `promotion_countable` was required. Exclusions: all 12 markets on
**08-16, 08-17, 08-28, 08-29, 08-30, 08-31, 09-01, 09-02**, plus **Austin 08-07**
(all not promotion-countable): 97 days. Seven off-target-date snapshots were
excluded. This is the supplied export's population, not a claim about current
settlement state. Snapshot JSONL SHA-256:
`249a9de0da7b41cb8a2ce1f07944e4007c585f601028b73acaae0dd4bd141c2e`.

Before/from 2026-08-23 remain separate: **239/264 market-days,
20/22 date clusters, 12/12 market clusters**. No pre-boundary B/C data or frozen
workstation mirror was used. Native units were traced; legacy `_c` fields
were not double-converted. Brier is the mean binary score across the complete
band support. Snapshots collapse to market-day-hour cells, then equally weighted
market-days. Raw market probabilities are primary; normalization is a sensitivity.
Intervals use 2,000 independent date × market multinomial bootstrap draws.
Power uses prespecified shifted effects, not the observed effect. Zero-variation
samples have no claimed inferential power/MDE; their empirical zero-width interval
does not rule out unseen rare events.

## Check 1: the gap starts in the morning

Numbers below are before / from August 23. Brackets are crossed 95% intervals.

| Endpoint | Before | From | Support D/M/N | MDE80; power at prespecified effect |
| --- | --- | --- | --- | --- |
| All-hour model / market Brier | 0.059720 / 0.034008 | 0.058933 / 0.035250 | 20/12/239; 22/12/264 | Excess MDE 0.01098/0.01040; power at 0.01: 71.7%/76.8% |
| 06:00–09:59 model/market ratio | 1.482 [1.287,1.749] | 1.440 [1.247,1.654] | 20/12/235; 22/12/264 | 0.325/0.285; power at 0.30: 72.4%/84.8% |
| 13:00–16:59 ratio | 1.789 [1.477,2.278] | 1.715 [1.407,2.161] | 20/12/239; 22/12/264 | 0.548/0.522; power at 0.30: 30.9%/32.3% |
| Signed excess share at/after noon | 54.70% [47.28,63.23] | 50.09% [41.75,59.60] | 20/12/239; 22/12/264 | 11.36/12.17 percentage points; power at 10 points: 69.7%/62.0% |
| Paired PM minus AM ratio | +0.332 [0.059,0.736] | +0.275 [−0.016,0.671] | 20/12/235; 22/12/264 | 0.456/0.473; power at 0.30: 41.0%/40.9% |

The frozen **pre-day point rule fires in both strata**. The ≥60%-after-noon
intraday rule does not. The lower bounds of morning ratios do not prove a
minimum 30% deficit; this is the literal point-estimate rule, not a threshold test.
The ratio rises rather than staying flat, so the book study was not skipped.

Inclusive-hour sensitivity (hours 6–10 and 13–17) gives AM ratios 1.469/1.439,
PM 2.011/1.875. Normalized-market primary-window ratios are AM 1.482/1.441,
PM 1.794/1.716. The qualitative localization survives; including hour 17 changes
the PM effect size materially. Full intervals/power are in the aggregate JSON.

At 13:00, resolved-only median information lag is **1 hour [1,2]** in each stratum,
on 197/243 resolved days (20/22 dates, 12 markets). MDE is just over 1 hour;
power at a one-hour shift is 34.1%/45.2%. Censoring is **17.57% [6.75,31.25]**
and **7.95% [2.65,15.91]**, MDE 17.21/9.47 points, power at ten points 34.8%/86.6%.
Do not state that every market-day resolves in one hour. Peak-relative tables
and monotone-envelope alternatives are retained. Maxima decrease on 161 days;
a final captured maximum is a proxy, not proof of the true full-day peak.

## Check 2: precision is not the leading branch

Final instrument mismatch is **2/239 = 0.837% [0,3.347]** and
**2/264 = 0.758% [0,3.409]**. MDE is 2.52/3.03 percentage points;
power at ten points is 100% in this empirical calculation. These upper bounds
are below the frozen 10% criterion. The after-07:00 monotone-envelope sensitivity
has the same mismatch counts. Per-market whole-degree histograms, including
the last pre-18:00 snapshot, are in the evidence.

In the 64%-loss-tail snapshot set, adjacent modes occur on **65.34% [55.76,73.96]**
and **69.21% [60.43,77.54]** of the equally weighted cells. Support is
20/12/191 and 22/12/212; MDE 12.66/12.13 points; power at ten points 61.4%/65.6%.
Two-or-more-band separation is 29.46% [21.17,39.23] / 21.49% [12.74,31.52],
MDE 12.92/13.29 points, power 56.5%/53.9%. Neither frozen separation rule fires.
The instrument evidence, rather than a barely missed adjacent-mode point threshold,
is why the rounding branch is not supported.

Model mass strictly below its own captured running maximum is **zero throughout
the admitted sample**, also after 07:00. This is an observed structural property;
its degenerate empirical interval supplies no rare-event power guarantee.
It does not prove that the station feed includes all settlement information.

## Check 4: useful guidance, but parity not established

US percentile/CDF-field fill is **24.6%–38.3% by market/stratum**; Toronto has none.
Fill by date and hour is retained. Morning NBM+floor comparisons cover only
**149 days / 19 dates / 9 markets** before, **166 / 22 / 9** after.

| Morning diagnostic | Before: ratio to market [95% CI] | From: ratio [95% CI] | Before / from D,M,N |
| --- | --- | --- | --- |
| NBM raw | 1.198 [1.094,1.318] | 1.177 [1.057,1.309] | 20,11,218 / 22,11,239 |
| NBM + observed floor | 1.217 [1.075,1.389] | 1.148 [1.005,1.322] | 19,9,149 / 22,9,166 |
| NWS earlier-date kernel | 1.429 [1.215,1.748] | 1.372 [1.214,1.565] | 15,11,164 / 17,11,187 |
| Open-Meteo earlier-date kernel | 1.516 [1.307,1.818] | 1.456 [1.276,1.672] | 15,12,179 / 17,12,204 |
| HRRR earlier-date kernel | 1.308 [1.153,1.491] | 1.251 [1.101,1.424] | 15,11,164 / 17,11,187 |

Ratio MDEs before/from: raw NBM 0.159/0.177, floored NBM 0.218/0.217,
NWS 0.373/0.250, Open-Meteo 0.358/0.272, HRRR 0.236/0.224.
Power for a 0.10 ratio effect is respectively 41.1/32.8%, 22.9/24.5%,
11.8/20.5%, 13.2/18.0%, 21.1/23.6%. Full paired model deltas, other buckets
and normalized sensitivities are in the evidence; supports are never borrowed
across variants.

NBM+floor minus served-model Brier is **−0.01470 [−0.02603,−0.00334]** /
**−0.01476 [−0.02751,−0.00195]**, MDE 0.01609/0.01813,
power at 0.01 39.7%/35.0%. This is a descriptive improvement on matched snapshots,
not a served candidate result. Neither point estimate meets the frozen 1.10 parity
rule. Restricting to 07:00–09:59 gives ratios 1.221/1.155, and including hour 10
gives 1.216/1.148. Raw and floored rows have different coverage; their aggregate
scores are not a head-to-head floor effect. On identical after-07:00 snapshots,
floor-minus-raw differences are −0.00000520 [−0.00002756,+0.000000054] /
+0.000000093 [−0.000000283,+0.000000952], not distinguishable from zero.
No past-date kernel includes its scored date; at least five earlier dates per
market/stratum/bucket are required.

**4b:** a captured Atlanta 2026-08-01 cutoff-7 row was passed through
`FeatureModelMixin._evaluate_feature_model_for_cutoff`, with the real imputer
and predictor from the hash-verified local artifact:
`9f045926126ab37bbc71b2c7db97b79cda8061c36c0fae93f2e12495493c9b9f`.
Every cutoff 7–20 has 27 selected columns, no direct NBM/NWS-grid/HRRR columns,
and no retained permutation-importance key. Removing NBM from the captured row
changes neither selected/imputed input nor its HGB input. Unselected fields
are dropped before imputation; missing NBM cannot be median-imputed into a
column that is absent. Aggregate features such as forecast high can still carry
guidance indirectly. The export has an opaque model identity and unbound release
status, not individual artifact fingerprints: **historical active binding is
unproved**. No replay equivalence or new permutation-importance fit is claimed.

**4c was triggered** by thin NBM coverage and the matched improvement.
Free serial downloads (≥1.1 seconds apart, URL/hash manifests retained):
44 text ZIPs / 3,730 products / 9,282,617 compressed bytes, NBS/NBP/LAV/MAV for
11 US stations. The returned text coverage starts September 12, not May 10.
The documented structured MOS endpoint supplied 33 CSVs / 19,416 distinct
station-model runs / 61,837,888 bytes, covering May 10 through September 21 for
NBS, LAV and GFS (the MAV product). Run and forecast stamps stay separate.
NBP is rejected by the structured endpoint (HTTP 422 allowed-model validation);
its older probabilistic history remains missing. No downloaded guidance was
stitched, substituted into the captured panel, trained or scored.
Sources: [text endpoint](https://mesonet.agron.iastate.edu/cgi-bin/afos/retrieve.py?help),
[structured endpoint](https://mesonet.agron.iastate.edu/cgi-bin/request/mos.py?help),
[model naming/archive description](https://mesonet.agron.iastate.edu/mos/).

## Check 5: regime labels are unpowered

The tail contains 62/239 and 71/264 market-days. Every observed tag is unpowered
at OR=2 (maximum power 26.6%); MRMS has no usable tag measurements.
Examples: guidance-bust OR **0.318 [0.032,1.243]** (20/11/211, MDE OR 11.57,
power 8.2%) and **0.846 [0.160,3.022]** (22/11/242, MDE OR 8.03, power 12.1%).
Only 11.7%/19.7% of tail days with an eligible NWS as-of-08:00 value are tagged
guidance busts. This does not prove that public guidance knew the outcome, or
that no one could know a bust pre-day. Other tags, support and missingness
appear in the aggregate evidence. No regime feature is selected.

The original ensemble-spread alias missed the captured
`forecast_global_ensemble_spread` field; the final analysis corrects that
schema mapping without changing the threshold or frozen reading rule.

## Check 3: timing exists, feed identity remains unresolved

All 84 countable sampled book-days were read: 48 before (4 dates, 12 markets)
and 36 after (3 dates, 12 markets). The fixed August 30 sample was excluded by
the countable gate. Trade histograms cover 72 days/6 dates and 264 days/22 dates,
12 markets each, using the canonical tape reader. Top-two bands are fixed
as-of 10:00; quote staleness is capped at 120 seconds.

SPECI signed 15-minute **post** moves: **−0.00163 [−0.03510,+0.02851]**
(34 events, 4 dates/9 markets/14 days), **+0.01200 [−0.02284,+0.07538]**
(33 events, 3/8/11). MDE 0.04257/0.07099; power at a one-cent effect 8.7%/8.9%.
Pre-SPECI moves and post-minus-pre changes also include zero.
Routine-METAR temperature-aligned pre-10-minute changes are
+0.00094 [−0.00651,+0.00911] / +0.00944 [−0.00188,+0.02528],
support 4/12/47 and 3/12/36; MDE 0.01089/0.01951, one-cent power 71.1%/27.5%.

Positive winner-directed move share in complete [observation, observation+3min]
intervals exceeds eligible time exposure by **9.08 [5.21,13.36]** /
**5.77 [1.54,11.62] percentage points**, on 4/12/48 and 3/12/36.
MDE 5.84/6.90 points; power at one point 7.4%/8.0%.
This descriptive clock association does not identify a feed or an information
advantage. Minute-of-hour tables and all −15..+15 event curves are retained;
per-bin intervals are not a multiple-comparison discovery claim.

Exact captured ≥3-cent jumps precede the next snapshot by mean
**4.44 [3.92,5.32]** / **4.20 [3.81,4.57] minutes**,
support 4/12/48 and 3/12/35; MDE 1.086/0.532 minutes,
power at one minute 71.0%/99.8%. These jumps use actual capture times, not
rounded minute endpoints. No such sampled jump is right-censored.

**All 89,271 relevant observation payload rows lack a complete provider-observed /
first-seen pair.** Provider-to-ingestion delay is not measurable from this export.
IEM `valid` is observation time, not a publication receipt. The frozen “private
feed/permanent gap” interpretation is neither statistically triggered here nor
causally identified by this design.

## Validation and outstanding limits

Final focused run: **105 passed, 11 expected skips** (platform/outer-lease safety
conditions). Tests cover probability mass/rounding, chronology, crossed resampling,
missingness/censoring, artifact-output serialization, and a hand-computable
end-to-end book jump delay. The expected skips do not weaken admission gates.
All heavy commands used the approved workstation wrapper. No full repository
suite was run; canonical docs and production code were not changed.
`git diff --check` passed. Temporary pytest trees were removed.

Authoritative local outputs are `analysis-2`, `supplement-3`, `clock-3`,
`extracted-1`, and the three IEM directories below. Earlier attempts remain
preserved and are not cited as final results. Headers bind source bytes;
the aggregate JSON records hashes of final local evidence.

The unresolved items are evidence limits, not affirmative nulls:
historical active-artifact binding, stored permutation importances,
provider ingestion times, pre-September-12 NBP history, and regime/SPECI power.
No candidate, forecast-model fit, alpha allocation, live order, credential read,
production write, Scheduler change, registration, restart, master merge or
runtime adoption was performed. Only the prescribed earlier-date diagnostic
error kernels were estimated.

The proposed next step is the morning, floor-preserving NBM candidate design
in the one-page summary, including full served-pipeline propagation, point-in-time
input binding, fresh held-out dates and candidate-specific power before any
alpha decision. The canonical digest/EF/state files are outside this mission's
owned paths; the receiving agent can record accepted findings there.

## Roll verdict and per-file handback

The repository tool returned **UNDECIDABLE: no live closure evidence**:
snapshot, CLOB, observation-trigger and enrichment status files are all absent
on this worktree. It was not replaced with stale mirror data or a hand-derived
closure. Production access remains copy-only, so the receiving operations agent
must run the verdict against current closures before integration. A branch push
does not adopt or restart capture.

Every changed path below has **UNDECIDABLE / no verified closure membership**.
This is not a claim that documentation or PowerShell normally rolls Python:
it reports the actual failed-closed tool result, rather than inventing a per-file
live-closure proof.

| Path | Verdict |
| --- | --- |
| `.codex/hooks/pre_tool_use_host_load.py` | UNDECIDABLE |
| `scripts/ops/workload_admission.ps1` | UNDECIDABLE |
| `tests/operations/test_codex_host_load_hook.py` | UNDECIDABLE |
| `tests/operations/test_missing_information_admission.py` | UNDECIDABLE |
| `tests/operations/test_workload_admission_script.py` | UNDECIDABLE |
| `tests/reporting/test_missing_information_methods.py` | UNDECIDABLE |
| `tests/reporting/test_missing_information_pipeline.py` | UNDECIDABLE |
| `tests/reporting/test_missing_information_supplement.py` | UNDECIDABLE |
| `tools/research/missing_information/README.md` | UNDECIDABLE |
| `tools/research/missing_information/__init__.py` | UNDECIDABLE |
| `tools/research/missing_information/analysis_settings.json` | UNDECIDABLE |
| `tools/research/missing_information/checks.py` | UNDECIDABLE |
| `tools/research/missing_information/clocks.py` | UNDECIDABLE |
| `tools/research/missing_information/extract.py` | UNDECIDABLE |
| `tools/research/missing_information/fetch_iem.py` | UNDECIDABLE |
| `tools/research/missing_information/guidance_archive.py` | UNDECIDABLE |
| `tools/research/missing_information/methods.py` | UNDECIDABLE |
| `tools/research/missing_information/regimes.py` | UNDECIDABLE |
| `tools/research/missing_information/run.py` | UNDECIDABLE |
| `tools/research/missing_information/supplement.py` | UNDECIDABLE |
| `docs/research/missing-information-results-2026-09-79a.md` | UNDECIDABLE |
| `docs/research/missing-information-results-2026-09-79a-completion.md` | UNDECIDABLE |
| `docs/research/missing-information-summary-2026-09-79a.json` | UNDECIDABLE |
| `docs/roadmap/agent-report-2026-09-79a-workstation-what-does-the-market-know.md` | UNDECIDABLE |
| `docs/roadmap/agent-report-2026-09-79a-workstation-what-does-the-market-know-completion.md` | UNDECIDABLE |

## Exact workstation reproduction

Inputs remain under `C:/Users/Michael/Documents/github/weather/scratch/missing-information-20260921`.
Use the committed worktree and project interpreter below. Outputs use new
`reproduce-*` directories; choose another fresh suffix if those already exist.
The checks refuse changed snapshot/IEM hashes and changed frozen-plan bytes.
The base64 arguments are UTF-8 JSON arrays for the documented guarded driver.
Archive verification/extraction is already retained in `unpacked/verification.json`;
the first command re-extracts the verified unpacked export without touching the mirror.

```powershell
# extract
& 'C:/Users/Michael/Documents/github/weather/scratch/w/missing-information-checks-20260921/scripts/ops/workstation_heavy.ps1' -Kind weather_heavy -PythonPath 'C:/Users/Michael/Documents/github/weather/venv/Scripts/python.exe' -ArgumentsBase64 'WyItbSIsInRvb2xzLnJlc2VhcmNoLm1pc3NpbmdfaW5mb3JtYXRpb24ucnVuIiwiZXh0cmFjdCIsIi0taW5wdXQiLCJDOi9Vc2Vycy9NaWNoYWVsL0RvY3VtZW50cy9naXRodWIvd2VhdGhlci9zY3JhdGNoL21pc3NpbmctaW5mb3JtYXRpb24tMjAyNjA5MjEvdW5wYWNrZWQiLCItLW91dHB1dCIsIkM6L1VzZXJzL01pY2hhZWwvRG9jdW1lbnRzL2dpdGh1Yi93ZWF0aGVyL3NjcmF0Y2gvbWlzc2luZy1pbmZvcm1hdGlvbi0yMDI2MDkyMS9yZXByb2R1Y2UtZXh0cmFjdGVkIl0=' -RepoRoot 'C:/Users/Michael/Documents/github/weather/scratch/w/missing-information-checks-20260921'
# analyze
& 'C:/Users/Michael/Documents/github/weather/scratch/w/missing-information-checks-20260921/scripts/ops/workstation_heavy.ps1' -Kind weather_heavy -PythonPath 'C:/Users/Michael/Documents/github/weather/venv/Scripts/python.exe' -ArgumentsBase64 'WyItbSIsInRvb2xzLnJlc2VhcmNoLm1pc3NpbmdfaW5mb3JtYXRpb24ucnVuIiwiYW5hbHl6ZSIsIi0taW5wdXQiLCJDOi9Vc2Vycy9NaWNoYWVsL0RvY3VtZW50cy9naXRodWIvd2VhdGhlci9zY3JhdGNoL21pc3NpbmctaW5mb3JtYXRpb24tMjAyNjA5MjEvcmVwcm9kdWNlLWV4dHJhY3RlZCIsIi0tb3V0cHV0IiwiQzovVXNlcnMvTWljaGFlbC9Eb2N1bWVudHMvZ2l0aHViL3dlYXRoZXIvc2NyYXRjaC9taXNzaW5nLWluZm9ybWF0aW9uLTIwMjYwOTIxL3JlcHJvZHVjZS1hbmFseXNpcyIsIi0taWVtIiwiQzovVXNlcnMvTWljaGFlbC9Eb2N1bWVudHMvZ2l0aHViL3dlYXRoZXIvc2NyYXRjaC9taXNzaW5nLWluZm9ybWF0aW9uLTIwMjYwOTIxL2llbSJd' -RepoRoot 'C:/Users/Michael/Documents/github/weather/scratch/w/missing-information-checks-20260921'
# supplement
& 'C:/Users/Michael/Documents/github/weather/scratch/w/missing-information-checks-20260921/scripts/ops/workstation_heavy.ps1' -Kind weather_heavy -PythonPath 'C:/Users/Michael/Documents/github/weather/venv/Scripts/python.exe' -ArgumentsBase64 'WyItbSIsInRvb2xzLnJlc2VhcmNoLm1pc3NpbmdfaW5mb3JtYXRpb24ucnVuIiwic3VwcGxlbWVudCIsIi0taW5wdXQiLCJDOi9Vc2Vycy9NaWNoYWVsL0RvY3VtZW50cy9naXRodWIvd2VhdGhlci9zY3JhdGNoL21pc3NpbmctaW5mb3JtYXRpb24tMjAyNjA5MjEvcmVwcm9kdWNlLWV4dHJhY3RlZCIsIi0tcmF3IiwiQzovVXNlcnMvTWljaGFlbC9Eb2N1bWVudHMvZ2l0aHViL3dlYXRoZXIvc2NyYXRjaC9taXNzaW5nLWluZm9ybWF0aW9uLTIwMjYwOTIxL3VucGFja2VkIiwiLS1iYXNlbGluZSIsIkM6L1VzZXJzL01pY2hhZWwvRG9jdW1lbnRzL2dpdGh1Yi93ZWF0aGVyL3NjcmF0Y2gvbWlzc2luZy1pbmZvcm1hdGlvbi0yMDI2MDkyMS9yZXByb2R1Y2UtYW5hbHlzaXMiLCItLW91dHB1dCIsIkM6L1VzZXJzL01pY2hhZWwvRG9jdW1lbnRzL2dpdGh1Yi93ZWF0aGVyL3NjcmF0Y2gvbWlzc2luZy1pbmZvcm1hdGlvbi0yMDI2MDkyMS9yZXByb2R1Y2Utc3VwcGxlbWVudCJd' -RepoRoot 'C:/Users/Michael/Documents/github/weather/scratch/w/missing-information-checks-20260921'
# clock
& 'C:/Users/Michael/Documents/github/weather/scratch/w/missing-information-checks-20260921/scripts/ops/workstation_heavy.ps1' -Kind weather_heavy -PythonPath 'C:/Users/Michael/Documents/github/weather/venv/Scripts/python.exe' -ArgumentsBase64 'WyItbSIsInRvb2xzLnJlc2VhcmNoLm1pc3NpbmdfaW5mb3JtYXRpb24ucnVuIiwiY2xvY2siLCItLWlucHV0IiwiQzovVXNlcnMvTWljaGFlbC9Eb2N1bWVudHMvZ2l0aHViL3dlYXRoZXIvc2NyYXRjaC9taXNzaW5nLWluZm9ybWF0aW9uLTIwMjYwOTIxL3JlcHJvZHVjZS1leHRyYWN0ZWQiLCItLXJhdyIsIkM6L1VzZXJzL01pY2hhZWwvRG9jdW1lbnRzL2dpdGh1Yi93ZWF0aGVyL3NjcmF0Y2gvbWlzc2luZy1pbmZvcm1hdGlvbi0yMDI2MDkyMS91bnBhY2tlZCIsIi0tb3V0cHV0IiwiQzovVXNlcnMvTWljaGFlbC9Eb2N1bWVudHMvZ2l0aHViL3dlYXRoZXIvc2NyYXRjaC9taXNzaW5nLWluZm9ybWF0aW9uLTIwMjYwOTIxL3JlcHJvZHVjZS1jbG9jayIsIi0taWVtIiwiQzovVXNlcnMvTWljaGFlbC9Eb2N1bWVudHMvZ2l0aHViL3dlYXRoZXIvc2NyYXRjaC9taXNzaW5nLWluZm9ybWF0aW9uLTIwMjYwOTIxL2llbSJd' -RepoRoot 'C:/Users/Michael/Documents/github/weather/scratch/w/missing-information-checks-20260921'
```

Final original output paths: `extracted-1`, `analysis-2`, `supplement-3`, `clock-3`.
Download evidence: `iem/manifest.json`, `iem-guidance-1/guidance_manifest.json`,
`iem-guidance-csv-1/structured_manifest.json`. A new download uses a new end time
and is new evidence; do not overwrite these manifests to reproduce the report.
