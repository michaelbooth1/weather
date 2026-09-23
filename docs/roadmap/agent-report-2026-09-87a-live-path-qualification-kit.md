# Agent report 2026-09-87a — live-path qualification kit

**PASS for the kit's public-function contracts and requirements-only import smoke.
The single full suite had three admission-list failures, all repaired and covered
by a passing focused rerun; there was no second full suite. Production roll
qualification remains UNDECIDABLE. No live/session adoption is authorized.**

## Branch and scope

Branch: `codex/live-path-qualification-20260923`.
Original fetched master: `198f7ccbcd8e80271693462425582097d22b298b`.
Handoff fetched from `origin/codex/reward-test-attended-handoff-20260921`
at `dc0d2949` using the exact named 87a path.

That master did not contain any RE-1 modules. The owner explicitly answered
**"Authorize a base containing RE-1"** in this task. The branch therefore
preserves master ancestry and merges published dependency
`c771cbb427cd2ab3cac1cbee52c84721bb3ac935` at `296f9376`.
The cumulative master diff includes that already-existing RE-1/Stage-2 lineage;
it is not a claim that all inherited changes were authored by this mission.
All eight `src/weather/market/re1_*.py` files are byte-identical to `c771cbb42`.
No session worktree was opened. Main-checkout user state remains unchanged.

Final implementation tip: `e977ec47e0cf4e5bdb391fbee06cce615995e40d`.
The public probe and single full suite ran on clean implementation
`9436ba5ad59216da2b60d15c6d5066281e9e06e7`; final focused verification and
compileall cover the subsequent repairs at `e977ec47`.
The final report-only successor is handed back with its full tip; obtain it with
`git log -1 --format=%H -- docs/roadmap/agent-report-2026-09-87a-live-path-qualification-kit.md`.
There was no master integration, runtime adoption, PR creation or CI run.

## What was built

- `weather.http`: descriptive commit-bound User-Agent, JSON Accept, mandatory
  timeout/size bounds, HTTP/JSON errors with status and a 200-character body
  preview, no redirects or retry. `location_config_refresh` is the sole migrated
  caller; its atomic generation and pagination behavior from the dependency
  merge were preserved.
- Three repo-wide AST ratchets, with explicit file:line HTTP debt and named
  undeclared-import issues. Four existing non-RE-1 PowerShell command vectors
  gained the handoff-required process-local execution-policy arguments.
- `live_contract_probe`: exactly five public reads, no retries, exact URL/method
  allowlist, no credentials, no order modules imported. Frozen public functions
  are compiled unchanged from their original AST definitions in an explicit
  isolated namespace because importing their containing modules would import
  credential/order code. Source hashes are printed. This exercises public
  function paths, not the complete live-module composition. PublicBooks performs
  the book/reward reads; the original RE-1 json reader performs geography/RPC;
  the original official-adapter function validates positions. Unknown imports
  fail closed. A bounded real opener prevents redirects, duplicate reads and
  the adapter's otherwise unbounded positions read. The final revision also
  rejects ambient proxy configuration before every request, including positions.
- Venue fixtures reproduce the confirmed complementary trade: taker YES at
  0.52, maker NO at 0.48, maker quantities 20 and 5.57. Both token aliases pass
  the frozen RE-1 normalizer and retain our 5.57-share fill. Recursive credential
  field checks cover every fixture. The order fixture preserves a retained
  normalized YES BUY placement at 0.49 for 20 shares, LIVE with zero matched
  size. It was selected with a bounded field allowlist from the campaign's
  `session-1/user-stream.jsonl` outside the session worktree; identifiers are
  replaced. This is a real normalized event, not original wire JSON. The trade
  fixtures reconstruct the confirmed 84g REST shape and documented WS alias:
  exact session-1 failing WS bytes were never retained, according to 84g.
- Workstation fresh-venv smoke: fixed offline module admitted through the shared
  lease/kill-on-close wrapper; requirements-only public-PyPI install; one child
  per `mm_*`/`re1_*` import, with network and `.env` access refused during imports;
  checked task-owned venv cleanup. The wrapper and checked-in hook admit the
  same exact smoke module; direct unwrapped execution remains blocked. Lazy
  imports remain covered by the AST audit. Truncated HTTP reads also retain
  typed status/body diagnostics, including when reading an HTTP error body.

## Real public probe

