# 110p — per-record work registry, step 1

**VERDICT: IMPLEMENTED. The falsifier does not hold. Production adoption remains
pending: the seed intentionally exposes five approvals absent from this base's
DECISION_LOG, and production alone must generate the board and obtain the runtime
roll verdict. No production action is authorized by this handback.**

## Falsifier evidence

At base `965374a0edc6fcb65d66e257be9e404cc9af8d60`,
`src/weather/reporting/roadmap/roadmap_backlog.py` has `STATUS_RE` for
OPEN/PARTIAL/COMPLETE and `OWNER_PACKAGE_RE`; `parse_item` and `item_metadata`
emit status and owner/package but no dependency or landing-slot metadata.
`docs/roadmap/AGENTS.md` defines item scope/status/evidence, not a per-mission
owner/dependency/landing protocol. Free prose can mention these facts but the
existing parser neither represents nor checks them. The requested four-part
existing-format capability therefore does not exist; numbered items remain
authoritative for engineering scope and acceptance.

## Delivered

- `python -m weather.reporting.roadmap.worktrack`: new, set, link, check, board,
  night-plan and handoff-prompt. Defaults use `weather.paths`; no capture-domain
  module import, network client, runtime state or central schema-registry change.
- Strict per-file validation, duplicate-key rejection, dependency existence/cycle
  checks, immutable ids, exclusive creation and atomic record replacement.
  Request/receipt clocks are separate from updated so ordinary edits cannot
  refresh stale work. Approved requests match exact DECISION_LOG date/text cells.
- Production-only board command with explicit role declaration, by-status and
  workstream views, owner waits, and conservative readiness. Role declaration is
  not host authentication. Fixtures exercise rendering; this workstation did not
  generate the canonical board.
- 47 initial W records, including all seed branch tips/PRs/slots and corrections,
  dependency constraints, approvals, storage operations, the three chat missions,
  autumn PIT without a handoff, and 88a/disk/panel headroom. All 25 seed hash
  references and all named PRs were checked against the backfill text.
- Registry ownership/CLI contract in `docs/roadmap/work/README.md`, linked from
  the roadmap agent guide, documentation map and documentation ownership map.

Files use JSON-compatible YAML 1.2 (valid YAML with quoted flow syntax). The
base environment has no YAML parser dependency. This keeps dependencies and
capture-imported schema files untouched; block YAML/comments/anchors are
explicitly unsupported. Use the CLI or a JSON-compatible YAML patch to edit.
These are documentation records, not versioned capture/runtime artifacts.

## Seed interpretation and unresolved work

Seed authority is `074c281d628dea2708fcbc8db888685742adac06` on
`origin/codex/worktrack-seed-20260926`, path
`docs/roadmap/work-seed/night-plan-2026-09-26.md`; every record links it.
Later seed corrections govern the stored slots: 110j D on 09-29/30, C alone on
09-28/29, ratchets last, 110o part 3 after 110n plus neutral helpers, and index
split at the clean post-integration boundary. No proposed landing was marked
landed or verified. Missing roll evidence is unknown, not guessed from filenames.

The seed's final `caaf62294c` is a typo: its earlier `caf62294c` and the remote
lane-extension ref agree on `caf62294c0273e38ac2648b324e3cf9beac0824a`.
Superseded suite/handoff/harness tips remain in notes. The three chat branches
use read-only Git/PR metadata (PRs 107–109); replay-hurdles advanced from
`c7404346` to `bc9fd5b1` during backfill. No other branch tree was integrated.
Seed publication time is the known receipt bound, not a claim to have observed
the exact handback event. Formal handoffs absent from evidence stay null.

At `--now 2026-09-27T02:31:00Z`, the real registry check returns **1**, solely for:

