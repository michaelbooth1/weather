# The WU settlement source went down — root-caused and fixed 2026-08-07

Status: **root cause found, fix verified on production, awaiting the quiet-window merge.**
Supersedes the framing in
[the 404 classification note](2026-06-21-wu-history-current-day-degradation.md) and every
"use `-Refetch`" instruction written on 2026-08-06.

## Root cause — we were sending an advertising key to the weather API

`public_access_from_page` scanned the history page for *any* URL carrying an `apiKey=`
parameter and took the first match. That match was
`https://weather.com/api/v1/mew/entity/ad_third_party_config/...?apiKey=...` — **the page's
third-party advertising config**. The client then used that host and that key for the
observations call.

This explains both symptoms exactly, and neither is an outage:

- **404 on `<wu-provider>/v1/...`** — the host came from the ad URL, and it does not serve the
  observations route at all.
- **401 on `api.<wu-provider>/v1/...`** — the correct host, presented with an advertising key.

`-09-37a` replaces the regex with a parse of the page's injected runtime config
(`const data = {... "API_URL": ..., "API_KEY": ... }`), which is what the browser itself uses.
It resolves to the provider API host with the page's own 32-char token.

**The date-independence was the clue and it was mis-read.** Every date failing, including ones
already stored, meant the *request* was wrong, not the data. It was read as "the endpoint is
gone" instead. When a source fails uniformly across every key you vary, suspect the part you
are not varying.

## Verification on the production host, 2026-08-07

Run from an **isolated git worktree**, never the live working tree — `wu_history.py` is in the
snapshot and observation-trigger closures and a checkout would have rolled capture.

| Check | Result |
| --- | --- |
| `2026-06-15` Toronto vs stored `daily_summary.csv` | **24 observations, max 20, min 10** — stored row is `row_count 24, max_temp 20.0, min_temp 10.0` |
| `2026-08-05`, `2026-08-06` Toronto | **OK** — 24 and 34 observations |
| `2026-08-05`, `2026-08-06` NYC | **OK** — 26 and 31 observations, in °F as configured |
| Payload shape | unchanged 45-field v1 observations |
| `tests/sources/test_historical_sources.py` | 44 passed |

The 08-05 / 08-06 fetches are the dates that were actually blocking settlement.

**Rate limiting is real.** Probing five dates back-to-back drew failures that a 12-second
spacing did not. Space requests; do not read a burst failure as a route failure.

## Branch supersession

`-09-37a` **contains all of** `codex/fix-wu-404-classification-2026-08-06` —
`PAGE_BACKED_PERMANENT_NO_DATA_STATUS_CODES`, `PAGE_BACKED_EXCEPTION_ATTR`, `_raise_for_status`
and the `failure_class_for_error_row` re-derivation. **Do not merge that branch as well**; it is
superseded and would conflict.

## Original diagnosis, kept because the reasoning matters

## What is true

`<wu-provider>/v1/location/<history_id>/observations/historical.json` returns **404 for every
date**, not for a missing day. The settlement chain has been stuck since **2026-08-04**.

| Probe (Toronto, `CYYZ:9:CA`) | Result |
| --- | --- |
| `2026-08-05`, `2026-08-06` — unsettled dates | **404** |
| `2026-08-04` — **a date already stored locally** | **404** |
| `2026-06-15`, `2026-07-10` — long-settled dates | **404** |
| `https://weather.com/v1/.../observations/historical.json` | **404** |
| `the provider API host/v1/.../observations/historical.json` | **401** |
| `https://www.wunderground.com/history/daily/CYYZ/date/2026-8-5` | **HTTP 200**, 48,121 bytes |
| `public_access_from_page` on that page | **succeeds**, 32-char token |

**404 versus 401 is the whole diagnosis.** The route still exists on `api.<wu-provider>`; it
rejects the token the history page hands out. The page-scrape half of the client still works and
the API half does not.

The page carries **no** observation payload to fall back on: `valid_time_gmt` occurs 0 times,
`__NEXT_DATA__` 0 times. The only versioned API paths it references are an ad config and a
script loader. A naive "parse the page instead" will not work.

## What this is NOT

- **Not a poisoned date.** `-Refetch` **worked**: the 01:30 recovery genuinely re-attempted all
  12 markets — fresh `recorded_at_utc` of 05:31–05:34, `transient_retry_count: 0`,
  `fetched 0`, `blocked 12`. It did not skip. The fetch was made and returned 404.
- **Not fixed by the classification branch.** `codex/fix-wu-404-classification-2026-08-06` is
  still worth merging — it stops dates being stamped `treated_as_source_unavailable` so they
  stay retryable once a route works — but **it does not restore settlement.**
- **Not a per-station outage.** All 12 markets across 3 countries fail identically.

## Blast radius

