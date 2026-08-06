# Workstation report 2026-08-06 — does the cool bias track seasonal distance?

## Verdict

**STOP — the commissioned natural experiment is falsified before replay because
Stratum A is not genuinely in-sample.** The frozen per-market HGB training path
excludes the target year, so none of the proposed 2026-05-27 through 2026-06-13
rows can have entered any of the twelve model fits. The A/B/C design therefore
compares three groups of out-of-sample 2026 dates; it cannot separate "the model
is cool" from "the model is cool where it never trained."

The retrain thesis is **unsupported by this test**. No collection spend is
authorized by this result, and a new design is required before treating
seasonal distance as the cause of the retained cool bias.

P0, P1, and P2 were not estimated. The market control, base-HGB contrasts,
severity-tail contrasts, continuous trend, and power calculation all require a
valid A control. Computing their intervals after discovering that the control
is void would attach false precision to a different estimand.

## The prerequisite measurement

| Quantity | Result |
| --- | ---: |
| Frozen market artifacts covered | **12** |
| Intended Stratum A date clusters | **18** |
| Intended Stratum A market clusters | **12** |
| Potential Stratum A market-days | **216** |
| Exact 2026 Stratum A dates admitted to the HGB fit | **0 / 18** |
| Potential Stratum A market-days that can be exact fit rows | **0 / 216** |
| Latest reconstructed historical fit date across the fleet | **2025-06-21** |

The support counts above describe the proposed design grid and its fit overlap,
not an admitted settlement sample. Settlement admission was deliberately not
performed once the load-bearing control failed.

There is no interval for this deterministic source-and-artifact check. Crossed
date × market intervals are therefore **not applicable**, not omitted: no valid
C−A or C−B estimand was formed. Power for those contrasts is likewise not
defined under the commissioned design. This is stronger than a low-power
result—the named control is structurally absent.

## Evidence

### 1. The trainer excludes every target-year row

The serving-safe default in
[`model_climatology.py`](../../src/weather/model/model_climatology.py) parses
each historical target date and skips it when
`local_date.year >= self.target_date.year`, unless an explicit coverage date is
supplied. The feature-model trainer in
[`feature_model.py`](../../src/weather/calibration/feature_model.py) calls
`model.historical_target_cache()` without an explicit coverage set and fits the
final `HistGradientBoostingClassifier` from the resulting matrix.

For a 2026 target, that path can contain seasonally matching month-days from
earlier years, but no exact 2026 date. Being inside the May 10–June 30 archive
window therefore does not make a 2026 observation in-sample.

### 2. The retained artifacts independently agree

The retained artifact audit in
[`agent-report-2026-08-03-workstation-what-n-do-we-actually-have.md`](agent-report-2026-08-03-workstation-what-n-do-we-actually-have.md)
verified all twelve artifact hashes and found zero overlap with the 2026 label
inventory. Its fingerprint-matched forensic reconstruction ends between
2025-06-16 and 2025-06-21 by market. The reconstruction is evidence of lineage,
not a claim that raw row-level fit receipts were serialized in the legacy
pickles.

That audit's retained `artifact-contamination.json` receipt was re-hashed at
`11afe50210bfeefa0d02afa574b4e35926b685e506d8fbc8c1d6d3300ddc97ba`;
its independent `verification.json` remained PASS at
`4b60eeab79342aade37372e7df720774bc11e9206cec08c0eeafb061809719e3`.

### 3. Established findings remain unchanged

The retained −0.6641 C-equivalent cool bias and its crossed interval remain the
current result in
[`ESTABLISHED_FINDINGS.md`](../operations/ESTABLISHED_FINDINGS.md). They were
not re-measured here. This mission tested only whether the proposed natural
experiment could identify seasonal distance as its cause. It cannot.

## Priority disposition

