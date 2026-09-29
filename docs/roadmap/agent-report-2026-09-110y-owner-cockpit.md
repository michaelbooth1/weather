# Agent report 2026-09-110y — owner cockpit page

**VERDICT: IMPLEMENTED, ROLL-FREE. The Owner Cockpit is the new default Streamlit page: Money / Work / Health /
Exam columns from a read-only snapshot in which every source is optional and states why it is unavailable. No
mutation controls; the page fails closed. One deliberate deviation from the handoff: the snapshot module lives at
`src/weather/reporting/market/cockpit_snapshot.py`, not the reporting package root (reason below). Nothing was
registered, written to production, restarted or merged.**

Branch `codex/owner-cockpit-20260928`, base `origin/master` `b0032a90` merged with
`origin/codex/W-tracker-step1-20260927` (`0d4e3f00`, PR #110) as the handoff says. Serves open questions: none.

## Delivered

- `weather.reporting.market.cockpit_snapshot.collect_cockpit_snapshot()` (stdlib + `weather.paths`; lazy imports of
  `worktrack` and the GET-only `wallet_reader_client`). Sections:
  - **Money:** wallet reader `summary` and `rewards` (previous UTC day; `earnings` summed only when every row parses,
    otherwise "unparsed"). Campaign P&L is shown only when the reader reports `OBSERVED`/`BLEED_LIMIT` *and* returns a
    number; otherwise `pnl_pusd` is null and `pnl_reason` carries `INCOMPLETE: <reasons>`. The per-campaign ledger book
    is dropped (embargo). Client refusals surface only the client's reason code (`config`, `timeout`, `refused`,
    `http_NNN`), never the token or URL. Client timeout is the minimum 5 s.
  - **Work:** `worktrack.load_records`/`check`/`blockers` over `docs/roadmap/work/`. Pending owner requests with age in
    days, `overdue` above 3 days (the registry's own check threshold); open counts by status and owner; records with no
    blockers ("ready to land"); the `check` issues.
  - **Health:** `data/alerts/host_health_latest.json` (BOM-tolerant; stale above 60 min), the last 64 KiB of
    `data/alerts/disk_free_trail.jsonl` (24 h slope computed exactly as `status.ps1` does: latest sample versus the
    newest sample at least 24 h older; days to 50 and 40 GiB only when falling, 0 when already below), and
    `data/maker_evidence/status.json` plus closed 88a UTC dates.
  - **Closed 88a UTC date** = a date directory before today (UTC) in which every hourly segment folder has
    `manifest.json` or `manifest.json.gz`. Dates with an unsealed or no segment are listed separately. Only directory
    names and manifest existence are read; no journal content.
  - **Exam:** constants citing DECISION_LOG 2026-09-27 (Clarification 1: calibration 09-27..29, panel 09-30..10-13,
    settlement 10-14, look 10-15; one-sided second candidate: panel 10-16..10-29, look 10-31). Phase, days to look,
    closed 88a panel dates out of 14 (unknown, not zero, when 88a is unavailable).
- `app/views/cockpit.py`: four columns, no buttons/inputs. The body renders inside an `st.empty()` container that is
  cleared on any exception, so a render fault shows one error and no partial numbers.
- Router: three pages. No query → Cockpit (`?cockpit`); any `?market=` (control and retired routes) → Control Room;
  `?roadmap` unchanged. The Control Room is labelled "Control Room (historical pilot view)" with an info banner.
- **Embargo:** no policy P&L or policy comparison anywhere; the snapshot never reads maker scoring, and the wallet
  campaign book is excluded (tested). The Exam column states the embargo.
- Docs: README dashboard section, `app/AGENTS.md`, `docs/architecture.md`, `OPERATIONS_DESIGN.md` layer 2,
  `NIGHTLY_RETRAIN_RUNBOOK.md` page count. The launcher (`scripts/launch/start_weather_dashboard.ps1`) now opens
  `?cockpit` so "default page" holds for the owner's normal entry point — a one-line change outside the named files,
  flagged here.
- Merge of the tracker branch: `docs/documentation-maintenance.md` conflict resolved by keeping both sides (wallet and
  portfolio rows plus the work-registry rows); `correspondence-index.md` regenerated.

### Deviation: module path

`src/weather/reporting/AGENTS.md` reserves the reporting package root for shared helpers and puts domain reporting in a
subpackage; nested `AGENTS.md` takes precedence for its subtree. The cockpit replaces the Control Room as the default
page, whose reducer is `weather.reporting.market.operator_control_room`, so it sits beside it. The
`reporting -> market` edge is stable in the import ratchet.

## Tests (fixtures only; no network, no `.env`, no `data/`)

`tests/reporting/test_cockpit_snapshot.py` (10): every source missing → each unavailable with a reason; INCOMPLETE P&L
never shown as a number even when the reader returns one, campaign book dropped; OBSERVED P&L shown; negative disk slope
→ days to 50/40 GiB; tail-only read and non-falling slope; owner wait older than 3 days → overdue and a check issue;
host-health BOM and staleness; closed-date counting; exam phases across the calendar; reward-shape refusal.
`tests/app/test_cockpit_view.py` (4): default route renders read-only cockpit; render-time exception drops the partial
page; load exception fails closed; retired `?market=` route still opens the Control Room. Existing app tests updated
for three pages and the new label.

Workstation results under `scripts\ops\workstation_heavy.ps1`: the focused set below, including the repo-wide
schema-registry, import-architecture, agent-docs, path-policy, module-size, knowledge-structure and structure-inventory
audits, **118 passed**. `compileall` over `app`, `src/weather/reporting/market`, `tests/app` and `tests/reporting` is
clean, and `weather.operations.agent_docs_audit` PASSES. The first run caught an unregistered `owner_cockpit_snapshot_v1`
literal. The snapshot is never persisted, so the fix removed the version. Registering one would have put a
`schema_registry*` change, which enters all four closures, into a roll-free branch. GitHub CI for PR #132 is reported
in the handback reply.

## Per-file roll verdict

`roll_verdict.ps1` needs the production status files and was not run here; production must obtain it. Derivation for
review: every changed Python file is either new, under `app/`, or under `tests/`; none is in the snapshot, CLOB,
observation-trigger or CLOB-enrichment closures (the Streamlit app and a brand-new module are not imported by any
capture loop). No `schema_registry*` change.

| File | Closures entered |
| --- | --- |
| `src/weather/reporting/market/cockpit_snapshot.py` (new) | none |
| `app/streamlit_app.py`, `app/views/cockpit.py` (new), `app/views/control_room.py`, `app/views/roadmap.py` (docstring) | none |
| `tests/app/*`, `tests/reporting/test_cockpit_snapshot.py` | none |
| `scripts/launch/start_weather_dashboard.ps1` | none (`.ps1`) |
| `README.md`, `app/AGENTS.md`, `docs/**` | none (Markdown) |
| Tracker merge: `src/weather/reporting/roadmap/worktrack.py`, `docs/roadmap/work/*` | none (PR #110's own verdict) |

## What was NOT done

No Scheduler registration, no production or `data/` write, no restart, no merge to master, no wallet-reader call, no
venue call, no credentials read. No W record exists for 110y in `docs/roadmap/work/`; none was allocated here to avoid
an id collision with parallel sessions — production should create or link one.

## Reproduction (workstation, from the branch checkout)

```powershell
.\venv\Scripts\python.exe -m pytest -q tests\app tests\reporting\test_cockpit_snapshot.py tests\reporting\test_worktrack.py tests\operations\test_schema_registry.py tests\operations\test_import_architecture.py tests\operations\test_agent_docs_audit.py tests\operations\test_path_policy.py tests\operations\test_module_size_audit.py tests\operations\test_knowledge_structure_audit.py tests\operations\test_structure_inventory.py
.\venv\Scripts\python.exe -m weather.operations.agent_docs_audit
.\venv\Scripts\python.exe -m streamlit run app/streamlit_app.py
```

On the capture host these run only under its host-load policy.
