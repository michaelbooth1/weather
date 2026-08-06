# Workstation prove-the-blindness report - 2026-08-02

## Verdict

**The blindness is real, live-path relevant, and category (a) train/serve skew
for every affected feature. Category (b) is rejected.** The 09:00-14:00
artifact-bound training reconstruction is 97.04-100% populated by feature and
hour, while captured inference is 0% for eight numeric fields plus wind group
in both the frozen-gate qualified and excluded lanes. Cloud is effectively the
same defect with a Toronto-only serving overlay: 99.96-100% in training, 0% in
the qualified lane, and 11.16% in the excluded lane because all 254 populated
rows are Toronto.

The diagnosis is not a replay-table artifact. Directly invoking the base-commit
extractor on all 2,868 manifest-pinned 09:00-14:00 captured source envelopes
matched all 28,680 accepted affected-feature cells. WU history/current were
`paid_provider_disabled` in every envelope, METAR was fresh in every envelope,
ECCC SWOB was fresh in all 254 Toronto envelopes, and the station-observation
fallback existed in 2,858/2,868. The production-captured feature row is exactly
what this path emitted.

One important part of the original mechanism hypothesis is **not** confirmed.
These nulls do not take HGB missing-value branches. The eight numeric fields are
replaced by their artifact `SimpleImputer` medians; absent wind/cloud groups are
encoded as all-zero dummy vectors. No affected split traversed a native-missing
branch. Against a diagnostic native-NaN counterfactual, the combined actual
route moved HGB centre only `+0.0149` native units on average and was positive
on 54.29% of snapshots. The observed HGB centre was instead `-0.5381` settlement
bands versus market on average and was cooler on 69.71% of excluded snapshots.
The defect destroys discriminating information, but its fixed routing is not a
demonstrated one-direction cause of the observed cool displacement.

The strict exact centre oracle can retire **51.40%** of excluded-lane positive
excess; the liberal closest-feasible sensitivity retires **53.18%**. That is a
material ceiling, not a 2% effect, but it is also far short of a proof that a
real repair will recover half the loss. The oracle grants perfect market-centre
knowledge, preserves served entropy when feasible, and uses hindsight to apply
the correction only when it helps. It is an unattainable upper bound and not
expected gain.

Provenance is mixed. The already-trained artifact contents first appeared from
June 9 through June 14. Commit `5735b573` disabled WU history/current on June 30,
severing their training-time surface contract. Commit `2a878d91` added a free
METAR/ECCC station fallback on July 2, but only temperature and current max
reached the feature extractor. The loss of WU availability is a regression;
full free-source parity for trajectory, dew point, humidity, pressure, wind,
and cloud was never implemented.

This is a strong post-release-#1 experiment, not an authorization to repair it
now. No candidate, artifact, fit, feature view, serving change, or score was
created.

## Scope and guardrails

The work was based exactly on
`codex/workstation-1000-information-gap-audit-2026-08-19a @ f032bf4e` on branch
`codex/workstation-prove-1000-blindness-2026-08-20a`.

The sole declared output root is
`C:\Users\Michael\Documents\github\weather\scratch\runs\prove-1000-blindness-2026-08-20a`,
outside the mirror. The audit read only tracked artifacts and code, pre-2026 WU
history needed to reconstruct the artifact population, and the manifest-pinned
July 22-26 accepted replay/captured inputs. It did not read, enumerate,
evaluate, or substitute August 1-3 or August 6-19. It did not write `data/`, the
mirror, a feature/sidecar/marine path, or any artifact. July 31 remains the
`rows[-1]` POST-regime boundary and the observed-high floor is unchanged.

The initial local oracle declaration used the wrong label
`material_floor_binding == false` for the population. The calculation itself
used the correct pre-existing frozen gate: qualified iff `floor_available` and
`floor_removed_mass > 0.20`, excluded otherwise. The correction receipt records
that mismatch and that it was noticed after the first deterministic
calculation. The oracle formula and gate both predate this mission, but the
number below is deliberately described only as a post-hoc mathematical ceiling
and is permanently invalid for candidate or promotion evidence.

## 1. Training versus inference coverage

### Artifact-bound reconstruction

The artifacts do not retain raw row-level lineage or per-feature missingness
counts, so an exact raw training table cannot be read directly from the
pickles. They do retain three useful fingerprints:

1. Every tree root retains its exact fit count: 164/165 rows for ten markets,
   439 for Miami, and 649 for Toronto, totaling 2,734 rows per hour.
2. Every affected numeric imputer statistic is finite.
3. The hour-specific artifacts split on these fields and their one-hot wind and
   cloud encodings, which requires variation in those exact hour matrices.

