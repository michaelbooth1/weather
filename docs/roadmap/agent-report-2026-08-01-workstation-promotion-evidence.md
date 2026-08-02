# Workstation promotion-evidence report — 2026-08-01

## Handback

Mission `workstation-handoff-2026-08-11a-red-team-the-release-path` is complete on
`codex/workstation-promotion-evidence-2026-08-11a`, based on `origin/master`
`a1421aca999b71def6ef77a3b2aa006cc199029b`. Repository changes are documentation only.

The declared run root was
`C:\Users\Michael\Documents\github\weather\scratch\runs\promotion-evidence-2026-08-11a`.
It contains only the declaration, synthetic filled examples, a validator helper, and JSON/Markdown
transcripts. No `data/`, candidate, release, artifact, pointer, scheduler, capture, mirror, ACL, or
serving state was read or changed. The synthetic release id is
`synthetic-never-a-release-validator-example`; it cannot collide with the nightly release-id format,
and every example is marked non-evidence.

**Result:** both fill-in templates pass the real merged validators after their deliberate fail-closed
sentinels are replaced. One pass, all 26 distinct failure branches, both boundary edges, the
production-release-kind alternative, and seven permissiveness probes were executed directly. The
runbook had two build-critical disagreements with merged code; both are corrected here and in the
runbook. Most importantly, the automated bootstrap in `training_window.ps1` is now the primary path.

## Promotion-decision contract

Template: [`release-promotion-decision.template.json`](../operations/release-promotion-decision.template.json).
The first-release call passes `expected_release_kind="serving_identity_bootstrap"`, so every row below
is required. A missing field is the same as a mismatched field except for the two separately checked
review fields.

| Field | Exact accepted value/type for release #1 | Provenance and timing |
| --- | --- | --- |
| `schema_version` | JSON string `release_promotion_decision_v0.1` | Fixed in advance from the schema registry/validator. |
| `decision` | JSON string `PROMOTE` | Set only for an affirmative promotion decision. |
| `gate_status` | JSON string `PASS` | Human review outcome, after all adopted gates pass. |
| `release_id` | Exact JSON string passed to `promote` | Copy `release_id` from `release_lifecycle_cli verify <release-id>`. Do not infer it from a folder name. |
| `manifest_sha256` | Exact manifest identity returned by verification | Copy `manifest_sha256` from the same verify JSON. This is the canonical manifest self-hash, not `Get-FileHash release_manifest.json`. |
| `candidate_only_build` | JSON boolean `true` | Set only after `nightly_retrain_status.json` shows `candidate_release.activation=NONE`, `candidate_release.active_pointer_unchanged=true`, and `first_inactive_release_bootstrap_finalization.status=PASS`. The validator itself checks only the asserted value. |
| `release_kind` | JSON string `serving_identity_bootstrap` | Required for the one-time research-only first identity selected by `--bootstrap-first-release`. For a later production-capable release it must be absent or `production`. |
| `reviewed` | JSON boolean `true` | Set at review time, never staged as true. |
| `reviewed_by` | Nonblank reviewer identity | Fill at review time. The current validator string-coerces rather than type-checks; the template requires a human-readable JSON string. |
| `reviewed_at_utc` | ISO-8601 timestamp with timezone | Fill after review. `Z` and explicit offsets parse; the validator normalizes for validation but returns/hashes the original string. There is no review-time freshness limit. |

Build-day source command:

```powershell
$verified = python -m weather.operations.release_lifecycle_cli verify <release-id> | ConvertFrom-Json
$verified.status                 # PASS
$verified.release_id             # copy exactly
$verified.manifest_sha256        # copy exactly; canonical manifest identity
```

The decision may be prepared after the immutable build and verification, but its review fields and
the three proof booleans must not be pre-approved. Do not add keys: unknown keys currently pass but
alter the canonical hash stored in the active pointer.

## Market-day-boundary contract

Template: [`release-market-day-boundary.template.json`](../operations/release-market-day-boundary.template.json).
It is intentionally unusable until the operator replaces both identity sentinels, the date/time
sentinels, both `false` values, and both sentinel list entries.

