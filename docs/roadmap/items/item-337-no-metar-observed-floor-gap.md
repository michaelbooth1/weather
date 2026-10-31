# 337. No-METAR Observed-Floor Gap [OPEN 2026-10-08 - OWNER YES 2026-10-13, CONDITIONAL ON THE HOST REPLAY]

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
  is consistent with venue settlement on the evidence so far; it is not proof. EF §10qq.

Acceptance:

- [x] Host read: WU settled high for Toronto on 2026-09-06, 09-21 and 09-26 against anchor buckets 19, 15 and 14, and
  whether WU's day-D history includes the 12:00 AM observation (decides whether the residual could ever settle).
  Done 2026-10-13: WU includes 00:00; see the host-read finding above (n = 2 discriminating days).
- [x] Owner decision: keep the hedge on the no-METAR path, or floor at the observed SWOB/WU-current same-day high
  (this would reverse the "SWOB keeps its warm-bias hedge" choice made for v4). Decided 2026-10-13 ~18:30 EDT (relayed
  verbatim by master-agent; [DECISION_LOG](../../operations/DECISION_LOG.md)): "Yes, after the replay (Recommended)" —
  "Run the late-September replay on this PC first (10-15 or later); if it passes, flip the switch, bump the model
  version and land it in a quiet window." Conditional: floor only if the host replay below passes.
- [ ] Host `lockin_anchor_replay --with-no-metar-arm` over 2026-08-25..09-29 (all markets) on the draft branch
  `claude/no-metar-floor-20261013`; earliest 2026-10-15 02:00-04:00 under the heavy lease.
- [ ] On a PASS: flip `no_metar_observed_floor` on in a reviewed change with a model-version bump (the replay above
  must show zero below-anchor mass on no-METAR rows and no other change), the release-binding steps, and a quiet-window
  landing after a roll verdict.

## Evening-fix read postponed (2026-10-31)

The evening lock-in fix read (signed pre-registration
`docs/research/evening-lockin-fix-scoring-preregistration-DRAFT-2026-10-13.md`, which reports this item's
no-METAR rows separately in its safety count) did not run on 2026-10-29. Reason, as section 5 requires it to be
recorded: "the scorer was never landed; it slipped on the night queue" (prereg line 193). The read is postponed, not
cancelled; the window is unchanged (10-16..10-27, extension 10-28 only, never 10-29). It runs in two stages under
[Clarification 1](../../research/evening-lockin-fix-scoring-clarification-1-2026-10-31.md), with the no-market
scorer on `claude/evening-fix-no-market-20261031`. Nothing in this item's acceptance changes.
