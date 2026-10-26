Code `c6e87fd9f`; run through `workstation_heavy.ps1`; JSON sha256 `4b9c8f5711427435a0c06e2a3a841322ad298f12b5d59407a54f30df91944253` (`C:\t\l11\desc1`, not committed). The floor-only rows reproduce run 1/2 (13-16 ALL 0.9845, PRIMARY5 0.9776).

# P3d_N alone vs the market, 13-16 (DESCRIPTIVE - not pre-registered for a decision)

Note `7928629405d812dd4642e39c1e02d7ff31542deabc10176f7c59147e9975332b`; vectors `721ae2cd24283115f68c4b6a1b38d84d34a81921e41468d360b587599fd031ec`; served control PASS. Scored 2026-08-15..2026-09-29.

| Vector | Pool | Window | n md | R | crossed | date | log ratio | covered |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| candidate | ALL | h13 | 473 | 1.2368 | [1.1130, 1.3733] | [1.1709, 1.3120] | 1.3076 | 0.998 |
| floor_only | ALL | h13 | 473 | 0.9991 | [0.9878, 1.0205] | [0.9912, 1.0115] | 1.0070 |  |
| candidate | PRIMARY5 | h13 | 215 | 1.1894 | [1.0232, 1.3973] | [1.0970, 1.3039] | 1.2277 | 0.999 |
| floor_only | PRIMARY5 | h13 | 215 | 0.9977 | [0.9884, 1.0036] | [0.9936, 1.0013] | 0.9913 |  |
| candidate | ALL | h14 | 473 | 1.3020 | [1.1660, 1.4572] | [1.2387, 1.3741] | 1.3196 | 0.999 |
| floor_only | ALL | h14 | 473 | 0.9793 | [0.9437, 1.0100] | [0.9596, 1.0022] | 0.9951 |  |
| candidate | PRIMARY5 | h14 | 215 | 1.2204 | [1.0548, 1.4269] | [1.1144, 1.3488] | 1.2224 | 0.999 |
| floor_only | PRIMARY5 | h14 | 215 | 0.9814 | [0.9577, 0.9944] | [0.9706, 0.9908] | 0.9728 |  |
| candidate | ALL | h15 | 473 | 1.3669 | [1.1772, 1.5683] | [1.2485, 1.4824] | 1.3386 | 0.999 |
| floor_only | ALL | h15 | 473 | 0.9778 | [0.9397, 1.0387] | [0.9564, 1.0099] | 1.0035 |  |
| candidate | PRIMARY5 | h15 | 215 | 1.3205 | [1.0639, 1.6031] | [1.1567, 1.5101] | 1.2477 | 0.999 |
| floor_only | PRIMARY5 | h15 | 215 | 0.9667 | [0.9186, 0.9932] | [0.9514, 0.9790] | 0.9633 |  |
| candidate | ALL | h16 | 473 | 1.2106 | [0.9614, 1.5008] | [1.0425, 1.4058] | 1.2844 | 1.000 |
| floor_only | ALL | h16 | 473 | 0.9677 | [0.9071, 1.1102] | [0.9356, 1.0142] | 1.0188 |  |
| candidate | PRIMARY5 | h16 | 215 | 1.1345 | [0.7956, 1.4888] | [0.9026, 1.4114] | 1.1153 | 1.000 |
| floor_only | PRIMARY5 | h16 | 215 | 0.9400 | [0.8513, 0.9791] | [0.9030, 0.9696] | 0.9394 |  |
| candidate | ALL | 13-16 | 473 | 1.2795 | [1.1539, 1.4106] | [1.2130, 1.3520] | 1.3148 | 0.999 |
| floor_only | ALL | 13-16 | 473 | 0.9845 | [0.9641, 1.0268] | [0.9709, 1.0069] | 1.0034 |  |
| candidate | PRIMARY5 | 13-16 | 215 | 1.2184 | [1.0442, 1.4189] | [1.1107, 1.3478] | 1.2126 | 0.999 |
| floor_only | PRIMARY5 | 13-16 | 215 | 0.9776 | [0.9619, 0.9887] | [0.9715, 0.9831] | 0.9724 |  |

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
