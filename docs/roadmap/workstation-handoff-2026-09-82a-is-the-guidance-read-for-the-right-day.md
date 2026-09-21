# Workstation handoff 2026-09-82a — is the NBM guidance read for the right day?

Host: the 32 GB workstation (non-capture). Issued by the production operations agent, 2026-09-21.
Follows mission `2026-09-81a`, whose handback is accepted: NO-GO for a confirmation this season. `2026-09-82a` is a mission label.

## 1. Goal

81a found that **more than half of the US morning snapshots, and nearly every snapshot after 10:00 local, had NBM
percentile values thrown away as "impossible against the observed floor"**. A correct forecast of today's maximum should
not be refuted by the morning's temperatures about nine times in ten at 09:00 local. Decide, with real bulletins, whether the values we
discard are (a) a correct forecast of today's maximum that the day has already beaten, or (b) a value for the wrong
period — a night minimum or another day's maximum. If (b), build the fix. **No candidate is scored in this mission.**

## 2. Start from this — do not re-derive it

Read `AGENTS.md`, `docs/operations/STATE_OF_PLAY.md`, `docs/operations/FINDINGS_DIGEST.md`, then the 81a report on this
branch (`docs/roadmap/agent-report-2026-09-81a-workstation-morning-guidance-candidate.md`, P0 section and its evidence).

- 81a census of the 79a export: US 06:00–09:59, 13,584 snapshots, 6,293 with a complete valid NBM set, 7,290 with an
  explicit floor-dropped field; US 10:00–12:59, 17 complete of 10,707, 16 of those 17 with no captured floor. All-market
  fill by local hour: 72.7% at 06, 60.2% at 07, ~33% at 08, ~6–7% at 09, ~0 afterwards. The few after-10:00 rows score
  0.16–0.18 Brier (79a), i.e. nearly all mass on a wrong band — not what a right-day forecast without a floor does.
- The slot choice is `_slot_index_for_target` in `src/weather/sources/nbm_probabilistic_tmax.py`: for each `FHR` group it
  takes the **first** token, adds it to the issue time, subtracts one day, and accepts the first group whose date equals
  the target. `parse_nbp_station_tmax` then reads `TXNP1..TXNP9`, `TXNMN`, `TXNSD` at that group's first token.
  **Hypothesis to test, not a finding:** in an NBP bulletin the `TXN` rows alternate 12-hour maximum and minimum periods,
  and which of the two comes first in a group depends on the cycle hour. If so, for some cycles the first token whose
  "valid time minus one day" equals the target date is a **night minimum**, and its percentiles land below the observed
  floor and are dropped. The 120-minute cache and the current-to-24-hour-old cycle search decide which cycle a snapshot got.
- The feature builder (`src/weather/model/model_features.py`, the `nbm_probabilistic_tmax` block) drops each value that is
  below the floor by more than the tolerance, but still writes `nbm_prob_tmax_stddev`, `nbm_prob_tmax_iqr` and
  `nbm_prob_tmax_p10_p90_spread` from the payload. So where p75 and p90 survived, the export lets you recover
  `p25 = p75 − iqr` and `p10 = p90 − spread` exactly. Use this for diagnosis only.
- The export has no payload bytes, issue times or chosen slots. NOAA publishes NBP text bulletins free (the same public
  source the collector uses, and the public NBM archive bucket for past cycles). Fetching them on the workstation is
  allowed: it is a free public source and no production data.

## 3. Work, in this order

- **T0 — the convention, from real bulletins.** Fetch NBP bulletins for at least four cycle hours spread over a day
  (for example 01Z, 07Z, 13Z, 19Z) on three recent dates, keep the station blocks for the 11 US settlement stations, and
  record for each: the `FHR` row, the UTC valid time of every token, and whether each `TXN` token is a maximum or a
  minimum **according to NOAA's published NBP product description** (cite it; do not infer it from magnitudes alone — then
  confirm with magnitudes against the day's observed max and min). State the rule in one paragraph.
