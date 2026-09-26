# Agent report 2026-09-100d — wallet reader classification, budgets and partial results

**IMPLEMENTED; fixture verification PASS. No real-account validation or reader
restart in mission 100d. Production adoption remains owner/production-agent work.**

Answers [handoff 100d at the fetched master commit](https://github.com/michaelbooth1/weather/blob/20d9fd37c7f45e102a9b11b4f3192d4746e88aba/docs/roadmap/workstation-handoff-2026-09-100d-wallet-reader-fixes.md).
Branch: `codex/wallet-public-reader-20260925`.
Implementation tip: `a448927c6a8d32eeddfd643c1a00a6a9b8f612f5`.
The requested fetch/reset targeted the remote branch, which had advanced beyond
`1e89fc250` to `088d157e107cc856a39b2785f6d97f89f6fb7caa` (the published dotenv
dependency repair). This work preserves that history. Report and generated-index
commits follow the implementation; resolve the final delivered tip with:

```powershell
git ls-remote origin refs/heads/codex/wallet-public-reader-20260925
```

## Diagnosis and changes

The existing workstation request journal for 2026-09-25, inspected as metadata
only, contains 25 book attempts (23 HTTP 404, two HTTP 200), 25 separate Gamma
market attempts (all HTTP 200), and no market-reward attempts. The retained span
was 12:20:00.716247–12:21:37.738638 America/Toronto. Positions, cash, orders,
authenticated trades, public trades and activity had successful HTTP reads.
This supports repeated book/metadata fan-out and absent books as contributors.
It does **not** prove every null mark was caused by the minute cap: the journal
omits response bodies and pre-socket refusals, so parsing failures and exact
budget exhaustion cannot be reconstructed. No new request was made to confirm it.

- Discover positions first, then obtain one Gamma batch using repeated
  `condition_ids` query values. A redeemable row or Gamma `closed=true` is
  resolved; `closed=false, active=true` establishes live. Expired dates and zero
  prices alone do not establish resolution. Unknown rows remain explicit.
- Request books and public rewards only for live rows. Resolved rows include
  size, redeemable status and last price in `resolved_positions`; the client
  exposes them with `--include-resolved`. Default output retains their count.
- Plan enrichment in descending reported value against the remaining shared
  minute budget, with at most 24 new GETs per summary/positions response.
  Cached upstream reads cost zero. Unfinished rows carry `budget_deferred`.
  Cash and orders are read first and survive inventory/mark failures.
- Preserve independent host/path/query caches: successes 30 seconds, failures
  at most 10 seconds. No composite result is cached. Response field failures
  appear in an `errors` map; row errors stay on their rows.
- Add a 16-second planning deadline and clip each upstream socket timeout to
  remaining time. The client defaults to 20 seconds; `--timeout` accepts 5–120.
  Client errors retain `wallet_reader_client_failed` plus `timeout`,
  `http_<status>`, `refused`, or `config`, without raw exception text.
- Preserve hidden resolved value in summary equity using terminal last prices
  only (0 or 1). Unknown resolution/value or incomplete live marks prevents
  aggregate P&L. This is an indicative mark, not redemption or liquidation proof.

The `/positions` API now returns an object containing live/resolved/unknown
lists, errors, status and plan rather than a bare list. Resolved rows are omitted
unless requested; hiding them never changes equity. The updated
[runbook](../operations/wallet-reader.md) owns this response and timeout contract.

The deadline bounds new-call fan-out, not a strict wall-clock SLA for DNS,
trickling response bodies, disk latency or requests queued behind this serial
server. No real-network latency claim is made. Discovery remains bounded by the
existing five-page limit; incomplete discovery is explicit, not empty inventory.

## Fixture evidence and verification

All account identifiers, credential fields and HTTP replies in tests are
synthetic. Reader tests prohibit socket connect/bind. Credential tests use
temporary synthetic files only; no actual `.env` or client credential file was
opened. No signing client was imported and no private-key field was selected.

| Acceptance case | Observed result |
| --- | --- |
| 104 positions: 100 resolved dust before four live rows | Four live marks; 13 GETs total: cash, orders, two position pages, one Gamma batch, four books, four rewards. Zero resolved book/reward requests. |
| 20 live positions, cold summary | 24 GETs; ten highest-value rows marked, ten `budget_deferred`; cash/orders retained, P&L unknown. |
| 24 prior minute attempts | Remaining six GETs admit discovery and two live marks; cached retry uses zero GETs and retains those marks. |
| Book 404 | Cash/orders remain readable; failed book reused at 9.999 seconds and retried at 10; successful keys stay cached. |
| Cash, order or position failure | HTTP 200 partial summary with field error, no composite cache poisoning or secret leakage. |
| Slow upstream simulation, four live plus 0 or 100 dust | Six simulated calls, 16 seconds of fake time; deadline stops new reads and flags deferral. No sleeps or real network. |
| Missing metadata; old date/zero price; closed nonterminal row | Unknown or unavailable value stays explicit; no speculative books or fabricated P&L. |
| Client and LAN boundary | Default 20 seconds, configurable floor five, safe reason codes, resolved flag validation, existing token/IP/origin/GET checks pass. |

- **154 passed**: wallet reader, schema registry and import architecture tests.
- **29 passed**: agent documentation audit, correspondence index and roadmap
  backlog tests (before adding this report; final index/audit verification follows
  source commit as required by the correspondence workflow).
- `compileall -q app src tests`: PASS.
- `git diff --check`: PASS.

All pytest/compilation commands ran serially through `workstation_heavy.ps1` as
the attending principal. No workload gate was changed. These are deterministic
software checks, not an economic measurement; clustering/intervals do not apply.
Open-question IDs: none assigned by the handoff.

Reproduce on the non-capture workstation from the branch checkout; paths derive
from the current Git worktree and its common checkout, not a scratch location:

```powershell
$readerRepo = (Get-Location).Path
$readerCommonGit = (Resolve-Path (git rev-parse --git-common-dir)).Path
$readerPython = (Resolve-Path (Join-Path (Split-Path $readerCommonGit -Parent) 'venv\Scripts\python.exe')).Path
$readerArgs = @('-m','pytest','tests/market/test_wallet_reader.py','tests/operations/test_schema_registry.py','tests/operations/test_import_architecture.py','tests/operations/test_agent_docs_audit.py','tests/reporting/test_correspondence_index.py','tests/reporting/test_roadmap_backlog.py','-q','--basetemp',"$readerRepo\scratch\wallet-reader-100d-tests")
$readerEncoded = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes((ConvertTo-Json -InputObject $readerArgs -Compress)))
& "$readerRepo\scripts\ops\workstation_heavy.ps1" -Kind pytest -PythonPath $readerPython -ArgumentsBase64 $readerEncoded -RepoRoot $readerRepo
$readerCompile = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes('["-m","compileall","-q","app","src","tests"]'))
& "$readerRepo\scripts\ops\workstation_heavy.ps1" -Kind compileall -PythonPath $readerPython -ArgumentsBase64 $readerCompile -RepoRoot $readerRepo
```

Remove only the verified task-specific pytest directory after verification.
Capture-host qualification must instead use its existing admitted bounded-suite
path and timing gates; the workstation command does not authorize production tests.

## Roll disposition and boundaries

Executed `scripts/ops/roll_verdict.ps1 -Branch codex/wallet-public-reader-20260925`:
**UNDECIDABLE: no live closure evidence**. The tool reports absent snapshot, CLOB,
observation-trigger and enrichment status files. No closure membership is invented.

| File changed by 100d | Per-file disposition |
| --- | --- |
| `src/weather/market/wallet_reader.py` | Closure membership unavailable; re-derive on production. |
| `src/weather/market/wallet_reader_transport.py` | Closure membership unavailable; re-derive on production. |
| `src/weather/market/wallet_reader_client.py` | Closure membership unavailable; re-derive on production. |
| `src/weather/market/wallet_reader_server.py` | Closure membership unavailable; re-derive on production. |
| `tests/market/test_wallet_reader.py` | Test changes; closure membership unavailable. |
| `docs/operations/wallet-reader.md` | Documentation, roll-free class. |
| This report and `docs/roadmap/correspondence-index.md` | Documentation, roll-free class. |

The full branch retains the 100a **additive-only**
`src/weather/schema_registry_recent_data.py` registration; 100d does not change
it. Its registry-family roll sensitivity and the handoff's next quiet-window,
bounded-suite integration requirement remain binding. Other inherited 100a files
are listed in the [100a report](agent-report-2026-09-100a-wallet-reader.md).
The subsequent `pyproject.toml`/`requirements.txt` dotenv pin is also retained;
exact closure verdict is unavailable here.

During **100d**, no real-account request, real `.env` read, credential provisioning,
private-key load, signing import, order mutation, firewall/Scheduler registration,
production write, service restart, deployment or master merge was performed.
The existing reader was not probed or restarted. The owner restarts `serve` on
the new tip after review; the production agent owns adoption. All 100a allowlisted
GET-only, public-header isolation, SecretGuard, LAN/IP/token, journal and
account-identity safety controls remain in force.

## Addendum A — bounded Gamma classification (2026-09-25)

**IMPLEMENTED; fixture verification PASS. No real-account run, actual `.env`
access or reader restart in this addendum.**

Answers [Addendum A on origin/master](https://github.com/michaelbooth1/weather/blob/5700260f/docs/roadmap/workstation-handoff-2026-09-100d-wallet-reader-fixes.md#addendum-a-2026-09-25-1250-et-after-the-first-live-read-on-e57c9ee12).
The owner explicitly requested appending this result to the existing report;
the historical sections above are preserved unchanged. Base:
`e57c9ee129d795fd7c8017e29669cd6ce3a3e473`; verified implementation:
`954f106b7f84f437140524b26400ccca039af688`, on
`codex/wallet-public-reader-20260925`. The following report commit is part of the
handback; the branch-tip lookup command above resolves the final pushed tip.

This corrects the original all-holdings Gamma batch: redeemable rows now require
no Gamma lookup, and remaining distinct condition IDs are sent in chunks of at
most 20, with `limit` equal to chunk size. Each chunk is validated in isolation
before its metadata is retained. An HTTP failure, unexpected condition ID or
duplicate condition invalidates only that chunk, preserving successful chunks
both before and after it. Its affected rows retain `classification_unavailable`;
the existing aggregate metadata error and partial-result contract remain intact.
The existing total request/time budget still applies to every chunk.

| Fixture | Result |
| --- | --- |
| 104 holdings, 103 redeemable and one live | One Gamma GET for exactly one ID (`limit=1`); the live row marks successfully; seven summary GETs total. |
| 45 non-redeemable holdings | Three Gamma GETs with 20, 20 and five IDs and matching limits; all 45 classify live; marking stays within the 24-GET composite budget. |
| Middle chunk fails: HTTP 414, foreign ID or duplicate ID | Only its 20 conditions remain unknown; the other 25 classify live, and unknown rows request no books. |
| 104 redeemable holdings | Two position pages only; zero Gamma, book or reward GETs. |

**160 focused tests passed** (the same reader/schema/import command above),
including six new addendum cases and all existing safety regressions.
Compilation (`compileall -q app src tests`) and `git diff --check` passed.
**29 documentation tests passed**, including the appended report's repository
audit and generated-index parity. Reproduction commands are above.
All verification uses synthetic fixtures
through the unchanged workstation admission wrapper; no statistical inference
or live-network latency claim is made. The production observation in the
handoff was supplied evidence, not re-measured here.

Per-file roll disposition: `src/weather/market/wallet_reader.py` and
`tests/market/test_wallet_reader.py` have no available production closure evidence;
`docs/operations/wallet-reader.md` and this report are documentation, roll-free
class. Re-running `roll_verdict.ps1 -Branch codex/wallet-public-reader-20260925
-Base origin/master` returned exit 1, **UNDECIDABLE: no live closure evidence**,
with the same four absent status files. The full branch's inherited schema
registration remains additive-only and roll-sensitive; production must re-derive
the verdict and perform its guarded integration.

No transport allowlist, credential loader, signing/import boundary, SecretGuard,
LAN/IP/token check, journal schema, firewall or scheduling behavior changed.
No real account or credential file was accessed, no private key was loaded, no
reader/account endpoint was probed, and no service restart, registration,
production write or master merge occurred during this addendum. The running
reader was left untouched; adoption of the new tip remains a separate step.

## 100e — separate live and resolved P&L (2026-09-25)

**IMPLEMENTED; fixture verification PASS. No production run, real-account read,
actual `.env` access or reader restart in 100e.**

Answers [handoff 100e at the fetched master commit](https://github.com/michaelbooth1/weather/blob/9f7e5f68f57f0cfee8b45b342f1e16c0e0e341e2/docs/roadmap/workstation-handoff-2026-09-100e-wallet-reader-pnl-split.md).
The owner explicitly requested this append to the existing 100d report; all
historical sections above are preserved. The branch was reset as requested to
`4ac1571859a389efede818a8c4d148d4f194cd22`. Verified implementation:
`6681444fa01ffe01da7b5c3803c1b439951ff9e2`, on
`codex/wallet-public-reader-20260925`. The following report commit is part of the
handback; the branch-tip lookup command above resolves the final pushed tip.

This supersedes 100d's inclusion of resolved marked value in summary equity.
`marked_positions_pusd` and `unrealized_pnl_pusd` now sum live positions only;
`mark_basis` is `live_two_sided_mid`. The separate informational
`resolved_pnl_vs_cost_pusd` sums resolved terminal value minus cost, with
`resolved_count` reported regardless of row visibility. A missing resolved
valuation makes only that resolved total unknown; an empty resolved list gives
zero. Incomplete live inventory or live marks still prevents live/campaign totals.

Campaign P&L is cash plus live marked value minus the explicit contribution
baseline. The [runbook](../operations/wallet-reader.md) tells the owner to pass
equity at the **2026-09-22 campaign start**, adjusted for later deposits and
withdrawals and reconciled on the same cash-plus-live-marks basis. Historical
resolved dust stays outside both sides; lifetime lot costs are not a campaign
baseline. Without capital, campaign P&L remains unknown. `BLEED_LIMIT` still
uses only cash < 60 or campaign P&L < -40, with both thresholds unchanged.

| Synthetic fixture | Observed result |
| --- | --- |
| One live lot: 10 shares at cost 0.70, bid 0.40 / ask 0.60; 103 resolved lots, each 100 shares at cost 0.90 | Live mark 5.0 and live unrealized -2.0, regardless of historical resolved outcome. |
| All 103 resolved lots terminate at 0 / at 1 | Separate resolved P&L -9270.0 / +1030.0; `resolved_count=103`; neither alters live/campaign totals or status. |
| Cash 70; capital omitted / 85 / 115 / 115.01 | Campaign null / -10.0 / -40.0 / -40.01; status INCOMPLETE / OBSERVED / OBSERVED / BLEED_LIMIT, for both resolved outcomes. |
| Hide / show resolved rows | Same totals, seven fake GETs across both calls, one live book request; cached visibility change adds no reads. |
| Unknown resolved value with complete live marks | Resolved P&L null; live and campaign totals remain available. |
| Incomplete discovery or missing live mark | Live/campaign totals remain null, even with separately available resolved P&L. |
| Empty resolved list; cash 59; capital omitted | Resolved P&L 0, count 0; campaign null; cash independently triggers BLEED_LIMIT. |

**172 focused tests passed**: reader, schema registry and import architecture,
including all prior 100a/100d safety regressions and 12 added 100e cases.
**29 documentation tests passed**, including the appended report's repository
audit, correspondence-index parity and roadmap-backlog checks.
Focused compilation of `wallet_reader.py` and its test file passed, as did
`git diff --check`. All pytest/compilation ran through the unchanged
`workstation_heavy.ps1` admission wrapper. An initial compile invocation supplied
the wrong workload kind and was rejected before execution; the corrected
`-Kind compileall` invocation passed. The reproduction commands above cover the
same test modules and a broader compilation set. Fixtures use synthetic account
identifiers and temporary synthetic credential files; socket connect/bind are
prohibited by the test suite. No statistical or live-network claim is made.

Per-file roll disposition: `src/weather/market/wallet_reader.py` and
`tests/market/test_wallet_reader.py` have no available production closure evidence;
`docs/operations/wallet-reader.md` and this report are documentation, roll-free
class. `roll_verdict.ps1 -Branch codex/wallet-public-reader-20260925 -Base
origin/master` returned exit 1, **UNDECIDABLE: no live closure evidence**, with
the same four missing status files listed above. The full branch retains the
inherited additive-only schema registration and its guarded production-adoption
requirements; no workstation roll-free verdict is claimed.

Classification, budgets, transport allowlists, credential selection, signing
boundaries, SecretGuard, LAN/IP/token/origin checks, public-header isolation,
journaling and account-identity controls are unchanged. No production or mirror
evidence, actual `.env`, real account or reader endpoint was accessed; no private
key was loaded, service started/restarted, firewall/Scheduler state changed,
order mutated, production write performed or master merge made. **The owner
restarts `serve` after reviewing the pushed tip.**

## 110f — Campaign unredeemed value and incomplete evidence

Verdict: **PASS — fixture-tested correction, owner service restart pending.**
This section supersedes 100e's exclusion of all resolved value from campaign
equity, following the owner's 110f handoff at
`codex/owner-decisions-0925-night` commit
`8643c31ee3352b27548e6cc5b1316333de34a252`.
Base: `ec44b657d29218b839eba28db0daebf161d9a749` on
`codex/wallet-public-reader-20260925`; implementation tip:
`c91b96fee223db9a82bc417ac7d72113128ab270`.
Work used an isolated local worktree/branch to preserve the owner's existing
wallet checkout; the handback is pushed to the requested wallet branch.

### Behavior

`/summary` always exposes positive resolved holdings as `unredeemed_positions`,
including title, outcome, size, terminal value/status and campaign scope. Exact
0/1 data-api prices or token-matched closed Gamma outcome prices provide terminal
value. Conflicting terminal sources fail closed. Winning campaign shares add
their size to equity; losing shares add zero. Resolved cost-basis P&L remains a
separate informational comparison, and live marks remain separate.

Campaign P&L is cash + live marks + campaign unredeemed terminal value minus the
owner's reconciled capital baseline. Zero-size/absent redeemed holdings add no
value on top of cash. A redemption record with a stale positive holding makes
acquisition/quantity evidence incomplete instead of double counting proceeds.
Unknown terminal value yields `status=INCOMPLETE`, null campaign P&L,
`reason=unredeemed_terminal_value_unknown`, and a per-lot
`terminal_value_status=terminal_value_unknown`. The independent
`bleed_limit_reached` flag preserves a known low-cash breach.

The new optional `--campaign-start-utc` takes the owner's exact timezone-aware
baseline instant; no campaign clock is guessed from a calendar date or end date.
When positive resolved lots exist, absent baseline/acquisition evidence yields
`unredeemed_acquisition_time_unknown` and incomplete P&L. With a baseline,
summary uses the already-allowlisted public `/activity` endpoint, starting at
Unix zero, ascending, at most five 100-row pages, after live marking. Only an
exhausted history whose account/token-matched buys minus sells reconcile exactly
to the current lot can establish age. Mixed-age lots, unsupported activity,
missing/duplicate/future rows, failures or pagination/budget exhaustion stay
unknown. A fully sold lot resets subsequent acquisition scope; no FIFO age is
invented. Proven pre-baseline dust stays out of campaign equity, preserving its
separate `resolved_pnl_vs_cost_pusd`. This is deliberately conservative and may
report incomplete on real histories that cannot be reconciled within the bounds.

### Validation and safety

**206 focused tests passed**: wallet acceptance, schema registry and import
architecture. They include winners, losers, unknown terminal values (also with
low cash), historical dust, exact baseline boundary, zero-size redemption, stale
positive redeemed rows, partial sales, full exit/reentry, Gamma token mapping,
conflicting prices, absent baseline, missing/future dates, mixed lots, quantity
mismatches, foreign account rows, duplicates, splits, unknown sides, exhausted
history, read failure and exhausted GET budget. Tests exercised `/summary`
through server dispatch with synthetic credentials and refused socket connect/bind.
Historical 100e fixture assertions now prove dust acquisition using fixture
activity; visibility toggles still use the shared read cache.

Changed files: `src/weather/market/wallet_reader.py`, its wallet test file,
`docs/operations/wallet-reader.md`, and this append-only report section.
The source is Python and needs the production script's closure verdict before
any later production adoption; test/docs files do not enter a runtime closure.
No production closure evidence was accessed and no new production roll verdict
is claimed. This branch remains a workstation reader handback.

**100a safety is unchanged:** transport allowlists and GET-only enforcement,
30-second success cache, 30-GET/minute ceiling, 24-GET/16-second composite plan,
credential selection, no private-key loading/order signing, account identity,
redaction, journal schema, LAN/IP/token/origin controls and firewall code are
unchanged. Additional history reads consume the existing plan and cache; they
cannot expand its limits. No real `.env`, account, venue call, production data,
reader startup, firewall/Scheduler mutation, order or master merge was used.
Only synthetic temporary credential fixtures are exercised by inherited tests.
The owner must reconcile the baseline, adopt the pushed tip and restart `serve`
with `--campaign-capital` and `--campaign-start-utc` to activate this behavior.

Final 110f verification: **29 documentation tests passed** (agent-doc audit,
roadmap backlog and correspondence parity), the standalone documentation audit
passed, focused compilation passed, and `git diff --check` passed. Regenerating
the correspondence index produced no change for an append to an existing report.
