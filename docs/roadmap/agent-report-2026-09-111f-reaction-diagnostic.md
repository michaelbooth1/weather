# Agent report 2026-09-111f — competitor-reaction and decidedness-latency diagnostic

Handoff: `workstation-handoff-2026-09-111f-competitor-reaction-diagnostic.md` (ref
`origin/codex/exam-fixes-handoffs-20260929`). Branch `codex/reaction-diagnostic-20260930`, base `origin/master`
`b0032a90`. Workstation, fixtures only.

## Verdict

**TOOL BUILT; NO PRODUCTION RESULT YET.** `python -m weather.market.reaction_diagnostic {reaction,latency}` is
built and fixture-tested. Both commands take an explicit UTC date allow-list and refuse every quote-panel date
(2026-09-30..10-14). `latency` also refuses any date outside calibration 2026-09-27..29. Both use the plugin's read caps.

**Expected `reaction` result: NO_OVERLAP.** This is the handoff's falsifier, stated in advance. The canon puts
the last RE-1 session at 2026-09-25 01:12-02:23Z ([EF §10m](../operations/ESTABLISHED_FINDINGS.md)). The canon also
says 88a has been capturing only since 2026-09-25 06:34Z (100b handoff). If no RE-1 session ran after that, the two
sources never share a band and time. share(t) is then **not estimable from 88a**. The tool prints `NO_OVERLAP` and
substitutes no other source. Production confirms or refutes this by running the tool; the prediction is based on
documentation only.

**Input placement blocks `reaction` on production as-is.** The RE-1 journals are on the **workstation**, in two places:
- the live campaign root `%USERPROFILE%\.weather-re1m-20260921`;
- the owner's copy `C:\Users\Michael\Documents\re1-analysis-copy-20260924`.

This mission checked only that both paths exist and read nothing in them. The 88a books are on production. The owner
must place a read-only analysis copy on production before `reaction` can run (see *Production commands*). A copy named
`…20260924` may predate sessions 9-11 (09-24/25), so a fresh copy is needed.

## What the tool measures

### `reaction`
- **Postings.** The tool reads each `session-N/journal.jsonl` and checks:
  - the canonical hash chain;
  - `prediction.json` `journal_sha256`, when that file is present.

  Our live orders come from `submit_request`/`submit_response` (`status: live`). They end at `cancel_request`,
  `cleanup_cancel_request`, `cleanup_cancel_all_request` or `terminal`.
- **Episodes.** An episode starts at a posting that follows more than 60 s without one, which covers the opening pair
  and each requote. It ends at the next episode or when its orders end.
- **share(t).** For each sealed 88a YES book of the session's token inside an episode:
  - Our modelled share is recomputed with the RE-1 84b scoring (`observe`): size-cutoff midpoint, our own size removed
    from our level, `share_many` and `share_single`.
  - Reward terms come from the session's latest journal `quote_inputs`.
  - Samples are binned by whole minute since the episode start, up to a 60 min horizon.
  - Each bin reports samples, episodes, sessions, bands, and the fraction of samples in which our quote is visible in
    the 88a book.
- **k.** k = Σ(episode mean share over covered minutes) / Σ(share at posting). Share at posting is the first sample
  within 120 s of the episode start. The replay's no-reaction assumption is k = 1.
  - Each episode's k is listed.
  - The interval is a crossed date × market bootstrap (2,000 reps, seed 20260930). Market = 88a city.
  - No interval is claimed with fewer than two dates or two markets.
- **Second series.** The journal's own per-minute `share_many` is reported beside the 88a series and labelled as
  such. It is the RE-1 self-measurement ([EF §10m](../operations/ESTABLISHED_FINDINGS.md)) and does not change the
  verdict.

### `latency`
- **Triggers.** Triggers are `wu_history_high_increased` entries in `trigger_context.triggers` of the
  observation-trigger journal (live file plus rotated siblings), deduplicated.
  - A line is kept only if the date prefix of its `current_captured_at_utc` is on the allow-list.
  - Other lines are discarded from the raw bytes before JSON parsing.
- **Bands.** The static band bounds come from `data/snapshots/<slug>/snapshots_long.csv(.gz)`.
  - Rows captured on panel dates are skipped.
  - The **new-high band** contains `round_half_up(current_value)`. The **previous-high band** contains the old value.
    Each is mapped with `band_contains_value`, in native units.
  - YES tokens come from 88a `universe` records.
- **Lag.**
  - Reference: the last sealed 88a plain mid at or before the trigger capture, at most 300 s old.
  - Lag: the time to the first later mid at least one `tick_size` away.
  - Horizon: 120 min.
  - Resolution is bounded by the 88a book cadence. The first post-trigger book time is reported.