| Record | Missing decision evidence on this base |
| --- | --- |
| W-0043 | All ten repo-health owner decisions |
| W-0044 | Unmatched lots default to owner-discretionary outside bot bleed limits |
| W-0045 | Prior trades are manual; campaign starts only at next automated campaign |
| W-0046 | Read-only workstation RE-1 journal access |
| W-0047 | Storage decisions 1–9 approved, 10 keep, 11 no |

W-0047 already identifies the exact row on `owner-decisions-0926-day` at
`ed075014161e6e0b0f8d3e9d0fc8dd265356d2c2`. Adopt that row; do not duplicate it.
The other four are the seed's pending production docs rows. These are missing
records of approvals already granted, not requests for repeat owner permission.
Production reconciles current receipts, logs/link approvals, verifies handbacks,
updates slots and runs check/board in its docs step. Time-based stale checks will
correctly add failures if the snapshot is left untouched.

## Verification and reproduction

Focused fixture suite: **25 passed**. Initial combined verification: **69 passed,
1 failed** solely because the architecture audit requires the two new Python
files to be staged/tracked. Final staged verification is recorded in the closeout
below. No production data or network fixture was used.

Use the workstation's `scripts/ops/workstation_heavy.ps1`, with its own absolute
RepoRoot and existing project interpreter, and JSON/base64 arguments as documented
in `docs/development.md`. Exact Python argument list for the required suite:

```text
-m pytest -q tests/reporting/test_worktrack.py tests/operations/test_schema_registry.py tests/operations/test_import_architecture.py tests/operations/test_path_policy.py tests/operations/test_agent_docs_audit.py --basetemp <fresh-existing-parent>/pytest-worktrack
```

The schema test includes the strict source audit; path/import tests scan the
repository; `test_agent_docs_audit_passes_repository_contracts` calls the complete
documentation audit including generator parity. The audit CLI is also executed
under the wrapper using a temporary pytest driver. After committing this report,
regenerate correspondence so its Git-added date is available:

```powershell
python -m weather.reporting.roadmap.correspondence_index
python -m weather.reporting.roadmap.correspondence_index --check
python -m weather.reporting.roadmap.worktrack --now 2026-09-27T02:31:00Z check
```

The last command's expected result on this base is the five failures above.
Production's separate docs step runs:

```powershell
python -m weather.reporting.roadmap.worktrack board --actor production --night 2026-09-27
scripts\ops\roll_verdict.ps1 -Branch origin/codex/W-tracker-step1-20260927
```

## Per-file roll disposition and boundaries

| Changed files | Disposition |
| --- | --- |
| `src/weather/reporting/roadmap/worktrack.py` | New offline module; only project import is weather.paths; no existing source imports it. Structurally roll-free; production closure verdict pending. |
| `tests/reporting/test_worktrack.py` | Fixture tests, outside capture imports. |
| `docs/roadmap/work/W-0001.yaml` through `W-0047.yaml`, `work/README.md` | Documentation metadata, roll-free. |
| `docs/roadmap/AGENTS.md`, `docs/documentation-maintenance.md`, `docs/README.md` | Documentation ownership/routing, roll-free. |
| This report and generated `docs/roadmap/correspondence-index.md` | Documentation, roll-free. |

No schema-registry-family file changed. An authoritative retained-closure verdict
cannot be obtained here without violating the mission's no-data boundary; the
production agent must run the repository verdict above. No manual closure guess
is offered as that verdict.

No Scheduler registration or mutation, credentials access, production/mirror
read/write, capture restart, runtime data access, trading, model work, merge,
history rewrite or branch deletion was performed. Only source Git/PR reads,
fixture verification and the authorized topic publication are in scope.

## Source-control closeout

Branch: `codex/W-tracker-step1-20260927`. Base: `965374a0edc6fcb65d66e257be9e404cc9af8d60`.
Worktree: `.worktrees/W-tracker-step1-20260927` under the workstation checkout;
the primary checkout and pre-existing branches are preserved. Implementation
commit, final verification and draft PR are recorded in the follow-up closeout
before publication. Merge/runtime adoption remains with production and owner.
