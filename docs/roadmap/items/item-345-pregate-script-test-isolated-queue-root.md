# 345. Isolated Queue Root For The Workstation Pre-Gate Script Test [OPEN 2026-11-05 - TEST-ONLY FIX BUILT, AWAITING REVIEW]

Goal: make `tests/operations/test_workstation_pregate_script.py` run against an isolated heavy-workload queue root
instead of the real one, so a suite run cannot read or write the host-global queue that live wrappers use.

Owner/package: `tests/operations` (the test) and, if the queue root is not yet overridable, the admission helpers in
`scripts/ops/workload_admission.ps1` (a reviewed `.ps1` change). Workstation builds; master lands.

Source: WS run lessons 2026-11-04/05 (343b suite runs; relayed by the WS coordinator). The run-procedure lessons are in
[development, workstation pre-gate](../../development.md#workstation-pre-gate-before-a-host-landing-slot).

Why this matters: at `cb6678f35` the test builds its queue path from the real `%ProgramData%`
(`test_workstation_pregate_script.py:362`, `Path(os.environ["ProgramData"]) / "WeatherProject" /
"heavy_workload_queue_v1"`), so the test shares state with every wrapper on the machine.

Disclosure: two of its fixtures skip below 55 GiB free on the test volume (at `cb6678f35`, `:285-286` and `:671-672`: the `fixture_repo` fixture and the nested-exclusive test; "the host
suite's 50 GiB disk floor cannot be met on this volume"); a green run on a fuller disk did not exercise them.

Checklist:

- [x] No production override was added: the production admission script still honours no redirect. Instead
  every fixture copy of `workload_admission.ps1` in the test is rewritten (`_copy_isolated_scripts`): a private
  `Local\WeatherPgFixture-<uuid>` mutex family and a temporary state root, so the queue, slot state and exclusive-holder
  record resolve under `tmp_path`. Nested tests hold that private slot 1 instead of inheriting the caller's real slot.
  Setup fails closed before any write: each overridden production function must be defined exactly once and the
  host common-data root may be reached only inside `Get-WeatherHeavyWorkloadPoisonPath`
  (`test_isolation_fails_closed_at_setup_when_an_override_would_not_bind`), and a read-only resolution probe checks the
  copy before use. Intentional coverage trade: the residual-process and memory stubs, and the bypassed ACL-checked
  state-root resolver, are not exercised by this test.
- [x] `test_fixture_admission_uses_a_temp_queue_root_and_private_mutexes` asserts the queue root, holder record,
  slot state files and mutex names all resolve to the temporary root and private names, none under the host's common
  application-data root; the end-to-end receipts assert the queue directory under the temporary root. No host-global
  state is read or written; the only contact with the live root is the negative test listing names under it (metadata,
  no file opened).
- [x] Fail-closed setup, added after review: `test_isolation_fails_closed_at_setup_when_an_override_would_not_bind`
  runs 5 cases through `_copy_isolated_scripts` (each of the three override targets renamed, a second
  `CommonApplicationData` use, `$env:ProgramData` in another copied script); each aborts before any write and before any
  process starts. Its supporting snapshot is the set of names under the live root (minus queue tickets, slot state
  files and `.tmp`/`.bak` siblings) plus whether the exclusive-holder record exists. The rewritten admission text is
  asserted to name no `Global\` object, and the 7 other copied scripts are checked for any host-state-root token.
- [ ] The 55 GiB skips are reported in the suite receipt when they fire.
- [ ] Open follow-up (delta review of `be1beced9`, findings 1-2): take the overridden function's span from the
  PowerShell parser AST instead of a text scan to the next `function`, and check that no top-level statement of the
  production admission script reaches host state outside the overridden functions.
- [ ] Open follow-up: minors 2, 3, 5 and 6 of the delta review of `be1beced9..4e2e64cde`.

Acceptance: the test passes with no state read or write under the real `%ProgramData%\WeatherProject` root; the
negative test only lists names there (metadata, no file opened). That listing is supporting evidence; the proof is
setup failing closed before any write and before any process starts.
