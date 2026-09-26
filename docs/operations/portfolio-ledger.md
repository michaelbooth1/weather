# One-wallet portfolio ledger

Status: canonical. Owns neutral account snapshots, campaign attribution, FIFO
accounting, reconciliation and create-only portfolio records. Read when rebuilding
campaign books from recorded wallet reads. This is reporting, never order or bleed
enforcement. The [wallet reader](wallet-reader.md) owns LAN reads and credentials.

## Boundaries and commands

`maker_core.portfolio.ledger` is pure and imports no weather, venue, runtime or
network code. `maker_core.venue.account_read` converts saved reader JSON without
IO. Runtime orchestration supplies explicit paths and optional LAN reads. The
`maker_core.portfolio.__main__` command shim imports only that orchestration entry
point; importing the portfolio package does not load it. Existing v0.1 contracts
are unchanged; the portfolio contracts are additive.

From the production checkout, after the owner supplies the campaign configuration:

```powershell
.\venv\Scripts\python.exe -m maker_core.portfolio report --snapshots .\data\wallet_ledger --campaigns .\config\local\portfolio_campaigns.json --out .\data\portfolio_ledger
```

The command reads every `*.json` directly in the explicit snapshot directory.
Do not put unrelated files there. It writes one record in a separate output
directory. Exit 0 means a complete reconciled book; 2 means a recorded INCOMPLETE
book; 1 means invalid input or a refused write. An incomplete record is evidence,
not permission to trade. Output cannot be within the snapshot directory.

Optional `--reader-url http://192.168.1.106:8765 --client-config
.\config\local\wallet_reader_client.json` adds two fixed GETs: summary with resolved
rows and trades since the earliest campaign start. The existing token file must
contain that same literal RFC1918 IPv4 URL and a 64-hex bearer token. No DNS/public
URL, redirect, proxy, arbitrary route, venue credential or environment lookup is
allowed. Each LAN timeout is 20 seconds; responses are capped at 2 MB. The normalized
capture is saved create-only under its content hash in the snapshot directory,
so offline rebuilds retain the same inputs. The optional path never assumes that
the reader's bounded recent history is exhaustive. It may therefore be INCOMPLETE.

## Neutral snapshot schema

`portfolio_snapshot_v0.1`, owned by `maker_core.contracts.portfolio`:

| Field | Meaning |
| --- | --- |
| `account_id`, `as_of_utc` | One opaque account identity and timezone-aware capture instant. Mixed accounts are refused. |
| `cash_pusd` | Recorded nonnegative cash, decimal string or null when unavailable. |
| `positions_complete` | Explicit bool: all live, resolved and unknown positions included. |
| `history_complete`, `history_start_utc` | Explicit coverage assertion and instant; complete coverage must reach every campaign start. No assertion is inferred from recent-page length. |
| `positions[]` | `asset_id`, `condition_id`, `event_slug`, `size`, `avg_price`, `classification` (`live`, `resolved`, `unknown`), `redeemable`, `bid`, `ask`, `terminal_price`. Prices/size are decimal strings; unknown prices are null. |
| `trades[]` | Stable `event_id`, `transaction_hash`, `at_utc`, `asset_id`, `condition_id`, `event_slug`, `side` (`BUY`, `SELL`, `REDEEM`), `size`, `price`, `fee_pusd` (null if unknown). A REDEEM needs explicit quantity and terminal 0/1 price. |

All numbers must be finite; quantities cannot be negative and prices lie in
[0,1]. Use one stable event ID per actual fill, including multiple fills in one
transaction. Repeated identical events across archives are deduplicated;
conflicting versions make the book incomplete. Event ordering is timestamp then
event ID; multiple same-asset events at the same instant make affected campaigns
INCOMPLETE because the tie break cannot prove FIFO order. Inputs and config are
hashed; rebuilds are independent of file order.

Reader archives are `{account_id, captured_at_utc, summary, trades}`. A direct
summary object is also accepted if it carries `account_id`; missing trades mean
incomplete history. `summary.positions`, `resolved_positions`, and
`unclassified_positions` are normalized; omitted resolved rows are a missing
read, not zero holdings. `trades.account_activity` (or existing `recent_activity`)
uses public activity fields: `proxyWallet`, `type`, `side`, `asset`, `conditionId`,
`eventSlug`, `transactionHash`, `timestamp`, `size`, `price`, optional explicit
`fee_pusd` and fill `id`. Account mismatches, unsupported activity, missing hashes
or invalid times invalidate history coverage. Explicit `history_complete` and
`history_start_utc` travel inside `trades`. Existing bounded recent output has no
such completeness proof. Raw authenticated CLOB fills are not reinterpreted as
account-relative buys/sells: maker allocations require separate evidence.
Unknown archive layouts are refused; missing evidence is never synthesized.

