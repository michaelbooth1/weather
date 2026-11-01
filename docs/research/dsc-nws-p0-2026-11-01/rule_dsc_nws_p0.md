# DSC-NWS market-residual P0 at 07-12 (ruling R28a, lane L40, 2026-11-01)

**Status: DRAFT, S0 only.** The arm set (§3) is fixed by the S0 inputs-only screen in
[s0_report.md](s0_report.md). No statistic, label or outcome has been computed for this rule. The single run
waits until master accepts S0. Development evidence (dev window, provisional).

**Question:** at local hours 07-12, does the market under-react to a capture-time disagreement between the
station nowcast and NBM, or over-anchor on the free NWS gridpoint high? Either would show up as a signal that
predicts the market's own error at the same snapshot.

## 0. Claim and kill check (done before any design)

Each family below was checked against the findings digest, the exhaustion register and the dev-window ledger.

- **NWS gridpoint high as a point kernel.** Register S16 marks it TESTED-UNDERPOWERED (EF §10h). That test
  asked whether the NWS high is a better centre than the served model. This rule asks a different question:
  whether the market's error moves with the NWS high's distance from the market's own centre. No NWS-level
  *model* arm is built here; see §3.2.
- **NWS revisions.** S17 is TESTED-NO-INCREMENT (a blur artefact). No revision arm is built.
- **Per-market NWS debias.** S28 (L5 A1 v2+NWS per-market debias) is KILL. No debias arm is built.
- **The market-residual sweep, row 78** (rule `85f8192c…`, X54-X57):
  - It never swept the NWS grid or hourly highs; its rule excludes them at line 112. FADE and GAP are
    therefore untested constructions.
  - X56/X57 (GEFS level centres) had *negative* Δ. A level forecast that the market partly follows produced
    an anti-signal. FADE's sign is set from that result and is disclosed in §3 as **informed, not blind**.
- **The morning battery, row 81** (DIS-HN/DIS-NG/RATE at 07-12, all KILL) is the template for this rule.
  Disagreement *between models* is dead at 07-12. W1 is disagreement between the *observed-station nowcast* and
  NBM, which has a different source. §5 screens W1 against DIS-HN and OM-MM-SPREAD.
- **Row 90 and the register drafts.** Nothing in RETRACTED_AND_FALSE_LEADS or on the open register-draft
  branches retracts an NWS market-residual construction. No retracted lead is rebuilt.

## 1. Population and data (as rule `85f8192c…` §1)

- **Layout:** `C:/swarm/v3layout`, manifest
  `4d53fdbdc551f33e331fa3b51cc425e354eec4426c8c7b52910b2e7340915f22`, loaded by `mr_gate.build_tables`.
  - Fit table: burn-in 08-01..08-14 plus the scored dates.
  - Score table: 08-15..09-29.
  - US11, °F. **Nothing dated 2026-09-30 or later is read**, except the single replication in §7.
- **Block:** 07-12 only, by the layout's `local_hour` (7..12).
- **Market:** m = `Table.p_market` (Gamma YES). μ_m and σ_m come from `mr_sweep.band_geometry`.
- **Replay inputs:** `data/inbox/replay-inputs-le0929`, SHA256SUMS sha
  `d9c2ed46a72442c68deb6f6b36784fcf081edc52e2a0d8f024cd6cc1a5a38b82`.

## 2. Capture-time validity

A snapshot is uncovered for an arm unless every input of that arm passes its check below.

| input | definition | validity |
| --- | --- | --- |
| **nws_max** | max of `nws_grid` `data.day_rows[].max_temp_native` over finite values | `ok` true and `fetched_at` ≤ `captured_at_utc` |
| **v** (NBM v2 mean) | Open-Meteo multimodel `day_model_highs.ncep_nbm_conus` | `ok` true and `fetched_at` ≤ `captured_at_utc` |
| **n** (L6 OWN nowcast) | row 30's capture-time nowcast `C:\t\l3\l6cap\nowcasts.parquet` (sha `3806687cd6ad8d38571fd5d17efa5405856300d2f0029ae644e3ad08db4a31f3`), column `n_own`, joined on `row_key` | present for that snapshot |

Notes on each input:

- **nws_max must come only from `day_rows`.** `day_max_native`, `nws_grid_high_raw` and `nws_grid_high` are
  never used.
- **NWS record shape (S0):** every `ok` record at 07-12 carries exactly one `max_temp_native`.
- **The `stale` flag is not used as a filter.** It occurs on 10 fit snapshots, all with `cache_status`
  fallback. Its `fetched_at` still has to pass, and S0 reports its share.
