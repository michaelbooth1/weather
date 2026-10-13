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
- **Host read, 2026-10-13 (master; pre-embargo reads only): WU counts the 00:00 observation.** CYYZ raw WU day files
  hold 24 observations, 00:00-23:00 local. Settled highs: 09-06 = 22 (max at 13h), 09-21 = 15 (the 00:00 reading ties
  the 14-17h readings), 09-26 = 23 (14-15h). All three reconcile with the Polymarket outcome, but none of them separates
  "midnight counts" from "midnight does not count". A scan of Toronto raw days 2025-01-01..2026-09-29 found 23 days on
  which only the 00:00 observation held the maximum; 2 have settlement rows, and on both the venue resolved the
  with-midnight band (2026-06-14: 24 with midnight, 23 without, resolved 24; 2026-08-02: 24 with, 22 without, resolved
  24). Our `settlement_high` is read from `daily_summary`, so it is circular; the independent check is the Polymarket
  closed-market winner: with-midnight 2, without 0. **n = 2, no counterexample.** So a floor at an observed hour-0 high
  is consistent with venue settlement on the evidence so far; it is not proof. EF §10r.

Acceptance:

- [x] Host read: WU settled high for Toronto on 2026-09-06, 09-21 and 09-26 against anchor buckets 19, 15 and 14, and
  whether WU's day-D history includes the 12:00 AM observation (decides whether the residual could ever settle).
  Done 2026-10-13: WU includes 00:00; see the host-read finding above (n = 2 discriminating days).
- [ ] Owner decision: keep the hedge on the no-METAR path, or floor at the observed SWOB/WU-current same-day high
  (this would reverse the "SWOB keeps its warm-bias hedge" choice made for v4). The host read leans toward the floor;
  the call stays the owner's.
- [ ] Host `lockin_anchor_replay --with-no-metar-arm` over 2026-08-25..09-29 (all markets) on the draft branch
  `claude/no-metar-floor-20261013`; earliest 2026-10-15 02:00-04:00 under the heavy lease.
- [ ] If flooring: a reviewed change with a model-version bump, a replay over the same window showing zero
  below-anchor mass on no-METAR rows and no other change, and the release-binding steps.

Draft build (2026-10-13, branch `claude/no-metar-floor-20261013`, not landed; owner decision still open):

- `no_metar_observed_floor` on the model, default off, so serving and the model version are unchanged. When on and
  the day has no METAR row, the v4 pre-lock-in move applies at the observed station anchor bucket (stage
  `pre_lockin_no_metar`); with METAR rows nothing changes. If the owner chooses the floor, flipping the default needs
  the model-version bump and release-binding steps above.
- `lockin_anchor_replay --with-no-metar-arm` replays the switch next to the served arm and exits 3 when a no-METAR row
  keeps mass below the anchor or any other row changes.
- Workstation validation on local captures only (Toronto 2026-06-03..08-12, 77 folders, 11,168 snapshots; Miami and
  NYC, 4,924 snapshots, as a collateral check). Toronto had 836 no-METAR rows on 41 dates. With the switch on, 0 of
  them kept mass below the anchor: 520 were floored by the new stage and 316 were already floored late-day. 492
  changed (max L1 0.397). 0 rows changed anywhere else (Toronto's 10,332 METAR rows, and Miami and NYC, which had no
  no-METAR rows). Under the served code
  182 of those Toronto rows kept mass below the anchor (max 0.199), far more than the three B-replay rows. 50 of the
  changed rows are hour 0, so the open WU 12:00 AM question decides whether the switch is safe.
- Host read done 2026-10-13 (WU counts 00:00; venue paid the with-midnight band 2/2, EF §10r). Still needed: the
  same arm over the B window (2026-08-25..09-29) on the capture host, earliest 2026-10-15 02:00-04:00.