One run on the clean tested implementation, September 23, 2026. Five requests,
exit 0; no retries. Configured LA September 24 80–81 F YES token:
`15432250279049081963827803811324694729539139797228087450179126800337565816732`.
Condition:
`0x11348776f1d311b744028d447635b39f1b9ddac91fcb1e48d5a0ebae501fda59`.
Explicit public address: `0x000000000000000000000000000000000000dEaD` (burn
address, not an owner account). Positions returned an empty list, so real
nonempty-position-row coverage is not claimed. The geoblock payload returned
`blocked: true`; its schema PASS is **not** geographic eligibility or permission
to trade. No IP or full geoblock body was retained.

```json
{"blocked": true, "contract": "geoblock", "http_status": 200, "note": "shape only; not eligibility authority", "status": "PASS"}
{"block_number": 94309240, "contract": "polygon_rpc", "http_status": 200, "status": "PASS"}
{"asks": 53, "bids": 10, "contract": "clob_book", "http_status": 200, "status": "PASS"}
{"condition_id": "0x11348776f1d311b744028d447635b39f1b9ddac91fcb1e48d5a0ebae501fda59", "contract": "condition_rewards", "http_status": 200, "status": "PASS"}
{"contract": "public_positions", "http_status": 200, "row_count": 0, "status": "PASS"}
{"requests": 5, "source_sha256": {"mm_official_adapter": "09f37773923c0d2d97dc036f1c77c331e7d114d283d311c69ed3b841923d7943", "mm_stage2_hold": "4c47014470c9c37562fc10f0994c1794cad40e712a963c9175817b619ae7778a", "mm_stage2_selection": "7e86bb587185fe2b785d2ba7bbc7c0646cbe9e1715fe71c1a0f4aa3866ea3cbb", "re1_owner_checks": "f2f81b3706aac341d37e325f6d70a0409ea183299446749cf269b230b6479b32", "re1_transport": "f86550e355c4c1c93be69e9901bc2381beb90173dbfbb8ad9a30027fa1752754"}}
```

## Ratchet inventories

The exact shrinking lists are owned by
`tests/operations/live_path_allowlist.json`. Counts: **23 urllib sites**, including
Request constructors and injected-opener binding sites; **17 undeclared-import
sites across four distributions**; **13 PowerShell argument vectors, zero
exceptions**. The four missing-policy repairs are in `operating_reference.py`,
`producer_provenance.py` (two), and `taker_bot_daily_roll.py`.

```text
src/weather/market/exchange_economics.py:130
src/weather/market/exchange_economics.py:137
src/weather/market/exchange_economics.py:176
src/weather/market/exchange_economics.py:183
src/weather/market/mm_geographic_eligibility.py:151
src/weather/market/mm_geographic_eligibility.py:161
src/weather/market/mm_live_stage0_scope.py:271
src/weather/market/mm_live_stage0_scope.py:275
src/weather/market/mm_official_adapter.py:342
src/weather/market/mm_official_adapter.py:346
src/weather/market/mm_official_adapter.py:442
src/weather/market/mm_official_adapter.py:446
src/weather/market/mm_official_transport.py:97
src/weather/market/mm_official_transport.py:121
src/weather/market/mm_official_transport.py:150
src/weather/market/mm_official_transport.py:219
src/weather/market/mm_stage2_selection.py:109
src/weather/market/mm_stage2_selection.py:121
src/weather/market/re1_payout_evidence.py:514
src/weather/market/re1_transport.py:57
src/weather/market/re1_transport.py:121
src/weather/market/re1_transport.py:130
src/weather/sources/official_guidance_collection.py:192
```

