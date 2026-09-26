# Repository long-term-health audit — 2026-09-26

- **Owns:** the synthesis of the 2026-09-26 repo-health audit (legacy code, retired-feature residue, oversized modules,
  config/evidence bloat, docs growth, scheduled scripts, tests, dependencies/CI/branches), its prioritized action list and
  the proposed regrowth ratchets.
- **Read when:** planning clean-up, retiring a feature, splitting a module, or adding a ratchet.
- **Do not use for:** current state (STATE_OF_PLAY) or `data/` storage ([storage value assessment](../storage-value-assessment-2026-09-26.md)).

Method: a Fable planning agent defined eight dimensions ([PLAN](PLAN.md)); eight read-only subagents audited them on the
production host with batched `git grep`/`git log` only, each with a skeptic pass on every delete/archive row
([D1](dimensions/D1.md) dead code, [D2](dimensions/D2.md) retired residue, [D3](dimensions/D3.md) size and duplication,
[D4](dimensions/D4.md) config/artifacts/evidence, [D5](dimensions/D5.md) docs growth, [D6](dimensions/D6.md) scripts and
tasks, [D7](dimensions/D7.md) tests, [D8](dimensions/D8.md) deps/CI/branches). Roll labels are import-trace estimates;
production takes `roll_verdict.ps1` before any merge.

## Verdict

The repository is structurally sound — every config file has a reader, every artifact is manifest-bound, every large
evidence blob is cited, no dead links in live docs, skip markers are healthy — but it carries **four live defects found by
the audit**, **retired features still wired into the daily chain and alarms**, and **growth with no ceiling** (module size
allow-list 11 → 23 in two months, generated index churn, 43k lines of unimported research code). Almost nothing should be
deleted; the work is fix, decouple, archive-in-place and ratchet.

## Live defects (fix first)

1. **Unsigned band parser in live capture** (D3-01/02): `market_microstructure_capture.label_bin_metadata` uses
   `re.findall(r"\d+")`, so `-2°C or below` is recorded as `lte 2` in every CLOB token row (`bin_value`), read by markouts,
   microstructure features and paper scoring; `observation_trigger.band_key` has the same fallback and treats 0 as missing.
   95b fixed six other callers. Negative Celsius labels start around November. Quiet window. → 110m.
2. **Settlement holes never reach CRITICAL** (D6-03, ps-ops-3 still open): `health_watchdog.ps1:139` regex never matches
   `status.ps1:1866`; `status.ps1:1613-1616` prints a literal `{0}` (`-f` binds tighter than `+`). → 110n.
3. **Deployed watchdog is not on master** (D6-01): `WeatherHostHealthWatchdog` runs tag `deployed/health-watchdog-aa99048`;
   master's registrar cannot express its hash pins, so fixes on master never reach the alarm path and re-registering from
   master would downgrade it. → 110n.
4. **Unscheduled producers feed live readers** (D1-09): seven modules nothing schedules write JSON that
   `daily_refresh_reporting_steps.py:837`, `market_beating_objective_scoreboard.py:18-20` and
   `promotion/orchestration.py:653-674` read — those readers likely see stale or missing inputs. Owner decision.

## Prioritized actions

**Roll-free quick wins** (docs, `.ps1`, config, pins; production or workstation, any hour after review)
- Retired taker off the Stage-A critical path: pass the existing `--skip-taker-*` flags in `daily_refresh_contract.ps1`
  and update the two flag-list tests (D2-01; archiving taker evidence would otherwise block promotion).
- Silence retired-bot false CRITICALs in `nightly_health_checks.py` whose remedy restarts a retired bot (D2-02; check roll).
- Registrars refuse retired tasks without `-AcknowledgeRetired`: taker, paper maker, clob enrichment, model-market
  disagreement (D2-03, D6-05).
- Pin `pyarrow==24.0.0` (undeclared, imported by parquet evidence writers) (D8); move harness ignore paths from
  `.git/info/exclude` into `.gitignore` (D8); document `archive/*`, `deployed/*`, `preserve/*` tags in the git SOP (D8).
