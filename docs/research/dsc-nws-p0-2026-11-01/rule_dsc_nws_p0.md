# DSC-NWS market-residual P0 at 07-12 (ruling R28a, lane L40, 2026-11-01)

**Status: DRAFT, S0 only, revision 2.** This revision applies master's ACCEPT-WITH-FIXES on `1aff095c8`
(items 1-9 and the three non-blocking notes). It is not frozen. The arm set (§3) is fixed by the S0
inputs-only screen in [s0_report.md](s0_report.md). No P0 statistic or outcome has been computed for this rule.
The single run waits until master re-checks and the rule is frozen. Development evidence (dev window,
provisional).

**Question:** at local hours 07-12, does the market under-react to a capture-time disagreement between the
station nowcast and NBM, or over-anchor on the free NWS gridpoint high? Either would show up as a signal that
predicts the market's own error at the same snapshot.

## 0. Claim and kill check (done before any design)

Each family below was checked against the findings digest, the exhaustion register and the dev-window ledger.

- **NWS gridpoint high as a point kernel.** Register S16 marks it TESTED-UNDERPOWERED (EF §10h). That test
  asked whether the NWS high is a better centre than the served model. This rule asks a different question:
  whether the market's error moves with the NWS high's distance from the market's own centre, or from NBM.
  No NWS-level *model* arm is built here; see §3.2.
- **NWS revisions.** S17 is TESTED-NO-INCREMENT (a blur artefact). No revision arm is built.
- **Per-market NWS debias.** S28 (L5 A1 v2+NWS per-market debias) is KILL. No debias arm is built.
- **The market-residual sweep, row 78** (rule `85f8192c…`, X54-X57):
  - It never swept the NWS grid or hourly highs; its rule excludes them at line 112. FADE and GAP are
    therefore untested constructions.
  - X56/X57 (GEFS level centres) had *negative* Δ. A level forecast that the market partly follows produced
    an anti-signal. FADE's sign is set from that result and is disclosed in §3.1 as **informed, not blind**.
- **The morning battery, row 81** (DIS-HN/DIS-NG/RATE at 07-12, all KILL) is the template for this rule.
  Disagreement *between models* is dead at 07-12. W1 is disagreement between the *observed-station nowcast* and
  NBM, which has a different source. §4 screens W1 against DIS-HN and OM-MM-SPREAD.
- **The register drafts.** Nothing in RETRACTED_AND_FALSE_LEADS or on the open register-draft branches retracts
  an NWS market-residual construction. No retracted lead is rebuilt.

## 1. Population and data (as rule `85f8192c…` §1)

- **Layout:** `C:/swarm/v3layout`, manifest
  `4d53fdbdc551f33e331fa3b51cc425e354eec4426c8c7b52910b2e7340915f22`, loaded by `mr_gate.build_tables`.
  - Fit table: burn-in 08-01..08-14 plus the scored dates.
  - Score table: 08-15..09-29.
  - US11, °F.
- **Dates read:** nothing dated 2026-09-30 or later is read, except the single replication in §6, which needs
  its own rule and row.
- **The reserved MG-1 confirmation window is not read.** That window is 2026-10-15 through the provisional
  2026-11-28 (`reserved-confirmation-window.md`), and every date in it is after 09-29. This rule makes no use of
  the MG-2 or MG-3 exemptions.
- **Block:** 07-12 only, by the layout's `local_hour` (7..12).
- **Market:** m = `Table.p_market` (Gamma YES). μ_m and σ_m come from `mr_sweep.band_geometry`.
- **Replay inputs:** `data/inbox/replay-inputs-le0929`, SHA256SUMS sha
  `d9c2ed46a72442c68deb6f6b36784fcf081edc52e2a0d8f024cd6cc1a5a38b82`.

## 2. Capture-time validity

A snapshot is uncovered for an arm unless every input of that arm passes its check below. t_c is the
snapshot's `captured_at_utc`.

