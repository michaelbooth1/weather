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

Disclosure: two of its fixtures skip below 55 GiB free on the test volume (`:285-286` and `:671-672`, "the host
suite's 50 GiB disk floor cannot be met on this volume"); a green run on a fuller disk did not exercise them.

Checklist:

- [x] No production override was added: the production admission script still honours no redirect. Instead
  every fixture copy of `workload_admission.ps1` in the test is rewritten (`_isolate_admission`): a private
  `Local\WeatherPgFixture-<uuid>` mutex family and a temporary state root, so the queue, slot state and exclusive-holder
  record resolve under `tmp_path`. Nested tests hold that private slot 1 instead of inheriting the caller's real slot.
- [x] `test_fixture_admission_uses_a_temp_queue_root_and_private_mutexes` asserts the queue root, holder record,
  slot state files and mutex names all resolve to the temporary root and private names, none under the host's common
  application-data root; the end-to-end receipts assert the queue directory under the temporary root. The test file no
  longer names the real queue path.
- [ ] The 55 GiB skips are reported in the suite receipt when they fire.

Acceptance: the test passes with no read or write under the real `%ProgramData%\WeatherProject` queue directory.
