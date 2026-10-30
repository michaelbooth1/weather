# WS T+1 price forward recorder (lane L3, 2026-10-30)

This is a dated research note, not canonical guidance. It records the comparator for the T+1 forward test draft
(`docs/research/t1-forward-prereg-2026-10-30/README.md` on `claude/t1-forward-prereg-20261030`), whose freeze
precondition P1 asks for 3 days of closed manifests from this recorder.

**Status: built and tested; NOT registered and NOT running.** Registration needs the owner's yes in the coordinator's
chat, and the coordinator registers it. Captured prices are forward data. This lane does not analyse them, and the
recorder reads no outcome, settlement or label.

## Why

Master checked the host on 2026-10-30. `WeatherClobBookLoopSupervisor` runs with `date_selection = market_local_date`,
so it records T+0 books only. 88a records a top-ten partial universe (`maker_evidence_public.select_universe`). So no
full T+1 ladder was captured anywhere.

## What is recorded

| Item | Value |
| --- | --- |
| Markets | the 12 built-ins: the 10 US markets other than Denver, Toronto (CYYZ), and Denver (KDEN, kept because it costs nothing). Read from the default registry; refuses if `WEATHER_MARKET_REGISTRY` is set |
| Events | T+1 and T+2, where the target date is the market-local date at the slot plus 1 or 2 days. The slug follows the `event_slug_for_date` rule (a test checks it) |
| Slots | every UTC quarter-hour, which is every local top of hour for these whole-hour zones plus :15/:30/:45. `--top-of-hour-only` drops the quarter points |
| Price | Gamma `outcomePrices`, the entry labelled "Yes" (chosen by label, not position). This is the T+0 layout's `market_yes` definition |
| Book | CLOB best bid and best ask of each band's YES token: the max bid and min ask over levels with size > 0, with their sizes and the book `timestamp`. `last_trade_price` is never recorded |
| Ids | event id and slug; per band the condition id, Gamma market id, label, and active/closed/acceptingOrders flags |
| Receipt | `gamma_received_utc` and `books_received_utc`: our clock when each reply arrived |
| Checks | per event: `n_bands`, `n_yes`, `yes_sum`, `ladder_complete` (every band has a finite Yes price), `sum_in_range` (0.90 to 1.10) and `n_book_two_sided` |

## Endpoints (public, read-only, International Polymarket only)

- `GET https://gamma-api.polymarket.com/events/slug/<slug>`
- `POST https://clob.polymarket.com/books` with a body of at most 50 `{"token_id": ...}` items. This is the public batch
  book read that 88a already uses.

`check_url` refuses everything else before any socket opens, including:

- any other host or path;
- any query, fragment, port or userinfo;
- any other body shape.

The recorder uses stdlib `http.client` only. It sends no cookies, no auth header and no credential. It does not import
`weather.market` client, account or order modules. Its only repository import is `weather.market.market_registry`.
It opens no `.env*`, `*.cred`, `*.key`, `*.pem` or `config/local/*` file. A test pins the import set.

## Layout and integrity

- **Output:** `C:\t\t1_prices\forward\<YYYYMMDD UTC>\prices.jsonl`, append-only.
- **One cycle, one append:** each slot's event rows and then one `cycle` record go out in a single fsynced append.
- **Cycle record:**
  - `rows_sha256` over its event rows. A reader trusts event rows only when a matching cycle record follows them.
  - `complete`, meaning every expected event was fetched with a complete Gamma ladder, or else `reasons` saying why
    not.
  - `late`, true when the cycle started more than 10 minutes after the slot.
- **Day manifest:** after a UTC day ends, `<day>/manifest.json` holds:
  - cycle counts, complete counts and the number of missing top-of-hour cycles;
  - the file sha256 and the recorder sha256.

  On restart, any earlier day still open is closed.
- **No backfill:** prices cannot be fetched after the fact. A slot is attempted only within 10 minutes of its start, and
  missed slots go to `gaps.jsonl` (as do pause start and end).
- **Guards**, as the L13 recorders have:
  - below-normal priority;
  - a 0.2 s request spacing and a 4,000-request hourly ceiling;
  - a 20 GB per-process network cap;
  - `RECORDER_PAUSE` and `STOP` files;
  - a single-instance lock;
  - a 20 GB free-disk floor;
  - a 2 GB output cap.

## Volume (from the dry run)

- About 2.8 MB downloaded and 48 requests per cycle, so about 270 MB/day at 96 cycles.
- About 127 KB kept per cycle, so about 12 MB/day; the 2 GB cap is about 160 days.

## Running

- **Dry run, one foreground cycle:**

  ```
  venv\Scripts\python.exe tools\research\t1_price_forward_recorder.py --out C:\t\t1_prices\dryrun --once
  ```

- **Launcher:** `tools\research\t1_price_forward_recorder_launch.ps1`.
  - It starts the recorder WMI-detached, pinned to the recorder's git blob in `C:\wt\l3t1rec`.
  - It refuses when the STOP file exists, when a recorder is alive, or when the blob differs.
- **Registrar:** `tools\research\register_t1_price_forward_recorder_task.ps1`.
  - Task name `L3 T+1 price forward recorder (logon)`.
  - Shape: AtLogOn with a PT5M delay, Interactive/Limited, IgnoreNew, StartWhenAvailable off, a 10-minute limit for
    the launcher only.
  - It requires `-ExpectedLauncherSha256`.
  - It validates the task name: no `/ \ : * ? " < > |`, and no leading or trailing space.
  - It refuses the real ScheduledTasks module under `WEATHER_TASK_TEST=1`.
  - Run it with `-WhatIf` first.
- **Tests:**
  - `tests/sources/test_t1_price_forward_recorder.py` uses an offline fake and makes no network calls.
  - `tests/sources/test_t1_price_forward_recorder_registrar.py` uses L13's import-then-stub harness with fake task
    names.
- **Stop:** `New-Item C:\t\t1_prices\forward\STOP`.
