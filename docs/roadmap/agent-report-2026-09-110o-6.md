# 110o part 6 — correspondence index split by month (owner decision 6, D5-1) [DONE]

**Verdict: DONE, roll-free. `weather.reporting.roadmap.correspondence_index` now writes one shard per Git-added month
(`docs/roadmap/correspondence-index/<YYYY-MM>.md`) under a small root `docs/roadmap/correspondence-index.md` that lists
the months only; it rewrites only shards whose rows changed and removes shards no longer generated.
`agent_docs_audit` (through `knowledge_structure_audit.generated_index_errors`) checks the root, every shard, and stray
shard files.** A new report now changes its own month's shard only; closed months and the root stay byte-identical.

Branch `codex/110o-correspondence-index-by-month-20260929`; handoff
[workstation-handoff-2026-09-110o](workstation-handoff-2026-09-110o-repo-health-owner-decisions.md) part 6; audit row
D5-1 option (a) ([D5](audits/repo-health-audit-2026-09-26/dimensions/D5.md)).

## Design

- **Shard key = Git-added month**, the same date the single file already used (never filename dates or the clock).
- **Root lists months without counts**, so it changes only when a new month starts (or an `uncommitted` shard appears).
- **`uncommitted.md`** holds rows for files not yet committed. The documented workflow (commit the report, then
  regenerate) moves the row into its month and deletes that shard, so it is never committed in practice; `--check`
  flags it if it is.
- **Residual churn, stated honestly:** the "answering report" column of a handoff row changes when its report lands. If
  the report lands in a later month, the handoff's (closed) month shard changes once. Title/citation edits to an old
  immutable record would too.

## What changed

| File | Roll | Change |
| --- | --- | --- |
| `src/weather/reporting/roadmap/correspondence_index.py` | roll-free (docs tooling; imported only by `knowledge_structure_audit` / `agent_docs_audit`; confirm) | `render_index` → `render_outputs` (root + shards), `write_outputs` (writes changed files only, removes stale shards), `parity_errors` over all outputs plus stray shards. Row extraction and dating are unchanged. |
| `docs/roadmap/correspondence-index.md` | roll-free | Now the small root (13 lines instead of ~256 KB). |
| `docs/roadmap/correspondence-index/2026-07.md`, `2026-08.md`, `2026-09.md` | roll-free | Generated shards; links are `../<file>`. |
| `tests/reporting/test_correspondence_index.py` | roll-free | Existing tests moved to shards; new test: a new month leaves the closed shard byte-identical, `uncommitted` is transient, a second run writes nothing, stray shard is a parity error. |
| `tests/operations/test_knowledge_structure_audit.py` | roll-free | Writes all generated outputs; a new uncommitted report is now two correspondence errors (root + missing shard). |
| `docs/roadmap/AGENTS.md` | roll-free | Describes the shards. |

## Verification

`python -m weather.reporting.roadmap.correspondence_index` then `--check`: OK; a second run prints
`Correspondence index: unchanged`. pytest over `test_correspondence_index.py`, `test_knowledge_structure_audit.py` and the
repo-wide audits (`test_agent_docs_audit`, `test_import_architecture`, `test_module_size_audit`, `test_path_policy`,
`test_schema_registry`, `test_structure_inventory`, `tests/app/test_app_architecture`): 83 passed. `agent_docs_audit`
PASS; `roadmap_backlog --check` OK.

## What was NOT done

No registration, production write, restart or merge. No correspondence file was moved or edited (D5-4's
per-month directory for new correspondence stays an owner option).

## Production steps

1. CI green; `roll_verdict.ps1 -Branch codex/110o-correspondence-index-by-month-20260929` roll-free; land on the
   roll-free light path when the exam-period merge policy allows.
2. **Every open branch that touched `docs/roadmap/correspondence-index.md` will conflict once.** Resolution: merge
   `origin/master`, take master's version of the root, run `python -m weather.reporting.roadmap.correspondence_index`,
   commit. From then on docs branches conflict only when they add correspondence in the same month shard.