The reconstruction used each artifact's first-content commit date, the
corresponding +/-7-day target-season history, and the most recent rows bounded
to the immutable root-node count. This reproduces 571/576 affected numeric
medians exactly, 575/576 within 0.1 native units, and the last within 1 unit.
That is a strong artifact-bound fingerprint, but the percentages below remain
forensic reconstructed rates rather than retained original counters.

Training lane is `N/A`: the historical feature records did not retain a
serve-time floor-gate qualification. The qualified/excluded split is therefore
reported only for captured inference, where it is defined.

| Base feature | Train 09 | Train 10 | Train 11 | Train 12 | Train 13 | Train 14 | Inference excluded | Inference qualified | Verdict |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| Rise from 07:00 | 99.82% | 99.78% | 99.82% | 99.82% | 99.78% | 99.89% | 0.00% | 0.00% | **(a)** |
| Warming rate, 2 h | 99.82% | 99.82% | 99.85% | 99.85% | 99.78% | 99.89% | 0.00% | 0.00% | **(a)** |
| Hours at peak | 100.00% | 100.00% | 100.00% | 100.00% | 100.00% | 100.00% | 0.00% | 0.00% | **(a)** |
| Dew point | 99.78% | 99.71% | 99.82% | 99.82% | 99.74% | 99.89% | 0.00% | 0.00% | **(a)** |
| Humidity | 99.82% | 99.78% | 99.82% | 99.85% | 99.82% | 99.93% | 0.00% | 0.00% | **(a)** |
| Pressure | 99.82% | 99.82% | 99.82% | 99.82% | 99.82% | 99.89% | 0.00% | 0.00% | **(a)** |
| Pressure trend, 3 h | 99.78% | 99.78% | 99.82% | 99.82% | 99.78% | 99.82% | 0.00% | 0.00% | **(a)** |
| Wind speed | 97.04% | 97.37% | 98.21% | 98.54% | 98.83% | 99.01% | 0.00% | 0.00% | **(a)** |
| Wind group | 99.85% | 99.71% | 99.82% | 99.71% | 99.85% | 99.78% | 0.00% | 0.00% | **(a)** |
| Cloud group | 100.00% | 99.96% | 100.00% | 100.00% | 100.00% | 100.00% | 11.16% | 0.00% | **(a), Toronto-only overlay** |

The inference denominators and cloud exception are hour-specific:

| Hour | Excluded snapshots | Qualified snapshots | Nine fully blind fields, excluded / qualified | Cloud, excluded | Cloud, qualified |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 09 | 451 | 52 | 0.00% / 0.00% | 9.76% | 0.00% |
| 10 | 429 | 62 | 0.00% / 0.00% | 10.02% | 0.00% |
| 11 | 401 | 80 | 0.00% / 0.00% | 10.22% | 0.00% |
| 12 | 354 | 118 | 0.00% / 0.00% | 11.58% | 0.00% |
| 13 | 341 | 111 | 0.00% / 0.00% | 10.85% | 0.00% |
| 14 | 299 | 170 | 0.00% / 0.00% | 16.05% | 0.00% |

This rejects category (b) in two independent ways. The same feature is
populated and varying in each hour-specific training matrix, and the qualified
serving lane is just as blind as the excluded lane. The gate partitions the
consequences; it does not explain the missing fields.

## 2. Direct serving-path check

Captured inputs are already production-serving envelopes, but this audit went
one step closer than the prior flattened replay analysis:

- It selected the exact 2,868 manifest-pinned July 22-26 envelopes whose
  accepted floor trace lands at 09:00-14:00.
