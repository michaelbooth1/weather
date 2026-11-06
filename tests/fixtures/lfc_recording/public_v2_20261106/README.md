# Public Data API v2 recording shapes

Captured with exactly one unauthenticated GET per endpoint and the explicit
`weather-lfc-recording/1` User-Agent. `provenance.json` records request URLs,
observation times, statuses and exact response SHA256 values.

The condition comes from the retained Los Angeles 2026-09-21 stage-2 fixture.
The activity query uses the public synthetic fixture account address, REWARD
only, and the 2026-09-20 UTC interval. It returned an empty page; item-field
tests therefore use the official OpenAPI contract rather than claiming a
nonempty activity observation. No credentials or post-embargo market data
were read. The historical resolution response lacks a payout vector and must
remain pending; its price fields must never be used to invent a winner.
