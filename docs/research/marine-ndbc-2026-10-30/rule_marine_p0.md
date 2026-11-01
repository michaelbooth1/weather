# Marine market-residual P0 rule (ledger row 87)

Status: pre-declared before any download or computation (2026-10-30, lane L3).
Evidence class: free-data, kill-only history SCREEN. Nothing here is a release,
serving, capture or scheduling decision. A live marine refresh or any recorder
stays an open owner question (register S27, Q-list item 13).

## 1. Machinery

Identical to the market-residual sweep rule `docs/research/mr-sweep-2026-10-30/rule_mr_sweep.md`
(sha256 `85f8192cc260cadb9a8ec3db010016e9952515a9492de896d8907e68075b1956`) sections 1-5,
except where this file says otherwise: layout `C:/swarm/v3layout`, burn-in
2026-08-01..08-14, scored 2026-08-15..09-29, e = y - m, market moments with the
sigma^2 floor 0.25, type D band signal s_b = sign * g_z * (z_b - mu_m) / sigma_m with
g_z z-scored within market over the covered fit snapshots, the exponential tilt,
the calibration-matched disagreement placebo (`market_blend.placebo_vector`,
derangement within (market, hour), J = 20 seeds 20260921+j), Delta = rho_c - mean
rho_pl, B = 10,000 date-cluster bootstrap draws with seed 20261024, one-sided p,
UNTESTABLE below 20 covered dates or 1,000 snapshots, per-date rows with the six
sufficient sums.

## 2. Population

The sweep's fit and score tables restricted to markets
{san-francisco, seattle, los-angeles, nyc, miami, houston} and to snapshots whose
local hour is 07..12 inclusive. Toronto, chicago and every inland market are out.
No data after 2026-09-29 is read for any market.

## 3. Candidates (K = 2, both type D)

| id | value | sign | mechanism |
| --- | --- | --- | --- |
| MAR-SST | latest water temperature, degC | + | warmer water, warmer coastal max than the market prices |
| MAR-ONSHORE | latest wind speed in m/s when the wind direction lies inside the market's registry onshore sector (inclusive), else 0; missing when speed or direction is missing | - | onshore flow caps the coastal max below the market |

Onshore sectors are the in-repo `MARINE_CONTEXT_REGISTRY` sectors
(`src/weather/sources/marine_context.py`), unchanged.

## 4. Stations and the as-of value

- Per market, the station priority list is the registry order (nyc: CO-OPS
  8518750, then NDBC 44065; every other market its single CO-OPS station).
- An offshore NDBC secondary is appended after the registry stations only for a
  variable that S1 shows the primary lacks (at least half the hours missing over
  2026-08-01..09-29), and only after its NDBC metadata confirms it reports that
  variable. Any such addition is recorded as a row 87 amendment, with its reason,
  before P0 compute. S1 reads marine observations only, never labels or prices.
- For a snapshot captured at `captured_at_utc` and a lag L, a station's
  qualifying observation is its latest one with obs_utc + L <= captured_at_utc
  and obs_utc >= captured_at_utc - 6 h. The value is taken from the
  highest-priority station with a qualifying non-missing observation of that
  variable; SST and wind may come from different stations. No qualifying
  observation means the snapshot is uncovered for that candidate.
- CO-OPS is read in GMT and metric units; NDBC stdmet is UTC. Both are outside
  EF §10w (not Open-Meteo hourly-derived).

## 5. Lags and decision

- L = 90 min is primary and L = 180 min is the sensitivity; both are gates, for
  NDBC and CO-OPS alike.
- At each lag, BH at q = 0.10 over the K = 2 candidates. A candidate survives at a
  lag iff it is testable, BH rejects and the Delta 95% lower bound is > 0.
- A candidate SURVIVES P0 only if it survives at both lags. Otherwise it is a
  KILL (or UNTESTABLE if untestable at either lag).
- The w gate of the sweep rule runs only for a survivor, at L = 90. LOYO history
  comes only after a survivor, under a new ledger row.
- One run. Outputs: a receipt JSON with both lags, per-date rows JSONL, and a
  features file carrying, per snapshot and candidate, the value, the station and
  its obs_utc.
