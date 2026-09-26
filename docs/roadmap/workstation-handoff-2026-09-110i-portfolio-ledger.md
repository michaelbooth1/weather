# Workstation handoff 2026-09-110i — one-wallet portfolio ledger (the "master runner" for positions)

Written 2026-09-26 by the production agent. Owner, 2026-09-26: the MrBeast (YouTube) positions trade from the **same wallet**
as the weather maker, so we need one master record of every position, attributed to the campaign that owns it. This is the
`portfolio/` ledger that the [informed maker design](../operations/informed-maker-design-2026-09-25.md) already names
("ledger (one wallet), reservation, limits, exposure"). Base: `master` (maker core Phase 0, tag `maker-core-contracts-v0.1`)
plus the wallet reader branch `codex/wallet-public-reader-20260925` at `7c3184e81` or newer (110f INCOMPLETE semantics).

## Why now

The wallet reader has one campaign baseline. When the owner bought 140 YES of "MrBeast next video 70-80M views week 1"
@0.72 on 2026-09-25, cash fell from 102.97 to 2.17 and the reader flipped the weather campaign to `BLEED_LIMIT`, although
the weather maker lost nothing from it. Chicago 68-69°F Sep 25 (75 YES @0.43) then resolved as a loss in the same wallet.
One wallet, several owners of risk: records must say whose each lot is.

## Build

1. **Pure ledger, `src/maker_core/portfolio/`.** Imports neither `weather`, a venue SDK, nor the network. Input: account
   snapshot records (cash, positions with size/avg price/classification/redeemable/terminal price, trades with
   transaction hash and timestamp) in a documented neutral schema; output: a campaign book. `venue/account_read.py` adapts
   the wallet reader's `/summary` + `/trades` JSON (and the archived `data/wallet_ledger/*.json` snapshot files) into that
   schema. Contracts are additive to v0.1.
2. **Campaigns and attribution.** Config file (path passed explicitly) listing campaigns: `weather-maker` (RE-1 lots and
   the informed maker), `youtube-maker` (future plugin), `owner-discretionary` (owner's manual trades). Each has a start
   time, recorded capital contributions, and an optional bleed limit. Attribution rules in order: explicit per-lot override
   by transaction hash → market-family rule (event-slug prefix or condition id, e.g. `highest-temperature-in-*` →
   weather) → **default `owner-discretionary`**. A lot is never attributed to a bot campaign by default. (Owner to confirm
   the default; if not confirmed, keep it configurable and ship this default.)
3. **Per-campaign figures:** contributed capital, open lots (FIFO), realized P&L on closes and settlements, unredeemed
   terminal value (110f rules: known 0/1 terminal price counts; unknown → `INCOMPLETE`, never zero), unrealized at a
   declared mark basis (two-sided mid, else `INCOMPLETE`), fees paid, and bleed status against its own limit
   (report only; enforcement stays deferred by the owner).
4. **Whole-wallet reconciliation.** Cash + marked/terminal positions must equal the sum over campaigns plus unattributed
   cash, within a stated tolerance. Any mismatch, missing read or unknown lot → the whole book `INCOMPLETE` with reasons.
   Records come from actual wallet reads only, never guesses.
5. **Append-only journal.** Each run writes one hash-chained record (`portfolio_ledger_v0.1`) to an explicit output
   directory; it refuses to overwrite and never rewrites earlier records. A rebuild over the archived snapshot files must
   reproduce the same book.
6. **CLI** `python -m maker_core.portfolio report --snapshots <dir> --campaigns <json> --out <dir>` (all paths explicit;
   no network by default). Optional `--reader-url` reads the LAN reader with the existing client token file; read-only.
7. **Wallet reader:** add an optional `--campaigns <json>` so `/summary` gains a `campaigns` block from the same ledger code
   and the single-baseline `status` is replaced by per-campaign statuses. Keep every 100a/110f safety property.

## Tests (fixtures only)

The 09-25/26 sequence as a fixture: weather baseline 135.218694 contributed; the owner MrBeast buy leaves the weather
campaign un-bled and appears under `owner-discretionary`; Chicago resolves 0 and is a weather realized loss; the
RE-1 Miami sale (75 @0.18) is realized; a lot with unknown terminal price makes only its campaign and the wallet
`INCOMPLETE`; a reconciliation mismatch; an overridden lot; rebuild determinism; journal refuses overwrite. Include the
repo-wide audits in the focused run (`test_schema_registry.py`, `test_import_architecture.py`, `test_agent_docs_audit.py`,
`test_path_policy.py`) and the maker-core import-boundary tests.

## Boundaries and deliverables

No orders, cancels, signing, private keys, `.env` or real account data; fixtures only. Branch
`codex/portfolio-ledger-20260926` (push authorized). Report
`docs/roadmap/agent-report-2026-09-110i-portfolio-ledger.md`: verdict first, the neutral snapshot schema, roll
classification per file, and the exact production command to rebuild the book from `data/wallet_ledger/`.
