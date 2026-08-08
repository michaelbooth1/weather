# Agent report 2026-08-07 — restore the settlement source

## Verdict

**GO for quiet-window merge review: the free page-backed WU history route is
working again and the repaired client preserves the v1 observation and derived
daily-summary contracts. The workstation closed 4 of 6 requested stored-truth
cells exactly; production must close the two missing 2026-06-15 F-market
controls before merge because those rows are absent from this workstation's
retained `data/`.**

The fix does not add a credential, environment variable, paid-provider path, or
replacement settlement proxy. It reads the same runtime `API_URL` and
`API_KEY` globals used by the public page's own historical-observations model.
The scraped key was never printed, logged, written, or committed.

## Root cause and repaired route

The public page injects one runtime configuration object. On the measured
Toronto page it contained a 32-character `API_KEY` and an `API_URL` for the
provider API host. The page also contained one unrelated URL query token; the
two tokens were not equal. `PublicWundergroundHistoryClient` selected the first
URL carrying `apiKey=`, so it sent the unrelated token to the history endpoint.

Using the runtime global instead produced:

| Probe | Result |
| --- | --- |
| Public Toronto history page | HTTP 200 |
| Runtime configuration objects found | 1 |
| Runtime key length | 32 |
| First embedded URL token equals runtime key | false |
| Runtime-key v1 history request, Toronto 2026-06-15 | HTTP 200 |
| Observations | 24 |
| Fields per observation | 45 |
| Top-level payload keys | `metadata`, `observations` |

The client now JSON-decodes the page-injected `const data = {...}` object,
requires non-empty `API_URL` and `API_KEY` strings, and ignores unrelated token
URLs. It still calls the v1 location history endpoint and returns its payload
unchanged apart from the existing `_wu_collector_provenance` wrapper. No parsed
row or daily-summary field changed.

The implementation reproduces the unmerged
`codex/fix-wu-404-classification-2026-08-06` change rather than stacking on it:
page-backed 404s are transient and stay fetchable, page-backed 400s remain
permanent, and the disabled legacy paid-path 404 classification remains
permanent. Previously poisoned page-backed 404 error rows can now be released
by the existing recovery path.

## Stored-truth comparison

The crossed design kept both dates and all three markets separate; no rows were
pooled. Numeric fields used absolute tolerance `1e-9`; dates, times,
categoricals, booleans, missingness, and schema labels required exact equality.
This is a deterministic contract comparison, so no statistical interval was
constructed.

One 2026-06-15 through 2026-07-10 range fetch was made per market, with a
two-second pause between markets:

| Market | Native unit | Fresh observations | 2026-06-15 | 2026-07-10 |
| --- | --- | ---: | --- | --- |
| Toronto / CYYZ | C | 738 | **29/29 match** | **29/29 match** |
| Atlanta / KATL | F | 706 | stored row absent | **29/29 match** |
| NYC / KLGA | F | 709 | stored row absent | **29/29 match** |

All six live target rows were returned. Every comparable field matched and no
field differed. A repository-wide search of workstation
`data/**/daily_summary.csv` found the 2026-06-15 row only under CYYZ; all twelve
stations retained 2026-07-10. The two missing F controls are therefore missing
comparison evidence, not mismatches, and are left as a production-host
acceptance condition rather than silently upgraded.

Fifteen gentle provider GETs were made across route discovery and acceptance.
No 429, disconnect, or retry was observed. The steady-state client uses one
page GET and one history GET per market-day, or 24 GETs for the current
12-market daily fleet. This was not a rate-limit load test, but nothing observed
indicates that cadence is infeasible.

## Changed files and roll verdict

| File | Purpose | Roll verdict |
| --- | --- | --- |
| `src/weather/sources/wu_history.py` | Runtime-global access extraction, redaction, and page-backed 404 classification | **ROLL: snapshot (`loop`) and observation-trigger** |
| `tests/sources/test_historical_sources.py` | Offline route, output, redaction, and failure-class regressions | roll-free |
| `tests/fixtures/wu_history_page_runtime_config.html` | Sanitized recorded page-runtime shape with a deliberately unrelated URL token | roll-free |
| `tests/fixtures/wu_history_v1_response.json` | Recorded 45-field v1 observation fixture | roll-free |
| `docs/operations/HISTORY_DATA_DESIGN.md` | Owning route and failure-class contract | roll-free |
| `docs/roadmap/agent-report-2026-08-07-workstation-restore-the-settlement-source.md` | This handback | roll-free |

Mechanical command:

```powershell
powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File scripts\ops\roll_verdict.ps1 -Branch codex/workstation-restore-the-settlement-source-2026-09-37a
```

Result on the final branch: `changed=6`, `importable=1`,
`wu_history.py -> loop,observation_trigger`, **`VERDICT: ROLL-SENSITIVE`**, exit
`3`. The dormant CLOB-enrichment closure was 264.4 hours old but mechanically
subsumed by live closures. Merge only in the 01:00–04:00 quiet window.

