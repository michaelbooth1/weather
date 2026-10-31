# S31 v2 Clarification 1 (2026-10-31): in-run power gate, floors before Δ, receipt head, clip diagnostic

Status: clarification to `rule_s31_v2.md` (sha256 `4495b6526e69698bab8bc5e9e0943b2adbd17526a3dc7b8a9fabd30d501b3315`).
Master approved that rule to freeze on 2026-10-31 and named the additions below, which the coordinator relayed.
The rule file is not edited. Lane L14, ledger row 102. This file was written before the v2 run and before any
venue price read under v2.

## 1. In-run power gate (adds to rule §7)

- After the three intervals are computed, each KAL arm gets power at edge,
  **Φ(Δ_edge / SE_widest − 1.96)**, where:
  - Δ_edge is 0.224;
  - SE_widest is the Clarification 5 wider-of-three SE (the maximum of the date-clustered, Clarification 1
    non-circular block-3, and REV-2 circular block-3 SEs);
  - the N is the realised, value-checked population.
- **If power is below 0.5:**
  - the arm is labelled **"UNTESTABLE at edge"** before any Δ verdict;
  - its Δ, intervals and subgroup reads are withheld from the receipt;
  - it enters BH with p = 1, and no w gate runs.
- There is **no rerun**.
- The per-date sufficient sums still go to the rows file, as the audit trail.

## 2. Testability floors are gated before Δ (restates rule §5.7 at arm level)

- An arm is testable only if it has:
  - at least **20 population dates**;
  - at least **1,000 population snapshots**;
  - at least **10 kept seeds**.
- This is checked before Δ or any bootstrap is computed. Otherwise the arm is **UNTESTABLE** (p = 1).
- The receipt records the floor values per arm.

## 3. Receipt head

The receipt's first key is `coverage_summary`. It holds:
- the realised coverage: covered fit snapshots, with the 6-bin and 5-bin counts;
- the 5-bin share and the missing-bin positions;
- the donor counts, including the dropped (snapshot, seed) pairs and the snapshots with no seed;
- per arm: the population, the seeds kept, the seeds dropped entirely, the floors, the power gate and the label.

## 4. Clip diagnostic (decides nothing)

The receipt reports the share of 5-bin snapshots whose imputed missing-bin mass was clipped to 0, that is,
where the five quoted mids summed to more than 1. It is a diagnostic only. No label, gate or threshold reads it.
