# Agent report 2026-09-110z part 2 — wallet-reader settlement watcher

Answers [workstation handoff 2026-09-110z](workstation-handoff-2026-09-110z-reward-scan-and-read-tools.md), part 2.
Branch `codex/reader-settlement-route-20260928`, code commit `094951085c8c2bd16827fa25b2696fbc3b371bf3`, draft PR
[#130](https://github.com/michaelbooth1/weather/pull/130). Written 2026-09-29 on the 32 GB workstation.

## Verdict

**DELIVERED, FIXTURE-VERIFIED ONLY, WITH ONE SCOPE INTERPRETATION.** The reader has a new `/settlement` route
(client: `settlement --since`). For every held or recently filled market it reports:

- the Gamma resolution state and UMA status;
- the redeemable flag and terminal price per held token;
- the venue's winner and its declared resolution basis;
- the local WU settlement-proxy value in native units.

It flags disagreements, unredeemed winners and resolved-but-unreconciled holdings. It uses the existing
allow-list unchanged, and the existing composite budget, cache and journal.

**Interpretation:** the handoff asks for "the venue's weather.gov outcome where applicable". I did **not** add
`weather.gov` to the reader's allow-list: the handoff also says "same allow-list", and fetching the WRH page
would be a new host and a new parser. Instead, each market reports `venue_resolution_source` and
`venue_outcome_basis` (`weather_gov`, `wunderground`, `other`). Where the basis is `weather_gov`, the venue's
resolved winner is the weather.gov outcome. If production wants an independent WRH read, that is a separate,
allow-list-changing decision.

## What was built

| File | Purpose |
| --- | --- |
| `src/weather/market/wallet_reader_settlement.py` (new) | Join logic; direct latest-revision ledger read (64 MiB cap); band-label comparison; flags |
| `src/weather/market/wallet_reader.py` | `WalletReader.settlement(since)` in one composite plan; `settlement_root`/`events_config_path`; `serve --settlement-root` |
| `src/weather/market/wallet_reader_server.py` | `/settlement` route; `since` query (default 7 days); same auth/method/browser gates |
| `src/weather/market/wallet_reader_client.py` | `settlement` route; `--since` allowed for trades and settlement |
| `tests/market/test_wallet_reader_settlement.py` (new), `tests/market/test_wallet_reader.py` | 5 fixture tests; the existing import allow-list test now also covers the new module |
| `docs/operations/wallet-reader.md`, README, ownership row | Route documentation |

Rules, all fixture-tested:

- **Resolution:** a market is `resolved` only when Gamma says `closed` and every outcome price is exactly 0 or 1,
  summing to 1. Otherwise it is `closed_awaiting_terminal_price`, `open`, `unknown` or `metadata_unavailable`.
  Resolution is never inferred from dates or a zero price, the same rule as the positions route.
- **Settlement proxy:** read from `<settlement root>/<location>/ledger.jsonl`, taking the latest revision
  (maximum `revision_number`, file order as the tie-break, as `settlement_ledger.current_ledger_label` does).
  The location comes from the event-slug prefixes in `config/location_market_events.json`. Non-weather markets
  (for example YouTube) are `proxy_not_applicable`. No settlement or model module is imported, so the reader's
  import allow-list keeps its shape.
- **`disagreements`:** the proxy's winning band and the venue's winner disagree about this band. Bands are
  compared by label text after removing spaces and degree signs.
- **`unredeemed_winners`:** a held token whose terminal price is 1.
- **`resolved_unreconciled`:** a venue-resolved holding with no proxy label, or with a ledger status other than
  `match`.
- **Missing data** never counts as agreement.

### Limits the production agent should know

- The reader runs on the workstation, so it reads the workstation's `data/settlements` copy, which lags
  production. Recent days show `proxy_label_absent` and are flagged `resolved_unreconciled`; they are never
  counted as agreement. `serve --settlement-root <dir>` can point at a copied ledger.
- Band matching by label text has not been tested against real ledger `winning_band` strings. It is exact up to
  whitespace, case and the degree sign. A formatting difference would appear as a false `disagreement`, never
  as a false agreement.
- "Recently filled" means maker fills from authenticated CLOB `/data/trades` (the existing allow-listed path),
  within the existing five-page cursor bound.

## Measured values

None; fixtures only.

## Per-file roll verdict

Derived from the delegation contract §3; the production agent re-derives it with `roll_verdict.ps1`:

| File | Closures | Verdict |
| --- | --- | --- |
| `src/weather/market/wallet_reader*.py` | none expected: the reader is an owner-started workstation service, not a capture-loop import | roll-free (confirm) |
| `tests/…`, `docs/…`, `README.md` | none | roll-free |

The reader adopts the change only when the owner restarts it.

## What was NOT done

- No reader was started and no venue call was made.
- No credential, `.env` or `config/local` file was read.
- No firewall change, registration, production write or merge.

## Verification

- `pytest tests/market/test_wallet_reader_settlement.py tests/market/test_wallet_reader.py`: 181 passed, run
  directly before the final fixture edit; the settlement file alone: 5 passed.
- Focused set plus repo-wide audits through `scripts\ops\workstation_heavy.ps1`: 300 passed; 1 failure was the same path-length artifact in `test_reward_share_estimate.py`, which then passed 24/24 with a short `--basetemp`.
- GitHub CI on the PR head: see the handback reply.

## Reproduction

```powershell
.\venv\Scripts\python.exe -m pytest -q tests\market\test_wallet_reader_settlement.py tests\market\test_wallet_reader.py
# After the owner restarts the reader from this code, on the client host:
.\venv\Scripts\python.exe -m weather.market.wallet_reader_client settlement --since <unix seconds>
```

## Open questions served

None.
