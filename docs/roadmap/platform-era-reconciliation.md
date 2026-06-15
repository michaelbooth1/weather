# Platform Era Reconciliation (2026-06-06)

Since the 2026-05-31 deep dive the project changed shape: it is no longer a
single-Toronto system. It now serves **12 markets** (1 Celsius: Toronto;
11 Fahrenheit: NYC, Atlanta, Austin, Chicago, Dallas, Denver, Houston,
Los Angeles, Miami, San Francisco, Seattle) — "foundations for all Canada + USA
Polymarket high-temperature markets," the first milestone. Work landed that
supersedes parts of items 18-19:

- **Declarative market registry** (`src/market_registry.py`): a market is a
  config entry (slug, station, geo, tz, unit, source set). Adding one needs no
  engine changes.
- **Native-unit operation (the C/F split)**: each market runs end-to-end in its
  settlement unit, with per-unit model artifacts (`*_f`). This replaced an
  earlier canonical-Celsius approach that leaked probability across the 2°F
  bands.
- **Per-market data layer**: WU history + Open-Meteo forecast archive + live
  sources, all under `spec.data_root`, in native units.
- **Timezone correctness**: `spec.tz` is now threaded through serving and
  backfill. It had been a global Toronto constant that silently put the 8
  non-Eastern cities on the wrong clock (day boundaries + intraday cutoff) in
  both history and live serving — found and fixed in the 2026-06-06 design audit.
- **Improvement engine** in place: replay corpus, settlement backtest (item 20),
  per-location trust score, forecast-vs-realized tracker, market-day labels.

Open architectural finding from the audit: **C vs F is an I/O concern (band unit
+ granularity), not a model/training axis.** Features, training, and calibration
should be shared; only band parsing (in) and discretization (out) differ. Today
the F model is trained on NYC alone and served to all 11 F cities (climatology +
floors rescue out-of-range cities like Seattle/Denver). The two tracks below take
the data layer and the model from this bootstrap to production.
