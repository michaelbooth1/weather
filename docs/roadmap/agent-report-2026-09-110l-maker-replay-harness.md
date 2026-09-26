# Agent report 2026-09-110l — maker replay harness

**PARTIAL — first working increment: bounded neutral bundles, capture-time snapshots and a diagnostic-only CLI.
Phase 2 is not complete; no scored replay, real-data read, economic result or full-session RE-1 parity is claimed.**

## Increment 1 — 2026-09-26

Owner authorized starting the multi-day build now and pushing working increments with interim notes. Mission:
`docs/roadmap/workstation-handoff-2026-09-110l-maker-replay-harness-phase2.md`, read from
`origin/codex/handoff-110k-20260926` at `b5a1cf81e`. Branch `codex/maker-replay-harness-20260926` starts at
`3b8c7b92d` (`origin/codex/weather-maker-plugin-20260925`) and merges integration `8180404a0` in local merge
`87526eeb`. The requested integration was not ancestral to fetched `origin/master` (`965374a0`) at intake. After production
lands it, subsequent increments should fetch and merge `origin/master`, preserving topic history and regenerating the index.

The merge preserved the implemented portfolio and weather plugin ownership descriptions and regenerated the correspondence
index. No source conflict occurred. Worktree: `scratch/w/maker-replay-harness-20260926` beneath the workstation checkout.
The original checkout was clean and is unchanged. No subagents were used.

### Delivered contract and behavior

- [Neutral bundle contract](../operations/maker-replay-bundle.md): one closed UTC capture day, bounded manifest and flat
  JSONL streams, byte/count/hash verification, per-record capture clock and payload/source hashes, deterministic ordering,
  explicit active intervals and stable market cluster labels. Plugin v0.1 remains unchanged.
- Immutable snapshots expose only records captured at or before the requested time. A fixture provider drives the existing
  `decide()` to prove that changing a later-captured input does not change an earlier decision. This is a substrate test,
  not the full event engine.
- Deterministic JSON/Markdown diagnostics report hashes, record counts and capture exclusions. Missing minutes do not
  become economic zeros; evaluable minutes are null until payload semantics and decision replay exist.
- The CLI defaults to diagnostic-only. A requested policy is recorded but never executed. Comparison and pre-registration
  flags refuse before bundle or registration IO. A hash alone is not an owner signature; the signed authorization verifier
  and score path must land together later. Neither `captured` nor `synthetic` labels bypass the guard.
- Strict byte/row/time limits, duplicate-key/nonfinite-number rejection, changed-file checks, redirected-path refusal and
  create-only output are covered by fixture tests. All paths are explicit; no `weather.*` import enters `maker_core`.

### Verification

Initial focused run through `scripts/ops/workstation_heavy.ps1`: **32 passed, 1 skipped** (Windows symlink creation is not
granted to this test process). Broader maker/plugin tests, required repository audits and compilation are pending below.
All inputs are synthetic except the already-tracked Phase 0 public quote-price parity fixture.

The first broader run returned **1,113 passed, 13 skipped, 2 failed**: critical new files were not yet staged, and the
documentation audit required a canonical map link and correspondence regeneration. The map link is now added; the index
must be regenerated after committing this report to record its Git-added date. No behavioral failure occurred.
`compileall -q app src tests` passed through the same workstation wrapper. Final audit recheck follows the source commit.

Logical test command (dispatch through the workstation wrapper using its literal base64-JSON argument contract):

```text
python -m pytest tests/maker_core tests/market/test_maker_plugin.py tests/market/test_maker_plugin_dry_run.py tests/operations/test_schema_registry.py tests/operations/test_import_architecture.py tests/operations/test_agent_docs_audit.py tests/operations/test_path_policy.py -q --basetemp <fresh-temp-dir>
```

