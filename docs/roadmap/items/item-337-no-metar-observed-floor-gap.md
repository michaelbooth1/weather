# 337. No-METAR Observed-Floor Gap [OPEN 2026-10-08 - SCOPE QUESTION FOR THE OWNER]

Goal: decide whether, when a market has no METAR rows for the day, its observed same-day station high (SWOB or WU
current, including a reading at local midnight) should act as a hard floor on the probability vector, and if so build
it with its own replay.

Owner/package: `weather.model` (`model_distribution.py` hard floor and lock-in anchor, `model_distribution_signals.py`
SWOB warm-bias hedge, `model_base.py` floor inputs).

Source: owner decision 2026-10-08 11:55 (relayed by master-agent), accepting lockin-anchor-v4 (#246 on #189) on the
condition that the B replay's residual R2 rows are pre-existing; this item tracks the gap those rows exposed.

Why this matters: in the B replay (2026-08-25..09-29, 75,796 snapshots) three Toronto snapshots kept 0.005-0.010 of
probability below the observed anchor bucket. All three had no METAR rows, so the v4 pre-lock-in floor (which reads
METAR only) was inert, and the mass was identical under the old code, v4 with the floor disabled, and v4. On 2026-09-06
(07:28) mass sat two and three buckets under an observed 18.7.

Findings so far (workstation code trace at 91bf07863; host read of the three rows):

- The anchor high equals `guidance_physical_floor`, which is the max over observed sources only
  (`model_features.py:222-252`); with no METAR the SWOB station rows supply it. It is observed, not forecast-derived.
- The only floor applied on this path is the existing hard floor: round(max(current temperature, max since 07:00 from
  cutoff hour 7)) (`model_distribution.py:298-307`, applied at `:447`, zeroed in calibration at `:557-562`;
  `model_base.py:64-80,102-106`). Overnight readings never enter it, so buckets are zeroed only up to the current
  reading.
- The residual just under the anchor is the deliberate SWOB warm-bias hedge (`model_distribution_signals.py:221-240`).
- "00:00" first-reached is a genuine day-D SWOB observation at local midnight: SWOB rows are keyed by observation time
  converted to local and filtered to the target date (`model_sources.py:2410-2427`). It is not the prior-day keying
  defect #189 fixed for METAR.
- The replay's `below_floor_viol` does not test these rows (it checks only rows where the v4 floor is set).

Acceptance:

- [ ] Host read: WU settled high for Toronto on 2026-09-06, 09-21 and 09-26 against anchor buckets 19, 15 and 14, and
  whether WU's day-D history includes the 12:00 AM observation (decides whether the residual could ever settle).
- [ ] Owner decision: keep the hedge on the no-METAR path, or floor at the observed SWOB/WU-current same-day high
  (this would reverse the "SWOB keeps its warm-bias hedge" choice made for v4).
- [ ] If flooring: a reviewed change with a model-version bump, a replay over the same window showing zero
  below-anchor mass on no-METAR rows and no other change, and the release-binding steps.
