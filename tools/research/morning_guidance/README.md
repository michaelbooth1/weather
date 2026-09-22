# Morning guidance research — mission 2026-09-81a

Offline tooling for the fixed two-candidate development read. The immutable
[pre-registration](../../../docs/research/morning-guidance-candidate-preregistration-2026-09-21.md)
owns the estimator; [DESIGN.md](DESIGN.md) is a proposal only.
The [handback](../../../docs/roadmap/agent-report-2026-09-81a-workstation-morning-guidance-candidate.md)
owns results, exact local reproduction commands and limitations.

Run `tools.research.morning_guidance.run` only through
`scripts/ops/workstation_heavy.ps1 -Kind weather_heavy`. The exact entry point
is admitted in both the hook and workload wrapper, with their tests; all other
host, principal, lease and child-tree checks remain intact. No network or
provider retrieval is implemented here.

- `coverage --input <extracted-1> --raw <unpacked> --output <new scratch dir>`
  counts availability and joins the numeric rows to retained rejection reasons;
  it computes no candidate score. The original P0 outputs precede registration.
- `score` with the same arguments also requires `--push-receipt <file>` binding
  the frozen commit/hash, exact branch ref and pre-score remote verification
  timestamp. Hash checks and the immutable output header precede scoring.
- `publish --input <evidence scratch root> --output <new scratch dir>` produces
  aggregate-only publication material from retained coverage/scoring outputs;
  it never scores or changes the frozen specification.

Inputs and outputs must be absolute scratch paths, never mirror/data paths.
Outputs are create-only. Raw per-snapshot deltas stay in ignored scratch.
The retained aggregate `evidence.json` contains no row-level market identities
or archive payloads; it binds source/output hashes and carries the frozen
pre-registration header. Reruns must use fresh directories and retain failures.

Synthetic tests live beside the pure function as requested; the normal suite
collects them through `tests/reporting/test_morning_guidance.py`. Every heavy
test or analysis uses the same workstation wrapper and an explicit temporary
pytest directory. Nothing under this tool is imported by serving.
