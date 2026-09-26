# Agent report 2026-09-110i — one-wallet portfolio ledger

**Verdict: IMPLEMENTED; fixture acceptance passes. Ready for production-agent
review, not runtime adoption or a claim of reconciled real-account balances.**
Unmatched lots default to **owner-discretionary**, outside bot bleed limits,
as the owner confirmed on 2026-09-26. The implementation keeps separate FIFO
campaign books, reconciles against independent wallet cash and positions, and
writes create-only hash-chained records. Bleed limits are report-only.

## Authority and source binding

- Mission: [110i handoff at the fetched owner-decisions tip](https://github.com/michaelbooth1/weather/blob/ed075014161e6e0b0f8d3e9d0fc8dd265356d2c2/docs/roadmap/workstation-handoff-2026-09-110i-portfolio-ledger.md).
  Required `8cf764d26` is an ancestor of that tip; the owner's explicit default
  instruction governs the older handoff's parenthetical request for confirmation.
- Branch: `codex/portfolio-ledger-20260926`, based on fetched `origin/master`
  `965374a0edc6fcb65d66e257be9e404cc9af8d60`.
- Explicit dependency: merged `origin/codex/wallet-public-reader-20260925`
  at `7c3184e8193ce60f2797200ded8857a1494944aa`, retaining 110f semantics,
  with merge commit `f4322c7e`. The generated correspondence index was regenerated;
  the ignore-file conflict retained both local-config and local-agent-state ignores.
- Implementation: `05e8857b4b6435a87719c18f202428474cafa4fa`.
  This report and its regenerated correspondence index follow as separate commits.
- Workstation implementation only. No actual account files, `.env`, private keys,
  signing clients, live GETs, orders or cancels were used. All added behavior was
  exercised with synthetic fixtures and fake transport responses. The running
  wallet reader was not restarted or changed. No master merge or runtime adoption.

## Implementation and neutral snapshot contract

Canonical schema, configuration and operator instructions are in
[the portfolio ledger runbook](../operations/portfolio-ledger.md).
Existing maker-core v0.1 contracts are unchanged; three registered schemas are
additive: `portfolio_snapshot_v0.1`, `portfolio_campaigns_v0.1`,
and `portfolio_ledger_v0.1`.

| Neutral snapshot field | Contract |
| --- | --- |
| `schema_version` | `portfolio_snapshot_v0.1` |
| `account_id`, `as_of_utc` | Opaque account identity and timezone-aware capture time; mixed accounts refused. |
| `cash_pusd` | Recorded nonnegative decimal amount, or null when unreadable. |
| `positions_complete` | Explicit completeness bool covering live, resolved and unknown inventory. |
| `history_complete`, `history_start_utc` | Explicit coverage assertion and start; complete coverage must reach every configured campaign start. |
| `positions[]` | Asset/condition IDs, event slug, size, average entry price, classification, redeemable flag, bid/ask, terminal price. Missing marks/terminal values remain null. |
| `trades[]` | Stable event ID, transaction hash, timestamp, asset/condition IDs, event slug, account-relative BUY/SELL/REDEEM, size, price, explicit fee or null. REDEEM requires a known 0/1 price. |

Amounts use finite decimal strings. Event IDs deduplicate repeated recorded fills;
conflicting copies invalidate completeness. Same-asset timestamp ties are
INCOMPLETE because a deterministic event-ID tie break does not prove FIFO order.
Configuration and snapshot hashes bind the deterministic book to its inputs.

The pure ledger imports neither weather, venue/runtime code nor a network SDK.
`venue/account_read.py` adapts saved summary/activity envelopes without IO;
runtime orchestration owns explicit files and the optional LAN reader call.
The required `python -m maker_core.portfolio` entry point is a five-line command
shim. Its single import of `maker_core.runtime.portfolio_report.main` is documented
and narrowly allowed by the import ratchet; portfolio library/package imports of
runtime or venue remain forbidden. Tests verify that the exception cannot be
used from the ledger, journal or package initializer, or for venue/credentials.

Attribution is transaction override, then first matching condition/prefix rule,
then owner-discretionary. A sale consumes account FIFO and retains each
acquisition's campaign even when campaigns share one token. Entry/exit fees are
allocated proportionally. Known settlement values realize the remaining lot's
P&L without crediting unredeemed cash; redemption moves value to cash without
counting it twice. Unknown settlement values or one-sided quotes are incomplete.

Reconciliation compares recorded cash and separately valued positions with
campaign equity plus explicitly recorded unattributed cash. The default tolerance
is 0.000001 pUSD; config cannot exceed 0.01. A residual is never silently made
unattributed cash. Unknown acquisitions are not manufactured from average price.
Unknown financial aggregates are null with reasons. Campaign cash can be negative
when shared cash finances an owner's lot; this never debits the weather book.

The journal validates sequence, canonical bytes and prior hashes before appending,
uses exclusive files plus an exclusive writer lock, flushes/fsyncs new records,
refuses repeated books, and never rewrites history. An externally retained tip
hash is still necessary to detect tail deletion or replacement of the entire chain.

Reader `--campaigns <json>` adds the same book to `/summary`, with per-campaign
statuses replacing the legacy single-baseline P&L/bleed fields. Configuration is
validated before credential loading. Optional activity walks remain inside the
existing GET allowlist and composite/rate limits. Without this option, 110f behavior
is retained. The portfolio CLI's optional LAN path uses the existing explicit
URL/token JSON format, two fixed GET routes, no proxies or redirects, RFC1918
literal IPv4 validation, response bounds, and no environment/venue-key loading.

## Fixture evidence and checks

The focused run was executed through `scripts/ops/workstation_heavy.ps1` with the
project interpreter and a dedicated `--basetemp`, under the workstation admission
lease. Final result: **862 passed, 12 skipped in 11.49 seconds**:

```text
-m pytest tests/maker_core tests/market/test_wallet_reader.py
tests/operations/test_schema_registry.py tests/operations/test_import_architecture.py
tests/operations/test_agent_docs_audit.py tests/operations/test_path_policy.py
-q --basetemp C:/Users/Michael/Documents/github/weather/scratch/portfolio-ledger-tests
```

The 12 skips are existing RE-1 full-minute parity skeletons whose sanitized
account-journal exports were unavailable in fixture-only 110c. No new acceptance
test was skipped. Compileall of `app src tests` also passed through the wrapper;
`git diff --check` passed. Documentation parity is checked again after committing
this report and regenerating the index.

| Acceptance fixture | Observed result |
| --- | --- |
| Weather contribution 135.218694; owner buys 140 MrBeast YES at 0.72 | Owner-discretionary lot; weather stays OBSERVED before its own losses; no owner bot limit. Synthetic reserve/cash values are explicit fixture inputs, not claimed account balances. |
| Miami 75 sold at 0.18 | Fixture acquisition/fee evidence yields realized -13.30 pUSD. |
| Chicago 75 at 0.43 resolves at 0 | Additional weather realized loss -32.25; combined weather -45.55 crosses its own fixture limit of 40. |
| Known winner, then redemption | Equity unchanged by moving terminal value to cash; no double count. Stale positive holdings after redemption are incomplete. |
| Unknown terminal value | Affected campaign and wallet INCOMPLETE; unrelated campaigns retain known status. |
| Cash/quantity mismatch or missing acquisition/fee/history/mark/read | INCOMPLETE with reasons; no invented lot, fee or balancing cash. |
| Override and cross-campaign FIFO partial sale | Override wins; acquisition ownership and proportional fees survive the close. |
| Reordered/repeated archives | Identical canonical book and hashes. |
| Journal duplicate, tampering, existing writer lock | Refused; prior bytes and another writer's lock preserved. |
| Reader campaign integration and LAN client | Fixture summaries use campaign status; fixed GET routes and rejected non-LAN/arbitrary URLs. |

Task pytest scratch was removed after checking its absolute path. Worktree/code
and reports are retained. C: free space was 139,360,931,840 bytes before the work
and 139,264,974,848 bytes after verification/cleanup (shared-host measurement, not
an attribution of all disk movement to this task). No tapes or trading evidence
were deleted.

## Roll classification and integration

Executed the repository-owned verdict, not a hand-derived import closure:

```powershell
.\scripts\ops\roll_verdict.ps1 -Branch codex/portfolio-ledger-20260926 -Base origin/master
```

Result **UNDECIDABLE**, exit 1: no live closure evidence in the isolated worktree.
The four required snapshot/CLOB/observation-trigger/enrichment status files were
absent. Treat the branch as roll-sensitive until the production agent obtains a
fresh verdict. This does not prevent a topic-branch push. No production merge is
authorized by this report.

Per-file inventory includes the explicitly requested wallet-reader merge, not just
110i's own diff. **D** means canonical documentation/PowerShell roll-free surface;
**U** means no per-file roll-free claim is possible from the unavailable live
closure evidence. The branch-level script verdict above governs integration.

| File relative to repository root | Roll handling |
| --- | --- |
| `.env.example` (inherited names-only template) | U |
| `.gitignore` | U |
| `README.md` | D |
| `docs/README.md` | D |
| `docs/documentation-maintenance.md` | D |
| `docs/operations/README.md` | D |
| `docs/operations/config-inventory.md` | D |
| `docs/operations/package-boundaries.md` | D |
| `docs/operations/portfolio-ledger.md` | D |
| `docs/operations/wallet-reader.md` | D |
| `docs/roadmap/agent-report-2026-09-100a-wallet-reader.md` | D |
| `docs/roadmap/agent-report-2026-09-100d-wallet-reader-fixes.md` | D |
| `docs/roadmap/agent-report-2026-09-110i-portfolio-ledger.md` | D |
| `docs/roadmap/correspondence-index.md` | D |
| `pyproject.toml` | U |
| `requirements.txt` | U |
| `scripts/ops/register_wallet_reader_firewall.ps1` | D; no registration executed |
| `src/maker_core/contracts/portfolio.py` | U |
| `src/maker_core/portfolio/__main__.py` | U |
| `src/maker_core/portfolio/journal.py` | U |
| `src/maker_core/portfolio/ledger.py` | U |
| `src/maker_core/runtime/credentials.py` | U |
| `src/maker_core/runtime/portfolio_io.py` | U |
| `src/maker_core/runtime/portfolio_report.py` | U |
| `src/maker_core/venue/account_read.py` | U |
| `src/maker_core/venue/portfolio_client.py` | U |
| `src/weather/market/wallet_reader.py` | U |
| `src/weather/market/wallet_reader_client.py` | U |
| `src/weather/market/wallet_reader_security.py` | U |
| `src/weather/market/wallet_reader_server.py` | U |
| `src/weather/market/wallet_reader_transport.py` | U |
| `src/weather/schema_registry_recent_data.py` | U; additive registrations |
| `tests/maker_core/test_portfolio.py` | U |
| `tests/market/test_wallet_reader.py` | U |
| `tests/operations/test_import_architecture.py` | U |

## Exact production rebuild command and evidence limits

After guarded integration, from the production checkout with the owner-supplied
recorded campaign configuration, run:

```powershell
.\venv\Scripts\python.exe -m maker_core.portfolio report --snapshots .\data\wallet_ledger --campaigns .\config\local\portfolio_campaigns.json --out .\data\portfolio_ledger
```

This is offline by default. It was **not** run on production or real snapshots.
The command expects neutral snapshots or documented `{account_id,
captured_at_utc, summary, trades}` reader archives; a direct summary with an
account identity is accepted but cannot prove missing trade history. Unknown
legacy layouts are refused, rather than inventing identity or history. The
actual production archive layouts and fee/coverage availability have not been
inspected under this fixture-only mission.

The owner configuration must record real capital flows, starts, reserve and
attribution rules; the runbook's example is structural only. An opening equity
number alone cannot reconstruct pre-existing lots. Recent reader activity and
raw authenticated CLOB fills do not prove complete account-relative FIFO history;
missing fee/coverage evidence produces INCOMPLETE, not assumed zero. The optional
LAN capture path saves its normalized input create-only for later offline rebuild.

Exit 0 means a complete reconciled book, 2 a recorded INCOMPLETE book, and 1 invalid
input or refused write. Rebuilding the same inputs into a separate empty output
directory reproduces the book hash; trying to append the same book to the existing
journal is deliberately refused. Keep the returned tip hash outside the journal.
Production acceptance and any later reader restart remain separate operations.