| Field | Exact accepted value/type | Provenance and timing |
| --- | --- | --- |
| `schema_version` | JSON string `release_market_day_boundary_v0.1` | Fixed in advance. |
| `status` | JSON string `PASS` | Promotion-time boundary review outcome. |
| `release_id` | Exact verified release id | Same `release_lifecycle_cli verify` JSON as the decision. |
| `manifest_sha256` | Exact verified manifest identity | Same verify JSON; not a file-byte hash. |
| `effective_target_date` | ISO date string; use `YYYY-MM-DD` | Establish from the operator's market-day schedule at cutover. The validator checks only parseability, not its relationship to the lists. |
| `observed_at_utc` | ISO-8601 timestamp with timezone | Write last, at promotion time, after quiescence/list checks. Compared with the promote process's `datetime.now(timezone.utc)`. |
| `at_market_day_boundary` | JSON boolean `true` | Set only after the market-day check is actually true. |
| `processes_quiesced` | JSON boolean `true` | Set only after snapshot, observation-trigger, maker, and taker release writers are stopped; the CLOB loop is normally stopped with capture. |
| `open_market_days` | Exact empty JSON array `[]` | Promotion-time inventory; any member blocks. |
| `mixed_release_market_days` | Exact empty JSON array `[]` | Promotion-time inventory; any member blocks. |

The default age window is inclusive at both edges: exactly 900 seconds old passes; 900.001 seconds
old blocks. Exactly 60 seconds ahead passes; 60.001 seconds ahead blocks. A naive proof timestamp or
naive injected current clock blocks. The boundary cannot be staged: author it only after quiescence,
then invoke `promote` before 900 seconds elapse.

## Hash and JSON rules

Both returned proof hashes are `SHA-256(json.dumps(object, sort_keys=True,
separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8"))`; no field is omitted.
They are object hashes, not hashes of file bytes. Promotion stores them in the pointer. By contrast,
the release manifest's canonical identity omits its own `manifest_sha256` field. The CLI uses
`strict_json_loads`, so malformed JSON, a non-object top level, unreadable input, and duplicate keys
are rejected before either validator. Those loader errors are additional to the validator matrix.

Current validator gaps, confirmed directly:

- Python equality accepts JSON number `1` for each expected `true`; templates use real booleans.
- `reviewed_by` is string-coerced, so a number passes; the template requires a string.
- neither validator rejects unknown keys; templates contain no extras.
- neither validator validates the lexical shape of `manifest_sha256`; real promotion supplies the
  exact hash from an independently verified release, which makes a non-hash value unable to match.
- `candidate_only_build`, boundary state, and the two empty inventories are operator assertions. The
  validator does not derive them from another artifact. The runbook now names the evidence the
  operator must inspect before asserting them.

## Direct validator transcript

The helper loaded the two checked-in templates, replaced their sentinels with deliberately synthetic
values, and called `validate_promotion_decision` and `validate_market_day_boundary` directly. Clock:
`2026-08-01T16:00:00+00:00`; default maximum age: 900 seconds. Result: 38 cases, 12 PASS and 26
intentional BLOCK. Transcript JSON SHA-256:
`ea79596651cb20d5e1d9be21dd3b18d69414dc3bb5143db4d2efda1c58bfd824`.

### Passing template/edge cases

| Case | Actual result |
| --- | --- |
| Filled first-release decision template | `PASS`; proof hash `5f85616da63b23dd03e65a78b0a3baba073da0bb647c93b2a97c89aca9f52c92`; returned kind `serving_identity_bootstrap` |
| Production-capable decision with `release_kind` absent | `PASS` |
| Filled boundary template, 30 seconds old | `PASS`; proof hash `f2d0bd735ad2377cb42bfd89ac84ccef2ee46133c48ad81afa47d8c434bce5b1` |
| Boundary exactly 60 seconds in the future | `PASS` |
| Boundary exactly 900 seconds old | `PASS` |

### Every distinct failure branch

