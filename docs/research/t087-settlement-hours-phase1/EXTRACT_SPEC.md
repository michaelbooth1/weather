# T087 — master-only minimal extract

Copy to a new `minimal_extract.json` for Phase 2 only. Local target dates:
**2026-10-23 through 2026-11-09 inclusive**, all 12 built-in market IDs below.
For each D, observations only in **[D-1 21:00 local, D+1 00:00 local)**,
using the market's IANA zone and observation instant. Thus the earliest local
observation is 2026-10-22 21:00; the last is before 2026-11-10 00:00.
Keep both repeated hours on 2026-11-01. Never filter by UTC date alone.

| market_id | label station | IANA zone |
| --- | --- | --- |
| toronto | CYYZ | America/Toronto |
| nyc | KLGA | America/New_York |
| atlanta | KATL | America/New_York |
| austin | KAUS | America/Chicago |
| chicago | KORD | America/Chicago |
| dallas | KDAL | America/Chicago |
| denver | KDEN | America/Denver |
| houston | KHOU | America/Chicago |
| los-angeles | KLAX | America/Los_Angeles |
| miami | KMIA | America/New_York |
| san-francisco | KSFO | America/Los_Angeles |
| seattle | KSEA | America/Los_Angeles |

Only these JSON fields:

| Level | Required field | Exact contents / source |
| --- | --- | --- |
| top | `schema` | Literal `t087-minimal-v1` |
| top | `through` | Literal `2026-11-09` |
| top | `days` | Array, one object per available requested market-date; no other dates |
| day | `market_id` | ID in table |
| day | `target_date` | ISO local target date in stated range |
| day | `resolution_source_url` | The event's exact dated Gamma `resolutionSource`; retain `ids`, `format`, `date`, `hours` |
| day | `bands` | Array of that event's complete `markets[].groupItemTitle` band labels, including tails, in native units |
| day | `paid_band` | Label of the unique final Gamma YES-paid band; null if not final/unambiguous |
| day | `complete` | true only when the scoped routine observation extract is complete for this station-date; otherwise false |
| day | `observations` | Array of the following observation objects, preserving source order for revisions |
| observation | `valid` | CSV `valid`, converted from documented IEM UTC to offset-bearing ISO UTC (`Z` or `+00:00`); do not use reportTime |
| observation | `metar` | CSV `metar` raw report, unchanged |
| observation | `declared_report_type` | Integer 3 only from the documented IEM routine-only request; null if source declaration is unknown |

Optional fields, only if actually recorded and needed: observation
`receipt_time` (offset-bearing ISO UTC); day `next_routine_time_utc` (the
next local date's first routine observation timestamp, timestamp only, for a
recorded COR receipt deadline). IEM normally supplies neither; omit them.

Observation source paths relative to the capture host's `weather.paths.REPO_ROOT`:

1. `data/venue_rule_labels/runs/<completed-utcRunId>/<icao-lower>/routine/asos_routine_<start-ISO>_<through-ISO>.csv`,
   from one complete adequate run; or
2. `data/venue_rule_labels/metar/<icao-lower>/routine/asos_routine_<start-ISO>_<end-ISO>.csv`.

Use the run receipt/manifest to identify the exact source file. The documented
initial file is `asos_routine_2026-10-22_2026-11-03.csv`; do not assume it
covers all requested dates. Copy only the two CSV columns and scoped rows,
not the source files. Do not fetch missing weather. Mark unavailable days
incomplete or leave absent; the analysis lists omissions/refusals.

Gamma source, read by master: `/events/slug/<event-slug>`. Use only final
resolved status and terminal payouts to identify the paid band; do not use
the repo helper's >0.5 live-price heuristic. Export the labels and dated
source link above, no payout/probability arrays or whole response. If a dated
link is missing, do not infer its timestamp/hour count from another event.

The observation ceiling is the target date's end even when the source link
ends later. Copy no next-morning temperature, no earlier evening, no WU
fallback, tmpc, price, model output, own-session record or other field.

Master's separate read receipt: real extraction timestamp, actual absolute
source paths, source file byte sizes/hashes, each copied field/date range,
Gamma event identity and finality check, missing keys, extract SHA-256, and
the named owner scope. Keep that receipt separate from the minimal JSON.
Log the read before launching Phase 2.
