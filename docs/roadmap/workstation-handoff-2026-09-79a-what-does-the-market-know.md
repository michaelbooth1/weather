# Workstation handoff 2026-09-79a — what does the market know that we don't?

Host: the 32 GB workstation (non-capture). Issued by the production operations agent, 2026-09-21.
Owner decision 2026-09-21: **model work is unpaused.** `2026-09-79a` is a mission label, not a calendar date.

`ARCHIVE_DIR` = the workstation folder holding `mi-core.tgz`, `mi-tape.tgz`, `mi-books-sample.tgz` and `MANIFEST.json`. They were staged on the production host 2026-09-21 02:37 (433 MB, SHA-256 in the manifest). The copy the owner pastes says how the mission obtains them; where the two copies differ, the pasted copy wins.

## 1. Goal

Say, with measured support, **which kind of information accounts for the served forecast's gap to the market** —
intraday settlement-station observations, station guidance we hold but do not use, regime days, or something we cannot
obtain — by running five pre-specified descriptive checks on the post-boundary served surface.

## 2. Start from this — do not re-derive it

Read `AGENTS.md`, `docs/operations/STATE_OF_PLAY.md`, `docs/operations/FINDINGS_DIGEST.md`, then only the EF sections cited here.

- The gap is 98.88% resolution; recalibration ≤ 16.494% of it (EF §1c). 4.387% of band rows carry 64.140% of excess loss;
  that tail is confident-wrong-centre and predictable ex ante, AUROC 0.90260 (EF §1f, §1g). On |model − market| ≥ 0.30
  rows, market replacement closes 85.6% (EF §1c). Repairing 9 blind features moved nothing (EF §4).
- Since 2026-06-30 `wu_history`, `wu_current`, `weather_forecast` are empty in every capture; by code trace 13 of ~26
  serving stages, including all five late-day lock-ins, are no-ops (EF §10e, not confirmed from served output).
- The venue settles on `weather.gov/wrh/timeseries?site=<icao>` since ~2026-08-23; nothing in `src/` reads it (EF §10c).
- Station guidance is **captured**: `features_long.csv` has `nbm_prob_tmax_p10..p90`, `nws_grid_high`,
  `open_meteo_hrrr_high_delta`; `snapshots_long.csv` has `nws_forecast_max_c`, `open_meteo_max_c`, `station_current_c`,
  `station_max_since_7am_c`. One Atlanta day: NBM filled on 71 of 179 snapshots, the others on 179 of 179. Item 190 says
  the active artifact selects zero NBM columns.
- Public execution tape: taker fee 0; maker markout +0.19 c at 5 min, −0.43 c to settlement (digest, market making).
- `docs/operations/reserved-confirmation-window.md` read **NONE RESERVED** at issue. Re-read its status line before
  opening any data; if it has changed, it wins.
- The production host's `data/metar` store stops at 2026-06-30. METAR and SPECI for August–September are **not** in the
  archives; fetch them from the free IEM ASOS archive (12 stations: CYYZ KATL KAUS KBKF KDAL KHOU KLAX KLGA KMIA KORD
  KSEA KSFO), ≥ 1 s between requests, keep a URL + SHA-256 manifest. Verify the endpoint at run time.
- Full method, reading rules and traps: `docs/research/missing-information-test-plan-2026-09-21.md` on this branch
  (companion review: `docs/research/missing-information-review-2026-09-21.md`). The reading rules there are **frozen**;
  do not edit them after you have seen a result. If one is unworkable, say so in the report and show both readings.

## 3. Data you were given

Three archives staged from the production host's `data/snapshots/`, 600 closed event folders, target dates 2026-08-01 ..
2026-09-19, layout `<event-folder>/<file>`:

| Archive | Contents |
| --- | --- |
| `mi-core.tgz` | `snapshots_long.csv`, `features_long.csv`, `settlement.json`, `observation_payloads_long.csv` per folder |
| `mi-tape.tgz` | `execution_tape/` per folder (public trade tape, from ~2026-08-14) |
| `mi-books-sample.tgz` | `order_books_summary.csv` for all markets on 08-15, 08-18, 08-20, 08-22, 08-23, 08-30, 09-06, 09-13 (sample fixed before any result) |

Verify every SHA-256 against `MANIFEST.json` before use and quote them in the report. Unpack to a scratch folder
**outside** the repository's `data/`, outside the workstation mirror and outside `D:\weather-mirror`. Your own `data/`
is frozen at 2026-08-12 and must not be used or written for this mission.

## 4. Work, cheapest falsifying test first

Population: folders whose `settlement.json` has `promotion_countable == true`; print the count and the excluded list.
Two strata, split at target date 2026-08-23; never pool with the pre-boundary B/C panel. Aggregate to market-day (× hour)
cells before any average. Every interval: crossed date × market bootstrap, 2,000 draws; report n, power and MDE for every
comparison. Market probability = raw `market_yes`; sensitivity = renormalised within snapshot. Commit the plan file's
SHA-256 into your output header **before** the first full run.

