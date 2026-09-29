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

- Focused tests on the workstation: `tests/market/test_order_journal.py`, 28 passed. The
  PowerShell cases cover:
  - registrar pins against a mock Scheduler;
  - by-file `-WhatIf` with no `-RepoRoot`;
  - the runner's pin refusals;
  - a real runner/interpreter run into a temp `-StateRoot`, with no reader config and no network.
- Repo-wide audits: `agent_docs_audit` PASS. `schema_registry audit --strict` found 0 unregistered.
  `module_size_audit` passed, and the new modules are 141-329 lines. `roadmap_backlog --fail-on-lint
  --check` OK.
- Wrapped audit test run (`workstation_heavy.ps1`, `-Kind pytest`, head `dc4e658d`): **305 passed**. It
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

- runner `scripts/ops/manual_order_journal.ps1`:
  `d2fbf68b52f725fc9099e7e9d3b84af3da02d346b9b0b8c60835f9a398a19737`
- modules digest: `9432b4db02e7e525ba36a7b345aba1bdfaba0986e8b58f49251c9e0060b1e8c6`

Prerequisites:
- `config\local\wallet_reader_client.json` exists in the production checkout.
- The owner's reader is serving on the workstation. If it is not, each run records `timeout` or
  `refused` and nothing else happens.

If `-WhatIf` reports different current hashes, stop and review the difference; do not paste the new
values.

**Option A: after the branch merges (quiet window if roll-sensitive), from the production checkout:**

```powershell
.\scripts\ops\register_manual_order_journal.ps1 -ExpectedRunnerSha256 d2fbf68b52f725fc9099e7e9d3b84af3da02d346b9b0b8c60835f9a398a19737 -ExpectedModulesSha256 9432b4db02e7e525ba36a7b345aba1bdfaba0986e8b58f49251c9e0060b1e8c6 -WhatIf
.\scripts\ops\register_manual_order_journal.ps1 -ExpectedRunnerSha256 d2fbf68b52f725fc9099e7e9d3b84af3da02d346b9b0b8c60835f9a398a19737 -ExpectedModulesSha256 9432b4db02e7e525ba36a7b345aba1bdfaba0986e8b58f49251c9e0060b1e8c6
```

**Option B: before the merge, pinned detached worktree, production venv/config/data.** Worktree
creation and task registration do not change the production working tree, so this is roll-free.
Substitute the PR's reviewed head SHA:

```powershell
$env:GIT_LFS_SKIP_SMUDGE = '1'
git fetch origin codex/manual-order-journal-20260928
git worktree add --detach ..\weather-manual-order-journal-deployed-<sha8> <reviewed-head-sha>
$wt = (Resolve-Path ..\weather-manual-order-journal-deployed-<sha8>).Path
& "$wt\scripts\ops\register_manual_order_journal.ps1" -RepoRoot $wt -StateRoot (Get-Location).Path -ExpectedRunnerSha256 d2fbf68b52f725fc9099e7e9d3b84af3da02d346b9b0b8c60835f9a398a19737 -ExpectedModulesSha256 9432b4db02e7e525ba36a7b345aba1bdfaba0986e8b58f49251c9e0060b1e8c6 -WhatIf
& "$wt\scripts\ops\register_manual_order_journal.ps1" -RepoRoot $wt -StateRoot (Get-Location).Path -ExpectedRunnerSha256 d2fbf68b52f725fc9099e7e9d3b84af3da02d346b9b0b8c60835f9a398a19737 -ExpectedModulesSha256 9432b4db02e7e525ba36a7b345aba1bdfaba0986e8b58f49251c9e0060b1e8c6
```

Check it with the following commands, and read the last lines of `data\manual_order_journal\runner.log`:

```powershell
Get-ScheduledTask WeatherManualOrderJournal | Select-Object State, @{n='Args';e={$_.Actions[0].Arguments}}
.\venv\Scripts\python.exe -m weather.market.order_journal verify --out data\manual_order_journal
```

After a merge, move from option B to option A by re-registering from the production checkout.
Remove the task with `register_manual_order_journal.ps1 -Unregister`.