- **T1 — what our parser picks.** Run `parse_nbp_station_tmax` unchanged on every block from T0 for target = the local
  date, local date + 1, and local date − 1. Table: cycle hour x station -> chosen group, its valid time, maximum or
  minimum per T0, the p50 it returned, and the observed daily max and min for that date (IEM ASOS or the NWS
  timeseries, free). Count right-period and wrong-period picks by cycle hour.
- **T2 — does it explain the export.** Using the recovered quantiles (section 2) on the 79a export, compare dropped-row
  p50 with that market-day's settled maximum and with a typical night minimum. If wrong-period picks explain the drops,
  the dropped p50 sits near the minimum, far below the maximum; if the day merely beat a correct forecast, it sits within
  a few degrees of the maximum. Report the distribution by local hour and market with n, date and market clusters. This is
  a census of a diagnostic, not a score: **no Brier, no comparison with served or market, on any row.**
- **T3 — only if T0–T2 show a wrong-period pick: the fix**, on a separate branch from `origin/master`
  (`codex/nbm-target-fix-20260921`): select the group and token that NOAA's description says is the daytime maximum for
  the target local date; record in the payload the issue time, the chosen token's valid time, its period kind, and keep
  the raw percentiles, mean and rejection reasons beside the filtered features (new diagnostic fields only — do not change
  the meaning of an existing feature column). Tests from the T0 bulletins as fixtures (small station blocks, not national
  files). State which active artifacts select any `nbm_prob_tmax_*` column (`artifacts/`, read-only): if none does, say the
  fix changes captured evidence only; if one does, stop and report — that is a train/serve parity change needing its own
  mission. Never weaken or bypass the observed-high floor.
- **T4 — if T0–T2 show the picks are right**, say so plainly: the drops are a correct forecast already beaten, the 81a
  selection reading stands, and the only proposal is to retain raw values and provenance (the T3 diagnostic fields
  alone, same branch name, no slot change).

## 4. Boundaries

`docs/operations/DELEGATION_CONTRACT.md` §2 binds this mission in full. In addition:

- 81a's rule still holds: **no new forecast candidate is proposed or scored from these dates.** A better parser is a
  capture repair, not a candidate; whether guidance then helps is a later pre-registered question on later dates.
- Research files: `tools/research/nbm_target_trace/**`, `tests/**/test_nbm_target_trace*`, your report. Fix branch only:
  `src/weather/sources/nbm_probabilistic_tmax.py`, the `nbm_probabilistic_tmax` block of
  `src/weather/model/model_features.py` for added diagnostic fields, their tests and fixtures, and the owning docs for any
  new field. Nothing else under `src/`, `config/` or `artifacts/`.
- Free public sources only. No credentials, no exchange calls, no live or authenticated Polymarket access. Never read
  `.weathersync.cred` or any credential file. Be polite to NOAA: serial requests, cache every file, no national-file
  refetch.
- Heavy commands through `scripts/ops/workstation_heavy.ps1`. Commit and push your branches freely; never merge to
  `master`. The production host lands the fix in a quiet window after its own verdict and suite.

## 5. What would falsify the hypothesis

- NOAA's description and the magnitudes agree that the first token of every matching group is the daytime maximum at all
  cycle hours => the parser is right; go to T4.
- Wrong-period picks occur only at cycle hours the collector never uses for a morning snapshot (show which cycles the
  cache and search order can deliver at each local hour) => it does not explain the export; say what does.
- Recovered dropped p50 values sit within a few degrees of the settled maximum => the days simply ran warm.

## 6. Branch and report

- Research branch: `codex/nbm-target-trace-20260921`, from `origin/codex/nbm-target-trace-handoff-20260921`.
  Fix branch (T3 or T4 only): `codex/nbm-target-fix-20260921`, from `origin/master`.
- Report: `docs/roadmap/agent-report-2026-09-82a-workstation-is-the-guidance-read-for-the-right-day.md`, per contract §5 —
  verdict first in bold (WRONG-PERIOD PICKS / PARSER RIGHT / UNDECIDED and why); the T1 table; measured values with full
  support; per-file roll verdict for each branch (run the tool; the production host re-runs it); what was NOT done;
  reproduction commands with workstation paths.