| input | definition | validity |
| --- | --- | --- |
| **nws_max** | max of `sources.nws_grid.data.day_rows[].max_temp_native` over finite values | `nws_grid.ok` true and `nws_grid.fetched_at` ≤ t_c |
| **v** (NBM v2 mean) | the layout's `v2_mean`: NBM station-guidance tmax mean, `inputs_snapshots.parquet` | `v2_status` = `available`, `v2_available_basis` = `response_received_at`, `v2_available_at` ≤ t_c, finite |
| **n** (L6 OWN nowcast) | row 30's capture-time nowcast `C:\t\l3\l6cap\nowcasts.parquet` (sha `3806687cd6ad8d38571fd5d17efa5405856300d2f0029ae644e3ad08db4a31f3`), column `n_own`, joined on `row_key` | present, **and** the snapshot's own `sources.metar` record passes the `rule_mr_sweep` §2 METAR check: `ok` true, `fetched_at` ≤ t_c, `data.report_time` ≤ t_c, `data.target_date_match` true |

Notes on each input:

- **nws_max must come only from `day_rows`.** `day_max_native`, `nws_grid_high_raw` and `nws_grid_high` are
  never used.
- **NWS record shape (S0):** every `ok` record at 07-12 carries exactly one `max_temp_native`.
- **The NWS `stale` flag is not used as a filter.** It occurs on 10 fit snapshots, all with `cache_status`
  fallback. Its `fetched_at` still has to pass, and S0 reports its share.
- **v is the layout's NBM v2 mean, not Open-Meteo's `ncep_nbm_conus`** (review item 3).
  - Revision 1 of this table wrongly named the Open-Meteo column. S0 itself (`s0_compute.py` `bafc2bfb…`)
    already used `v2_mean` with the receipt check above, so the decision is to **keep v2_mean**. It is the
    ruling's "NBM v2 mean", and no S0 re-run was needed for item 3.
  - Open-Meteo `ncep_nbm_conus` appears only as the N of the screen-only DIS-HN value (§4), as in row 81.
- **How n was built.** `r0_ols_floor_challenger l6-captured` (module sha `f82b6fc0…`, branch
  `claude/r0-ols-floor-challenger-20261024` @ `ecd8c9ba6`) computes it per snapshot:
  - from the snapshot's own `sources.metar.data.rows`;
  - a row counts only if its observation time + 10 min ≤ t_c;
  - maximum age 90 min, COR rows excluded;
  - the previous day's max comes from D−1's last capture, which is before 07:00 local on every date;
  - the model is fit on IEM Aug-Sep history up to 2025-12-31.
- **The observation-time filter now sits inside a checked record.** The obs + 10 min rule is used only inside a
  record whose receipt passes the METAR check.
- **What the METAR check costs W1** (S0 revision 2):
  - It drops **4,139** of 27,868 fit and **3,215** of 21,111 scored W1-covered snapshots.
  - Every drop is `report_time` > t_c. No snapshot fails on `ok`, `fetched_at` or `target_date_match`.
  - `report_time` is the nominal top of the next hour for routine METARs, so captures at :52-:59 fail by
    0-7.5 min.
  - W1's realised population falls from 12,945 to **9,432**.
- **Not re-checked:** D−1's `prev_dmax` record comes from an earlier capture of the previous event and is not
  re-checked by this gate. This is disclosed in §8.

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
- **FADE:** tilt mass away from the NWS high, measured against the market centre.
- **GAP:** tilt toward NBM, away from the NWS high.

**FADE and GAP both tilt away from NWS.** When nws_max is high, FADE's tilt (σ = −1 on nws_max − μ_m) and GAP's
tilt (σ = +1 on v − nws_max) both point down. The raw-value ρ of −0.490 (§4) is therefore an effective
signed-signal correlation of **+0.49**. They share a direction but are not redundant. FADE measures against
the market centre and GAP against NBM, and BH runs over both.

### 3.1 Intake mechanism (method rule 14)