| Priority | Disposition | Reason |
| --- | --- | --- |
| P0 market control | **Not run** | The requested identical-row A→C contrast has no in-sample A. A market result cannot repair that missing model control. |
| P1 stratified cool-bias contrast | **Not run** | C−A and C−B would compare only out-of-sample target dates and answer a different question. |
| P2 severity-tail contrast | **Not run** | Restricting an invalid contrast to the tail does not restore identification. |
| Crossed-cluster power | **Not run** | There is no valid commissioned contrast to power. |

The cheapest decisive check was therefore the handoff's explicit falsifier:
"Stratum A is not genuinely in-sample." The mission stopped at that boundary
rather than forcing an alternate analysis.

## What was not done

- No base HGB was replayed, fitted, refitted, repaired, or replaced.
- No provider call, collection, settlement write, tape write, ledger write, or
  production-data mutation occurred.
- No market-centre, model-centre, tail, trend, or power endpoint was computed.
- No observed-high floor, source gate, release, pointer, candidate, promotion,
  trading, or readiness state changed.
- No scheduled task was registered or modified; no capture process was
  restarted or re-adopted.
- No production branch was merged and no pull request was opened.

## Per-file roll verdict

This branch changes only this report.

| File | Snapshot closure | CLOB closure | Observation-trigger closure | CLOB-enrichment closure | Verdict |
| --- | --- | --- | --- | --- | --- |
| `docs/roadmap/agent-report-2026-08-06-workstation-does-the-cool-bias-track-seasonal-distance.md` | No | No | No | No | **Roll-free.** Markdown is outside all four recorded runtime import closures. |

The branch is roll-free. Pushing it cannot roll capture; no merge was performed.

## Validation

- `git diff --check` — **PASS**.
- All four links introduced by this report resolve — **PASS**.
- The reserved-confirmation-window contract was re-read and contains no active
  reservation — **PASS**.
- `python -m weather.operations.agent_docs_audit` — **BASELINE FAIL**, one
  unrelated issue. The required base already contains a link from
  `agent-report-2026-08-02-workstation-spec-contract-repair.md` to the retired
  `../../src/weather/reporting/validation/floor_retrain_gate_harness.py#L1079`.
  This mission did not alter that append-only historical report.

## Reproduction on the production host

These commands inspect the pushed source and report only. They make no provider
call and do not read or mutate production runtime data.

```powershell
Set-Location C:\Users\micha\Desktop\github\weather

$branch = 'codex/workstation-does-the-cool-bias-track-seasonal-distance-2026-09-30a'
git fetch origin $branch

git show "origin/${branch}:src/weather/model/model_climatology.py" |
    Select-String -Pattern 'local_date.year >= self.target_date.year' -Context 2,2

git show "origin/${branch}:src/weather/calibration/feature_model.py" |
    Select-String -Pattern 'cache = model.historical_target_cache\(\)|final_hgb.fit' -Context 2,2

git show "origin/${branch}:docs/roadmap/agent-report-2026-08-06-workstation-does-the-cool-bias-track-seasonal-distance.md"
git merge-base --is-ancestor 208e20d4a5770e06301bbfc6b8550f1598fdd18e "origin/$branch"
git diff --check 208e20d4a5770e06301bbfc6b8550f1598fdd18e..."origin/$branch"
git diff --name-only 208e20d4a5770e06301bbfc6b8550f1598fdd18e..."origin/$branch"
git rev-parse "origin/$branch"
```

Expected source result: the default cache skips target-year rows, the feature
trainer invokes that default cache, and the final HGB fits the resulting
matrix. Expected diff result: this report is the only changed file.

## Branch and commit

- Branch:
  `codex/workstation-does-the-cool-bias-track-seasonal-distance-2026-09-30a`
- Base: `208e20d4a5770e06301bbfc6b8550f1598fdd18e`
- Measurement/report commit: `c6a469ce801fa8cd1183216cd32c4e46b380bb67`
- Final branch tip: use the `git rev-parse` command above; a Git commit cannot
  record its own hash in its contents.
