# Workstation Maker-Execution Economics Reduction

Date: 2026-09-16

Branch: `codex/workstation-maker-economics-reduction-2026-09-92a`

Source commit: `c932b54f8747df5cdefc4cc42f8454b6797f09ae`

Source tree: `6df5bac16d8c780c35b4601941eaca1137ea7070`

## Verdict

`NEEDS_EXACT_PRODUCTION_EXPORT`

The frozen workstation mirror cannot produce complete, trustworthy maker
execution economics. It has 2,916,117 quote-intent rows and large public book,
websocket, and token archives, but it has exactly zero maker fill rows, zero
authenticated-fill artifacts, zero exchange-reconciliation artifacts, and zero
canonical execution-tape trade/gap/status artifacts. Its maker runs are legacy
Polymarket US compatibility evidence or carry no platform identity; none is
identified as International Polymarket. Calculating realized spread, markout,
inventory, fees, incentives, or net P&L would therefore require a prohibited
fill reconstruction, a fee/rebate assumption, or post-freeze production data.

The P0 stop rule fired before any economic analysis, fill simulation, settlement
join, bootstrap, power calculation, or profitability classification. No
`PROFITABLE_SIGNAL`, `LOSS_SIGNAL`, or `INCONCLUSIVE` economics result exists.

The exact compact export contract is
[maker-economics-production-export-spec-2026-09-92a.json](maker-economics-production-export-spec-2026-09-92a.json).
It caps the complete export at 64 MiB and 128 files and requests selected raw
own-account evidence plus production-side reductions and complete source-file
hash receipts, not the 500+ GB production tree.

Export-spec bytes: 22,586

Export-spec SHA-256:
`2139f7b73bdbf598f33c48d600bc1377350b7276a1b269e7bdcf1c6aed5c1275`

## Scope and immutability

The inventory used only the local frozen mirror at
`C:\Users\Michael\Documents\github\weather\data`. The mirror records a freeze
at 2026-08-12 05:03 and is not current-production evidence. The scan opened
files read-only, created no mirror-side files, did not copy any corpus, and did
not access production, a provider, an exchange, credentials, Scheduler, or a
weather model.

The mirror's own pause record documents an incomplete final mirror pass and
eight restore-verification problems. That limitation is preserved; none of the
family hashes below upgrades the mirror to complete production evidence.

## P0 inventory

Each family digest binds every selected file as the SHA-256 of UTF-8 lines
`relative/path|byte_count|file_sha256\n`, ordered by full path. The digest is a
compact inventory identity; it is not row-level economic support. No row was
admitted as an authenticated fill, so no candidate economic record was reduced.

