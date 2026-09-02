# Agent report 2026-09-10 — twelve-field seasonal challenger

**Verdict: `BLOCKED_MISSING_SEALED_CORPUS`.** The exact sealed hourly
twelve-field Previous Runs corpus and its manifests are not present on this
workstation, so P0 failed before design freeze, fitting, outcome access, or
evaluation. No model result can be produced honestly from the retained lead-1
aggregate alone. Per the mission's explicit stop rule, the corpus was not
rebuilt from projections and no provider was called.

## Git and isolation

| Item | Value |
| --- | --- |
| Required source commit | `2e20e59aae08e7367dc79e1b8102c0551e7f6904` |
| Required source tree | `f3855fcd456fa81df8486bf02d0f21de833ea4ff` |
| Verified source commit/tree | exact match |
| Mission branch | `codex/workstation-research-12field-seasonal-challenger-2026-09-86a` |
| Isolated worktree | `C:\Users\Michael\Documents\github\weather\scratch\w\seasonal-challenger-09-86a` |
| Final report-only tip/tree | reported in the outer handback; a commit cannot contain its own hash |

The main checkout was clean before the branch was created. The mission branch
was created directly at the supplied source commit rather than from the newer
local `master`.

## P0 — sealed-input verification

The canonical retained finding and the frozen extraction tool identify two
required roots:

```text
C:\tmp\pit-refetch-2026-08-10-front
C:\tmp\pit-refetch-2026-08-10
```

Both paths are absent on this host. Therefore their `CORPUS.md`, segment
manifests, twelve per-market front files, twelve per-market back files, and
retained raw-corpus digests cannot be opened or reproduced. The historical
record says the two segments together held 1,645,056 rows across twelve
markets, twelve fields, leads 1-7, and target dates 2026-06-03 through
2026-08-09 at 100% non-null coverage. Those are historical claims, not a
substitute for current byte/hash verification. Exact raw-corpus hashes are
therefore **not verifiable** and are deliberately not copied into this report
as if they had been re-proved.

A filename-only search of the repository-local forecast-history and scratch
roots found no `*_previous_runs_long*.csv` or corpus `CORPUS.md`. It found only
tracked derivatives and synthetic pytest manifests. The tracked derivative
reproduces exactly:

| Retained derivative | Verified value |
| --- | --- |
| File | `docs/roadmap/pit-lead1-daily-features-2026-09-61a.csv` |
| SHA-256 | `60b450f1dd1ee575acde86607d179ae0cae68ddee541feef664923bd62b71ac8` |
| Rows | 696 = 58 dates x 12 markets |
| Date range | 2026-06-03 through 2026-07-30 |
| Source/basis | `open_meteo_previous_runs` / `fixed_lead_day_offset` |
| Hourly values consumed by its historical build | 116,928 |
| Lead support | **lead 1 only** |
| Outcome or market-price fields | none |

Its file digest matches both its sidecar and manifest. It is not the sealed
hourly corpus and cannot support either the required all-leads 1-7 primary
challenger or the required leads 2-7 sensitivity. Expanding or imputing it
would fabricate the missing inputs and violate P0.

### No settled/stitched substitution

The frozen repository-local `data/forecast_history/<station>/forecast_long.csv`
files are the older archive, not the missing staged corpus. The Toronto header
and first data row show `open_meteo_historical_forecast` with
`stitched_continuous_archive`; its file was last written 2026-06-23. It was
inspected only to classify and reject it. No row from that surface was used,
and no settled or stitched profile was substituted for Previous Runs evidence.

### Workstation mirror state

The repository-local `data/` mirror retains explicit inherited deny-write,
deny-delete ACL entries for both `DESKTOP-RFCD2GH\Michael` and
`DESKTOP-RFCD2GH\CodexSandboxOffline`. Read-only checks found no `robocopy`
process. The newest sampled mutable files in `data/alerts`, `data/snapshots`,
and `data/logs` are dated 2026-08-12 at or before 04:30 America/Toronto, which
is consistent with the canonical frozen-at-2026-08-12-05:03 record. The three
production-side mirror task names are absent on this workstation, so this
mission makes no claim about current production Scheduler state. The mirror
was read-only throughout and was not treated as live-production evidence.

## P1/P2 disposition

P1 and P2 were not entered. In particular:

- no experiment design was sealed after the failed input gate;
- no C outcome, market probability, market price, or settlement-derived field
  was loaded;
- no baseline, all-leads challenger, or leads-2-7 sensitivity was fitted;
- no estimator, hyperparameter, seed, row population, feature order, or
  postprocessing choice was made after seeing an evaluation result;
- no probability vector, metric, bootstrap draw, power estimate, MDE, model
  artifact, or design artifact was produced; and
- `GO_TO_SECOND_RESEARCH_REPLICATION`, `NO_GO`, and
  `INCONCLUSIVE_UNDERPOWERED` were not evaluated because they require a valid
  matched-row experiment.

Accordingly, model/artifact hashes, metrics, intervals, per-market directions,
power, and MDE are **not applicable**, not zero. Reporting zeros would falsely
turn missing evidence into a model result.

## Verification

The P0 stop made harness/parity, deterministic-refit, simplex, leakage,
crossed-bootstrap, and full-suite tests inapplicable: no harness or source code
was added and no fit was permitted. The following repository checks were run
after this report was written:

| Check | Result |
| --- | --- |
| Tracked lead-1 derivative SHA-256 and manifest cross-check | PASS |
| Repository compileall through `scripts/ops/workstation_heavy.ps1` | PASS (exit 0) |
| Agent-document audit through `scripts/ops/workstation_heavy.ps1` | PASS (18 agent files, 832 Markdown files) |
| Roadmap lint/generated-view check through `scripts/ops/workstation_heavy.ps1` | PASS (`Roadmap backlog: OK`) |
| `git diff --check` | PASS |
| Canonical `scripts/ops/roll_verdict.ps1 -Branch ...` | PENDING |

## Prohibited-actions audit

| Action | Result |
| --- | --- |
| Provider or network call / refetch | none |
| Production or mirror write | none |
| Scheduler, capture, settlement, exchange, or credential access | none |
| Release, pointer, promotion, activation, serving change, alpha allocation, or candidate freeze | none |
| Model fit, artifact creation, Git LFS addition, or production-data read | none |
| Pooling across the `b77cfbed` / 2026-07-31 boundary | none |

The smallest valid unblock is transfer or restoration of the exact two-segment
sealed hourly corpus together with its original manifests and digests into a
declared read-only input location. A projection, a fresh fetch, the tracked
lead-1 aggregate, or the frozen mirror's stitched archive is not equivalent.