- **How n was built.** `r0_ols_floor_challenger l6-captured` (module sha `f82b6fc0…`, branch
  `claude/r0-ols-floor-challenger-20261024` @ `ecd8c9ba6`) computes it per snapshot:
  - from that snapshot's own captured METAR rows;
  - a row counts only if its observation time + 10 min ≤ the capture time;
  - maximum age 90 min, COR rows excluded;
  - the previous day's max comes from D−1's last capture, which is before 07:00 local on every date;
  - the model is fit on IEM Aug-Sep history up to 2025-12-31.

## 3. Arms (K = 3)

The types are those of rule `85f8192c…` §4:

- **S:** s = g_z((z − μ)² − σ²)/σ².
- **D:** s = σ · g_z · (z − μ)/σ_m.
- g_z is the arm value standardised within market over that arm's covered fit-table snapshots at 07-12.
- No parameter is fitted.

| # | id | type, sign | value g |
| --- | --- | --- | --- |
| 1 | W1-0712 | S, σ = +1 | ln max(\|n − v\|, 0.25) |
| 2 | NWS-FADE-0712 | D, σ = −1 | nws_max − μ_m |
| 3 | NWS-GAP-0712 | D, σ = +1 | v − nws_max |

What each arm says:

- **W1:** when the station-driven nowcast and NBM disagree, widen the distribution.
- **FADE:** where the NWS high sits away from the market centre, tilt mass *away* from it. This is the
  rule-14 anchoring mechanism (§3.1).
- **GAP:** tilt toward NBM where NBM is above NWS.

### 3.1 Intake mechanism (method rule 14)

The prior is that public forecasts are already priced. FADE is admitted only through a named mechanism:
**crowd anchoring on the most visible free US forecast.** The NWS point forecast is the high shown on
weather.gov and on most consumer apps, so retail traders anchor on it. Its error, relative to a better
blend, is then left in the price.

- The sign σ = −1 is **informed** by X56/X57 (level forecasts gave a negative Δ) and by row 90. It was not
  chosen blind.
- A FADE survivor must still pass the §6 w gate. A survivor with no w is not an edge.

### 3.2 Decided before any read: not tested and not in K

- **W1-0006: dropped.** The L6 OWN model is defined and fit only for local hours 07-12 (`l6.HOURS`). No
  capture-time 00-06 n exists, and the ruling keeps this arm only if S0 names one.
- **NWS level tilt** (a D arm with σ = +1 on nws_max − μ_m, i.e. "follow NWS"): **refused at intake** under
  rule 14. It is the already-priced prior with no mechanism. S16 already scores NWS as a centre. Proposed
  register row in the S0 report.
- **DIS-NWS** (|nws_max − v| or |nws_max − H| as an S arm): **CLOSED-BY-RULE** (rule 15). It extends the
  model-disagreement family, whose siblings are row 81's DIS-HN/DIS-NG and X54/X55, all KILL. It can be
  reopened on a survivor of this P0. Proposed register row in the S0 report.
- **NWS revisions, NWS debias:** S17 and S28 (§0).

## 4. Redundancy screen (S0; result in the S0 report)

The screen uses pooled Spearman ρ on covered fit-table snapshots at 07-12. **An arm is dropped if |ρ| ≥ 0.80**
in any of these pairs:

- GAP against FADE (GAP is kept only if |ρ| < 0.80);
- W1 against DIS-HN-0712's |H − N|;
- W1 against OM-MM-SPREAD.

The result: GAP vs FADE −0.490, W1 vs DIS-HN −0.034, W1 vs MM-SPREAD +0.004. **No arm is redundant, so K = 3.**

## 5. P0 statistic and decision

The statistic is `mr_sweep.p0_candidate` from rule `85f8192c…` §§4-6 unchanged (rule sha256
`85f8192cc260cadb9a8ec3db010016e9952515a9492de896d8907e68075b1956`), at the run-env pin
`8bb0f9563582885c4d01d34b67476f2563260e43`.

- **Machinery:**
  - Calibration-matched disagreement placebo: J = 20, seeds 20260921 + j, donors within (market, local hour).
  - B = 10,000 date-cluster draws, seed 20261024.
  - Population: covered snapshots whose 20 donors are also covered.
  - Floor: MIN_DATES 20, MIN_SNAPS 1,000. Below the floor the arm is UNTESTABLE: p is set to 1 and it stays
    in K.
