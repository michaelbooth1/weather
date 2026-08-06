# Workstation contract-repair specification - 2026-08-02

## Verdict

The defect has two different repairs and they must not share a release claim.

1. **Regression restoration:** commit `5735b573` made both WU history and WU
   current fail before network access on **2026-06-30 at 12:16:08 EDT**. An
   exact, public-page-backed WU-history restoration can be serving-side only
   and can reuse the fitted artifacts **without a retrain**, but only if it
   proves the same v1 history payload, station, requested units, row
   normalization, and point-in-time availability as the artifact-era path.
   That proof does not exist yet. There is no public `wu_current` replacement
   in the repository.
2. **Free-source parity:** routing METAR or ECCC SWOB into the affected
   predictors is **not** an exact restoration of their training distribution.
   Observation cadence, precision, pressure definition, wind unit, and weather
   category semantics differ. It therefore needs a separate feature-contract
   version and retrain. It must not be served through the current artifacts as
   a supposedly no-refit repair.

The direct answer to **"serving-side only, no retrain?" is no for the complete
METAR/ECCC repair, and conditionally yes only for exact WU-history
restoration.**

Every affected field can be made point-in-time valid from ECCC SWOB for
Toronto. METAR can directly support temperature trajectory, dew point,
pressure, wind, and weather/cloud classification. It cannot faithfully supply
relative humidity from the current Aviation Weather payload; deriving humidity
from temperature and dew point would be a new approximation and must remain
missing in this repair.

A real feature-level train/serve receipt would have caught the defect. The
current gate did not and, as implemented, still will not: it validates an
externally supplied boolean receipt but has no producer that compares training
and serving feature values. Release-bound captured-input replay compares live
serving with replay of the same captured inputs through the same code, so both
sides can be identically blind and pass. Release #1 alone does not close this
gap.

No repair, shim, feature view, candidate, artifact, fit, score, fresh-date read,
or runtime change was made.

## Scope and guardrails

This specification is based exactly on
`codex/workstation-prove-1000-blindness-2026-08-20a @ 6a068783`. The branch is
stacked and must remain held until release #1 exists.

The declared run-output root is
`C:\Users\Michael\Documents\github\weather\scratch\runs\spec-contract-repair-2026-08-21a`,
outside the mirror. It was intentionally unused: the work was static inspection
of tracked code, artifacts, commits, tests, prior aggregate receipts, and public
source contracts. The tracked report is the only output.

The audit did not read, enumerate, evaluate, or substitute 2026-08-01 through
08-03 or 2026-08-06 through 08-19. It did not read or write `data/`, write a
feature/sidecar/marine path, alter the observed-high floor, or access the
production host. July 31 remains the `rows[-1]` POST-regime boundary.

## 1. Regression half: exactly what `5735b573` changed

### Timeline

| Event | Commit/time | Contract consequence |
| --- | --- | --- |
| WU-backed feature extraction established | `ebebce76` (2026-05-30) | Training and serving read trajectory and surface state from WU history/current. |
| Paid path disabled | `5735b573aa284da070fba9b751d3a48f5819aca4`, 2026-06-30 12:16:08 EDT | WU history/current/forecast throw `paid_provider_disabled` before network. |
| Partial free fallback | `2a878d918cc7a3ef0b70950d4fa404650e6e507f`, 2026-07-02 18:31:59 EDT | Full METAR/SWOB row sequences were captured, but `station_observations` retained only current temperature and max since 07:00. |

The effective behavioral date is the first runtime adoption of `5735b573` on
or after June 30. Git cannot prove the production process restart time, but the
held captures show the disabled behavior and the prior audit reproduced it on
all 2,868 source envelopes.

### Exact code change

The parent of `5735b573` called two paid endpoints:

- `fetch_wu_history()` called the v1 station historical-observation endpoint,
  requested the market's `wu_units`, and normalized each observation to
  `time`, native temperature/dew point, relative humidity, pressure, cloud and
  condition text, wind cardinal, speed, and gust.
- `fetch_wu_current()` called the v3 current-observation endpoint and returned
  native current/max/dew point, humidity, cloud, condition, wind, and gust.

