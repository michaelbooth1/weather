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

- [ ] Until the fix: a test that pins today's mismatch, citing this item and EF §10ay (trainer `current_temp` null,
  serve helper returns the latest non-null row, on the same rows). Tests-only; no B-bound file edited.
- [ ] A parity-gate fixture with a null-temperature last pre-cutoff row, so the gate compares the serve helper with
  the trainer on that case instead of the trainer with itself.
- [ ] At the next retrain or model change (not before; master): the trainer adopts the serve semantics (latest
  non-null row), with the pin test flipped to assert agreement, through the retrain and edge gates.

Acceptance:

- The pin test and the parity fixture are on master before any retrain; the trainer change lands only with a
  retrain or model change and its release binding.
- No serve-side change.
