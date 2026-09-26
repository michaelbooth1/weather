# 110g — Disable afternoon residual centering

Verdict: **PASS, ready for production review; activation pending.** Implemented
the owner's 110g handoff from `codex/owner-decisions-0925-night` at
`8643c31ee3352b27548e6cc5b1316333de34a252`. No production data, `.env`, live
service, training, scoring or venue access was used. No master merge or restart
was performed on the workstation.

Branch: `codex/disable-afternoon-centering-20260926`, created from
`origin/master` at `e4dcef601b1b67afa9f3c8a6e361ebbb8ff92fb7`.
Implementation tip: `481eabf4da28a0cdbe33b2747d7acc8a299e88c6`.
This report and its generated correspondence-index commit follow that tip; use
the pushed branch head as the complete handback.

## Change and verification

- `artifacts/misc/afternoon_residual_centering.json`: only
  `component.enabled` changes from true to false. Fitted contexts, hours and
  provenance remain byte-for-byte unchanged outside that switch.
- `artifacts/manifests/model_artifact_registry.json`: regenerated with
  `python -m weather.artifacts registry`. The sole artifact identity change is
  the centering file: 57,701 bytes, SHA256
  `1cbe4cc81ac07fd038858fc3a8a6800b30405e6556588ba71e86effdda13951e`.
  The producer also refreshes checkout mtimes and generation time. No other
  tracked manifest pins this file; existing immutable releases are untouched.
- `tests/model/test_shipped_afternoon_centering.py`: 16 cases run the actual
  global serving loader and distribution stage for Toronto and NYC at both
  endpoints of every hour from 15:00 through 18:59. Each asserts
  `artifact_disabled`, inactive, zero shift/spread, unchanged probabilities and
  mean, unit mass, no mutation and no active pipeline component.
- `docs/operations/ESTABLISHED_FINDINGS.md` section 2 records the owner decision,
  in-sample June fit and obsolete pre-June-30 pipeline. `docs/architecture.md`
  owns the switch, reload and release-binding contract. No improvement is claimed.

**142 tests passed, plus 14 subtests**, across shipped-centering,
`test_estimate_distribution`, calibration centering, release candidate contract,
release serving and artifact tests. Existing synthetic enabled-stage tests remain
useful for the retained implementation; no shipped-enabled assertion remained.
All pytest work used `scripts/ops/workstation_heavy.ps1` with an explicit owned
temporary directory. `weather.artifacts promotion-preflight --fail-on-warn`
passed with zero errors and warnings; it did not promote anything. Registry
identity comparison proved all other artifact identities unchanged.

## Activation plan — production operator only

1. Fetch the reviewed branch and use the repository integration procedure in the
   owner's **01:00–04:00 local September 26/27 quiet window**. Run
   `scripts/ops/roll_verdict.ps1 -Branch origin/codex/disable-afternoon-centering-20260926`
   against the actual production base and current closure evidence. No workstation
   verdict substitutes for this. Respect workload admission and the reserved
   evidence window before any production checks.
2. The roll script considers imported Python source under `src/` and `weather/`;
   artifacts, their manifests, tests and docs cannot cause a source-fingerprint
   roll. This branch has no runtime Python edits. A ROLL-FREE result with valid
   evidence therefore does **not** establish activation of the artifact switch.
3. Deliberately recreate serving processes/model instances within the quiet
   window using the supported stop/ensure lifecycle in
   [operations design](../operations/OPERATIONS_DESIGN.md). Coordinate
   `WeatherSnapshotLoopSupervisor` and `WeatherObservationTriggerSupervisor`
   with their workers so automatic ensure ticks cannot race the controlled stop;
   restore their original enabled state and verify new healthy workers afterward.
   `snapshot_tracker.capture_snapshot` constructs `TorontoHighTempModel` for
   a due capture; observation-trigger polling also constructs it for source
   assembly. The JSON is cached on each model instance, not watched on disk.
   Fresh per-cycle constructions can already see changed global bytes, but a
   deliberate restart gives an explicit, verified adoption boundary. Recreate
   any separately retained dashboard/replay model instances before using them.
   The independent CLOB book, enrichment and execution-tape workers do not own
   this model artifact; preserve their health throughout.
4. The handoff states there is no production bound release; this was not
   remeasured. The operator must confirm that assumption. If a release pointer
   has appeared, **stop this global-artifact activation plan**: the verified
   release copy is authoritative, and global edits cannot override it. Build and
   review a new immutable candidate using the existing release workflow instead
   of editing a bound release or deleting its pointer. Candidate construction
   already copies this now-disabled shared artifact.
5. Verify the adopted SHA/switch, supervisor recovery and fresh snapshots. In
   `probability_calibration_context.afternoon_residual_centering`, require
   `reason=artifact_disabled`, `active=false`, zero shift and spread weight,
   equal before/after means. Retain the receipt and check fresh afternoon
   15:00–18:59 snapshots under the evidence-window contract when available; a
   successful merge or a healthy worker alone is not serving proof. There is no
   source-roll or live snapshot receipt from this workstation task.
6. Re-enable only after a separate owner-reviewed measurement/decision. Change
   the switch to true, regenerate the registry via its CLI, validate artifact
   and release contracts, and repeat controlled activation (or build a new
   bound release). Preserve the fitted contexts as historical provenance;
   **never refit this stage on its own output**. Retained data do not establish
   that the old fit is suitable for reactivation.

Per-file roll classification: the two artifact JSON files change serving state
without source fingerprint coverage; the Python test and Markdown files do not
enter a worker source closure. Production still obtains its own script verdict
and performs the deliberate adoption checks above. Pushing this branch does not
activate it.

Final documentation verification: **29 documentation tests passed** (agent-doc
audit, roadmap backlog and correspondence parity), the standalone documentation
audit passed, and `git diff --check` passed. The generated correspondence index
adds the new 110g report after its source commit.
