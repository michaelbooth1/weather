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

The stored numeric diagnostics are `nbm_prob_tmax_parser_version`,
`nbm_prob_tmax_valid_hour_utc`, `nbm_prob_tmax_cycle_age_hours`, and
`nbm_prob_tmax_maximum_period_flag`. An unavailable/incomplete maximum has
flag zero; absent provenance stays null, never inferred from a capture date.
They belong to `FEATURE_DIAGNOSTIC_COLUMNS`, carried into live feature records,
audit rows and captured-input feature replay, never to `FEATURE_COLUMNS` or
the NBM source-gate predictor lists. They are filter/provenance fields, not
selectable predictors. The centrally versioned feature-row schema changes
because its persisted diagnostic columns change; the trained NBM input list
remains the original 15 names. Feature extraction must not mutate captured inputs.
When capture supplies `cycle_age_at_use_hours`, the feature-row age diagnostic
uses it; otherwise it retains the parser's original-capture age. This permits
cross-pass reuse to record current age without rewriting frozen raw provenance.

A malformed, naive or pre-issue capture timestamp raises `NBPClockError` during
replay. The live fetch catches that specific error, returns unavailable with
`nbp_capture_time_invalid`, `nbp_capture_time_naive` or
`nbp_capture_time_before_issue`, and retains the full raw payload and selected
token provenance. A bad clock must not escape the live source call or supply
temperature values.

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

The real forecast manifest's parser version, issue cycle, provider valid time,
station/target identity and retained national bytes suffice to derive period,
group/token and all seven raw TXN values by versioned replay. No redundant
token columns are required in that manifest. Capture minus issue determines
cycle age; existing feature diagnostics retain floor rejection details. This
derivation does not change the writer, archived bytes, floor or admission gates.

## Offline window diagnostic

`tools.research.nbm_target_fix window --output <new-directory>` enumerates the
candidate search across all local hours in standard and daylight time. Its
`healthy_unavailable` total is computed from the emitted rows; an empty
candidate list emits unavailable healthy/fallback cycles and empty ages.
Run this diagnostic through the workstation heavy-work wrapper.

## Why 12Z, 13Z and 19Z bulletins carry no maximum for the issue date

This is the bulletin's structure, not a parser choice. The maximum for local
date D is the 12Z-06Z window labelled 00Z on D+1; it opens at 12Z on D. NOAA's
TXN rows start at the first period that has not begun at issue time:

| Issue (UTC) | First TXN token | First 00Z maximum | Holds the issue date's maximum |
| --- | --- | --- | --- |
| 00Z, 01Z, 07Z | 00Z D+1 maximum (FHR 24 / 23 / 17) | 00Z D+1 | yes |
| 12Z, 13Z, 19Z | 12Z D+1 minimum (FHR 24 / 23 / 17) | 00Z D+2 (tomorrow's) | no |

From 12Z the window for D has already opened, so the product publishes D's
minimum first and D+1's maximum next. All 44 retained 2026-09-17 station blocks
(11 stations at 01/07/13/19Z) and the 00Z/12Z KLGA controls show this, pinned by
`tests/sources/test_nbm_parser_v2_landing.py`. Parser version 1 took the first
token, which is why it read the next morning's minimum (EF 10k). So
`target_max_not_in_cycle` for D at 12Z/13Z/19Z is correct, and from 12Z the
newest NBP guidance for today is the 07Z cycle, 5-24 hours old. Fresher
same-day guidance needs another product (the hourly NBH/NBS station blocks), not
a parser change.

## Parser version identity

`NBM_NBP_PARSER_V1` and `NBM_NBP_PARSER_V2` are the recorded labels. A v2 payload,
its raw wrapper, the fetch metadata, the station archive and the feature
diagnostic `nbm_prob_tmax_parser_version` (2.0) record the version. A v1 payload
records none; replay reads an absent version as 1. The payload schema label
(`nbm_probabilistic_tmax_v0.1`) is unchanged; the parser label is the
discriminator.

## Shadow input regime (quarantine)

An artifact consumes `nbm_prob_tmax_*` values only from the parser version it
was trained on ([`nbm_input_regime.py`](../../src/weather/model/nbm_input_regime.py)).
An artifact that selects any NBM column and declares no
`nbm_prob_tmax_parser_version` is version 1. Every tracked NBM-selecting
artifact is version 1, including `feature_model_hgb_f_pooled_v0_3.pkl` behind the
headline-disabled, promotion-blocked shadow
`pooled_f_candidate_miami_current_fallback_v0_1`. When the row's recorded version
differs, all 15 NBM inputs are set to missing before prediction. Missing is a
state the artifact already saw in training (absent or floor-dropped guidance),
and no v2 value reaches it. Both the live writer (`_pooled_candidate_replay_payload`,
`trace_pooled_band_binary_probabilities`) and captured-input replay
(`build_candidate_features`) apply the guard. An unknown row or artifact version
fails closed. Live payloads and traces carry `nbm_input_regime`, and replay
diagnostics count masked rows and values. Because the decision depends only on
the stored feature row and the artifact, it is reproducible from captured
evidence without a new tape column.

This is a quarantine, not a re-version. A v2 re-version needs a refit on v2
inputs: no fit is authorized and no v2 training corpus exists yet. Retiring the
shadow would end its evidence. The shadow keeps running under its existing
restrictions. It is not fitted, promoted or re-scored. A future artifact
trained on v2 rows must declare `nbm_prob_tmax_parser_version: 2`, and it will then
mask v1 rows the same way. Training assembly must still never pool rows from both
sides of the boundary. A forecast-effect question needs its own pre-registration
on dates captured after adoption.

## Update when

Update with period rules, supported station geography, parser dispatch,
provenance fields, archive persistence or guidance-admission semantics.
