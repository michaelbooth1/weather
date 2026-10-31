# F8-MH freeze sha pins (L16, 2026-10-31, ledger row 104)

sha256 of each frozen file at the freeze commit. The code pins the freeze doc and the S0 spec itself; this file pins
the code and the tests. Git blob shas of the vendored, unchanged statistic modules are in the code (`BLOBS`).

| File | sha256 | git blob |
| --- | --- | --- |
| `docs/research/f8-mh-forward-2026-10-31/freeze.md` | `273c1070df0cb87c9c25366d5f8b37d61b766e2f0f2faa550c633e2a19523316` | `d651de95089771057db9f6a58c63d8314efd0168` |
| `docs/research/f8-mh-forward-2026-10-31/s0_spec.md` | `795dd5091fdbaec702bd74ed650748f892e906710869140f3f8e42631ff026e8` | `c2c5669900569423373224024e4c9fb87a912b43` |
| `tools/research/forward_f8/f8_mh.py` | `b153886358e98070c5497d5164b8f93c5387e5517b0cd469e4f1332bd2f7f52f` | `e90e71a6fc982af1e9ae317d8001f25ccadd1d91` |
| `tests/reporting/test_forward_f8_mh.py` | `d19e02389c418118faf390726f9f1d2265182ccb51b0e1e4bb2f977239733d7f` | `a7bf2bd9492c3a31b591febfc25734cd782f4195` |
| `src/weather/calibration/mr_sweep.py` | `eab89868ecec5700799521b11a0d2706676ee32df0538977bb17ffb219184f2f` | `f49e38184d62264f9684922b02b4ca2e8923781b` |
| `src/weather/calibration/mr_gate.py` | `5bdc3fa867996811e48296d6e478fe5d02ab70ba040e6b73f441b09ffcab1852` | `153dd07c12cd20ca079cb4ee9647f9fce99e40e7` |
| `src/weather/calibration/loyo_screen.py` | `c5e52e6fdc10db03ad52e51c45753724a6474be637417e9bff777b9b9f1c4773` | `fd9ea5a7a0c8923042d522512771859746e2d55a` |
| `docs/research/mg2-composite-binding-2026-10-25/release-binding.json` | `4e4dd97d0b2aa0eae920d6ee5406160ca8f0c16a001ba1615446702554a812fa` | `a0dd554e03a2a842c2cdc70aad3f8368c150cda8` |

Base: `origin/master` @ `4e0939833f2d5cbef4de04de7caa8e06933591af`; ledger row 104 commit `1da8d747586067d683f55dd12d0fe505193c2e22`.
Tests: 24 passed (synthetic only), through `workstation_heavy.ps1 -Queue`, basetemp under `C:\t\l16`, deleted.

## Clarification 1 (2026-10-31, master ruling (b), before any forward read; non-deciding disclosure only)

The rows above stay the record of the freeze commit. The code and the tests changed for Clarification 1; their
current pins are below. `freeze.md`, `s0_spec.md` and the S0 receipt are unchanged, and S0 was not re-run. The code
pins the clarification's sha256 as `CLARIFICATION_1_SHA256`.

| File | sha256 | git blob |
| --- | --- | --- |
| `docs/research/f8-mh-forward-2026-10-31/clarification_1.md` | `eef842e8a40da1f9041a038bec6ab6ece6103d16235cb2b58c0231f3e115d260` | `da59b1e64276f24c587b36e028c89bd627071ed5` |
| `tools/research/forward_f8/f8_mh.py` (current) | `c325149ff2e0f5bbcb2d82169fcf293980a02d5f10cc60abec3990b025b509cd` | `0aa48b64f4cd7a92b9e9351b5df87074899a7b48` |
| `tests/reporting/test_forward_f8_mh.py` (current) | `28928821ace01c7574aef782e5839c3b4eb29a662cfe4cba095fcc5a52dbb75c` | `50d3e388bf1c4cbbaa5037da5a39b48de0eacb3b` |

Tests: 30 passed (synthetic only), through `workstation_heavy.ps1 -Queue`, basetemp `C:\t\l16\f8c1-pytest`, deleted.
They include the proof that the label, the D3 numbers, the result, the frozen disclosure and the control are identical
with and without Clarification 1's disclosure, and also when the disclosure raises an error.
