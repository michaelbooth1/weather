# International paper-harvest independent review

**Verdict: PASS_REPAIRED.** The source mechanism was the claimed single-process,
default-off International paper companion, but adversarial review reproduced
defects in disabled-mode inertness, early live-mode refusal, platform binding,
restart publication, evidence identity, and settlement countability. The scoped
repair closes those defects without changing the normal model-policy lane. All
review-owned tests pass. The complete repository suite has four reproducible
pre-existing Windows temp-path case failures, reproduced unchanged at the exact
source tip.

## Exact identity and isolation

- Mission SHA-256:
  `48f5a88baba22109700cf68782019ab2251d66526ff81d8f837301055a5d2a7c`.
- Dependency tip:
  `f964b9463dd850d56b10658ade14d1ecb19aec0b`.
- Source branch:
  `codex/workstation-international-paper-harvest-2026-09-94a`.
- Source tip/tree:
  `2ae55453133b7e8108132d45555dbd8a316d3914` /
  `497b47365b7fc9acda06fbb382a5012e67c9dcca`.
- Source implementation tip/tree:
  `d65144ec75be546db8aee254c8e9bbe02fad4a13` /
  `f96bcf08acddc53d89e7e0a38c96ba89387f8ca6`.
- Independent-review branch:
  `codex/workstation-international-paper-harvest-independent-review-2026-09-97a`.
- Final reviewed implementation tip/tree:
  `5d4406a8a34728645bbf8ac88982e6830a176b34` /
  `51953ba333a72ececd8a170863f0ab56359eef1e`.
- The report/receipt carrier is a separate descendant commit. Its exact Git
  identity and bundle SHA-256 are recorded in the external verified handoff;
  a commit cannot embed its own commit or tree hash in its tracked contents.

The dependency was an ancestor of the source, the source worktree was clean,
the review branch and worktree were absent, and public PR/CI identities matched
before the review branch was created. PR #11 was an open draft at the exact
dependency head; PR #12 was an open draft at the exact source head with run
`33708358328` complete and successful. The source worktree remains at its exact
tip and tree. The root checkout's unrelated `t87a-focused-20260902a/` remains
untracked and untouched.

## Mechanism verdict

The stacked implementation uses the existing daily-roll process. Each enabled
tick passes the token, book, source-status, and frozen economics objects already
loaded by the normal model loop into the companion. The review found no second
worker, provider read, exchange read, or large-tape reread. The companion stays
disabled by default, writes only to its isolated directory when enabled, and
feeds the existing strict public-counterfactual scorer. Normal model-policy
rows, promotion gates, live gates, release bindings, and model artifacts are
unchanged.

The source did not satisfy every safety premise, so `PASS_REVIEWED` was not
available. Each repair below corresponds to a reproduced failure and stays
inside the source PR's files and focused owner tests.

## Falsifiers and red-to-green evidence

| Falsifier | Source result | Final result |
| --- | --- | --- |
| Disabled/default mode leaves normal artifacts byte-for-byte shaped as before | Failed: the normal run payload always gained `market_harvest_companion: null` | Companion key is omitted unless folders exist; no companion state, files, rows, or extra reads occur |
| `live-pilot` rejects before write-capable construction | Failed: daily-roll Python entry points could construct/launch the child and publish status before child-level refusal | Runner, daily-roll build/start/ensure, launcher registrar, and supervisor registrar refuse before construction or status publication |
| International-only identity | Failed: explicit `polymarket_us` economics identity was accepted and relabelled global | Recursive input, config, tape, and scoring validation rejects any explicit non-International or US identity |
| Corrupt checkpoint fails closed | Failed: corrupt state was silently interpreted as empty | Corrupt state, pending transaction, or summary data raises before publication |
| Crash/restart cannot duplicate or partially publish a tick | Failed: a crash after append and before state commit duplicated rows | Atomic pending-tick outbox records phase completion; recovery deduplicates and repairs only unfinished surfaces, commits state last, then removes the outbox |
| Restart identity stays bounded | Source evicted old hashes, allowing a sufficiently old tick to replay | The 2,048-entry hard cap refuses a new tick rather than evicting deduplication history |
| Lifecycle evidence binds the exact inputs | Failed: lifecycle rows omitted exact token/book/source/economics binding and tick identity | Every row has deterministic tick/row IDs and exact parent input bindings |
| Public execution binds event, token, and condition | Failed: right-token/wrong-condition trade rows could count | Condition and token/event bindings are checked before any public-counterfactual execution can count |
| Incomplete/wrong-unit/wrong-date settlement fails closed | Failed: any local settlement value could make fills countable | Countability requires promotion-countable native-unit settlement with exact target, event/market, and numeric bucket binding |
| Public evidence cannot imply account economics | Failed: generic countable-market-day output could conflate public evidence with authenticated economics | Public-counterfactual and authenticated-account counts are separate; authenticated count, authenticated fill, realized P&L, and all reward/release/promotion/serving flags remain zero/false |
| File and row paths stay contained | Insufficient validation | Selected folders, output rows, run config, quote identity, and source paths are validated before scoring/publication |
| Single-read/object reuse premise | Passed | Focused call-count controls still prove one token/book/source/economics load per normal tick |
| Schema registration is additive-only | Passed | The cumulative schema diff adds exactly one `SchemaSpec`; no existing registration changes |

