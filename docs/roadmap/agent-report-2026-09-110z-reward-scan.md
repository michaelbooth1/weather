# Agent report 2026-09-110z part 1 — read-only reward-opportunity scanner

Answers [workstation handoff 2026-09-110z](workstation-handoff-2026-09-110z-reward-scan-and-read-tools.md), part 1.
Branch `codex/reward-scan-20260928`, code commit `c92344430e3b971dbaf69f3ebeb597d1caef43de`, draft PR
[#129](https://github.com/michaelbooth1/weather/pull/129). Written 2026-09-29 on the 32 GB workstation.

## Verdict

**DELIVERED, FIXTURE-VERIFIED ONLY.** `weather.market.reward_scan` produces every per-outcome field the handoff
names. It reads only public CLOB reward terms and books through one GET-only allow-list function. It reads the
owner's pool percentages through the wallet-reader client, run as a **child process**. The new transitive
import-closure ratchet shows that no order, signing, RE-1, credential, wallet-reader, live, SDK, maker-policy,
plugin or fair-value module is reachable. **It has never been run against the live venue**, because the session
preamble forbids venue calls. The first owner run is therefore also the first check of the real response shapes
and of the default pacing (0.2 s between GETs, 2000 GETs per scan). **Roll: sensitive, additive-only**, because
of one new schema-registry entry.

## What was built

| File | Purpose |
| --- | --- |
| `src/weather/market/reward_scan.py` | `scan --out <dir>` CLI, `check_public_get` allow-list, paced `PublicReader`, per-outcome geometry, reader child process |
| `src/weather/schema_registry_recent_data.py` | One additive `SchemaSpec("reward_scan", "reward_scan_v1", …)` |
| `tests/market/test_reward_scan.py` | 20 fixture tests: allow-list refusals before any socket, field values, NO mirroring, budget deferral, identity refusal, reader CLI contract, file output |
| `tests/operations/test_import_architecture.py` | `first_party_import_closure` plus a forbidden-module ratchet for `weather.market.reward_scan`, with its own positive controls |
| `scripts/ops/run_reward_scan.ps1` | Owner-started foreground 15-minute loop; `-WhatIf`, `-Once`, `-Condition`, `-NoReader`; no Scheduler registration |
| `docs/operations/reward-scan.md` + README/docs map/ownership rows | Canonical runbook |

For each order-book-enabled, open market of an unexpired event in `config/location_market_events.json`, and for
each explicit `--condition` id (resolved through Gamma `/markets`), the scanner reads
`/rewards/markets/<condition>`. It reads the YES `/book` only when today's summed `rate_per_day` is positive.
The NO outcome is the mirrored YES book. It emits one row per outcome:

- the daily reward rate, max spread and min size;
- the size-cutoff mid and the raw spread;
- whether the mid is inside [0.10, 0.90], with the one-sided factor 1/3 inside and 0 outside;
- the resting size of at least the min size, strictly inside the band, on each side;
- the tightest eligible non-crossing bid, its distance and `cash_needed_pusd = min_size × price`;
- `our_pool_percentage`.

Output files are `data/reward_scan/reward_scan_<stamp>.json` and `latest.json`, written atomically and tagged
`campaign: owner-discretionary`. The scanner computes no share estimate, fair value or edge.

### Design choices the production agent should check

1. **The reader runs as a child process, not an import.** `wallet_reader_client` imports
   `wallet_reader_security` (the dotenv credential loader) and `wallet_reader_transport` (L2 HMAC signing). A
   direct import would make both reachable and fail the ratchet the handoff asked for. The child process runs
   the documented CLI `python -m weather.market.wallet_reader_client rewards --date <UTC day> --timeout 20`.
   Its failure reason becomes `pool_percentage_status: reader_<reason>`, and the scan still completes.
2. **The ratchet is transitive and static.** It covers function-local imports, relative imports, literal dynamic
   imports and parent-package `__init__` files. Today's closure is `weather`, `weather.market` (and its
   `__init__`'s `market_config`/`market_registry`), `reward_share_estimate`, `paths` and the
   `schema_registry*` family.
3. **Pool-percentage shape.** The venue's `/rewards/user/percentages` shape was not observed in this session.
   The parser accepts a condition→number mapping (the existing reader fixture shape), a nested `data` mapping,
   or a list of `{condition_id, percentage}` rows. Anything else gives `null` per condition.
4. **Approximations,** also listed in each file's `notes`:
   - the venue's own midpoint is approximated from the displayed levels;
   - distance is measured against the pre-quote mid, so a quote that becomes the new best bid moves its own mid;
   - displayed size aggregates makers.

## Measured values

None. This is a tool mission with no market data; fixture values only. No date or market clusters apply.

## Per-file roll verdict

The workstation's capture status files are frozen, so `roll_verdict.ps1` cannot be run meaningfully here.
Derived from the delegation contract §3; the production agent re-derives it:

| File | Closures | Verdict |
| --- | --- | --- |
| `src/weather/schema_registry_recent_data.py` | all four (snapshot, CLOB, observation-trigger, CLOB-enrichment) | **sensitive, additive-only** (one new entry, no existing entry changed) |
| `src/weather/market/reward_scan.py` | none (new; nothing imports it) | roll-free |
| `tests/…`, `docs/…`, `README.md`, `scripts/ops/run_reward_scan.ps1` | none | roll-free |

Under the exam-period merge policy (panel 09-30..10-13), this branch is neither disk relief nor exam tooling. It
would wait for a quiet window after 10-13. The scanner runs on the workstation **from the branch** with no
production merge, so the owner can use it before adoption.

## What was NOT done

- No venue, Gamma or reader call was made: fixtures only.
- No registration, Scheduler change, production write, restart or merge.
- No credential, `.env` or `config/local` file was read.
- The scanner was not run end to end against real data.

## Verification

- `pytest tests/market/test_reward_scan.py`: 20 passed, run directly.
- The focused set plus the repo-wide audits (import architecture, schema registry, path policy, module size,
  agent docs, ops-script ratchets, knowledge structure, Python runtime, correspondence index) ran through
  `scripts\ops\workstation_heavy.ps1`: 310 passed; 8 failures were Windows path-length errors from an over-long `--basetemp` in the unchanged `test_reward_share_estimate.py`, which then passed 24/24 with a short `--basetemp`.
- GitHub CI on the PR head: see the handback reply.

## Reproduction

From a checkout of the branch, on the workstation:

```powershell
.\venv\Scripts\python.exe -m pytest -q tests\market\test_reward_scan.py tests\operations\test_import_architecture.py tests\operations\test_schema_registry.py
.\scripts\ops\run_reward_scan.ps1 -WhatIf
.\scripts\ops\run_reward_scan.ps1 -Once -NoReader    # first live read: public venue GETs only
.\scripts\ops\run_reward_scan.ps1 -IntervalMinutes 15
```

## Open questions served

None.
