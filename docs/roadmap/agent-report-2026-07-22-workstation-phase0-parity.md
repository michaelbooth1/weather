# Agent Report - 2026-07-22 Workstation Phase 0 Parity

## Outcome

**PASS.** The workstation mirror reproduced two independent production-recorded
scorecards exactly enough to open the research program:

- the frozen-current arm and its pinned control match at all 18,403 shared
  observations (Brier delta `0.0`, log-loss delta `0.0`); and
- a fresh replay summary matches all 847 numeric score leaves in the recorded
  production summary with zero missing, extra, or mismatched metrics and
  maximum absolute delta `0.0`.

This is a parity result, not evidence of model edge. On the frozen 12-day,
three-market comparison, current Brier is `0.04272136` versus market Brier
`0.03310608` (`current - market = +0.00961528`).

The current promotion-corpus manifest binds 309 market-days, 44,178 snapshots,
486,486 band rows, 12 markets, and 32 fleet dates from 2026-06-03 through
2026-07-10. Every entry was independently rehashed against the read-only
snapshot mirror: 309 checked, zero warnings, zero affected folders.

## Isolation and safety

- Isolated scratch worktree:
  `scratch/worktrees/weather-workstation-research-2026-07-22`
- Branch: `codex/workstation-research-2026-07-22`
- Base: `99c0616419ce75a402e5b752fc87b4f9bebec54c`
- Input root: the repository-local, ignored `data/` mirror (read only); its
  exact resolved runtime root remains bound in the machine evidence
- Output root: `scratch/workstation-research-output`
- No production-host access, scheduler action, live trading, promotion,
  release-pointer mutation, or master push occurred.

Before the operator's explicit reminder about the mirrored tree, one empty
directory was created at
`data/backtest/research/workstation_2026-07-22/phase0`. No file or result was
ever written there. It was left untouched after the reminder; all experiment
state and outputs are outside `data/`.

## Mirror provenance

The clone-local mirror root and its major subtrees were created on 2026-07-21
at 14:07 ET. `data/snapshots` contains 574 immediate directories: 573 event
directories plus the cache directory. The newest event folders were created by
the 2026-07-22 mirror pass around 04:32 ET and had source-content mtimes through
05:00 ET. `data/backtest` had 2,376 immediate files and 17 immediate
directories, with a subtree mtime of 2026-07-22 01:00 ET.

There is no copy receipt in the mirror that binds each subtree to a named
production sync batch. Therefore the strongest honest provenance is the
observed 2026-07-22 mirror state plus content hashes below; an exact upstream
batch identifier cannot be claimed.

## Parity evidence

### Frozen baseline

Inputs:

- current export SHA-256
  `CE9CEEF79C320FCB9D59B94EBC924F2C32B91798F01C2F8923052156E6F9755A`;
- pinned control SHA-256
  `AD178340A1138B45FB0A9C6A51538D6C823618290AA8AEB5F675B07AEAAF8DBC`;
- current identity `item50_pooled_forecast_v3_candidate`;
- control identity `pooled_f_candidate_control`.

Result:

| Metric | Current | Pinned control | Delta | Market |
| --- | ---: | ---: | ---: | ---: |
| Brier | 0.04272136 | 0.04272136 | 0.00000000 | 0.03310608 |
| Log loss | 0.13573757 | 0.13573757 | 0.00000000 | 0.10654354 |

Coverage is 18,403 shared observations, 12 market-days, and three markets.
Validation errors are empty. The machine-readable output is
`scratch/workstation-research-output/phase0/frozen_trend.json`, SHA-256
`106147125ABA2DD1459AD1D4B466340C0A2BE7F2502107486992332D7A723F73`.

The scorer was changed to stream CSV/JSONL rows and retain only the requested
variant. The original materializing implementation exhausted workstation
memory on the 375 MB export; the bounded implementation completed without
changing the score.

### Independent replay-summary reproduction

The input row export
`data/backtest/repair_integrated_active_rows.csv` has SHA-256
`E2771F3B213EED70C8A4380F77FFAB93DC9A838065D2ED1C86C5F1D319CB4934`.
The production summary has SHA-256
`6D5A0A379A1DA0FC4D22F2B4889E04820ABB3495A8F86490A02AC33ED0F31BAC`.
A fresh summary was written to
`scratch/workstation-research-output/phase0/repair_integrated_replay_recomputed.json`,
SHA-256
`cfab48bbb2471d801207c04a23d28ecd2e75e1ed2b24026229dbaa4fd3d68282`.

Comparison result:

- numeric metric leaves: 847;
- missing / extra / mismatched: `0 / 0 / 0`;
- maximum absolute delta: `0.0`;
- row-export corpus hash: exact match
  (`b407a5237e74790d4e4e32c60b4c1cad92b0f7599ac128d7b572b6f2aecfc7ae`).

### Current corpus integrity

The current manifest file SHA-256 is
`4CAFCF1AA827BBF0B2B4C85AF898192A50637C49D0B270C5006EF56F3CACD1F5`;
its canonical corpus hash is
`d7cfdc58e31ecffab1e4e7f0ef19c4773dbf7c16e8eaeffbf19589e22fc0893f`.
`verify_entry_inputs` was applied to every manifest entry and reported 309/309
checked, zero warnings, and zero affected folders. The audit output is
`scratch/workstation-research-output/phase0/promotion_corpus_input_verification.json`,
SHA-256
`D0CCB2D204E2403E473DD060C8EF62A1DD3999711847C045B4969B06A203E8F0`.

An older 51-day manifest was rejected: all 6,989 bound tape hashes differ from
the current mirror (manifest dated 2026-06-19; tapes modified 2026-06-24). No
experiment in this program uses that stale manifest.

## Disposition

Phase 0 is open for offline research on the 309-market-day corpus, subject to
each experiment preserving the exact input hashes, date split, and read-only
mirror boundary. The parity checks do not authorize serving changes or imply
that the incumbent beats market prices.
