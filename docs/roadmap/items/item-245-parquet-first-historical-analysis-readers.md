# 245. Parquet-First Historical Analysis Readers [OPEN 2026-06-22 - ANALYSIS READS TEXT TAPES BY DEFAULT]

Goal: make historical analysis, reporting, and backtest readers prefer the
validated Parquet archive for closed market-days while preserving existing
CSV/JSONL behavior for live or unarchived days.

Source: Items 243 and 244 create the archive contract and conversion path. The
storage audit found that most local bytes are useful historical market and
weather evidence, but many reports still read heavy text tapes directly. That
forces repeated parsing of large CSV/JSONL files and makes historical analysis
depend on the least compact representation.

Why this matters: converting data is not enough if every analysis path keeps
reading the original text files. The project needs a single reader boundary
that can choose Parquet for closed history, fall back to text for active days,
and expose identical rows to downstream model, replay, and audit code.

## Design

1. Add archive-aware reader helpers for heavy snapshot artifact families, with
   a consistent preference order: validated Parquet, gzip-tiered text where
   supported, then current CSV/JSONL.
2. Keep the reader API compatible with existing reporting/backtest call sites;
   callers should not need to know whether a closed day came from Parquet or
   text unless they request provenance.
3. Add provenance fields to reader summaries: source mode, archive manifest
   hash, source file hash, row count, and fallback reason.
4. Evaluate DuckDB as an optional query engine for cross-market historical
   queries, but do not make it mandatory until dependency and packaging policy
   are explicit.
5. Migrate the highest-byte readers first: source-family inventory, snapshot
   evaluation, market microstructure/CLOB analysis, replay input loading, and
   promotion-corpus scans.
6. Add parity tests comparing Parquet and text results on representative
   market-days.

- [ ] Add archive-aware reader helpers for normalized snapshot/CLOB tables.
- [ ] Add provenance/fallback reporting for Parquet versus text reads.
- [ ] Update high-byte historical reports to use the shared readers.
- [ ] Add parity tests for Parquet-backed and text-backed rows.
- [ ] Decide whether DuckDB is an optional local tool, a pinned dependency, or
  only documented operator tooling.
- [ ] Add an operator query example for historical Parquet analysis without
  loading the full snapshot tree into memory.

Acceptance: closed historical analyses can run from Parquet by default with
matching row-level results versus text fixtures; live and unarchived days still
read from the existing `data/snapshots` layout; reports expose which source
mode was used; and dependency policy for DuckDB-style querying is documented.

Related: items 124, 146, 154, 203, 239, 243, 244.
