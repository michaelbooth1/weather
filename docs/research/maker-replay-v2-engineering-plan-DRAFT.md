# Maker replay v2 — engineering plan, DRAFT 2026-10-03

**Status: DRAFT plan for the [v2 registration draft](maker-replay-v2-registration-DRAFT.md); not part of the signed
bytes.** Owns the work packages, effort and measurements needed to make the draft executable and to fill its gates.
**Read when:** dispatching or reviewing v2 tooling work. All estimates are ESTIMATED until a package reports MEASURED.

## Boundaries

- Synthetic fixtures only, sized to the real calibration density: **170 conditions in the daily union**, about 120
  selected at once, and a T+0/T+1/T+2 mix with T+1/T+2 at about two thirds. No production, calibration, panel or
  settlement data enters workstation development. The production calibration measurements (P1–P4) run only after the
  code lands, on calibration dates, by the production agent.
- New modules only. The frozen exam tree (`664c8943`) and its hashed files are not edited. v2 lives beside v1:
  `maker_core/replay/v2/` for the engine, report, pack and ceilings, and a v0.2 path in the reader and exporter.
  Landing the reader/exporter change changes the exporter's module hash. That is expected, because v2 re-exports
  calibration under its own pin.
- Heavy commands on the workstation go through `scripts/ops/workstation_heavy.ps1`.

## Work packages

| WP | Deliverable | Depends on | Effort (agent-days) |
| --- | --- | --- | --- |
| W0 | **Fixture generator at 170 conditions.** Extend #166's `fixture.py`: union/instantaneous split, horizon roll at local midnight, coverage groups, trade rate T, terms per capture with rare body changes, and per-condition outcome views. Emit both v0.1 and v0.2 forms of the same day. | — | 1 |
| W1 | **Reader v0.2:** `coverage_groups`, the sorted-stream check, two-pass hash-then-stream reading, and the duplicate-elision expansion used by the equivalence test | W0 | 1.5 |
| W2 | **Exporter v0.2:** coverage groups with the same-coverage refusal, duplicate elision, sorted streaming writes, and validation by streaming re-read (no whole-output load). Its target is a peak below 2 GiB on the real night format. | W1 | 2 |
| W3 | **v2 engine:** per-condition wake schedule with lazy per-band timers, where a book wakes a band only when its decision-relevant state changes and every book record refreshes the freshness clock (registration §5 rule 1, owner decision 2026-10-04); exact running portfolio totals (Decimal quantized to 1e-6, Inexact trapped, debug recompute assertion); run-length state intervals; one parse of each day driving several engine instances in lockstep (base passes, then each matched-clock round) | W1 | 3 |
| W4 | **Reference schedule:** a deliberately simple engine — the frozen loop with ticks restricted to the wake set — used only for differential tests | W3 (spec) | 1 |
| W5 | **Streaming scorer and per-cell report:** cell sums, band-day table, pull endpoint per cell (common set, pulled bitmaps, midpoints), Clarification 3 fields, k = 0.3, small-cluster bound, sidecar and its hash | W3 | 2 |
| W6 | **v2 pack CLI:** rehearsal with the §9 whitelist (refuses to print fills or P&L); 3-date carried rehearsal; `derive_ceilings` under the v2 rule; gate report E1–E8; reachability fields, with the R1 variant behind a flag that is off by default | W5 | 1 |
| W7 | **Manifest, verifier and authorization** for `maker-replay-v2-v1` (new registration ID, signed-bindings list, expiry 2026-11-16T05:00Z), and the transfer-manifest check on the workstation | W6 | 1 |
| W8 | **Docs:** the bundle contract v0.2 section and a runbook for exports, transfer, rehearsal, gates and the look | all | 0.5 |

**Total ≈ 13 agent-days.** Two to three parallel sessions after W0/W1 (W2 ∥ W3 → W4/W5 → W6/W7) give about
**6–7 calendar days**, so the code is reviewable by about 2026-10-11 and the gates can run 10-13..10-17.

## Measurements on synthetic fixtures (workstation)

Every measurement reports MEASURED or ESTIMATED, a fresh process per run, and runs serially.

| ID | Measurement | Pass or stop rule |
| --- | --- | --- |
| S1 | Bytes and records per kind, v0.1 vs v0.2, for a full day at 170 conditions | v0.2 ≤ 1 GiB per date at fixture density; report the reduction per kind |
| S2 | Exporter peak memory vs output bytes (v0.2 streaming write) on the full-day fixture | peak < 2 GiB, the nightly wrapper's ceiling |
| S3 | v2 engine runtime and peak per pass at B ∈ {40, 85, 120, 170, 250} | runtime(250)/runtime(40) ≤ 7.5, at most 1.2x linear; stop if superlinear. Under "every book record wakes" it measured 11.0 (2026-10-04) because the exporter's re-projections per band grow with B; rule 1 now counts book changes only |
| S4 | Full pipeline (8 base passes and up to 24 matched-clock trials) on one full date at 170; a 16-day carried run at 170 | per date ≤ 2,048 s; 16-day peak ≤ 1.25 × 1-day peak; whole run ≤ 32,768 s |
| S5 | Differential test, v2 vs reference, at B = 12/40/170 on short windows: all policies, both bounds, every clock trial, two trade rates | identical fills, cash, legs, settlements, intervals, decisions and clock matches; any divergence stops |
| S6 | v0.2 → v0.1 expansion equivalence on fixtures, including horizon roll and group refusal | byte-identical expansion; the group refusal fires on a crafted mismatch |
| S7 | Scored report and sidecar bytes per date at 170 | report ≪ 1 GiB / 16; sidecar ≤ 8 GiB / 16 |
| S8 | `informed-v0` quoted fraction vs B and T under the v2 schedule and the frozen loop (cross-band coupling hypothesis) | report only; v2 fraction should not fall with B |
| S9 | Exact arithmetic on adversarial extremes (max caps, 16 days, max sizes) | no Inexact trap; running totals equal recomputation |

## Production measurements (calibration dates only, after W1–W6 land)

These fill the registration's `[GATE: …]` cells. No panel date may be touched.

| ID | Step | Fills |
| --- | --- | --- |
| P1 | v0.2 night-format export of 09-27, 09-28 and 09-29 under the nightly wrapper. Receipts carry bytes per kind, peak and runtime. | E1, E2 |
| P2 | v0.2 calibration-format export, expanded and compared by hash with the existing v0.1 calibration exports; hazard n/x from both | E3 |
| P3 | Owner `scp` of the three night-format bundles to the workstation against a committed transfer manifest; v2 rehearsal per date and as a 3-date run, twice for one date | E4–E7, ceilings, reachability, N_cal, L_cal |
| P4 | Coverage-group count, and which UTC capture day carries the settlement fact for calibration-period targets. This is reported only: the 10-15 settlement-only rule is already fixed. | context for E3 and C9 |

## Risks

- **Coverage may not be per-connection.** If 88a coverage differs within a capture connection, the group refusal fires.
  Fallback: one group per condition-shard as the exporter records it. If that still dominates bytes, gate E2 fails.
- **The night format may be book-heavy.** About 245 k book records a day are not elided. If books alone exceed
  1 GiB per date, E2 fails. The fix would be a book-encoding change, which needs a registration amendment before
  signature.
- **Reachability.** A conservative `max_m U_m` hazard may suppress quoting (f_cal < 0.5). That is decided by the gate,
  not by engineering.
- **Calendar.** A signature by 10-23 needs the gates by about 10-18. A slip of more than five days lapses the draft
  (§13 of the registration).