| Site | Issue |
| --- | --- |
| src/weather/calibration/residual_distribution_v1.py:27:joblib | DEP-1: declare directly instead of relying on scikit-learn |
| src/weather/operations/windows_silent.py:66:joblib | DEP-1: declare directly instead of relying on scikit-learn |
| src/weather/market/mm_credentials.py:354:eth_account | DEP-2: declare eth-account in the live extra |
| src/weather/market/mm_credential_import_cli.py:626:eth_account | DEP-2: declare eth-account in the live extra |
| src/weather/market/re1_transport.py:164:eth_account | DEP-2: frozen RE-1; declare eth-account after campaign |
| src/weather/market/mm_stage2_entrypoint.py:28:httpx | DEP-3: declare httpx in the live extra |
| src/weather/market/re1_resilience.py:11:httpx | DEP-3: frozen RE-1; declare httpx after campaign |
| src/weather/market/re1_transport.py:167:httpx | DEP-3: frozen RE-1; declare httpx after campaign |
| src/weather/operations/closed_market_day_archive.py:22:pyarrow | DEP-4: declare pyarrow for archive and PIT consumers |
| src/weather/operations/closed_market_day_archive.py:23:pyarrow | DEP-4: declare pyarrow for archive and PIT consumers |
| src/weather/operations/event_day_manifest.py:438:pyarrow | DEP-4: declare pyarrow for archive and PIT consumers |
| src/weather/operations/event_day_manifest.py:480:pyarrow | DEP-4: declare pyarrow for archive and PIT consumers |
| src/weather/point_in_time_contract.py:678:pyarrow | DEP-4: declare pyarrow for archive and PIT consumers |
| src/weather/point_in_time_contract.py:737:pyarrow | DEP-4: declare pyarrow for archive and PIT consumers |
| src/weather/point_in_time_contract.py:753:pyarrow | DEP-4: declare pyarrow for archive and PIT consumers |
| src/weather/reporting/validation/point_in_time_evaluation.py:37:pyarrow | DEP-4: declare pyarrow for archive and PIT consumers |
| src/weather/reporting/validation/point_in_time_evaluation.py:38:pyarrow | DEP-4: declare pyarrow for archive and PIT consumers |

These dependency issues are explicit direct-declaration debt; a transitive
installation does not satisfy the new ratchet. The live SDK remains an optional
declared distribution, and `python-dotenv` is declared on the authorized RE-1
base. No dependency pin was changed by this mission.

Other remaining repository-owned raw HTTP sends use requests rather than urllib
and are listed here too; binary-provider requests cannot use a JSON-only helper:

```text
src/weather/backtesting/settlement_ledger.py:667:    response = requests.get(gamma_event_url(event_slug), timeout=timeout)
src/weather/market/market_microstructure_capture.py:681:            response = self.session.get(
src/weather/market/market_microstructure_capture.py:702:            response = self.session.post(
src/weather/market/market_microstructure_capture.py:735:            response = self.session.get(
src/weather/market/mm_exchange.py:859:        response = requests.request(method, url, headers=headers, json=json_body, timeout=20)
src/weather/market/polymarket_client.py:25:            response = requests.get(self.gamma_event_url, timeout=self.timeout)
src/weather/model/model_sources.py:1186:                response = requests.get(url, timeout=self.timeout)
src/weather/model/model_sources.py:1206:                    resp = requests.get(f"{base_url}{filename}", timeout=self.timeout)
src/weather/model/model_sources.py:2223:            response = requests.get(url, timeout=self.timeout)
src/weather/model/model_sources.py:2239:            response = requests.get(url, timeout=self.timeout)
src/weather/model/model_sources.py:2377:            response = requests.get(url, params=params, headers=headers, timeout=self.timeout)
src/weather/model/model_sources.py:2384:            response = requests.get(url, headers=headers, timeout=self.timeout)
src/weather/sources/asos_one_minute.py:618:            response = requests.get(IEM_ASOS_1MIN_URL, params=params, timeout=self.timeout)
src/weather/sources/eccc_history.py:40:    response = requests.get(url, timeout=30)
src/weather/sources/eccc_swob_history.py:177:                response = requests.get(url, timeout=timeout)
src/weather/sources/eccc_swob_history.py:194:                response = requests.get(file_url, timeout=timeout)
src/weather/sources/forecast_history.py:659:        resp = requests.get(HIST_FORECAST_URL, params={
src/weather/sources/forecast_history.py:706:        resp = requests.get(PREVIOUS_RUNS_URL, params=params, timeout=timeout)
src/weather/sources/grib_probe.py:340:        response = client.get(source_url, timeout=timeout)
src/weather/sources/grib_probe.py:354:            idx_response = client.get(idx_url, timeout=timeout)
src/weather/sources/marine_context.py:487:    response = requests.get(url, timeout=timeout)
src/weather/sources/marine_context.py:619:    response = requests.get(url, timeout=timeout)
src/weather/sources/marine_context.py:726:    response = requests.get(url, params=params, timeout=20)
src/weather/sources/metar_history.py:221:            response = requests.get(IEM_ASOS_URL, params=params, timeout=self.timeout)
src/weather/sources/mrms_precip.py:333:    response = requests.get(url, timeout=20)
src/weather/sources/noaa_ghcnh_history.py:166:        response = requests.get(STATION_LIST_URL, timeout=self.timeout)
src/weather/sources/noaa_ghcnh_history.py:172:        response = requests.get(url, timeout=self.timeout)
src/weather/sources/open_meteo_archives.py:203:    response = client.get(
src/weather/sources/open_meteo_archives.py:214:    response = client.get(
src/weather/sources/reanalysis_history.py:147:        response = requests.get(ARCHIVE_URL, params=params, timeout=self.timeout)
src/weather/sources/reanalysis_synoptic.py:681:    response = requests.get(pressure_level_url(variable, year), timeout=timeout)
src/weather/sources/reanalysis_synoptic.py:691:    response = requests.head(pressure_level_url(variable, year), timeout=timeout)
src/weather/sources/wu_history.py:222:        response = requests.get(self.url, params=params, timeout=self.timeout)
src/weather/sources/wu_history.py:303:        page_response = self.session.get(
src/weather/sources/wu_history.py:314:        response = self.session.get(
```

