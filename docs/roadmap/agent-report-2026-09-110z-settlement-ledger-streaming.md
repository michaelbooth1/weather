# Agent report 110z follow-up: settlement route streams production-size ledgers

**Verdict: DONE (fixtures only).** The wallet reader's `/settlement` route no longer refuses
settlement ledgers above 64 MiB. Each location's `ledger.jsonl` is now streamed once per request
with no size cap, in memory bounded by a 1 MiB per-line limit plus one row per requested event.
A synthetic 70 MiB ledger (over the old cap) resolves correctly with a measured `tracemalloc` peak
below 4 MiB. **Roll:** expected roll-free, but the production host must confirm it. On the
workstation `roll_verdict.ps1` returns UNDECIDABLE because there is no live closure evidence there.

Branch `codex/ledger-cap-20261001`, from `origin/master` `819f8148`. Follow-up to #130
([110z part 2 report](agent-report-2026-09-110z-settlement-route.md)).

## Problem

After #130 landed, `ledger_label` returned `proxy_ledger_too_large` for every production location
ledger (90-105 MB) because of `LEDGER_MAX_BYTES = 64 MiB`. The route also re-read the whole ledger
once per market, so lifting the cap alone would have cost one full 100 MB scan per held or
filled market on every request.

## Change

`src/weather/market/wallet_reader_settlement.py`:

- New `ledger_labels(root, location_id, event_slugs)`: one binary pass using
  `readline(LEDGER_LINE_MAX_BYTES + 1)`. A line over the limit is skipped and the rest of it is
  drained in limit-sized reads, so one unterminated or huge line cannot grow memory. Latest-revision
  selection is unchanged: highest integer `revision_number`, with file order as the tie-break.
- Byte prefilter: venue slugs match `[a-z0-9-]`, which JSON never escapes, so a line is parsed only
  when it contains a requested `"<slug>"`. Any other slug shape falls back to parsing every line.
- `ledger_label` keeps its signature and statuses. It is now a wrapper over `ledger_labels`.
- `settlement()` groups event slugs by location and scans each location ledger once per request.
- `proxy_ledger_too_large` no longer exists. A matching row longer than 1 MiB is skipped rather
  than buffered. Real ledger rows are a few hundred bytes.

Runbook: `docs/operations/wallet-reader.md` §settlement replaces "(64 MiB cap)" with the new bound.

## Tests

`tests/market/test_wallet_reader_settlement.py`:

- `test_ledger_over_the_old_64_mib_cap_streams_in_constant_memory`: writes a ledger of more than
  70 MiB. The target event's revision 1 is the first line, about 70 MiB of other-event filler
  follows, then revision 2 and a second event. The test asserts the latest revisions, a
  `tracemalloc` peak under 4 MiB, and `proxy_label_absent` for an unknown event.
- `test_overlong_ledger_lines_are_skipped_not_buffered`: sets the limit to 256 bytes. A line of
  exactly 256 bytes is accepted. An over-long matching row with a higher revision is skipped, both
  mid-file and unterminated at EOF. A non-venue slug exercises the no-prefilter path, and the
  absent-ledger status is checked.

Run under `scripts\ops\workstation_heavy.ps1`, serially, with `--basetemp` (deleted afterwards):
the settlement and wallet-reader tests plus the schema-registry, import-architecture,
release-import-boundary, agent-docs, path-policy and module-size audits returned **237 passed**.

## Roll evidence (static; production decides)

`wallet_reader_settlement` is imported only lazily, from `WalletReader.settlement` in
`wallet_reader.py`. No capture supervisor imports `weather.market.wallet_reader*`; the only other
importer, `cockpit_snapshot`, reaches `wallet_reader_client` and `wallet_reader_security`, which are
unchanged. The production agent should run
`scripts\ops\roll_verdict.ps1 -Branch origin/codex/ledger-cap-20261001`. The owner restarts the
reader to adopt the change.

## Boundaries

Fixtures only. No production data, credentials, venue calls or Scheduler changes. Nothing places,
cancels or signs orders. Not merged.