The prior is that public forecasts are already priced. FADE and GAP are admitted only through a named
mechanism: **crowd anchoring on the most visible free US forecast.** The NWS point forecast is the high shown on
weather.gov and on most consumer apps, so retail traders anchor on it. Its error, relative to the market's own
centre or to a better blend, is then left in the price.

- **The sign is informed by X56/X57**: GEFS level centres gave a negative Δ on this window.
- **The ruling also cites row 90 for the sign.** On origin/master, row 90 is the Toronto ECCC P0 (rule
  `b8718b46…`), and its row reads "pending". L40 found no published result there that bears on an NWS sign.
  **The row-90 link is therefore marked UNVERIFIED**, and the sign rests on X56/X57 alone.
- **A survivor is not an edge.** A survivor must still pass the §6 w gate.

### 3.2 Decided before any read: not tested and not in K

- **W1-0006: dropped.** The L6 OWN model is defined and fit only for local hours 07-12 (`l6.HOURS`). No
  capture-time 00-06 n exists, and the ruling keeps this arm only if S0 names one.
- **NWS level tilt** (a D arm with σ = +1 on nws_max − μ_m, i.e. "follow NWS"): **refused at intake** under
  rule 14, not KILL. It is the already-priced prior with no mechanism, and S16 already scores NWS as a centre.
- **DIS-NWS** (|nws_max − v| or |nws_max − H| as an S arm): **CLOSED-BY-RULE** (rule 15). It extends the
  model-disagreement family, whose siblings are row 81's DIS-HN/DIS-NG and X54/X55, all KILL. It can be
  reopened on a survivor of this P0.
- **NWS revisions, NWS debias:** S17 and S28 (§0).
- **Register rows:** all three proposed register rows are in the S0 report.

## 4. Redundancy screen (S0; result in the S0 report)

The screen uses pooled Spearman ρ on covered fit-table snapshots at 07-12. **An arm is dropped if |ρ| ≥ 0.80**
in any of these pairs:

- GAP against FADE (GAP is kept only if |ρ| < 0.80);
- W1 against DIS-HN-0712's |H − N|;
- W1 against OM-MM-SPREAD.

Result (S0 revision 2, with the METAR gate on W1):

| pair | ρ |
| --- | --- |
| GAP vs FADE | −0.490 |
| W1 vs DIS-HN | −0.035 |
| W1 vs MM-SPREAD | +0.003 |

**No arm is redundant, so K = 3.**

## 5. P0 statistic and decision

The statistic is `mr_sweep.p0_candidate` from rule `85f8192c…` §§4-6 unchanged (rule sha256
`85f8192cc260cadb9a8ec3db010016e9952515a9492de896d8907e68075b1956`), at the run-env pin
`8bb0f9563582885c4d01d34b67476f2563260e43`.

- **Machinery:**
  - Calibration-matched disagreement placebo: J = 20, seeds 20260921 + j, donors within (market, local hour).
  - Population: covered snapshots whose 20 donors are also covered.
  - Floor: MIN_DATES 20, MIN_SNAPS 1,000.
- **Statistic:** Δ = ρ_c − mean_j ρ_pl,j.
- **The p that feeds BH:** `p0_candidate`'s one-sided date-cluster p. It comes from B = 10,000 date-cluster draws,
  seed 20261024, where draw b uses placebo j = b mod 20. An UNTESTABLE arm keeps p = 1.
- **The wider interval.**
  - **Date-clustered:** the 95% interval from the same 10,000 draws.
  - **REV-2 circular block-3:** `c3_kill_tier.block_counts`, BLOCK_LEN 3: ⌈n/3⌉ blocks of 3 consecutive present
    dates, wrapping, truncated to n. **B = 2,000, seed 20261024.** The module is
    `claude/c3-t1-fv-kill-tier-20261031` @ `b1d8e65fd577b16da8f3a278cb80fa7ea1e0f4ad`, imported only, as in
    `rule_rodc_released_p0` D3.
  - **Combining:** the wider interval takes the min of the two lowers and the max of the two uppers.
    SE_wider is the larger bootstrap SD (ddof 1).
