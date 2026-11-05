# 344. Trainer Keeps A Null Last Pre-Cutoff Temperature That Serve And Replay Skip [OPEN 2026-11-05 - MASTER RULING; FIX AT THE NEXT RETRAIN OR MODEL CHANGE, PIN NOW]

Goal: remove the rare train/serve mismatch in `x_current_temp` without moving a frozen or pinned state before its
time, and make the parity gate able to see it.

Owner/package: `weather.model` (`feature_store.build_historical_feature_record`), with the parity scorecard
`weather.reporting.scorecards.train_serve_feature_parity`. Workstation builds the test and fixture; master owns the
landing and any retrain.

Source: master ruling 2026-11-05 (relayed by the WS coordinator). Finding and file:line cites:
[EF §10ay](../../operations/ESTABLISHED_FINDINGS.md).

Why this matters: the trainer takes the last row at or before the cutoff even when its temperature is null, while
serve and replay take the latest non-null row. History rate 2 of 28,936 (market, date, hour) keys. The parity gate
builds its training side with the same trainer builder (`_base_training_record`), so it was blind to the case. It
is not a lever (too rare to power), and fixing either side now moves a frozen or pinned state: the trainer change
moves MG-1 and row-28b, and a serve-only fix is forbidden.

Checklist:

- [x] Until the fix: a test that pins today's mismatch, citing this item and EF §10ay (trainer `current_temp` null,
  serve helper returns the latest non-null row, on the same rows). Tests-only; no B-bound file edited.
  Done in `tests/model/test_item344_null_last_pre_cutoff_temp_pin.py`; plan in
  [the design note](../../research/item344-null-temp-plan-2026-11-05/design.md).
- [ ] A parity-gate fixture with a null-temperature last pre-cutoff row, so the gate compares the serve helper with
  the trainer on that case instead of the trainer with itself. Comparator level done (same test file, through
  `compare_feature_records`). The manifest case kind is a retrain-time step (next box; master Q2, 2026-11-05).
- [ ] At the next retrain or model change (not before; master): the trainer adopts the serve semantics (latest
  non-null row), with the pin test flipped to assert agreement, through the retrain and edge gates. Retrain-time steps:
  - The whole-row skip: `current_obs` moves to the latest non-null-temperature row, and every field read from it
    follows. This is master Q1, 2026-11-05, decided by the field-by-field proof in
    [the design note](../../research/item344-null-temp-plan-2026-11-05/design.md) §1a.
  - The parity scorecard's manifest gets a null-last-row case kind. This needs the serving surface
    `train_serve_feature_parity._wu_sources` (`:539`), which calls `float(row["temp_native"])` on every row (`:547`),
    to accept a null temperature. It is a source edit, so it lands only with the retrain (master Q2, 2026-11-05).

Acceptance:

- The pin test and the parity fixture are on master before any retrain; the trainer change lands only with a
  retrain or model change and its release binding.
- No serve-side change.
