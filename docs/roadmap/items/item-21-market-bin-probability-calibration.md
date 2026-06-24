# 21. Market-Bin Probability Calibration [COMPLETE - HIGHEST PRIORITY]

Goal: turn useful raw model signal into probabilities that are less
overconfident than the current live distribution.

- [x] Calibrate exact-bucket and market-bin probabilities separately.
- [x] Compare Platt scaling, isotonic regression, temperature scaling, and
  simple shrinkage-to-market/seasonal-prior baselines.
- [x] Learn calibration by cutoff hour, bucket distance from observed WU floor,
  and sample size.
- [x] Penalize extreme probabilities unless the settlement source has printed a
  hard floor/cap justification.
- [x] Export a lightweight calibration artifact consumed by live inference.
- [x] Add tests that calibrated distributions remain normalized and respect hard
  WU settlement floors.

Acceptance: calibration reduces model log loss/Brier versus the uncalibrated
model, and improves or at least does not damage Brier skill score versus
Polymarket on settled snapshot tapes.

Codex implementation status (2026-05-31): complete for the item-21 scope.
`src/probability_calibration.py` now trains a lightweight artifact and report
from settled snapshot tapes. Exact distributions are temperature-scaled
separately from binary market bins, with deployment temperature capped at `1.5`
so calibration does not revive buckets that live physical constraints already
crushed. Live market-bin probabilities now pass through the artifact in
`src/model_presentation.py`. `src/model_distribution.py` applies
exact-distribution calibration while preserving hard WU printed floors.
The binary calibrator compares deployable no-market methods against a
market-shrink baseline, uses cutoff-hour/bin-kind/floor-distance context
summaries for fallback base rates, and keeps hard YES/NO outputs only when WU
history has already printed the relevant floor.

Validation results:

- `.\venv\Scripts\python.exe -m pytest tests\test_probability_calibration.py tests\test_estimate_distribution.py tests\test_validation.py -q`: 28 passed.
- `.\venv\Scripts\python.exe -m pytest tests\test_intraday_calibration.py tests\test_probability_calibration.py -q`: 23 passed after capping exact-distribution deployment temperature to preserve live floor behavior.
- `.\venv\Scripts\python.exe -m pytest -q`: 113 passed.
- `.\venv\Scripts\python.exe -m compileall src tests`: passed.
- `.\venv\Scripts\python.exe -m src.probability_calibration train data\snapshots\highest-temperature-in-toronto-on-may-27-2026 data\snapshots\highest-temperature-in-toronto-on-may-28-2026 data\snapshots\highest-temperature-in-toronto-on-may-30-2026`: wrote
  `artifacts/calibration/probability_calibration.json` and
  `data/backtest/probability_calibration_report.md`.
- Settled-tape leave-one-day validation selected deployable `prior_shrink`
  with weight `0.6`: Brier improved from 0.0954 to 0.0775, log loss improved
  from 0.3705 to 0.2743, and Brier skill versus Polymarket improved from
  -1.500 to -1.031. Artifact replay on the same tapes scored Brier 0.0762 and
  log loss 0.2309. The market-informed comparison baseline still shows
  Polymarket ahead at Brier 0.0382, so the next accuracy work needs better
  weather signal, not just calibration.
- Quality caveat added after item 25: this calibration artifact/report used the
  3 settled-looking tapes before coverage-aware labels existed. It is still
  useful as a provisional overconfidence fix, but future calibration reports
  should either filter or explicitly stratify by label quality once there are
  enough complete market days.

Follow-up now unlocked: item 22 should replace forecast cap/floor heuristics
with learned source-error distributions. That is the best next route to a more
accurate model because calibration reduced overconfidence but did not create
new information edge over the market.

## Completion Notes

Validated in the 2026-06-24 complete-roadmap sweep:

- `ROADMAP.md` and this item file both mark the item `COMPLETE` with status text `COMPLETE - HIGHEST PRIORITY`.
- The file contains 6 checked implementation checklist item(s); no unchecked implementation checklist items remain.
- Validation result: accepted as properly implemented for this completed disposition based on the existing checked implementation evidence; no active roadmap work was reopened for this item.
- Future validation should rerun `python -m weather.reporting.roadmap_backlog --fail-on-lint` and the referenced modules, generated artifacts, and checked implementation bullets in this file.

