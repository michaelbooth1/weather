# 110b — weather maker plugin Phase 1 handback

**PASS for offline fixture implementation; real-input dry run pending the production agent's bounded export. No live or edge claim.**

Executed the handoff at `origin/master:docs/roadmap/workstation-handoff-2026-09-110b-weather-maker-plugin-phase1.md`
and the [informed-maker design](../operations/informed-maker-design-2026-09-25.md).
Open-question IDs: none assigned by the handoff.

## Branch and freeze

- Branch: `codex/weather-maker-plugin-20260925`.
- Parent: `origin/codex/maker-core-phase0-20260925`, `0b2224d377b0dfcaee8d223efe35182c460d5f16`.
- Tested implementation tip: `1448d45763e61cf4ee9f35c9b0bb92c4b25cddd0`.
- Pre-registration freeze: `08860d39fb1d702678b20793118a0ed22660b305`, before implementation or any real-data read.
- [Frozen pre-registration](../research/t1-fair-value-preregistration-2026-09-25.md).
- Isolated worktree: `scratch/w/weather-maker-plugin-110b` under the existing repository. The pre-existing main-worktree
  `.env.example` modification was preserved and not read or staged.
- Subsequent report/index commits contain documentation only. Resolve the final pushed tip with
  `git ls-remote --exit-code origin refs/heads/codex/weather-maker-plugin-20260925`; compare to local `git rev-parse HEAD`.

## Module map

| Module under `src/weather/market/maker_plugin/` | Contract and behavior |
| --- | --- |
| `universe.py` | `WeatherUniverse`: built-in markets, local T+0..T+2 slugs, exact YES/NO identities; captured bands and both-token book rules; event neg-risk group; native units |
| `fair_value.py` | `WeatherFairValue`: NBP CDF integration and event renormalization, fixed-spread PIT lead-one fallback, captured T+0 marginal; expiry and `Unavailable` |
| `nbp.py` | Vendor of parser-v2 maximum slot selection from `abd648c7c`; issue/capture/hash checks and complete native-percentile extraction |
| `clock.py` | `WeatherInformationClock`: station minute table from `d059cc78`, NBP cycles and actual fetch detection, NWP +210 minutes, printed-high and determined-band pull events |
| `settlement.py` | `WeatherSettlement`: PIT revision chains, label/revision/change hashes, exact identity and unit, reconciled `match`; otherwise `Pending` |
| `exposure.py` | `WeatherExposure`: factors from the canonical pure `mm_risk` region map |
| `inputs.py`, `__init__.py` | Detached captured records, timestamp normalization, native integer bands, hashing, plugin identity |

Only `maker_core.contracts` is imported from the core. No provider, network, file or environment reads are performed by
the adapters. Existing registry and risk tables are reused; capture modules and the unmerged parser/clock branches are
not imported. No core contract changes were needed.

## Captured shapes and discoveries

All test values are invented, using 2030 dates. See the [fixture provenance](../../tests/fixtures/maker_plugin/README.md)
and [tests](../../tests/market/test_maker_plugin.py). Factories emit minimal field projections of the actual writers:

| Input | Writer shape used |
| --- | --- |
| Discovery and books | 88a `captured_at_utc`, `http_status`, `body_stored`, `body_utf8`, response/stored hashes; discovery `selection_projection`; both-token book `tick_size` / `min_order_size` |
| NBP | `nbp_raw_payload`: station/target/fetched_at/payload_hash/text; fixed six-character row codes and pipe-separated FHR/TXN pairs |
| T+0 | `snapshots_long.csv` `model_probability`, `snapshot_id`, `condition_id`, native `bin_value_c` / `bin_value_hi_c`, `bin_kind` (`eq`, `lte`, `gte`) |
| Stage and release | Matching explanation JSON `explanations.probability_calibration_context.afternoon_residual_centering`; matching source rows' verified release ID and manifest hash |
| Fallback | `forecast_archive` daily_high `forecast_high_c`, target/event, provider issue/update time and capture time; legacy _c remains native-unit |
| Observation | `trigger_record` reason/source, observed_at, current_captured_at_utc, values/buckets, market/event/target/unit |
| Settlement | `settlement_ledger_v2` revision rows with recorded_at_utc, label hash, revision identity/supersession, revision_changes, reconciliation_status, bucket and winning-band metadata |

