# 110m part 4 — dependency, temp and retirement quick wins

**Verdict: PASS; source changes are roll-free by the static evidence below,
pending production's mechanical roll verdict.** Branch
`codex/repo-health-quick-wins-20260926` starts at integration `8180404a0`.
Fixtures and tracked repository text only; no production data, credentials,
environment files, local exclude/settings files, Scheduler or venue calls.

Both pin files now declare `pyarrow==24.0.0` and directly imported
`joblib==1.5.3`. No environment installation was performed. The bounded suite
puts pytest's basetemp and `TEMP`/`TMP` in sibling directories under the chunk
cleanup root: pytest initialization cannot erase the active tempfile directory.
The parent environment is restored in `finally`, including admission failures.
The wrapper's admission, deadlines, Job ownership and inventory checks are unchanged.
Canonical wording and the hook now say the full suite runs in chunks of at most
25 files; the default chunk size remains 20.

The ten exact `**/.claude/` patterns supplied by the owner in this session, plus
`.ruff_cache/`, are tracked in `.gitignore`. A regression test asserts every
pattern, including the nested-worktree prefixes. No local ignore file was read.

## Deletion proof and skeptic pass (rule 2.2)

Removed only the unused `operations/runtime_identity.py` facade, the 16 named
retired research stubs and their harness rows, and five `tests/fixtures/smoke/`
files. Current traced evidence rechecks D1-01/02/03 and D7-07:

- (a) Tracked Python AST import scan across src/app/tests/tools: no candidate
  imports. Relative runtime-facade and retired-stub imports were checked separately.
- (b) Qualified module/path and basename search across scripts, operational docs,
  README, CI and tracked Codex files: no shim/stub invocation or smoke-tree reference.
- (c) AST string constants and qualified dynamic module/path searches found no
  candidate reference. The harness's explicit basename inventory was removed with
  the stubs; generic inventory iteration remains tested. Arbitrary external callers
  cannot be established by repository analysis.
- (d) All repository registrars were included; no registration references these
  paths. Host-local Scheduler state was deliberately not inspected.
- (e) Last Git edits are recorded per deleted file below. Bulk `add` commits are
  provenance, not evidence of last runtime use.
- (f) The source facade has no incoming static/dynamic repository edge, and thus
  no path from the capture roots. The defining `weather.runtime_identity` stays.

**Opposing case: old pickles or capture workers need the facade.** It merely
re-exported the defining module, so object `__module__` and pickle identity remain
`weather.runtime_identity`; no importer or scheduled entrypoint uses the facade.
**Opposing case: an item requires the tombstones.** Item 330 W9 explicitly calls
for removing the selected stubs and inventory entries. NYC, Chicago and ten-minute
stubs cited by other items remain. All frozen research/evidence scripts remain.
**Opposing case: smoke filenames occur in runbooks.** `HISTORY_DATA_DESIGN.md`
lines 70–80 describe `data/wunderground/cyyz/`, not `tests/fixtures/smoke/`.
Other `manifest.json` hits are integration/live/research manifests with distinct
paths. No `ghcnh_smoke`, `reanalysis_smoke` or `fixtures/smoke` consumer exists in
the checked execution surfaces. Item 29 describes scratch output, not these files.

## Verification

- Pre-deletion trace and four repo audits: **47 passed (49.33 s)**.
- Final pin, research harness, native bounded-suite/temp, host-hook and four repo
  audits: **105 passed (27.05 s)** through `workstation_heavy.ps1`. The import
  architecture audit includes maker-core boundary checks.
- The initial focused run exposed three stale isolated admission fixtures after
  adding temp helpers; their mocks now isolate admission while the separate native
  test exercises real pytest initialization and environment restoration.

No Scheduler re-registration is part of this change. Production should sync the
pinned environment through its normal approved dependency process and obtain
`roll_verdict.ps1` before landing. Every changed path is classified below.

## Deleted-file provenance