- **Statuses.** `moved`, `no_move_within_horizon`, `no_pre_trigger_book`, `no_post_trigger_book`, and
  `censored_by_allow_list`. The last one means the horizon would have run into a date that is not on the allow-list,
  so a 09-29 late trigger never reads 09-30.
- **Summary per band role:**
  - lag p25/median/p75/p90 and a crossed bootstrap interval on the median;
  - the fraction of triggers whose pre-trigger mid was already outside [0.10, 0.90];
  - the fraction whose mid moved at least one tick in the 15 min before the trigger;
  - date × market cluster support.

### Bounds (same as the plugin reader, `maker_plugin_capture.py` on `codex/weather-maker-plugin-20260925`)
- 64 MiB decompressed per file, 1 MiB per line, 100,000 rows per file.
- 1 GiB input per run, and 2,700 s at most. Caps above these are refused.
- Only sealed 88a segments are read. Each file read is verified against its manifest SHA-256 and byte count, and
  unsealed segments are skipped. Only dated folders on the allow-list are opened.
- Hitting a run cap refuses the run (exit 2, JSON `refused`) and writes no output.
- Output is two create-only files, `<command>.json` and `<command>.md`. They are refused inside an input root.

## Measured values

None. Fixtures only; no production, RE-1 or 88a data was read.

## Per-file roll verdict (production re-derives with `scripts\ops\roll_verdict.ps1 -Branch codex/reaction-diagnostic-20260930`)

| File | Closures | Note |
| --- | --- | --- |
| `src/weather/market/reaction_diagnostic.py` (new) | none | imported by no loop |
| `src/weather/market/reaction_diagnostic_io.py` (new) | none | imported by no loop |
| `src/weather/schema_registry_recent_data.py` | **all four** (snapshot, CLOB, observation-trigger, CLOB-enrichment) | **additive only**: one new `SchemaSpec` appended; no existing entry changed |
| `tests/market/test_reaction_diagnostic.py` (new) | none | test |
| this report, `docs/roadmap/correspondence-index.md` | none | docs |

The branch is **roll-sensitive** only through the additive registry row. Under the exam-period merge policy it is exam
tooling, a secondary diagnostic under Clarification 2.

## Production commands (after merge; 00:30-09:00 under the shared lease)

Expected inputs on production:
- 88a root: `data\maker_evidence\<YYYY-MM-DD>\<HH>-<id>\` (sealed).
- Trigger journal: `data\snapshots\observation_triggers.jsonl` plus rotated `observation_triggers.<stamp>.jsonl`.
- Bands: `data\snapshots\<event-slug>\snapshots_long.csv[.gz]`.
- RE-1 journals: the owner-placed copy `C:\re1-analysis-copy-<date>\session-N\{journal.jsonl,prediction.json}`. The
  folder name must contain `analysis-copy`; the tool refuses any other root, including the live campaign root.

```powershell
. .\scripts\ops\workload_admission.ps1
$repo = (Get-Location).Path
$lease = Enter-WeatherHeavyWorkloadLease -RepoRoot $repo -Workload "reaction_diagnostic_111f"
if ($null -eq $lease) { throw "Heavy workload lease busy" }
try {
    .\venv\Scripts\python.exe -m weather.market.reaction_diagnostic latency `
        --date 2026-09-27 --date 2026-09-28 --date 2026-09-29 `
        --out-dir data\alerts\reaction-diagnostic-111f
    .\venv\Scripts\python.exe -m weather.market.reaction_diagnostic reaction `
        --date 2026-09-23 --date 2026-09-24 --date 2026-09-25 --date 2026-09-26 `
        --re1-root C:\re1-analysis-copy-<date> `
        --out-dir data\alerts\reaction-diagnostic-111f
} finally { Exit-WeatherHeavyWorkloadLease $lease }
```

- The `reaction` allow-list should cover every RE-1 session date and 88a's first days.
- A session whose journal crosses a date that is not on the list is excluded and named in the output.
- Exit 0 prints the verdict and the output paths. Exit 2 is a refusal on a run cap.

## What was NOT done

- No production, RE-1 or 88a data was read. On this host, only the existence of the two RE-1 paths was checked.
- Nothing was registered, scheduled, restarted or merged.
- No hurdle, estimator, policy or signed file was changed. No quote-panel date was read.

## Reproduction (fixtures)

```powershell
.\venv\Scripts\python.exe -m pytest -q tests\market\test_reaction_diagnostic.py tests\operations\test_schema_registry.py tests\operations\test_import_architecture.py tests\operations\test_agent_docs_audit.py tests\operations\test_path_policy.py tests\operations\test_module_size_audit.py
```

## Open questions served

None directly. This is the Clarification 2 secondary diagnostic reported with the 10-15 look.
