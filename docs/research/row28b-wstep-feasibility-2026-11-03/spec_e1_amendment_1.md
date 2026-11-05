# E1 spec amendment 1: the N extract, LOYO states and PIT semantics (create-only)

Lane L59, WS, 2026-11-03. Amends `spec_e1_0712_descriptive.md` (sha256
`0496eaa962b5911587db5a345879f328e6020fcefd251bf8e3d0ed547d28bdd2`, committed at `70a81de10`). That file is not
edited. Label unchanged: **POST-HOC-FILLED DESCRIPTIVE**. Nothing in this amendment has been scored; no label, outcome,
Brier value or loss has been computed or read for E1.

## A1. The blocking gap is ruled: option (i), an outcome-blind N extract

- **Ruling.** Master's STAGED GO on the 07-12 plan (`docs/research/b0712-program-plan-2026-11-03/README.md` at
  `a6dd53c1e`), 2026-11-03: stages 1-2 GO, the N builder from the bound IEM manifests through the serve core.
- **Source.** Only row 28's bound IEM manifests: `manifest_iem.json`
  `17aca6d162316aeb4b391cd145ca830578e8191e1a49a878bb6e93ed699ad61f` and `manifest_iem_gap.json`
  `bdf84209d1ef99c2cff74caf0b81201b63e873944fd2cb8607dc9277fa9fb402`. Each file was sha-checked against its
  manifest's file list before parsing. No download.
- **Path.** The serve core's own functions, unchanged (`src/weather/model/mg_serve_core.py` sha256
  `179fcbe495f36f6fd194c1bd0052ed6e150b0f016adbe0f8e9bb6128bd42e5d8` at `621d67f0f`):
  `parse_captured_metar` (anchor = the IEM observation time), `l6_captured_features`, `routine_dmax` and
  `l6_own_nowcast`. The builder helpers are `n_builder_v1.py` sha256
  `643ea3d64ec81c9e97649734d3664a0085133b7767918a8b4ac5a59894c28d0c` and the h:30 table is built by `n_h30_v1.py`
  sha256 `855614e590d1188393d36057fb0c18732860a657fc27ed8caa0e8a918cdb77a6` (both WS-local, `C:\t\L59\b0712\scripts`).
- **Grid.** US10 × row 28's 660 deciding dates (`6913484a…84bcfb`) × hours 07-12 = 39,600 rows, keyed
  `<ICAO>|<date>|<hh>`.

## A2. PIT semantics

- A history row (station, local date D, hour h) is a nominal snapshot at **D h:30 local**. Forward serving caps N at
  each snapshot's actual `captured_at_utc` (`src/weather/calibration/mg2_composite.py:833-835`, `:846`, `:872`), whose
  minute within the hour is roughly uniform (dev serve features `0d5c30b3…`, 08-01..09-29 rows: median 32, mean 31.4,
  P5 2, P95 57). h:30 is the matching nominal cap and is also L6's own training-history convention
  (`upstream_obs_screen.history_queries`). **Disclosed:** the forward cap varies about ±30 min around h:30; the
  history cap does not.
- A METAR is usable only if its observation time + 10 min ≤ the cap, COR reports are excluded, and an observation
  older than 90 min is not used (the serve core's rules, unchanged).
- **Disclosed:** prev_dmax is `routine_dmax` over D−1's archived IEM rows; the forward path uses the bundle's
  `prev_day` record.
- A PIT parity unit test (`C:\t\L59\b0712\tests\test_s1_pit_parity_v1.py` sha256
  `31afc70899188c30bf88c17f64dedb0ffa1557da1ef752e6372b2d5cfcc4307e`) passed under `workstation_heavy -Kind pytest
  -Queue`: the builder equals a direct serve-core call, and METARs not yet usable at the cap change no feature.

## A3. S for in-sample rows: LOYO season-L6 states

- The bound state `800072c7…2ee2db` is fitted on Oct-Dec 2021-25. E1's Dec 17-31 rows of 2021 and 2022 (the only
  December dates on the list; it ends 2025-05-31 and has no Oct-Dec 2025 date) are therefore scored with a state
  refitted on the same rows minus that year: `ex2021` `03c6bc03ca986a8309628a3f632e2a9b38f086160c917d9da26dd4dcb6fedea0`
  and `ex2022` `54f3ba513fbab48dddfeb02f5960c9f5d0da1b5aaf07afe07589108e87279912`. Jan-May rows use `800072c7…`.
  **Disclosed departure from prereg:286** ("state `800072c7…`") on those 1,781 rows only, to avoid in-sample scoring.
- **K1a PASS.** An all-year refit by the same routine reproduces `800072c7…` with max |gap| = 0.0 on the training
  rows, the dev serve features, the dev nowcast pin `714fa14e…` and the history features (tolerance 1e-9); training
  inputs equal the sidecar (29,905 rows, 2021-10-01..2025-12-31, obs `37d97195…`). Result `s1_result.json` sha256
  `3b90f9a601962843a365915c6370780a4c3b46078cc7f2618e43a84bf9a039f2`.
- The coefficients stay `07a67425…ee17e9`. S = the L6 stack over MG-1: mu = v2_mean + a_h + b_h (N − v2_mean);
  rows without N are MG-1 exactly (`l6_stack.py:9-13`).

## A4. N table and coverage (K1b)

- `history_nowcasts_h30.parquet` sha256 `99f138ac4f85e026c6575b38e5d2ef43917300915eadf39fc8f12e86dd9ce523`;
  features `eadc59cc124f741fc94d3268644b0e1c58ab3ca42549fa5428ef1e9e2090da18`. Two runs were byte-identical.
- Rows by state: bound 37,384; loyo_ex2021 900; loyo_ex2022 881; no N 435 (S = MG-1 there).
- **K1b PASS:** coverage 0.9890 (≥ 0.90); by hour 0.988-0.990; lowest station KMIA 0.965. These are grid counts
  before row 28's §1.1/§5 integrity drops.
- The h:00 table (`5f367eb6…`) is superseded and kept.

## A5. Unchanged

Arms, folds, rows, outputs, inputs, cost, run conditions and the E3 decision rule are as in the spec
(`spec_e1_0712_descriptive.md`), except that S reads N from the A4 table. B at 07-12 is fitted by a new runner
`row28_run_v13.py` (v12 unchanged), not yet written.