- **Statistic:** Δ = ρ_c − mean ρ_pl.
- **Interval:** the **wider** of the date-clustered 95% interval and the REV-2 circular block-3 bootstrap
  interval.
- **Multiplicity:** Benjamini-Hochberg at q = 0.10 over K = 3.
- **Verdicts:**
  - **SURVIVOR** iff BH rejects and the wider lower bound > 0.
  - **KILL at edge** iff the wider upper bound < 0.2236 (√0.05).
  - Otherwise the arm is **INCONCLUSIVE** and does not move forward.
- **Label order:** labels and outcomes are attached only after the arm values, the populations and the controls
  are frozen in the receipt.

### 5.1 Controls (run first; any miss refuses the run)

1. **Served reference:** reproduce served 1.774 / 1.526.
2. **MG-1 07-12 excess:** reproduce 0.0120.
3. **Identity:** `market_blend.w0_identity` holds at w = 0.
4. **Synthetic checks:**
   - SYN+ (a planted positive signal) must be recovered as a SURVIVOR;
   - SYN− (a sign-flipped plant) must not be a SURVIVOR.

### 5.2 Power (method rule 16, projected on the realised population)

- **Template:** `rodc_released_p0 --rehearse-to-table` at `d4ebc9576`.
- **Formula:** power = Φ(Δ_edge/SE − 1.96), with SE = SE_ref · √(N_ref/N_arm) and Δ_edge = 0.2236.
- **SE_ref:** RATE-0712 (row 81), SE 0.02296 at N 14,820. This is the most conservative row 81 reference.

| arm | realised scored population (snapshots / dates) | projected SE | power at edge |
| --- | --- | --- | --- |
| W1-0712 | 12,945 / 43 | 0.0246 | ≥ 0.9999 |
| NWS-FADE-0712 | 21,391 / 43 | 0.0191 | ≥ 0.9999 |
| NWS-GAP-0712 | 21,391 / 43 | 0.0191 | ≥ 0.9999 |

Power stays ≥ 0.995 at twice the SE. The break-even SE is 0.114.

## 6. Survivors only

1. **w gate:** `mr_gate.gate_candidate(arm, "07-12", …, p_placebo_fit = the j = 0 placebo)`. **PASS iff all
   four hold** (rule `37cb46be`):
   - mean w ≥ 0.05;
   - blend R date upper < 1;
   - blend − placebo upper < 0;
   - blend − floor-only upper < 0.
2. **Freeze and blind accrual** (method rules 8-9). Nothing after 09-29 is read for a survivor.
3. **The one exception:** an NWS-FADE or NWS-GAP survivor gets a single replication on X87's released cells.
   **W1 never goes there** (DL 10-30).

## 7. Module contract and execution

- **Code:** a new `loyo_screen` subcommand, `dsc-nws-p0`, on a run branch. It is a module diff to master and
  touches no B-bound file; B-bound modules are imported read-only.
  - It reads the nowcast parquet above by sha.
  - It extracts nws_max and v by the S0 extraction rules (§2).
  - It calls `p0_candidate` at the pin.
- **Run:** a clean tree, then one `powershell -File scripts\ops\workstation_heavy.ps1 -Queue …` run.
- **Receipt:** run-env HEAD, driver sha, layout manifest sha, replay SHA256SUMS sha, nowcast parquet sha,
  malformed lines, coverage, controls, every Δ / interval / p / q / verdict, and per-date rows.
- **Archive:** `C:\archive\ruled-out\dsc-nws-p0-2026-11-01\` for any killed arm, plus an INDEX line.
- **Ledger row:** proposed **107, or the next free number across origin branches at registration**. It must
  be strictly after L21's row 106 and after the T+1 freeze commit (205) is on origin (conflict C21). This
  rule claims no number.

## 8. Disclosures

- **S0 read market prices** (μ_m, through `band_geometry`) for the FADE screen and population only. The label
  columns were loaded by `sc.Table` but never accessed.
- **The screen values come from L40's own extraction** of `day_high_spread`, `day_model_highs`, `ok` and
  `fetched_at`, not from the pinned `record_features`. The run uses the module's extraction, and the receipt
  restates the screen.
- **The nowcast receipt check uses observation time** (+10 min, within the snapshot's own record), not the METAR
  `fetched_at`.
- **Window:** the 07-12 US dev window is the most-read morning block (parity swarm, MG-1, MR gate, rows 78 and
  81, R-ODC).