This includes `test_maker_core_and_plugin_import_boundaries` and its negative controls. The RE-1 full-minute journal tests
already skip twelve attempts because sanitized full-session fixtures do not exist. Passing the retained first-price tests
does not discharge the handoff's full replay parity requirement.

### Roll classification per changed file

No production closures were accessed. Fresh mechanical classification must be obtained on production before adoption:

```powershell
scripts\ops\roll_verdict.ps1 -Branch origin/codex/maker-replay-harness-20260926
```

| Increment file | Classification / closure evidence |
| --- | --- |
| `src/maker_core/replay/__init__.py` | UNDECIDABLE without production closures; no production verdict claimed |
| `src/maker_core/replay/__main__.py` | UNDECIDABLE without production closures; offline CLI only |
| `src/maker_core/replay/bundle.py` | UNDECIDABLE without production closures; new neutral module |
| `src/maker_core/replay/timeline.py` | UNDECIDABLE without production closures; new neutral module |
| `src/maker_core/replay/diagnostics.py` | UNDECIDABLE without production closures; new neutral module |
| `tests/maker_core/test_replay_bundle.py` | Test-only; no claimed production closure membership |
| `tests/maker_core/fixtures/replay_bundle.py` | Synthetic test producer; no claimed production closure membership |
| `tests/maker_core/fixtures/README.md` | Roll-free Markdown |
| `docs/operations/maker-replay-bundle.md` | Roll-free documentation |
| `docs/operations/maker-core-contracts.md` | Roll-free documentation |
| `docs/operations/package-boundaries.md` | Roll-free documentation, including merge resolution |
| `README.md` | Roll-free operator command catalog |
| `docs/README.md` | Roll-free documentation map |
| This report | Roll-free documentation |
| `docs/roadmap/correspondence-index.md` | Roll-free generated documentation |

These are the increment's files, not a new verdict for the inherited integration and Phase 1 branches. No central schema
registry change was introduced by this increment. The existing integration merges registry additions from its own missions.

### Remaining increments and explicit blockers

1. Implement typed payload adapters and the weather-side exporter using 110h's sealed-segment reader. **Exact production
   bundle-export command: not yet implemented. Expected bytes/day: not measured.** Do not substitute the dry-run CLI or
   extrapolate tiny fixture sizes as a production estimate. Publish the real command and bounded fixture size measurements
   when its implementation exists, with production volume still labelled unmeasured until an authorized diagnostic export.
2. Implement the event engine around shared `decide()`, portfolio reservations, clock/terms changes, requotes and pulls.
3. Copy the 89a fill kernel behind a neutral facade; both fill bounds, sibling cancellation and cash commitment tests.
4. Add reward/nominal rebate/markout/settlement/cash-hour scores, no-quote and clock-only baselines, and date/crossed
   date×market 90% intervals with `UNDERPOWERED` below ten clusters. No inference has been run on this three-date,
   two-market synthetic fixture.
5. Add owner-signed pre-registration verification and exact policy/date/cluster/hurdle binding before any scored real-data
   path. Full-session RE-1 parity needs a separately authorized sanitized journal fixture; current fixtures are insufficient.
6. Operations-owned admission update: the workstation wrapper's allowlist does not yet include `maker_core.replay` or the
   future exporter. No guard/wrapper was changed to admit itself. Tests exercise the new CLI inside admitted pytest.

No production data, mirror, credentials, `.env`, venue, model fitting, Scheduler registration, capture restart, live trading,
production write or master merge occurred. Only the owner-requested dependency merge was performed in this local topic.
Publication commit and final verification are recorded in the next note after the working increment is committed.

### Increment 1 publication verification — 2026-09-26

Implementation, fixtures and the initial report are committed as **`5cfc32c8`**. After committing the source report,
`weather.reporting.roadmap.correspondence_index` regenerated its entry with the Git-added date. The two failed checks were
rerun through `workstation_heavy.ps1` and **both passed**: `test_project_critical_files_are_tracked_or_ignored` and
`test_agent_docs_audit_passes_repository_contracts`. Together with the initial broader run, every selected non-skipped
check has passed (1,115 distinct checks, 13 explicit skips). No broad suite was rerun merely to replace that evidence.
Compilation and `git diff --check` passed. This is local fixture verification, not full-repository or hosted CI qualification.

