# Workstation report 2026-08-03 — scope the forecast archive extension

## Verdict

The transfer is feasible; the proposed drop-in archive extension is not.

At the current format, the requested May 10 through August 31 envelope for
2018–2025 would be about **428.3 MiB** and require **192 HTTP requests** (about
**2,423 free-tier call-equivalents** under Open-Meteo's documented long-request
weighting). A conservative current-format build limited to the potentially
admissible 2021–2025 years is about **398.4 MiB**, **120 requests**, and **1,515
call-equivalents**. Only its issue-qualified fixed-lead rows could enter the PIT
forecast role; the size intentionally retains the rest as an upper bound. The
existing 12-market corpus is 226.8 MiB. A healthy serial build should fit in a
two-hour window, with roughly 45–90 minutes the planning range. Neither the
request count nor the final storage requires a paid provider.

That is not the hard part. The current `forecast_daily.csv` is derived from
Open-Meteo's Historical Forecast API, which stitches the first hours of
successive model runs into a continuous time series. The repository stores
those rows with an empty `issue_time` and
`issue_time_basis=stitched_continuous_archive`, then takes the maximum over the
target day. It therefore cannot prove that `forecast_high` was known at the
training row's cutoff. Extending that series would widen an archive whose
point-in-time contract is already insufficient.

Open-Meteo's exact issue-aware alternatives do not cover the requested years
symmetrically. Previous Runs has GFS 2 m temperature from March 2021 and JMA
from 2018, while most models begin in 2024. Single Runs preserves an exact run,
but IFS HRES begins in March 2024 and most other models begin in April 2026.
There is no documented way to reconstruct the current `best_match` forecast,
with the current variables and one coherent issue, for every year 2018–2025.

The safe disposition is therefore:

1. build a **separate, versioned training-only corpus** after release #1 and the
   lock window, using an explicit issue/lead contract and excluding the target
   year;
2. leave the active analog archive byte-for-byte pinned;
3. fail the first retrain until the new corpus has exact date/field/PIT
   coverage and the WU train/serve contract independently passes; and
4. widen analog inputs only later, as a separately release-bound serving-input
   change with an old-versus-new output gate.

If the first retrain requires the same coherent issue and source/model contract
for 2018–2020, the answer is **not feasible from the documented Open-Meteo
archive today**. That would require a new free upstream archive, provider-side
reconstruction, or asymmetric training support. It must not be papered over
with stitched rows or silent missing-value imputation.

No archive, row, artifact, sidecar, cache, candidate, fit, score, release,
pointer, scheduler, serving process, ACL, mirror, credential, or production
host state changed.

## Scope and evidence boundary

This report is based exactly on `master` at
`3eb4305a3de2f73c19bee8a3a87e19d2b6ea5405`. The sole declared output root is

`C:\Users\Michael\Documents\github\weather\scratch\w\forecast-archive-extension-28a`

and the tracked report is the only output.

The local `data/` deny-write ACL was verified, not changed. Inspection read
only forecast-history manifests and file metadata; it did not read forecast
CSV rows or any trading/evaluation row. It did not read, enumerate, evaluate,
or substitute any reserved date named in the handoff. No API data endpoint was
queried. Provider feasibility was checked only against current public
Open-Meteo documentation.

Relevant provider contracts:

- Historical Forecast API:
  <https://open-meteo.com/en/docs/historical-forecast-api>
- Previous Runs API:
  <https://open-meteo.com/en/docs/previous-runs-api>
- Single Runs API:
  <https://open-meteo.com/en/docs/single-runs-api>
- Free-tier limits and call weighting:
  <https://open-meteo.com/en/pricing>
- Non-commercial free-use terms:
  <https://open-meteo.com/en/terms>

## 1. What exists now

All 12 manifests have the same logical contract:

| Property | Observed aggregate |
| --- | ---: |
| Generated | 2026-06-23 |
| Season window | May 10 through June 30 |
| Covered years declared | 2018–2026 |
| Compatibility forecast days | 5,532 fleet / 461 per market |
| Rich long rows | 747,648 fleet / 62,304 per market |
| Daily issue rows | 31,152 fleet / 2,596 per market |
| On-disk bytes | 237,844,913 bytes / 226.8 MiB |

The final 2026 partition was necessarily partial at its June generation time,
so “52 days per year” is the configured full-year window rather than the exact
count in every partition. File modification time is not logical currentness;
the decisive contract is the fixed May–June window.

The producer makes two requests for each market/year:

