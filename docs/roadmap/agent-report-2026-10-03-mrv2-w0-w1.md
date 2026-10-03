# Agent report — 2026-10-03 maker replay v2 W0/W1

**Verdict: W0 and W1 are BUILT. S6 PASSES (MEASURED). S1 PASSES its stop rule at fixture density (MEASURED): v0.2 is
628,521,543 bytes (0.585 GiB) per date against the 1 GiB rule. Coverage groups remove 93.8% of coverage bytes, but books are
never elided and become 80.6% of the v0.2 bytes. Two design facts found in code need a decision before W2/W3,
and are listed under "Findings".**

Branch `codex/mrv2-w0-w1-20261003`, based on integration branch `codex/maker-replay-v2-build-20261003`. The
integration branch is `origin/master` + exam tree `664c8943` (merged unchanged) + the v2 design branch (#176). The work
follows `docs/research/maker-replay-v2-engineering-plan-DRAFT.md` (W0, W1, S1, S6). Open questions served: none.
Reserved confirmation window: NONE RESERVED (checked at run time).

## What was built

- **W0** `tools/research/maker_replay_v2/fixture170.py`, a new module. It extends #166's
  `tools/research/pull_cap_precheck/fixture.py`, which is merged here unchanged.
  `tests/maker_core/test_replay_v2_fixture.py` pins #166's outputs byte-identical (full and reduced form).
  - One fictional UTC day: 12 fictional markets in 12 time zones, with four target dates each.
  - Band counts are spread so the daily union is exactly 170: 121–129 bands are selected at once (mean 127.7,
    sampled each minute of the full day), and 68.1% of selected band-minutes are T+1/T+2.
  - At each market's local midnight, T+0 leaves the export, T+1/T+2 roll with a new descriptor, and the new T+2
    event is discovered.
  - Every discovery batch is one trade-stream subscription, giving 16 coverage groups. A print renews its
    subscription's 30 s health; socket outages drop every subscription on the socket.
  - Rows follow the exam exporter (`maker_replay_bundle.export`) in kind and order:
    - books: `ceil(2D/100)` rows a minute, each projecting every live condition;
    - a terms row per selected condition per minute, with about six body changes a day;
    - per-condition outcome views, refreshed every 10 minutes;
    - first-sight plugin inputs and ledger settlements (stamped later than their sequence);
    - coverage for every seen condition at every capture.
  - The generator emits v0.1 and v0.2 forms of the same day.
- **W1** `src/maker_core/replay/bundle_v02.py`, a v0.2 path beside the frozen v0.1 reader. It imports the v0.1 reader
  and does not edit it.
  - `coverage_groups` manifest validation: unique IDs, non-empty sorted member lists, known conditions, one group per
    condition.
  - Pass one hashes each stream in 1 MiB chunks and checks size, count, terminator and file identity. Nothing is parsed
    on a mismatch.
  - Pass two parses one line at a time, re-hashes, refuses an unsorted stream, enforces global sequence uniqueness
    with a bitmap, merges the streams by `(captured_at, sequence)`, and refuses at the end of a stream that changed
    between passes.
  - `load_any` admits v0.1 through the frozen `load_bundle` and v0.2 through the stream reader.
- **W1** `src/maker_core/replay/v2/compaction.py`.
  - `Compactor` is an exporter-faithful group compaction. Each group record carries the sequence of its first member
    in the run, so expansion restores the original v0.1 sequences.
  - The group refusal (`coverage_group_mismatch`) fires when a group's members in a capture are not exactly its seen
    members, or when they disagree in payload or source hashes.
  - Duplicate elision covers descriptors and outcome views.
  - `expand` is the exact inverse.
- The S1/S6 runner is `tools/research/maker_replay_v2/run.py`. It is admitted as one exact module to the workstation
  wrapper allowlist and the Codex hook, following the `nbm_target_trace` precedent, with an exact-module test.

## Measurements (all MEASURED; fictional fixtures; fresh process per run, serial, under `workstation_heavy.ps1`)

All runs used fictional date 2026-09-27 with the full 1,440-minute day. The fixture had union 170, 16 coverage groups,
121–129 bands selected at once (mean 127.7), and a T+1/T+2 share of 0.681. Each run was one fresh
`python -m tools.research.maker_replay_v2.run` process under the wrapper, and the runs were serial. The code was this
branch's commit `ce87cfd4` (W0/W1 code is unchanged after it). Peak RSS was not recorded because `psutil` is absent
from the venv; peak memory is S2's measurement, not S1's.

### S1: bytes and records per kind, v0.1 vs v0.2, one full day at 170 conditions

Primary run: T = 2,000 prints a day, books 8 levels a side. It took 269 s and the result's `sha256` is `26593d15…`.

| Kind | v0.1 bytes | v0.2 bytes | v0.1 records | v0.2 records | Byte reduction |
| --- | ---: | ---: | ---: | ---: | ---: |
| book | 506,376,146 | 506,376,146 | 551,649 | 551,649 | 0 |
| coverage | 401,545,251 | 24,780,593 | 951,084 | 64,801 | **93.8%** |
| terms | 82,885,709 | 82,885,709 | 183,883 | 183,883 | 0 |
| outcome_view | 12,788,494 | 12,788,494 | 18,396 | 18,396 | 0 (exporter already dedups) |
| trade | 954,658 | 954,658 | 1,983 | 1,983 | 0 |
| plugin_input | 358,727 | 358,727 | 510 | 510 | 0 |
| descriptor | 254,391 | 254,391 | 256 | 256 | 0 (exporter already dedups) |
| info_event | 60,660 | 60,660 | 170 | 170 | 0 |
| settlement | 19,861 | 19,861 | 33 | 33 | 0 |
| **total streams** | **1,005,243,897** | **628,479,239** | **1,707,964** | **821,681** | **37.5%** |

The manifests are 32,931 bytes (v0.1) and 42,304 bytes (v0.2). **The v0.2 bundle is 628,521,543 bytes = 0.585 GiB per date,
which is within the ≤ 1 GiB rule (PASS).**

Sensitivity (same day and code, one process each):

| Variant | v0.1 bytes | v0.2 bundle bytes | Reduction | Coverage reduction | Books share of v0.2 | Within 1 GiB |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| T = 20,000, depth 8 | 2,153,954,317 | 712,102,031 | 66.9% | 93.8% | 71.7% | yes |
| T = 2,000, depth 16 | 1,237,493,268 | 860,422,444 | 30.5% | 93.8% | 85.8% | yes |

Coverage shrinks by the same factor whatever the trade rate: about 14.7 v0.1 rows per group row, which is the seen-condition
count per group. The v0.2 margin is set by books, which no v0.2 rule touches.

### S6: v0.2 → v0.1 expansion equivalence and group refusal

The run took 1,292 s and the result's `sha256` is `41a383f3…`. The method:

1. Write both forms of the full day.
2. Reopen each through the two-pass stream reader (pass one hashes, pass two streams).
3. Expand v0.2 with `expand()` and compare its canonical JSONL with `elide(v0.1)` by SHA-256, byte count and record count.

| Case | Expanded v0.2 | Elided v0.1 | Byte-identical | Elided rows | Horizon-roll descriptor changes |
| --- | --- | --- | --- | ---: | --- |
| Exporter-faithful day | `0d2ae1b2…bab4c`, 1,005,243,897 B, 1,707,964 rows | same | **yes** | 0 | 1→0: 40, 2→1: 46 |
| With byte-identical view/descriptor repeats (v0.1 1,925,539,306 B, 2,792,610 rows) | `0f67c14a…049ac`, 1,005,687,227 B, 1,707,964 rows | same | **yes** | 1,084,646 | 1→0: 40, 2→1: 46 |
| Crafted mismatch: one member's coverage flipped at the first capture after 10:00 UTC | — | — | — | — | refusal fired: `coverage_group_mismatch` |

In the exporter-faithful case, the expanded bytes are the whole v0.1 `events.jsonl`: 1,005,276,828 bytes on disk, less the
32,931-byte manifest, equals 1,005,243,897. The expansion restores every coverage row with its original sequence, so
nothing is renumbered. **S6 PASSES.**

Reading and comparing a full day took 365–389 s per case in pure Python, through the two-pass reader (both forms) plus
expansion and canonical re-encoding. That is not an engine cost, but W3's per-date budget (≤ 2,048 s) has to absorb a
parse of about that order.

## Findings that need a decision before W2/W3

1. **The real v0.1 exporter already elides duplicates.**
   - `Projection.add(..., changed=True)` skips a payload whose hash equals the condition's previous one of that kind.
     It is used for descriptors, terms, outcome views, info events and settlements (`maker_replay_bundle.py:168-176,
     418-433`).
   - So §6's duplicate elision saves nothing against real v0.1 exports. The S1 reduction comes from coverage groups
     alone, and the E3 comparison will find zero elided rows.
   - S6 still proves the elision path on a variant with byte-identical repeats.
2. **The frozen v1 engine reads an outcome view's capture time.**
   - The re-entry rule after an `INFO_PULL` compares `state.captured["outcome_view"]` with `resume_after`
     (`engine.py:402`), and pull-decision digests hash `state.captured` (`engine.py:264`).
   - The registration's claim that "the engine reads only payload fields, never a duplicate's capture time" (§6) is
     therefore false for v1. It must be made true in the v2 engine (W3) and pinned by the test §6 promises. Otherwise
     elision against a non-deduplicated source would change decisions.
   - Against the real exporter this is moot today, because of finding 1.
3. **Books dominate v0.2.** Book records are never elided. At 8 levels a side they are 506 MB of the 629 MB v0.2 date. Each extra level adds
   about 28.5 MB a day, so the 1 GiB rule would be crossed by books alone at about 30 levels a side. This matches the plan's "night format may be book-heavy" risk. The
   fixture's book depth is invented, so the real E2 margin is decided only by P1 on calibration dates.
4. **Coverage groups must be subscriptions, not sockets.** The exporter renews health per subscription token group
   (`maker_replay_bundle.py:205-245`), and a newly subscribed token starts unhealthy. A socket-level group would
   therefore trip the refusal whenever a new event subscribes mid-day. The fixture uses one group per subscription,
   and W2 should do the same. A condition with a descriptor but no subscription needs its own group (always
   `trade_stream_ok=false`), or compaction refuses it (`coverage_condition_without_group`).
5. **Adding v2 files changes the v1 manifest's source inventory.** `execution_manifest.source_hashes()` hashes every
   `src/maker_core/**/*.py`. No existing file changes, but a v1 manifest built from this tree would list three more
   files. v1 is closed NOT EXECUTED, so this matters only if anyone rebuilds a v1 manifest from it.

## Frozen-bytes proof

- The 188 paths the exam tree `664c8943` changed against master's merge base are byte-identical at the integration head
  `4055d051` (`git diff --stat 664c8943 4055d051 -- <188 paths>` is empty).
- At this branch's head, the only difference among those 188 paths is `docs/roadmap/correspondence-index.md`. That file
  is generated, not hashed, and was regenerated after merging #166.
- Over the v1 hashed set (`src/maker_core`, `src/weather/market/maker_plugin`, the four named plugin/exporter modules
  and `pyproject.toml`), `git diff --name-status 664c8943 HEAD` lists additions only:
  - `src/maker_core/replay/bundle_v02.py`
  - `src/maker_core/replay/v2/__init__.py`
  - `src/maker_core/replay/v2/compaction.py`

## Per-file roll verdict

`roll_verdict.ps1` is UNDECIDABLE on the workstation (no `data\snapshots` closure files). The static verdict:

| Files | Closure membership |
| --- | --- |
| `src/maker_core/replay/bundle_v02.py`, `src/maker_core/replay/v2/*` | New. Nothing outside tests and tools imports them (grep of `src`, `app`, `scripts`), so they are in none of the four closures. |
| `scripts/ops/workload_admission.ps1`, `.codex/hooks/pre_tool_use_host_load.py` | Roll-free (`.ps1`; a hook outside every closure) |
| `tools/research/maker_replay_v2/*`, `tests/**`, `docs/**` | Roll-free |

No `schema_registry*` file is touched. The integration branch also carries the exam tree, which touches
capture-adjacent code. Production must run `roll_verdict.ps1` on the integration branch itself before any landing,
which is after signature and after 10-14.

## Audits and tests

Pending: filled after the full suite run.

## What was NOT done

- No production, calibration, panel or settlement data was read.
- No registration, Scheduler change, production write, restart, venue call or merge to master.
- No file of `664c8943` was edited. W2–W8 were not started.
- The W0/W1 branch was merged only into the integration branch, after CI was green, as instructed.

## Reproduction

From a checkout of this branch on the workstation:

```powershell
$env:PYTHONPATH = "$PWD\src;$PWD"
function Invoke-Mrv2($a) {
  $b64 = [Convert]::ToBase64String([Text.UTF8Encoding]::new($false).GetBytes((ConvertTo-Json -Compress -InputObject $a)))
  .\scripts\ops\workstation_heavy.ps1 -Kind weather_heavy -PythonPath (Resolve-Path .\venv\Scripts\python.exe).Path -ArgumentsBase64 $b64 -RepoRoot $PWD.Path
}
Invoke-Mrv2 @('-m','tools.research.maker_replay_v2.run','s1','--out','<new dir>','--trades','2000')
Invoke-Mrv2 @('-m','tools.research.maker_replay_v2.run','s1','--out','<new dir>','--trades','20000')
Invoke-Mrv2 @('-m','tools.research.maker_replay_v2.run','s1','--out','<new dir>','--trades','2000','--book-depth','16')
Invoke-Mrv2 @('-m','tools.research.maker_replay_v2.run','s6','--out','<new dir>','--trades','2000')
```

Each run writes `s1.json` or `s6.json` under `--out`. Delete the `--out` directory afterwards, because each full day
is about 1–2 GB.