SDK-managed HTTP and WebSocket sends are separate transport surfaces, not
hidden migrations into this helper. No RE-1 call site was migrated.

## Verification

Fresh venv: **42/42 imports PASS** (34 `mm_*`, 8 `re1_*`), requirements install
PASS, no missing module-initialization packages, cleanup PASS, exit 0. No live
extra or ambient site packages were installed in that venv. This does not prove
that lazy SDK/eth-account/httpx imports can execute under requirements alone.

Focused pre-suite run: **113 passed, 11 skipped**, 29.78 seconds. The skips are the
existing lease acquisition tests while the outer wrapper owns the mutex.
`scratch/87a-final-focused.xml` SHA256:
`4bf1dff26b3891e4f4c75319230624c942bcdf0b1098fdb76c69c2483d2b0d36`.
The earlier committed-file ratchet refusal was resolved by committing the new
files, not relaxing the ratchet. Two initial inventory runs were interrupted
after an inefficient AST traversal; the wrapper recovered each stale marker
only after proving zero residual heavy processes, then admitted the exact
retry. The traversal was corrected before final focused verification.

One full suite: **7,384 passed, 3 failed, 34 skipped, 13 warnings, 991 subtests
passed**, pytest duration 2,862.15 seconds. The guarded job ran September 23
**09:11:20–10:00:49 ET** (13:11:20–14:00:49 UTC), exit 1, no timeout, owned
`C:/pt/87a-full` removed. It finished nearly nine hours before the 19:00 cutoff.
The three failing tests were:

- `test_codex_host_load_hook.py::test_hook_and_workstation_wrapper_share_the_same_offline_module_set`
- `test_morning_guidance_admission.py::test_wrapper_and_hook_exact_allowlist`
- `test_nbm_target_trace_admission.py::test_exact_module_and_guarded_launch`

All three found the same omission: the new `fresh_venv_smoke` module was in
the wrapper's exact allowlist but absent from the checked-in hook. The final
repair adds that one exact entry and tests wrapped acceptance plus direct
execution refusal. No wildcard or authority boundary was widened.

Post-repair focused run: **160 passed, 11 skipped**, 39.45 seconds, including all
three previous failures, the three ratchets, transport/probe/fixture tests,
location-refresh, provenance, import-architecture and workload/hook checks.
The final HTTP truncated-body and per-request proxy refusal regressions pass.
The full suite was **not repeated**, as required; no clean final full-suite
result is claimed. No heavy process or owned pytest temp directory remains.

Retained local receipts (SHA256; the report carries results for clean-checkout readers):

| Receipt | SHA256 |
| --- | --- |
| `scratch/87a-full.xml` | `ab05b5570f7186a183dbb0f4ca9d17dc7c45e3b68ae7c9bf5517e8728ec73753` |
| `scratch/87a-full-receipt.json` | `a75004ecea549f3b9964f5f4b4e46df2f6b5d9f8670d14c814d35aac51893aa5` |
| `scratch/87a-postfull.xml` | `3e2a69fedf9e8bf7b04d8a52707ecc7c60ee1d2d552feab114c003e8481f5a67` |
| `scratch/87a-public-probe.jsonl` | `ebef7235066b54ef361dbbe470421d599d8160c282080aa071c0b66d7d6002cd` |

Documentation audit PASS (18 agent files, 945 Markdown files); generated
roadmap check PASS. PowerShell syntax parse PASS. Cumulative diff check PASS.
`python -m compileall -q app src tests` under `workstation_heavy.ps1`: PASS,
exit 0 after the final implementation repairs.

## Mechanical roll verdict and per-file disposition