The served probability is not a top-level model estimate or a recomputation: it is the captured long-row
`model_probability`. Stage context is in the explanation sidecar, and release lineage is in source rows. The adapter
exposes `afternoon_residual_centering` plus the context hash in `model_id` and binds it in `inputs_hash`.

88a discovery projects away band boundaries and does not retain tick/minimum order size. The universe therefore requires
captured long-row band metadata and both-token books. A reward minimum is not substituted for the order minimum.
Supplying only 88a discovery produces an explicit refusal, not fabricated descriptors.

## Fixed choices and limitations

The pre-registration freezes linear CDF tails, half-degree band boundaries, complete-partition validation,
`sqrt(p*(1-p))*(age_hours/24+0.25)`, and next-cycle availability with a one-hour engineering publication allowance.
Fallback spread is 2 C / 3.6 F, explicitly a zero-fit engineering prior rather than an empirical climatology estimate.
Neither constant was selected from real data. Exact zero/one probabilities cannot carry positive stdev under the specified
formula; they return `Unavailable` under contracts v0.1 instead of receiving an undocumented epsilon.

NBP v2 only qualifies its mainland station map. Toronto needs admissible lead-one fallback; T+2 NBP coverage remains
unverified. Older complete target maxima may be used within their validity, but corrupted or ambiguous evidence never
silently becomes fallback. Repeated identical forecast issues remain usable; conflicting values at one issue refuse.

The station-minute table describes routine report times, not publication guarantees. Only a captured WU printed high
can create a hard `decided` event here; supporting METAR data is not promoted to settlement authority. Settlement requires
recorded venue reconciliation and matching labels, preserving the WRH-source caveat. Legacy unversioned or incomplete
ledger chains remain pending. Inline UTF-8 bodies are supported; sharded/compressed bodies must first be reconstructed
and hash-verified by the separate export/loader owner.

## Verification

- **967 passed**: plugin fixtures, existing Phase 0 core tests, import architecture ratchet, and documentation audit tests.
- Focused `compileall` passed for the plugin, test module and fixture oracle.
- `git diff --check` passed.
- Conformance covers NBP lead one/two, native F/C fallback, and served T+0. It checks expiry, missing inputs, repeated PIT
  queries after future inputs arrive, and market-price contamination. Additional tests vary actual captured market-price
  fields, midnight horizons, all registered station minutes, slot ambiguity, duplicate issues, malformed hashes, source
  units, band mass, and settlement revisions. The ledger fixture also passes the canonical ledger history verifier.
- Parser-v2 parity is tested against the retained source selector on synthetic layouts across stations, cycles,
  T+1/T+2 and DST dates. No real bulletin fixture was read.
- Initial combined validation found an absent scratch parent and unstaged-file ratchet failures; these were corrected.
  The sandbox principal could not acquire workstation admission; the same unchanged wrapper admitted the assigned user.
  `weather_heavy` does not allow the docs-audit CLI; the existing `test_agent_docs_audit_passes_repository_contracts`
  exercises the same `audit_repo()` through the supported pytest wrapper. No wrapper or gate was changed.
- Full repository pytest was not run; focused coverage includes the affected contract and architecture owners.

No scored dates, market clusters, market-days, fitted models, Brier results or intervals were produced. The frozen future
evaluation calls for separate lead/source tables, paired Brier versus 88a mids, reliability bins, crossed date x market
90% intervals, and `UNDERPOWERED` below ten clusters in either dimension, once after the panel closes.

### Reproduction on the assigned workstation

