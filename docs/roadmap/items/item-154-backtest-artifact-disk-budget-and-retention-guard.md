# 154. Backtest Artifact Disk-Budget And Retention Guard [COMPLETE 2026-06-19 - GUARDED EXPORTS AND CLEANUP MANIFEST LIVE]

Goal: make replay, promotion-refresh, and shadow-variant artifact generation
respect local disk budgets before writing large backtest outputs.

Evidence: while evaluating the Item 147 time-split alpha candidate on
2026-06-19, a promotion-refresh run wrote a 120 MB variant CSV and left the
local `C:` volume at 0 bytes free. Pytest then failed during cache write with
`OSError: [Errno 28] No space left on device`. The failed wrapper byproducts
were removed, freeing only about 100 MB, so the workspace remains critically
low on disk even after cleanup.

This is separate from Item 146's backup durability and high-volume tape
retention work. Item 146 now has local backup/restore evidence green, but still
covers external backup-root durability for irreplaceable and high-volume data.
This item covers local run-time budgets for generated backtest,
promotion-refresh, and variant exports so diagnostics cannot starve the
workstation or scheduled jobs.

- [x] Add a preflight disk-headroom check before the largest candidate and
  multi-variant shadow CSV/JSON/Markdown artifact writes.
- [x] Extend the preflight disk-headroom check to remaining replay and
  promotion-refresh summary JSON/Markdown outputs.
- [x] Estimate worst-case output size for candidate variant exports and block
  or require an explicit override when free space is below the configured
  reserve.
- [x] Add retention/tiering policy for generated `data/backtest/*variant*.csv`,
  replay JSON, and promotion-refresh scratch artifacts.
- [x] Make failed or interrupted promotion-refresh runs clean up incomplete
  scratch outputs or mark them as incomplete in a manifest.
- [x] Add an operator report showing largest generated artifacts, retained
  evidence artifacts, and safe-delete candidates.

Acceptance: a full promotion-refresh or replay export cannot start when the
workspace lacks configured headroom; interrupted runs leave a clear incomplete
manifest and do not strand large unreferenced scratch files; focused tests cover
the disk-budget gate and cleanup behavior.

## 2026-06-19 variant-export headroom guard

The first guard is implemented for the largest generated CSV path:
Item-69-compatible candidate/source-state/microstructure/bridge variant
exports. `weather.calibration.pooled_candidate_scoring` now estimates variant
CSV size from row count and requires configurable post-write free-space
headroom before opening the output file. `pooled_candidate_replay` and
`promotion_refresh` expose `--min-artifact-free-bytes`, defaulting to
`1000000000` bytes for CLI runs; operators can set it to `0` only when they
explicitly want to disable the guard.

This would have failed the 2026-06-19 promotion-refresh wrapper before writing
the 120 MB variant CSV while the drive had under 100 MB free. Focused coverage
now verifies the guard blocks writes before creating the file and that
promotion refresh passes the setting through to candidate replay:
`python -m pytest -p no:cacheprovider tests\calibration\test_pooled_candidate_replay.py tests\calibration\test_promotion_refresh.py tests\backtesting\test_replay.py -q`
passed with `86 passed`.

Remaining work: none for the local guardrail. Future operators can delete or
tier additional rebuildable artifacts by rerunning the cleanup manifest command
after confirming paired evidence is retained.

## 2026-06-19 retention report and multi-variant guard update

`weather.reporting.backtest_artifact_retention` now writes
`data/backtest/backtest_artifact_retention.json` and
`data/backtest/backtest_artifact_retention_report.md`. The current report is
`BLOCK`: after deleting three generated Item 147 row-level CSV exports while
retaining their paired reports/manifests, `C:` has `88.6 MB` free, leaving an
`865.0 MB` shortfall versus the 1 GB reserve. It scanned 640 backtest files,
found `2.8 GB` of local backtest artifacts, and identified 30 rebuildable
cleanup candidates totaling `2.1 GB` plus 33 review candidates totaling
`2.2 GB`. The report does not delete anything automatically; it names
row-level replay/shadow exports and generated shadow payloads as review-delete
candidates only after paired reports, corpus inputs, and model artifacts are
retained or externally archived.

The disk guard is also shared through
`weather.reporting.artifact_disk_budget`. `weather.reporting.multi_variant_shadow`
now exposes `--min-artifact-free-bytes`, defaulting to the same 1 GB reserve,
and preflights its long CSV, attribution sidecar, JSON, and Markdown report
writes before opening output files. That covers the large multi-variant shadow
outputs that dominate the retention report, including generated long CSVs and
row-bearing JSON payloads.

## 2026-06-19 final-output and incomplete-run guard update

The reserve check now covers final summary outputs too. `pooled_candidate_replay`
preflights its Markdown and JSON reports, `promotion_refresh` preflights final
summary JSON/Markdown outputs and gap-experiment manifests, and the candidate
report renderer fails before creating the Markdown file when the configured
headroom is unavailable.

`promotion_refresh` now writes a best-effort
`data/backtest/f_family_promotion_refresh_incomplete.json` manifest when a
guarded run raises. The manifest records `INCOMPLETE`, the exception type,
error text, configured output paths, and the `--min-artifact-free-bytes`
reserve. It intentionally does not auto-delete artifacts; cleanup/tiering still
requires retaining paired reports, corpus inputs, and model artifacts first.

## 2026-06-19 cleanup manifest and reserve clearance

