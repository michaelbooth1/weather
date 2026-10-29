# R-ODC forward pre-registration (P1 only): DRAFT, NOT FROZEN

Status: draft (L8, 2026-10-29), with master's rulings of 2026-10-29 applied, including ruling (c): P1 only. Nothing
here is frozen.

- No date after 2026-09-29 has been read for it: no snapshot, no label, no outcome.
- It freezes only as a later commit that says FROZEN, dated 2026-10-30 or later, together with its ledger row.

Lineage:

- Ledger row 69: G2 history gate PASS.
- Ledger row 70: the PROXY retro gate PASS, on IEM ASOS archive features.
- Both are selection-contaminated history evidence on Oct-Dec 2021-25 07-12.

What this test asks: can the two R-ODC columns (low_so_far, dewpoint_c) be built at serve time, from the captured
METAR, at parity with the WU-history construction the model was trained on? It does not test the model's skill
forward. That is left to the next release candidate's own gates.

## 0. Disclosures

- **Third test.** This is the 3rd R-ODC test on the hypothesis, after rows 69 and 70, and the first on fresh dates.
  It is disclosed in a new ledger row at the freeze.
- **P2 dropped before the freeze (master's ruling c).** A P2 non-inferiority test on dR(NEST vs G1) was drafted
  and dropped, for these reasons:
  - The forward MG-2 input bundles lack inputs that G1 and NEST need: HRRR k_max and k_tcdc, current_temp, and the
    raw METAR rows.
  - The bundle's NBM mean (v2_mean) has not been verified to match the dev construction (`nbm_at_cutoff`).
  - Power at 45 dates without Denver was only 0.78 if the dev effect holds, and 0.37 if the true effect is 0.
  - That is too much new plumbing for a −0.001 effect.
  - The dropped P2 is not run, and no P2 number is reported from these dates.
- **Denver.** Denver is excluded, as in test B (DL 10-23, KDEN vs KBKF). The dev rows of rows 69 and 70 included it.
- **Overlap with B (ruling a): allowed.** The forward dates overlap test B's dates. R-ODC's dates and results are
  never pooled with B. Its look comes after the B look receipt. Nothing from it feeds B or MG-2.

## 1. P1 (the only primary): serve parity

P1 needs no labels, but it reads forward snapshots and WU rows, so it is a look (section 3).

- **Markets:** the dev markets without Denver. **Hours:** h07-12.
- **On each forward date** D, market and hour h, compute:
  - **serve:** `odc_metar_features.odc_features` on the captured snapshot chosen by `choose_snapshot` with the
    state's late-report rule `last_in_hour`;
  - **research:** the training construction on the WU history. That is the rows with local_date == D and
    minute_of_day ≤ h·60; low = the min of temp_native; dew = the dewpoint_native of the latest row.
- **Serve data source:** the raw METAR in the capture host's existing snapshot store (the serve source; no new
  capture path).
  - The path is `<snapshots root>/<event slug>/replay_inputs.jsonl`, with each capture's
    `sources.metar.data`.
  - The root defaults to `weather.paths.data_path() / "snapshots"`; the event slug is
    `market_config.event_slug_for_date`. The read code is `rodc_forward_scorer.read_snapshots`, pinned by blob in
    section 5.
- **Research data source (ruling b):** the capture host's existing daily-refresh WU history,
  `weather.sources.wu_history`. It is free and approved.
  - The store is `WundergroundHistoryStore` exactly as `daily_refresh_source_steps._store_for_wu_restore(spec)`
    builds it, with `spec = market_registry.spec_for_id(market)`. Its root is `spec.data_root`, built by
    `weather.paths.data_path()`. No data path is written by hand.
- **At the look,** master exports the forward-date snapshot METAR rows and the WU history to the workstation.
  - Any missing (market, date) WU day is backfilled with the same `PublicWundergroundHistoryClient`.
  - **WU gap limit, pre-set:** if more than 5% of the required (market, date) WU days, from D0 to the 45th
    countable date, are still missing after the backfill, P1 is VOID.
- **Dev reference:** the 2026-08-01..08-10 sample (L8, `par.py` part b), 575 compared rows:
  - low_so_far: 563/575 exact (97.9%, Wilson 95% lower bound 96.4%), max |diff| 1 °F;
  - dewpoint: 573/575 exact (99.7%, Wilson lower 98.7%), max |diff| 4 °F, from one receipt lag;
  - for reference, the served high_so_far: 564/575.
- **Pre-set limits.** Each is set below the dev Wilson lower bound to allow for a winter regime shift (more frequent
  SPECIs, a different receipt lag):

  | Column | Exact-match rate | Max \|diff\| | Rows with \|diff\| ≥ 2 °F |
  | --- | --- | --- | --- |
  | low_so_far | ≥ 95% | ≤ 2 °F | ≤ 1% |
  | dewpoint | ≥ 97% | ≤ 5 °F | ≤ 1% |

- **Precision.** 45 dates × 10 markets × 6 hours is up to 2,700 rows. At the dev rates the Wilson half-width is
  about 0.5 point, so each limit is decidable.
- **Mismatches and refusals:**
  - A `check_bounds` refusal on a serve hour counts as a mismatch in the ≥ 2 °F bucket. The hour's own bounds
    (low ≤ high_so_far, low ≤ current temperature, from the same snapshot) are checked, and its running minimum
    against the previous scored hour.
  - A value on one side and None on the other counts the same way. Both None is a match. Neither enters max |diff|.
