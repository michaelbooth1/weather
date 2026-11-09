# Public expansion fixtures

The `inputs/` files are the master's T046 public market-rules, station and
72-hour METAR survey supplied on 2026-11-08. Text is normalized to UTF-8/LF;
the rules JSON uses Unicode escapes to preserve the supplied strings while
avoiding literal C1 control characters already present in the survey.
generator provenance hashes refer to those checked-in bytes. These raw weather
and bin-format fixtures are authorized by T046; no price, ledger or maker tape
is included or read. They are not forecast-evaluation or edge evidence.

The supplied map omits HKO; its metadata comes from the existing location
registry. Families are derived from the actual per-city rules, including
highest-only cities. The inputs identify three non-METAR cities; the prompt's
"49 of 51" count is inconsistent with those exceptions.

`legacy_venue_functions.py.txt` freezes the two extracted legacy functions at
base `73140b20eed0f81c8fa26bb5faf6defcb269533a`, solely as a test oracle.
`legacy_market_registry.sha256` pins the normalized UTF-8 source of the built-in
registry at that base. Neither fixture is imported by production code.
