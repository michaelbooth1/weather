# MOS against the market: market-residual P0 rule (ledger row 89)

Status: pre-declared before any computation (2026-10-30, lane L3). Evidence class: dev-window kill-only P0
screen. It is its own arm with its own K. It is not pooled with rows 78, 81, 87 or 88. Nothing here is a release,
serving, capture or scheduling decision. Eligibility: coordinator ruling 2026-10-30 (lever map item 3, inventory
row 18). The stated family reason is that MOS is station-specific statistical post-processing of single models,
which the killed raw-grid centres (X46-X49, X52, X53, X56, X57) lack.

## 1. Machinery

The rule is identical to `docs/research/mr-sweep-2026-10-30/rule_mr_sweep.md`
(sha256 `85f8192cc260cadb9a8ec3db010016e9952515a9492de896d8907e68075b1956`), sections 1-5, except where this
file says otherwise.

- Data:
  - layout `C:/swarm/v3layout`;
  - burn-in 2026-08-01..08-14;
  - scored dates 2026-08-15..09-29;
  - e = y - m.
- Signal: market moments with the sigma^2 floor 0.25; the exponential tilt; type C band signal
  s_b = (x - mu_m) * (z_b - mu_m) / sigma_m^2, x in native °F.
- Placebo and bootstrap: the calibration-matched disagreement placebo (`market_blend.placebo_vector`, derangement
  within (market, hour), J = 20, seeds 20260921+j); Delta = rho_c - mean rho_pl; B = 10,000 date-cluster draws
  with seed 20261024; one-sided p.
- UNTESTABLE below 20 covered dates or 1,000 snapshots; per-date rows with the six sufficient sums, plus
  per-market per-date rows.

## 2. Population and hour block

The sweep's fit and score tables: every layout market except toronto. Only snapshots whose local hour is 07..12
inclusive are used. No data after 2026-09-29 is read; MOS rows with a runtime on or after 2026-09-30 00Z are
dropped.

The block is fixed before any read, for these reasons:

- 07-12 carries about two thirds of the remaining excess as sharpness/shape (EF §10ag; lever inventory row 9).
- 13-16 is excluded: dev MOS values were already read with outcomes at h13-15 (X42).
- 00-06 is excluded: a killed family (X31, X32; ledger rows 81 and 86).

## 3. Prior reads of these values (disclosed)

Dev-window MOS/NBE values have already been read with outcomes, in two other estimands:

- S5 (SYN §1.3): MOS/NBE at 00-16 as an increment against the served forecast, -0.0015 [-0.0049, +0.0019].
- X42 (R-V (b), ledger row 56): MOS/NBE day-max (`v_gap`) as an SM-H h13-15 input, KILL.

The 07-12 market-residual estimand of this rule has never been read for any MOS or NBE value.

## 4. Candidates (K = 2)

| id | value | type | sign |
| --- | --- | --- | --- |
| MOS-GFS | GFS MOS (MAV) `n_x` for the target day's daytime maximum | C | + |
| MOS-NAM | NAM MOS (MET) `n_x` for the target day's daytime maximum | C | + |

- Source: the A-IEM-2 forecast-only IEM MOS archive `C:/swarm/data/iem/mos` (MANIFEST.json sha256
  `21844eae6f3398cf4cef4c95b801c1c20383ada008112a1d95cf2eee362bedb3`; `mos_GFS.parquet`
  `94c8ba654e9369dfb59578acbc16bf84f97f7680c2f3a783556416f34e6a5cb4`; `mos_NAM.parquet`
  `32b92d8ab0a3c0c7c33f6f165aebe0a256fe9eb648cc6f91f44a3a9c22f247ca`). The run refuses on a sha mismatch.
- The target day D is the snapshot's market date. The daytime-maximum row is the one whose `ftime` is (D + 1)
  00:00 UTC at the snapshot's layout station.
- The selected value is the latest run (by runtime) whose `available_utc` <= `captured_at_utc` and whose value is
  finite and within [-40, 130] °F. A snapshot without one is uncovered.
- Not tested:
  - NBE `txn`: the NBM extended text, inside the closed NBM-centre family (X22); its TSD/XND spread is inside the
    closed NBM-published-spread family (X37).
  - MEX `n_x`: the extended GFS MOS duplicates MOS-GFS.
  - LAV (LAMP): hourly temperature, no day maximum.

## 5. Availability is modelled, not a capture receipt

Production captures no MOS. `available_utc` is the archive's modelled availability:

- GFS (MAV): runtime + 4 h 30 min, from the NCO production schedule plus a margin;
- NAM (MET): runtime + 4 h 00 min, assumed, not measured;
- MEX: runtime + 5 h 00 min, assumed (not tested here);
- NBE: the measured S3 LastModified (not tested here).

**Sensitivity arm (not in K, reported only):** both candidates recomputed with every model lag + 1 h
(`available_utc` + 1 h). It must not flip the verdict. A candidate SURVIVES only if it also passes the same test
(p <= its BH threshold from the main arm and Delta lower bound > 0) under the sensitivity arm. A main-arm KILL
stays a KILL whatever the sensitivity arm shows; the sensitivity result is reported.

## 6. Decision

- BH at q = 0.10 over K = 2 on the main arm.
- A candidate SURVIVES iff it is testable, BH-rejected, its Delta 95% lower bound is > 0, and the sensitivity
  arm does not flip it (section 5). Otherwise it is a KILL, or UNTESTABLE.
- Only for a survivor: the w = 0 identity control, then the sweep's w gate in block 07-12 with c_pl,0 as the
  placebo.
- One run. Outputs: a receipt JSON; per-date rows plus per-market per-date rows; the extracted feature file.

## 7. Kill and reopen line (written now)

If both candidates are KILL, the MOS-against-the-market family is CLOSED. It reopens only with a captured MOS
feed (a capture-time receipt on the serve grid) plus a new rule, on dates disjoint from the dev window
2026-08-01..09-29. A survivor earns only the MOS recorder question; it is not an adoption.
