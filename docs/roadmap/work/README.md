# Work registry

Status: canonical contract. Read when dispatching a mission, receiving a handback,
recording an owner dependency or planning a landing. `W-####.yaml` owns mission
coordination state. Numbered items retain engineering scope/acceptance/evidence;
`STATE_OF_PLAY` owns direction; `DECISION_LOG` owns approval evidence. A work
record grants no execution authority.

## Record contract

Files use **JSON-compatible YAML 1.2**, written with the standard library.
Quoted keys, strings, arrays, objects, `null` and booleans are supported; block
YAML, comments and anchors are not. This avoids a new dependency or capture
schema-registry import for documentation metadata. There is no versioned runtime
artifact. Duplicate/unknown keys (including nested keys), bad types/enums and
filename/id mismatches fail. `weather.reporting.roadmap.worktrack` owns validation.

All fields are required; optional values use null or empty lists:

| Fields | Contract |
| --- | --- |
| `id`, `title` | W-####, nonempty title; id immutable, never reused |
| `workstream` | maker, wallet, model, storage, repo-health, youtube, ops, canon |
| `status` | proposed, handed-off, in-progress, handback-received, verified, queued, landed, blocked, dormant, closed |
| `owner` | production, workstation, owner; responsible host/person |
| `handoff` | Path or pinned remote document URL, or null until authored |
| `handbacks` | List of `{path, received, verified}`: path/URL, timezone timestamp, boolean |
| `branch`, `tip`, `pr` | Branch without origin/, 7–40 hex commit, PR URL; nullable |
| `roll` | free, sensitive, unknown; production still obtains roll_verdict before landing |
| `depends_on` | W-id list; no missing records, self-dependencies or cycles |
| `landing_slot` | null or `{date, window}`; date is the evening starting the night, window describes local scheduling |
| `needs_owner` | List of `{question, status, since, decision}`; status pending/approved/declined; decision null or `{date, text}` matching the exact first two cells of a DECISION_LOG table row |
| `item`, `questions` | Nullable owning item path/URL; list of question ids/text |
| `updated`, `notes` | CLI-maintained timestamp; list of provenance/context strings |

Dates alone mean midnight UTC; timestamps require a timezone. `since` and
`received` measure age independently of `updated`. Linking a handback sets
handback-received and verified=false; re-linking preserves its received time.
Production marks handbacks verified and advances status explicitly.

`check` fails on pending owner requests older than three elapsed days,
handback-received records with unverified handbacks older than two elapsed days,
approved requests without an exact decision row, future dates, or invalid
structure/dependencies. Exact two/three-day boundaries pass. Declined requests
stop aging but block landing until revised/closed. Chat approval with no log row
remains a failure; this does not ask the owner to approve again.

## CLI and production workflow

Defaults use `weather.paths`, independent of current directory. Global flags
`--root`, `--decision-log` and optional reproducible `--now` precede the command.

```powershell
python -m weather.reporting.roadmap.worktrack new --title 'Bounded mission' --workstream ops --owner workstation
python -m weather.reporting.roadmap.worktrack set W-0001 status=in-progress branch=codex/mission tip=abcdef1
python -m weather.reporting.roadmap.worktrack link W-0001 handoff docs/roadmap/mission.md
python -m weather.reporting.roadmap.worktrack link W-0001 handbacks docs/roadmap/result.md
python -m weather.reporting.roadmap.worktrack link W-0001 depends_on W-0002
python -m weather.reporting.roadmap.worktrack set W-0001 --file approved-patch.yaml
python -m weather.reporting.roadmap.worktrack check
python -m weather.reporting.roadmap.worktrack night-plan --night 2026-09-27
python -m weather.reporting.roadmap.worktrack handoff-prompt W-0001
```

`new` allocates the next id or accepts `--id`, refusing existing ids. Sync before
allocation across hosts; preserve both missions under distinct ids on conflict.
`set` accepts `FIELD=text`, quoted `FIELD=JSON`, or a JSON-compatible YAML mapping
patch with `--file`. Mutations reject invalid structure/dependency graphs while
allowing incremental repair of age/decision failures. `link` supports handoff,
handbacks, branch, pr, depends_on, item and questions. Record replacements are
atomic; coordinate edits of the same record through Git.

Only **production**, during its docs step, runs:

```powershell
python -m weather.reporting.roadmap.worktrack board --actor production --night 2026-09-27
```

This writes `docs/roadmap/work-board.md`; never hand-edit it. `--actor` declares
the role; it is not host authentication. Tests may render temporary fixtures.
Sections group by status/workstream, show owner waits and readiness tonight.
Ready requires verified/queued status, branch/tip, known roll, verified handbacks,
approved/logged requests and landed/closed dependencies. Close a dependency as
satisfied only when resolved; review dependents when cancelling a requirement.
Registry errors suppress readiness and make night-plan fail; board still writes
diagnostics and exits 1. No handoff paste is emitted until branch/handoff exist.
These coordination gates do not replace production merge/readoption gates.

## Backfill and adoption

Each initial record links the pinned seed `074c281d6` from
`origin/codex/worktrack-seed-20260926`. Final corrections supersede early slots;
old tips remain in notes. Branch/PR metadata supplies the three chat missions.
Received timestamps use seed publication (when the backfill knows the reports
existed), not an inferred exact handback time. Missing handoffs, unknown roll,
unverified reports and unlogged approvals remain explicit.

Production reconciles actual receipts, records missing decision rows, verifies
handbacks, updates slots and regenerates its board. Workstations update records
and push handbacks. Never infer completion from a date or branch existence.

## Update when

Update with registry fields, CLI, ownership or check rules. Run
`tests/reporting/test_worktrack.py` and repository audits through the workstation
wrapper; production verification follows its host-load contract.