- **Exclusions:** a row with no snapshot in the hour, no kept METAR row, or no WU row is excluded and counted. If
  more than 10% of the rows on the scored dates are excluded, P1 is VOID.

## 2. Countable dates and the look

- **Countable date:** a date ≥ D0 with at least one (market, hour) row, Denver excluded, where both the serve and
  the research value exist.
- **N = 45 countable dates.** P1 is scored on the first 45. A date that is not countable is skipped and does not
  enter the exclusion share.
- **D0 = the freeze date.**
- **The look** comes after the 45th countable date and on or after the B look receipt. A look later than 12-14 is
  fine.
- If fewer than 45 countable dates precede the look, the scorer refuses. Master then sets a later look; nothing
  scored is reported in between.

## 3. Embargo and timing

- **Embargo:** no snapshot, label or outcome after 2026-09-29 is read before the look.
- **P1 is a look.** Forward snapshots and WU rows are read only at the look.
- **D0** is the freeze date, strictly forward. Captured-but-unread days before the freeze do not count.
- **One fixed-sample look.** No interim look.
- **Enforced in code:** `rodc_forward_scorer.check_look` refuses every read and the verdict unless:
  - the freeze is ≥ 2026-10-30 and D0 equals it;
  - the look is ≥ D0 + 45 days and ≥ the B receipt date;
  - today ≥ the look;
  - every date is in [D0, look);
  - no Denver row is present.
  `p1_verdict` refuses fewer than 45 countable dates.

## 4. Outcomes

| P1 | Verdict |
| --- | --- |
| PASS | R-ODC becomes **eligible as a feature in the next release candidate**. That release's own gates decide on outcomes; P1 does not. This is not a promotion. |
| FAIL | R-ODC closes: it cannot be served at parity. |
| VOID | No verdict. The dates are spent. |

## 5. Pinned items 1-8 (the serve construction) and the code

1. **Source:** captured `sources.metar.data` rows only. No WU-current or station fallback.
2. **Instant:** `observed_running_max.metar_observation_local_time` (obsTime, else raw DDHHMMZ), else the row's
   `obs_time`. Undated rows are skipped.
   - A row is kept if it is on local date D, at or before h:00, and at or before the snapshot capture time.
3. **Snapshot:** the state's late-report rule (`last_in_hour`) through `choose_snapshot`.
4. **Values:** low_so_far = `wu_whole_f`(the min plausible temp_native, half_up). dewpoint = `wu_whole_f`(the
   dewpoint_native of the latest kept row, half_up).
   - Here `wu_whole_f` is `mg_serve_core.wu_whole_f`, the serve T-group conversion.
   - The unit is native °F whole degrees. The legacy name dewpoint_c does not mean Celsius.
5. **Missing values:**
   - dewpoint is None when the latest kept row lacks one. There is no fallback.
   - No kept row means the row is excluded and counted, like high_so_far.
6. **Refusals:** `check_bounds`: the running min never increases, low ≤ current, and low ≤ high.
7. **The train/serve split is accepted and measured.** The model stays trained on the WU-print columns (rows 69/70).
   P1 measures the split forward.
8. **Serve module:** `src/weather/calibration/odc_metar_features.py` on `claude/rodc-odc-metar-features-20261029`
   @ `0e11b018fda76125425c8ebdd21560ee10289d70`, git blob `1cc4d565468bf4959137a8f6f6cec5b10adfce24`, sha256
   `dd53e81ebbf8851673d01f138296fb56a91ce898e53c0541d67226e64dd981d1`. It stays unlanded, pinned by blob.

**Scorer and read code:** `src/weather/calibration/rodc_forward_scorer.py` on `claude/rodc-forward-scorer-20261029`
@ `347cd31233a7b9a79642ff772bc2147e41f027e6` (stacked on 0e11b018f), git blob
`1a38ddb9c406f38bd3f5185940be7b2a6d7e4241`, sha256
`888d8987dd2d124efd2fdba0b61854e6bdb43a2019c8a931b53bdf30f9e3f5f1`.

- It holds both reads (`read_snapshots`, `read_wu_rows`), `p1_day`, `countable_dates`, `p1_verdict` and `verdict`.
- Tests: `tests/calibration/test_rodc_forward_scorer.py`, blob `aeef114cc53d75b3a0df3ebcbb294bc04dd320d7`. With the
  module's tests, 26 passed through the workstation queue.
- Neither file is in RELEASE_FILES, and no serve path imports them.
- Pinned constants: `P1_LIMITS`, `P1_EXCLUDED_VOID`, `WU_GAP_VOID`, `N_COUNTABLE`, `HOURS`, `EXCLUDED_MARKETS`,
  `FREEZE_EARLIEST`, `SNAPSHOT_RULE`.

## 6. Rulings applied (master, 2026-10-29)

- **(a)** The overlap with B is allowed: never pooled, the look after the B receipt, nothing feeds B or MG-2.
- **(b)** The P1 WU source is the daily-refresh WU history store, with a 5% gap limit.
- **(c)** Denver is excluded. Then, after the P2 frame review: P1 only, P2 dropped and disclosed (section 0); the
  serve source is the snapshot store's raw METAR; countable dates, D0 and the look as in section 2.
- **(d)** The NI margin m = +0.0015 was ruled, then dropped with P2.
