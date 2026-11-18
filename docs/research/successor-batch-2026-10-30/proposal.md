# Successor batch proposal (2026-10-30)

Status: PROPOSAL. No freeze, no prereg commit, no ledger row has been written.
This document is a research artifact under MODEL_IMPROVEMENT_METHOD §5 rule 5:
sub-MDE levers are assembled into one batch rather than screened one by one.
Item 11 (WS L-D, 11-02..11-10) owns assembly and freeze.

Data boundary for everything here: history up to and including 2026-09-29 only.
No outcomes, labels, prices or market data after 09-29 were read. Nothing in this
document reads or prepares the 09-30..10-14 window (item 12 owns that read).
No B-bound file is edited (mg2_composite.RELEASE_FILES, pooled_residual_model.py,
B_FORWARD_TEST_DESIGN.md, mg2 binding docs).

## 1. Lever eligibility

Sources: LEVER_INVENTORY_2026-10-26, EXHAUSTION_REGISTER §3 (stop list) and §6
(rows X1..X70), FINDINGS_DIGEST, STATE_OF_PLAY, DEV_WINDOW_LEDGER rows to 81
(same-day 10-30 kills: rows 74..81).

Eligibility test (all three must hold):
- E1: positive history evidence (helpful-side point estimate, underpowered; not a
  harm, not a clean null);
- E2: not in an exhausted family (§3 stop list) and not KILLed;
- E3: not killed by name or family on 10-30 (rows 74..81, SoP, same-day lanes).

| Lever | History evidence (ΔBrier, helpful < 0) | E1 | E2 | E3 | Verdict |
| --- | --- | --- | --- | --- | --- |
| R-ODC low_so_far (07-12, Oct-Dec) | joint NEST−G1 −0.000876 [−0.00145, −0.00029] (row 69); proxy −0.00103 (row 70); comparator was HRRR-carrying G1 | yes | yes | yes, but adjacent to RATE-0712 (row 81) | ELIGIBLE, needs per-component Oct-Dec LOYO on the live SM-L6 incumbent (C1) and a redundancy screen vs RATE-0712 |
| R-ODC dewpoint component | inside row 69 joint estimate | — | `td` is already in L6 OWN | MET-DEWDEP killed vs market (rows 74..81) | DROPPED: already served by the incumbent |
| R-PD (L6 own-obs on NBM, 00-06), X31 | gate-1 LOYO −0.0047 [−0.0073, −0.0022], Aug-Sep 2021-25 only; dev −0.0232 [−0.0520, +0.0047]; CLOSED not killed; P1 PASS (PD-1, 0.99919) | yes | yes | yes | ELIGIBLE, needs Oct-Dec LOYO (C2); current evidence is out of season |
| MRMS echo flag (13-16), X7 | −0.0005 [−0.0010, −0.0001] over t3-r3; reopen text names a batched package | yes | yes | yes | DEFERRED: no 2021-25 MRMS history, capture change held (DL 10-24); cannot be LOYO'd or served |
| L6_G (R-O) | dev −0.00932 | yes | — | — | NOT IN BATCH: already its own bound forward screen |
| R-N HRRR 2 m max 00-06, X32 | — | — | extra daily-max NWP | HRRR family killed (X44/X45) | EXCLUDED |
| P3d_H Oct-Dec, X41 | −0.0063 | yes | — | HRRR vs market killed, MG-3 dropped | EXCLUDED |
| TXNSD X37, GEFS SD X43 | — | — | spread used as a scale | — | EXCLUDED |
| NBS TXN X35, A2 X8, X42 | — | — | KILL | — | EXCLUDED |
| R-F blends X17 | — | — | closed | — | EXCLUDED |
| R-G X18, R-J X20 trajectory columns | sub-bar positive | yes | R10 allows Oct-Dec | trajectory/tracking killed 10-30 (X66..X70, RATE-0712 row 81) | EXCLUDED (flag: reopen only via the frozen RISE-T3R3 replication, row 80) |
| L4 h15-23 X6 | — | — | extra NWP | — | EXCLUDED |
| X11 | — | — | extra station feed | — | EXCLUDED |
| X30, X40 | harm | no | — | — | EXCLUDED |
| X14 | served-path precondition, not a lever | — | — | — | N/A |
| Toronto NBM A/B X64/X65 | — | — | — | killed 10-30 | EXCLUDED |
| 17-arm market-residual sweep X46..X62 (incl. MET-MAX, MET-COOLING, MET-DEWDEP, MET-COVER) | — | — | — | killed 10-30 | EXCLUDED |
| TRK/PROJ/RISE X66..X70 | positive points | — | — | killed 10-30; reopen text: positive points are not a reopen reason | EXCLUDED |
| DIS-HN/DIS-NG 0006/0712, RATE-0712 (row 81) | clean nulls | no | — | killed 10-30 | EXCLUDED |

Result: two eligible levers (R-ODC-low, R-PD), one deferred (MRMS).

## 2. Missing per-component Oct-Dec LOYO (pre-declared)

Both components lack an Oct-Dec 2021-25 LOYO against the incumbent that would
actually serve. The runs below are pre-declared here; this file's sha256 at the
commit that adds it is the rule hash. One run per component.

