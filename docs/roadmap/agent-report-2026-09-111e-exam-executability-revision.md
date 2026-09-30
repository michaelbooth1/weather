# Agent report 2026-09-111e (revision) — tooling updated to the revised Clarification 2

Correction and successor to `agent-report-2026-09-111e-exam-executability.md`, which stays unedited as the record of
the first handback. This revision answers the production review of PR #144. It implements the revised draft
`docs/research/maker-replay-clarification-2-2026-09-29.md` at commits `7118ca0c` and `5743c613` on `codex/exam-fixes-handoffs-20260929`,
which settled A1–A8. Branch `codex/exam-executability-20260930`, PR #144.

**Verdict: IMPLEMENTED on fixtures to the revised rule, and the universe producer now exists. Whether the exam can run
on this host is still NOT KNOWN until the three calibration-date rehearsals run.** Under the revised rule the exam is
executable only if every calibration date stays within these limits:
- a full-pipeline rehearsal of at most **~273 s**;
- at most **~273 MiB** of peak memory above the interpreter baseline;
- at most **~273 MiB** of input.

Each follows from the largest power of two under the host limit (8,192 s under 4 h; 8 GiB under 70% of 16 GiB)
divided by 30. That is about 8× looser on runtime and 2× on memory than the first draft. It still may not hold for a
real all-city day; the rehearsals decide.

## Changes in this revision

- **Rehearsal per date.**
  - `rehearse` now takes exactly one calibration-date bundle, so each date runs in its own process and peak memory is
    per date.
  - It keeps input bytes, records, the largest engine events, the largest decisions+spans, rendered report bytes,
    runtime, peak memory above the pre-input baseline, and that baseline.
  - No score, fill, reward or hurdle value is kept. Panel dates refuse from the path before any read.
  - The single-date `measure_ceilings` command is removed.
- **Rule.** `derive_ceilings --rehearsal ×3` requires exactly the three calibration dates (all rehearsed against the
  same calibration hash). Then:
  - Each ceiling is the largest date × 15 × 2, rounded up to the next power of two in its natural unit.
  - Memory = that value for peak-above-baseline plus the largest baseline, unmultiplied.
  - Decisions+spans bind `max_outputs`, separately from `max_events`.
  - Report bytes bind the report ceiling: the fixed 8 MiB is gone, and `write_report` accepts up to the host memory
    limit when a manifest derives it.
- **Host limits.**
  - Memory and memory-resident input/report bytes: ≤ 70% of 16 GiB.
  - Runtime: ≤ 4 h (`HOST_MAX_SECONDS` = 14,400).
  - Counts: ≤ 2^31.
  - Pre-reservation refusal when system commit is ≥ 70%.
  - New: a pre-reservation refusal unless the whole runtime ceiling fits inside 00:30–09:00 Toronto, so a run can never
    be killed at 09:00 after spending the look. This is my reading of "4 hours inside the 00:30–09:00 admitted window".
    It refuses without consuming, and the owner may strike it.
- **Manifest.** The manifest binds the per-date measurements, the three rehearsal hashes and the derivation; every CLI
  ceiling, engine ceiling and the memory guard come from it. `manifest build` no longer takes an output ceiling.
- **Operational refusals and late look.** Unchanged from the first report and now matching the revised text:
  - Any refusal after authorization verifies and before the first policy replay is non-consuming and records its
    stage, whether from manifest build, verify or run.
  - A later look up to 2026-10-31 requires such a record dated 2026-10-15 (Toronto), with `expires_at` 2026-11-01.
- **Universe producer.** New `weather.market.maker_replay_universe`, reached through
  `python -m weather.market.maker_plugin.replay_export universe --bundle <≤15 dirs> --out <json>`.
  - It lists every condition in the sealed bundles with its registered city, target date and IANA timezone, from the
    captured descriptor's event slug and the built-in registry.
  - It refuses a condition without a descriptor or with a changed binding. Output is create-only.
  - The test proves the manifest's own `_inventory` check accepts its output.
- **k = 0.3 sensitivity (draft commit `5743c613`).** `score` adds `reward_k03` and `modeled_net_k03`, the
  comparison report adds paired intervals for `modeled_net_k03` against every baseline, and the Markdown shows a
  labelled k=.3 column. `evaluate_hurdles` and the manifest's registered metrics still read only k = 1 and k = 0.5. A
  test shows that removing every k = 0.3 contrast leaves the decision unchanged.
- **Nightly export.** Its default budget is pinned at the accepted 45 minutes (`DEFAULT_SECONDS`), independent of the
  4 h host limit.

## Verification

- Under `scripts\ops\workstation_heavy.ps1`, `tests/maker_core` plus both exporter suites: 920 passed, 1 skipped,
  5 xfailed.
- Focused files pass locally:
  - `tests/maker_core/test_replay_execution_pack.py`: 37 passed.
  - `tests/maker_core/test_replay_bundle.py`: 31 passed, 1 skipped.
  - `tests/market/test_maker_replay_night.py`: 28 passed.
- The repo-wide audits and the full suite run in GitHub CI on PR #144.
- The workstation heavy lease was held by another session during the first handback; see the PR checks for this head.

## Per-file roll verdict

Unchanged: every changed or new file is expected roll-free. No capture loop imports the replay/export stack, and no
`schema_registry*` file changed. Production derives it with `scripts\ops\roll_verdict.ps1 -Branch
codex/exam-executability-20260930`.

## What was NOT done

No registration, Scheduler change, production write, restart, merge, venue call, credential use or real-data read. No
signed file was touched.

## Production commands (replace step 3 and the 10-15 universe of the first report)

Same worktree, `$python`, `$data`, `$releases`, `$cal`, `$measure`, `$mod`, `$caps` and lease wrapper as in the first
report.

```powershell
# 3. Panel-format export and a fresh-process score-free rehearsal for EACH calibration date.
$rehearsals = @()
foreach ($d in '2026-09-27','2026-09-28','2026-09-29') {
  & $python -B -P -m weather.market.maker_plugin.replay_export night --day $d --data-root $data `
    --release-root $releases --out $measure --expected-module-sha256 $mod
  $r = Join-Path $cal "rehearsal-$d.json"
  & $python -B -P -m maker_core.replay rehearse --bundle (Join-Path $measure "$d\bundle") `
    --calibration (Join-Path $cal 'calibration.json') --out $r
  $rehearsals += '--rehearsal', $r
}
& $python -B -P -m maker_core.replay derive_ceilings @rehearsals --out (Join-Path $cal 'ceiling-measurement.json')
```

`derive_ceilings` prints `executable_on_host=True|False` and the binding limits. **False ends the exam as designed on
this host.** Report it, and do not read panel bundles.

On 2026-10-15, after the 10-14 bundle seals, before `manifest build`, and within 00:30–09:00:

```powershell
& $python -B -P -m weather.market.maker_plugin.replay_export universe @panel --out (Join-Path $cal 'universe.json')
```

Then pass that file as `--universe`. There are no ceiling flags on build, verify or run.
