# 102. Toronto ECCC Runtime Source Hardening [COMPLETE 2026-06-18 - TORONTO SOURCE HEALTH GATE LIVE]

Goal: make Toronto's official Canadian observation and gridded forecast sources
fail independently and diagnostically, without breaking late-day model
confidence or observation-trigger policy.

Source: `docs/research/MODEL_LIVE_REVIEW_2026-06-16.md`. The June 16 latest
Toronto source-status rows showed `eccc_gem`, `eccc_swob`, and `open_meteo`
failures. The observation-trigger status also surfaced an ECCC SWOB runtime
error: `name 'ThreadPoolExecutor' is not defined`.

Why this is missing: items 80 and 89 added Toronto ECCC/GEM source and model
contracts, but the runtime paths still need failure isolation and targeted
tests for supervisor/import contexts. Toronto is the only current moderate-trust
location, so source regressions there carry extra operational cost.

## Design

Keep Toronto's official Canadian sources independent at fetch, provenance, and
reporting boundaries:

1. Exercise the supervisor path (`weather.operations.observation_trigger` ->
   `TorontoHighTempModel.fetch_eccc_swob`) in a focused test with mocked SWOB
   directory/XML responses. This locks in the runtime import boundary that
   previously missed `ThreadPoolExecutor`.
2. Keep ECCC SWOB, ECCC citypage, ECCC GEM, Weather.com, and Open-Meteo as
   separate source adapter rows. A failure in one source must produce its own
   `source_status` row and must not collapse the rest of the fetch group.
3. Add a Toronto official-source health gate over `eccc_swob`,
   `eccc_citypage`, and `eccc_gem`. During late-day lock-in windows, any
   missing/degraded official source should warn explicitly while preserving the
   model row.
4. Persist that health gate in model build output and snapshot artifacts, and
   add compact long-row fields so every captured model row says whether
   official Canadian inputs were available.
5. Extend the source-redundancy report with live source-status cases from
   `source_status_long.csv`, including official Canadian source failures. This
   turns the June 16 Toronto `eccc_gem`/`eccc_swob` failure into a regression
   shape future reports can compare against.

- [x] Reproduce the observation-trigger ECCC SWOB failure in a focused test or
  CLI smoke that runs the same import path as the supervisor.
- [x] Fix the missing runtime import/dependency boundary that produces
  `ThreadPoolExecutor` failures.
- [x] Add per-source failure isolation so ECCC SWOB, ECCC citypage, ECCC GEM,
  Weather.com, and Open-Meteo failures are reported separately and do not mask
  each other.
- [x] Add Toronto source-health gates that warn when official Canadian sources
  are missing during late-day lock-in windows.
- [x] Backfill the June 16 Toronto source-status case into the source
  redundancy report so future regressions can be compared to this event.

Acceptance: Toronto can run snapshot and observation-trigger loops with ECCC
sources enabled under supervisor conditions, failures are source-specific and
actionable, and late-day model rows explicitly report whether official Canadian
inputs were available.

Verification:

- `python -m pytest tests/operations/test_observation_trigger.py::ObservationTriggerTests::test_observation_fetch_eccc_swob_supervisor_path_uses_threadpool_import tests/model/test_source_cache_ttl.py::TestSourceCacheTtl::test_toronto_forecast_source_failures_remain_independent tests/model/test_source_cache_ttl.py::TestSourceCacheTtl::test_toronto_official_source_health_warns_late_day_degradation tests/reporting/test_source_redundancy.py::TestSourceRedundancy::test_source_redundancy_includes_june16_toronto_source_status_case`
- `python -m pytest tests/model/test_source_cache_ttl.py tests/operations/test_observation_trigger.py`
- `python -m pytest tests/reporting/test_source_redundancy.py tests/sources/test_eccc_gridded.py`
