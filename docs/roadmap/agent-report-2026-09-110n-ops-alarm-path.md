# Agent report 2026-09-110n — ops scripts and alarm path

Verdict: implementation complete; final fixture verification pending. No production
deployment or Scheduler change has been performed.

Mission source: owner-authorized 110n at handoff branch 2c8b90618.
Branch: codex/ops-alarm-path-20260926, based on integration 8180404a0 pending
tonight's production landing.

## Changes and limits

1. Three-way content merge from deployed/health-watchdog-aa99048 preserves both
   deployed source pins/memory-guard alarms and integration's bounded log rotation.
   The registrar requires two reviewed hashes, checks the pinned-source parameter
   contract before replacement, and reads back the exact action and S4U principal.
2. Settlement-hole count now matches status's emitted date(s) format, escalating
   two or more dates to CRITICAL. The tiering lease-busy message formats the whole
   concatenated string.
3. Stage A passes all three existing taker skip flags. Fixture barrier tests prove
   these skips are non-critical without weakening settlement-truth failures.
4. Nightly health honors the tracked retired maker/taker state without loading old
   bot evidence or suggesting forced starts. Explicit active fixture states retain
   the prior liveness alarms. Unknown lifecycle values fail visibly.
5. Six retired registrars require -AcknowledgeRetired before the register path.
   Enrichment is added to expected-disabled status; its unregister path is retained.
6. Every ops PowerShell script is parsed for syntax, operator-shaped parameters and
   the concatenation/format precedence trap, with positive and negative controls.
   Windows qualification now runs that ratchet and native status/watchdog fixtures.
   Host-literal checks cover every ops script. Seven explicitly counted existing
   exceptions remain, including the frozen incident push bindings; no credentials
   or local environment files were read. Consolidating those bindings needs the
   separate owner decision identified in D6, not an incidental rewrite.
7. The tracked task inventory owns names/patterns, lifecycle, expected-disabled and
   nonzero classifications, registrar and owner. It matches registrar defaults,
   status lists and the generated operating reference. Maintained/active is not a
   claim that a task is enabled. Host-local definitions lacking XML remain
   unverified. Dynamic attempt names are recorded as patterns. Obsolete MM/taker
   quoting language is removed from the generated protected-window rationale.

## Verification

Priority run: 170 passed, two new fixture-harness failures (format argument count
and mock scope) corrected before final verification. Existing native status tests
passed. Config inventory: PASS, nine configs, zero warnings.
Final focused run and all schema/import/agent-doc/path-policy audits pending.
All heavy tests use workstation_heavy.ps1; maker-core import boundaries are included.
No production evidence, credentials, .env, venue calls or Scheduler mutations.

## Roll classification by file

All classifications are source-level conservative estimates; production must obtain
the mechanical roll_verdict before adoption. No production closure evidence is
available on this workstation.

| File | Classification |
| --- | --- |
| scripts/ops/health_watchdog.ps1 | Roll-free; scheduled, pinned redeployment required |
| scripts/ops/status.ps1 | Roll-free; pinned watchdog copy must be redeployed |
| scripts/ops/register_health_watchdog.ps1 | Roll-free; registrar only |
| scripts/ops/daily_refresh_contract.ps1 | Roll-free; wrapper source changes next adopted run |
| scripts/ops/register_taker_bot_daily_roll.ps1 | Roll-free |
| scripts/ops/register_taker_bot_daily_roll_supervisor.ps1 | Roll-free |
| scripts/ops/register_market_making_daily_roll.ps1 | Roll-free |
| scripts/ops/register_market_making_daily_roll_supervisor.ps1 | Roll-free |
| scripts/ops/register_clob_enrichment.ps1 | Roll-free |
| scripts/ops/register_model_market_disagreement_analysis.ps1 | Roll-free |
| src/weather/operations/nightly_health_checks.py | Treat as roll-sensitive pending mechanical closure verdict |
| src/weather/operations/operating_reference.py | Treat as roll-sensitive pending mechanical closure verdict |
| src/weather/operations/config_inventory.py | Treat as roll-sensitive pending mechanical closure verdict |
| config/scheduled_tasks.json | Roll-free lifecycle intent |
| tests/operations/test_health_watchdog_script.py | Roll-free |
| tests/operations/test_status_script.py | Roll-free |
| tests/operations/test_ops_alarm_path.py | Roll-free |
| tests/operations/test_ops_script_ratchets.py | Roll-free |
| tests/operations/test_daily_refresh_script.py | Roll-free |
| tests/operations/test_learning_lane_unblock.py | Roll-free |
| tests/operations/test_nightly_health_checks.py | Roll-free |
| .github/workflows/windows-qualification.yml | Roll-free |
| docs/operations/OPERATIONS_DESIGN.md | Roll-free |
| docs/operations/OPERATING_REFERENCE.md | Roll-free |
| docs/operations/config-inventory.md | Roll-free |
| this report; docs/roadmap/correspondence-index.md | Roll-free |

## Production adoption after owner-ops review

The report's final verification revision will bind the exact reviewed source
commit and script hashes for the watchdog re-registration command.
Do not re-register retired tasks. Stage A's action tokens are unchanged; its child
contract gains skip flags. If its action executes a separate checkout, production
must adopt this source into that checkout under its existing provenance contract.

