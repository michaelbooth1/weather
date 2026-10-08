# Agent report 2026-09-110x — manual order journal

Verdict: PASS. The journal, report, runner, registrar and docs are built and fixture-verified. The
branch is **expected ROLL-SENSITIVE** because of its two schema-registry rows; confirm with
`roll_verdict.ps1`. It can go live before the merge from a pinned detached worktree (option B below).
Nothing was registered and no production data, credentials, `.env`, Scheduler or venue was touched.

Mission source: `docs/roadmap/workstation-handoff-2026-09-110x-manual-order-journal.md` (origin/master
`164f12d0`). Branch `codex/manual-order-journal-20260928`, based on origin/master `164f12d0`. Draft PR
https://github.com/michaelbooth1/weather/pull/127. The runbook
[manual-order-journal.md](../operations/manual-order-journal.md) owns the definitions.

## What was built

1. `python -m weather.market.order_journal record --out <dir>` is read-only. It appends one
   hash-chained canonical line per run to `<dir>/<UTC-date>.jsonl`. `sequence` and `previous_sha256`
   are over the previous line's bytes, and an OS-held lock admits one writer. A run reads only the
   journal tail because each record carries forward `state`. `verify` walks the whole chain. A
   record holds:
   - open orders (id, condition, token, side, outcome, price, size, matched);
   - the public `/book` best levels, mid, spread and top five levels;
   - `/rewards/markets/<condition>` terms;
   - reader `/rewards` earnings and pool percentages, today every run and the prior day hourly;
   - reader `/summary` cash and positions;
   - fills, order events and markouts.
2. Fill detection. The primary source is reader `/trades`: the taker leg, or maker orders matched
   by order id or account address, deduplicated with a one-hour overlap. A `size_matched` increase
   with no trade across two consecutive trade-readable runs becomes an `order_delta` fill, and its
   time is only a no-later-than bound. A vanished order becomes a `closed` event carrying its
   unattributed size.
3. Markouts at +5 and +30 minutes come from public `/prices-history`. The settlement markout comes
   from the public CLOB `/markets/<condition>` single `winner` once the market is closed, checked
   hourly. Later runs fill these in. The public-GET budget is 40 per run within 150 s, and overflow
   is deferred, never dropped.
4. `report` gives, per order and per market:
   - reward accrued, allocated to orders by size-seconds share within each condition-day;
   - fills, and markouts at 5m, 30m and settlement;
   - cash-days;
   - the reward-share path;
   - net = rewards + settlement markout, `null` until every fill has settled, with a provisional net
     alongside;
   - a hypothetical two-sided baseline: 3× reward by the Q_min rule, plus mirrored equal-distance
     fills contributing `2 × distance × size`.
   Every row is `owner-discretionary`.
5. `scripts/ops/manual_order_journal.ps1` and `register_manual_order_journal.ps1` define
   `WeatherManualOrderJournal`: every 5 minutes, S4U/Limited, a 4-minute limit, `IgnoreNew`, no late
   catch-up, lease-free, and `-WhatIf`. It carries two pins: the runner SHA256, and a combined
   modules digest over `order_journal*.py` and `wallet_reader_client.py`. The runner refuses (exit 3,
   `runner.log`) on any drift. `-StateRoot` separates the code checkout from the
   venv/config/data checkout.
6. Also changed:
   - schema rows `manual_order_journal_v0.1` and `manual_order_journal_report_v0.1`;
   - a `config/scheduled_tasks.json` row and the regenerated `OPERATING_REFERENCE.md`;
   - the runbook, plus rows in README, `docs/README.md` and `docs/operations/README.md`;
   - the journal tests added to Windows qualification.

## Limits and judgement calls

- Venue reward earnings are per condition-day, not per order. The per-order figure is an
  allocation. Earnings on condition-days the journal never observed (for example, before the first
  run) are reported separately as `reward_outside_observation_pusd` and excluded from market net.
- 5m/30m marks are price-history points, not executable prices. Settlement uses the CLOB `winner`
  flag. The handoff said price history, but a terminal history point cannot prove resolution.
- A vanished order with unattributed size cannot be classed as cancelled or filled. Late trade
  rows still attribute it.
- The baseline is hypothetical and assumes the mirror fills in lockstep. `outside_one_sided_band`
  counts observations whose mid falls outside 0.10-0.90, where the ×3 ratio does not hold.
