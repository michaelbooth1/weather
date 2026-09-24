# Workstation handoff 2026-09-93a — knowledge-structure generator and checks

Written 2026-09-24 by the production agent after a read-only knowledge-structure audit. Serves open questions: none (tooling).
The hand-kept parts are built (on `origin/codex/reward-test-attended-handoff-20260921`): EF §10m, the §10b correction,
`docs/roadmap/audits/README.md`, `docs/operations/OPEN_QUESTIONS.md`, `docs/operations/DECISION_LOG.md`, routing rows, and
the DELEGATION_CONTRACT §4/§5 hooks. This mission makes them hard to let drift.

## 1. Goal

Every index an agent relies on is either generated with a `--check` parity test or covered by a completeness check inside
`python -m weather.operations.agent_docs_audit`, so a stale or broken index fails the audit instead of misleading an agent.

## 2. Build (branch `codex/knowledge-structure-checks-20260924` from the handoff branch tip)

1. **Correspondence index (generated):** a `weather.reporting.roadmap` module writing tracked
   `docs/roadmap/correspondence-index.md` from filenames and H1 titles: mission id, type (handoff/report/work order), title,
   git-added date, answering report (same id or "none in tree"), EF sections and items cited. `--check` exits non-zero on
   drift. No hand-written topics. Tolerate broken links inside immutable dated files.
2. **Audit checks** (add to `agent_docs_audit`): (a) every `docs/roadmap/audits/*.md` and audit sub-directory has a row in
   `audits/README.md`; (b) every `EF §<id>` cited in the findings digest resolves to an EF heading (would have caught the
   missing §10m); (c) `OPEN_QUESTIONS.md` ids are unique and `Q-nn` shaped, pointers resolve, and `ANSWERED` rows cite an
   existing EF anchor; (d) every `Owner 20YY-MM-DD` date in `STATE_OF_PLAY.md` has a same-date row in `DECISION_LOG.md`;
   (e) the correspondence index and `roadmap_backlog --check` parity run inside the audit.
3. **Glossary:** a `## Glossary` section in `docs/operations/AGENT_CONTEXT.md` (term, one line, owner link): B/C strata, mission
   id, roll-sensitive/roll-free, `promotion_countable`, pUSD, T+1/T+2, `P_many`/`P_single`, `k_accrued`, EF/RF/HW, lease,
   quiet window, attempt vs session.
4. **Naming rule** in `docs/roadmap/AGENTS.md`: reports reuse the handoff id (`agent-report-<id>-<slug>`); audits are
   `<scope>-audit-<date>.md` with an index row in the same commit.

## 3. Tests and boundaries

Unit tests for each check with synthetic docs trees (missing row, dangling EF citation, duplicate question id, undated
decision, stale generated index). Run the docs audit and the new tests through `scripts/ops/workstation_heavy.ps1` with a
short `--basetemp`, never during an RE-1 session. Docs and tooling only: no runtime code, no `.env`, no live commands.
Report: `docs/roadmap/agent-report-2026-09-93a-knowledge-structure-checks.md` (verdict first, checks added, what each caught
on the current tree, the tip). Push is authorized.
