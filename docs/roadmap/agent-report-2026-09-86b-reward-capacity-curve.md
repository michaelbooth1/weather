# Reward capacity curve — 86b handback

**NO-GO for the unamended sampling specification: the complete venue universe
cannot fit a 15-minute cycle at one request per second through the unchanged
canonical reader. No 24-hour curve or modelled dollars/day is claimed.**

This report answers `workstation-handoff-2026-09-86b-reward-capacity-curve.md`
fetched from `origin/codex/reward-test-attended-handoff-20260921` on
2026-09-22. The implementation is on `codex/reward-capacity-curve-20260922`,
stacked exactly on `475a626e4abd1c4f5824544078d0eccbf2156116`.
Nothing is adopted. The two owner-excluded worktrees were not accessed.

## Cheapest falsifying measurement

The public Gamma weather tag and complete public current-reward pagination
returned, on September 22 afternoon ET:

| Measurement | Count |
| --- | ---: |
| Dated weather events for today/tomorrow | 168 |
| Bands in those events | 1,870 |
| Current reward conditions, venue-wide | 16,202 |
| Reward conditions intersecting those weather events | 248 |
| Of those, configured-city highest-temperature bands | 73 |
| Event discovery requests, five events/page | 72 |
| Current-reward discovery requests, 500 conditions/page | 33 |

`Re1PublicBooks.snapshot()` uses both `/book` and `/fee-rate` for each token;
each band also needs its exact per-condition reward response. That is **five
requests per band**, or **1,240 requests before discovery**. Including the
105 discovery reads gives 1,345 requests, **at least 22.4 minutes** at the
specified rate. A complete 15-minute cycle is therefore impossible even with
zero processing overhead and no retries. This conclusion does not depend on
the optional discovery requests: the band reads alone exceed 900 seconds.

The broader venue universe includes unconfigured cities, lowest-temperature
events, rain and tornado events. Restricting discovery to the twelve configured
highest-temperature cities would silently change "every weather reward market
the venue lists." The sampler does not make that change by default.

The owner was asked to choose between preserving the universe with a 30-minute
cycle, preserving 15 minutes with configured-city scope, or allowing public
batch-book reads. **No amendment was assumed.** The default sampler refuses a
cycle whose minimum request count exceeds its cadence; it does not exceed the
rate limit or label a subset complete.

## What is implemented

- `weather.market.reward_capacity`: bounded public discovery, the unchanged
  `Re1PublicBooks` reward/book parsing, one request/second, descriptive
  User-Agent, raw response bytes with SHA-256, immutable run directories,
  canonical snapshots, per-band refusals, and an explicit stop deadline.
- `capacity_quote` next to canonical selection: 20/50/100/200-share modelled
  scenarios using the canonical `order_score`, `q_min` and `share_of` functions.
  It holds the canonical 20-share prices and admission rules fixed; larger
  sizes are research outputs and never increase a live ceiling.
- Canonical ranking is shared through `selection_rank`; the original ranking
  expression and `select_table` behavior are preserved. Configured UTC-tomorrow
  rows also pass through the original `select_table`. Same-day and unconfigured
  rows are explicitly research scope, not RE-1 live selections.
- `weather.market.reward_capacity_report`: hourly band availability, each
  band's modelled share/six-hour dollars/capital/loss, and best 1/3/10 portfolio
  summaries. Raw hashes, snapshot reconstruction and derived calculations must
  reproduce before reporting. Missing/failed/paused intervals are not filled.
  Readiness requires both 24 hours elapsed and 24 hours of covered cells.

The public import graph previously reached order-controller modules through
`mm_stage2_hold` and `re1_rehearsal`. Pure evidence helpers were moved verbatim
to `mm_stage2_public` and re-exported from the old module; rehearsal-only imports
now occur when constructing `RehearsalVenue`. The sampler imports no order,
SDK, credential or dotenv module. No `.env` was read.

## Model interpretation and parity

The twenty-share helper returns the original canonical `RewardQuote` directly.
Four deterministic book/midpoint/depth/term combinations prove equality of
every quote field, `predicted_360_minutes`, and eligibility with canonical
selection. Larger sizes call the same scoring primitives, preserve prices and
competition, and demonstrate the linear own-score and nonlinear share response.

For size `s`, own score `Q(s)`, and canonical displayed competing score `C`,
modelled share is `h = Q(s)/(C+Q(s))`. If `n` additional competitors each place
the same size at the same prices, the sensitivity is
`Q(s)/(C+(n+1)*Q(s)) = h/(1+n*h)`. Six-hour dollars are that share times the
observed daily allocation times `360/1440`. This holds displayed competition,
midpoint, prices and allocation fixed; it does not predict competitor behavior.

