# Workstation handoff 2026-09-110h — bounded real-data dry-run command for the weather plugin

Written 2026-09-26 by the production agent. The 110b report asks production for a real-input dry run of the weather plugin,
but the plugin has no bounded entry point, so the run was deferred on 2026-09-26 night. Branch
`codex/weather-maker-plugin-20260925` (tip `c734e5c2b` or newer; `maker_core` Phase 0 and the contracts tag are on master).

## Build

`python -m weather.market.maker_plugin.dry_run --date <UTC-date> --data-root <path> --output <dir> [--markets ...]
[--max-seconds 2700] [--max-output-bytes 200000000]`:

- Reads only **sealed** 88a segments for the date (`data/maker_evidence/<date>/<hh>-<seg>/` with a seal/manifest; never an
  unsealed segment, `status.json` or `.tmp`), the snapshot rows, retained NBP bulletins, observation triggers and settlement
  ledgers named in the 110b report. Open-read-close per file; never hold a handle; no writes outside `--output`.
- For each market/event/band and each captured minute: build descriptors (universe), evaluate fair value, list clock events,
  resolve settlement (Pending expected for recent dates), and run `maker_core.quoting.policy.decide()` with the
  `informed_v0` profile on the captured book and reward terms.
- Report (JSON + Markdown): joins and coverage per input source, `Unavailable` reasons with counts, per-event probability mass
  sums, per-decision leg counts (0/1/2) and reason codes, time and bytes used. Stop cleanly at the time or byte cap.
- Tests on fixtures; include the repo-wide audits (schema registry, import architecture, agent docs audit, path policy) in the
  focused run.

## Boundaries and deliverables

No venue calls, no credentials, no production data on the workstation (fixtures only). Report:
`docs/roadmap/agent-report-2026-09-110h-weather-plugin-dry-run-cli.md` with the exact production command. Push is authorized; the
production agent runs it under the lease.