| Deleted file | Last Git edit |
| --- | --- |
| `src/weather/operations/runtime_identity.py` | 249b1905 2026-06-22 add |
| `tools/research/fix_app.py` | e0b26bc4 2026-06-18 add |
| `tools/research/train_all.py` | e0b26bc4 2026-06-18 add |
| `tools/research/train_all2.py` | e0b26bc4 2026-06-18 add |
| `tools/research/audit_band.py` | e0b26bc4 2026-06-18 add |
| `tools/research/audit_lowend.py` | e0b26bc4 2026-06-18 add |
| `tools/research/audit_responsiveness.py` | e0b26bc4 2026-06-18 add |
| `tools/research/audit_toronto.py` | e0b26bc4 2026-06-18 add |
| `tools/research/check_chicago_history.py` | d50ca6fe 2026-06-25 add |
| `tools/research/full_audit.py` | e0b26bc4 2026-06-18 add |
| `tools/research/model_market_disagreement_analysis.py` | aea4919c 2026-07-01 add |
| `tools/research/model_market_disagreement_audit.py` | aea4919c 2026-07-01 add |
| `tools/research/run_live_model.py` | e0b26bc4 2026-06-18 add |
| `tools/research/retired_analogs_live.py` | 483b17ba 2026-06-22 add |
| `tools/research/retired_continuation.py` | 483b17ba 2026-06-22 add |
| `tools/research/retired_feature_model_live.py` | 483b17ba 2026-06-22 add |
| `tools/research/retired_freshness.py` | 483b17ba 2026-06-22 add |
| `tests/fixtures/smoke/ghcnh_smoke/station.json` | fd728d4a 2026-06-13 add |
| `tests/fixtures/smoke/reanalysis_smoke/daily/daily_summary.csv` | fd728d4a 2026-06-13 add |
| `tests/fixtures/smoke/reanalysis_smoke/hourly/year=2026/month=06/observations.jsonl` | fd728d4a 2026-06-13 add |
| `tests/fixtures/smoke/reanalysis_smoke/manifest.json` | fd728d4a 2026-06-13 add |
| `tests/fixtures/smoke/reanalysis_smoke/raw/year=2026/2026-06-01_2026-06-01.json` | fd728d4a 2026-06-13 add |

## Per-file roll classification

| File | Classification |
| --- | --- |
| `.codex/hooks/pre_tool_use_host_load.py` | Roll-free |
| `.gitignore` | Roll-free |
| `AGENTS.md` | Roll-free |
| `docs/operations/HOST_LOAD_POLICY.md` | Roll-free |
| `docs/operations/OPERATIONS_AGENT_ROLE.md` | Roll-free |
| `docs/roadmap/agent-report-2026-09-110m-part4-repo-health-quick-wins.md` | Roll-free |
| `docs/roadmap/correspondence-index.md` | Roll-free |
| `pyproject.toml` | Roll-free |
| `requirements.txt` | Roll-free |
| `scripts/ops/bounded_worktree_test_suite.ps1` | Roll-free |
| `src/weather/operations/runtime_identity.py` | Roll-free (unused facade; proof above) |
| `tests/fixtures/smoke/ghcnh_smoke/station.json` | Roll-free |
| `tests/fixtures/smoke/reanalysis_smoke/daily/daily_summary.csv` | Roll-free |
| `tests/fixtures/smoke/reanalysis_smoke/hourly/year=2026/month=06/observations.jsonl` | Roll-free |
| `tests/fixtures/smoke/reanalysis_smoke/manifest.json` | Roll-free |
| `tests/fixtures/smoke/reanalysis_smoke/raw/year=2026/2026-06-01_2026-06-01.json` | Roll-free |
| `tests/operations/test_bounded_worktree_test_suite_script.py` | Roll-free |
| `tests/operations/test_codex_host_load_hook.py` | Roll-free |
| `tests/operations/test_dependency_pins.py` | Roll-free |
| `tools/research/audit_band.py` | Roll-free |
| `tools/research/audit_lowend.py` | Roll-free |
| `tools/research/audit_responsiveness.py` | Roll-free |
| `tools/research/audit_toronto.py` | Roll-free |
| `tools/research/check_chicago_history.py` | Roll-free |
| `tools/research/fix_app.py` | Roll-free |
| `tools/research/full_audit.py` | Roll-free |
| `tools/research/model_market_disagreement_analysis.py` | Roll-free |
| `tools/research/model_market_disagreement_audit.py` | Roll-free |
| `tools/research/research_harness.py` | Roll-free |
| `tools/research/retired_analogs_live.py` | Roll-free |
| `tools/research/retired_continuation.py` | Roll-free |
| `tools/research/retired_feature_model_live.py` | Roll-free |
| `tools/research/retired_freshness.py` | Roll-free |
| `tools/research/run_live_model.py` | Roll-free |
| `tools/research/train_all.py` | Roll-free |
| `tools/research/train_all2.py` | Roll-free |
