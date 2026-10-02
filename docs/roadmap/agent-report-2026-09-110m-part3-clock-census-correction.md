# 110m part 3 — private clock census correction

**Verdict: PASS after correction.** This supplements the published
[part 3 report](agent-report-2026-09-110m-part3-paper-maker-decouple.md) and
explicitly corrects its clock census. The first scan counted public `utc_now`
definitions only. The audit's totals include private `_utc_now` definitions:
the integration base has 32 datetime definitions including the shared owner
(28 public copies and three private copies), and 15 string definitions
(nine public and six private). The earlier claim that the base differed from
the audit was incorrect.

The queue now aliases the shared clock. Geographic eligibility and captured-input
parity retain their private validation wrappers, with the default clock delegated
to `weather.time.utc_now`. An injected naive or invalid geographic clock still
raises `CLOCK_NOT_UTC_AWARE`; a naive parity timestamp still raises
`now must be timezone-aware`. These checks must precede normalization. All 31
duplicate datetime clock sources now route to the one shared implementation.
The 15 string-returning clocks remain separate. Private names and patch points
are preserved.

The definition ratchet now covers both names and explicitly checks that the two
validation wrappers delegate their fallback without reading another clock.
Fixture controls exercise invalid values, naive timestamps, offset conversion,
shared fallback and alias identity. The full geographic-eligibility, parity and
snapshot-batch files plus the helper tests and all four repo audits completed
through `workstation_heavy.ps1`: **94 passed in 28.18 s**. The audits include
maker-core import boundaries. The previous 1,406-pass broader run remains evidence
for the other helper moves; it predates this small correction.

Base remains integration `8180404a0`. No production inputs, credentials, local
exclude/settings files, Scheduler changes or venue calls were used.

| File | Roll classification |
| --- | --- |
| `src/weather/collection/triggered_snapshot_queue.py` | Conservatively roll-sensitive; capture worker dependency |
| `src/weather/market/mm_geographic_eligibility.py` | Conservatively roll-sensitive; live eligibility dependency |
| `src/weather/reporting/scorecards/captured_input_parity_evidence.py` | Conservatively roll-sensitive; shared parity dependency |
| `tests/market/test_neutral_execution_helpers.py` | Roll-free |
| `docs/roadmap/agent-report-2026-09-110m-part3-clock-census-correction.md` | Roll-free |
| `docs/roadmap/correspondence-index.md` | Roll-free |

Production must obtain its mechanical `roll_verdict.ps1` verdict and follow the
existing integration procedure. This correction requires source adoption only.
