# Clarification 1 to rule L11 market-blend (rule.md sha256 e29c9a84395d7f4f5e9a0091da99ff970597c40faa7d4cc81aa034a373f8bb8c)

Written 2026-10-25, after the MG-2 afternoon pick resolved (coordinator relay). It was written BEFORE any row
of either vector below was read, and before any composite row that uses them exists. Only file metadata has
been read: the shas, the P3d_N emit audit, and the nowcasts manifest. MG-1, the fits, the w grid, the folds,
the burn-in, the controls, the placebo, the metrics and the keep/kill rule are unchanged.

## Composite candidate (replaces section "Candidates" item 2's two slots)

- **Pre-13 slot (local hour < 13): MG-1 + L6 own-obs stack, on the captured-METAR re-spec.**
  - Module: `C:\t\l11\mods\l6_captured_candidate.py`, sha256
    `764679b9a52c9b6ff2aea8315856a39ef5354119e8b1f2eec53df44ddab781dd`. It is copied byte for byte from L3
    `tools/research/r0_ols_floor/l6_captured_candidate.py` at `ecd8c9ba6`.
  - It is L6's unchanged `l6_stack` fit and predict, reading the nowcasts below (environment variable
    `L6_CAPTURED_NOWCASTS`).
  - Nowcasts: `C:\t\l3\l6cap\nowcasts.parquet`, sha256
    `3806687cd6ad8d38571fd5d17efa5405856300d2f0029ae644e3ad08db4a31f3`.
  - It is walk-forward per fold, with the same burn-in folds (min_train_dates 0) as the rule.
- **13:00 onwards slot: P3d_N** (the MG-2 afternoon pick). It is used in place of "L3 arm A refit".
  - Vectors: `C:\t\l2\p3d_n_dev\dev_P3d_N.jsonl`, sha256
    `721ae2cd24283115f68c4b6a1b38d84d34a81921e41468d360b587599fd031ec`.
  - The file holds 79,403 rows at cutoffs 07-20. It is a distributions file, trained on 2021-2025, and loaded
    with trained_through 2025-12-31.
  - It is used only at local hours >= 13. Where it does not cover a snapshot, the scorecard's served fallback
    applies.
- The lead-1 arm A vectors stay refused. `control_refit_armA.json` is required only to exist, as the rule
  says; it is not read.

## Controls (section (a))

- Unchanged: served 1.774 / 1.526, MG-1 07-12 excess 0.0120, and w = 0 identity per candidate.
- The composite-only control "L6 own-stack 07-12 Brier minus MG-1 = -0.0036243" is still computed on the
  rule's IEM L6 module (`l6_own_candidate.py`), as the harness twin control.
  - The captured re-spec is not gated on that number. L3's ledger row 30 already establishes the re-spec's
    parity to the IEM twin.
  - No captured-minus-IEM delta is reported, because the rule forbids arm-vs-arm deltas.

## Reporting

- Results are reported per the rule: PRIMARY (ALL, 07-12, pooled 07-12 Brier fit), the blocks 06-09, 10-12,
  12-16 and 13-16, and per hour h07..h16 (h13..h16 on the 13-16 w), for ALL 11 markets and PRIMARY5. Each
  blend is reported against the market only.
- The pre-registered keep/kill reading applies to the PRIMARY row.
- Declared here, before the rows: the same reading is also applied, as a SECONDARY reading, to the 13-16 row.
  - It uses the walk-forward 13-16 w mean.
  - M_floor is the floor-only 13-16 R (ALL 0.9845, PRIMARY5 0.9776; from run 1, rows `1d9fc6d3…`).
  - The decision interval is crossed.
- MG-1 is not re-run (run 1 stands). The composite rows from run 1 are superseded by this composite. This
  completes ledger K candidate 21 (composite); it is not a new row.