The mechanical local command
`scripts/ops/roll_verdict.ps1 -Branch codex/maker-replay-harness-20260926 -Base 87526eeb`
returned exit 1, **UNDECIDABLE: no live closure evidence**, naming all four missing snapshot/CLOB/observation/enrichment
status files. Nothing was copied from production to change that verdict. Before adoption, production must run the command
above against its actual target base and fresh closures, including the inherited dependencies.

Origin was fetched again before publication; master remained `965374a0`, so the integration-branch base is still the
owner-directed choice. The tested source commit and this appended note/index commit are the first increment to push.
Later notes in this report should append to this record, as the owner requested, rather than rewrite these observations.

## Continuation item 1 — event engine (2026-09-26)

**PASS on fixtures: capture-ordered engine and typed payload adapters implemented.**
Resume base is `e3274ea7`; fetched master remains before the instructed integration landing.
The engine invokes shared `decide()`, maintains reservations across bands, records
explicit excluded intervals, schedules information/freshness/close timers, latches
decidedness, and cancels before cooldown/replacement. Future captured probability
or event changes leave earlier decisions byte-identical. No external provider is
called. Numeric cash and hazard inputs remain explicit counterfactual assumptions.

Admitted fixture verification: **39 passed, 1 symlink-privilege skip** (engine and
bundle tests). It covers scheduled pull/re-entry, permanent decidedness, mid drift,
minimum-size changes, gaps, cash reservation and future payload-clock refusal.
The fill hook is inert in this item; item 2 supplies it. Scoring CLI remains refused.
New `engine.py` and `payloads.py` are neutral offline modules with no production
closure evidence; mechanical adoption verdict remains UNDECIDABLE. New scenario
and engine-test files are test-only; the contract and this report are roll-free.

## Continuation item 2 — fill facade (2026-09-26)

**PASS on fixtures: both 89a fill bounds, sibling cancellation and cash accounting.**
Item 1 was pushed as `f4b68464`. The original 89a simulate implementation is copied
at `de76a4a9b67b25781c6c6f33b10691841e8630cc`, with its unchanged test reference;
both-bound differential tests compare fills, exposures and quote diagnostics.
An explicit trade-health capture is required: absent prints alone do not prove
zero fills. Duplicate IDs cannot fill twice; conflicting IDs refuse. Equal-time
trades consume old quotes, both legs cancel after a fill, and cash/reservations
remain shared across markets. The conservative remainder cancellation and 60-second
coverage limit are deliberate lifecycle overlays on 89a's predicate.

Admitted engine/fill suite: **15 passed**. No real tape was read. New fill facade,
copied kernel and payload/engine changes have UNDECIDABLE production closure
classification pending the mechanical production verdict; fixture/reference/test
files are test-only; documentation is roll-free.

## Continuation item 3 — scorer (2026-09-26)

**PASS on fixtures: per-band-day scorer implemented.** Item 2 was pushed as
`d6e732d9`. Accrual uses changing reward terms and k=1/0.5; nominal fee-funded
rebates stay separate from cash. Maker fees follow EF §10o. Both-token markouts at
1/5/30 minutes and settlement retain missing counts and null missing valuations.
Settlement P&L never double-counts markouts. Inventory cash-hours include holding
after quote windows, while capture exclusions cannot become zero-return days.
The scorer includes pull fraction, quote/requote counts and event-window fills.

Admitted engine/fill/score suite: **21 passed**. Pure copied markout/rebate logic is
differentially checked against the existing owner module. New score module and
engine changes: production closure UNDECIDABLE; tests are test-only, docs roll-free.
