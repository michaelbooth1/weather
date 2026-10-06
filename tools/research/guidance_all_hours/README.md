# Guidance at all hours — mission 2026-09-111h Part 2

Offline scorer for the frozen
[pre-registration](../../../docs/research/guidance-all-hours-preregistration-2026-09-29.md).
The [handback](../../../docs/roadmap/agent-report-2026-09-111h-guidance-all-hours.md) owns results.
81a's `candidate.py` and `statistics.py` are imported unchanged; `features.py` only substitutes
the seven NBM v2 values and recomputes the two validity flags with the feature builder's rule.

Run only through `scripts/ops/workstation_heavy.ps1 -Kind weather_heavy`, in this order:

1. `control --input <extract dir> --output <new dir>`: 81a's rule on captured features, 06-09
   local, targets through 2026-09-19. Reported before any v2 table.
2. `census --input <extract dir> --output <new dir>`: the EF §10k wrong-period census.
3. `score --input <extract dir> --output <new dir> --control <control.json>`: v2 C1/C2 tables
   per hour block × stratum and all hours, the decision rule and both falsifiers.

Every stage refuses unless the pre-registration bytes match its hash, the freeze commit binds them,
is an ancestor of HEAD and is on the remote freeze branch, and every extract file matches
`SHA256SUMS` with manifest status `COMPLETE` at parser HEAD `2e17ce0eb`. Rows with a target date
on or after 2026-09-30 (the replay-exam panel) are counted and never scored. Inputs and outputs
are absolute paths outside the repository; outputs are create-only. Per-row deltas stay outside
the repository; only the aggregate `evidence.json` is committed.