| Case | Actual merged-validator message |
| --- | --- |
| decision schema | `promotion decision failed closed: schema_version must be 'release_promotion_decision_v0.1'` |
| decision value | `promotion decision failed closed: decision must be 'PROMOTE'` |
| decision gate | `promotion decision failed closed: gate_status must be 'PASS'` |
| decision release | `promotion decision failed closed: release_id must be 'synthetic-never-a-release-validator-example'` |
| decision manifest | `promotion decision failed closed: manifest_sha256 must be 'ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff'` |
| candidate-only assertion | `promotion decision failed closed: candidate_only_build must be True` |
| reviewed assertion | `promotion decision failed closed: reviewed must be True` |
| bootstrap release kind | `promotion decision failed closed: release_kind must be 'serving_identity_bootstrap'` |
| production-capable release kind | `promotion decision failed closed: release_kind must be absent or 'production' for a production-capable release` |
| blank reviewer | `promotion decision failed closed: reviewed_by is required` |
| malformed review time | `promotion decision failed closed: reviewed_at_utc must be an ISO-8601 timestamp` |
| naive review time | `promotion decision failed closed: reviewed_at_utc must include a timezone` |
| boundary schema | `market-day boundary proof failed closed: schema_version must be 'release_market_day_boundary_v0.1'` |
| boundary status | `market-day boundary proof failed closed: status must be 'PASS'` |
| boundary release | `market-day boundary proof failed closed: release_id must be 'synthetic-never-a-release-validator-example'` |
| boundary manifest | `market-day boundary proof failed closed: manifest_sha256 must be 'ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff'` |
| not at boundary | `market-day boundary proof failed closed: at_market_day_boundary must be True` |
| processes live | `market-day boundary proof failed closed: processes_quiesced must be True` |
| open day present | `market-day boundary proof failed closed: open_market_days must be []` |
| mixed day present | `market-day boundary proof failed closed: mixed_release_market_days must be []` |
| malformed effective date | `market-day boundary proof failed closed: effective_target_date must be an ISO date` |
| malformed observed time | `market-day boundary proof failed closed: observed_at_utc must be an ISO-8601 timestamp` |
| naive observed time | `market-day boundary proof failed closed: observed_at_utc must include a timezone` |
| naive current clock | `market-day boundary proof failed closed: current time must include a timezone` |
| 61 seconds ahead | `market-day boundary proof failed closed: observed_at_utc is in the future` |
| 901 seconds old | `market-day boundary proof failed closed: market-day boundary proof is stale (901.0s > 900.0s)` |

Additional probes confirmed that numeric truths, a numeric reviewer, unknown keys, and a non-hex
manifest value when the caller supplies that same expected value are accepted. These are documented
limits, not recommended template forms.

## Cutover checklist

This is an operator checklist, not authority to execute it now. Promotion must occur outside the
12:00–18:00 no-roll interval, with the boundary writers already quiesced.

### 1. Promote and pin the pointer identity

```powershell
python -m weather.operations.release_lifecycle_cli promote <release-id> `
  --decision <reviewed-promotion-decision.json> `
  --market-day-boundary <fresh-market-day-boundary.json> `
  --bootstrap-first-release
$active = python -m weather.operations.release_lifecycle_cli active | ConvertFrom-Json
```

Require promote `status=PROMOTED`, intended `release_id`,
`release_kind=serving_identity_bootstrap`, and `restart_required=true`. Require active `status=PASS`,
the same `release_id`/`manifest_sha256`/`pointer_sha256`, `sequence=1`, and
`production_capable=false` for the deliberately narrow first serving-identity bootstrap.

### 2. Restart every process-sticky binder

`market_making_run.py` and `taker_bot_cli.py` are the only direct callers of
`load_worker_release_binding`. Snapshot serving instead calls
`get_process_active_serving_bundle` through `snapshot_store`/`TorontoHighTempModel`; it is equally
process-sticky and must restart. Observation trigger and CLOB do not use `worker_release_binding`,
but restore them because they were quiesced for the boundary.

```powershell
python -m weather.collection.snapshot_tracker --restart
python -m weather.collection.snapshot_tracker --status

python -m weather.operations.market_making_daily_roll stop
python -m weather.operations.market_making_daily_roll ensure
python -m weather.operations.market_making_daily_roll status

