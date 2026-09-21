# NBM target-period and parser provenance contract

Status: source contract. Read when parsing, persisting, replaying or admitting
NBP maximum-temperature guidance. The source owner is
[`nbm_probabilistic_tmax.py`](../../src/weather/sources/nbm_probabilistic_tmax.py).
This contract does not certify deployment; qualification evidence belongs in
the [83a handback](../roadmap/agent-report-2026-09-83a-workstation-read-the-guidance-for-the-right-day.md).

## Period identity

NOAA's [NBP key](https://vlab.noaa.gov/web/mdl/nbm-textcard-v5.0) labels a
maximum at 00Z and a minimum at 12Z. The maximum covers 12Z on the daytime
date through 06Z the next day. It is supporting guidance, not a local-midnight
settlement extreme or an observation. The qualified mainland station map in
the source binds station IDs to the registry's US timezones. The window start
and 00Z label must agree on a station-local date; that date is the target.
Unknown stations and ambiguous assignments are unavailable.

Parser version 2 inspects both tokens of every FHR group, accepts exactly one
00Z maximum for the target, and requires TXNP1/2/5/7/9, TXNMN and TXNSD at
that token. Missing rows/tokens, provider -99 and negative standard deviation
are rejected. No target maximum yields `target_max_not_in_cycle`, never a
substitute minimum or next day's maximum. The unchanged version-1 rule is
available explicitly as `parse_nbp_station_tmax_v1`.

The target-aware search considers the evidenced complete-TXN issue hours in
`NBM_NBP_TXN_CYCLES`, newest first, within the existing 24-hour lookback.
Before 12Z the first maximum belongs to the issue date; from 12Z it belongs
to the following date. Station completeness remains a parser check. Fetch
coalescing and shared-CAS byte deduplication alone do not prove reuse across
capture passes or a two-hour network-download budget.

## Payload and feature fields

The normalized payload and station raw wrapper record `parser_version`;
`issued_at` and `valid_time_utc`; `period_kind`; zero-based `group_index` and
`token_index` within that group; `forecast_hour`; `station_timezone`; and
`cycle_age_hours` (original capture time minus issue time, not current wall time).
Age is null without a captured timestamp. `raw_values` retains all seven TXN
values, including rejected sentinels. `value_rejection_reasons` maps row codes
to a reason or null. The filtered percentile/mean/spread fields keep their
existing names, Fahrenheit units and numeric types. The observation-floor
filter remains a subsequent, unchanged feature step; its existing
`guidance_impossible_features` records which values it removed.

The numeric feature additions are `nbm_prob_tmax_parser_version`,
`nbm_prob_tmax_valid_hour_utc`, `nbm_prob_tmax_cycle_age_hours`, and
`nbm_prob_tmax_maximum_period_flag`. An unavailable/incomplete maximum has
flag zero; absent provenance stays null, never inferred from a capture date.
The feature schema is versioned centrally; estimators continue to select their
trained feature names. Feature extraction must not mutate captured inputs.

Future training or evaluation may count a row as corrected NBP guidance only
when all these provenance fields are present, parser version is 2, UTC valid
hour is zero, age is nonnegative, and the maximum flag is one, with the payload
station/target/period binding verified. Availability, cutoff, physical-floor,
release and ordinary corpus admission gates still apply. Historical unversioned
rows exclude themselves from that guidance population. This is not a model
fit, a candidate proposal, permission to score these dates, or permission to
relax an existing gate.

## Replay and archive

Shared-payload and station-archive replay dispatch by the recorded parser
version; no version means version 1. Unknown versions fail closed. Migration
passes the recorded version through without rewriting retained bytes. The
station archive adds parser/period/group/token/age columns and refuses to append
to an older CSV header; start a new archive root rather than rewrite evidence.
Archive identities include the parser version. Repeated captures preserve the
first retained wrapper and capture time; neither a repeated fetch nor parsing
the same bulletin under another version may overwrite its original bytes.

Persistence must retain token provenance and raw versus floor-filtered values
and rejection reasons in the forecast manifest as well as in the payload.
The source wrapper alone is insufficient: national-body CAS strips wrapper
metadata. Do not treat a parser-only change as completion of that contract.

## Shadow input regime

The owner-authorized NBM repair is an input-regime boundary for the active,
headline-disabled, promotion-blocked legacy validation shadow. Its identity
comes from the variant registry and trained selectors, not a new candidate.
Rows on opposite sides of the parser boundary must never be pooled. The
shadow continues under its existing restrictions; this repair does not retire,
fit, promote or re-score it. A later forecast-effect question requires its own
pre-registration on dates captured after adoption.

## Update when

Update with period rules, supported station geography, parser dispatch,
provenance fields, archive persistence or guidance-admission semantics.