- **Multiplicity:** Benjamini-Hochberg at q = 0.10 over K = 3.

### 5.1 Verdict per arm, assigned in this order

The first matching step decides.

1. **UNTESTABLE (coverage):** the population fails the floor (fewer than 20 dates or fewer than 1,000
   snapshots).
2. **UNTESTABLE at edge (C5):** that arm's C5 edge-reach control fails (§5.2).
3. **UNTESTABLE at edge (power):** in-run power Φ(0.2236/SE_wider − 1.96) < 0.5.
4. **KILL at edge:** the wider upper bound < 0.2236 (√0.05).
5. **SURVIVOR:** BH rejects and the wider lower bound > 0.
6. **INCONCLUSIVE:** anything else. It does not move forward.

None of these is an edge claim.

### 5.2 Controls

Any miss of C0-C3 refuses the whole run. A C5 miss makes only that arm UNTESTABLE at edge.

**C0: reproduce S0.** Before any label is attached, the run must reproduce exactly, per arm:

- fit covered, scored covered, and population snapshots / dates (S0 revision 2, `s0.json` `025b4780…`):

  | arm | fit covered | scored covered | population (snapshots / dates) |
  | --- | --- | --- | --- |
  | W1-0712 | 23,729 | 17,896 | 9,432 / 43 |
  | NWS-FADE-0712 | 28,796 | 21,693 | 21,391 / 43 |
  | NWS-GAP-0712 | 28,796 | 21,693 | 21,391 / 43 |

- GAP-vs-FADE ρ = −0.49003, within 1e-4.

**The run's extraction is new code.** The pinned `mr_sweep.record_features` extracts neither `nws_grid` nor the
`metar` `report_time`/`target_date_match` gate used here for n. The run's extraction re-implements S0's rules
(`extract_s0.py` `c70dee7b…` and `extract_metar_v1.py` `188dab67…`) in the module, and C0 is its parity
check. v comes from the layout columns via `build_tables`.

**C1: served reference.** Reproduce served 1.774 / 1.526.

**C2: MG-1 07-12 excess.** Reproduce 0.0120.

**C3: identity.** `market_blend.w0_identity` holds at w = 0.

**C5: edge-reach control (row 94's C5; per arm, on that arm's real population).**

- **Planted distribution:** Gaussian bands centred at μ_m + s · (y_mid − μ_m) + ε, width σ_m.
  - ε ~ N(0, sd(y_mid − μ_m)), seed 20261101.
  - **s = 0.75, frozen here.** That is X85's plant, which reached only Δ 0.180 on this window.
- **SYN+:** the plant replaces the arm's signal input in `p0_candidate`, with the arm's own population, donors
  and seeds.
- **SYN−:** the same with centre μ_m − s · (y_mid − μ_m) + ε.
- **PASS iff both hold:**
  - SYN+'s wider lower bound > 0 **and** its wider upper bound ≥ 0.2236;
  - SYN−'s wider upper bound < 0.
- **Failure:** the arm is **UNTESTABLE at edge**, not KILL.
- **Not a candidate:** C5 reads the outcome deliberately, as a planted control. It is not an oracle candidate.

### 5.3 Label order (two stages)

**Stage 1 (outcome-free; template `rodc_released_p0 --rehearse-to-table` at `d4ebc9576`).**

- It stops before `sc.Table` is built: no label column is loaded or accessed.
- It writes the per-snapshot arm values and the population masks to a parquet and records its sha256 in the
  receipt.
- It writes C0's counts and ρ.
- A C0 miss stops the run here.

**Stage 2.** It requires the Stage 1 sha and refuses a second look. Steps, in order:

1. Attach the labels (`sc.Table`).
2. Run C1, C2, C3 and C5.
3. Run `p0_candidate` per arm, then BH and §5.1.

### 5.4 Power (method rule 16, projected on the realised population)

