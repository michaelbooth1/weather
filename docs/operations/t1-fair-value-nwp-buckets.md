# T+1 fair-value NWP-availability breakdown

Status: canonical CLI and output contract for the reported-only post-processor of T+1
pre-registration Amendment 3 (`docs/research/t1-fair-value-preregistration-2026-09-25.md`).
It owns the `weather.market.maker_fair_value_nwp_buckets` command only. The amendment owns
every statistical choice; the frozen scorer (`weather.market.maker_fair_value_score`, with its
contract in `docs/operations/t1-fair-value-scoring.md` on the exam line) owns `report.json`.

**Read when:** running or reviewing the Amendment 3 breakdown after the single 2026-10-15 read.
It supplies no scoring authority and never delays, repeats or alters the frozen read.

## Command

Run after the frozen scorer has written its report, on that report's directory:

```powershell
.\venv\Scripts\python.exe -B -m weather.market.maker_fair_value_nwp_buckets --report C:\reports\t1-fair-value-once\report.json
```

`--report` is the scorer's unchanged `report.json`; it is read once and never written. The
command creates `buckets.json` beside it (create-only) and prints its status. It refuses with
exit 2 when the report cannot be read or `buckets.json` already exists. When the report lacks
the fields the breakdown needs (`selected_hours[]` with `captured_at`, `lead`, `source`,
`target_date`, `market_id` and per-band `probability`, `mid`, `observed_yes`), it writes
`status: NOT_COMPUTED` with a `reason` and exits 0.

## Output

`status: REPORTED_ONLY`, the report's SHA-256, the anchors, and one cell per lead (1, 2),
clock (`gfs`, `ecmwf`, `latest_of_either`) and bucket (`[0,60)`, `[60,120)`, `[120,240)`,
`[240,360]` minutes since the latest availability at or before `captured_at`). Anchors are
the amendment's fixed engineering assumptions: GFS 03:30, 09:30, 15:30, 21:30 UTC; ECMWF
01:40, 07:40, 13:40, 19:40 UTC. Membership is the frozen pooled descriptive table's (plain
`nbp` and `fallback` sources); tied-read strata are not broken down.

Each cell carries the paired provider, mid and provider-minus-mid Brier with the frozen
aggregation (bands, then hours within market-day, then market-days equally), the frozen
crossed date x market bootstrap (10,000 replicates, seed 110, two-sided 90% percentile
intervals with valid/undefined replicate counts), the date-only sensitivity, date, market and
market-day cluster counts, event-hour and band-hour counts, per-market-day scores and the frozen
`UNDERPOWERED` rule. That aggregation is vendored from
`weather.market.maker_fair_value_statistics`; a test pins equality wherever both are present.
`assignments[]` records each member row's minutes and buckets.

No bucket is primary and no cell is compared against a threshold. The output carries the
amendment's interpretation constraint verbatim: fair value updates only on NBM cycles, so a
bucket pattern is not evidence about NWP-driven market moves.

## Update when

The CLI, its output fields, or the amendment it implements changes. A change to anchors,
buckets, membership or statistics needs a dated amendment before scoring, never an edit here.
