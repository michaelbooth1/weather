# 110o part 1 report — move generated event snapshot to data/

**Verdict: implemented and locally qualified; production cutover remains pending.** The tracked Gamma event snapshot is removed from the current tree, readers use `data/location_market_events.json`, refreshes atomically replace it after archiving prior bytes, and the one-time bootstrap copies the legacy bytes exactly. The move is conservatively roll-sensitive because Python runtime files and live-stage templates changed. The workstation `roll_verdict.ps1` result is **UNDECIDABLE**: no production closure evidence is present here. Production closure membership and fleet adoption are unverified.

Base: `3b93c6f3259f11d66f6e6d0c995a881aa1ff303e` (`origin/master` at implementation start). Local checked-in legacy blob OID and copied ignored data blob OID both equal `7bec74c070afc169caab46f1a008536d601d43cb`; `data/location_market_events.json` matches `.gitignore`, while `config/location_market_events.json` is no longer tracked. The full file SHA-256 equality check also passed. The local snapshot is a copy of the checked-in repository snapshot, not production state; tests use fixtures and did not read that ignored file.

## Per-file roll classification

Source files are conservatively marked roll-sensitive until production runs the authoritative closure check. `roll_verdict.ps1` on this workstation returned UNDECIDABLE because the four capture closure status files are absent.

| File | Roll classification | Change |
| --- | --- | --- |
| `.gitignore` | Roll-free | Keep the current snapshot and archive ignored. |
| `README.md` | Roll-free | Document the new path and refresh command. |
| `config/AGENTS.md` | Roll-free | Transfer generated-file ownership to the data-root snapshot. |
| `config/location_market_events.json` | Roll-free; cutover-sensitive | Remove the tracked current snapshot; Git history remains intact. |
| `config/locations.json` | Roll-free; cutover-sensitive | Point to the snapshot path and remove the duplicate refresh timestamp. |
| `docs/architecture.md` | Roll-free | Update canonical path. |
| `docs/operations/EXCHANGE_ECONOMICS_SNAPSHOT_RUNBOOK.md` | Roll-free | Update reader path. |
| `docs/operations/OPERATIONS_AGENT_ROLE.md` | Roll-free | Update generated-drift description. |
| `docs/operations/OPERATIONS_DESIGN.md` | Roll-free | Update snapshot source description. |
| `docs/operations/RELEASE_ONE_BUILD_RUNBOOK.md` | Roll-free | Update old build and staging instructions. |
| `docs/operations/config-inventory.md` | Roll-free | Classify the ignored snapshot and record bootstrap steps. |
| `scripts/ops/boot_recovery.ps1` | Roll-free | Recover markers using their exact recorded path set and preserve the snapshot hash pin. |
| `scripts/ops/international_live_templates/stage0.py.tmpl` | Roll-sensitive pending verdict | Narrow tracked dirty-path allowance. |
| `scripts/ops/international_live_templates/stage1_cancel_all.py.tmpl` | Roll-sensitive pending verdict | Narrow tracked dirty-path allowance. |
| `scripts/ops/quiet_window_merge.ps1` | Roll-free | Commit only tracked locations drift; bind the ignored snapshot SHA-256 in active markers and verify it before merge. The spent production-baseline incident hashes and two-file contract remain unchanged. |
| `scripts/ops/refresh_location_config.ps1` | Roll-free | Default writes to the new data path. |
| `scripts/ops/register_location_config_refresh.ps1` | Roll-free | Update task description; no scheduler was touched. |
| `scripts/ops/training_window.ps1` | Roll-free | Auto-commit only tracked locations drift. |
| `src/weather/io.py` | Roll-sensitive pending verdict | Add atomic byte replacement. |
| `src/weather/market/exchange_economics.py` | Roll-sensitive pending verdict | Read the new default snapshot path. |
| `src/weather/market/execution_tape_capture.py` | Roll-sensitive pending verdict | Read the new default snapshot path. |
| `src/weather/operations/config_inventory.py` | Roll-sensitive pending verdict | Inventory the data-root snapshot and freshness timestamp. |
| `src/weather/operations/event_metadata_validation.py` | Roll-sensitive pending verdict | Validate and document the new default path. |
| `src/weather/operations/international_live_wrapper_sealer.py` | Roll-sensitive pending verdict | Remove the deleted tracked file from the dirty-path allowance. |
| `src/weather/operations/location_config_refresh.py` | Roll-sensitive pending verdict | Add exact-byte bootstrap, append-only archive, atomic LF writer, and remove duplicate timestamp output. |
| `src/weather/operations/release_candidate_contract.py` | Roll-sensitive pending verdict | Freeze the event snapshot from `data/` into the release contract. |
| `src/weather/paths.py` | Roll-sensitive pending verdict | Define canonical new and legacy paths. |
| `src/weather/reporting/source_gates/source_family_inventory.py` | Roll-sensitive pending verdict | Read the data-root snapshot by default. |
| `tests/fixtures/toronto_signed_band_replay.json` | Roll-free | Update fixture provenance path. |
| `tests/operations/test_config_inventory.py` | Roll-free | Use fixture data path and assert inventory provenance. |
| `tests/operations/test_daily_refresh.py` | Roll-free | Use fixture data path. |
| `tests/operations/test_international_live_wrapper_sealer.py` | Roll-free | Prove the ignored snapshot is not an allowed tracked dirty path. |
| `tests/operations/test_location_config_refresh.py` | Roll-free | Cover exact-byte bootstrap, archive append behavior, and LF atomic output. |
| `tests/operations/test_quiet_window_merge_script.py` | Roll-free | Fixture-check the new data SHA pin and tracked dirty allow-list; preserve retired incident-pin assertions. |
| `tests/operations/test_release_candidate_contract.py` | Roll-free | Build the snapshot fixture under `data/`. |

