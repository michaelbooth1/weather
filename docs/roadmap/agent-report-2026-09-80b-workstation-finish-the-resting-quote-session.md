# Mission 09-80b — finish the resting-quote session

**PASS for inert implementation and workstation qualification: the full suite has zero failures. No live authority is granted.**

## Provenance

Branch: `codex/stage2-hold-build-20260921`; draft PR [74](https://github.com/michaelbooth1/weather/pull/74),
stacked on `codex/maker-reconcile-20260920`. The handoff-b branch was merged
first, followed by the requested maker parent `0fc25f40b`. Their merged
starting point is `6fc7b4ba9d56ea504ece1892c4b982c016d35897`.
The implementation commits are `0ef0e354`, `ac9d0feb`, `dd693ec5`, `983f8989`,
`a114d5c2`, and `12e64a8e9e825ed5688591a2b82629fe79e31676`.

Mission 80b explicitly corrects both stops in the accepted 80a report. The
owner additionally granted the manifest builder and tests, the exact two-token
user-stream extension and tests, the additive `mm_stage2_hold_v0.1` schema,
and the PowerShell host-assignment parser and tests. The offline module list
and workload admission controls were not changed.

## Package dispositions

| Package | Disposition |
| --- | --- |
| W0/W1 | Retained from 80a. The real allocation/isolation validator still rejects the old mixed wallet under isolation. Pure quote pricing remains unchanged. A fresh dedicated wallet is the default; no wallet was accessed. |
| W2 | Hash-bound profiles drive adapter and runtime caps. Stage 1's numeric profile bytes remain unchanged. Stage 2 is 16/order, 20/band, 25/event, 25/daily loss, 100/wallet, two 20-share BUY post-only orders, 7,200 seconds, four sessions/day and three reward days. Both dated grants must match. |
| W3 | Two independent single-use token capabilities, one heartbeat; zero account-wide orders before leg one and exactly leg one before leg two. Fake-clock end conditions cancel/reconcile. Both known unfilled IDs must appear in the explicit cancel acknowledgement; dead-man disappearance cannot substitute. Filled or unresolved attempts stop the campaign. |
| W4 | Stage 2 manifest, fixed template, sealer, original predecessor consumption, host schema, workload name and parent receipt validation. One typed session confirmation precedes credentials. Four original Stage 0/1 runs are required: YES Stage 0 plus both Stage 1 modes, and NO Stage 0. The existing portable Git, host/principal, ACL, source/interpreter and child-job controls remain. |
| W5 | Actual pinned SDK scoring/earnings parsers over closed HTTP fixtures; no import-time reads. Prediction and journal hashes freeze before earnings. Daily accrual is separate from independently reconciled payment. The offline verdict retains the frozen thresholds, cumulative evidence floor and all-session/day coverage checks. |
| W6 | One public-book/fake-exchange rehearsal command; three retained, reproducible bands from one complete configured tomorrow-market selection. They are explicitly REHEARSAL, never eligibility, payment or live evidence. |
| W7 | Pilot and portable-host runbooks, owner decision draft/abort card, PROPOSED dated RE-1A addendum and owning roadmap items. The owner has not ratified the addendum and no grant exists. |

Stage 2 uses half-second SDK connect/read/write/pool inactivity limits and a
two-second separate positions request. Control checkpoints run between reads.
These are socket inactivity bounds, not a guaranteed total HTTP elapsed-time
bound. The launcher deadline and the unchanged venue dead-man backstop remain
necessary. No Stage 0/1 transport default was changed.

## Retained three-band rehearsal

The common [selection](../../tests/fixtures/stage2_hold/20260921/selection.json)
was captured on 2026-09-21 at approximately 14:55 UTC, for September 22 markets.
It retains the public Gamma/event, per-condition reward, fee and book response
evidence, every ranked/refused row, and the selection. SHA-256:
`132b27ecc8b4010b1791656f920dd01b2f74937b7ec4119db1d41f8584b84f47`.
There were 17 configured band rows, four eligible. Only the first, Miami, is
selected for a hypothetical live seal; testing the next two does not authorize
substitution. Earlier public fetches correctly refused HTTP/pagination errors
or a now-ineligible Seattle condition; the predicates were not relaxed.

| Band | `P_many` for 360-minute selection | Replayed `P_many` / `P_single` | Visible fake minutes | Cleanup elapsed |
| --- | ---: | ---: | ---: | ---: |
| Miami | 6.644751876527137 | 0.03691528820292854 / 0.04451604697502856 | 2 | 2 seconds |
| Dallas | 3.7488448326969017 | 0.02082691573720501 / 0.025010772081370987 | 2 | 2 seconds |
| Los Angeles | 3.3629028909893535 | 0.01868279383882974 / 0.02027331431145819 | 2 | 2 seconds |

The [fixture README](../../tests/fixtures/stage2_hold/20260921/README.md) identifies
the real and simulated fields. Each 125-second accelerated run reuses one
public snapshot, adds fake own visible depth, makes exactly two fake submits,
and retains a journal, frozen prediction and bundle. No control predicate was
replaced. All three returned both cancellation acknowledgements, zero open
orders and zero fills. The SDK fixture confirms `SecureClient.cancel_all()`
parses `CancelOrdersResponse.canceled` (tuple of order IDs) and `not_canceled`
(ID-to-reason mapping), and adapter normalization preserves both IDs as a list.
It uses a closed HTTPX transport without auth headers or a signer.

| Band | Journal SHA-256 | Prediction SHA-256 |
| --- | --- | --- |
| Miami | `3c08cb66eb6a4ee6d39b4dcb66d0cdec8f867db1371f88082b83da6a24696860` | `30975190b99eda7a566234ceb26477f6cbdfb0014b14e3265b4324cd26d79da0` |
| Dallas | `b505cf54dd62268ea89b09ad68db09014305405080e66ce93fb833526f9c3fea` | `17939afcc4f357788336d9569c255feb363b533d0d5cf572cddb7b4ddedc7066` |
| Los Angeles | `79ab6577b76b74e89d6f1073656e71fea63f61c0845226d8477fe3d838fa0bf8` | `d2647ac24776c1c70a8fe0bba1452daa648f6578b145782fa52a76accfe7a9b4` |

This is three band fixtures from one public capture date, not three reward
days or a statistical sample. Zero economic market-days, fills or payments
were observed; confidence intervals and profitability claims do not apply.
The 360-minute numbers rank public inputs; they are not measured earnings.

## Verification

- Focused workstation regression: **88 passed, zero failures**, 41.37 seconds, including the installed pinned SDK transport/parser fixtures and module-size/import-architecture checks.

- Required full workstation suite at `12e64a8e9e825ed5688591a2b82629fe79e31676`: **7,044 passed, 34 skipped, 991 subtests passed, zero failures**, 2,755.17 seconds (45:55), through `scripts/ops/workstation_heavy.ps1`.
- JUnit confirms 8,069 cases including subtests/skips, **0 failures and 0 errors**. Retained task-local file: `data/research/stage2-hold-80b/full-suite-12e64a8e.xml`, SHA-256 `90de1fc052d1e6b8d0dacc5516cb003184f06b9a60beaf076fd8c568fd7e8c8c`. It is ignored local evidence, not assumed present in a clean checkout; commands below reproduce it.
- The only warning was the NumPy/netCDF binary-size warning already visible in Linux CI. It did not fail a test. No remaining failure needs a parent reproduction.
- `compileall -q app src tests` passed through the workstation wrapper at the same code revision.
- The handback adds documentation only after that tested code commit. Documentation audit passed (18 agent files, 908 Markdown files); backlog regeneration/check and diff whitespace verification passed for the handback.

At `12e64a8e9e825ed5688591a2b82629fe79e31676`:

- [Linux CI](https://github.com/michaelbooth1/weather/actions/runs/35621053575): **6,566 passed, 512 skipped, 989 subtests passed, zero failures**, 497.86 seconds. One NumPy/netCDF runtime warning. Optional live-SDK parser fixtures skip only where that extra is absent; the workstation has the pinned SDK installed.
- [Native Windows qualification](https://github.com/michaelbooth1/weather/actions/runs/35621053634): **308 passed, zero failures**, 399.22 seconds.
- CI compileall, documentation audit and generated-backlog check all passed.

The preceding Linux run found one emergency-cancel evidence regression and
two module-size audit failures. All were introduced here and corrected:
retain and journal the adapter's explicit emergency ACK when a rejected second
submit already cancelled leg one, and extract terminal market evidence into
its existing market owner. The architecture threshold/allowance was not raised.
A local full run on `dd693ec5` was interrupted to tighten ACK handling; it is
not counted as a completed qualification. Its temporary directory was removed.

The complete positive four-predecessor live seal has not been exercised on an
authorized installation. Manifest construction, actual template rendering,
real controller/fake transports, parent artifact consumption and rehashed
tamper refusals are covered separately. Actual-host qualification and fresh
attended predecessors remain prerequisites to any later owner-authorized use.

## Preserved grant preparation sequence

The inherited [80a handoff, section 7](https://github.com/michaelbooth1/weather/blob/a1ee3ba986bedde452e6953236d4b0553cc6dde0/docs/roadmap/workstation-handoff-2026-09-80a-build-the-resting-quote-session.md)
places initial attended Stage 0/1 qualification before the owner grant decision.
The handback preserves that order. A grant commit changes the exact Git tip
and host-assignment bytes, so the four predecessor runs used for Stage 2 must
be repeated after that commit. Earlier receipts cannot cross the binding change.
This is additional attended qualification, not a relaxed predicate or new live
authority. The pilot runbook and owner draft now say so explicitly.

Reversing the preparation order to avoid that repeat was offered for separate
owner review, but has not been approved and is not used by this handback.
No grant or live predecessor was produced during this mission.
## Roll disposition

The repository-owned `roll_verdict.ps1` returned exit 1, **UNDECIDABLE**, because
all four live closure receipts are absent on this workstation. The rerun at `12e64a8e` is retained in `data/research/stage2-hold-80b/roll-verdict-12e64a8e.log`. No closure was
derived by hand and no production evidence was fetched. Treat the branch as
roll-sensitive and rerun the canonical verdict on production before scheduling
its guarded adoption. The delegation contract identifies `schema_registry*`
as entering all four closures. The registry diff here is **additive-only**:
the two approved policy-identifier exclusions and one approved durable schema;
no existing registration was changed.

| Mission path (relative to merged starting point) | Roll disposition |
| --- | --- |
| `docs/operations/INTERNATIONAL_MM_LIVE_PILOT.md` | Roll-free non-runtime file; no Python closure membership. |
| `docs/operations/PORTABLE_LIVE_EXECUTION_HOST.md` | Roll-free non-runtime file; no Python closure membership. |
| `docs/operations/stage2-hold-owner-authorization-draft.md` | Roll-free non-runtime file; no Python closure membership. |
| `docs/research/re1a-hold-treatment-addendum-2026-09-21.md` | Roll-free non-runtime file; no Python closure membership. |
| `docs/roadmap/active-backlog.md` | Roll-free non-runtime file; no Python closure membership. |
| `docs/roadmap/items/item-330-maker-economics-refocus-master-plan.md` | Roll-free non-runtime file; no Python closure membership. |
| `docs/roadmap/items/item-67-authenticated-exchange-adapter-and-mm-2-pilot-harness.md` | Roll-free non-runtime file; no Python closure membership. |
| `scripts/ops/international_live_templates/stage0.py.tmpl` | UNDECIDABLE: live closure receipts unavailable; no membership inferred. |
| `scripts/ops/international_live_templates/stage1_cancel_all.py.tmpl` | UNDECIDABLE: live closure receipts unavailable; no membership inferred. |
| `scripts/ops/international_live_templates/stage2_hold.py.tmpl` | UNDECIDABLE: live closure receipts unavailable; no membership inferred. |
| `scripts/ops/workload_admission.ps1` | Roll-free non-runtime file; no Python closure membership. |
| `src/weather/execution_host.py` | UNDECIDABLE: live closure receipts unavailable; no membership inferred. |
| `src/weather/market/AGENTS.md` | Roll-free non-runtime file; no Python closure membership. |
| `src/weather/market/market_making_live_pilot.py` | UNDECIDABLE: live closure receipts unavailable; no membership inferred. |
| `src/weather/market/mm_live_attendance.py` | UNDECIDABLE: live closure receipts unavailable; no membership inferred. |
| `src/weather/market/mm_live_candidate_cli.py` | UNDECIDABLE: live closure receipts unavailable; no membership inferred. |
| `src/weather/market/mm_live_envelope.py` | UNDECIDABLE: live closure receipts unavailable; no membership inferred. |
| `src/weather/market/mm_live_pilot_cli.py` | UNDECIDABLE: live closure receipts unavailable; no membership inferred. |
| `src/weather/market/mm_official_adapter.py` | UNDECIDABLE: live closure receipts unavailable; no membership inferred. |
| `src/weather/market/mm_policy.py` | UNDECIDABLE: live closure receipts unavailable; no membership inferred. |
| `src/weather/market/mm_stage2_entrypoint.py` | UNDECIDABLE: live closure receipts unavailable; no membership inferred. |
| `src/weather/market/mm_stage2_hold.py` | UNDECIDABLE: live closure receipts unavailable; no membership inferred. |
| `src/weather/market/mm_stage2_rehearsal.py` | UNDECIDABLE: live closure receipts unavailable; no membership inferred. |
| `src/weather/market/mm_stage2_rewards.py` | UNDECIDABLE: live closure receipts unavailable; no membership inferred. |
| `src/weather/market/mm_stage2_selection.py` | UNDECIDABLE: live closure receipts unavailable; no membership inferred. |
| `src/weather/market/mm_stage2_user_stream.py` | UNDECIDABLE: live closure receipts unavailable; no membership inferred. |
| `src/weather/market/mm_user_stream.py` | UNDECIDABLE: live closure receipts unavailable; no membership inferred. |
| `src/weather/operations/international_live_session_launcher_sealer.py` | UNDECIDABLE: live closure receipts unavailable; no membership inferred. |
| `src/weather/operations/international_live_session_runner.py` | UNDECIDABLE: live closure receipts unavailable; no membership inferred. |
| `src/weather/operations/international_live_wrapper_sealer.py` | UNDECIDABLE: live closure receipts unavailable; no membership inferred. |
| `src/weather/schema_registry_data.py` | All four per standing contract; additive-only. Fresh tool verdict unavailable. |
| `tests/fixtures/stage2_hold/20260921/README.md` | Roll-free non-runtime file; no Python closure membership. |
| `tests/fixtures/stage2_hold/20260921/dallas/bundle.json` | Roll-free non-runtime file; no Python closure membership. |
| `tests/fixtures/stage2_hold/20260921/dallas/journal.jsonl` | Roll-free non-runtime file; no Python closure membership. |
| `tests/fixtures/stage2_hold/20260921/dallas/prediction.json` | Roll-free non-runtime file; no Python closure membership. |
| `tests/fixtures/stage2_hold/20260921/los-angeles/bundle.json` | Roll-free non-runtime file; no Python closure membership. |
| `tests/fixtures/stage2_hold/20260921/los-angeles/journal.jsonl` | Roll-free non-runtime file; no Python closure membership. |
| `tests/fixtures/stage2_hold/20260921/los-angeles/prediction.json` | Roll-free non-runtime file; no Python closure membership. |
| `tests/fixtures/stage2_hold/20260921/miami/bundle.json` | Roll-free non-runtime file; no Python closure membership. |
| `tests/fixtures/stage2_hold/20260921/miami/journal.jsonl` | Roll-free non-runtime file; no Python closure membership. |
| `tests/fixtures/stage2_hold/20260921/miami/prediction.json` | Roll-free non-runtime file; no Python closure membership. |
| `tests/fixtures/stage2_hold/20260921/selection.json` | Roll-free non-runtime file; no Python closure membership. |
| `tests/market/stage2_fakes.py` | UNDECIDABLE: live closure receipts unavailable; no membership inferred. |
| `tests/market/test_mm_live_attendance.py` | UNDECIDABLE: live closure receipts unavailable; no membership inferred. |
| `tests/market/test_mm_live_envelope.py` | UNDECIDABLE: live closure receipts unavailable; no membership inferred. |
| `tests/market/test_mm_stage2_hold.py` | UNDECIDABLE: live closure receipts unavailable; no membership inferred. |
| `tests/market/test_mm_stage2_rehearsal.py` | UNDECIDABLE: live closure receipts unavailable; no membership inferred. |
| `tests/market/test_mm_stage2_rewards.py` | UNDECIDABLE: live closure receipts unavailable; no membership inferred. |
| `tests/market/test_mm_stage2_selection.py` | UNDECIDABLE: live closure receipts unavailable; no membership inferred. |
| `tests/market/test_mm_user_stream.py` | UNDECIDABLE: live closure receipts unavailable; no membership inferred. |
| `tests/operations/test_international_live_session_runner.py` | UNDECIDABLE: live closure receipts unavailable; no membership inferred. |
| `tests/operations/test_international_live_wrapper_sealer.py` | UNDECIDABLE: live closure receipts unavailable; no membership inferred. |
| `tests/operations/test_stage2_child_evidence.py` | UNDECIDABLE: live closure receipts unavailable; no membership inferred. |
| `tests/operations/test_stage2_host_schema.py` | UNDECIDABLE: live closure receipts unavailable; no membership inferred. |
| `tests/operations/test_stage2_session_sealing.py` | UNDECIDABLE: live closure receipts unavailable; no membership inferred. |
| `tests/operations/test_workload_admission_script.py` | UNDECIDABLE: live closure receipts unavailable; no membership inferred. |
| `docs/roadmap/agent-report-2026-09-80b-workstation-finish-the-resting-quote-session.md` | Roll-free documentation. |

## Boundaries retained

No real order, signature, cancellation, authenticated venue call, account or
wallet read, credential file/store access, authorizing grant, Scheduler
registration, production write, capture restart, master merge or live promotion
was performed. Only source-control network operations and unauthenticated
public market GETs were used. Historical test grants have expired dates and
incomplete fictional assignments; they cannot authorize this installation.
The real current-authority file and host assignment are unchanged.

The owner draft explicitly retains residual exposure: after total loss of
connectivity, both twenty-share buys may rest up to fifteen seconds, with
about 19.40 pUSD reserved capital. Explicit acknowledged cancel-all is primary;
the existing 10–15 second dead-man acceptance window is unchanged.

## Reproduction

From a checkout of the tested commit with the project interpreter and optional
pinned live SDK extra installed, on the **non-capture workstation only**, use
the full-suite wrapper form in [development](../development.md#separate-non-capture-workstation).
Include `--basetemp` and `--junitxml`; remove only that run's verified temporary
directory afterwards. The capture host must use its admitted bounded-suite
runbook instead; these commands grant it no full-suite exception.

```powershell
$repoRoot = (Resolve-Path .).Path
$pythonPath = (Resolve-Path .\venv\Scripts\python.exe).Path
$argumentJson = ConvertTo-Json -InputObject @('-m','pytest','-q','--tb=short','--basetemp','C:/tmp/weather-80b-verify','--junitxml','data/research/stage2-hold-80b/full-suite.xml') -Compress
$argumentBase64 = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($argumentJson))
& (Join-Path $repoRoot 'scripts/ops/workstation_heavy.ps1') -Kind pytest -PythonPath $pythonPath -ArgumentsBase64 $argumentBase64 -RepoRoot $repoRoot
.\venv\Scripts\python.exe -m weather.operations.agent_docs_audit
.\venv\Scripts\python.exe -m weather.reporting.roadmap.roadmap_backlog --fail-on-lint --check
.\venv\Scripts\python.exe -m weather.market.mm_live_pilot_cli stage2-hold rehearse --condition 0x5e0efc3ebbf93111ed44ccca7aa815a058cacd59fbcfe648fd787ad7ef4dca90 --public-capture tests/fixtures/stage2_hold/20260921/selection.json --out data/research/stage2-hold-replay/miami
git ls-remote --exit-code --refs origin refs/heads/codex/stage2-hold-build-20260921
```

Use new output directories. Dallas condition:
`0x15ed16f5d58af7848906269e3727688667c90aa033edd2cb0dc4bc16286dbb18`;
Los Angeles:
`0xd461d5df262d1247450b11b4be29426a9996d384ae0b5d0a4be0fd3655484666`.
The same rehearsal accepts `--scenario fill_first` or `--scenario reject_second`.
Omit `--public-capture` only for a fresh public-only selection, which may refuse
previously eligible bands. No seal or grant is needed for the closed rehearsal.
