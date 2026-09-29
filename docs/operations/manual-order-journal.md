# Manual order journal

Status: canonical runbook. Owns the read-only journal of the owner's manual resting orders
(`weather.market.order_journal`), its record and report definitions, and the
`WeatherManualOrderJournal` task. Read when measuring manual one-sided orders against their
rewards and markouts. The [wallet reader](wallet-reader.md) owns LAN account reads and the client
token file. The [portfolio ledger](portfolio-ledger.md) owns campaign books.

## Boundaries

- Every record, fill, markout and report row is labelled `owner-discretionary`. The journal
  measures the owner's manual orders. Its output never enters automated campaign, maker-evidence or
  exam data.
- Account data comes only through `wallet_reader_client.read_account` (`summary`, `trades`,
  `rewards`), using the existing ignored client file `config/local/wallet_reader_client.json`.
  Market data comes only from GET-only public CLOB reads against an exact allowlist: `/book`,
  `/prices-history`, `/rewards/markets/<condition>` and `/markets/<condition>`. These reads send no
  auth headers and use no proxy, redirects or retries. Each run is capped at 40 public GETs and
  150 seconds. Anything left over is deferred to the next run and recorded under `errors`; nothing
  is lost.
- No venue credentials, SDK, order, cancel or signing path exists in these modules. A test
  enforces that.
- The task is light and lease-free. It needs 3-4 LAN reader GETs and a few public GETs every
  5 minutes, has no capture imports, and never takes the workload lease. The heavy-work windows in
  the [host load policy](HOST_LOAD_POLICY.md) do not apply to it.

## Commands

```powershell
& $python -m weather.market.order_journal record --out data\manual_order_journal
& $python -m weather.market.order_journal verify --out data\manual_order_journal
& $python -m weather.market.order_journal report --out data\manual_order_journal --json <path> --markdown <path>
```

`record` accepts `--reader-config <path>` in place of the default client file. It prints one JSON
line and exits 0 when it appended a record, even one with read errors. It exits 2 with a fixed
reason (`journal_writer_busy`, `journal_tail_truncated`, `journal_chain_invalid`,
`journal_clock_not_monotonic`) and appends nothing when the journal itself cannot be trusted.
`verify` walks the whole chain. `report` verifies first, then reports.

## Records

`data/manual_order_journal/<UTC-date>.jsonl` holds one canonical JSON line per run. Each line carries
`sequence` and `previous_sha256`, the SHA256 of the previous line's bytes, so any edit, deletion or
reorder breaks `verify`. The file is append-only and one OS-held lock admits one writer. A record
holds:

- **Open orders:** id, condition, token, side, outcome, price, size, matched, status.
- **Books** for each order's token: best bid and ask, two-sided mid, spread, and the top five levels.
- **Reward terms** per condition: daily rate, max spread, min size.
- **Reward earnings and pool percentages** for the current UTC day, plus the prior day re-read
  hourly. These are account reads, not payment verification.
- **Cash and positions** from the reader summary.
- **New fills, order events and markouts.**
- **Carried-forward `state`,** so a run reads only the journal tail.

**Fills.** The primary source is reader `/trades` (authenticated CLOB fills, one-hour overlap,
deduplicated by trade, order and token). The owner's leg is the taker leg, or the maker order that
matches a known order id or the account address. A `size_matched` increase with no trade across two
consecutive trade-readable runs becomes an `order_delta` fill. Its time is only a
no-later-than bound. A vanished order produces a `closed` event with its unattributed size; the
journal cannot tell a cancel from an unreported fill. Each fill records the mid from the preceding
record as `reference_mid`.

**Markouts** are signed so that positive favours the order: `(mark − price) × size` for a buy.
- **+5 and +30 minutes:** the last `/prices-history` point at or before the target, within 15
  minutes. Failing that, the first point after it, within 15 minutes. These points are not
  executable prices. A markout still unavailable 6 hours after its target is recorded as
  `unavailable`.
- **Settlement:** 1 or 0 from the public CLOB market's single `winner` token once it is `closed`.
  This is checked at most hourly per condition.

A failed reader read leaves known orders untouched. There are no `closed` events or delta fills
without a readable summary and trades.

## Report

Per order and per market:

- **Reward accrued.** Venue earnings per condition-day, latest observation wins. Only condition-days
  the journal observed count toward a market. The rest is `reward_outside_observation_pusd`. The
  per-order share splits each condition-day's earnings pro rata to the order's remaining size ×
  seconds that day. That split is an allocation, not a venue attribution.
- **Fills and markouts** at 5m, 30m and settlement.
- **Cash-days.** Resting BUY collateral (price × remaining size) × time, plus filled cost from fill
  to settlement or the last record. Record gaps over 15 minutes count only 15 minutes; the excess
  is `unobserved_seconds`.
- **Reward-share path.** Changes in the condition's pool percentage.
- **Net = rewards + settlement markout.** It stays `null` (`pending_settlement`) until every fill has
  settled. `net_provisional_pusd` uses the latest available horizon per fill.
- **Two-sided baseline (hypothetical).** Three times the reward, by the Q_min rule: a one-sided
  quote scores S/3 while the mid is inside 0.10-0.90, and `outside_one_sided_band` counts
  observations outside that band. It adds a mirror order at equal distance on the other side that
  fills the same size at the same time. Settlement then cancels and each fill contributes
  `2 × distance × size`.

## Scheduled task

The runner is `scripts/ops/manual_order_journal.ps1`; its registrar is
`scripts/ops/register_manual_order_journal.ps1`. The task is `WeatherManualOrderJournal`: every
5 minutes, S4U/Limited, a 4-minute limit, `IgnoreNew`, no late catch-up. The registrar requires two
pins:
- `-ExpectedRunnerSha256`, the runner file's SHA256.
- `-ExpectedModulesSha256`, the SHA256 of the UTF-8 text joining `<repo-relative path>:<lowercase sha256>`
  lines with `\n` for `order_journal.py`, `order_journal_io.py`, `order_journal_sources.py`,
  `order_journal_report.py` and `wallet_reader_client.py` (all under `src/weather/market/`), in that
  order.

Both pins must match before any Scheduler call. The action carries them, so the runner refuses to run
(`runner.log` status `refused`, exit 3) after any unreviewed edit. Re-register after a reviewed change.
A wrong or missing pin makes `-WhatIf` and a real run print the current hashes. `-RepoRoot` is the
code checkout. `-StateRoot` (default `-RepoRoot`) supplies `venv`, `config\local` and `data\`. A
detached reviewed worktree can therefore journal into the production checkout before its branch
merges, following the pinned-worktree pattern in the [operations design](OPERATIONS_DESIGN.md).

The pins cover `-RepoRoot\src` only, and the state venv's editable `.pth` can point at another
checkout's `src`. So the runner starts Python with `-P -B` and sets `PYTHONPATH` to `-RepoRoot\src`,
for the child only. Before recording, it probes `weather.market.order_journal.__file__`. If that path
is not under `-RepoRoot\src`, including when the import fails, the runner refuses: exit 3, `refused`
in `runner.log`, and no record is written.
Each run appends one line to `data/manual_order_journal/runner.log`.

## Update when

Update with any change to the record schema, the fill or markout rules, report definitions, public
routes or budgets, the runner or registrar parameters, or the task cadence.
