# Workstation handoff 2026-09-95d — the full Polymarket weather-market universe, triaged

Written 2026-09-24 by the production agent. Owner request: "The markets we are tracking are just a selected subset … time to
think about what else is worth tracking. Get ALL weather markets on Polymarket and sort them into buckets: worth ingesting now,
worth ingesting later, not worth trying." Serves the multi-domain maker goal (forward-plan decision 5) and Q-01/Q-05. Research
only; nothing is ingested, registered or traded by this mission.

## 1. Context — start from this, do not re-derive it

- We track 12 configured markets (11 US °F cities + Toronto °C): `config/locations.json`, `config/location_market_events.json`,
  `src/weather/market/market_registry.py`. The owner has seen active international temperature markets we do not track (e.g.
  Paris °C, Qingdao °C).
- Pillar B economics (EF §10a, §10m, §10n): rewards are per band per day (~25-30/day on a rewarded T+1/T+2 band); other makers
  arrive within minutes; the cash limit applies **per market**, so more markets means more capacity for the same cash.
- Hard constraints: International Polymarket only; **no paid weather data** (free sources only: METAR/IEM, NWS/NBM, ECCC,
  Open-Meteo free tier, national met services' free products); native settlement units; the settlement source named in each
  market's rules is what matters.

## 2. Discover (public, read-only, throttled to one request per second per host; cache under ignored `data/`)

Enumerate **every** active and recently closed (last 60 days) weather-related event and market on International Polymarket via
the public Gamma API (tags/categories and text search: temperature, highest/lowest temperature, rain/precipitation, snow,
hurricane/storm, heat, climate/global temperature, etc.) and the CLOB public reward records (`/rewards/markets/<condition>`).
For each **event family** (e.g. "highest temperature in <city> on <date>"), record: cities/regions, unit, recurrence (daily?),
bands per event, typical lead time (T+0/T+1/T+2 availability), settlement source and station named in the rules, reward rate,
`min_size`, `max_spread`, 7- and 30-day volume, typical spread and displayed depth, `market_competitiveness`, negRisk flag,
and first/last seen dates.

## 3. Score each family

1. **Reward opportunity:** reward rate x bands x days available; depth and competition (share we could plausibly hold).
2. **Data feasibility (free only):** is the settlement source readable free and in time (station METAR/SYNOP, national service
   page)? Is there a free forecast/guidance product for that location (NBM is US-only; Open-Meteo free global; ECMWF/ICON open
   data)? Local timezone and cutoff semantics; unit.
3. **Build cost:** fits the current registry/plugin model directly (same shape as our 12) vs new market type (rain totals,
   storms, global anomalies) needing new settlement logic; capture load (~0.1 GiB/day per family estimate from 88a; the
   production disk is the binding resource).
4. **Risk:** settlement ambiguity (source changes, manual resolution), thin or manipulable books, known disputes.

## 4. Buckets and deliverables

Sort every family into **Ingest now** (same shape as today's markets, free settlement data, rewarded, capture cost small),
**Ingest later** (valuable but needs new settlement or data work — say what), or **Not worth it** (say why). For "Ingest now",
give the exact registry/config additions it would need (city, station, timezone, unit, source) as a proposal, not an edit.

Branch `codex/weather-market-universe-20260924` from `origin/master` (push authorized): a `tools/` discovery script that
rebuilds the inventory from the cache, a machine-readable inventory (CSV/JSON under `docs/roadmap/` or the report's evidence
folder), and `docs/roadmap/agent-report-2026-09-95d-weather-market-universe.md` (verdict first; the bucket table with the
reason for each; total reward opportunity now vs if "Ingest now" were added; the capture/disk cost; open questions). No
`.env`, no credentials, no authenticated or order endpoints, no config or registry edits, nothing heavy while an RE-1 session
is running.