| | |
| --- | --- |
| Settlement | frozen at **2026-08-04** |
| Toronto streak | **15 / 14, banked and safe** — but frozen, and it cannot advance |
| Learning loop, promotion, MM countability | all downstream of settlement |
| Capture (snapshot, CLOB, observation-trigger) | **unaffected** — independent of WU history |

The banked 07-21 → 08-04 window survives in the ledger. What is at risk is *future* contiguity:
if 08-05 and 08-06 never settle, a later 14-day window restarts from whenever settlement resumes.

## The standing architectural risk, now realised

`AGENTS.md` makes configured Weather Underground history **the** settlement proxy. 26 source
adapters feed features; one unowned scraped source decides truth. This is the third failure of
that dependency and the first that no retry, reclassification, or flag can repair.

Any durable fix should be judged on whether it reduces that single point of failure, not only on
whether it makes today's fetch work.

## Reproduce

```powershell
$repo = 'C:\Users\micha\Desktop\github\weather'
Set-Location $repo
.\venv\Scripts\python.exe -c @"
import datetime as dt
from weather.sources.wu_history import PublicWundergroundHistoryClient
c = PublicWundergroundHistoryClient(history_id='CYYZ:9:CA', station_icao='CYYZ', units='m')
for d in ('2026-06-15','2026-08-04','2026-08-05'):
    day = dt.date.fromisoformat(d)
    try: print(d, 'OK', len(c.fetch_range(day, day)))
    except Exception as e: print(d, 'FAIL', getattr(getattr(e,'response',None),'status_code','-'))
"@
```

Never print the scraped token. `redact_api_key` exists in `weather.sources.wu_history` for
exactly this.

## The source was fixed and the CHAIN then blocked it — 2026-08-08

`-09-37a` merged 01:20 on 08-08 and **works**: `public_wu_settlement_restore` ran 699 s over 40
processes and read 15.9 GB. It then failed `containment_setup_failed` on **one transient
`OSError [Errno 31]` in 1 of 3,402 capture calls** — `process_identity_query_failed`, a process
exiting between handle-open and job-membership query. 18 of the 19 lifetime checks passed.

**The blast radius is the whole chain, not just settlement.** `public_wu_settlement_restore` is
step 4 of ~45. Everything after it never ran, including `market_day_labels_finalize`,
`maker_paper_score`, `trading_evidence`, `daily_learning` and
`market_beating_objective_scoreboard` — which is why every `mm_*` field in the daily report reads
`null` and variant learning reads `SKIPPED`. It is not that MM evidence was bad; **it was never
computed.**

Fixed by `codex/production-tolerate-benign-capture-race-2026-08-08` (queued 01:20 on 08-09):
`no_capture_failures` becomes `no_unexplained_capture_failures` over a benign set of exactly one
kind. Containment is unchanged — `every_job_process_observed`, `job_quiesced` and
`no_job_limit_terminated_processes` stay mandatory, so a skipped-but-still-Job-bound process still
FAILS the summary.

### Backfill runbook — REQUIRED after the fix lands

**Each chain run settles only *yesterday*, so the fix alone does not heal 08-05 → 08-07.** Those
three dates need an explicit run each. Confirm the fix is on master first
(`git log --oneline -1 origin/master`), then, **inside the 01:00–04:00 quiet window or at least
outside 12:00–18:00**, one date at a time, checking each before starting the next:

**Use `scripts\ops\chain_recovery_run.ps1`, not a hand-rolled `daily_refresh` command.** It is the
purpose-built resume tool and it **refuses to start inside 12:00–18:00** unless `-Force`, because a
heavy chain in the graded window is the top cause of capture gaps — which cost streak days. A raw
`daily_refresh run` has no such guard. (I drafted the raw command first; the tool already existed.)

```powershell
$repo = 'C:\Users\micha\Desktop\github\weather'
Set-Location $repo
foreach ($d in '2026-08-05','2026-08-06','2026-08-07') {
    powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\ops\chain_recovery_run.ps1 `
        -ResumeFrom public_wu_settlement_restore `
        -TargetDate $d
    # STOP if this exits non-zero. Do not queue the next date on top of a failure.
}
```

**Resume from the step that actually FAILED, not from the barrier that reported it** — the barrier
re-reads the earlier step's persisted BLOCK artifact and just blocks again.

Then confirm the ledger actually advanced — the run exiting 0 is not the same as a settled date:

```powershell
Get-Content data\settlements\toronto\ledger.jsonl -Tail 3
```

**Expect the chain to take a long time and to hold memory.** `public_wu_settlement_restore` alone
peaked at 3.3 GB private / 2.0 GB working set against a 4 GB cap. Do not run it while capture is
under pressure; the host has 16 GB and each capture worker needs 3.49 GB free to admit.

## Update this file when

A working route is found, the client is adapted, or the settlement proxy contract changes.