`5735b573` replaced the optional key constant with
`PAID_WEATHER_PROVIDER_ACCESS_ENABLED = False` and inserted
`paid_weather_provider_disabled(...)` at the top of both methods. The exception
is raised before `get_json()`. The same commit changed the source state to
`paid_provider_disabled`, cache state to `expected_unavailable`, and removed
`wu_current` from the declared fallback list. See
[`model_sources.py`](../../src/weather/model/model_sources.py#L88) and
[`model_constants.py`](../../src/weather/model/model_constants.py#L16).

It did **not** change the feature formulas. They still read the affected fields
from `wu_history.rows` or `wu_current`; see
[`extract_live_features()`](../../src/weather/model/model_features.py#L739).

### Fields that stopped reaching the active matrices

The active artifacts select these ten base fields. The previous direct-path
audit measured 28,680 / 28,680 accepted cells and found all ten blind on the
qualified lane as well as the excluded lane, except for Toronto's cloud
overlay.

| Field | Artifact-era WU input | Result after disablement |
| --- | --- | --- |
| `rise_from_7am` | target-date history temperature path | null |
| `warming_rate_2h` | target-date history temperature path | null |
| `hours_at_peak` | target-date history temperature path | null |
| `dewpoint_c` | latest cutoff history row, else WU current | null |
| `humidity` | latest cutoff history row, else WU current | null |
| `pressure` | latest cutoff history row | null |
| `pressure_trend_3h` | cutoff pressure minus approximately three-hour-prior pressure | null |
| `wind_speed_kmh` | latest cutoff history row, else WU current | null |
| `wind_group` | latest cutoff history cardinal, else WU current/forecast | null |
| `cloud_group` | latest cutoff history condition/cloud, else WU current/forecast | null except Toronto forecast overlay |

`wind_gust_kmh` and `wind_shift_3h_degrees` also depend on this surface path in
current code, but they are not selected by the active artifact set audited in
`-08-20a`; they are not part of the 28,680-cell finding.

### Can the old behavior simply be reverted?

**No. A literal revert is unsafe.** It would reintroduce a paid-provider
credential path that repository policy now forbids, undo expected-unavailable
source semantics, and bypass two months of source freshness, capture,
current-max quarantine, station fallback, and release-binding work. The old
empty key also did not make the endpoint operational.

A clean regression restoration exists only in a narrower form. The repository
already has `PublicWundergroundHistoryClient`, which derives transient access
from the public WU history page and calls the **same v1 station historical
endpoint** without a stored/user credential; see
[`wu_history.py`](../../src/weather/sources/wu_history.py#L209). A future live
adapter may reuse that client and the old row normalizer, provided it proves:

1. current-target-date observations are available at model-emission time;
2. the response station ID and requested `m`/`e` units match the market spec;
3. the normalized row values are byte/value equivalent to the artifact-era v1
   contract for every affected field;
4. the public-page access route is captured with `retrieved_at_utc` and fails
   expected-unavailable without falling back to paid access; and
5. only rows known by the capture and valid by the effective cutoff are used.

This is **awkward but bounded**, not a revert. The public client is currently a
historical backfill client, not a latency-bounded live source, and has no
current-observation counterpart. A failed current-day availability proof means
the regression half stays missing; METAR/ECCC must not be silently substituted
under the WU contract.

## 2. Never-implemented half: source contract inventory

### What the live extractors produce now

| Source | Current decoded row fields | Raw fields retained but not normalized | What `station_observations` preserves |
| --- | --- | --- | --- |
| Aviation Weather METAR, all markets | local target-date time, native temperature/dew point, wind direction degrees, wind speed/gust in knots, `cover`, raw METAR | payload may include altimeter/SLP, weather and cloud layers; none is normalized for features | source/station, current temperature, max since 07:00 only |
| ECCC SWOB, Toronto | local time/date, air temperature C, dew point C, RH %, 1/6/24 h maxima | retained XML contains pressure, 3 h pressure tendency, wind, gust, present weather, and cloud layers; live parser ignores them | source/station, current temperature, max since 07:00 only |

The richer historical adapters already demonstrate most required
normalization. [`metar_history.py`](../../src/weather/sources/metar_history.py#L35)
requests temperature, dew point, RH, wind, altimeter/SLP, sky and weather and
normalizes native temperatures, hPa, and km/h.
[`eccc_swob_history.py`](../../src/weather/sources/eccc_swob_history.py#L323)
parses the corresponding SWOB pressure, wind, present-weather, and cloud
elements. Those batch adapters are useful implementation references, but their
post-day archives are not point-in-time serving evidence.

### Exact field contract

Legacy names do not prove units. The active artifacts were trained on WU
responses requested with `wu_units=m` for the C market and `wu_units=e` for F
markets. Therefore `dewpoint_c` is native C/F, `wind_speed_kmh` is km/h for the
metric lane but mph for the English lane, and `pressure`/its trend follow the
WU response unit (hPa/mb metric, inHg English). A no-refit path must preserve
those artifact-era units despite the misleading names. A future retrained
free-source contract should instead use explicit `*_native`, `*_hpa`, and
`*_kmh` names.

| Feature | Training definition and role | Direct free source | Faithful population requirement | PIT | Artifact reuse |
| --- | --- | --- | --- | --- | :---: |
| `rise_from_7am` | cutoff current temperature minus the row closest to 07:00 within 06:00-08:00; native degree delta; morning heating state | METAR temp; SWOB `air_temp` | retain full same-day rows, convert C to market native, select only admitted rows, preserve source-specific row time | achievable | **retrain** for free source |
| `warming_rate_2h` | cutoff current temperature minus row closest to cutoff-120 min within +/-60 min; native degree delta; recent heating rate | METAR temp; SWOB `air_temp` | same row contract and selection window; missing if no candidate | achievable | **retrain** |
| `hours_at_peak` | hours since first admitted row equal to admitted high-so-far; duration; plateau age | METAR temp; SWOB `air_temp` | compute from one source's rows at its native cadence/precision; never mix sources | achievable | **retrain**; highly cadence/rounding sensitive |
| `dewpoint_c` | latest admitted dew point; native C/F despite name; moisture state | METAR `dewp` C; SWOB `dwpt_temp` C | convert to market native exactly once; select latest admitted row | achievable | **retrain** unless exact WU restored |
| `humidity` | latest admitted relative humidity, percent | SWOB `rel_hum`; no direct live METAR field | use direct SWOB percentage; METAR derivation from temp/dew point is forbidden in this phase | ECCC yes; METAR **no** | **retrain** |
| `pressure` | latest admitted WU pressure; hPa/mb metric or inHg English; synoptic state | METAR `altim` inHg (and optional `slp` hPa); SWOB `altmetr_setng`, `stn_pres`, `mslp` | choose the quantity that overlap evidence proves equivalent to WU `pressure`; do not mix station, altimeter and MSL pressure | achievable as direct observation, but WU equivalence unproved | **retrain** absent exact equivalence |
| `pressure_trend_3h` | current pressure minus closest same-definition pressure at cutoff-180 min within +/-60; same pressure unit | same METAR/SWOB pressure rows; SWOB also has `pres_tend_amt_pst3hrs` | compute from the same selected quantity at both times; direct SWOB tendency is a consistency check, not a silent replacement | achievable | **retrain** |
| `wind_speed_kmh` | latest WU sustained wind; km/h metric, mph English despite name; mixing/flow intensity | METAR `wspd` knots; SWOB `avg_wnd_spd_10m_pst2mts` km/h | convert knots to artifact lane's mph for no-refit comparison or to explicit km/h for retrain; do not pass raw knots | achievable | **retrain** |
| `wind_group` | categorical group from cardinal direction; onshore/regime role | METAR `wdir` degrees/VRB/calm; SWOB `avg_wnd_dir_10m_pst2mts` degrees | map degrees to the same 16-point cardinal buckets; VRB/calm to `Other/variable`; missing if direction unavailable | achievable | **retrain** |
| `cloud_group` | ordered text mapping to precip, fog/haze, clear, partly, overcast, other; radiative/weather regime | METAR weather + cloud layers; SWOB `prsnt_wx_*` + `cld_amt_code_*` | decode official weather/cloud codes, then apply a versioned category mapping; unknown codes stay missing, not `Other` | achievable for known codes | **retrain** |

Public source definitions support these units and roles. Aviation Weather states
that METAR contains wind, weather, sky condition, temperature, dew point, and
altimeter; temperature/dew point are Celsius, wind is normally knots, and the
altimeter is inHg:
<https://aviationweather.gov/help/data/#metars>. The ECCC SWOB guide defines
`stn_pres` in hPa, `air_temp`/`dwpt_temp` in C, `rel_hum` in percent,
two-minute wind in km/h/degrees, and indexed present-weather/cloud fields:
<https://eccc-msc.github.io/open-data/msc-data/obs_station/readme_obs_insitu_swobdatamart_en/>.
The TWC historical contract confirms that English/metric request units change
temperature, altimeter pressure and wind representations:
<https://www.ibm.com/docs/en/environmental-intel-suite?topic=apis-historical-conditions-hourly>.

## 3. Point-in-time contract

Every future normalized observation row must carry:

- `source_family`, station ID, market ID, and target local date;
- `valid_time_utc` and timezone-aware `valid_time_local`;
- `known_at_utc` from the immutable capture/fetch receipt, not file mtime;
- the source field name, source unit, normalized field name/unit, and normalizer
  version; and
- captured payload hash and release/code identity.

Feature selection must follow all of these rules:

1. Use only the source envelope actually captured for that snapshot. Do not
   refetch, backfill, or rebuild the row from a later archive.
2. Require `known_at_utc <= captured_at_utc <= model_emitted_at_utc`. A report
   whose valid time is before the cutoff but which arrived after capture is
   future information and is excluded.
3. Require the target local date and `valid_time_local <= cutoff_hour:00` for
   every printed-path field. The ten-minute near-hour alias is WU settlement
   print semantics only; it must not move a METAR/SWOB observation forward.
4. Do not use a row after the cutoff merely because it exists in the captured
   payload. This specifically blocks the retrospective leak found in `-08-18a`.
5. Use a single observation source for all row-derived values within a feature
   record. Toronto's ordered source is WU, then ECCC SWOB, then METAR; the other
   markets are WU, then METAR. Do not combine a METAR current row with an ECCC
   07:00 or pressure baseline.
6. Reject source envelopes already marked stale/failed. Within an admitted
   envelope, the trajectory lookup windows remain the existing +/-60-minute
   contract; if no row exists, the derived field is missing.
7. A max-since-07:00 summary may continue to protect the observed-high floor
   under its existing trust/quarantine rules, but it may not stand in for the
   row path used by rise, warming rate, peak age, or surface fields.
8. Unknown units, duplicate unit conversion, station mismatch, unparseable
   time, unrecognized categorical code, or missing capture receipt produce
   `None` and an explicit reason. They never trigger a forecast, climatology,
   later observation, or cross-source approximation.

### Cutoff-valid restoration list

- **Exact public WU history:** all ten fields, only when the current-day payload
  was retrieved by capture time and passes exact station/unit/normalization
  parity.
- **METAR:** rise since 07:00, two-hour warming, hours at peak, dew point,
  pressure, three-hour pressure trend, wind speed, wind group, and cloud group,
  subject to the row/receipt rules above.
- **ECCC SWOB (Toronto):** all ten fields, subject to decoding the richer raw
  XML fields and the row/receipt rules above.

### Cannot be restored faithfully in this phase

- METAR relative humidity: the current Aviation Weather live payload contract
  has no direct RH value. Formula-derived RH is an approximation and remains
  missing.
- Any observation first available after the captured snapshot, even when its
  `valid_time` is earlier than the model cutoff.
- Any public-WU current/history value not available at capture time. A later
  public history response is not a substitute for the missing live receipt.
- An unrecognized METAR/ECCC weather or cloud code. Do not coerce it to
  `Other`, because that is a real fitted category rather than a missing marker.
- Any pressure value whose definition/unit cannot be proven against the chosen
  contract. Station pressure, altimeter and mean-sea-level pressure are not
  interchangeable.

## 4. Retrain decision and release sequencing

### Phase R - exact WU regression restoration

This phase may be **no-refit**. It restores the old v1 WU-history row contract
through the public-page-backed client and changes no feature schema, field
order, preprocessing, artifact, or model coefficient. It still requires the
full post-release-#1 gate because the extractor and source topology are
roll-sensitive.

The phase is admissible only if a C-market and F-market receipt proves exact
affected-field equality against artifact-era fixtures and a capture-time test
proves later rows are rejected. If current-day public WU is unavailable or any
unit/value differs, Phase R is blocked rather than widened.

### Phase F - METAR/ECCC free-source contract

This phase is **retrain-required**. It introduces a new, explicitly versioned
observation-row contract. It must keep free observations separate from
`wu_history`; WU rows remain settlement-proxy evidence and may not be fabricated
from METAR/ECCC.

The future implementation should:

1. share the rich METAR/SWOB normalizers between historical training and live
   capture;
2. expose a separately named feature-observation row source with the provenance
   fields in section 3;
3. make both `build_historical_feature_record()` and
   `extract_live_features()` consume that same normalized row schema and field
   formulas;
4. bind the source-contract version and normalizer hashes into the candidate
   release; and
5. leave unavailable direct fields missing, especially METAR humidity.

No free-source field is approved for the old artifacts merely because its
physical meaning is similar. Even dew point and temperature trajectory differ
in station report cadence and precision; peak age is equality/cadence
sensitive; pressure has multiple physical definitions; wind changes units and
averaging periods; cloud/weather categories are provider-specific. An overlap
study may later show one or more differences immaterial, but that evidence
would justify a scoped exception then. It cannot be assumed now.

### Required build acceptance checks

- Unit fixtures for at least one C and one F market, including negative
  temperatures, knots-to-mph/km/h, and inHg/hPa pressure.
- Same raw normalized rows through historical and live builders produce exact
  equality for all ten affected fields, feature order, missingness, and
  categorical encoding.
- Rows one second after the cutoff, rows known one second after capture, wrong
  local dates, stale source envelopes, and mixed stations are rejected.
- Missing METAR RH, unknown cloud/weather codes, and ambiguous pressure remain
  missing with stable reason codes.
- WU, METAR and ECCC rows are never spliced into one `wu_history` sequence and
  never change the trusted observed-high floor authority.
- Release-bound captured replay reproduces probabilities and emitted feature
  records from the same immutable envelopes.
- Fresh post-August-19 full-gate evidence clears total Brier, severe/new-severe,
  protected slices, probability mass, floor invariants, real train/serve
  parity, captured-input replay, and release binding before any roll.

## 5. Median imputation recommendation

**Median imputation should not survive for genuinely absent observation fields
in the next retrained contract, but it must not be changed in Phase R.**

For current artifacts, the imputer is part of the fitted preprocessing
contract. Removing it only at serving would be another train/serve skew. Exact
WU restoration therefore keeps the existing imputer and uses it only when the
original WU field is actually absent.

Phase F/M should be a separate candidate that trains and serves the affected
numeric columns with native NaN, plus explicit source-availability/provenance
signals where useful. HGB can learn missing branches only when NaNs reach both
fit and predict. Wind/cloud require a distinct treatment because current
one-hot encoding turns missing into an all-zero vector; use an explicit
`Missing` category or availability indicator on both sides and retrain.

This change needs its own ablation: free-source restoration with the current
imputer versus the same restoration with native missingness. It cannot ride on
the restoration result, because changing missing routing can move predictions
even where no field is restored.

## 6. Would the release parity gate catch this?

### What would have happened with a real receipt

Yes. Feeding the same synthetic WU-era row set to the historical builder and
the post-`5735b573` live builder would yield ten populated training fields and
ten null/all-zero serving fields. `predictor_fields_equal` would be false, and
the gate would block.

### What the implemented gate actually does

[`evaluate_train_serve_parity_gate()`](../../src/weather/reporting/validation/floor_retrain_gate_harness.py#L1079)
requires a payload with `status=PASS` and eleven booleans such as
`predictor_fields_equal`, `feature_order_equal`, `imputation_equal`, and
`native_nan_equal`. No repository producer computes those booleans from
feature rows. The only complete payloads are test fixtures; real scorecards
therefore report `NOT_EVALUABLE`.

The existing captured-input parity system is a different proof. It rebuilds a
release prediction from captured inputs and compares it with the served
prediction. If live and replay both execute the same blind extractor, exact
parity is expected. Release graph binding likewise proves identity, not
training-feature semantics.

### Required gate repair

Before either future phase can qualify, add a release-bound producer that:

1. reads the active artifact's exact feature names, order, imputer statistics,
   native-NaN list, categorical levels, and source-contract version;
2. runs a shared set of immutable C/F point-in-time raw observation fixtures
   through the historical and live builders;
3. compares every preprocessed predictor value, null mask, one-hot value,
   decoded native output, and floor-control field;
4. includes an explicit empty-WU/healthy-METAR-or-ECCC fixture so the original
   regression cannot hide behind two equally blind production paths;
5. compares fresh serving missingness/source/unit distributions with the
   artifact-bound training reference by feature and market; and
6. writes a self-hashed, release/manifest/code/source-bound receipt whose
   per-field counts support the summary booleans.

The gate must reject hand-authored summary booleans without those row-level
hashes and counts. Until that producer is required, **recurrence detection is a
named release-gate gap, even after release #1 exists**.

## 7. Doubts and limits on the 51.40% number

The prior calculation is reproducible as the stated strict centre-oracle result
on its frozen excluded population. This specification found no new arithmetic
error. It did find reasons not to call 51.40% a feature-repair ceiling without
qualification:

1. It is an oracle for a **correction class**, not an identified causal effect
   of the ten blind fields. It supplies the contemporaneous market expected
   centre, which METAR/ECCC does not reveal.
2. It uses hindsight to apply the correction only when positive-excess Brier
   improves. A deployable repair must act before the winner is known.
3. It holds served entropy/support fixed where feasible. A real retrain can
   change centre, width, skew, support and calibration together, so 51.40% is
   not a mathematical upper bound on every possible model repair.
4. Conversely, attributing every oracle-correctable centre error to blindness
   greatly overstates expected recovery. `-08-20a` found that the actual
   imputer/all-zero routing effect was small and slightly warm on average, while
   the observed displacement was cooler. Blindness and centre displacement are
   not yet a demonstrated single mechanism.
5. The report's 51.40% denominator is excluded-lane positive excess. The later
   statement that this lane holds 81.21% of "remaining" loss uses a different
   post-gate denominator than `-08-20a`'s 69.42% share of the incumbent held
   lane. The roughly 42% project-wide translation is valid only if that 81.21%
   denominator is retained and documented; the percentages must not be
   multiplied across unlike baselines.
6. Free-source substitution changes measurement distributions. Even perfect
   point-in-time coverage does not grant the WU-trained trees the oracle's
   centre, so the no-refit interpretation would be especially optimistic.

The safe statement is: **51.40% proves that excluded-lane centre correction is
material enough to test; it does not bound or forecast lift from this contract
repair.**

## Handback

- Regression and never-implemented work are cleanly separated above.
- The point-in-time restorable and cannot-restore lists are explicit.
- Complete METAR/ECCC repair: **retrain required**. Exact public-WU history
  restoration: **no refit conditionally allowed**, subject to exact parity and
  current-day availability proof.
- A real parity receipt would catch the skew; the current boolean-only receipt
  gate and captured-input replay will not. This is a release-gate gap.
- The 51.40% result remains a centre-oracle diagnostic, not a causal repair
  ceiling or expected gain.

`-08-16a` remains queued for 2026-08-05 04:30. No release, pointer, promotion,
capture, scheduler, mirror, ACL, paid-provider, or production-host state
changed.

## Static evidence identities

| Evidence | Identity |
| --- | --- |
| Base | `6a068783a8ba6abcb1286e408da07d1b0f7e70d6` |
| Regression commit | `5735b573aa284da070fba9b751d3a48f5819aca4` |
| Partial fallback commit | `2a878d918cc7a3ef0b70950d4fa404650e6e507f` |
| Prior direct-path result | 28,680 / 28,680 affected cells; evidence hash `0930dd914150b061936692b4356b5b20e7950cf3d1962e7f41cbdbe0b075d7b5` |
| Prior strict oracle | 51.40%; evidence hash `76ac1a8481ce34cd440e5bf589e4bc54eaec12bcd05d94e23af93ca890bafa13` |