Capital is `s*(YES_buy+NO_buy)`. With no requoting, the worst one-sided fill
loss before fees is `s*max(YES_buy,NO_buy)`; gross cash at risk is also retained.
Both equal-size legs filled below a combined price of one settle differently
from only the losing leg filling. Portfolio loss maxima are summed
conservatively without cross-band settlement netting. Fees, fill probabilities,
adverse selection, inventory accumulation, operating cost and paid rewards are
not measured. Daily equivalents assume repeated selection and capital reuse;
they are not realized or guaranteed P&L.

The 20/50/100/200-share best 1/3/10 daily estimates and associated selected
capital are **unavailable**, not zero: no complete 24-hour sample exists.
There are zero inferential date/market clusters and no confidence interval,
power calculation or hypothesis test. The discovery event count is not a
statistical sample of earnings.

## Retained evidence

All journals remain in the task worktree's ignored `data/reward_capacity/`.
They are not in Git and are not assumed to exist on another host.

| Worktree-relative artifact | SHA-256 |
| --- | --- |
| `data/reward_capacity/discovery-probe-2/events.jsonl` | `5b9264c0c14f48a77eecad75408c5bca591634bf655c76f8ab4beffbe3079819` |
| `data/reward_capacity/reward-universe-probe/rewarded.jsonl` | `d37c373386a503ee743cd1b518e181df94821cc55443972f8ea20f6e9de871fe` |
| `data/reward_capacity/book-parser-proof/proof.jsonl` | `603bade6d68b2472a15d928f0533c79bd2cdea0f79d2c58148b5ba748ddd4946` |

The one-band public parser proof made five requests and retained both books.
Its reward terms failed the canonical treatment at all four sizes; it is a
parsing proof, not a qualifying-capacity observation. The initial 50-event
discovery page exceeded the canonical two-megabyte limit and was refused;
subsequent discovery used five-event pages. The initial oversized diagnostic
response was not retained in full and is not used as evidence of completeness.

The default one-cycle invocation at 15:40 ET retained its own discovery under
`data/reward_capacity/20260922T194050496316Z/`. Its current-reward pagination
repeated a condition, so the canonical validator refused the incomplete
listing and the process stopped. It created no complete sample. The earlier
complete probe, not this refused pagination, supports the counts above.
The stopped lifecycle receipt and absence of `sampler.lock` were checked.

## Safety and verification

The exact non-capture workstation installation and attending principal were
checked against the tracked assignment before public reads. Each request holds
`Global\WeatherProjectHeavyWorkloadV1`, the same mutex held throughout RE-1 live.
Busy/abandoned mutex or workload poison stops the sampler. A create-only sampler
lock prevents duplicate runs. `data/reward_capacity/STOP` stops the sampler;
it is not removed automatically. The deadline is checked before and between
requests, with a one-second-before-deadline process watchdog as a final bound.
The September 22 CLI refuses deadlines past 19:45 ET. No automatic restart
after the live session is installed; the owner agreed to signal its completion.

Focused verification used the required workstation-heavy wrapper and owned
`--basetemp`, removed afterwards: 156 tests passed across capacity, canonical
selection, quote pricing, RE-1 rehearsal regression, and import architecture.
The subsequently expanded capacity-only file passed 18 tests, including
cadence refusal, raw-response replay/tampering, nonzero failure exit and lock
cleanup. The seven changed Python files compiled through the same wrapper.
No full suite ran.

## Reproduction

Use a fresh isolated checkout of this branch on the assigned workstation and
its project interpreter. These commands are repository-relative and do not
depend on another host's scratch tree or retained runtime files:

```powershell
# Resolve the interpreter belonging to this checkout's common Git repository.
$capacityGitDir = git rev-parse --path-format=absolute --git-common-dir
$capacityPython = Join-Path (Split-Path $capacityGitDir -Parent) 'venv/Scripts/python.exe'
if (-not (Test-Path -LiteralPath $capacityPython)) { throw 'Provision the project interpreter first' }

# From that checkout, read public data only; default scope/cadence fail closed.
# Use a fresh future deadline within 18 hours and outside every RE-1 live session.
& $capacityPython -m weather.market.reward_capacity --until 2026-09-22T19:45:00-04:00 --once

# Offline, after qualifying samples exist in this checkout's own data directory.
& $capacityPython -m weather.market.reward_capacity_report
```

The dated command above records the actual September 22 invocation, not future
authority to restart. `--interval-minutes 30` and `--configured-only` are
explicit amendment switches, not default behavior or authorization.

