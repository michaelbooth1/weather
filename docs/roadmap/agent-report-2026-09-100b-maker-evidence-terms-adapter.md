# Mission 100b — sealed 88a reward terms for the 89a desk study

**PASS — synthetic adapter and integration verified; no production run.** The reader accepts
88a's sealed gzip reward journals, preserves unchanged-minute capture times, and feeds the existing
89a terms parser and freshness rule. This is implementation evidence, not a maker-economics result.

Answers [handoff 100b](workstation-handoff-2026-09-100b-maker-evidence-terms-adapter.md) and finding 1 of
the [post-night audit](audits/post-night-audit-2026-09-25.md). No empirical date clusters, market
clusters or market-days were evaluated; no empirical estimates or intervals were produced. Existing
date-cluster and crossed date-by-market inference are unchanged.

## Branch and authority

- Branch: `codex/fill-toxicity-desk-study-20260923`.
- Requested starting remote tip: `2ac227d08f8de80ae6fe43a18e7693f50c9d311d`.
- Fetched master: `177e2b0864cb3af52329b0edfb599f2778d3357f`.
- Conflict-free workstation merge: `b1da008f` (master into the requested topic).
- Clarification 11 commit and new `FROZEN_REF`: `d81c184b36e7889cbeb4853947b97302ad0358d1`.
- Verified implementation tip: `95ea1111f65e889ed2b2e317782fb47f75b007a9`.
- The subsequent report and generated correspondence-index commits are publication metadata;
  the final pushed tip is reported in the task handback and can be resolved with
  `git ls-remote --exit-code origin refs/heads/codex/fill-toxicity-desk-study-20260923`.

The existing clean topic worktree was fast-forwarded from `d3dff0f2` to the requested tip before the
merge. The main checkout and unrelated worktrees were not edited. The user explicitly authorized
the topic merge and push; there is no production/master integration or runtime-adoption claim.

## Adapter and Clarification 11

