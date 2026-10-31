# DRAFT: HRRR forward-recorder parity plan, R-R addendum (h07-12, RN-1 point rule)

**Status: DRAFT, NOT APPLIED.**
- Drafted by L2 on 2026-10-26 under R-R's gate-4 WIN clause (`rule_rr.md` `e3d92e1a…bb22`).
- It extends `hrrr_forward_recorder_parity_plan_DRAFT.md` (sha `66ad9599…a8eba8`, R-K, 13-16). Everything there
  applies, with these changes.

## 1. Scope

- **Cutoff hours:** h07-h12 are added to h13-16. The window is still [h:00, 17:00 local]; fhs ≤ 18 hold, with zero
  windows truncated at f18 (L13 planner).
- **Variables:** TMP 2 m and TCDC entire atmosphere only. There is no DPT and no wind.

## 2. Point rule (new recorder fields)

- **Values:** the recorder stores the full 3x3 block per message (`block3x3`, `neighbourhood()` order: row-major,
  south to north, west to east) and the value at the RN-1 chosen cell.
- **Per-station metadata, pinned in the release:**
  - `land_sha256` = `22069beb…d7fd6`;
  - LAND message sha `10c7fb85…7e1c29`;
  - `stations_json_sha256` `52e8bb5f…0abe3`;
  - `rn1_chosen_index` per station (KSFO 3, every other R0 station 4).
- **Refusal:** the serve path recomputes the chosen index from (fi, fj) and the LAND block, exactly as
  `rr_point_rule` does, and refuses on any mismatch.
- **LAND is static:** a change of HRRR version or grid is a new point rule, not a silent update.

## 3. Parity tests before any forward day is scored

1. **Value parity:** recorder value = `block3x3[chosen]` from an independent AWS byte-range read, with |Δ| ≤ 1e-6 K
   and 1e-6 % on a sample of at least 200 (cycle, fh, station) messages across all 11 stations. KSFO must be
   included at index 3.
2. **Selection parity:** for each forward (station, date, h07-12) row, the recorder's cycle and fhs equal a re-run
   of L13's selector on the recorded `LastModified` (availability + 10 min ≤ h:00). There may be zero mismatches.
3. **Missingness parity:** when no cycle qualifies, the row is `k_miss` = 1, with no fallback to an older cycle
   beyond the selector's lookback 4.
4. **Feature parity:** `k_max`, `k_gap` and `k_tcdc` computed live equal the `rk_columns` recomputation from the
   stored values to 1e-9 °F / %. `k_gap` uses the row's own captured `usable_v2_mean`.
5. **Open-Meteo check (reported only):** compare the RN-1 cell against the captured Open-Meteo `hrrr_high` per
   station. KSFO's gap should shrink from about 7.4 °F (nearest cell) to the 0.5-1 °F range of the other stations.
   If it does not, that is a flag, not a gate.

## 4. Release binding per snapshot

The release binds `hrrr_cycle_utc`, `hrrr_fhs`, `hrrr_msg_sha256[]` (TMP and TCDC), `point_rule = "RN-1"`,
`rn1_index` and `land_sha256`. A snapshot missing any of them is served with `k_miss` = 1 and logged.