| Family | Files | Bytes | Family binding SHA-256 | Evidence class / disposition |
| --- | ---: | ---: | --- | --- |
| Maker `run_config.json` | 375 | 3,270,930 | `287e49a07d06f322d0e04d4103b2aedd9e7dfc48abf06c55d3711a067986eaf3` | Run provenance only; 343 US and 32 blank platform identities; reject for International economics. |
| Maker `quote_intents_long.csv` | 361 | 5,495,478,695 | `038531e23da904e6bd41a0300543f951e3ee458538ec0fc14255d2bfcda5b2c3` | 2,916,117 quote-opportunity rows across 9 historical headers; not fills. |
| Maker `fills_long.csv` | 361 | 62,092 | `2e3f15d16d0724963335278c1d3d16782778ec235f90f3a1a47948ac6a2fc4c0` | Header-only in every file: exactly 0 fill rows. |
| Maker `order_lifecycle.jsonl` | 360 | 194,843,572 | `aaab38dfc6d559eb0f4ff95877299b4d53d372274ae21f601f4ff9cefe9ac8f5` | 225,822 `mm_run_v0.2` paper lifecycle rows in 30 nonempty files; not authenticated execution. |
| Maker `run_summary.json` | 361 | 82,109,892 | `6157876f0a6e7b95ad046417f57b1dcee3058e04d3d38e0840fa04c5a06f8103` | Repeated summary state; never independent support. |
| Maker scoring-projection manifests | 118 | 351,272 | `b3adc9135246c3e9baf4482cd4ef5c541ec79f058352ca938d77ff498a7814ca` | Compact quote projections; their source quote bindings do not carry complete source SHA-256 identities. |
| Book summaries | 262 | 7,238,467,719 | `d60eb753246abd5720ac54ace440a7d7f946a720794c07d3719c827804801c0d` | Public book state only; not own execution. |
| Raw book JSONL | 262 | 41,376,115,401 | `dd102b09aad73e4f5d2be5bafa93c689e31b61b6c529e3922db06ad9807dc109` | Public book state with incomplete event-manifest coverage; reject as a reconstructed fill path. |
| Plain long book CSV | 15 | 4,737,130,099 | `2e0743497e41fb6cc6dc8eb67798808ed367cdff42007496c7fbff07206e2259` | Public projection only. |
| Gzipped long book CSV | 257 | 8,542,522,208 | `a95999fae418f880df6c00dc5b29990027dd7d1c5a53463c3676730932d0708b` | Public projection only. |
| Public WS projection CSV | 146 | 807,237,438 | `ba0fb1c0bfed91cce11915e228ca8a97cc9cbcec1947322f41407a9554250b04` | Observed public state/trades; cannot prove our fills or queue. |
| Raw public WS JSONL | 146 | 5,673,498,666 | `e4bd4ee980ac6f3b581bc7e5b604d70be56d77e47b3a904081fcd2ff3b536b59` | Public evidence with no canonical continuous execution-gap ledger at freeze. |
| CLOB token CSV | 265 | 6,756,147,051 | `260c1e8631d43444724391f44eea21c102557c72a1e241082707fd0cdce61eed` | Event/token metadata only. |
| CLOB token JSONL | 265 | 12,877,159,800 | `80a5c0f9d891052f3a1ccddd0c949d7f051b9d1a7b0a187e00df11eddc2c7587` | Event/token metadata only. |
| Event-day manifests | 13 | 454,817 | `283f08e7c690634a485cc3ae3eff49ac4545f803c20c797393d8223c7ed18d8c` | Too sparse to bind the 586 snapshot namespaces as complete market-day evidence. |
| Snapshot settlement files | 290 | 5,142,838 | `acda82ee29a5057ac5d653f29122396bb0b63e2aba7ad5ecccf269ef6055bc4e` | Settlement evidence only; cannot create a fill. |
| Settlement ledgers | 12 | 250,299,220 | `1f87a32fda417730ebd1916f5ecee79a740ced92e477bc468690ebf95155116d` | Revision-rich WU settlement evidence; rows are not independent support. |

The exact absence checks were:

- `execution_tape/` directories: 0;
- canonical execution trade parts: 0;
- canonical execution gap parts: 0;
- canonical execution status files: 0;
- maker `fills.jsonl`: 0;
- maker `exchange_reconciliation.json`: 0;
- maker `mm2_pilot_report.json`: 0.

### Maker run support

- Run configurations: 375 (`mm_run_v0.1`: 1; `mm_run_v0.2`: 374).
- Run modes: 325 `paper-live-forward`; 50 `shadow`; 0 authenticated
  live-execution run configurations.
- Platform identity: 343 `polymarket_us`; 32 blank; 0
  `polymarket_global`.
- Declared support after deduplicating retries/runs to market x target date:
  58 dates, 12 markets, and 696 market-days.
- Pre-boundary support, through 2026-07-30: 46 dates and 552 declared
  market-days.
- Post-boundary support, from 2026-07-31 through 2026-08-11: 12 dates and
  144 declared market-days.
- The boundary cohorts were inventoried separately and never pooled.
- The 225,822 lifecycle rows comprise 75,466 `intended`, 75,466
  `paper_posted`, 53,582 `replaced`, 13,844 `released`, 5,632
  `blocked_by_preflight`, and 1,832 `expired` transitions. They contain no
  authenticated trade/fill transition.

These 696 declared market-days are inventory support, not admissible economic
support. The admissible authenticated-fill support is exactly 0 dates, 0
markets, 0 market-days, and 0 fills in both provenance regimes.

### Economics and settlement identities

| Artifact | Bytes | SHA-256 | Disposition |
| --- | ---: | --- | --- |
| `backtest/exchange_economics_accepted_snapshot.json` | 9,109 | `841b3c1871a0c26656e34114f1b30f6c7d86a582879ed5da71eecb02387f718d` | `exchange_economics_snapshot_v0.1`, Polymarket US, target 2026-06-27; not International evidence. |
| `backtest/exchange_economics_snapshot.json` | 8,551 | `9801412e6c4916726f4dfb35cac298dfea98c86fcbc3819741dfcc2761dab351` | Frozen current US snapshot for 2026-08-12; not an accepted International per-run binding. |
| `backtest/settlement_source_revision_audit.json` | 2,178,863 | `bf7049d87d0e2820af09e99fe7cc1d2b48679a032153592aebf0d8d84b45b589` | Settlement revision audit only. |

The three-file economics/audit family binding is
`10034d49684a28cf4f4c381d7acb12e2a35992becff4da289a92a4d2db4ecbfe`.
Primary-liquidity incentives remain exactly zero for decision purposes because
there is no accepted, exact, realized incentive reconciliation for any
authenticated fill.

