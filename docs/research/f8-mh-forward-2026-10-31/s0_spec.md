# F8-MH S0: outcome-free history count of the regime flag (SPEC, frozen with the F8-MH freeze, L16, 2026-10-31)

Admitted by master 2026-10-31, to run only **after** the freeze commit is pushed. History only; no forward date, no
label, no price, no daily maximum.

## Script and run

- A new file `tools/research/forward_f8/f8_mh_s0.py`, written after the freeze push. Its sha256 is recorded before it
  runs; it is never edited in place (any change is a new `_v2` file with its own sha).
- Light (one parquet read with column and row filters, well under 1 min and 1 GB); if it could exceed either, it runs
  through `scripts\ops\workstation_heavy.ps1 -Queue`.
- Output: a new folder under `C:\t\l16\f8-s0\`, with an exclusive-create `s0_receipt.json` and its sha256.

## Input (the X72 frame)

- `data/research/upstream_obs/obs.parquet` and `selection.json` (IEM METAR history, the frame of row 86 / X72);
  their sha256 are recorded.
- Columns read: `station`, `role`, `valid_utc`, `tgroup_f`, `tmpf`, `is_cor`. Rows read: `role == "market"`,
  `valid_utc` in [2021-09-30, 2026-01-01) UTC (the parquet filter), then kept only for local dates in October,
  November and December of 2021-2025.
- Markets: B's US10 (the selection's market stations minus Denver/KBKF).

## The flag on history (freeze §2, with the history substitutions named)

- **Routine:** IEM raw text has no METAR/SPECI prefix, so routine = the station-year's modal report minute
  (`upstream_obs_screen.routine_mask`'s rule, re-implemented in the script), and COR rows are dropped (as
  `upstream_obs_screen.load`). This is the only routine substitution.
- **Temperature:** `tgroup_f` when finite, else `tmpf`; whole scale through `mg_serve_core.wu_whole_f(v, "half_up")`,
  imported read-only after the B-manifest check (the F8-MH module's check is reused by importing it).
- **Evaluation instant** for local hour h ∈ {01, …, 06} on local date D: h:30 local (the X72 frame's mid-hour query),
  with rows of D whose observation time + 10 min ≤ h:30 (the frame's market availability lag). An ambiguous or
  non-existent local instant (the DST-end night) is skipped for that hour.
- H, t_H, C and the regime test exactly as freeze §2: t_H ≤ 01:59 local and H − C ≥ 3 °F; no rows → missing.

## Projection (method rule 16, the ≥ 2-regime-date cell filter)

- Per (market, hour) cell: f = regime dates / evaluable dates over the 460 Oct-Dec dates.
- Window D = 85 dates (2026-11-02 .. 2027-01-25). λ = f × D. Expected kept regime dates in the cell, under the cell
  filter (K ~ Poisson(λ), kept iff K ≥ 2): λ − λe^(−λ). Population market-day-hours = the sum over cells.
- **Snapshots** = population market-day-hours × 7.1 (`SNAPS_PER_MARKET_HOUR`, X75's 01-06 capture density).
- **Dates** = D × the share of evaluable history dates with at least one regime (market, hour) among cells whose λ ≥ 2
  (clustering across markets is taken from the history itself, not assumed).
- **Power (deff 2)** = `f8_mh.projected_power(population market-day-hours)`.
- Disclosure, non-deciding: the same projection from November-December rates only (the window has no October and
  includes January, which the frame lacks), per-year regime counts and the missing count.

## Verdict

- **UNTESTABLE (arm closed, no forward date read)** if projected dates < 20, snapshots < 1,000 or power < 0.5. Then
  the prereg, code, script, outputs, receipts and logs are archived to `C:\archive\ruled-out\f8-mh-midnight-high\`
  with SHA256SUMS, never deleted.
- **S0 PASS (arm stays open)** otherwise. Nothing is read until the look gate (freeze §4).