schtasks /change /tn WeatherTakerBotDailyRollSupervisor /disable
$taker = python -m weather.operations.taker_bot_daily_roll status | ConvertFrom-Json
python -c "import json; from pathlib import Path; from weather.operations.taker_bot_daily_roll import DEFAULT_STATUS_PATH, retire_taker_bot_process_tree; s=json.loads(Path(DEFAULT_STATUS_PATH).read_text(encoding='utf-8')); r=retire_taker_bot_process_tree(s['pid'], s['target_date']); print(json.dumps(r, sort_keys=True)); assert r.get('stopped'), r"
python -m weather.operations.taker_bot_daily_roll ensure
schtasks /change /tn WeatherTakerBotDailyRollSupervisor /enable
python -m weather.operations.taker_bot_daily_roll status

python -m weather.market.market_microstructure ensure --market all --interval-seconds 60 --fast-interval-seconds 15
python -m weather.operations.observation_trigger ensure --market all --interval-seconds 60 --stale-after-seconds 180
schtasks /change /tn WeatherSnapshotLoopSupervisor /enable
schtasks /change /tn WeatherClobBookLoopSupervisor /enable
schtasks /change /tn WeatherObservationTriggerSupervisor /enable
```

The taker helper refuses unless the PID is a live Python process whose command line is exactly
`-m weather.market.taker_bot` for the recorded target date, then retires its Windows process tree.
Require its JSON `stopped=true` before `ensure`. The missing canonical taker stop CLI remains a
code/runbook gap; do not replace this check with a generic PID kill.

### 3. Prove release-bound rows

For the first market day whose files are entirely post-cutover, inspect the snapshot
`variant_predictions_long.csv`, maker run `run_config.json` and quote tape, and taker run
`run_config.json` and order tape.

| Evidence | Fields | Worked value |
| --- | --- | --- |
| all three | `release_id`, `release_manifest_sha256`, `release_pointer_sha256` | exactly equal `$active.release_id`, `$active.manifest_sha256`, `$active.pointer_sha256` |
| snapshot rows | `release_identity_status` | `verified_variant_serving_bundle` |
| snapshot rows | `serving_model_binding_status` | `verified_release_base_model` |
| maker/taker config and rows | `release_identity_status` | `verified_variant_serving_bundle` |
| maker/taker config and rows | `base_model_release_bound` | JSON/CSV true |
| every row | unbound/restart/failure/blank/mismatch count | zero |

Forbidden states are `research_unbound_non_countable`, `release_restart_required`,
`release_binding_failed`, `release_unbound_legacy_base_model`, blank identities, or mismatched hashes.
A healthy process status alone is insufficient; only persisted post-cutover rows prove binding.

### 4. Prove the nightly parity unlock

Let the next ordinary automated 01:00 window run; do not manually simulate the gated production
path. Then:

```powershell
python -m weather.operations.nightly_retrain status
$nightly = Get-Content data\backtest\nightly_retrain_status.json -Raw | ConvertFrom-Json
$nightly.captured_input_replay_parity.status
$nightly.promotion.reason
$nightly.steps | Where-Object name -eq captured_input_replay_parity
```

Worked means parity `status=PASS`, promotion reason is not
`captured_input_replay_parity_blocked`, and no matching step has `status=blocked`. A later independent
gate may still make the top-level nightly status non-success; report that separately.

### 5. Prove settlement identity

```powershell
python -m weather.reporting.scorecards.live_variant_settlement_scorecard score `
  --tape <fully-post-cutover-variant_predictions_long.csv> `
  --expected-variants-manifest artifacts\releases\<release-id>\release_manifest.json `
  --json-out <review-output-outside-data>\live_variant_settlement_scorecard.json `
  --report-out <review-output-outside-data>\live_variant_settlement_scorecard.md
$score = Get-Content <review-output-outside-data>\live_variant_settlement_scorecard.json -Raw | ConvertFrom-Json
```

Worked means `coverage.eligible_partition_count > 0`, every
`partitions[].release_identity_sources` is exactly `['explicit']`, every
`variant_release_summaries[].release_id` equals `$active.release_id`, and zero release IDs begin
`legacy-runtime:`. The overall scorecard may still block on scoring/coverage quality; that is not an
identity regression.

### 6. Prove replay-cache classification, without cleanup

```powershell
python -m weather.operations.replay_cache_retention `
  --cache-root <replay-cache-root> `
  --corpus <fresh-pinned-promotion-corpus.json> `
  --registry config\model_variant_registry.json `
  --active-release-pointer artifacts\releases\current_release.json `
  --releases-root artifacts\releases `
  --output-root <review-output-outside-data> `
  --protected-root <production-data-root> `
  --protected-root <mirror-data-root>