- Historical Forecast requests 21 hourly fields from `best_match` and converts
  every returned hour into a rich row.
- Previous Runs requests temperature at fixed lead offsets 1–7, currently only
  from 2021 onward, and emits separate issue rows.

`load_forecast_daily()` ignores the Previous Runs issue rows. It reads the
compatibility daily file created only from
`open_meteo_historical_forecast` rows. Both base training and serving analog
matching therefore receive the stitched daily maximum, not an issue-selected
forecast.

The manifests prove row totals, endpoints, configured leads, schemas, and the
season window. They do **not** prove per-variable completeness, model identity
within `best_match`, raw-response integrity, actual issue availability, or
cutoff-safe use.

## 2. Can the provider support the extension?

### Endpoint availability

| Endpoint | Documented availability | Issue/PIT quality | Disposition |
| --- | --- | --- | --- |
| Historical Forecast | Continuous archive around 2021 onward, with model-specific exceptions including IFS HRES and JMA before then | Stitches the first hours of successive runs; no coherent issue for a daily maximum | Useful as a forecast-like/reanalysis covariate, **not acceptable as forecast-at-cutoff evidence** |
| Previous Runs | Most models from 2024; GFS 2 m temperature from March 2021; JMA GSM/MSM from 2018 | Fixed 1–7 day offsets, not a preserved complete run | Potential training contract from 2021, but only after freezing lead/model/availability semantics and matching serving to it |
| Single Runs | IFS HRES from 2024-03-14; most other models from 2026-04-02 | Exact initialization selected by `run`; publication occurs roughly 1–6 hours later depending on model | Correct primitive, but too little history for the requested all-year corpus |

The Historical Forecast documentation lists the same broad variable catalogue
as the live API, but availability is model- and era-dependent. The existing
manifests contain no field-level counts, so they cannot establish that all 21
current request fields exist for late-July/August in every year. That must be a
future metadata/data probe, not an assumption.

### What `previous_runs` starting in 2021 implies

It is not merely an implementation cutoff. It marks a real support break:

- GFS 2 m temperature can supply the current fixed-lead temperature shape from
  2021 onward.
- JMA GSM may extend temperature support to 2018, but it is a different,
  explicitly selected global model and resolution. Substituting it for
  `best_match` in early years would create a year-conditional source contract.
- Exact preserved runs cannot fill the gap because Open-Meteo's Single Runs
  coverage begins later.

Therefore 2018–2020 stitched rows cannot be promoted to PIT forecasts. The
first admissible choices are:

1. **recommended:** make the forecast-selected training population explicitly
   2021–2025 and require 100% selected-date coverage there;
2. define and test a versioned mixed-model contract with a source/model
   indicator, which is a broader feature change; or
3. exclude the forecast fields entirely and freeze equal train/serve
   missingness, which forfeits parent-selected predictors and is not the first
   retrain described by `-08-25a`.

No choice may label stitched 2018–2020 values as forecasts known at issue time.

### Paid-provider boundary

No API key or paid plan is technically required for the planned request
volume. The current free endpoint limit is 10,000 calls/day, 5,000/hour, and
600/minute. However, the free service is contractually for non-commercial use
and has no uptime guarantee. Execution remains conditional on the repository
owner confirming that the existing use qualifies under those terms. If it
does not, the repository's no-paid-provider rule makes this Open-Meteo plan a
hard blocker rather than permission to subscribe.

## 3. Request volume, wall time, and disk

For a concrete serving-season estimate, this report uses May 10 through August
31: 114 calendar days per complete prior year.

### Requested 2018–2025 envelope

The table sizes the current format before applying the PIT support exclusion.

| Quantity | Estimate |
| --- | ---: |
| Markets × years | 12 × 8 |
| Raw HTTP requests | 192 (96 historical + 96 previous-runs) |
| Call-equivalents | about 2,423 |
| Compatibility daily rows | 10,944 fleet |
| Daily issue rows | 58,824 fleet |
| Rich long rows | 1,411,776 fleet |
| Final current-format size | 449,108,789 bytes / 428.3 MiB |
| Existing plus separate candidate | about 655.1 MiB |

The conservative 2021–2025 current-format subset is smaller:

| Quantity | Estimate |
| --- | ---: |
| Markets × years | 12 × 5 |
| Raw HTTP requests | 120 (60 historical + 60 previous-runs) |
| Call-equivalents | about 1,515 |
| Compatibility daily rows | 6,840 fleet |
| Daily issue rows | 54,720 fleet |
| Rich long rows | 1,313,280 fleet |
| Final current-format size | 417,720,175 bytes / 398.4 MiB |
| Existing plus separate candidate | about 625.2 MiB |

