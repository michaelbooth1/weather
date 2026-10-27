# Item 5: P3d_N (NBM) log-pool blend at 07-12 vs the market (lane L11, 2026-10-25)

Development evidence only.

- Rule: `market_blend_rule_nbm0712.md`, sha256 `94b1603a407dd66ccb6137468cc3e703e00f73024209997c3181e26ed8a07e84`,
  prereg PASS. It was recorded before any row.
- Machinery: run 2's, unchanged. The candidate is P3d_N `721ae2cd…` in place of MG-1+L6.
- L9's N1 was dropped, because no 07-12 vectors exist for it.
- Code: `2691d9d36`, run through `workstation_heavy.ps1`.
- Rows: `C:\t\l11\nbm0712\market_blend_rows.json`, sha256
  `85ef656f1b5544e19745806167457e68c0968f51ccf5540f39edae8708342645`.
- Controls, all PASS: served; MG-1 excess 0.0120; MG-1's run-2 07-12 R 1.0016629 reproduced; the fit vector equals
  the score vector; the w = 0 identity. The placebo also passed: mean w 0.004, R 1.0013.
- Candidate coverage at 07-12 is 0.999.

## Reading (pre-registered): NOTHING

The mean walk-forward w at 07-12 is **0.0051**, below the 0.05 bar, and 28 of 43 dates have w = 0. **The NBM model adds
nothing to the market before 13:00.**

| Row (blend vs market) | R | crossed 95% CI | date 95% CI |
| --- | --- | --- | --- |
| 07-12 ALL (primary) | 1.0013 | [0.9992, 1.0075] | [0.9996, 1.0043] |
| 07-12 PRIMARY5 | 1.0003 | [0.9995, 1.0015] | [0.9999, 1.0009] |
| h07 / h08 / h09 ALL | 1.0006 / 1.0006 / 1.0009 | | |
| h10 / h11 / h12 ALL | 1.0014 / 1.0011 / 1.0037 | | |

The floor-only control for 07-12 ALL is R 1.0010. The MDE80 is 0.0038.

## DESCRIPTIVE only (not for a decision): P3d_N alone vs the market

This is the first 07-12 read of P3d_N; it had not been computed or seen before this run.

| Pool | 07-12 R | crossed | date |
| --- | --- | --- | --- |
| ALL | 1.1912 | [1.1024, 1.2944] | [1.1395, 1.2481] |
| PRIMARY5 | 1.1875 | [1.0335, 1.3872] | [1.0986, 1.3012] |

Per hour on ALL, R runs from 1.18 to 1.21. Unblended, P3d_N is about 19% worse than the market in Brier at 07-12, so
the walk-forward w correctly keeps it near zero. The full per-hour tables are in `market_blend.md` next to the rows.

## Look-ahead audit (2026-10-25, master ruling)

**The ruling.** Every input to a read against the market must be no-look-ahead: the latest snapshot captured
at or before the row's capture time, with no METAR row received after it. This audit read code and input
metadata only and produced no new scores.

**Market side: clean.** `dev_scorecard.Table.p_market` is the layout's `p_market_yes`, keyed by each row's own
`row_key`, so it is the row's own captured price. The table's impossibility mask and `has_floor` use the row's
own served floor fields.

**Candidates:**

- **MG-1: clean.** `loss_atlas.mg1_frame` uses the row's own `v2_mean` / `v2_stddev`, only where
  `v2_available_at <= captured_at_utc`, and the row's own served floor fields.
- **L6 captured re-spec (the run-2 composite before 13:00): clean.** `r0_ols_floor_challenger.l6_captured_features`
  (commit a482d1b17) builds each snapshot's features from that snapshot's own captured METAR rows. It keeps a
  row only when `valid + 10 min <= captured_at_utc`. The previous-day max comes from the previous day's last
  snapshot.
- **P3d_N (`dev_P3d_N.jsonl`, sha 721ae2cd...): look-ahead, confirmed (`last_in_hour`).**
  - `pooled_residual_model.scan_replay_n` (commit 064aabe6a) takes `high_so_far` and `current_temp` from the
    *last* replay snapshot captured in [h:00, h+1:00). It does this with `cutoff_hour = h`, so it keeps METAR rows
    observed at or before h:00 but received any time before that last snapshot.
  - It then emits that one input set for every layout row with `cutoff_hour = h`, whatever that row's own
    capture time.
  - Its NBM input (`nbm_usable`) is the row's own and is availability-gated.
- **Exposure, counted from metadata:** layout snapshot times against the IEM market-station METAR times, with the
  rule's +10 min availability. The count is a row whose own capture is earlier than "latest METAR at or before
  h:00, plus 10 min". "Raises H" means that METAR raises the whole-degree running max H.
  - 07-12: **1,793 of 28,770 rows (6.2%)** are exposed; 956 of them (3.3%) have that METAR raise H.
  - 13-16: **1,057 of 18,591 rows (5.7%)** are exposed; 602 of them (3.2%) have that METAR raise H.
  - All exposed rows also carry a `current_temp` from the later snapshot.
  - The count assumes 10-minute receipt. Rows whose METAR arrived later than that are not counted, so it is a
    lower bound.
  - Script `C:\t\l11\audit\p3dn_exposure.py` (sha b98dfdd3...); output `p3dn_exposure_out.json` (sha bf219767...).

**Effect on the readings.** The look-ahead can only favour the candidate.

- **Item 5** (P3d_N at 07-12: NOTHING, mean w 0.0051): the null is firmer.
- **Descriptive P3d_N** (R 1.19 against the market at 07-12): the true gap is if anything wider.
- **Run 2:**
  - The PRIMARY composite at 07-12 is MG-1 plus L6 captured, so it was clean. Its INCONCLUSIVE reading stands
    as computed.
  - The composite's 13-16 secondary used P3d_N. It read NOTHING, which is firmer.
  - The MG-1 readings were clean.
- No re-score is needed for any null. A positive result built on P3d_N would have required a no-look-ahead
  re-emission first.
