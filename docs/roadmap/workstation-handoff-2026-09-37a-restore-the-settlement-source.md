# Workstation handoff 2026-09-37a — restore the settlement source

Written 2026-08-07 by the production agent. Read on `origin/master` and execute.
**This is the top operational item on the project. Nothing else is running.**

## 1. Goal

**Find a free, page-backed route that returns Weather Underground historical observations
again, and adapt `PublicWundergroundHistoryClient` to use it** — so settlement can advance past
2026-08-04.

## 2. Why this, and why now

Settlement is **frozen at 2026-08-04**. Everything downstream is stopped with it: the learning
loop, the market-beating scoreboard, promotion, and MM countability. The Toronto streak is
**15/14 banked and safe**, but it cannot advance, and if 08-05/08-06 never settle a future
14-day contiguous window restarts from whenever settlement resumes.

## 3. Start from this — it is measured, do not re-derive it

Full evidence: **[`docs/operations/wu-settlement-source-down-2026-08-07.md`](../operations/wu-settlement-source-down-2026-08-07.md)**. In short:

| Probe (Toronto `CYYZ:9:CA`) | Result |
| --- | --- |
| `2026-08-04` — **a date already stored locally** | **404** |
| `2026-06-15`, `2026-07-10` — long-settled | **404** |
| `<wu-provider>/v1/.../observations/historical.json` | **404** |
| `api.<wu-provider>/v1/.../observations/historical.json` | **401** |
| `wunderground.com/history/daily/CYYZ/date/2026-8-5` | **200**, 48,121 bytes |
| `public_access_from_page` on that page | **succeeds**, 32-char token |

**404 vs 401 is the diagnosis.** The route still exists on `api.<wu-provider>`; the token the
history page exposes is no longer valid for it. The page-scrape half of the client works; the
API half does not.

**Do not re-open:** whether this is a poisoned date (it is not — `-Refetch` genuinely
re-fetched and got fresh 404s), whether it is per-station (all 12 markets, 3 countries, fail
identically), or whether the page can be parsed directly (`valid_time_gmt` and `__NEXT_DATA__`
occur **zero** times in it).

## 4. The binding constraint — read this before designing anything

**Paid weather-provider access is unsupported** (`AGENTS.md`, non-negotiable; operator decision
2026-08-05). The 401 from `api.<wu-provider>` is a *paid-key* wall. **You may not add an API key,
a credential, a required environment variable, or any plan that depends on one.** A fix that
works only with a purchased key is a NO-GO and should be reported as such, not implemented.

The target is the route **the page's own JavaScript uses**, which carries its own short-lived
token — the same class of access the current client already relies on.

## 5. Prioritised work

### P0 — find a working free route

Reverse how the history page actually loads its observations table: read the page's JS bundles,
follow the token it exposes, and try the API hosts/versions/paths it references. Vary host
(`api.<wu-provider>`, `<wu-provider>`), version (`v1`, `v2`, `v3`), and path shape
(`.../observations/historical.json`, `v3/wx/observations/historical`, geocode-based variants),
and the header set — `Referer`, `Origin`, and `User-Agent` are already load-bearing in
`_headers`.

**Be gentle.** One probe already drew a `RemoteDisconnected`. Sleep between calls, keep total
request volume low, and never hammer a 4xx in a loop.

### P1 — adapt the client, preserving the output contract

Change `src/weather/sources/wu_history.py` so `fetch_range` works again. **The parsed row schema
must not change.** Everything downstream — `daily_summary.csv`, label finalization, the ledger,
captured-input replay — depends on it. If the new route returns a different payload shape, map
it back to the existing schema rather than propagating the change outward.

### P2 — the acceptance test that actually proves it

**Regression against stored truth.** We already hold verified observations for dates the source
now 404s. Fetch **2026-06-15** and **2026-07-10** for at least Toronto plus two F-markets with
the repaired client, and compare field-by-field against the stored rows in
`data/wunderground/<station>/daily/daily_summary.csv`.

**A route that returns data but different values is a failure, not a success.** Report the
comparison explicitly — matching field count, any field that differs, and the tolerance used.

## 6. Method — binding

- **Never print, log, or commit the scraped token.** `redact_api_key` exists in
  `weather.sources.wu_history` for exactly this. Check your report before committing.
- Add tests with **recorded fixtures**, not live calls. The existing suite must stay runnable offline.
- `pytest -q` is **red on master** before you start — 4 unowned failures listed in
  `STATE_OF_PLAY.md`. Diff against those; do not claim you broke or fixed them.

## 7. Boundaries

`DELEGATION_CONTRACT.md` §2 in full, with one **explicit exception**: this mission **may make
provider calls to Weather Underground / weather.com**, because probing the route is the task.
No other provider, no market endpoint, no paid service.

- **Do not** write production `data/`, run the chain, run `chain_recovery_run.ps1`, settle a
  date, or backfill anything. Repair the client; production will use it after merge.
- **Do not** change the settlement-proxy contract. If you conclude WU cannot be restored free,
  that is a finding for the operator, **not** a licence to switch sources.
- `wu_history.py` is **ROLL-SENSITIVE** — it sits in the snapshot and observation-trigger
  closures. Expect `roll_verdict.ps1` exit 3. That is correct and does not block you; it means
  production merges it in the 01:00–04:00 quiet window. **Pushing a branch never rolls anything.**
- Coordinate with `codex/fix-wu-404-classification-2026-08-06`, which also edits this file and is
  unmerged. Prefer rebasing onto it or reproducing its change, and say which you did.

## 8. What would falsify this mission

- **No free route exists.** Report it plainly with what you tried. That is a major architectural
  decision for the operator — the settlement proxy would need to change — and it is worth more
  than a workaround.
- **A route returns data that does not reproduce stored truth.** Report the mismatch; do not ship it.
- **Rate limits make 12 markets/day infeasible.** Say so with the observed limit; that changes
  the capture design, not just the client.

## 9. Branch and report

- Branch: `codex/workstation-restore-the-settlement-source-2026-09-37a`
- Report: `docs/roadmap/agent-report-2026-08-07-workstation-restore-the-settlement-source.md`

Per `DELEGATION_CONTRACT.md` §5, with production-host reproduction paths and a per-file roll
verdict from **`scripts\ops\roll_verdict.ps1 -Branch <branch>`** — do not derive it by hand.
**Commit and push whenever you finish**; pushing cannot roll production capture.