The settlement ledgers contain 18,031 physical revision rows. Their exact
file hashes are:

| Market | Rows | Bytes | SHA-256 |
| --- | ---: | ---: | --- |
| Atlanta | 1,481 | 20,562,772 | `e28c03335430d09f521524f9ddf5d21a904b29d3fcc8fcb053b56acb97eb68c9` |
| Austin | 1,480 | 20,419,421 | `b5f2b4ef917374746476e9aa627f47d7979ba2a5bf905e66373077e0f75a260a` |
| Chicago | 1,480 | 20,614,556 | `9758b0277a9198bf433fa962493dc7baee105b4f9a6b51d6b288744c154d3bd1` |
| Dallas | 1,480 | 20,534,901 | `ff0bc976723776ef1bde43ee8fbc00297262f51a4e3c2bf63258825062ce2378` |
| Denver | 1,480 | 20,414,726 | `8820e0fe9fcee57300e7698706b34e6afa65ddcdfc5af68053dec4247cd9d467` |
| Houston | 1,480 | 20,617,272 | `0c7c9cc36d7f52f37f229921a87cfd9cf6be58e0ffd1825dbc2e0c4f3544d374` |
| Los Angeles | 1,480 | 20,844,608 | `3948710c52364d26be2ae749803c9bad465af7702d95354a40104b70b16cd2bb` |
| Miami | 1,480 | 20,494,032 | `2a1d1763865ff3c0869fe3b8fa1328017082224d2e875c5994a7c72331dade3e` |
| NYC | 1,480 | 20,477,439 | `5dd23e2f611f41eb4d87bbf6cc94362433e9e98d8c71bf935e1de77ade783b5e` |
| San Francisco | 1,480 | 20,799,311 | `962410099bc200629e73110ebac544abe73f506454fdfa97fadcab76696727a9` |
| Seattle | 1,480 | 20,524,402 | `93a7c6cd953c2c902b8a678d5d40e813dce2ce2adf6f200911907794bcd3f621` |
| Toronto | 1,750 | 23,995,780 | `d9bcf4cb73387ab8cd5073afd1852bd094ff24b56cd14d1d5318642fbb0064d3` |

No settlement row was joined to a fill. Hashing and counting the ledgers did
not reopen or analyze a market outcome.

## Required-quantity gate

| Required quantity | Frozen evidence | P0 result |
| --- | --- | --- |
| Quote opportunities by market/hour/spread/distance | Historical quote intents and public books exist, but the maker rows are US/blank platform evidence and the nine quote schemas are not a current International execution cohort. | Not measured. |
| Conservative fill probability | Simulated/paper lifecycle exists; authenticated fill count is zero. | Unavailable without fabricated fills. |
| Realized spread | No own fill price/size/time is available. | Unavailable. |
| 1-, 5-, and 15-minute markout | No authenticated fill anchor and no canonical gap-accounted execution tape exist at the freeze. | Unavailable without reconstruction. |
| Settlement markout | Settlement labels exist, but no fill can be joined to them. | Unavailable. |
| Inventory exposure | No exact own-account position reconciliation exists. | Unavailable. |
| Fees | The accepted snapshot is old US evidence and no confirmed-trade fee reconciliation exists. | Unavailable without an assumption. |
| Documented incentives | No exact accepted payout/rebate reconciliation exists. | Zero by fail-closed default; no proved nonzero amount. |
| Net P&L after all costs | Fill, inventory, fees, and incentives are incomplete. | Unavailable. |

## Exact P0 stop mechanism

The stop rule fired independently on all of these grounds:

1. Any fill rate or realized P&L would need fabricated or simulated fills.
2. Any 1/5/15-minute fill markout would need a reconstructed public path across
   unproved capture coverage.
3. Books cannot be treated as fresh at a nonexistent authenticated fill time.
4. Current International attempt/economics evidence is necessarily post-freeze
   production data and was not accessed.
5. The frozen accepted fee/rebate snapshot is Polymarket US evidence; applying
   it to International fills would be an assumption.
6. Ledger revisions, quote rows, book snapshots, and repeated lifecycle rows
   cannot inflate independent market-day support.

This is an evidence-integrity stop, not a negative profitability result.

## Minimal production export

The machine-readable contract requests an exact post-freeze target-date range
of 2026-08-13 through 2026-09-15, excluding the partial freeze date. It requires:

- complete source-file path/bytes/SHA/schema/market/date/provenance bindings;
- exact run and private-attempt lineage hashes;
- one deduplicated row per quote opportunity and authenticated fill lifecycle;
- selected raw user-stream/REST account records, with credential material
  prohibited;
