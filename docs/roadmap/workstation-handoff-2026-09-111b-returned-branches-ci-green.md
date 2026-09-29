# Workstation handoff 2026-09-111b — get every returned, unlanded branch CI-green on current master

Written 2026-09-29 by the production agent. `master` is `164f12d0a` (integration `85092752a` landed 2026-09-29: 110k,
110m part 1, 110n, fresh 110q, 110v part 1, plus the 2026-09-28 size-audit ownership fix). Nothing joins an integration
branch before its full GitHub CI is green (owner rule 2026-09-27), and every draft PR below is red or cancelled.

## Observed CI state (2026-09-29 13:30)

| PR | Branch | Failure |
| --- | --- | --- |
| #96 | `codex/weather-maker-plugin-20260925` | green (111a changes it next) |
| #100 | `codex/maker-replay-harness-20260926` | `test_module_size_audit` ownership: `closed_day_projection_tiering` (fixed on master) |
| #103, #104, #105, #109, #113, #114, #115 | see PR | same size-audit ownership failure (check each; #105 also fails `hook`) |
| #112 | `codex/replay-execution-pack-20260927` | `test_international_live_wrapper_sealer`: 3 "Regex pattern did not match" + `candidate economics acceptance does not match the sealed evidence` |
| #117-#121 | 110v parts 2-6 | runs CANCELLED (superseded), never completed |
| #124 | `codex/110o-events-data-root-20260928` | green |
| #125 | `codex/110o-unscheduled-producers-20260928` | NEW size warning needs reviewed ownership: `weather.operations.daily_refresh_reporting_steps` |

## Work, in this order (exam tooling first)

1. #100, #112, #113, #114, #115 (the replay-exam line; production needs #112 and #114 for the 2026-09-30 enrolment).
2. #117-#121, #125, #103, #104, #105, #106, #110.
3. #109 is the frozen pre-registration: merge `origin/master` into it only if its CI fails for a master-side reason, and
   never change any `docs/research/maker-replay-*` file or its bytes (its hashes are signed).

For each branch: merge `origin/master` (never rebase or force-push a pushed branch), fix what is still red, push, and
wait for the full GitHub CI to finish green. A fix must be the real cause, not a weakened test: for #112, find why the
sealer's error messages and economics acceptance differ from its tests after the 110q changes on master; for #125, either
shrink the module or add a reviewed ownership entry with a rationale. Where branches stack (plugin #96 under harness #100
under #112-#115), merge downward-first so each PR's diff stays its own.

## Boundaries and deliverables

Fixtures only; no production data, credentials, `.env`, Scheduler changes or venue calls. Heavy commands through
`scripts/ops/workstation_heavy.ps1`. Coordinate with the 111a session: it owns `codex/weather-maker-plugin-20260925`;
do not push to that branch. Report `docs/roadmap/agent-report-2026-09-111b-returned-branches-ci-green.md`: a table of PR,
head SHA, CI run URL and conclusion, and what each fix was.