`weather.reporting.backtest_artifact_retention` now supports explicit cleanup
manifests for rebuildable generated artifacts. The command only selects
artifacts with retained paired evidence, records the selected paths and paired
reports/manifests, and deletes only when `--apply-cleanup` is present. Cleanup
paths are required to resolve under the configured backtest root.

Four applied manifests removed 27 generated row/shadow artifacts totaling
about `1.9 GB`, including multi-variant long CSVs, generated shadow payloads,
Item 35 row exports, and the default pooled candidate variant CSV exports. The
paired Markdown reports, promotion corpus, trust manifest, and model artifacts
were retained. The latest pass,
`data/backtest/backtest_artifact_cleanup_manifest_4.json`, deleted 8 additional
rebuildable row exports totaling `297.2 MB` after retaining paired replay
reports, variant-export metadata, or explicit Markdown report references. The
post-cleanup report
`data/backtest/backtest_artifact_retention_after_cleanup_report.md` is `PASS`:
`C:` has `1.1 GB` free, shortfall is `0 B`, and `data/backtest` has `897.8 MB`
across 698 scanned files.

This clears the local disk-budget blocker for guarded replay/promotion work.
The report still lists 3 rebuildable cleanup candidates totaling `129.1 MB`
and 6 review candidates totaling `274.2 MB`, but the configured 1 GB reserve is
met.

Remaining work: none for this item. Continue to use the cleanup manifest before
large all-grade refreshes if local headroom falls below reserve again.

Verification:
`python -m pytest -p no:cacheprovider tests\reporting\test_multi_variant_shadow.py tests\reporting\test_backtest_artifact_retention.py tests\calibration\test_pooled_candidate_replay.py tests\calibration\test_promotion_refresh.py tests\backtesting\test_replay.py -q`
passed with `109 passed`; the report-reference cleanup matcher follow-up is
covered by
`python -m pytest tests\reporting\test_backtest_artifact_retention.py -q`.

## 2026-06-19 source-state ablation cleanup classification

The raw CLOB audit and continued capture loops pushed local free space back
below the 500 MB working reserve:
`data/backtest/backtest_artifact_retention_after_clob_raw_gate_report.md` was
`BLOCK` with `371.6 MB` free and a `105.3 MB` shortfall. The largest review
items included `item35_density_source_state_ablation_v0_2.csv` and
`item35_density_source_state_ablation_v0_2_floorfix.csv`, both row-level
source-state ablation exports whose retained replay reports explicitly name the
CSV outputs.

`weather.reporting.backtest_artifact_retention` now classifies
`source_state_ablation` CSVs as rebuildable generated row exports, still
requiring paired replay-report evidence before deletion. Cleanup manifests then
deleted 19 rebuildable row/shadow exports totaling `156.9 MB`:
`data/backtest/backtest_artifact_cleanup_manifest_after_source_ablation_cleanup.json`
deleted the two large source-state ablation CSVs and three smaller paired row
exports, and
`data/backtest/backtest_artifact_cleanup_manifest_after_row_export_cleanup.json`
deleted fourteen additional small paired row exports. Reports, manifests,
corpora, and model artifacts were retained.

The final no-cleanup check
`data/backtest/backtest_artifact_retention_after_row_export_cleanup_final_report.md`
is `PASS`: free space is `490.0 MB`, shortfall is `0 B`, and `data/backtest`
has `366.9 MB` across 752 scanned files.

Verification:
`python -m pytest tests\reporting\test_backtest_artifact_retention.py -q`
passed with `8 passed`.

## 2026-06-19 pooled-training preflight guard

An Item 32 no-pressure reanalysis experiment showed one remaining hole in the
guardrail surface: `pooled_feature_model` could spend a long training window
before discovering local artifact headroom was already below reserve. The full
no-pressure command ran past a 20-minute timeout, was stopped, and produced no
artifact/report.

`pooled_feature_model` now accepts `--min-artifact-free-bytes`, defaulting to
the shared artifact reserve, and preflights the planned model/report outputs
before dataset assembly or fitting. Rerunning the same Item 32 no-pressure
command with current disk state now fails fast with an explicit
`insufficient disk headroom for pooled feature model training outputs` error
instead of starting a long training process.

Current local retention after the failed training attempt is again blocked:
`data/backtest/backtest_artifact_retention_after_item32_no_pressure_guard_report.md`
is `BLOCK` with `255.6 MB` free, a `221.2 MB` shortfall against the 500 MB
reserve, and zero policy-safe cleanup candidates. This means the local
guardrail works, but the environment needs external storage, large-review
artifact tiering, or a deliberate lower-reserve bounded smoke run before more
broad model artifacts are generated.

Verification:
`python -m pytest tests\calibration\test_pooled_feature_model.py -q` passed
with `41 passed`.

## Completion Notes

Validated in the 2026-06-24 complete-roadmap sweep:

- `ROADMAP.md` and this item file both mark the item `COMPLETE` with status text `COMPLETE 2026-06-19 - GUARDED EXPORTS AND CLEANUP MANIFEST LIVE`.
- The file contains 6 checked implementation checklist item(s); no unchecked implementation checklist items remain.
- Validation result: accepted as properly implemented for this completed disposition based on the existing checked implementation evidence; no active roadmap work was reopened for this item.
- Future validation should rerun `python -m weather.reporting.roadmap_backlog --fail-on-lint` and the item-specific `Verification:` command(s) or artifact checks listed above.