- **Template:** `rodc_released_p0 --rehearse-to-table` at `d4ebc9576`.
- **Formula:** power = Φ(Δ_edge/SE − 1.96), with SE = SE_ref · √(N_ref/N_arm) and Δ_edge = 0.2236.
- **SE_ref:** RATE-0712 (row 81), SE 0.02296 at N 14,820. This is the most conservative row 81 reference.

| arm | realised scored population (snapshots / dates) | projected SE | power at edge | power at 2 × SE |
| --- | --- | --- | --- | --- |
| W1-0712 | 9,432 / 43 | 0.0288 | ≥ 0.9999 | 0.973 |
| NWS-FADE-0712 | 21,391 / 43 | 0.0191 | ≥ 0.9999 | ≥ 0.9999 |
| NWS-GAP-0712 | 21,391 / 43 | 0.0191 | ≥ 0.9999 | ≥ 0.9999 |

This projection does not decide anything; the in-run power gate in §5.1 does.

## 6. Survivors only

1. **w gate:** `mr_gate.gate_candidate(arm, "07-12", …, p_placebo_fit = the j = 0 placebo)`. **PASS iff all
   four hold** (rule `37cb46be`):
   - mean w ≥ 0.05;
   - blend R date upper < 1;
   - blend − placebo upper < 0;
   - blend − floor-only upper < 0.
2. **Freeze and blind accrual** (method rules 8-9). Nothing after 09-29 is read for a survivor under this rule.
3. **The one exception: a replication of an NWS-FADE or NWS-GAP survivor on X87's released cells.** It is not
   part of this rule. It needs:
   - its own rule and its own ledger row;
   - a rule-9 claim check, re-confirmed by master before it runs;
   - a population that **excludes Austin 10-03 and all Denver cells**.
4. **W1 never goes there** (DL 10-30).

## 7. Module contract and execution

- **Code:** a new `loyo_screen` subcommand, `dsc-nws-p0`, on a run branch.
  - It is a module diff to master and touches no B-bound file; B-bound modules are imported read-only.
  - It has two stages, `stage1` and `stage2` (§5.3).
  - It reads the nowcast parquet above by sha.
  - It extracts nws_max and the METAR gate by the S0 rules (§2).
  - It calls `p0_candidate` at the pin.
- **Run:** a clean tree, then each stage through one `powershell -File scripts\ops\workstation_heavy.ps1
  -Queue …` run, serially.
- **Receipt:** run-env HEAD, driver sha, layout manifest sha, replay SHA256SUMS sha, nowcast parquet sha, the
  Stage 1 parquet sha, malformed lines, coverage, C0-C5, and every Δ / interval / SE / power / p / q / verdict,
  with per-date rows.
- **Archive:** `C:\archive\ruled-out\dsc-nws-p0-2026-11-01\` for any killed or UNTESTABLE arm, plus an INDEX
  line.
- **Ledger row and multiplicity:**
  - **Row number:** proposed **107, or the next free number across origin branches at registration**. The row
    opens strictly after L21's row 106 and after the T+1 freeze commit is on origin (conflict C21). This rule
    claims no number.
  - **Denominator:** the multiplicity denominator is **the dev-window reuse count published at registration
    + 1**. If the T+1 freeze publishes a reuse count of 205 and nothing else is registered in between, this
    row's count is 206.

## 8. Disclosures

- **What S0 read.**
  - S0 read market prices (μ_m, through `band_geometry`) for the FADE values and the population.
  - **Labels were loaded in S0**, by `mr_gate.build_tables` / `sc.Table`, on dev dates ≤ 09-29. They were
    never accessed.
- **The run uses new extraction code.** The S0 values come from L40's own extraction of `nws_grid`, `metar` and
  the Open-Meteo screen fields, not from the pinned `record_features`. C0 binds the run to them.
- **The nowcast receipt is checked on the D record only.** It is checked on the snapshot's own METAR record. The
  D−1 `prev_dmax` input comes from an earlier capture and is not re-gated.
- **The 07-12 US dev window is the most-read morning block:** the parity swarm, MG-1, the MR gate, rows 78 and
  81, and R-ODC have all read it.
