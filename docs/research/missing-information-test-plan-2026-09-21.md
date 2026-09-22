# Test plan — the five checks on "what does the market know that we don't" (local plan, 2026-09-21)

Owner decision 2026-09-21 00:05: **model work is unpaused.** (Wrap must record this in STATE_OF_PLAY, the digest's
"owner decisions in force" line and EF §10e's "do not act" note.) Companion: `missing-information-review-2026-09-21.md`. Executed by workstation handoff `2026-09-79a`.

## 0. Correction to the review before anything runs

`features_long.csv` already carries `nbm_prob_tmax_p10..p90`, `nws_grid_high`, `open_meteo_hrrr_high_delta`, MRMS and
marine columns, and `snapshots_long.csv` carries `nws_forecast_max_c`, `open_meteo_max_c`, `station_current_c`,
`station_max_since_7am_c`. So station guidance is **captured**, not missing (one Atlanta day: NBM percentiles filled on
71 of 179 snapshots; NWS grid and HRRR delta on 179 of 179). Item 190 says the active artifact selects zero NBM columns.
The question for candidate B is therefore "we hold it and do not use it", which is cheaper to test and to fix than
"we lack it". Check 4 is redesigned around that.

## 1. Population, data, rules (common to all five)

- **Population:** closed event folders under `data/snapshots/highest-temperature-in-<city>-on-<date>/`, target dates
  2026-08-01 .. 2026-09-19, `settlement.json.promotion_countable == true`. This is the post-boundary **served** surface.
  Never pooled with the pre-boundary B/C panel (that export lives on the workstation). Report two strata: before and
  after the 2026-08-23 resolution-source switch. Expect about 12 × 50 = 600 market-days, fewer after the countable filter;
  print the count and the excluded list (unsettled dates leave silently otherwise — EF §10d).
- **Inputs per folder:** `snapshots_long.csv` (~1.8 MB: per band `model_probability`, `market_yes`, `best_bid`,
  `best_ask`, `captured_at_local`, station fields), `features_long.csv` (~0.3 MB), `settlement.json` (winner, high, unit).
  Check 3 adds the execution tape and a sample of `order_books_summary.csv`.
- **One extraction pass** `mi_extract.js` (node, streaming, one file open at a time, below-normal priority): writes
  `C:\tmp\mi\snapshots.jsonl` — one row per snapshot: market, date, local time, cutoff_hour, bands[], p_model[], p_mkt[],
  winner index, station_current, station_max_so_far, nws/open-meteo/NBM fields, settlement_high. About 1.2 GB read once,
  ~150 MB written. Everything in checks 1, 2, 4a, 5 then runs off that file in seconds.
- **Host rules:** bulk scan ⇒ 00:30–09:00, under the `workload_admission.ps1` lease, serial with everything else, not
  across 04:45–06:45, never open today's or tomorrow's live folders, track the PID and kill on exit. No pytest involved.
- **Statistics:** aggregate to market-day (× hour) cells first, then crossed date × market bootstrap, 2,000 draws, for
  every interval; report n, power/MDE where a comparison is made. Market probability = raw `market_yes`; sensitivity =
  renormalised to sum 1 within snapshot. These are descriptive localisations: **no α row, no candidate, no serving
  change**, and no fitted mapping is scored without an expanding-window (past dates only) fit.
- **Freeze before reading:** commit this file's reading rules (sections below) with a SHA-256 in the output header
  before the first result is looked at. Results go to `docs/research/` + digest as measured findings, whatever they say.

## 2. Check 1 — where in the day is the gap?

- **Compute** per snapshot Brier_model, Brier_mkt, excess = difference. Cell = market-day × local hour (mean of snapshots).
- **Tables:** (a) by local hour 00–23: n market-days, both Briers, excess, ratio, share of total summed excess;
  (b) by hours relative to the realised peak (first time `station_max_since_7am_c` reaches its final value): bins
  ≤−6, −6..−3, −3..−1, −1..0, 0..+1, +1..+3, >+3; (c) **information lag**: for each hour h, the smallest L ≥ 0 with
  Brier_model(h+L) ≤ Brier_mkt(h), per market-day, median and IQR — "the market knows at 13:00 what we know at 13:00+L".
- **Reading rule (frozen):** ≥ 60% of summed excess at local hour ≥ 12 **and** ratio rising from the 06–10 bucket to the
  13–17 bucket ⇒ intraday observation or latency (A/F). Ratio in 06–10 already ≥ 1.30 ⇒ pre-day guidance or training
  population (B/D) carries a material part. Report both shares; they are not exclusive.
- **Trap:** snapshot cadence is event-triggered, so hours with more triggers must not get more weight — hence the cell mean.

## 3. Check 2 — how far apart are we and the market, and is it the instrument?

- **Sets:** (i) all snapshots; (ii) disagreement set, max_band |p_model − p_mkt| ≥ 0.30 (EF §1c's gate); (iii) loss tail:
  snapshots ranked by excess, the top group carrying 64% of summed excess.
- **Per snapshot:** mode band of model m, of market k, winner w; distances |m−k|, |m−w|, |k−w| in band steps; sign of
  (m−k) (are we cooler?); whether the snapshot is before or after the realised peak.
- **Impossible-mass test:** model mass on bands strictly below the running max from our own station feed, against the
  market's mass on the same bands. Non-trivial model mass there = a floor failure we can see without any new data.
- **Instrument test (the direct test of candidate A):** per market-day, `settlement_high` minus our final
  `station_max_since_7am_c` converted to the settlement unit and rounded by the market's rule. Histogram in whole
  degrees, by market, by stratum (WU era / weather.gov era). Also the same at the last snapshot before 18:00 local.
- **Reading rule:** in set (iii), |m−k| = 1 on ≥ 70% of snapshots **and** the instrument histogram is off zero on ≥ 10%
  of market-days ⇒ precision/rounding of the settlement reading is a real part (A). |m−k| ≥ 2 on ≥ 40% and mostly
  before the peak ⇒ centre/guidance/regime (B/C). Instrument histogram ~all zero ⇒ drop the rounding story, keep cadence.

## 4. Check 3 — which clock does the market trade on?

- **Data:** execution tape trades for all 30+ captured dates (small; reuse the reader in the merged
  `execution_tape_markout` tool rather than re-parsing), plus `order_books_summary.csv` midpoints for a fixed sample
  chosen before looking: 12 markets × 8 dates (4 per stratum, dates = the 1st, 8th, 15th, 22nd available) ≈ 4.6 GB streamed.
- **Observation clock per station:** routine METAR timestamps and SPECI timestamps from `data/metar/<icao>/raw`; 5-minute
  marks; our own `observation_payloads_long.csv` `provider_observed_at`, `first_seen_at`.
- **Measures, 10:00–18:00 local only:** (a) minute-of-hour histogram of trade count and of |Δmid| on the top two bands,
  against a uniform null; (b) **informative move** = Δmid toward the eventual winner, share falling within
  [t_obs, t_obs+3 min] versus its time share; (c) SPECI event study: mean signed move in −15..+15 min around each SPECI —
  SPECIs are irregular, so this is free of bots' round-minute habits; (d) lead test: does the mid move toward the next
  METAR's temperature change in the 10 minutes **before** it is issued; (e) our latency: `first_seen_at − provider_observed_at`,
  and minutes from a ≥ 3c mid move to our next snapshot.
- **Reading rule:** spike at the routine METAR minute and after SPECIs ⇒ market reads METAR, we can match it; spike on a
  5-minute lattice ⇒ it reads the 5-minute feed — adopt `api.weather.gov` observations; significant movement before both ⇒
  someone holds a faster feed we cannot buy, and that part of the gap is permanent; no clock structure ⇒ not observation-driven.
- **Trap:** minute-of-hour structure alone can be bots; only (c) and (d) identify information.

## 5. Check 4 — is station guidance alone as good as the market? (and do we use what we hold?)

- **4a, local, no download.** On snapshots where NBM percentiles are present (report the fill rate by market, hour and
  date first — 40% in the one sample): build band probabilities from a piecewise-linear CDF through p10/p25/p50/p75/p90
  with normal tails from mean/stddev, in the settlement unit with the market's rounding. Variants: NBM raw; NBM + observed
  floor (mass below the running max zeroed, renormalised); `nws_forecast_max_c`, `open_meteo_max_c` and HRRR
  (forecast_high + hrrr delta) as point forecasts with an error kernel fitted on **earlier dates only**, per market.
  Score Brier of each against market and against `final_model` on identical snapshots, by bucket (≤10, 10–13, 13–17, >17 local).
- **4b, artifact trace.** Read the active artifact's feature list and permutation importances: are the NBM / NWS grid /
  HRRR columns selected, and what happens to them on the 60% of snapshots where NBM is empty (imputed? dropped?).
  A trace, not a grep: follow one snapshot's NBM value into the model input row.
- **4c, download, only if 4a is promising or fill is too thin.** IEM archive of station text guidance (NBS/NBP, LAV, MAV)
  by station and run time, 11 US stations, 2026-05-10 → now, one request per station-model, ≥ 1 s apart, to
  `data/research/iem_guidance/` with a manifest of URLs and hashes. Verify the endpoint and parameters at run time
  (do not trust my recollection of the URL). Light network work, not a heavy job; still keep it out of 12:00–18:00.
  This is also the point-in-time corpus the retrain lacked, so keep run-time stamps intact and never stitch runs.
- **Reading rule:** NBM(+floor) morning Brier ≤ 1.10 × market ⇒ the pre-day gap is station guidance we hold and do not
  use; next step is a pre-registered candidate that centres on it (that *is* an α decision — not in this plan).
  NBM ≈ our model, both ≫ market ⇒ the market has more than guidance; weight moves to A, C, E.

## 6. Check 5 — what kind of day is a tail day?

- **Tail:** market-days ranked by summed excess loss; top group carrying 64%. Comparison: all other market-days.
- **Tags from held data** (`data/metar/<icao>/hourly`, `features_long.csv`, `settlement.json`): hour of the realised max
  (**non-diurnal day** = max before 11:00 or after 18:00 local, the midnight-high case); ceiling BKN/OVC < 5,000 ft during
  10–16 local; wind shift ≥ 90° in 3 h; thunder/showers reported; front proxy (wind shift + dewpoint drop ≥ 3 °C + pressure
  rise); coastal-stratus morning (coastal markets); `mrms_convective_interruption`, `marine_layer_suppression`,
  `forecast_disagreement`, ensemble spread; **guidance bust** = |settlement_high − nws_forecast_max at 08:00 local| ≥ 3 °F.
- **Output:** per tag, tail rate vs non-tail rate, odds ratio, crossed-bootstrap interval, n. Expect ~60 tail market-days,
  so state the MDE; tags that need more days are reported as unpowered, not as nulls.
- **Reading rule:** tail days are mostly guidance-bust days ⇒ nobody knew pre-day, so the market's advantage there is
  intraday observation (A), and C is a way to see the bust coming; tail days are not guidance busts ⇒ the public
  guidance was right and we were wrong (B/D). A dominant single tag (non-diurnal max, stratum) names the first feature to build.

## 7. Order, time, outputs

| Step | When | Cost |
| --- | --- | --- |
| Write `mi_extract.js`, `mi_check1/2/4a/5.js`; dry-run on one closed Atlanta folder | daytime 09-21 (single small folder, not a bulk scan) | minutes |
| Freeze reading rules (hash) | before the first full run | — |
| Extraction pass + checks 1, 2, 4a, 5 | night 09-21→22, first job after the 00:33 health check, under the lease | ~20–30 min |
| 4b artifact trace | daytime 09-22 | reading only |
| Check 3 (tape + sampled books) | night 09-22→23 | ~30–40 min |
| 4c IEM download, if called for | 09-22 evening-free hours | light |
| Write-up: one research doc, digest + EF entries, item for the follow-on candidate | morning 09-23 | — |

Not tonight: the 09-21 window is committed to the host suite, the guarded merge, five backfills and the wrap. If the
backfills end before 07:30 the extraction pass may start then, and must end by 08:05.

What would change the plan: check 1 showing the gap is already full-size at 06–10 local makes check 3 low value (skip
the 4.6 GB book sample); check 2's instrument histogram all zero removes the rounding branch of A.
