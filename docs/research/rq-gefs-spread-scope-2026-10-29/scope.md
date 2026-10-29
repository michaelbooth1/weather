# GEFS ensemble spread as a dev candidate: scoping note for master (lane L13, 2026-10-29)

**Design only.** Nothing in this note was computed, fitted or scored. No outcome, price or label dated after
2026-09-29 was read, and no 88a, panel or settlement data for 2026-09-30..10-15 was read. No B-bound file is
touched: the `mg2_composite.RELEASE_FILES` list, `b_scorer` and `B_FORWARD_TEST_DESIGN.md`.

The only forward data opened were the GEFS recorder's own day manifests, for counts and receipt times; these are
forecast inputs, not outcomes.

## 0. Headline: this lever is already pre-registered as L15's R-Q

- **It is a duplicate.** "GEFS member spread as spread information" is lane L15's rung **R-Q**:
  - rule `docs/research/l15-spread-info-2026-10-25/rule_rq.md`, raw sha256 `5703f065…`;
  - committed `197729f4a` and code `19d822389` on `claude/spread-info-20261026` (not landed);
  - STATE_OF_PLAY lists it as **running**;
  - EXHAUSTION_REGISTER §6 says "GEFS member spread R-Q running" (X37 note).
- **It has not been scored.** There is no DEV_WINDOW_LEDGER row and no `C:\t\l15\rq\` outputs.
- **It is not killed.** No kill covers it (section 4).
- **Recommendation:** do not open a second rung under the name R-Q. Pick one of:
  - **(a)** run L15's R-Q as registered. Its variant A gates 1 and 2 need only the existing history and dev corpus,
    not the forward recorder.
  - **(b)** if master wants the forward L6-family form below, register it as a **new, separately named rung**
    (suggested **R-QF**). It must cite R-Q and inherit R-Q's kill breadth, so that a failure of either closes the
    same family.

The rest of this note scopes (b), so that master can choose.

## 1. Inputs

### Fields and members

- NOAA GEFS v12, AWS open bucket `noaa-gefs-pds`: free, official, anonymous, no key.
- Product `pgrb2sp25` (0.25°), the **06Z cycle of target date D**, steps f006..f024 every 3 h.
- Message `TMP:2 m above ground`, bilinear at the registry lat/lon, in °F.
- Members `gep01..gep30`. `gec00` is excluded from every spread statistic.
- This is exactly the R-O / L6_G extraction (rule_rn.md L31-49). It is not a new source.

### Daily-max proxy

- h_m is member m's max over the steps whose valid local date is D (R-O's `ro_member_highs`).
- A member counts only if every needed step has S3 LastModified at or before the row's cutoff.
- A row needs at least 25 of the 30 members; otherwise the spread is missing and the modulation is 0.

### Spread definitions

Pre-declare **one**; the others are excluded, not tried.

- **Primary (as R-Q variant A):** u = ln(max(SD_m(h_m), 0.25)), sample SD.
  - It is centred per market on the fitting years: x = u − ū_mkt.
  - Only the day-specific anomaly enters, so it cannot sharpen globally (R9).
- **Not tried:** inter-quantile range Q90−Q10, warm half-spread Q90−Q50, range and MAD.
  - R-Q's kill already names them as covered breadth.
  - Q90−Q50 is R-Q variant B, at 00-06 on the 18Z D−1 `pgrb2ap5` cycle. The recorder does **not** capture that
    cycle (below).

### Availability and latency at the serve cutoff

Recorder: `tools/research/gefs_forward_recorder.py` on `claude/gefs-forward-recorder-20261028`.

| Date | Rows | LastModified of the 217 objects | Last fetch | Note |
| --- | --- | --- | --- | --- |
| 2026-10-28 | 217/217 | 09:48-10:05Z | 15:59Z | manual proof fetch, after the Eastern 07-12 cutoffs |
| 2026-10-29 | 217/217 | max 10:02:50Z | 10:03:10Z | first live day, latency ~20 s |

- **Margin to the earliest 07-12 cutoff:**
  - About 55 min to Eastern h07 = 11:00Z (EDT).
  - About 1 h 55 min from 11-01, when h07 becomes 12:00Z (EST).
  - Pacific and Mountain margins are larger.
  - The rule-of-record probe gave 06Z f030 at 09:55-10:01Z in 2021-26.
- **00-06 is unavailable from this source.** The 06Z cycle lands after 06:00 local in every US market, so a 00-06
  variant would need the 18Z D−1 cycle recorded as well. That is out of scope here.
- **Receipts:**
  - Each row carries the grib and idx LastModified, our idx and message fetch times, and the sha256 of each.
  - The day manifest pins the rows sha256 and both G tables: the LastModified rule and the fetched rule.
  - A spread column would need the same two variants.

### Recorded dates

- The series started **2026-10-28** (manual) and **2026-10-29** (first live day). That is 2 dates at the time of
  writing, accruing one per day.
- The recorder is the WMI-launched process started 2026-10-28 16:15Z. This note did not disturb it.

### Dev history for 2021-25: it exists

- The `noaa-gefs-pds` archive holds GEFS v12 for the whole period (one model version).
- L11's corpus `C:\t\l11pb\gefs\corpus` (rows sha `8f512ad9…`, module `c898d94a…`) already covers:
  - Aug-Sep 2021-25;
  - 2026-07-30..09-29;
  - all 31 members.
- The recorder's code path reproduced it **byte-identically** on 2023-08-20, 2026-08-15 and 2026-09-29: every dev
  row field and all G cells.
- So **no forward-only power estimate is needed for the dev gates**: history LOYO plus dev can be run on data
  already held.
- **Oct-Dec (R10)** would need a fresh LOYO Oct-Dec 2021-25 fetch. It is free, uses the same fetcher, and costs about
  0.15 GB and 440 requests per date.

### Forward power (qualitative; nothing computed)

- Any forward confirmation shares L6_G's dates and its date-clustered noise. Its N would be bounded the same way:
  45 dates is a screen, with power about 0.49 at L6_G's in-sample dev point.
- A width-only effect is expected to be smaller than a centre shift:
  - R-S's NBM-spread gate 1 was −0.00099;
  - R-I's width effect was null on dev.
- So a 45-date forward screen would be **badly underpowered** for a plausible spread effect. Expect a powered test to
  need well over 100 dates. That argues for the history gates first and forward only after a dev PASS.

## 2. Frame: how a spread column joins the model rows

- **Join key:** (market, target local date D, snapshot local hour h), the same key `ro_dev_gefs` uses.
  - The spread is computed per key from the member rows of D's 06Z cycle.
  - It joins 1:1 onto the arm's snapshot rows.
- **Cutoff:** the row's effective cutoff is min(h:00 local, the snapshot's `captured_at_utc`). This is the same
  instant the effective-WU-print cutoff semantics use for the row. No member value later than it enters.
  - **Training and dev:** messages with LastModified at or before the cutoff (rule_rn.md L36-38).
  - **Serving and forward:** that rule **and** our `fetched_utc` at or before the cutoff (the recorder's
    fetched-rule table).
  - **Train/serve parity:** the train-side and serve-side spread are byte-equal whenever every member was fetched
    before the cutoff.
  - **Disclosure:** the share of rows where they differ is reported, never silently dropped.
- **Captured-input replay:**
  - The forward spread is recomputed only from the recorder's per-day `gefs_member_rows.jsonl`. Its sha is pinned
    in each day manifest.
  - Each emission records the manifest sha it read, so replay recomputes the same column bit for bit.
  - No Open-Meteo `global_ensemble` column is used. The captured `day_member_high_p10/p90` serve only as
    R-O-style parity precondition P.
- **Builders:**
  - **Dev:** extend `weather.calibration.spread_information_rung` (L15's R-Q module on `claude/spread-info-20261026`).
    Its tabulated-kernel scale search already takes a per-row x.
  - **Forward:** add a **new sibling module**, for example `weather.calibration.rq_spread_frame`. It reads MG-2's
    forward layout through `l6g_forward_frame.read_layout`, imported unchanged, and joins the spread column.
  - **Pinned for L6_G's screen; do not edit:** `l6g_forward_frame.py` (blob `75a587b0`, pinned by the 2026-10-29
    B-1 clarification) and the pooled_residual_model blob `80a585e8`.
  - **Arm form:** an L6-family scale modulator, s' = max(floor, s·e^m), m = clip(β_h·x, ±ln 2) (R-S/R-Q form).
    - It wraps L6's outputs as its own arm vector, as L6_G does.
    - MG-2's bound composite is never modified.
    - At β = 0 it is byte-identical to L6.

## 3. Gate rule (for a separately named R-QF; R-Q keeps its own registered gates)

1. **Dev gate 1 (history):** nested LOYO Aug-Sep 2021-25 on P3d_N_fix vs unmodulated, exactly R-Q gate 1.
   - Comparator: the unmodulated arm; the R-A control reproduced to 1e-9.
   - Metric: per-row Brier difference, pooled 07-12.
   - Interval: date-clustered bootstrap, 2,000 draws, seed 20261024.
   - PASS if the upper bound is below 0.
2. **Dev gate 2:** dev 08-15..09-29 on **L6** (the bound MG-2 arm) vs L6.
   - Metric: dR = mean_cell(Brier_arm − Brier_L6) / mean_cell(Brier_market), band Brier.
   - Interval: fixed-market, date-clustered 95%, 2,000 draws, seed 20260921.
   - PASS if U < 0 and no hour h07..h12 has a lower bound above 0.
   - β is fitted walk-forward on dev, as L6_G's gate 2 (L6 has no 2021-25 history).
   - MG-1 and NEST rows are reported, never gates.
   - Log loss is reported only; Brier decides, as in every rung of this family.
3. **Forward (only after 1 and 2 pass):**
   - Its own pre-registration and its own owner decision under B-1 §10: it reads NBM and would accrue on dates
     shared with B and L6_G.
   - No best-of selection with MG-2 or L6_G.
   - Comparator L6; endpoint, interval and pass rule as L6_G's §5-6.
   - Its look comes after B's and L6_G's.
- **VOID conditions:**
  - precondition P fails (the GEFS p10/p90 parity with the capture on dev snapshots; BLOCKED, not killed);
  - spread coverage below 90% of the scored rows;
  - any pin mismatch: rule, state, recorder or fetch-module blob, or a day manifest sha;
  - forward only: fewer than 40 of 45 countable dates, or a receipt gap leaving more than 10% of rows on the
    LastModified rule while the fetched rule is empty.
- **Ledger:**
  - Open a new DEV_WINDOW_LEDGER row as `pending` before any dev scoring.
  - It is a **candidate** row and counts toward the multiplicity denominator.
  - Kill-register family name: **"GEFS member spread as scale modulator (R9 spread-information family; R-Q / R-QF)"**.
  - On a kill: an EXHAUSTION_REGISTER §6 row with the numbers, window, conditions and a "Reopen if" line.

## 4. Kill check

Grepped: RETRACTED_AND_FALSE_LEADS.md, ESTABLISHED_FINDINGS.md, FINDINGS_DIGEST.md, DEV_WINDOW_LEDGER.md,
EXHAUSTION_REGISTER.md and STATE_OF_PLAY.md on `origin/master`. Terms: spread, GEFS, ensemble, dispersion, width,
uncertainty.

| Prior lever | Status | Covers GEFS member spread? |
| --- | --- | --- |
| R-I, fitted temperature/scale map on P3d_N_fix (X19, EF §10af) | KILL | No. It closes global fitted width maps only; master R9 keeps spread *information* open |
| EF §1c, sharper-everywhere is not edge | finding | No. It binds the form: centred anomaly, no global sharpening, floor kept |
| R-S, NBM-published spread (TXNSD) as scale modulator (X37, ledger row 58) | KILL at gate 2 | No. Different source; R-Q §1 states the distinction |
| R-Z / R-U, HRRR 3x3 spatial spread as width (X38, X39, EF §10al) | CLOSED at P0 | No. Spatial neighbourhood spread, not ensemble dispersion |
| F4 GEFS "mean" (X4, ledger row 12, EF §10y) | KILL (harm) | No. It scored the control-run column as a centre (EF §10s) |
| ECMWF ENS mean (X5) | KILL (null) | No. Centre only; "ENS spread as spread information" is listed as open |
| S7 HRRR time-lagged ensemble | NULL, underpowered | No. HRRR multi-run, not GEFS members |
| T18 EMOS / RV-1 fitted spread forms on captured v2 (register L6 row) | held, unregistered | Partly. Fitted width on the v2 stddev, not GEFS dispersion |
| RETRACTED_AND_FALSE_LEADS | no spread or ensemble entry | — |
| **R-Q (L15), GEFS member SD / warm half-spread** | **pre-registered, code written, not scored, listed running** | **Yes. This is the same lever** |

**Verdict:**
- **Not killed.** Spread information is open under R9, and STATE_OF_PLAY's headline says "GEFS spread open".
- **Already registered as L15's R-Q.** A new lane under that name would duplicate it.
- **Do not open a second rung.** Run R-Q as registered, or register the forward L6-family form under a new name that
  inherits R-Q's kill breadth.