The per-file production roll verdict requires current retained production
closures. This fresh workstation checkout has none; no merge or production
adoption is authorized by local tests. The mechanical verdict and implementation
commit are recorded in the final verification entry below.

## What was not done

No access to either excluded session worktree; no `.env`, credentials,
authenticated endpoint, account state, order, live session, payout, historical
execution-tape markout, model fitting, promotion, production write, registration,
Scheduler mutation, restart, merge, production adoption or full suite. No
production hourly selection logs were supplied or read. No cadence amendment,
24-hour measurement, economic GO, or profitability claim was invented.

## Final verification entry

Implementation commit: `86d1c9eac5cb13d4830c6fd9eedf0f190508c374`.
The final handback commit adds this report and removes trailing whitespace
from the extracted helper. Branch: `codex/reward-capacity-curve-20260922`.

The one-cycle process PID 36740 stopped at **2026-09-22 15:42:48 ET**, after
104 responses and zero complete samples, well before 19:45 ET. No sampler
was left running. Sampling has not been scheduled to resume while awaiting
the owner's cadence amendment and later RE-1 completion signal.

Mechanical command executed from the task worktree:

```powershell
powershell.exe -NoProfile -File scripts/ops/roll_verdict.ps1 `
  -Branch codex/reward-capacity-curve-20260922 -Base 475a626e4 `
  -JsonOut data/reward_capacity/roll-verdict.json
```

Result: **exit 1, UNDECIDABLE: no live closure evidence**. All four required
supervisor closure files were absent; the command returned before writing a
JSON verdict. No production evidence was substituted or fetched. Per-file:

| Changed file | Loaded capture closure membership / roll disposition |
| --- | --- |
| `src/weather/market/mm_stage2_hold.py` | Unavailable; treat as roll-sensitive pending production verdict |
| `src/weather/market/mm_stage2_public.py` | Unavailable; treat as roll-sensitive pending production verdict |
| `src/weather/market/mm_stage2_selection.py` | Unavailable; treat as roll-sensitive pending production verdict |
| `src/weather/market/re1_rehearsal.py` | Unavailable; treat as roll-sensitive pending production verdict |
| `src/weather/market/reward_capacity.py` | Unavailable; treat as roll-sensitive pending production verdict |
| `src/weather/market/reward_capacity_report.py` | Unavailable; treat as roll-sensitive pending production verdict |
| `tests/market/test_reward_capacity.py` | No retained closure proof; no production roll claim |
| This Markdown report | Documentation, roll-free by the delegation contract |

No schema registry was changed. The Python change includes import refactoring
as well as additions; it is not represented as additive-only schema work.

## Amendment preparation — awaiting session 1 completion

The owner instructed this task to follow §5 of the amended handoff fetched
on September 22. The original NO-GO above remains the accepted result for the
unamended venue-wide scope. The authorized collection is now **configured-city
scope**, `--configured-only --interval-minutes 15`. The broader 248-band count
is context only. No batch-book path or scoring change is authorized or added.

The only production-code change in this preparation removes the fixed
September 22 19:45 calendar cutoff. A deadline must still be strictly in the
future and no more than 18 hours from invocation. The focused offline tests
passed **23/23**: they admit the former evening cutoff and midnight crossing,
admit exactly 18 hours, and reject past, present and greater-than-18-hour
deadlines before file or network activity. The admitted test uses a fake cycle
and verifies the configured-only/15-minute arguments; it does not sample.

**No sampler was started.** `data/reward_capacity/STOP` was written in this
task's worktree, and no sampler lock exists. No polling, scheduled start,
network proof, full suite or RE-1 command was run. The sampler stays stopped
until the owner explicitly says **RE-1 session 1 has ended**.

On that signal, retain all existing evidence, confirm no RE-1 command is
running or about to run, then remove this task's STOP marker and run with a
fresh duration-based deadline:

```powershell
# Only after the explicit owner signal and confirmation of the quiet interval.
$capacityUntil = [DateTimeOffset]::UtcNow.AddHours(18).ToString('o')
& $capacityPython -m weather.market.reward_capacity --configured-only `
  --interval-minutes 15 --until $capacityUntil
```

Prepare the second fresh deadline only after the first process has exited and
its stopped receipt/lock release are checked; each deadline is at most 18 hours.
Continue toward 24 **covered** hours, with failed or paused cells left missing.
Before any later RE-1 command, including preflight or live, the owner or this
agent must write `data/reward_capacity/STOP` and verify sampler exit before the
RE-1 command starts. A STOP-triggered exit does not authorize a restart.

The configured-city curve section and final measurement handback remain pending
the owner's session-1 completion signal and actual collection. No modelled
dollars or coverage are manufactured during preparation.