$retention = Get-Content <review-output-outside-data>\replay_cache_retention_manifest.json -Raw | ConvertFrom-Json
```

Worked means `reachability.status=COMPLETE`, `serving_rebuild.release_id` and
`serving_rebuild.manifest_sha256` equal the active identity, no blocker begins
`reachability_incomplete:`, and `summary.ambiguity_count=0`. Prefer `status=PASS`; a quota-only block
is a separate storage finding. Do not pass `--apply`; this check authorizes no deletion.

Only after all six steps work may separately reviewed replay-cache reclaim or CLOB tiering be
considered. Both remain parked by operator decision.

## Runbook-versus-code red team

| Finding | Code evidence | Resolution |
| --- | --- | --- |
| **Build-critical:** old §3a used `nightly_retrain` folder mode as a staging-only command. Before release #1, ordinary captured-input parity runs before plan construction and defers all child steps, so prelock never runs. | `nightly_retrain.py:2062-2083`, `2116-2119`, `2281-2312`; standalone parser at `point_in_time_evaluation.py:5420-5444`. | §3a now invokes standalone `prelock-production` and writes the exact staged trio directly. |
| **Build-critical:** old §3b said a staged source should omit replay manifest; its shown command also omitted the receipt. The merged wrapper requires the complete corpus/manifest/replay/receipt quartet and verifies it before work. | `nightly_retrain.py:654-720`, `738-783`, `817-836`; automated quartet at `training_window.ps1:234-273`. | Keep the valid half of the correction—never use July-11 `promotion_corpus.json`—but pass the fresh staged replay manifest and receipt exactly as the automated path does. |
| Automated bootstrap was absent from the original procedure. | `training_window.ps1:152-178` narrow config auto-commit; `186-201` capture stop; `229-275` self-disarming bootstrap; `306-311` unconditional restore. | Made it primary and factored its exact arming checks/log line into §3 step 5. Manual build remains fallback. |
| Old §4a implied all long-running workers bind through `worker_release_binding`. Only maker and taker do; snapshot has a separate process-sticky serving-bundle path. | imports/calls at `market_making_run.py:141-147,1285-1304` and `taker_bot_cli.py:21-26,851-861`; snapshot path at `snapshot_store.py:68-75,207-214` and `toronto_model.py:59-64,107`. | §4a now names snapshot, maker, and taker separately and proves persisted rows. |
| A controlled taker restart has no canonical CLI stop verb, while maker does. | `taker_bot_daily_roll.py:1514-1528` versus `market_making_daily_roll.py:1387-1405`. | Checklist requires supervisor disable plus exact-PID verification/retirement, then `ensure`; no unsafe generic kill command is prescribed. This remains a future code hardening item, not work authorized here. |
| `candidate_only_build=true` is an assertion, not independently bound evidence. | `release_promotion.py:71-82`; inactive build facts at `release_candidate_build.py:286-321` and finalization at `nightly_retrain.py:2638-2648`. | Template defaults false; runbook names the three build/finalization fields required before flipping it. |
| Boundary truth is likewise asserted; the validator checks values, date parse, timezone, and age but does not enumerate processes or derive market-day state. | `release_promotion.py:116-167`. | Template defaults both booleans false and both lists nonempty; operator must establish and record the facts immediately before promotion. |
| Existing §8 said the synthetic rehearsal was still in flight. | Historical state contradicted the accepted merged rehearsal, while real post-preselection evidence is still absent. | §8 now distinguishes completed synthetic work from the still-unrun real candidate path. |

No other command/field disagreement was found in the reviewed release create/verify/promote path.
The runbook's July-11 replay warning, immutable inactive result, pointer rollback target, clean-tree
exclusions, promotion restart requirement, first-release release kind, and replay-retention pointer
dependency all match merged code after the corrections above.

## Verification

- Direct template/validator matrix: 38 cases; 12 PASS, 26 intentional BLOCK.
- JSON templates parse successfully and were the source objects for the passing cases.
- No promotion API, lifecycle mutation, release build, candidate build, or data reader was invoked.
- Documentation links/audit and clean-tree checks are recorded in the branch handback commit.