## Verification

| Command / check | Result |
| --- | --- |
| `python -m pytest tests\sources\test_historical_sources.py -q` | 44 passed |
| `python -m pytest tests\sources -q` | 154 passed, 1 unrelated binary-compatibility warning |
| `python -m compileall -q src\weather tests\sources` | passed |
| `python -m weather.operations.agent_docs_audit` | passed |
| tracked-or-ignored architecture ratchet after staging fixtures | passed |
| paid-provider policy-term ratchet | fails only on three files already in `origin/master`: the commissioned handoff and two incident/state documents; no changed file is an offender |

The full suite did not reproduce the handoff's stated four-failure baseline. It
finished `3318 passed, 4 skipped, 20 failed`; after the newly added fixtures
were staged, the one branch-caused tracked-or-ignored failure passed in
isolation. The remaining 19 are outside this diff: 13 experiment-executor
Windows path-length failures, four PowerShell execution-policy failures, the
three-existing-document policy-term ratchet above, and the existing unregistered
`severe_tail_ex_ante_casebook_v0.1` schema finding. No WU/source test failed.

## Production-host reproduction

Run from the production repository after fetching this branch. The parity
snippet is read-only with respect to `data/` and redacts any exception URL.

```powershell
Set-Location 'C:\Users\micha\Desktop\github\weather'
git fetch --prune origin
powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File scripts\ops\roll_verdict.ps1 -Branch origin/codex/workstation-restore-the-settlement-source-2026-09-37a
```

Create an isolated branch review worktree using the production repository's
venv:

```powershell
$reviewRoot = 'C:\Users\micha\Desktop\github\weather-review-09-37a'
git worktree add $reviewRoot --detach origin/codex/workstation-restore-the-settlement-source-2026-09-37a
Set-Location $reviewRoot
$env:PYTHONPATH = "$reviewRoot\src"
$code = @'
import csv
import time
from datetime import date
from decimal import Decimal, InvalidOperation

from weather.market.market_registry import ATLANTA, NYC, TORONTO
from weather.sources.wu_history import (
    PublicWundergroundHistoryClient,
    normalize_observation,
    redact_api_key,
    summarize_daily,
)

targets = (date(2026, 6, 15), date(2026, 7, 10))
tolerance = Decimal("1e-9")

def equal(actual, expected):
    left = "" if actual is None else str(actual)
    right = "" if expected is None else str(expected)
    if not left and not right:
        return True
    try:
        return abs(Decimal(left) - Decimal(right)) <= tolerance
    except InvalidOperation:
        return left == right

for index, spec in enumerate((TORONTO, ATLANTA, NYC)):
    if index:
        time.sleep(2.0)
    client = PublicWundergroundHistoryClient(
        history_id=spec.wu_history_id,
        station_icao=spec.icao,
        units=spec.wu_units,
    )
    try:
        payload = client.fetch_range(targets[0], targets[-1], units=spec.wu_units)
    except Exception as exc:
        print(spec.id, "FETCH_ERROR", redact_api_key(str(exc)))
        continue
    normalized = [
        row for observation in payload.get("observations", [])
        if (row := normalize_observation(observation, spec.tz, unit=spec.display_unit))
        is not None
    ]
    fresh = {row["local_date"]: row for row in summarize_daily(normalized)}
    with (spec.data_root / "daily" / "daily_summary.csv").open(
        "r", encoding="utf-8", newline=""
    ) as handle:
        stored = {row["local_date"]: row for row in csv.DictReader(handle)}
    for target in targets:
        key = target.isoformat()
        if key not in fresh or key not in stored:
            print(spec.id, key, "MISSING", "fresh" if key not in fresh else "stored")
            continue
        differences = {
            field: {"fresh": fresh[key].get(field), "stored": value}
            for field, value in stored[key].items()
            if not equal(fresh[key].get(field), value)
        }
        print(spec.id, key, f"{len(stored[key]) - len(differences)}/{len(stored[key])}", differences)
'@
$code | & 'C:\Users\micha\Desktop\github\weather\venv\Scripts\python.exe' -
```

Expected acceptance is `29/29 {}` for all six cells. Do not merge if a stored
row exists and any field differs.

## What was not done

No production `data/` was written; no backfill, chain, settlement, label
finalization, recovery run, registration, task mutation, capture restart,
candidate, release, live trade, merge, or PR was performed. The workstation
only fetched public WU/provider page-backed data allowed by the handoff. The
temporary probe scripts and roll-verdict clone were removed after use.

## Commit and branch

- Implementation commit: `e6a89db2` (`sources: restore public WU history access`)
- Branch: `codex/workstation-restore-the-settlement-source-2026-09-37a`