- `data/manual_order_journal/` is not classified in `storage_classes`. That leaves it undeletable by
  reclaim tooling, which is the safe default; classify it separately if wanted.
- **Roll sensitivity.** Every new module is imported only by the journal. The two `SchemaSpec` rows
  are in `src/weather/schema_registry_recent_data.py`, which capture loops import, so the branch is
  expected ROLL-SENSITIVE. Under the exam-period merge policy it would then land after 10-13. I did
  not work around the schema audit. Option B runs the pinned code before the merge instead.

## Verification

- Focused tests on the workstation: `tests/market/test_order_journal.py`, 29 passed. This includes
  a fixture whose interpreter resolves `weather` from another checkout's editable install and must
  refuse. The positive runner test succeeds only by importing the worktree's modules: the
  interpreter's `.pth` points at a checkout that has no `order_journal`. The
  PowerShell cases cover:
  - registrar pins against a mock Scheduler;
  - by-file `-WhatIf` with no `-RepoRoot`;
  - the runner's pin refusals;
  - a real runner/interpreter run into a temp `-StateRoot`, with no reader config and no network.
- Repo-wide audits: `agent_docs_audit` PASS. `schema_registry audit --strict` found 0 unregistered.
  `module_size_audit` passed, and the new modules are 141-329 lines. `roadmap_backlog --fail-on-lint
  --check` OK.
- Wrapped audit test run (`workstation_heavy.ps1`, `-Kind pytest`): **305 passed** on `dc4e658d`, and **306 passed**
  after the option-B isolation fix. It
  covered the journal and wallet-reader tests plus the repo-wide ratchets:
  - schema registry;
  - import architecture and release import boundary;
  - agent docs and knowledge structure;
  - path policy, module size, python runtime;
  - ops script ratchets and alarm path;
  - operating reference.
- GitHub CI on `dc4e658d` (the code head): CI success, Windows Qualification success (it now runs
  `tests/market/test_order_journal.py`). The report commit is docs-only; its CI is recorded on the PR.
- Fixtures: `tests/fixtures/manual_order_journal/three_runs.json` holds synthetic replies in the
  recorded shape, with fabricated ids.

## Production registration commands (owner-ops review required)

Pins at this branch. The report commit changes none of the pinned files.

Follow-up 2026-09-30: the probe's prefix check built `<worktree>\src` without its trailing
separator (`.TrimEnd('') + ''` where `.TrimEnd('\') + '\'` was meant), so a module under a sibling
such as `<worktree>\src2` passed. The runner now compares whole path segments, and
`test_runner_refuses_a_sibling_src2_that_shares_the_pinned_prefix` proves a sibling `src2` is refused
(it fails against the previous runner with exit 0). Only the runner pin changed; the modules digest
is unchanged. Production re-registers the running task with the new runner pin.

Follow-up 2026-09-30 (public 403): **PASS — the journal's public CLOB reads now send an explicit
User-Agent.** Since 2026-09-29 22:00Z the venue answered them with HTTP 403 while 88a's public reads
from the same host succeeded; `PublicClob.get` sent the urllib default User-Agent, whereas
`maker_evidence_public.py` sends `Mozilla/5.0 weather-passive-maker-evidence/1` (the RE-1 lesson).
Every public request now sends `PUBLIC_USER_AGENT` (`Mozilla/5.0 weather-manual-order-journal/1`);
the fixture opener asserts the header on every request of every test run and
`test_every_public_read_sends_the_explicit_user_agent` pins the exact header set. Only
`order_journal_sources.py` changed, so only the modules digest moved; the runner pin is unchanged.
Production re-registers the running task with the new modules pin.

The wallet reader's 503s on `summary`/`trades`/`rewards` since 00:11Z 09-30 are **not** the same
kind of failure, so its `weather-wallet-reader` User-Agent was left unchanged. Read-only evidence on
the workstation: the reader's request journal (`scratch\w\wallet-110f\data\wallet_reader\`,
09-26..09-30) holds 672 upstream `200`s, one data-api `/activity` `429` and no `403`, ending at
00:00:06Z 09-30. The workstation itself lost power (Kernel-Power 41; unexpected shutdown 19:38 local,
reboot 20:11:33 local = 00:11:33Z) and rebooted again at 14:20 local 09-30. The reader was not
running between those boots unless started by hand; it now runs from the new logon task
`WeatherWalletReader` (main checkout, started 14:21 local, no campaign flags), and that checkout
has no `data\wallet_reader` journal yet, so it has made no upstream attempt since. The reader
answers `503 read_unavailable` for any local exception, before any upstream call. The production
journal's exact client error codes over the window would settle what it saw. Not done: no probe of
the reader or of any venue, no restart, no Scheduler change.

