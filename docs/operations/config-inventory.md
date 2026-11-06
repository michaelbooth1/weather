# Config Inventory

Status: canonical configuration classification and freshness policy.

Checked-in files under `config/` are classified by owner and freshness policy:

| File | Classification | Policy |
| :--- | :--- | :--- |
| `scheduled_tasks.json` | Hand-authored task lifecycle registry | Reviewed intent, never proof of Scheduler state or permission to re-arm. Owns nightly retired-bot monitoring and the generated task table; update with registrar and status classification changes. |
| `locations.json` | Durable location registry | Hand-authored location, station, settlement, and source-plan facts. Volatile market-event fields are not stored here. |
| `location_market_events.json` | Generated snapshot | Current Gamma API active-event metadata by location; stale after 7 days. |
| `candidate_markets.json` | Inactive candidate registry | New-city model lane candidate `MarketSpec` rows with their METAR label and print-cutoff rules ([new-city model lane](NEW_CITY_MODEL_LANE.md)). Never the default registry; read only by workstation research modules or under an explicit `WEATHER_MARKET_REGISTRY` override that live paths refuse. Activation is a reviewed `MarketSpec` change. |
| `markets.json` | Deprecated compatibility shell | Empty external override file retained for `weather.market.market_registry`; built-in `MarketSpec` definitions remain authoritative. |
| `model_variant_registry.json` | Hand-authored registry | Validate before promotion; active promoted artifacts must not point at ignored `data/` paths. |
| `supplemental_stations.json` | Hand-authored registry | Review when station provenance changes. |
| `venue_rule_stations.json` | Hand-authored registry | Dated per-market station overrides for venue-rule labels ([spec](venue-rule-labels.md)). Add a dated entry when the venue's station changes; never rewrite an earlier entry. |
| `no_market_extra_locations.json` | Local shadow registry | Active entries must be backfilled before training eligibility; evidence-free diagnostic entries are retained under `archived_locations`. |
| `storage_pressure.json` | Operator activation policy | **Activated `false` by the owner on 2026-09-19 (item 325).** `capture.write_order_books_long_csv=true` restores the long-CSV projection. Change it only in an operator-approved quiet window after the production dry-run; missing or invalid policy fails safe to writing the projection. |
| `international_live_execution_host.json` | Hand-authored execution-role registry | Binds one active portable Windows installation and token principal per production tip, separately identifies the dedicated capture host, and is `UNASSIGNED` until a reviewed relocation assigns both public IDs. |
| `frozen_bindings.json` | Append-only frozen-binding registry | One hold per bound rule (R14, master 2026-11-01). `records`, `record_globs` and `frozen_prefixes` are frozen permanently (a new file matching a glob may be added); `code` and the files listed by `release_binding` are frozen while the hold is active, which is while its `release_record` is absent; once present, the `release_record` is never modified or removed. `s1_edit` names the only permitted change of code pins, the S0-to-S1 edit of B-1 Clarification 3 §5: one head changes exactly the constant line in every `s1_edit` file, all to the same 64-hex value, nothing else in those files; besides them the head may add at most one new file, matching `s1_companion_glob` (B-1: `docs/research/**/b1-clarification-7-*.md`), and touch no other path (master's strict ruling, 2026-11-01). The `release_record` carries `key: value` lines: `rule_sha256` (equal to `record_rule_sha256`, B's rule sha), `receipt_path` (the committed receipt's repo path, made non-text in the same head by a `.gitattributes` line `<path> -text` or `<path> binary` with no later line setting text again), `receipt_sha256` (over that file's bytes exactly as written) and `decision_log_row`; or `b_abandonment` with a `decision_log_row` whose DECISION_LOG row names an owner abandonment (`release_record_policy`). Enforced by `tests/operations/test_frozen_bindings.py` in every suite and by `scripts/ops/frozen_binding_guard.ps1` (`Test-FrozenBindingHead`, reading the registry from the merge base) on the docs light path, the night sequencers and before a manual quiet-window merge. Only pure additions are allowed: append a hold, a record, a glob or a prefix; never edit or remove one. **PT-1 and R14 (master ruling R21 2026-11-01, follow-up C11, recorded 2026-11-06):** PT-1 with C-PT is NOT RUNNABLE (R21), so it never binds and never appends a hold. Its terminal record is the R21 receipt `docs/research/pt1-not-runnable-2026-11-03/receipt.md` (raw sha256 `8c45c8d99dabf1e38b21ad3ebd6e1b015a723b54054dd73d72e2373686cf7c35`; erratum 1 `c29eee7a…`). Wherever R14 makes the after-B list (fixes 10/11) wait for "PT-1's record", that receipt is the record, so fixes 10/11 wait only for B's release record. A successor appends its own hold: any later candidate that binds these release files does so in its own binding commit, under its own prereg. The `book_coverage` PT-1 label in the B-bound `src/weather/calibration/mg2_input_export.py` (hold B-1 `warn`, `frozen_bindings.json`:51-53; label at :49, :506-507, :611, :631, :657) stays UNCHANGED: it emits counts only and sets no PT-1 dependency, so it is vestigial under R21; any edit waits for B's release record and its own review. |
| `capture_families.json` | Hand-authored capture-family registry | Per-city event-slug prefixes, exclusions and bounds for passive capture families recorded by `weather.market.maker_evidence_capture --family <id>` in `data/maker_evidence_families/<id>`. Change a family only with the desk-study or owner decision that admits or excludes its cities; see [passive maker evidence capture](passive-maker-evidence-capture.md#capture-families). Its `platform` block (roll closures read by `roll_verdict.ps1` and `staleness_sweep.ps1`, evidence-family and storage rows) is owned by the [data layer v2 platform contract](DATA_LAYER_V2_CONTRACT.md). |

Generate the current inventory:

`config/local/` is ignored owner-local configuration, never part of the tracked
inventory. `local/wallet_reader_client.json` holds the LAN URL and reader bearer
token under the [wallet-reader runbook](wallet-reader.md); never commit or print it.
`examples/portfolio_campaigns.json` is a hand-authored structural template owned by
`maker_core.contracts.portfolio`; update it when the campaign contract changes.
The production agent authors `local/portfolio_campaigns.json` from it using the
owner's actual account and capital records; see [portfolio ledger](portfolio-ledger.md).

```powershell
python -m weather.operations.config_inventory --out data\backtest\config_inventory.json --report data\backtest\config_inventory_report.md
```

Refresh generated market-event metadata:

```powershell
python -m weather.operations.location_config_refresh --locations config\locations.json --event-metadata config\location_market_events.json
```

On the production host, `scripts/ops/refresh_location_config.ps1` follows that
refresh with an independent live target-date validation and reports task
success only when its receipt is readable, dated today, and `PASS`. Keep the
validation after the refresh: the 07:05 paper-maker launch precedes the 09:30
daily chain that otherwise produces this gate.

Event and location counts are volatile. Read the generated JSON or run the
inventory command for current values rather than copying them into prose.

## Update this file when

Update when a checked-in config file is added, removed, reclassified, changes
owner, or changes generation/freshness policy. The agent-doc audit fails when a
checked-in `config/*.json` file is missing from the table above.
