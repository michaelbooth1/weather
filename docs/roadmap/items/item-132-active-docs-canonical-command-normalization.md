# 132. Active Docs Canonical Command Normalization [COMPLETE 2026-06-18 - ACTIVE DOC LINT LIVE]

Goal: make active runbooks consistently use canonical `weather.*` commands
while preserving old `src.*` commands only as historical evidence.

Source: 2026-06-18 repository hierarchy review. README and CI now use
canonical `python -m weather...` commands, but several operations and research
docs still show `python -m src.*`. Some are historical audit records, while
others are active runbooks that operators may copy.

Why this matters: command drift keeps deprecated compatibility wrappers alive.
Current runbooks should teach the supported interface. Historical docs can keep
old commands only when they are clearly framed as records of past runs rather
than instructions to execute today.

## Design

1. Classify docs into active runbooks, current design docs, research records,
   and historical audit logs.
2. Update active docs to canonical `python -m weather...` commands.
3. Add a short historical-command note where old `src.*` commands remain in
   audit history.
4. Add a docs lint or search check for active docs that fail on new `-m src.`
   command examples.
5. Leave old commands untouched in archived evidence where changing them would
   distort the record.

- [x] Update active operations docs that still use `python -m src.*`.
- [x] Update current research runbooks that are not historical records.
- [x] Add a convention for marking historical command transcripts.
- [x] Add a search/lint check scoped to active docs.
- [x] Verify README, CI, scheduled-task scripts, and active docs agree on
  canonical commands.

Acceptance: active operator-facing docs use `weather.*` command examples,
historical docs that keep `src.*` examples are explicitly marked as historical,
and new active-doc command drift is caught by a lightweight check.

## Completion

Completed 2026-06-18.

Implementation:

- Updated `docs/operations/AGENT_CONTEXT.md` from legacy flat module names and
  root dashboard references to canonical `weather.*` modules and
  `app/streamlit_app.py`.
- Updated the current market-making runbooks
  `docs/research/MARKET_MAKING_LIVE_RUNBOOK_2026-06-15.md` and
  `docs/research/MM_INITIAL_TEST_RUN_DESIGN.md` to use canonical
  `python -m weather...` examples.
- Added the active-document command convention to
  `docs/operations/path-policy.md`.
- Added `test_active_docs_use_canonical_weather_commands` to the import
  architecture tests. It scans README, CI, active operations docs, and the
  active market-making research runbooks for legacy command drift.

Verification:

- Scoped search for legacy active-doc command examples across README, CI,
  scripts, `docs/operations`, and the active market-making runbooks returned no
  matches.
- `python -m pytest tests\operations\test_import_architecture.py::test_active_docs_use_canonical_weather_commands tests\operations\test_import_architecture.py::test_first_party_surfaces_do_not_call_compatibility_shims -q`
  passed.