- **P0 — extraction + Check 1 (where in the day is the gap).** One per-snapshot table (market, date, local time, bands,
  p_model, p_market, winner, station fields, guidance fields, settlement high). Then Brier model / market / excess by local
  hour, by hours from the realised peak, and the information lag L. *This can falsify the whole intraday story on day one.*
- **P1 — Check 2 (distance and instrument).** Mode-band distances on all / disagreement / loss-tail snapshots;
  model mass below our own running max; histogram of `settlement_high` − our final running max in whole settlement degrees,
  per market, per stratum.
- **P2 — Check 4 (guidance alone vs market).** 4a: band probabilities from the NBM percentiles (raw, and with the observed
  floor), and from NWS / Open-Meteo / HRRR point highs with an error kernel fitted on **earlier dates only**; Brier against
  market and `final_model` on identical snapshots by time bucket; report NBM fill by market, hour, date first.
  4b: trace one snapshot's NBM value into the served model's input row and read the active artifact's feature list
  (a trace, not a grep). 4c (IEM guidance archive download) only if 4a is promising or fill is too thin.
- **P3 — Check 5 (what kind of day is a tail day).** Tag tail vs non-tail market-days: hour of max (non-diurnal day),
  low ceiling, wind shift, thunder, front proxy, coastal stratus, the MRMS / marine / disagreement features, and
  guidance bust (|settlement high − 08:00-local NWS high| ≥ 3 °F). Odds ratios with crossed intervals; unpowered tags are
  reported as unpowered, not as nulls.
- **P4 — Check 3 (which clock the market trades on).** Skip the order-book sample if P0 shows the gap already full-size
  at 06–10 local. Otherwise: SPECI event study (−15..+15 min signed move toward the winner), pre-METAR lead test,
  minute-of-hour histograms against a uniform null, and our own latency (`first_seen_at − provider_observed_at`; minutes
  from a ≥ 3 c mid move to our next snapshot). Reuse the tape reader in the merged `execution_tape_markout` tool.

Put code under `tools/research/missing_information/` with focused tests for the band-probability builder, the peak-time
rule and the bootstrap. Heavy commands go through `scripts/ops/workstation_heavy.ps1`.

## 5. Boundaries

`docs/operations/DELEGATION_CONTRACT.md` §2 binds this mission in full. In particular and in addition:

- Descriptive only. **No model fit, no candidate, no α row, no serving or config change, no mapping scored without a
  past-dates-only fit.** A result that suggests a candidate ends in a proposed pre-registration, not in a candidate.
- Shrinking toward or consuming the market is a measurement, never an improvement (EF §1c).
- Free public sources only (NOAA, NWS, IEM, ECCC, free-tier Open-Meteo). No paid provider, no credentials, no exchange
  calls, no live or authenticated Polymarket access of any kind.
- Never weaken the observed-high floor; never relax a gate; never read `.weathersync.cred` or any credential file.
- Files you own: `tools/research/missing_information/**`, `tests/**/test_missing_information*`, your report, and your own
  scratch. If you need any other file, report the need instead of taking it.
- Commit and push your branch freely; never merge to `master`.

## 6. What would falsify this mission

- Check 1: the ratio is already ≥ 1.30 at 06–10 local and does not rise through the afternoon ⇒ the intraday-observation
  story (the issuer's first-ranked candidate) is wrong as the main cause.
- Check 2: the instrument histogram is zero on ~every market-day ⇒ the rounding/precision branch is dead.
- Check 4a: NBM(+floor) is as far from the market as `final_model` ⇒ "guidance we hold and don't use" is wrong; the
  market has more than public guidance.
- Check 5: tail days carry no tag at a detectable odds ratio ⇒ regime data is not worth its GRIB cost.
- Check 3: mid moves lead both METAR and SPECI ⇒ part of the gap is a faster private feed and is **not closable** under
  the free-sources rule. Say so plainly.
- Any check whose MDE exceeds the largest plausible effect ⇒ report it as unpowered; do not read the point estimate.

## 7. Branch and report

- Branch: `codex/missing-information-checks-20260921` (branch from `origin/codex/missing-information-handoff-20260921`).
- Report: `docs/roadmap/agent-report-2026-09-79a-workstation-what-does-the-market-know.md`, per contract §5 — verdict
  first in bold; measured values with date clusters, market clusters, market-days and interval treatment; per-file roll
  verdict (expected: all new files outside every capture closure — confirm, do not assume); what was NOT done; exact
  reproduction commands using paths that exist on the workstation; commit hash and branch.
- Also deliver one page, `docs/research/missing-information-results-2026-09-79a.md`: for each of the six candidates in the
  review, "supported / not supported / unpowered", and the single next step you would pre-register.
