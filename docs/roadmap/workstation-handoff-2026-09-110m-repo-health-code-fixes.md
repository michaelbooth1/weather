# Workstation handoff 2026-09-110m — repo-health code fixes and regrowth ratchets

Written 2026-09-26 by the production agent from the [repo-health audit](audits/repo-health-audit-2026-09-26/README.md)
(dimension files under `audits/repo-health-audit-2026-09-26/dimensions/`). Base: `origin/master` after the 2026-09-27
quiet-window landing (or `origin/codex/integration-91a-110f-20260926` until then). One branch per part; state roll-free or
roll-sensitive per file.

## Part 1 — signed band parsing in capture (`codex/signed-band-capture-20260926`, roll-sensitive, priority)

`market_microstructure_capture.label_bin_metadata` (~142-166) and `observation_trigger.band_key` (~1361-1386) parse band
labels with unsigned `\d+` (D3-01/02); `band_key` also treats a numeric 0 as missing. Route both through
`weather.units.parse_temperature_band` (the 95b parser), keeping output field names and types unchanged. Tests: negative
labels (`-2°C or below`, `-1°C`, `-3 to -2`), zero, Fahrenheit, open-ended bands, and a golden row per existing label shape
so no stored-tape key changes for non-negative labels. Report whether any stored CLOB token row could already carry a wrong
sign (fixture reasoning only; production checks the data).

## Part 2 — point-in-time contract split (`codex/pit-contract-split-20260926`, roll-sensitive)

Give `point_in_time_contract` the two hash parameters `residual_distribution_release` needs, switch that import off
`reporting.point_in_time_evaluation`, and remove the 12 diverged duplicates by making the reporting module import the
contract versions (D3-05). Prove behavior parity with the existing release/serving tests plus a differential test on the
12 functions. Report the lazy-import closure before and after.

## Part 3 — decouple live code from paper-maker helpers (`codex/paper-maker-decouple-20260926`)

Move `utc_now`, `maybe_float`, the pilot budget cap and `REMEDIATION_RULES` (and anything else live/pilot code imports from
`mm_policy` / `market_making_*`) to neutral owners (D2-04); consolidate the 32 `datetime`-returning `utc_now` copies into one
helper (not the 15 string-returning ones) (D3). No behavior change.

## Part 4 — roll-free fixes and deletes (`codex/repo-health-quick-wins-20260926`)

- Pin `pyarrow==24.0.0` in both pin files; declare `joblib` explicitly if imported directly (D8).
- `bounded_worktree_test_suite.ps1`: set `TEMP`/`TMP` inside each chunk's basetemp (D7).
- Wording: "25-file bounded suite" → it runs every tracked test in chunks (AGENTS.md, HOST_LOAD_POLICY, OPERATIONS_AGENT_ROLE,
  and `test_codex_host_load_hook.py` pinned text) (D7). Stay within the always-loaded line budgets.
- Deletes that survived the skeptic pass: `src/weather/operations/runtime_identity.py`, the 16 retired `tools/research` stubs
  and their `research_harness.py` rows, `tests/fixtures/smoke/` (D1-01/02/03, D7). Re-verify each with the rule 2.2 checks.
- Move harness ignore paths from `.git/info/exclude` into `.gitignore` (list them from D8; do not read local secrets).

## Part 5 — regrowth ratchets (`codex/repo-health-ratchets-20260926`, tests only where possible)

Per-module `max_lines` cap with shrink-only allow-list, extended to `tests/` and `maker_core`; orphan-module test with a
shrink-only allow-list; retired-symbol count that may only fall; no new `_c` names without an allow-list entry; no unsigned
band regex outside `weather.units`; tracked-file size budget (>1 MiB allow-listed; roadmap data >250 KB carries a mission id);
undeclared-import test; every report JSON read by daily_refresh / promotion / scoreboard has a producer listed in a
scheduled path or an explicit allow-list (seed it with the seven D1-09 producers pending the owner decision).

## Boundaries and deliverables

Fixtures only; no production data, credentials or venue calls. Include the repo-wide audits and maker-core boundary tests in
every focused run. Push and draft PRs are authorized. Reports `docs/roadmap/agent-report-2026-09-110m-<part>.md`, verdict
first, roll classification per file.