## Campaign configuration

Schema `portfolio_campaigns_v0.1`. Store the owner's actual records at the
explicit config path; the following is a structural example, not capital advice:

```json
{
  "schema_version": "portfolio_campaigns_v0.1",
  "default_campaign": "owner-discretionary",
  "unattributed_cash_pusd": "0",
  "reconciliation_tolerance_pusd": "0.000001",
  "campaigns": [
    {"id":"weather-maker","start_utc":"2026-09-22T00:00:00Z","contributions":[],"bleed_limit_pusd":"40"},
    {"id":"youtube-maker","start_utc":"2026-09-22T00:00:00Z","contributions":[]},
    {"id":"owner-discretionary","start_utc":"2026-09-22T00:00:00Z","contributions":[]}
  ],
  "lot_overrides": [],
  "rules": [{"event_slug_prefix":"highest-temperature-in-","campaign":"weather-maker"}]
}
```

Each recorded contribution is `{id, at_utc, amount_pusd}`; negative amounts are
withdrawals and future contributions are not yet counted. `unattributed_cash_pusd`
is a separately recorded opening cash reserve, never the computed reconciliation
residual. The example times must be replaced by actual reconciled campaign starts.
An opening equity number alone cannot explain pre-existing lots: their acquisition
history is still required, otherwise the campaign is incomplete.

Acquisitions use transaction-hash `lot_overrides` first, then the first matching
rule (`condition_id` or literal `event_slug_prefix`), then **owner-discretionary**.
An override is `{transaction_hash, campaign}`. The owner confirmed this default
on 2026-09-26: it cannot default to a bot campaign, and owner-discretionary cannot
have a bot bleed limit. Prefixes are literal, not glob expressions.

Sales/redemptions consume account FIFO and retain each acquisition's campaign,
even when a token has lots from several campaigns. Entry and exit fees are
allocated proportionally. Missing fees stay unknown, never assumed zero.
Known resolved 0/1 values realize the remaining lot's P&L and add unredeemed value
to equity without crediting cash; a recorded redemption then moves that value to
cash without counting it twice. A stale positive position after redemption is a
quantity mismatch. Unknown terminal prices preserve 110f INCOMPLETE semantics.

Live marks use a two-sided midpoint only. Per-campaign equity is recorded capital
plus cash flows and live/terminal values; P&L subtracts that campaign's capital.
Bleed is P&L strictly below minus its optional loss limit. It never tests whole-wallet
cash. Campaign cash can be negative when an owner lot consumes shared cash; this
financing is visible and does not debit the weather campaign. Limits are report-only.

The wallet compares actual cash with campaign cash plus the recorded reserve,
and actual cash plus snapshot position values with campaign equity plus reserve.
Tolerance defaults to 0.000001 pUSD and cannot exceed 0.01. Unknown fees/history,
quantity/identity mismatches, missing reads or unknown values make the whole book
INCOMPLETE. A lot-specific unknown affects its own campaign; global history gaps
affect all campaigns. A cash reconciliation error stays on the wallet rather than
inventing an owning campaign. Unknown aggregates are null; reasons are explicit.

## Journal and reader integration

Each run writes one `portfolio_ledger_v0.1` record, named `00000000.json`, etc.,
with sequence, previous-record SHA256, deterministic book and book SHA256. Existing
records are verified before appending. Exclusive file creation prevents overwrite;
the same book is refused twice. An exclusive writer lock serializes processes;
a crash may leave a lock or partial record, which must be investigated, not erased
by the next run. Retain the externally returned tip hash to detect tail truncation
or whole-chain replacement; a chain alone cannot detect those attacks.

Reader `serve --campaigns <json>` validates this file before credential loading.
Its `/summary` adds a `campaigns` book and replaces the single-baseline status with
wallet completeness and per-campaign statuses. Legacy single-campaign P&L/bleed
fields are omitted in this mode. The account activity walk consumes the existing
five-page, 24-GET/16-second composite and 30-GET/minute limits; it never retries or
expands the allowlist. Missing fees or an unexhausted history remain incomplete.
Without `--campaigns`, 110f behavior is unchanged. No service restarts or real-account
probes belong to implementation verification.

## Update when

Update with schema, attribution, FIFO/fee/settlement, reconciliation, command,
archive adaptation, journal, safety-boundary or reader response changes.