`scripts/ops/roll_verdict.ps1 -Branch codex/live-path-qualification-20260923 -Base origin/master`
returned **UNDECIDABLE, exit 1: no live closure evidence**. The four expected
capture closure files are absent in this clean workstation worktree. No mirror
or production evidence was substituted. Production must obtain its own
mechanical verdict for the complete dependency-bearing branch before adoption.

The [per-file inventory](agent-report-2026-09-87a-live-path-qualification-kit-roll.json)
enumerates all 249 cumulative changed paths, including the inherited dependency
and these two report artifacts. Each mechanical capture-closure membership is
unknown because the required evidence is absent; the tool result is retained
without inventing a closure verdict from filenames.

For each mission-owned importable source below, all capture-closure memberships
are **unknown**; none is asserted roll-free:

| File | Roll disposition |
| --- | --- |
| `src/weather/http.py` | UNDECIDABLE |
| `src/weather/operations/fresh_venv_smoke.py` | UNDECIDABLE |
| `src/weather/operations/live_contract_probe.py` | UNDECIDABLE |
| `src/weather/operations/live_contract_sources.py` | UNDECIDABLE |
| `src/weather/operations/location_config_refresh.py` | UNDECIDABLE |
| `src/weather/operations/operating_reference.py` | UNDECIDABLE |
| `src/weather/operations/producer_provenance.py` | UNDECIDABLE |
| `src/weather/operations/taker_bot_daily_roll.py` | UNDECIDABLE |
| `.codex/hooks/pre_tool_use_host_load.py` | UNDECIDABLE; tracked admission entry only, no installed hook mutation |

Each mission-owned test, fixture, Markdown document and PowerShell script is
roll-free by the standing contract. That includes the new smoke wrapper and
its one-line admission-list addition. Inherited source/schema changes from the
explicit dependency retain their own review/integration obligations; this kit
does not certify them as additive or roll-free. This is software qualification,
not model measurement: cluster counts and confidence intervals are inapplicable.

## Reproduction

Run from this branch's worktree on the assigned workstation. Resolve the main
checkout's existing project interpreter, so these commands also work when the
qualified branch is checked out at a different worktree path:

```powershell
$qualificationRepo = (Get-Location).Path
$qualificationCommon = (git rev-parse --path-format=absolute --git-common-dir).Trim()
$qualificationPython = Join-Path (Split-Path $qualificationCommon -Parent) 'venv/Scripts/python.exe'
& "$qualificationRepo/scripts/ops/fresh_venv_smoke.ps1" -PythonPath $qualificationPython
& $qualificationPython -m weather.operations.live_contract_probe --token 15432250279049081963827803811324694729539139797228087450179126800337565816732 --condition 0x11348776f1d311b744028d447635b39f1b9ddac91fcb1e48d5a0ebae501fda59 --public-address 0x000000000000000000000000000000000000dEaD
$qualificationArgs = @('-m','pytest','tests/operations/test_live_path_ratchets.py','tests/operations/test_http.py','tests/operations/test_live_contract_probe.py','tests/operations/test_venue_shapes.py','tests/operations/test_location_config_refresh.py','tests/operations/test_import_architecture.py','tests/operations/test_producer_provenance.py','tests/operations/test_workload_admission_script.py','tests/operations/test_codex_host_load_hook.py','tests/operations/test_morning_guidance_admission.py','tests/operations/test_nbm_target_trace_admission.py','-q','--basetemp=C:/pt/87a-reproduce')
$qualificationEncoded = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes(($qualificationArgs | ConvertTo-Json -Compress)))
& "$qualificationRepo/scripts/ops/workstation_heavy.ps1" -Kind pytest -PythonPath $qualificationPython -ArgumentsBase64 $qualificationEncoded -RepoRoot $qualificationRepo
```

The historical market may expire; a later probe must supply another configured,
currently rewarded pair. Give every later test run a new owned `--basetemp`,
verify its resolved absolute path and remove it after exit. The one full-suite
allowance for this mission has already been consumed; this is not permission
to run another full suite or to cross a live-session boundary.

## Explicit exclusions

No RE-1 implementation change relative to the authorized dependency; no
session-worktree access, campaign mutation, `.env`, credential access,
authenticated venue endpoint, order submission/cancellation, live preflight,
production runtime write, mirror read/write, registration, Scheduler mutation,
restart, production merge, model fit, release promotion or eligibility override.
Source-control merging occurred only inside this isolated implementation branch
to bring in the owner-authorized dependency. No actual user-visible policy
setting was changed; PowerShell arguments affect the spawned child only.
The sole campaign evidence read was the bounded, credential-free normalized
order-event selection described above; no tape, ledger or evidence was changed.
