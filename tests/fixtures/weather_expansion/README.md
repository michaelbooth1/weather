# Expansion format fixtures

The tracked `inputs/metar-72h/` corpus is **seeded synthetic data**, dated
2026-09-20 through 2026-09-23 UTC. It contains no real survey observations.
The directory name is retained for compatibility. Generate it from the repo root:

```powershell
python tests/fixtures/weather_expansion/make_synthetic_metars.py
```

`make_synthetic_metars.py` uses a fixed seed and `metar_quirks.json`, which
contains station cadence and format classes only. Temperatures and dew points
are generated independently of real days. Named cases add parser regressions
such as malformed groups, stationless lines, unreadable times, the UUWW
TAF-like token and sea-state groups. Their values are constructed test inputs.
`provenance.json` pins the generator, inventory and every generated payload;
`summary.csv` describes the synthetic streams, not real report totals.

The original 72-hour real survey is embargoed label-determining text. It was
moved byte-for-byte to ignored local
`data/fixtures/weather_expansion_real/metar-72h/`. It must not be committed.
The optional real-survey test checks **format inventory only**, computes no
daily extrema or labels, and explicitly skips when that archive is absent.
It also skips by default when present; an authorized format audit opts in with
`WEATHER_EXPANSION_REAL_FORMAT_AUDIT=1`. This test-only opt-in is not authorization.
Normal parser and settlement tests use the synthetic corpus. Real-data reads
still require the applicable named authorization; file presence grants none.

The branch's earlier commits contain the old survey. Integration must use the
master's authorized squash of the final tree; branch history is not rewritten.

The other `inputs/` files are public rule, bin-format and station metadata.
They contain no observation, resolved outcome or price payload. Rule sample
dates and source query URLs are rule metadata, not captured weather values.
Text is normalized to UTF-8/LF; the rules JSON uses Unicode escapes to preserve
supplied strings without literal C1 control characters. Universe-generator
provenance still binds these unchanged metadata bytes. These fixtures are not
forecast-evaluation or edge evidence.

The supplied map omits HKO; its metadata comes from the existing location
registry. Families are derived from the actual per-city rules, including
highest-only cities. The inputs identify three non-METAR cities; the prompt's
"49 of 51" count is inconsistent with those exceptions.

`legacy_venue_functions.py.txt` freezes the two extracted legacy functions at
base `73140b20eed0f81c8fa26bb5faf6defcb269533a`, solely as a test oracle.
`legacy_market_registry.sha256` pins the normalized UTF-8 source of the built-in
registry at that base. Neither fixture is imported by production code.

`hko_daily_extract_202001.xml` is the named official Daily Extract endpoint's
development-date response, fetched 2026-11-09. The endpoint serves JSON despite
its suffix. Its Absolute Daily Max/Min columns are a parser schema fixture;
they are not evidence of an initial publication or of trading performance.

The synthetic shortened-T and dew-sign regression cases intentionally document
a strict-versus-legacy bucket divergence on synthetic KDEN 2026-09-21. This is
not a real label change or evidence about any forward-test day.
