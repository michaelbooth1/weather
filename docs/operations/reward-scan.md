# Reward-opportunity scanner

Status: canonical runbook. Owns `weather.market.reward_scan` and its owner-started
workstation loop `scripts/ops/run_reward_scan.ps1`.
Read when looking for liquidity-reward opportunities to act on manually, or when
wiring a reader (the owner cockpit) to the scan output. The scanner is research
for the owner's discretionary trading. **It places, cancels and signs nothing.**

## What it reads

For every order-book-enabled, open market of an event in
`config/location_market_events.json` whose `end_date` has not passed, plus any
explicit `--condition` id (for example a YouTube view market):

- public CLOB `/rewards/markets/<condition>`: reward configs active on the current
  UTC day (their `rate_per_day` summed), `rewards_max_spread` (cents) and
  `rewards_min_size`;
- public CLOB `/book` for the YES token only, when the daily rate is positive. The
  NO book is the YES book reflected (a YES ask at q is a NO bid at 1 - q);
- public Gamma `/markets` only to resolve token ids of explicit `--condition` ids;
- the owner's pool percentages through the wallet reader's `/rewards` route, by
  running `python -m weather.market.wallet_reader_client rewards --date <UTC day>` as
  a child process (the [wallet reader](wallet-reader.md) runbook owns its setup).

`check_public_get` is the single allow-list: GET only, those three exact host/path
pairs, exact query names, validated ids. Anything else is refused before a socket
opens. Requests carry no auth headers and use no proxies, redirects or retries.
Each scan has a GET budget (`--max-gets`, default 2000), a pace
(`--min-interval`, default 0.2 s) and a deadline after which no new GET opens
(`--deadline-seconds`, default 780). Markets are scanned nearest event first; any
market the budget or deadline does not reach keeps its rows with status
`budget_deferred`.

Import isolation is a ratchet in `tests/operations/test_import_architecture.py`:
the static first-party import closure of `weather.market.reward_scan` may not
contain order, signing, RE-1, credential, wallet-reader, live, SDK, maker policy,
plugin or fair-value modules. That is why the reader is a child process.

## Output

Each scan writes `<out>/reward_scan_<YYYYMMDDTHHMMSSZ>.json` and replaces
`<out>/latest.json` atomically; `<out>` defaults to `data/reward_scan/`. The
document has schema `reward_scan` (registry), `campaign: owner-discretionary`,
the scan time and UTC reward day, GET usage, `pool_percentage_status`
(`observed`, `reader_not_requested` or `reader_<reason>`), status counts and one
row per outcome with:

| Field | Meaning |
| --- | --- |
| `daily_reward_rate`, `max_spread_cents`, `min_size`, `tick_size` | Market reward terms and book tick |
| `best_bid`, `best_ask`, `spread` | Raw displayed best prices for this outcome |
| `mid` | Size-cutoff midpoint: best bid and ask among levels of at least `min_size` |
| `mid_in_reward_band`, `one_sided_score_factor` | Mid inside [0.10, 0.90]: one-sided quotes score S/3 (`0.333333`); outside it one-sided scores 0 |
| `resting_bid_size_in_band`, `resting_ask_size_in_band` | Displayed size of levels of at least `min_size` strictly inside `max_spread_cents` of the mid |
| `tightest_eligible_bid`, `tightest_eligible_distance_cents`, `cash_needed_pusd` | Highest tick at or below the mid that does not cross the ask, its distance, and `min_size` times that price |
| `our_pool_percentage` | The reader's current pool percentage for the condition, else `null` |
| `status`, `errors` | `observed`, `no_active_reward`, `reward_terms_unavailable`, `book_unavailable`, `two_sided_mid_unavailable`, `no_eligible_bid_inside_band`, `reward_terms_incomplete` or `budget_deferred` |

Approximations, also listed in each file's `notes`: the venue's own midpoint and
sampling instants are not observable; distance is measured against the pre-quote
mid, so a quote that becomes the new best bid moves the mid it is scored against;
displayed size aggregates makers, so resting size can include sub-minimum orders.
No reward share, fair value or edge is computed: that is policy, not this tool.

## Commands

On the workstation, from the repository root:

```powershell
.\scripts\ops\run_reward_scan.ps1 -WhatIf
.\scripts\ops\run_reward_scan.ps1 -Once
.\scripts\ops\run_reward_scan.ps1 -IntervalMinutes 15
.\scripts\ops\run_reward_scan.ps1 -IntervalMinutes 15 -Condition 0x<64 hex> -NoReader
.\venv\Scripts\python.exe -m weather.market.reward_scan scan --out data\reward_scan
```

The loop is foreground and owner-started; Ctrl+C stops it. There is no Scheduler
registration. Each iteration's deadline is the interval less two minutes. Without
a reader client config the scan still completes with
`pool_percentage_status: reader_config`.

## Update this file when

The scanned routes, the allow-list, output fields or path, the runner parameters,
or the import-isolation ratchet change.
