# Clarification 3a to the R-ODC / X13 released-cell P0 rule (ledger row 103, lane L16, 2026-10-31)

Amends Clarification 3 (sha256 `e9664e4ab24b1ad7ea98324bd0e9ca2013a32f1e86db0f9f82e6d10dc1c0465c`), point 1 only.
The rule (`9bff5c02762a27ef604219b305e6a8043497cbf0316ec2403b879f4ed09a2f11`), Clarification 1
(`064c4f267fab1e70d5b046c00da2b9796adae77031918ce08caee2030cd48be6`), Clarification 2
(`cec81d4fa556866a162e47ee990385f5c471973ced9a1fd35a93d98deef182c2`) and Clarification 3 are not edited. Where this
amendment differs from Clarification 3 point 1, this amendment wins.

This is master's ruling on rehearsal r1, relayed by the coordinator on 2026-10-31. It was written after rehearsal r1
and before rehearsal r2 and before look2. look2 is not admitted until master approves the r2 report. A rehearsal
stops before `sc.Table`, so r1 exposed no Δ, no label and no price.

## Why: rehearsal r1 refused at C-g on a known defect class

- r1 (`rehearse-to-table --out C:\t\l16\rodc-rehearse\r1`, driver at `f1e835675b40dde8b76a6e2616b4248f55725b45`)
  refused at C-g. Console log `C:\t\l16\rodc-rehearse-r1-console.log`, sha256
  `c2d4109983b3b9ccaa4f41afb41975033f526115932d85be604f7336c1275c96`. No rehearse receipt was written.
- The three violations are all Austin 2026-10-14, local hour 7: WU-whole low_so_far 79 above the WU-whole layout
  high_so_far 78. The `check_bounds` cell list was empty.
- Cause: the layout's high_so_far for that day falls. It is 78.98 °F through 12:29Z, 78.08 °F from 12:38:34Z to
  13:51Z, then 80.06 °F at 13:57Z. A low of 79 from the earlier ~78.98 observation then sits above the later 78.
- This is a known class. The findings digest, line 49: "`high_so_far` is not a running maximum: the vendor
  observation series is not append-only". Established findings §1k, `-09-70a` ("`high_so_far` decreases are common")
  and `-09-71a` ("the WU observation series is not append-only"). Row 80's population and the market carry the same
  property. Both were checked in the repository before this was written.
- C-g checks that the arm features are built correctly. high_so_far is not an arm input.

## 1. The C-g reference high is the point-in-time running maximum

- Inside `control_cg` only, the reference high for a snapshot is the running maximum of the layout's high_so_far over
  all captures of the same (market, date) up to and including this one, in capture order, on the WU whole scale:
  `wu_whole_f(max raw high_so_far, "half_up")`. Rounding is monotone, so this equals the running maximum of the
  whole values.
- "All captures" means every capture of that (market, date) in the release layout, not only the scored hours 7..12.
- Capture order is `captured_at_utc`. Captures sharing one instant form one group and each sees the whole group,
  because all of them are known at that instant; the result does not depend on how ties are ordered.
- Earlier captures are known at capture time, so the reference is point-in-time valid.
- **A low_so_far above that running maximum still FAILS C-g.** The rounded-current comparison, the running-minimum
  check and `check_bounds` are unchanged; `check_bounds` receives the running-maximum reference as the hour's high.
- **The arms, μ_m, the statistic, the floor and the population stay EXACTLY as frozen and as row 80. No scored value
  changes.** The reference is used only by C-g; `snapshot_features`, the arm columns, `sc.Table`, C-c and
  `p0_candidate` never see it. `odc_metar_features.py` stays blob-unchanged.
- C-g also records, for disclosure: the snapshots whose reference is above their own WU-whole high, and what the
  Clarification 3 own-snapshot comparison and the frozen raw-high comparison would have refused.

## 2. Disclosure: high_so_far decreases over the whole release layout

Disclosure only. There is no threshold and nothing is excluded.

- Script: `rodc_hsf_decrease_diag.py` (lane scratchpad), sha256
  `780a61c806ba280b51d6ac7f898d56b4bc6eefd095065a226e51cda8dbf1dede`. It is light and run directly.
  - It read five feature columns of `C:\t\r80\build\layout\inputs_snapshots.parquet`: market, date,
    captured_at_utc, row_key and high_so_far.
  - Dates were local target dates 2026-10-01..2026-10-14, with Austin 10-03 excluded. There were no labels and no
    prices.
- Output: `C:\t\l16\rodc-hsf-decrease-diag.json`, sha256
  `8f39b12e0dc0ef1e80f0bd1da31d8259ed87a6cb978e7f5b8a64226e7684fc90`.
- A snapshot counts when its high_so_far is below the maximum over strictly earlier capture instants of the same
  (market, date). A cell counts when it has at least one such snapshot.
- The driver's `high_so_far_decreases` reproduces these counts exactly on the same parquet. The r2 receipt repeats
  them under `controls["C-g"]["layout_high_so_far_decreases"]` and `clarification_3a`.

| Market | Snapshots | Below an earlier capture (raw) | Below (WU whole) | Cells | Cells with a decrease |
| --- | ---: | ---: | ---: | ---: | ---: |
| atlanta | 2542 | 960 | 960 | 14 | 14 |
| austin | 2315 | 576 | 576 | 13 | 13 |
| chicago | 2519 | 871 | 871 | 14 | 14 |
| dallas | 2517 | 845 | 845 | 14 | 14 |
| denver | 2342 | 550 | 508 | 13 | 13 |
| houston | 2487 | 765 | 765 | 14 | 13 |
| los-angeles | 2395 | 699 | 698 | 14 | 14 |
| miami | 2446 | 506 | 506 | 14 | 14 |
| nyc | 2524 | 706 | 706 | 14 | 14 |
| san-francisco | 2509 | 704 | 704 | 14 | 14 |
| seattle | 2511 | 740 | 740 | 14 | 13 |
| **Total** | **27107** | **7922** | **7879** | **152** | **150** |

The cell counts are the same on both scales.

A second light, feature-only probe locates the decreases in local time:
- Script: `rodc_hsf_window_probe.py`, sha256 `02a3c5c15f558a335e98b382eed83c38f396f4b224277c4bf72d1397f563a036`.
- Output: `C:\t\l16\rodc-hsf-window-probe.txt`, sha256
  `030a6d48266438663548a947e2395fdf903d2e02b7f1cb163ebadc5bc7a0c928`.
- Every capture's local date equals its target date.
- The decreases concentrate in local hours 1..8, at 400 to 1,050 per hour, against at most about 110 per hour
  after 11:00.
- The median drop is 1.98 °F, the 90th percentile 5.22 °F, and the maximum 24.66 °F.
- Consequence, stated for the record: at hours 7 and 8 the running-maximum reference often sits above the snapshot's
  own high. That makes C-g's low-versus-high comparison less strict there than Clarification 3's own-snapshot
  comparison. It cannot change a scored value. The r2 receipt counts the affected snapshots in
  `snapshots_reference_above_own_high`.

## 3. Order

Clarification 3a (sha) → driver and tests only, on top of `f1e835675b40dde8b76a6e2616b4248f55725b45` → focused tests
through `-Queue` (basetemp deleted) → pre-push screen → push without force → preflight → rehearsal r2 (one `-Queue`
job, `--out C:\t\l16\rodc-rehearse\r2`).

If r2 refuses on anything outside this documented class, the lane stops and reports and does not fix it. look2 stays
NOT admitted until master approves the r2 report. The look2 approval string pinned in Clarification 3 point 4 is
unchanged.