- reduced fresh book and 1/5/15-minute checkpoints whose entire windows are
  gap-free;
- actual fee, position, balance, rebate, incentive, redemption, and settlement
  reconciliations;
- one countability row per market x target date;
- atomic content-addressed publication and two byte-identical reducer passes.

The production-side command in the specification is deliberately marked
`DESIGN_ONLY_REQUIRES_SEPARATE_REVIEW_AND_AUTHORIZATION`. This mission did not
implement or execute a production reducer and grants no production access.

## Metrics and inference

No economics metric, crossed interval, power value, MDE, drawdown,
concentration statistic, or fraction-profitable statistic was computed. The P0
stop rule prohibits those computations from the frozen substrate. Their status
is `NOT_COMPUTED_P0_STOP`, not zero and not inconclusive.

## Verification

The focused test selection exercised the repository's existing implementations
for bounded execution-tape rotation, repeated public execution identity,
capture-gap accounting, maker trade deduplication, conservative fill scoring,
actual fee/position/rebate reconciliation, zero-default primary liquidity
rewards, and market-day clustered bootstrap behavior. No reducer/economics
implementation was added because the P0 stop rule forbids P1 construction on
this substrate.

| Check | Result |
| --- | --- |
| Machine-readable export specification parse | PASS; schema `maker_economics_production_export_spec_v1`, disposition `NEEDS_EXACT_PRODUCTION_EXPORT`, 11 artifact families, 64 MiB cap. |
| Focused market/economics/evidence tests through `workstation_heavy.ps1` | PASS: 100 passed in 39.82 s. |
| Streaming/bounded-memory primitives | PASS within the focused selection: execution-tape bounded rotation and bounded run binding. |
| Duplicate/revision and gap/refusal primitives | PASS within the focused selection: public execution identity, trade-source deduplication, status recount, and explicit gap accounting. |
| Fee/incentive zero-default primitives | PASS within the focused selection: incomplete evidence blocks actual fees/rebates; primary liquidity rewards remain zero. |
| Crossed/clustered market-day bootstrap primitives | PASS within the focused selection: row inflation is blocked by market-day clusters. |
| `compileall -q app src tests` through `workstation_heavy.ps1` | PASS. |
| `weather.operations.agent_docs_audit` | PASS: 18 agent files and 828 Markdown files. |
| Roadmap lint/check | PASS: generated report matches sources. |
| Complete suite through `workstation_heavy.ps1 --basetemp C:\t\pytest-92a` | BASELINE DEFECT REPRODUCED: 12 failed, 4,208 passed, 22 skipped, 862 subtests passed, 13 warnings in 491.35 s. All 12 failures are `tests/operations/test_experiment_executor.py`; no other failure family occurred. |
| `git diff --check` | PASS before commit; repeated after the final report update. |

Before the complete run, `C:\t\pytest-92a` was absent. Its parent `C:\t` was
verified as a plain, non-reparse NTFS directory on local fixed drive `C:`
(`Win32_LogicalDisk.DriveType=3`). Because the suite failed, the temp root was
not removed; this preserves the requested failed-run evidence.

The 12 complete-suite failures all end at
`src/weather/operations/experiment_executor.py:2124`: after the candidate
workspace has been moved to quarantine, `write_json_atomic(staged_result, ...)`
attempts to create the terminal result through the old staged workspace path
and receives `FileNotFoundError`. This is the already-known quarantine
lifecycle defect, not Windows MAX_PATH and not a maker-economics failure. The
mission explicitly prohibited changing `experiment_executor.py`, so the defect
was reproduced and preserved rather than repaired or masked.

## Canonical roll verdict

`UNDECIDABLE: no live closure evidence` (exit 1).

The canonical `scripts/ops/roll_verdict.ps1` check found only dormant
workstation closure records: `loop`, `clob_loop`, and `observation_trigger`
were 519.1 hours old, and `clob_enrichment` was 897.7 hours old, all beyond the
24-hour maximum. This frozen workstation cannot convert that result into a
hand-derived roll-free verdict. No merge is authorized or requested.

## Prohibited-actions audit

- Frozen mirror writes: 0.
- Production accesses or mutations: 0.
- Provider or exchange contacts: 0.
- Credential accesses: 0.
- Weather-model fits or evaluations: 0.
- Reconstructed execution rows: 0.
- Scheduler mutations: 0.
- Promotions, releases, candidate freezes, trades, or merges: 0.
- `LongPathsEnabled` changes: 0.
- `experiment_executor.py` changes: 0.
- Complete tape/tree copies: 0.