The call-equivalent estimate applies Open-Meteo's documented weighting for
requests longer than two weeks and requests containing more than ten
variables. It is an admission estimate, not a provider bill or measured API
receipt.

Including a complete 2026 partition would raise the current-format result to
about **508.0 MiB** and 216 raw requests. It is unnecessary for the first
retrain and should not be fetched: `historical_target_cache()` excludes the
target year by default, and both training and 2026 analog selection use prior
years.

### Wall time

The existing manifest completion timestamps span about 20 minutes across the
12-market June build. The proposed 2021–2025 materialization contains about
1.76 times as many long rows, which gives a 35-minute empirical lower planning
estimate. Hashing, field-completeness checks, checkpoints, provider variance,
and retries make **45–90 minutes** the honest healthy range. Reserve two hours;
abort into a resumable state at four hours.

The present client uses a 30-second request timeout, three attempts, bounded
exponential delay, and `Retry-After` support. That is adequate for small
requests but not a durable fleet-resume contract.

### Disk admission

The conservative 2021–2025 candidate itself is only 0.389 GiB (the broad
requested envelope is 0.418 GiB). A safe build should reserve **1.5 GiB** for
the existing 226.8 MiB archive, versioned derived candidate,
raw compressed responses, receipts, and atomic staging headroom. At 105 GB
free this is not the capacity blocker. At the stated 9.6 GB/day host loss,
however, 1.5 GiB is only about 3.75 hours of ambient erosion; execution must
recheck the host reserve immediately before starting rather than relying on
this design-day number.

### Required resume behavior

The current `backfill()` is not resumable or atomic. It catches a year error,
continues, and finally overwrites the three canonical CSVs from whatever
succeeded in memory. A transient failure can therefore publish a partial
archive, and a rerun starts every request again.

The replacement contract should:

1. write an immutable plan of every market/year/endpoint/window/model/variable
   request before network access;
2. persist each raw response under a request-keyed staging root with HTTP
   metadata, retrieval time, SHA-256, byte count, and validation status;
3. resume by skipping only hash-verified complete request units;
4. preserve an explicit failure ledger—zero rows is never silently success;
5. materialize derived files only after all required units and field matrices
   pass;
6. publish a new content-addressed corpus manifest atomically, never overwrite
   the active archive in place; and
7. retain enough raw lineage to reproduce every derived daily high.

Concurrency should remain one or at most two requests, honor `Retry-After`, and
admit the planned call-equivalents against the free-tier daily budget before
the first request.

## 4. Serving impact and required gate

### What widening the current path changes

`TorontoHighTempModel.build()` computes the probability distribution before it
calls `find_analog_days()`. The archive loaded inside analog search has no path
back into `estimate_distribution_result()` or the live base feature record.
Therefore a pure widening of the existing daily archive changes **none** of:

- the served bucket probability distribution;
- top temperature or market rows;
- the live base feature matrix;
- boundary transitions; or
- late-day continuation probability.

It does change served explanatory output:

- historical analog `forecast_high` and `forecast_gap` become populated;
- forecast-gap standardization and the analog distance term become active;
- top-five neighbor identities, order, distance, similarity, dates, settlement
  buckets, and temperature paths may change;
- the deep-dive “historical analogs” percentage and sentence may change; and
- the Streamlit analog panel displays the changed neighbors and values.

For the challenged late-season window the prior candidates all lack archived
forecast gap. Holding the candidate universe and non-forecast features fixed,
adding the forecast-gap term is non-negative for each candidate: its distance
can only stay equal or increase and its similarity can only stay equal or
decrease. Ranking can move either way because candidates receive different
penalties. The selected five's settlement composition can also move either
way. With five neighbors, the displayed analog percentage can move anywhere
from 0% to 100% in 20-point increments. The analog count itself should not
change because forecast fields are optional in `analog_feature_view()`.

Those are exact code-path bounds. An empirical magnitude is intentionally not
claimed because this mission could not read the reserved serving population.

### Gate before any analog widening

The current unversioned `daily_path_for(spec)` is ambient serving state. An
in-place backfill would alter the next build without a code change, release
binding, or review. That is unacceptable.

A later analog-v2 change must require a self-hashed corpus ID bound into the
serving release and a dual-read receipt over permitted captured inputs. The
gate must prove:

1. exact equality of the base feature vector, complete probability
   distribution, top temperature, boundary transition, and late-day outputs;
2. old/new analog candidate count, top-k Jaccard overlap, rank movement,
   per-neighbor distance/similarity delta, and settlement-bucket composition;
3. exact PIT and field coverage for every newly admitted analog date;
4. no global/ambient fallback when a release-bound corpus is declared; and
5. explicit operator acceptance of the UI/explanation diff.

Any probability or base-feature difference is a hard block because it would
contradict the traced isolation boundary. Analog explanation changes are
reviewable, not automatically acceptable.

### Split recommendation

The first corpus should be passed explicitly to the inactive base-retrain
candidate and its preflight. It must live outside `data/forecast_history` and
must not be discoverable by `daily_path_for()`. This makes the first retrain
possible without changing active served output.

Analog widening should be a later task with its own corpus role, release
binding, replay receipt, and roll decision. The two corpora may share immutable
raw responses, but they must not share an activation pointer.

## 5. Point-in-time and missingness contract

### Required row provenance

Every accepted forecast value must carry:

- provider, endpoint, canonical request hash, source model, and model/run ID
  where the provider exposes one;
- target market/station, target local date, valid time UTC/local, and source
  timezone;
- model initialization or documented nominal issue time, conservative
  `available_at_utc`, retrieval time, and the feature row's cutoff/as-of time;
- lead duration, variable, source unit, normalized unit, and normalizer/schema
  version;
- raw response SHA-256 plus the derived-row and corpus hashes; and
- an issue-evidence kind such as `single_run` or `fixed_lead_offset`.

Acceptance requires `available_at_utc <= feature_as_of_utc` and complete target
day hourly coverage. Initialisation time alone is insufficient because the
Single Runs documentation states that output becomes available one to six
hours later. A row failing the inequality is recorded as lookahead and blocks
the corpus; it is never trusted because its valid time is earlier than the
outcome.

The existing `previous_run_rows()` sets issue time to local midnight on
`target_date - lead_days`. That is not a provider run ID or publication time
and must not satisfy this contract. Likewise, an empty issue time on a stitched
row is an explicit non-PIT state, not missing metadata to infer later.

### Daily feature construction

`forecast_high` must be the maximum of one predeclared, cutoff-safe forecast
envelope. Do not combine hours whose values came from different later runs and
call the result a morning forecast. The feature contract must freeze:

- source model or model-selection policy;
- issue/lead rule and publication-lag rule;
- target-day valid-hour set and DST behavior;
- native C/F conversion;
- fallback and missingness behavior; and
- the identical live-serving construction.

If fixed-offset Previous Runs is selected, it becomes a new versioned feature
contract, not retroactive proof that the current stitched `forecast_high`
meant the same thing. If a coherent Single Run is required, the usable history
begins in 2024 and sample sufficiency must fail closed rather than borrow
earlier stitched values.

### Reserved-window avoidance and 2026

The base trainer excludes rows whose year is the target year. The new training
corpus manifest must make that exclusion structural:

- `target_year_excluded=true`;
- expected years are explicitly enumerated before collection;
- a target-year response is rejected from the training role even if present in
  a shared raw store; and
- corpus hashes cover the selected-year matrix.

Consequently the first training corpus needs no 2026 extension. Omitting it is
both cheaper and the cleanest proof that reserved current-year outcomes did not
enter training. A future analog corpus also uses prior years under the default
serving cache, so it does not justify a 2026 fetch either.

### Frozen missingness policy

For every parent-selected forecast field and every selected training date,
preflight must prove:

`expected dates = present dates = cutoff-safe dates = unit-valid dates`

at 100% for all 12 markets. Coverage is evaluated per market, year, date,
field, issue contract, and cutoff—not by total row count.

The recommended response to unavailable 2018–2020 PIT forecasts is to exclude
those years from the forecast-selected training population and receipt the
reduced support. Median imputation is not an equality policy when serving has a
forecast. A missingness lane is admissible only if the same deterministic
availability rule and indicator are used at train and serve and its ablation
is separately approved.

## 6. Ownership and staleness alarms

Historical partitions do not become stale merely because their generation
timestamp ages. The failure here was **logical horizon staleness**: the required
target-season window moved beyond the fixed corpus.

Ownership should be split between a collector and a mandatory consumer:

### Collector owner

`weather.sources.forecast_history` should own a future plan/collect/materialize
surface that writes only versioned corpus candidates. It runs:

- once to establish the complete May–August historical envelope;
- annually, after a calendar year becomes an eligible prior year;
- on an explicit provider/schema/normalizer revision; and
- on demand only for a missing immutable partition identified by the planner.

It should not refetch every historical byte daily.

### Daily owner

The nightly retrain plan should contain an unskippable, read-only
`forecast_corpus_readiness` step. Every night it computes the exact seasonal
support required by the next declared target date and verifies the active
training-corpus manifest, hashes, market/year/date/field matrix, issue
contract, target-year exclusion, and provider-license disposition.

The step must:

- warn when fewer than 14 calendar days of declared target support remain;
- fail the retrain lane when fewer than seven remain or any required date is
  absent;
- make `all_market_base_retrain` unreachable on failure;
- publish the failure in the authoritative nightly status/manifest; and
- raise the existing operator-visible task failure/alert, not only write a
  coverage report.

For a future serving analog corpus, the same readiness receipt must be bound to
the active release. Expiry keeps the prior verified corpus active and marks the
new analog role unavailable; it never silently adopts a mutable path.

This is an owner because the collector has a named cadence and the consumer
hard-fails a real scheduled lane. A dashboard-only staleness number is not.

## 7. Sequencing against WU parity

The two repairs can be implemented independently, but the first base retrain
requires both to pass together.

Recommended order after release #1 and the lock window:

1. **Implement and gate exact WU regression restoration first.** It repairs an
   active serving defect and establishes the observation feature contract the
   retrain must reproduce. If exact public-WU parity fails, make the explicit
   METAR/ECCC retrain-contract decision before fitting anything.
2. In parallel, implement the forecast corpus planner, immutable request
   receipts, resume ledger, and training-only path. This work does not touch
   serving and does not depend on WU values.
3. After the forecast issue/lead contract is frozen, perform one authorized
   provider coverage probe and build the 2021–2025 training corpus. Do not
   fetch 2026.
4. Require exact PASS from both the WU value/missingness parity receipt and the
   forecast corpus PIT/coverage receipt before the all-market base step may
   fit.
5. Consider analog-v2 widening only after the inactive base candidate work,
   behind the separate serving-output gate above.

They do not need to land in the same commit or release. WU restoration may land
alone after its full serving gate. The training-only forecast corpus may land
alone because it has no serving consumer. Neither independently authorizes the
first retrain.

## 8. Why this is harder than it looks

The bytes are a morning's work; the evidence contract is not.

- The current historical daily maximum is not bound to one issue and may use
  information from successive target-day runs.
- The only exact-run API has too little history; the longer fixed-lead API is
  asymmetric by year and model.
- `best_match` hides model changes, while field availability differs by model
  and era.
- The manifest has no field-level completeness, raw payload hashes, failure
  ledger, or actual issue/publication time.
- The current backfill overwrites canonical files after partial success and
  cannot resume.
- The active analog loader is ambient and unversioned, so a data-only backfill
  silently changes served explanations.
- Free-tier volume is adequate, but free-use eligibility and no-uptime terms
  remain an owner decision.
- Restricting PIT support to 2021–2025 sharply reduces the already small
  per-cutoff training population. Sample sufficiency must be re-proven before
  fit.

A production-quality training-only 2021–2025 lane is approximately **one to two
engineering weeks**, including schemas, resumability, PIT/coverage gates,
synthetic tests, and one authorized provider probe/build. The network transfer
itself should be under two hours. Requiring exact, coherent, same-contract
2018–2020 forecasts changes the answer to provider/reconstruction research and
could take a month or remain impossible.

## Handback

- **Feasible:** request volume and disk; a separate PIT training corpus from
  the years Open-Meteo actually supports under a frozen issue contract.
- **Not feasible as stated:** an all-year, drop-in extension of the current
  stitched archive with trustworthy issue-time provenance.
- **Serving disposition:** split now; current archive remains pinned. Later
  analog widening affects explanations/neighbor selection, not probabilities,
  and requires a release-bound differential gate.
- **PIT disposition:** no 2026 fetch; reject stitched/empty-issue rows; require
  100% selected-date field coverage or a genuinely equal train/serve
  missingness contract.
- **Owner:** immutable collector plus mandatory nightly readiness consumer and
  loud scheduled failure.
- **Sequence:** gate WU restoration first, build the independent training corpus
  in parallel, and require both receipts before the first fit.

No source file matches the capture supervisor's roll-sensitive patterns in
this design-only branch. The report can land after review without consuming a
capture-loop roll.