The authoritative text is [Clarification 11](../research/fill-toxicity-desk-study-preregistration-2026-09-23.md#clarification-11-2026-09-25-mission-100b-before-any-88a-backed-scoring).
Its data-inclusion rule is: accept 88a's **sealed** captured per-condition reward responses, decode
`body_utf8` -> `data[]`, match event and condition, and resolve `payload_ref.file` plus its
**uncompressed byte offset**. Use each outer row's `captured_at_utc`, including an unchanged
response; retain the same at-or-before-minute, **60-minute freshness** and all existing analysis.
There is no daily-terms fallback, new estimand, threshold, exclusion, horizon or window.

`fill_toxicity_reward_inputs.py` owns the adapter. The study plans an additional `maker_rewards`
input per event using overlapping UTC hours and the existing one-hour lookback. The optional
`--maker-evidence-root` defaults to `maker_evidence` beside the supplied snapshots root. Planning
and `--dry-run` only inspect names, seal existence and file sizes; inventories include the seals.
The reader filters response bodies by exact `event_slug` and condition URL/body identity, including
paginated URLs. Existing snapshot reward inputs remain supported.

Reading uses gzip streams, a single cached stored body, bounded reference seeks and the event's
disk-backed SQLite terms table. Limits: 16 MiB per decompressed record, 2 MiB per manifest,
20,000 reward paths per event, and a per-file declared-size ceiling inherited from the store's
500,000,000-byte raw-footprint bound. Manifest schema, seal time, file membership, uncompressed
offsets, record count, bytes, content hashes and full reward-file hashes are checked. Invalid or
unlocatable shared evidence refuses; no damaged row is silently counted as a fresh observation.

**Future-run constraint:** the unchanged frozen panel is August 15–September 23; the supplied
handoff says 88a began September 25. This source adapter cannot make those periods overlap.
Before the production agent reruns after about ten UTC capture dates (earliest approximately
October 5), a separate recorded date-range decision is needed. No later dates were admitted here.

## Synthetic verification

Fixtures use `EvidenceStore` itself with invented values in the handoff's documented response
shape: `count/data/limit/next_cursor`, condition/event/market identities, tokens, reward configs,
4.5 maximum spread and 100 minimum size. The writer supplies the exact outer hashes, offsets,
metadata, `body_stored`, references and seals; test-local files are then gzipped.

- **227 passed, 2 deselected in 39.60 seconds:** study/adapter, 88a capture/store, execution
  markout, reward estimator and import architecture. Tests cover body unwrap; unchanged-minute
  freshness; zero and nonzero uncompressed reference offsets; pagination; event isolation;
  unsealed exclusion and direct-read refusal; metadata-only planning; stale and future terms;
  corrupt references, identities, bodies and hashes; decompressed line bounds; and an end-to-end
  one-day synthetic study using only 88a reward terms (zero missing-term fraction).
- The two unchanged large synthetic controls passed in the first run, including the
  100,000-trade end-to-end study. That run finished **153 passed, 2 failed in 233.18 seconds**:
  a new assertion used `Terms.at` instead of `Terms.captured`, and the architecture ratchet
  required the new source file to be staged. Both were corrected and passed in the final run.
- Focused compileall through the workstation wrapper: PASS. `git diff --check`: PASS.
- This is focused verification, not a claim of a full repository suite or production throughput.

Exact test reproduction from this branch's checkout on the assigned workstation:

```powershell
$studyRepo = (Get-Location).Path
$studyRoot = Split-Path -Parent ((git rev-parse --path-format=absolute --git-common-dir).Trim())
$studyArgs = @('-m','pytest','tests/market/test_fill_toxicity_desk_study.py',
  'tests/market/test_maker_evidence_capture.py','tests/market/test_execution_tape_markout.py',
  'tests/market/test_reward_share_estimate.py','tests/operations/test_import_architecture.py',
  '-q','-k','not large and not hundred','--basetemp',(Join-Path $studyRoot 'scratch/test-100b-final'))
$studyEncoded = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes(
  (ConvertTo-Json -Compress -InputObject $studyArgs)))
powershell.exe -NoProfile -ExecutionPolicy Bypass -File ./scripts/ops/workstation_heavy.ps1 `
  -Kind pytest -PythonPath (Join-Path $studyRoot 'venv/Scripts/python.exe') `
  -ArgumentsBase64 $studyEncoded -RepoRoot $studyRepo
```

Remove `-k` and its expression to repeat the two large controls. Synthetic inputs are generated
under pytest's temporary directory; no mirror or production paths are required. On the capture
host, verification must instead use that host's admitted, time-gated path. No production study
command is supplied as current authority.

## Per-file roll disposition and exclusions

`scripts/ops/roll_verdict.ps1 -Branch codex/fill-toxicity-desk-study-20260923 -Base origin/master`
returned **UNDECIDABLE (exit 1): no live closure evidence** on this workstation. All four capture
status files are absent. Production must obtain the retained-closure verdict before integration;
none is inferred from filename patterns or the frozen mirror.

| Changed file for 100b | Roll disposition |
| --- | --- |
| `src/weather/market/fill_toxicity_reward_inputs.py` | UNDECIDABLE locally; production closure check required |
| `src/weather/market/fill_toxicity_desk_study.py` | UNDECIDABLE locally; production closure check required |
| `tests/market/test_fill_toxicity_desk_study.py` | No production closure claim; included in branch verdict |
| `docs/research/fill-toxicity-desk-study-preregistration-2026-09-23.md` | Markdown, roll-free |
| This report and generated `docs/roadmap/correspondence-index.md` | Markdown, roll-free |

No schema-registry changes. No production run or production data read/write, no `.env` or credential
access, no mirror access/write, no registration, no Scheduler changes, no restart, no capture loop,
no venue requests, no orders, no fitting, no promotion and no production/master merge. Only the
user-requested workstation topic merge, synthetic verification, source commits and publication.
