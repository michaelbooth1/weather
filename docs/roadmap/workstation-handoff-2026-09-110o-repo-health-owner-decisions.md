# Workstation handoff 2026-09-110o — implement the owner's 10 repo-health decisions

Written 2026-09-26 by the production agent. The owner approved all ten decisions of the
[repo-health audit](audits/repo-health-audit-2026-09-26/README.md) on 2026-09-26. Evidence per decision is in the dimension
files under `audits/repo-health-audit-2026-09-26/dimensions/`. Base: `origin/master` after the 2026-09-27 landing. One
branch per numbered part unless noted; state roll-free or roll-sensitive per file. Run after 110m part 1 and 110n items 1-3.

1. **`config/location_market_events.json` leaves git** (D4-1): generated file moves to a data-root path with an append-only
   dated archive; the ~20 call sites (execution-tape seed gate, live wrapper sealer and stage templates, `snapshot_tracker` /
   `event_metadata_validation`, the three merge tools' allow-lists) read the new path through `weather.paths`; a one-time
   bootstrap copies the tracked file on first run; then `git rm --cached` plus `.gitignore`. Roll-sensitive; the report must
   give the production cut-over order (copy, verify hashes, land, confirm fleet refresh writes the new path).
2. **Seven unscheduled producers** (D1-09): for each, trace the reader, say what it reads today (fixture reasoning), and
   recommend schedule-it (with the Stage-A step or task) or drop-the-input; implement the drop where the reader only
   displays it; for schedule-it, produce the change and leave activation to production. List them in the 110m part 5
   producer allow-list until resolved.
3. **Retire taker and paper-maker code** (D2, D7): after 110n item 3 removes the taker from Stage-A and 110m part 3 decouples
   the helpers, delete the taker and paper-maker runtime code, their daily_refresh steps, schema-registry rows, ownership-map
   entries and tests (7,990 + 4,183 test lines), keeping any reader of retained evidence (EF citations) working through a
   small read-only module. Tapes and run folders under `data/` are untouched. Roll-sensitive.
4. **CI workflows** (D8): remove `retrain.yml` and `settlement-audit-qualification.yml`, update the test and the docs that
   reference them; fix `ci.yml` so master runs are not cancelled in progress (wide-audit CI-3).
5. **Git repack — workstation clone only** (D4-4): run `git count-objects -vH`, `git repack -a -d` (then `git gc` without
   `--prune=now` on refs you have not verified), and report before/after. **Never on the production capture host.** Do not
   touch `.git/lfs`, never re-add `lfs: true`, never rewrite history.
6. **Split `docs/roadmap/correspondence-index.md` by month** (D5-1): the generator writes one file per month plus a small
   top-level index; `agent_docs_audit` checks all of them; stop regenerating unaffected months so docs branches stop
   conflicting. Roll-free (docs + reporting module; confirm no capture import).
7. **Branch lifecycle rule** (D8): document in `docs/git-workflow.md`: merged `codex/*` branches are retired within 7 days,
   archive-tag first for anything not contained in master, deletion through the one-shot push task with a receipt; document
   the `archive/*`, `deployed/*`, `preserve/*` tag namespaces. Add a status check that lists merged branches older than 7 days.
   (Production executes the deletions.)
8. **95d market universe** (D4-5): rebase `codex/weather-market-universe-20260924` so the 24 MB `markets.csv` and other raw
   data stay on that branch (or a data-root path) with hashes and a fetch/rebuild note on master; add the tracked-file size
   budget exemption only for the hash manifest.
9. **Polymarket US adapter refuses order mutation** (D2-05): `PolymarketUSHTTPAdapter` place/cancel paths raise a typed
   refusal naming AGENTS.md's International-only rule; tests prove it; read paths unchanged.
10. **Dormant roadmap items** (D5-5): add a `dormant` status (with dated disposition) to the item format and
    `roadmap_backlog`, mark the 25 listed items including 321, 322 and 328, and add the 45-day dormant flag.

## Boundaries and deliverables

Fixtures only; no production data, credentials, `.env`, Scheduler changes or venue calls. Include the repo-wide audits in
every focused run. Push and draft PRs are authorized. One report per part,
`docs/roadmap/agent-report-2026-09-110o-<n>.md`, verdict first, with the exact production steps.