The initial existing narrow suite passed (`7 passed, 91 deselected, 4 subtests
passed`), demonstrating that it did not cover the load-bearing cases above.
New adversarial tests then reproduced 13 real failures: 12 in the first red run
and the condition-ID mismatch in a separate red control. The final focused
owner/adversarial suite passed `113 tests and 19 subtests in 6.03s`.

## Repair behavior and bounds

The repair introduces an atomic `pending_tick.json` transaction. Each append is
flushed and synced; the pending record is updated after each completed surface;
recovery scans and atomically reconstructs only a surface whose completion was
not durably recorded. The bounded state is committed after all outputs, and the
pending record is removed last. Deterministic `companion_tick_id` and
`companion_row_id` values make recovery idempotent across crashes before state,
after lifecycle append, and during a partial append.

Processed identity history remains capped at 2,048 SHA-256 tick IDs. At the cap,
the companion refuses a new tick. It never evicts an identity that would permit
an old tick to duplicate. Normal operation appends without rescanning complete
files, so per-tick work remains proportional to the current tick plus bounded
state rather than accumulated history. The source report's current-policy daily
row estimates remain conservative; recovery may scan one unfinished surface,
but routine publication does not introduce quadratic I/O.

All companion input and output surfaces now bind run, parent run, date, event,
condition, token, capture identity/time, source hashes, economics snapshot/hash/
basis/platform, policy hash, TTL, schema, evidence class, and deterministic tick
identity. Settlement clears settlement/P&L fields when the required native,
promotion-countable, exact-market settlement is absent.

## Complete changed-path inventory and expected roll sensitivity

These are every path changed from dependency
`f964b9463dd850d56b10658ade14d1ecb19aec0b` through the handback. “Expected” is
static review evidence only. The production owner must run the canonical
`roll_verdict.ps1` against the published exact branch before integration.

| Path | Expected capture-roll sensitivity |
| --- | --- |
| `README.md` | Roll-free by the durable Markdown contract |
| `docs/operations/OPERATIONS_DESIGN.md` | Roll-free by the durable `docs/` contract |
| `docs/roadmap/agent-report-2026-09-03-workstation-international-paper-harvest.md` | Roll-free by the durable `docs/` contract |
| `docs/roadmap/agent-report-2026-09-06-workstation-international-paper-harvest-independent-review.md` | Roll-free by the durable `docs/` contract |
| `docs/roadmap/workstation-handback-2026-09-06-international-paper-harvest-independent-review.json` | Roll-free by the durable `docs/` contract |
| `scripts/ops/market_making_daily_roll_task.ps1` | Roll-free by the durable `.ps1` contract |
| `scripts/ops/register_market_making_daily_roll.ps1` | Roll-free by the durable `.ps1` contract |
| `scripts/ops/register_market_making_daily_roll_supervisor.ps1` | Roll-free by the durable `.ps1` contract |
| `src/weather/market/market_harvest_companion.py` | Expected outside the four capture-worker closures; canonical production verdict required |
| `src/weather/market/market_making_run.py` | Expected outside the four capture-worker closures; canonical production verdict required |
| `src/weather/market/market_making_run_support.py` | Expected outside the four capture-worker closures; canonical production verdict required |
| `src/weather/operations/daily_refresh_trading_steps.py` | Expected outside the four capture-worker closures; canonical production verdict required |
| `src/weather/operations/market_making_daily_roll.py` | Expected outside the four capture-worker closures; canonical production verdict required |
| `src/weather/schema_registry_recent_data.py` | Roll-sensitive in all four production capture closures; cumulative change is additive-only |
| `tests/market/test_market_harvest_companion.py` | Roll-free test path |
| `tests/market/test_market_making_run.py` | Roll-free test path |
| `tests/operations/test_host_task_wrappers.py` | Roll-free test path |
| `tests/operations/test_market_making_daily_roll.py` | Roll-free test path |