- runner `scripts/ops/manual_order_journal.ps1`:
  `3d12c5c7dc9b3120aad9a40d1d5db6753e18a2c5e42e6f11e5636a2acfc99eaf`
- modules digest: `f935f59f93ae2e9619ef67ce0f27749cb28bc1ef65485bd139b2ae1e925499b7`

Prerequisites:
- `config\local\wallet_reader_client.json` exists in the production checkout.
- The owner's reader is serving on the workstation. If it is not, each run records `timeout` or
  `refused` and nothing else happens.

If `-WhatIf` reports different current hashes, stop and review the difference; do not paste the new
values.

**Option A: after the branch merges (quiet window if roll-sensitive), from the production checkout:**

```powershell
.\scripts\ops\register_manual_order_journal.ps1 -ExpectedRunnerSha256 3d12c5c7dc9b3120aad9a40d1d5db6753e18a2c5e42e6f11e5636a2acfc99eaf -ExpectedModulesSha256 f935f59f93ae2e9619ef67ce0f27749cb28bc1ef65485bd139b2ae1e925499b7 -WhatIf
.\scripts\ops\register_manual_order_journal.ps1 -ExpectedRunnerSha256 3d12c5c7dc9b3120aad9a40d1d5db6753e18a2c5e42e6f11e5636a2acfc99eaf -ExpectedModulesSha256 f935f59f93ae2e9619ef67ce0f27749cb28bc1ef65485bd139b2ae1e925499b7
```

**Option B: before the merge, pinned detached worktree, production venv/config/data.** Worktree
creation and task registration do not change the production working tree, so this is roll-free.
The production venv's editable `.pth` points at the production `src`. The runner therefore launches
`python -P -B` with `PYTHONPATH=<worktree>\src` for the child only. It first probes
`weather.market.order_journal.__file__` and refuses (exit 3, logged, nothing recorded) unless that
path is under `<worktree>\src`. This closes the defect production review found in the first
runner, which would have imported production's modules, absent before the merge and unpinned
after. Check `runner.log`: the first line after registration must be `recorded`. A `refused` line
naming a path outside the worktree means the isolation failed.
Substitute the PR's reviewed head SHA:

```powershell
$env:GIT_LFS_SKIP_SMUDGE = '1'
git fetch origin codex/manual-order-journal-20260928
git worktree add --detach ..\weather-manual-order-journal-deployed-<sha8> <reviewed-head-sha>
$wt = (Resolve-Path ..\weather-manual-order-journal-deployed-<sha8>).Path
& "$wt\scripts\ops\register_manual_order_journal.ps1" -RepoRoot $wt -StateRoot (Get-Location).Path -ExpectedRunnerSha256 3d12c5c7dc9b3120aad9a40d1d5db6753e18a2c5e42e6f11e5636a2acfc99eaf -ExpectedModulesSha256 f935f59f93ae2e9619ef67ce0f27749cb28bc1ef65485bd139b2ae1e925499b7 -WhatIf
& "$wt\scripts\ops\register_manual_order_journal.ps1" -RepoRoot $wt -StateRoot (Get-Location).Path -ExpectedRunnerSha256 3d12c5c7dc9b3120aad9a40d1d5db6753e18a2c5e42e6f11e5636a2acfc99eaf -ExpectedModulesSha256 f935f59f93ae2e9619ef67ce0f27749cb28bc1ef65485bd139b2ae1e925499b7
```

Check it with the following commands, and read the last lines of `data\manual_order_journal\runner.log`:

```powershell
Get-ScheduledTask WeatherManualOrderJournal | Select-Object State, @{n='Args';e={$_.Actions[0].Arguments}}
.\venv\Scripts\python.exe -m weather.market.order_journal verify --out data\manual_order_journal
```

After a merge, move from option B to option A by re-registering from the production checkout.
Remove the task with `register_manual_order_journal.ps1 -Unregister`.
