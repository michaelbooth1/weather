# 95d retained public inventory

Historical evidence from the September 24, 2026 desk study. Read the
[mission report](../agent-report-2026-09-95d-weather-market-universe.md) for the
verdict and limitations. Nothing here is a registration or trading instruction.

| File | Meaning |
| --- | --- |
| `summary.json` | Counts, scope cutoff, discovery pagination, errors, reward totals, raw-input hashes |
| `families.json` | One row per normalized family; scores, source URLs, stations, units, liquidity, proposal and supporting event link |
| `families.md` | Complete human-readable bucket table, with a reason for every family |
| `events.csv` | One row per Gamma event; exact geography remains in title/slug and source URLs |
| `markets.csv` | One row per Gamma market/band, including condition ID, reward parameters and reported fee metadata |
| `excluded.csv` | Non-weather matches removed after discovery; retained for audit |
| `book_samples.json` | Public condition-reward records and derived YES/NO book metrics, with individual retrieval timestamps |
| `forecast_probes.json` | Public Open-Meteo responses for the proposed cities and the rejected Zhengzhou comparison |
| `source-read-notes.json` | Public-page feasibility observations; these are notes, not retained settlement prints |
| `roll-verdict.txt` | Workstation verdict-tool output; live closures are absent |
| `SHA256SUMS.txt` | Hashes of the evidence files, excluding this checksum file |

Generator: `tools/weather_market_universe.py`. UTF-8 CSV uses JSON strings for
nested lists/objects; empty CSV cells and JSON null mean unavailable, not zero.
Gamma market IDs and CLOB condition IDs are different keys. Forty-four draft
markets lack condition IDs and are never included in reward totals.

`asof` fixes the 60-day inclusion cutoff and local-date opportunity filter. It
does not make sequentially retrieved observations simultaneous. Closed events
qualify by actual `closedTime`, not scheduled `endDate`. First/last seen refers
only to this crawl; venue creation and target dates are separate fields.

Reward rates are the current shared pool, summed once per distinct condition
and asset. Historical reward rates are unavailable. A current zero means no
configured rate found in the returned current records; a null historical rate
does not mean the market never paid. `min_sizes` are shares and maximum reward
spreads are cents. Book prices/spreads are probability dollars, depth is shares.
YES/NO books can mirror liquidity; do not sum them as independent capital.
Depth within reward distance uses raw BBO midpoint, not the venue's adjusted
midpoint or a maker-specific Q-score. `market_competitiveness` is the public
API field, not a probability or our reward share.

Rolling volumes are exactly the fields Gamma supplied. Most closed event rows
lack them. Family `volume_*_reported_sum` sums distinct event fields once and
is **partial whenever `volume_*_complete` is false**. It is not a reconstructed
7/30-day trade total. Book medians are cross-sectional samples, not temporal
typical spreads. Listing lead is measured from Gamma `startDate` to local
target midnight; available lead days are a single local-date snapshot.

For daily temperatures, `unit` is the registry native settlement unit and
`rule_station_ids` independently extracts identifiers from rule URLs. For other
families, `units_mentioned_in_rules` is a search aid: rules can mention several
units or fallback sources. Exact primary quantity, station/gauge, precision,
cutoff and revision policy must be read at the representative rule/source URLs
before implementing an adapter. Rule hashes bind the retained raw description.
The latest eligible event represents current family rules; mixed current
source regimes are explicitly labelled. Individual event source fields preserve
historical source changes.

Scores are ordinal triage judgements, not fitted estimates. Reward score is
zero for a zero pool, otherwise 1 plus thresholds reached at 10, 50, 200 and
500/day (maximum 5). Higher feasibility is better; higher build cost and risk
are worse. Risk is raised to at least 4 when a sampled spread exceeds 9 cents.
No-live-event families receive zero feasibility/build/risk because no current
capture is proposed; this is not evidence of safety. The 0.1 GiB/day/family
storage figure is a handoff planning assumption, not measured disk usage.

Rebuild reads ignored `data/research/weather-universe-20260924/` only. That
cache is retained on the producing workstation and **does not exist in a clean
clone**. `verify` checks the committed portable inventory without it. To repeat
discovery later, use a new cache directory; immutable cached URLs deliberately
preserve the original snapshot rather than refreshing it.