- Suite runner points `TEMP`/`TMP` inside each chunk's basetemp (1,233 `TemporaryDirectory` uses escape cleanup) (D7).
- Fix wording "25-file bounded suite" (it runs every tracked test; 25 is chunk size) in AGENTS.md, HOST_LOAD_POLICY,
  OPERATIONS_AGENT_ROLE and the pinned test text (D7).
- Docs routing: `forward-plan-2026-09-23.md` and `live-testing-plan` are routed as current but are history/paused (D5-6/7);
  OPERATING_REFERENCE window text still describes MM quoting and the taker (D6-08); stale "mirror runs nightly" text (D2).
- Deletes that survived the skeptic pass: `operations/runtime_identity.py` (5-line unused re-export), 16 retired
  `tools/research` stubs and their harness rows, `tests/fixtures/smoke/` (D1-01/02/03, D7).

**Roll-sensitive (quiet window, bounded suite)**
- Signed band parsing in capture (defect 1) via `weather.units.parse_temperature_band`, with negative-label tests.
- `point_in_time_contract` gains the two hash parameters so `residual_distribution_release` stops importing
  `reporting.point_in_time_evaluation`; removes ~9.5k research lines from the capture supervisors' lazy import path and
  the 12 diverged duplicate functions (D3-05).
- Decouple live code from paper-maker helpers (`utc_now`, `maybe_float`, pilot cap, `REMEDIATION_RULES`) so the paper maker
  can be frozen (D2-04); consolidate the 32 `datetime`-returning `utc_now` copies (D3).
- Archive-in-place of unimported research reporting (~25k lines; needs a schema-registry edit) (D1-06/07/08).

**Owner decisions — all 10 APPROVED 2026-09-26** (implementation: 110m, 110n, 110o; branch lifecycle and workstation repack as noted in 110o)
1. Move `config/location_market_events.json` (generated, 90 commits, ~25-60 MB/yr of history, permanently dirty production
   tree) to `data/` with an append-only archive (~20 call sites) (D4-1; open since 09-18).
2. The seven unscheduled producers (defect 4): schedule them or drop their inputs.
3. Fully retire taker and paper-maker code and their tests (7,990 + 4,183 test lines) once Stage-A no longer calls them, or
   keep them as a compatibility surface (D2, D7).
4. `retrain.yml` (dormant, would not work as written) and `settlement-audit-qualification.yml` (dead push trigger,
   duplicate suite): fix or remove (D8).
5. Git repack on the **workstation clone only** (~450-490 MB of duplicated packs; never on the capture host) (D4-4).
6. Split `docs/roadmap/correspondence-index.md` by month (256 KB, 30 commits in 3 days, conflicts on every docs branch) (D5-1).
7. Branch lifecycle: retire merged `codex/*` branches within 7 days through the one-shot push task; archive-tag first (D8).
8. Keep 95d's 24 MB `markets.csv` off master (hashes on master, raw on its branch) (D4-5).
9. `PolymarketUSHTTPAdapter` can place orders though only tests build it: make it refuse order mutation (D2-05).
10. Mark 25 untouched active roadmap items (incl. 321 Release #1, 322 taker, 328 paper maker) dormant with a dated
    disposition (D5-5).

## Regrowth ratchets (proposed)

Per-module `max_lines` cap with a shrink-only allow-list, also for `tests/` and `maker_core` (D3); orphan-module test with a
shrink-only allow-list (D1); retired-symbol count that may only fall (D2); no new `_c` names without an allow-list entry
(D2); no unsigned band regex outside `weather.units` (D3); tracked-file size budget (>1 MiB needs allow-listing, roadmap data
>250 KB needs a mission id) (D4); venv-vs-pin drift check in `status.ps1` and after pin-changing merges, plus an
undeclared-import test (D8); register scripts refuse retired tasks and a tracked scheduled-task inventory tested against
registrars, `status.ps1` and docs (D6); watchdog regex must match `status.ps1` flag text (D6); PowerShell
operator-as-parameter and `-f`/`+` precedence check over all 76 scripts (D6); every report JSON read by the daily chain has
a scheduled producer (D1); generated-file churn guard and a 45-day dormant-item flag (D5).

## Done during the audit

- Pushed the local-only tag `archive/wt-stage2-build-20260921` (`dbf2f065f`) to origin (D8).
- Suite runs on production now redirect `TEMP`/`TMP` inside a cleaned root (night plan 2026-09-27).