From this topic checkout, using the existing main-checkout interpreter (no new environment). This is the documented
interactive wrapper form; automated launchers should expand these into the literal form in `docs/development.md`.

```powershell
$repo = (Get-Location).Path
$main = Split-Path (git rev-parse --path-format=absolute --git-common-dir)
$python = Join-Path $main 'venv\Scripts\python.exe'
New-Item -ItemType Directory -Force (Join-Path $repo 'scratch') | Out-Null
$argsJson = ConvertTo-Json -Compress -InputObject @('-m','pytest','tests/market/test_maker_plugin.py','tests/operations/test_import_architecture.py','tests/maker_core','tests/operations/test_agent_docs_audit.py','-q','--basetemp','scratch/pytest-maker-plugin-110b')
$encoded = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($argsJson))
& "$repo\scripts\ops\workstation_heavy.ps1" -Kind pytest -PythonPath $python -ArgumentsBase64 $encoded -RepoRoot $repo
$argsJson = ConvertTo-Json -Compress -InputObject @('-m','compileall','-q','src/weather/market/maker_plugin','tests/market/test_maker_plugin.py','tests/fixtures/maker_plugin')
$encoded = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($argsJson))
& "$repo\scripts\ops\workstation_heavy.ps1" -Kind compileall -PythonPath $python -ArgumentsBase64 $encoded -RepoRoot $repo
```

### Per-file adoption verdict

No production closures were accessed. An actual per-file closure verdict is **UNDECIDABLE on this workstation**, not a
hand-derived claim of roll-freedom. Production must run `scripts\ops\roll_verdict.ps1 -Branch <fetched-topic-ref>` before
any adoption. No schema registry or existing loop implementation was edited.

| Changed file | Closure disposition |
| --- | --- |
| `src/weather/market/maker_plugin/__init__.py` | UNDECIDABLE: no retained production closure supplied |
| `src/weather/market/maker_plugin/inputs.py` | UNDECIDABLE: same |
| `src/weather/market/maker_plugin/universe.py` | UNDECIDABLE: same |
| `src/weather/market/maker_plugin/nbp.py` | UNDECIDABLE: same |
| `src/weather/market/maker_plugin/fair_value.py` | UNDECIDABLE: same |
| `src/weather/market/maker_plugin/clock.py` | UNDECIDABLE: same |
| `src/weather/market/maker_plugin/settlement.py` | UNDECIDABLE: same |
| `src/weather/market/maker_plugin/exposure.py` | UNDECIDABLE: same |
| `tests/market/test_maker_plugin.py` | UNDECIDABLE: same; offline test only |
| `tests/fixtures/maker_plugin/v2_slot_oracle.py` | UNDECIDABLE: same; offline oracle only |
| `tests/fixtures/maker_plugin/README.md` | Markdown, roll-free by standing policy |
| `docs/operations/package-boundaries.md` | Documentation, roll-free by standing policy |
| `docs/research/t1-fair-value-preregistration-2026-09-25.md` | Documentation, roll-free by standing policy |
| This report and generated `docs/roadmap/correspondence-index.md` | Documentation, roll-free by standing policy |

## Handback requirements

Production next supplies a bounded hashed sample containing retained NBP raw payloads with fetch clocks; T+1/T+2 band
identities/boundaries plus both-token books; PIT daily-high fallback rows if available; matching T+0 long/source/explanation
records; observation triggers; and complete reconciled ledger chains. Validate those joins and coverage before any scoring.
If T+1/T+2 captured metadata or trustworthy issue/reconciliation evidence is absent, that is a coverage blocker, not
permission to fetch retrospectively or relax a gate.

**Not done:** no venue calls, credential access, `.env` reads, production or mirror data access/writes, Scheduler actions,
registration, capture restart, merge, model training, scoring, promotion, live trading or runtime adoption. The branch and
report are for review and the subsequently authorized real-sample dry run only.
