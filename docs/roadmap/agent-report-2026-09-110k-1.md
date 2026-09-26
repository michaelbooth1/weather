# 110k Part 1 — production snapshot envelope adapter

Verdict: implemented with fixture-only verification. No production snapshots,
credentials, `.env`, LAN reader or venue were accessed. Publication uses
`codex/portfolio-ledger-adapter-20260926`, based on integration commit
`8180404a0e588f73dab3c83a171538f8a89c9705`; rebase onto master after that integration lands.

The adapter accepts the helper's `reads` envelope as well as legacy and neutral
snapshots. Account identity must be explicit in `--account-id` or campaigns config;
conflicts refuse. Raw trade lists, including empty lists, cannot assert exhaustive
history: the book records `history_completeness_unproven` and remains INCOMPLETE.
Missing fees and unsupported activity stay unknown. Resolved inventory arrays can
be supplied by `reads.positions` when omitted from the summary.

The owner confirmed on 2026-09-26 that all trades so far were manual. The checked-in
`config/examples/portfolio_campaigns.json` therefore enables only owner-discretionary.
Weather and YouTube campaigns are disabled placeholders without start or capital;
rules and overrides cannot target them. The production agent authors the ignored
`config/local/portfolio_campaigns.json` from this example using actual owner records.
Its epoch coverage bound and empty capital records are structural, not accounting evidence.

The 110i report's production command received the narrow correction explicitly
requested by this handoff, with its original evidence limitations preserved.
Canonical details: [portfolio ledger](../operations/portfolio-ledger.md).

## Exact production command

After integration and owner configuration, from the production checkout:

```powershell
.\venv\Scripts\python.exe -B -m maker_core.portfolio report --snapshots .\data\wallet_ledger --campaigns .\config\local\portfolio_campaigns.json --account-id (Read-Host 'Public wallet account ID') --out .\data\portfolio_ledger
```

Alternatively omit `--account-id` when the same public identity is recorded in the
config. Exit 2 is an expected recorded INCOMPLETE result for the existing bounded
history shape; it is not complete accounting or trading authority. Exit 1 refuses
invalid input or a repeated journal book. This production command was not executed.

## Verification

The focused run includes `tests/maker_core`, `tests/market/test_wallet_reader.py`,
and `tests/operations/test_schema_registry.py`, `test_import_architecture.py`,
`test_agent_docs_audit.py`, `test_path_policy.py`. Maker-core import-boundary and
negative boundary tests are included in the architecture file. All execution uses
the required workstation heavy wrapper with a separate fixture basetemp.
The first run had 875 passes and 12 skips; its sole failure was the new fixture file
being untracked during the tracked-file audit. It was staged before the final run.
Final verification results are recorded in the publication commit.

Fixtures exercise the synthetic 09-25/26 cash/position sequence, manual allocation,
known settlement, completeness and fee uncertainty, legacy compatibility,
disabled-campaign guards, conflicting identity and module CLI execution from an
unrelated directory. Input files remain byte-identical.

## Per-file roll classification

`roll_verdict.ps1` returned **UNDECIDABLE: no live closure evidence** in this isolated
worktree. U below means undecidable; production must rerun the mechanical classifier
against current capture closures before integration. F is roll-free by file-class contract.

| File | Class |
| --- | --- |
| `src/maker_core/contracts/portfolio.py` | U |
| `src/maker_core/portfolio/ledger.py` | U |
| `src/maker_core/runtime/portfolio_report.py` | U |
| `src/maker_core/venue/account_read.py` | U |
| `config/examples/portfolio_campaigns.json` | F |
| `tests/maker_core/test_portfolio_archives.py` | F |
| `docs/operations/portfolio-ledger.md` | F |
| `docs/operations/config-inventory.md` | F |
| `docs/roadmap/agent-report-2026-09-110i-portfolio-ledger.md` | F |
| `docs/roadmap/agent-report-2026-09-110k-1.md` | F |
| `docs/roadmap/correspondence-index.md` | F |