Common: history 2021-10-01..2025-12-31, months 10-12 only, leave-one-year-out
(fit on the other four years, score the held-out year), Brier on the settlement
proxy (WU), no data after 2026-09-29. Report per-year and per-month ΔBrier,
dates-paired σ_d, lag-1 autocorrelation, block-3 SE and a dates-paired 95% CI.

### C1. R-ODC-low on SM-L6 (07-12)

- Incumbent: season-matched L6 (`season_matched_l6.fit_state` on Oct-Dec rows,
  OWN features), scored through the MG-2 l6_stack with the frozen coefficients
  (sha 4bc51e03…), as in the SM-L6 LOYO (rule 81649748…).
- Arm: identical, with OWN + `low_so_far` (running min of the WU-proxy temp since
  local midnight, availability valid_utc + 10 min, merged as of the query time,
  then min with `t`) and `t_minus_low` = t − low_so_far.
- Same HGB_PARAMS, same rows, same coefficients. Nothing refit in the stack.
- PASS: dates-paired upper 95% < 0 and no year or month whose own CI is entirely
  > 0. Otherwise DROP from the batch.
- Redundancy screen, outcome-free: Spearman ρ between `t_minus_low` and the
  RATE-0712 rise-rate column on the scored rows. |ρ| ≥ 0.80 means redundant with a
  killed lever: DROP regardless of C1.

### C2. R-PD Oct-Dec (00-06)

- Incumbent: MG-1 analogue at 00-06 (as in predawn_0006 gate 1).
- Arm: R-PD (L6 own-obs stacked on 01Z NBM), unchanged code, LOYO_MONTHS
  widened to (10, 11, 12).
- Needs the 01Z NBM corpus for Oct-Dec 2021-25 (about 460 dates, about 640 MB,
  free NOAA). Fetch only when no other history fetch is running; it is not
  a rebuild of the frozen caches.
- PASS / DROP as C1.

## 3. Proposed batch (one batch, paired screens)

Contents: R-PD at 00-06 and R-ODC-low at 07-12, each a paired screen against its
own incumbent. A component that fails its own C1/C2 rule is removed before the
freeze; if both fail there is no batch and the successor slot stays empty.

### 3.1 Joint LOYO

- Pool the surviving components over 00-12 market-hours, Oct-Dec 2021-25,
  blocked by year. dR = arm − incumbent per (market, date, hour), averaged to a
  date.
- PASS: dates-paired upper 95% < 0; no year, month or component with a CI
  entirely > 0.
- Pre-declared drop: a component whose own LOYO upper bound is ≥ 0 is removed and
  the joint LOYO is rerun once without it (this is the only rerun).
- Output σ_d, lag-1, VIF and block-3 SE; these are the sizing inputs.

### 3.2 Serve parity per lever

| Lever | Serve-time availability | Receipt dating | Train/serve parity |
| --- | --- | --- | --- |
| R-ODC-low | WU-proxy obs at serve are captured METAR (tgroup_f or tmpf), same transform | captured receipt; avail = valid_utc + 10 min in train, receipt time at serve | low_so_far is computed by `odc_metar_features` (branch claude/rodc-odc-metar-features-20261029, unlanded); dev parity 97.9% exact, forward P1 FROZEN (row 72, D0 10-31, look ≥ 12-15). Needs a new non-B-bound serve function for L6 + low; the B-bound l6_stack / mg_serve_core stay untouched |
| R-PD | 01Z NBM v2 captured; METAR captured | receipt-dated NBM cycle, cutoff 00-06 | P1 PASS under PD-1 (0.99919 exact); Oct-Dec training coverage is the C2 deliverable |

### 3.3 Sizing (§5 rule 6)

- N from the pair's measured σ_d at half the dev (LOYO) effect, ≥ 20 dates,
  power ≥ 0.5, training coverage reaching the last forward date.
- MDE80 = 2.802·σ·√VIF/√N; power 0.5 needs half effect ≥ 1.96·σ·√VIF/√N.
- N_max ≈ 50 in-season dates (D0 ≈ 11-11 to 12-31; NBM history corpus ends 12-16,
  so training coverage caps 00-06 accrual there).
- R-ODC alone (σ_d 0.00462, history effect −0.0007..−0.0009): N80 at half effect
  ≈ 866; power at N = 45 ≈ 0.09 at half effect. Unpowerable alone; it rides in the
  batch only if the joint effect clears the gate.
- If the joint half effect gives power < 0.5 at N_max: STOP and report. Do not
  shrink δ, do not widen the window.
- Futility looks at 7 (harm), 14, 21, 31 accrued dates, MDE inflated 4-7%,
  block-3 intervals reported (rule 7). Blind accrual (rule 8). One date rule
  (rule 9).
- Market P0 in season (rule 3) is only available from the item-12 one-shot
  09-30..10-14 kill-only read (about 11-10). Named here, not prepared.

## 4. What this document does not do

No freeze, no prereg commit, no ledger row, no forward read, no edit to any
B-bound file, no capture-host action.
