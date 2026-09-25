# Audit index

- **Owns:** the list of every audit under `docs/roadmap/audits/`, with scope, one-line verdict, what is still open and where
  the dispositions landed.
- **Read when:** you need the evidence behind a digest or established finding, want to know whether an area was already
  audited, or are about to run a new audit (see [how to run a second-opinion audit](#running-a-new-audit)).
- **Do not use for:** current state ([STATE_OF_PLAY](../../operations/STATE_OF_PLAY.md)), measured results
  ([findings digest](../../operations/FINDINGS_DIGEST.md)), or open research questions
  ([open questions](../../operations/OPEN_QUESTIONS.md)).

Audits are dated evidence, never instructions. Every file here must have a row (a new audit adds its row in the same
commit). Status: **OPEN** = findings awaiting action or an owner decision; **DISPOSED** = every finding has a recorded
disposition; **HISTORICAL** = predates the current canon and was not re-checked against it (use only via the digest's
citations).

| Audit | Added | Scope | Verdict (one line) | Open | Dispositions | Status |
| --- | --- | --- | --- | --- | --- | --- |
| [positions-review-2026-09-25](positions-review-2026-09-25.md) | 2026-09-25 | open RE-1 lots: hold/sell/rest EV, inventory policy, wallet reader | sell Miami, rest Chicago @0.37; policy + bleed limit; reader as a keyless script | wallet reader (100a) | inside the file; owner placed both orders | OPEN |
| [post-night-audit-2026-09-25](post-night-audit-2026-09-25.md) | 2026-09-25 | night landings, 88a/89a data path, disk, next moves | landings sound; 89a cannot read 88a output yet; disk tight for tonight | adapter, canon repair, two-band owner decision | inside the file | OPEN |
| [pre-night-audit-2026-09-24](pre-night-audit-2026-09-24.md) | 2026-09-24 | RE-1 code, landing plan, host, docs, 89a readiness | all areas GO or fixed | leftovers for owner review | inside the file | DISPOSED |
| [host-and-model-audit-2026-09-24](host-and-model-audit-2026-09-24.md) | 2026-09-24 | host, model, logging, RAM, storage, fleet, settlement, repo | capture healthy, instruments mislead; true disk low 43.2 GiB; learning lane dead since 08-13 | learning-lane reorder, monitoring flags, spent one-shots, boot-recovery tip, signed band parser, log rotation | inside the file; owner host actions 09-24 | OPEN |
| [second-opinion-audit-2026-09-24](second-opinion-audit-2026-09-24.md) | 2026-09-24 | RE-1 code, pre-registrations, ops fixes, handbacks, plan; follow-up; inventory review | safety envelope intact; selection chose empty books; fixes verified; resting sells a design input | owner: withdraw test (S1), resting-sell test (S2) not yet run | inside the file; EF §10m-§10o | OPEN |
| [full-audit-2026-09-18](full-audit-2026-09-18/) | 2026-09-19 | whole project (296 findings) | retained record of the September full audit | see its README | its README and owner-decision sheet | OPEN |
| [codex-project-audit-2026-08-11](codex-project-audit-2026-08-11.md) | 2026-08-11 | project | August project audit | not re-checked | — | HISTORICAL |
| [python-structure-refactor-audit-2026-06-25](python-structure-refactor-audit-2026-06-25.md) | 2026-06-25 | Python structure | refactor audit | not re-checked | — | HISTORICAL |
| [python-log-audit-2026-06-24](python-log-audit-2026-06-24.md) | 2026-06-25 | Python and runtime logs | log audit | not re-checked | — | HISTORICAL |
| [system-level-backlog-audit-2026-06-24](system-level-backlog-audit-2026-06-24.md) | 2026-06-23 | backlog | system-level backlog audit | not re-checked | — | HISTORICAL |
| [calibration-price-competitiveness-audit-2026-06-23](calibration-price-competitiveness-audit-2026-06-23.md) | 2026-06-23 | calibration vs market price | calibration and price competitiveness | not re-checked | — | HISTORICAL |
| [trading-stack-performance-strategy-audit-2026-06-23](trading-stack-performance-strategy-audit-2026-06-23.md) | 2026-06-22 | trading stack | performance and profitability | not re-checked | — | HISTORICAL |
| [taker-bot-performance-strategy-audit-2026-06-23](taker-bot-performance-strategy-audit-2026-06-23.md) | 2026-06-22 | taker bot (paused) | performance strategy | not re-checked | — | HISTORICAL |
| [taker-bot-performance-strategy-audit-2026-06-22](taker-bot-performance-strategy-audit-2026-06-22.md) | 2026-06-22 | taker bot (paused) | performance strategy | not re-checked | — | HISTORICAL |
| [closed-roadmap-model-progress-audit-2026-06-22](closed-roadmap-model-progress-audit-2026-06-22.md) | 2026-06-22 | closed roadmap, model progress | model progress | not re-checked | — | HISTORICAL |
| [early-hour-model-performance-audit-2026-06-22](early-hour-model-performance-audit-2026-06-22.md) | 2026-06-22 | early-hour model | early-hour performance | not re-checked | — | HISTORICAL |
| [location-performance-model-audit-2026-06-22](location-performance-model-audit-2026-06-22.md) | 2026-06-22 | per-location model | location performance | not re-checked | — | HISTORICAL |
| [settled-log-audit-2026-06-20](settled-log-audit-2026-06-20.md) | 2026-06-21 | settled logs | settled-day logs | not re-checked | — | HISTORICAL |
| [taker-bot-log-audit-2026-06-20](taker-bot-log-audit-2026-06-20.md) | 2026-06-20 | taker bot logs | log audit | not re-checked | — | HISTORICAL |
| [codex-deep-model-audit-2026-05-28](codex-deep-model-audit-2026-05-28.md) | 2026-06-15 | model | May deep model audit | not re-checked | — | HISTORICAL |
| [codex-audit-summary-2026-05-28](codex-audit-summary-2026-05-28.md) | 2026-06-15 | project | May audit summary | not re-checked | — | HISTORICAL |

## Running a new audit

Use a cheap read-only second-opinion subagent (a different model gives an independent view). Its brief must include: the
read order (AGENTS.md, STATE_OF_PLAY, the findings digest, the relevant owners); hard rules (read-only; no edits, tests,
processes, venue calls or credential files; never walk `data/` on the capture host; bounded reads of live logs); the scope as
concrete questions; and the output shape — verdict paragraph, findings table (severity, area, finding, evidence as `path:line`
or commit, recommended action, agent-alone or owner decision), a "sound, leave alone" list, and anything unverified marked
UNVERIFIED. The production agent then verifies the key claims before acting, saves the audit here with a **Dispositions**
column filled, and adds its row above.
