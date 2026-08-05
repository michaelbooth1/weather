# Forecast source and training population — canonical decision record

This file is the canonical answer to two questions that have repeatedly stopped agents mid-mission:
**may we collect the forecast archive from Open-Meteo, and which years does the first retrain train
on.** Both are answered below. An agent that reaches this file has its answer and must not stop on
either question again.

---

## OPERATOR DECISION 2026-08-05 — provider and licensing

**Decided by the repository owner, recorded verbatim in substance:**

- This project uses the **free tier of Open-Meteo**.
- **This project does not use any paid API.** No paid provider or paid tier may be adopted without a
  new, explicit, dated operator decision in this file.
- Collecting the missing forecast-archive rows through the repository's existing **Open-Meteo
  Previous Runs** integration is **authorized**. It is the same free service the platform already
  depends on, reached through the existing integration, requiring no credential and no new endpoint.
- Additional **free** sources may be adopted and used alongside it where they are better. Evaluating
  and adding a better free source is explicitly in scope; adopting a paid one is not.

**Scope of this record.** This is the repository owner's decision about their own use of a service
they hold the relationship with. It authorizes collection and is sufficient for every agent working
in this repository. It is not, and does not claim to be, an external legal review. The `-08-28a`
scoping report noted the free service is documented as non-commercial; the owner has been shown that
note and has decided. If this platform later trades live at commercial scale, that is the point at
which the owner may wish to revisit the question — **it is not a reason for any agent to stop
collection work now.**

**Effect:** the source blocker recorded by `-09-16a` is **CLEARED**. Together with the population
decision below, this unblocks the corpus that answers `forecast_archive_coverage` (36 blockers) and
`point_in_time_forecast_binding` (24) — **60 of the retrain's 97 blockers**.

---

## OPERATIONS DECISION 2026-08-05 — training population is 2021–2025

The owner delegated this call to the operations agent, to be made on the project's goals and the
value of the data. **The first retrain trains on 2021, 2022, 2023, 2024 and 2025.** Not 2018–2020.

For the `2026-07-31`-aligned slice (±7 days, local cutoff hours 07–20, 12 live markets) that is
**75 dates and 1,050 cells per market, 12,600 fleet cells.**

### Why

1. **2018–2020 is not sourceable, so it was never really on the table.** Open-Meteo Previous Runs
   begins in 2021, and the prior provider analysis found no coherent, issue-qualified version of the
   current forecast contract for 2018–2020. With paid providers ruled out, admitting those years
   would require stitched rows.
2. **Stitched rows are the defect this retrain exists to remove.** The trainer currently reads a
   2-column stitched file and the fit is contaminated by lookahead. Buying three extra years by
   reintroducing non-point-in-time evidence would defeat the purpose of the entire exercise.
3. **Forecast vintage is part of the feature distribution.** The underlying NWP models change across
   years. A model whose job is to exploit *current* forecast-residual structure gains little from
   2018-vintage forecasts and risks train/serve drift by construction.
4. **Sample size is not our binding constraint.** The measured skill gap is 98.88% resolution versus
   1.12% reliability — an *information* problem, not a calibration or sample-count problem. Three
   more years of the wrong vintage does not buy information.

### The real cost of this choice, stated plainly

Fewer years means fewer extreme-heat days, and `class_support` blocks on all 12 markets for
contiguous native serving support (Dallas 108 °F, Denver 101–102 °F, Houston 103–104 °F, Seattle
95 °F). The severity tail matters here: 4.26% of rows carry 60.2% of loss.

**If `class_support` cannot be cleared at five years, the answer is not to add unqualifiable forecast
years.** Check first whether tail support can come from observation history — labels, METAR/ASOS and
GHCNh reach back much further than 2021, and only the *forecast* archive is limited. If it genuinely
cannot, narrow the class contract or bring the gap back here as a new decision. Do not quietly widen
`covered_years`.

### How this year set binds — it is a policy object, not a manifest field

`-09-16a` found that the preflight derives required years from `source_payload["covered_years"]`,
i.e. from the candidate's own evidence, so a candidate can shrink the gate that judges it — from
20,160 cells to 2,520 by editing one JSON field.

**This year set must therefore be bound into the hash-bound retrain plan**, not read from a source
manifest. The source manifest may *prove coverage* of the matrix; it must never *choose its size*.
A test must show that reducing `covered_years` cannot reduce expected cells. Until that repair lands,
this file is the authority on the year set and the preflight's derived 2018–2025 matrix is a defect,
not a requirement.

---

## Standing follow-up — a better free source is in scope

The owner invited adoption of better free sources. Not on the retrain critical path; do not let it
delay the corpus. Candidates already identified in `docs/research/FREE_WEATHER_DATA_SOURCE_AUDIT_2026-06-15.md`,
which rated NBM "high priority": NOAA/NWS NBM via NOMADS or Open-Meteo `ncep_nbm_conus`, GFS/GEFS,
HRRR, and ECMWF open data. Any adoption must clear the same point-in-time contract as the primary
source — an issue-qualified, non-stitched, hash-bound archive — and must not become a second ambient
path into serving.

## Related

- `docs/operations/reserved-confirmation-window.md` — wins over this file where they touch.
- `docs/roadmap/agent-report-2026-08-05-workstation-clear-the-forecast-archive-gate.md` — `-09-16a`,
  the report this decision unblocks.
- `docs/roadmap/agent-report-2026-08-03-workstation-scope-forecast-archive-extension.md` — `-08-28a`,
  the scoping report whose open licensing condition this closes.