- It instantiated the base-commit model in research-unbound mode and invoked
  [`extract_live_features()`](../../src/weather/model/model_features.py#L739)
  directly on each captured `sources` payload at its captured time and effective
  cutoff.
- It compared ten affected fields against the accepted feature audit row
  emitted by the production capture. All `28,680 / 28,680` cells matched.
- The captured runtime used multiple master commits over the five days, but
  all 2,868 envelopes identify the same production `model_features.py` SHA-256
  `28bb052c...`. The base-commit extractor has since changed hash, yet reproduces
  all affected cells exactly.

This establishes the captured production serving path and shows the blindness
persists in the requested base code. It cannot establish what the production
process is running **now** because this mission had no production-host access
and was forbidden to use its credentials.

The exact host-side check is read-only: for one currently running process,
capture or select one source envelope, call that process's
`model.live_feature_record(sources, effective_cutoff_hour, captured_at)`, and
join the result by `snapshot_id` to its emitted `features.jsonl` row. Record the
active release/process identity and code hash; verify that METAR/ECCC is healthy
while `rise_from_7am`, `warming_rate_2h`, `hours_at_peak`, `dewpoint_c`,
`humidity`, `pressure`, `pressure_trend_3h`, `wind_speed_kmh`, and `wind_group`
remain null, with cloud populated only on the Toronto path. No collector restart
or write is required. If that process does not expose an in-memory envelope,
use the matching latest `replay_inputs.jsonl` and `features.jsonl` records from
the same snapshot instead.

## 3. Routing and centre direction

The handoff's premise that these rows use fitted HGB missing branches is not
the serving implementation:

- [`_evaluate_feature_model_for_cutoff()`](../../src/weather/model/model_features.py#L1093)
  runs `SimpleImputer.transform()` first.
- It restores native NaN only for the explicit
  `NATIVE_NAN_FEATURE_COLUMNS`; none of the eight affected numeric fields is on
  that list.
- A null wind/cloud group compares unequal to every category and therefore
  becomes an all-zero dummy vector, not NaN.

Across the 2,275 excluded snapshots, every affected numeric split took an
ordinary left or right threshold branch. Native-missing branch count was zero.
All 1,020,418 reached wind-dummy splits went left because every wind dummy was
zero. Cloud routing was 271,403 ordinary-left and 2,902 ordinary-right; the
right routes are the Toronto rows with an observed cloud category.

For a direction diagnostic only, the audit replaced the already-preprocessed
affected columns with NaN and compared HGB centres. This is not a feature view,
candidate, repair, or score; it asks what the unused native-missing routes would
have done.

| Route group | Mean actual-minus-native-NaN HGB centre, native units | Median | Positive / negative share |
| --- | ---: | ---: | ---: |
| All affected together | +0.0149 | +0.0271 | 54.29% / 45.71% |
| Wind speed | -0.0345 | -0.0098 | 46.55% / 53.45% |
| Wind group | -0.0335 | -0.0139 | 45.32% / 54.68% |
| Cloud group | +0.0316 | 0.0000 | 48.88% / 48.44%; 2.68% unchanged |
| Every other affected numeric field | -0.0094 to +0.0068 | near zero | mixed |

The observed excluded-lane displacement is materially cooler:

| Centre comparison | Mean bands | Median bands | Cool share |
| --- | ---: | ---: | ---: |
| HGB minus market | -0.5381 | -0.3509 | 69.71% |
| Final served model minus market | -0.3126 | -0.1379 | 61.45% |
| Final served model minus winner | -0.2585 | -0.0708 | 53.23% |

Only sign, not magnitude, is comparable across the first table's native bucket
centres and the second table's settlement-band indexes. Even by sign, the
combined imputer/zero route is slightly warm and nearly balanced while the
observed error is broadly cool. The branch-direction mechanism is therefore
**not supported**. What is supported is an information-loss mechanism: nine
features are constant after preprocessing across this lane, so trees trained to
differentiate trajectory and surface regimes cannot do so at serve time.

## 4. Excluded-lane upper bound

The oracle reuses the centre-versus-width ceiling construction on the correct
frozen-gate excluded population only:

1. Normalize the served and contemporaneous market distributions over 11
   ordered bands.
2. Exponentially tilt the served distribution to the market expected band.
3. At fixed corrected centre, return entropy/effective-band count to the served
   value when feasible.
4. Use hindsight to choose the complete correction or the unmodified served
   distribution per snapshot according to lower summed positive excess Brier.
5. Leave infeasible moment pairs untouched in the strict result; allow the
   closest feasible entropy boundary only as a liberal sensitivity.

The hard observed-high floor and the served support are retained. No estimator
is fitted and no parameter is selected.

| Metric | Baseline excluded | Strict exact oracle | Liberal boundary sensitivity |
| --- | ---: | ---: | ---: |
| Snapshots | 2,275 | 1,547 corrected | 1,591 corrected |
| Daily-weighted positive excess Brier | 0.373823 | 0.181665 | 0.175014 |
| Positive-excess reduction | - | **51.40%** | **53.18%** |
| Daily-weighted model Brier reduction | - | 0.201636 | 0.207126 |
| 30-point severe rows | 922 | 230 | 205 |
| 5-point positive-excess rows | 4,662 | 3,430 | 3,272 |

The excluded population is 79.32% of held 09:00-14:00 snapshots and contains
69.42% of the incumbent lane's daily-weighted positive excess. The strict
oracle reduces positive excess on the original 30-point severe tail from
0.174913 to 0.059223, a 66.14% reduction. Of 2,275 moment pairs, 2,197 are exact;
62 clip to the feasible maximum entropy and 16 to the feasible minimum, so they
remain unmodified in the strict ceiling.

The assumptions are intentionally extravagant. Restoring METAR/ECCC fields
does not confer market-centre knowledge, and a real model cannot use the
winner-aware selector. The bound attributes every correctable centre error on
an affected snapshot to this contract and allows no implementation cost,
estimation error, unit mismatch, or regime shift. Therefore **51.40% is the
maximum prize under this oracle, not a forecast of repair lift**. It says the
line is material enough for a later isolated serving experiment, but cannot by
itself justify a serving change.

## 5. Provenance: regression plus never-implemented parity

The active artifact contents predate the serving break:

| Artifact content epoch | Markets |
| --- | --- |
| June 9 | Austin, Chicago, Houston, Los Angeles, Seattle |
| June 10 | Atlanta, Dallas, Denver, NYC, San Francisco |
| June 13 | Toronto |
| June 14 | Miami |

Git history then shows this sequence:

1. Commit `ebebce76` (May 30) established the extractor's WU history/current
   dependency for trajectory, dew point, humidity, pressure, wind, and cloud.
2. Commit `5735b573` (June 30) changed WU history/current from provider calls to
   `paid_weather_provider_disabled(...)`. All held captures confirm the resulting
   expected-unavailable state.
3. Commit `2a878d91` (July 2) derived `station_observations` from METAR/ECCC and
   admitted it to current temperature/current max. It did not route the captured
   row sequence or other surface fields into the feature contract.

So the correct provenance answer is **both**:

- Regression: a training-time WU surface contract was disabled after every
  active artifact was trained.
- Never implemented: the policy-compliant free-source fallback never achieved
  field parity beyond temperature and the observed-high/current-max path.

Re-enabling a paid provider is unsupported and is not the repair implication.
A future authorized mission would need a point-in-time, native-unit,
train/serve-parity contract for the free METAR/ECCC fields, followed by the full
release gate. No such work was performed here.

## Handback

The two requested decisions are:

1. **(a) for every feature; (b) for none.** Cloud has a Toronto-only serving
   overlay, not a legitimate lane-specific training gap.
2. **The strict prize ceiling is 51.40% of excluded-lane positive excess**
   (53.18% liberal sensitivity). It is material, but it is not expected gain and
   does not prove that a repair will reproduce the oracle.

The absence of a one-direction branch mechanism is an important negative
finding. It prevents the correct contract diagnosis from being overstated as a
causal explanation for all centre displacement.

The `-08-16a` mission remains queued for 2026-08-05 04:30. No release, pointer,
promotion, capture, scheduler, mirror, ACL, or production-host state changed.

## Evidence identities

| Evidence | SHA-256 |
| --- | --- |
| Mission declaration | `464b71ebf3ad7734a1362822e4c21d69aa13f7308456540af88430ba4cac7029` |
| Artifact provenance | `7de091a8c160a6c63af45c9774ccf451c80a54b8ffce2a5accb61282b4a3f02f` |
| Training/inference coverage | `01e539543373eee94cc798676489e34e855851567190f6548a139e8d0fd2a47b` |
| Direct serving-path check | `0930dd914150b061936692b4356b5b20e7950cf3d1962e7f41cbdbe0b075d7b5` |
| Routing effect | `ed8e2e99b2c053c52efa1d7661846c0589ec9c748fc3bf88a2204c8d9388718a` |
| Oracle declaration | `c96a0437bb6c788714c4a598040aa13f67e80b8f8c8ff4d809783134a7300d6c` |
| Oracle declaration correction | `3a6811bc4575fca140ccbb899cf7c4162cb6ce692e6353f1617d9449c9873ec8` |
| Excluded-lane oracle bound | `76ac1a8481ce34cd440e5bf589e4bc54eaec12bcd05d94e23af93ca890bafa13` |
| Regression provenance | `38ceb0d9eacd2225763084380036cc80c0ae8421fd5717bb5bd5224de1c0facb` |
| Accepted development replay input | `55fd5104d7aa8240a9714d368ab15dd9bda34d87c4da27d7025b6cdb7c8e9ccd` |
| Accepted development floor trace | `2e9da6e324130494760cd6b2dbe632658f6b29b99615439bab66fa1141519c9b` |
| Development corpus manifest | `8cf0d01d222172dadd024b3e55a69494860477785ec100cbe8ae2ed546c1662d` |

The tracked report is the only repository change. Audit scripts and JSON remain
ignored under the declared run root.