The scoped repair relative to the source tip changes eleven paths: `README.md`,
`docs/operations/OPERATIONS_DESIGN.md`, both registrar scripts,
`market_harvest_companion.py`, `market_making_run.py`,
`daily_refresh_trading_steps.py`, `market_making_daily_roll.py`, and the three
focused test files. The two handback files are carried only by the separate
report/receipt commit.

## Verification and controls

All pytest and compileall commands ran serially through the checkout-owned
`scripts/ops/workstation_heavy.ps1`, using the canonical project interpreter,
the `workstation_offline_v1` profile, host-global mutex, and kill-on-close Job.

| Check | Result |
| --- | --- |
| Existing narrow source tests | `7 passed, 91 deselected, 4 subtests passed in 5.58s` |
| Adversarial red controls | 13 demonstrated source failures |
| Directly affected market/scorer/daily-roll/wrapper/schema/reporting files | `354 passed, 36 subtests passed in 58.34s` |
| Final focused owner/adversarial files | `113 passed, 19 subtests passed in 6.03s` |
| Complete repository suite, once, on final implementation | `4252 passed, 18 skipped, 4 failed, 867 subtests passed in 434.19s` |
| Exact four-failure control at untouched source tip | Same four failures in `1.54s` |
| `compileall -q app src tests` | Exit `0` |
| PowerShell AST for task, launcher registrar, supervisor registrar | `PASS` for all three |
| Agent-document audit | `PASS (18 agent files, 830 Markdown files)` |
| Roadmap lint/check | `OK (generated report matches sources)` |
| Cumulative diff and ancestry checks | Finalized after the report/receipt commit and recorded in the external handoff |

The four complete-suite failures are exact temp-directory case mismatches
between `pytest-of-Michael` and `pytest-of-michael` in untouched files:

- `tests/market/test_live_sdk_overlay.py::test_validator_binds_complete_overlay_and_ordered_wheelhouse`
- `tests/operations/test_replay_cache_retention.py::test_plan_selects_only_exact_unreachable_rebuildable_key`
- `tests/reporting/test_point_in_time_preselection_source.py::test_bounded_feature_quality_audit_matches_legacy_fixture`
- `tests/reporting/test_registration_parameters.py::test_verified_release_emits_exact_bindings_paths_and_powershell`

The exact four-test control fails identically at source tip
`2ae55453133b7e8108132d45555dbd8a316d3914`. No second complete suite was run.
The warnings were the existing scikit-learn empty-feature warnings and one
NumPy/netCDF binary-size warning.

## Prohibited actions and handoff

No production host, production status, Scheduler API, scheduled task, data
tree, provider, exchange, credential, account, endpoint execution, model fit,
corpus/outcome, release, promotion, serving, merge, history rewrite, source
branch edit, existing PR mutation, GitHub mutation, push, or old-worktree
cleanup was accessed or performed. The PowerShell registrars were parsed, not
executed. Network use was limited to the mission-authorized credential-free
public identity and CI reads.

The production owner must verify the complete bundle, publish the exact branch,
create a stacked draft PR targeting
`codex/workstation-international-paper-harvest-2026-09-94a`, obtain the canonical
production roll verdict, and monitor exact-head CI. Enabling the companion
still requires the separate reviewed launcher and supervisor registration
actions; this review grants no production adoption or live authority.
