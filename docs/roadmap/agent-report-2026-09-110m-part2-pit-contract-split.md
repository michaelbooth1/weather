# 110m part 2 — point-in-time contract split

**Verdict: PASS for the requested contract consolidation; no claim of complete
capture/reporting isolation.** Fixture-only work from integration `8180404a0` on
`codex/pit-contract-split-20260926`; no production evidence or services accessed.

The reporting evaluator imports all 12 formerly duplicated definitions from
`weather.point_in_time_contract`. Residual release verification imports the neutral
streaming verifier and supplies its two exact release hash bindings. Reporting
retains small adapters for JSON normalization and field-specific date diagnostics;
strict neutral hashing and the stronger training/resource checks remain intact.

Residual forward attestations already used a corpus-bound production window. That
mode is retained only with both valid, matching immutable hashes and nonempty
candidate/release identities. Ordinary pooled-training production validation still
requires the selection-universe lock. Tests reject mismatched and partial bindings.
The neutral verifier's stronger checks replace the reporting copy's weaker checks;
this is intentional consolidation, not a claim that every formerly accepted invalid
payload remains accepted. Differential fixtures compare all 12 definitions against
the frozen integration implementations, including invalid-input diagnostic cases.

## Validation and closure

- Release, serving, PIT evaluation/preselection and differential fixtures plus all
  four repo audits: **201 passed, 1 skipped (69.36 s)**. The skip is the existing
  Windows symlink-creation capability check.
- Expanded differential/closure tests plus schema registry, import architecture
  (including maker-core boundary controls), agent docs and path policy:
  **70 passed (29.01 s)** through `workstation_heavy.ps1`.
- Static closure includes nested/lazy imports and literal `import_module` calls.
  Before/after module counts: residual release **126/126**, market microstructure
  **132/132**, snapshot tracker **137/137**, observation trigger **140/140**.
  No whole modules leave these conservative closures. The remaining path is
  `residual_distribution_release -> calibration.residual_distribution_v1 ->
  reporting.validation.point_in_time_evaluation`. Removing that trainer coupling
  is separate work; this change removes the direct verifier dependency and 12
  duplicated implementations, not the remaining calibration path.

## Per-file landing classification

| File | Classification |
| --- | --- |
| `src/weather/point_in_time_contract.py` | Conservatively roll-sensitive; shared validation dependency |
| `src/weather/reporting/validation/point_in_time_evaluation.py` | Conservatively roll-sensitive through lazy calibration closure |
| `src/weather/residual_distribution_release.py` | Conservatively roll-sensitive through serving/release closure |
| `tests/reporting/test_point_in_time_contract_split.py` | Roll-free |
| `docs/operations/package-boundaries.md` | Roll-free |
| This report and generated `docs/roadmap/correspondence-index.md` | Roll-free |

Production must obtain the mechanical `roll_verdict.ps1` result and land through
the existing admitted integration path. The workstation classification is not
authority to restart capture. No production export or Scheduler operation is needed.
