# C3 kill tier, Revision 1 (2026-10-31): master D1 revisions (DRAFT, not frozen)

Lane L16. This file amends the reviewed draft
`docs/research/iterate-faster-2026-10-30/c3-t1-fair-value-kill-tier-DRAFT.md`, sha256
`cd4d814f4144a5e0a72d7632f413d000174d2cade4c4ce8d50f0ee5f6f76b5f6` (committed in
`863cbfc2fce1bc38616f67bf82c1f0ece3f3f33a`). The reviewed file is not edited. Master's D1 ruling on it was
**APPROVED WITH REVISIONS**. The C3 rule is that draft as amended here; where they differ, this file wins. The freeze
row pins both shas and the driver sha. Nothing has been read: no row 80 data, and no price or outcome after 09-29.

## 1. Kill semantics at edge size (replaces the draft's §4 KILL row)

**Edge size.** The source is exhaustion register §6, "Edge size and the 5% bar" (L15, commit `815e642c3`, on
origin/master `035f5bb19350d7b56964fbe4d41948b2177ffb02`). For a calibrated market the best linear use of a signal
correlated ρ with the market residual cuts the squared error by ρ². A 5% Brier gain therefore needs
ρ ≥ √0.05 = **0.2236**.

**Check (L16).**
- Let e = y − m. Calibration gives E[e | m] = 0, so the market's Brier per entry is Var(e).
- The best linear predictor of e from s has residual variance (1 − ρ²)·Var(e). The fractional Brier gain is
  therefore ρ², and a 5% gain gives ρ = √0.05 = 0.22361.
- This agrees with the register. Its 3% line also checks: √0.03 = 0.173. So does the 80% MDE factor:
  (1.960 + 0.842)/1.960 = 1.4296.
- **Caveats, recorded rather than corrected.**
  - The register applies Δ_edge to Δ = ρ_c − mean ρ_placebo, not to ρ_c alone. Placebo correlations are near 0 by
    construction, so the two coincide to first order.
  - ρ is the pooled per-entry Pearson correlation. The scorer's Brier is aggregated as a band mean, then an hour mean
    within each cell, so the gain mapping is a linear/Gaussian approximation. The register calls it "necessary, not
    sufficient".

**Δ_edge = √0.05 = 0.2236** (driver `DELTA_EDGE`; `EDGE_GAIN` = 0.05).

**Outcomes and decision order.** These replace the draft's §4 table. The driver's `decide` applies them in this
order:

| Order | Condition | Outcome |
| --- | --- | --- |
| 1 | D < 10, M < 5, or fewer than 200 scored lead-1 event-hours | INCONCLUSIVE (coverage) |
| 2 | Power at edge size (§2) < 0.5, or not computable | **DESCRIPTIVE**: reported only, cannot drop A1 |
| 3 | P0 step: Δ's upper 95% bound < Δ_edge | **KILL at edge size** |
| 4 | P0 does not hold (BH reject and Δ lower bound > 0 both needed) | INCONCLUSIVE ("P0 does not hold; underpowered for information"), never KILL |
| 5 | w holds (the draft's §3 w gate, unchanged) | NOT KILLED |
| 6 | w step: the gain (market − blend) has upper 95% bound < 0.05 × the mean market cell Brier on the scored dates | **KILL at edge size** |
| 7 | Otherwise | INCONCLUSIVE |

- A control failure is still VOID (exit 7).
- The receipt records the deciding step (`decided_by`).
- At step 3, a P0 that holds but stays wholly below Δ_edge is also a KILL at edge size. It is a real signal, but
  too small to matter.
- **w-step wording.** The ruling says "the upper bound of (blend − market) excludes the edge-size gain". The driver
  reads this as the gain's upper bound: the lower 95% bound of (blend − market) > −0.05 × the market Brier. That is
  the only reading in which a kill means "an edge-size gain is excluded". If master meant otherwise, flag it before
  the freeze.
- The interval is the draft's paired date-cluster bootstrap (B 2,000, seed 20261024) over the scored dates.

**Scope (OP2, accepted).** A KILL at edge size drops A1 as a solo arm and keeps A2 and A3. It takes effect by a
dated clarification before the forward freeze. DESCRIPTIVE and INCONCLUSIVE drop nothing.

## 2. Power at edge size (new)

- **SE_Δ** is the standard deviation (ddof 1) of the finite bootstrap draws of Δ. The draws are the same 2,000
  date-clustered replicates that give the P0 interval, built from the per-date sufficient-sum rows (`p0_sums`).
- **VIF** = N_entries × SE_Δ². This is the design effect against the iid standard error 1/√N of a near-zero
  correlation.
- **Power at edge size** = Φ(Δ_edge / SE_Δ − 1.960) = Φ(Δ_edge·√(N/VIF) − 1.960). It is the probability that Δ's
  upper 95% bound falls below Δ_edge when the true Δ is 0 (normal approximation).
- **Power ≥ 0.5 if and only if SE_Δ ≤ 0.2236/1.960 = 0.114**, that is N/VIF ≥ 77. For example, 200 event-hours ×
  8 bands = 1,600 entries tolerate a VIF up to about 21.
- **Rule.** If power at edge size < 0.5, the read runs **DESCRIPTIVE** only (the C3 slice's original frozen class)
  and cannot drop A1.
- **This value cannot be stated before the read.** SE_Δ needs the per-date rows, and reading them before the freeze
  would be a look. The formula and threshold are fixed here, and the driver computes and records `se_delta`, `vif`
  and `power_at_edge`.
- **Projections from register analogues (no new data).**

  | Analogue | 95% half-width | SE | Power |
  | --- | --- | --- | --- |
  | Toronto GEM, ledger row 90 | ±0.157 | 0.080 | ≈ 0.80 |
  | Toronto X64 | ±0.113 | 0.058 | ≈ 0.97 |
  | X69 | ±0.094 | — | ≈ 0.997 |
  | US pooled sweeps | ±0.010..±0.048 | — | ≈ 1 |

  A 14-date, top-ten 88a panel is expected to land between these. That is a projection, not a measurement.
- **The w step's power is reported beside the result and does not gate.** It is Φ(edge_gain / SE − 1.960), with SE
  from the paired bootstrap of (blend − market). The receipt field is `w.power_at_edge_reported`.

## 3. Correction to §7: `e89cbb523` does not land, and no date gate was found

- The draft's §7 listed "embargo edit `e89cbb523` landed" as a dependency. That is wrong (master D1) and is removed.
- **Code-only trace of the frozen builder and scorer at `d937b34ab1d50cd4b8e35e80901184f7f0f82a9f`.** No data was
  read.
  - `src/maker_core/shadow/` does not exist at that commit. `EMBARGO_WINDOWS`, which lives in
    `src/maker_core/shadow/admission.py` (the module `e89cbb523` edits), is absent, and nothing imports it.
  - The gates that do exist are not a 09-30..10-15 embargo:
    - the scorer's `PANEL_START`/`PANEL_END` (09-25..10-08);
    - its `EARLIEST_DATE` 10-09 refusal (`scoring_before_registered_earliest_date`);
    - the "bundle day ≥ today" and "sealed_at in the future" refusals in the scorer and the bundle builder;
    - plugin run windows relative to the bundle day;
    - the reward-config start and end dates.
- **Verdict: run as is.** No in-process override is added, and the driver records
  `date_gate_trace = {embargo_gate_found: false, override_applied: false}`.
- Production code is not edited, and maker economics stay closed.
- Export gating is governed by the export manifest and its owner release (owner 2026-10-30 release of
  2026-09-30..10-14, DECISION_LOG 2026-10-30 row, origin/master `5f4d87818`). It is outside this trace.
- **Revised §7 host-export row:** depends on manifest open points 1 and 4 being ruled, plus a host night. It no
  longer depends on `e89cbb523`.

## 4. Accepted as proposed

- OP1: burn-in of 4 dates.
- OP2: as stated in §1 above.
- OP3: M ≥ 5.
- OP4: (a).
- The placebo choices:
  - rank alignment, with unmatched bands set to s = 0;
  - market-time-zone local hour;
  - the 20-blend w placebo.
- The driver's `PROVISIONAL` record now says "accepted D1" and stays pre-freeze until the ledger row pins it.

## 5. K3 consistency

- Under the new order, K3 still requires:
  - positive → NOT KILLED (which now also needs power ≥ 0.5 and a Δ upper bound ≥ Δ_edge on the synthetic panel);
  - negation → KILL, decided at the P0 edge step (Δ upper < 0 < Δ_edge);
  - null → a Δ interval that covers 0.
- The draft's §5 K3 text otherwise stands.