## Verification

- Wrapper-focused suite: **501 passed, 17 subtests passed** in 373.15 seconds. It included the full live-wrapper sealer module and all four required repository audits: schema registry, import architecture, agent docs, and path policy.
- Wrapper `compileall -q app src tests`: passed.
- `git diff --check`: passed.
- Exact-byte provenance: legacy and local data snapshot blob OIDs match; ignored path confirmed; legacy path absent from the index.
- No API/network call or production data read was made. Production live closure membership remains unverified.

## Production cutover steps — not executed here

1. On the production workstation, while the legacy tracked file still exists and before landing this branch, run `.\venv\Scripts\python.exe -m weather.operations.location_config_refresh --bootstrap-legacy --event-metadata data\location_market_events.json`.
2. Compare `(Get-FileHash config\location_market_events.json -Algorithm SHA256).Hash` with `(Get-FileHash data\location_market_events.json -Algorithm SHA256).Hash`; require an exact match. Confirm the dated file exists under `data\location_market_events_archive\` and the data path is ignored.
3. Run the production `roll_verdict.ps1 -Branch <branch>` against the reviewed full tip. Because this branch is conservatively roll-sensitive, use the scheduled quiet-window merge if the authoritative verdict is ROLL-SENSITIVE or UNDECIDABLE; do not infer a roll-free result from this workstation.
4. Land the reviewed tip with the existing quiet-window merge gates. Verify the tracked legacy file is absent and the data snapshot remains byte-identical after merge.
5. Let the existing fleet refresh write `data\location_market_events.json`, then run event metadata validation and config inventory. Confirm the snapshot timestamp comes from its own `generated_at_utc`, the durable registry has no `last_refreshed_at_utc`, and every runtime reader resolves the data-root path.

The one-time `quiet_window_merge.ps1 -ProductionBaselineReconciliation` hash pins are deliberately unchanged: they authenticate a spent, incident-specific two-file baseline, not the active generated-drift allow-list. The active merge path now captures and verifies a dynamic SHA-256 pin for the ignored data snapshot.
