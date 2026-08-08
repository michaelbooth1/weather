# Workstation report 2026-09-44a — re-measure the repaired-model gap

## Verdict

**THE IN-SEASON GAP DID NOT MOVE DETECTABLY; THE REPAIR RESTORES INPUTS BUT DOES
NOT CLOSE THE MARKET GAP ON THE SEALED REPLAY CORPUS. RESOLUTION DOMINANCE AND
SEVERE-TAIL CONCENTRATION STAND QUALITATIVELY; THEIR LEGACY EXACT PERCENTAGES,
THE `−0.6641` COOL-BIAS NUMBER, AND THE `74.97%` CENTRE-ORACLE NUMBER ARE NOT
CURRENT-SURFACE ESTIMATES.**

On the exact `-09-34a` population, repaired served in-season Brier is
`0.053379789` against market `0.037505658`, ratio **`1.423246x`
`[1.242584, 1.659022]`**. The sealed pre-repair ratio is `1.423260x`. The
paired ratio delta is **`−0.0000140` `[-0.0022674, +0.0024795]`**, with
observed-effect plug-in power **`0.050`** and 80%-power MDE `0.003055` ratio
points. The point is not distinguishable from zero. The repair changed 7,112
of 12,289 served distributions, but the scored in-season gap is numerically
unchanged.

This falsifies the useful version of the mission premise: on the retained
corpus, routing the captured station block does not move the in-season market
gap. It does not prove the inputs are worthless going forward: the corpus is
the documented partial repair, with U.S. humidity absent and pressure absent
fleet-wide.

No fit, candidate, promotion, collection, provider call, serving change, or
production action was performed.

## Base and positive control

`origin/master` at `8009260b` contained this handoff but did **not** contain the
`-09-43a` implementation tip. Per §10 of the handoff, the work branch is based
on the fallback
`origin/codex/workstation-repair-the-blind-feature-block-2026-09-43a` at
`96a5877443284ee7d375bff768580ec87319e8c8`.

The direct comparator is the sealed `-09-34a` replay tree at `d8bd0259`, with
only the `-09-39a` station-wind implementation `87ca37cf` and the `-09-43a`
station-routing implementation `b17f29b0` applied in a disposable detached
worktree. The overlay changes exactly:

| Overlay file | SHA-256 after repair overlay |
| --- | --- |
| `src/weather/model/feature_store.py` | `aea68e8256d79233fcf21ea70053d87074e547c490ee5cd632df2335aa6721b2` |
| `src/weather/model/model_features.py` | `016543d80548e4958e46d20b996978718a8c0e2278b63b96ea664977e0da4058` |
| `src/weather/model/model_sources.py` | `b99bf5e84e39d7998c62e1dc64754585ef859c5ca6b67131e43897bdb5c9e0b9` |

The pre-repair independent verifier was rerun, not merely read. It returned
`PASS` and rebound the exact 12,289-snapshot / 135,179-band population, source
and artifact hashes, mass, score points, crossed intervals, decomposition, and
final `NOT_POWERED` decision. Its new receipt SHA-256 is
`50a8bd7e4def6325a6b39528fa30bc01c7bde2b943390772979e25dfff1c3752`.

The literal captured `snapshots_long.csv:model_probability` lane cannot be the
positive control on this population: 267 of 12,289 partitions are partial and
fail probability mass, exactly as `-09-34a` recorded. Dropping those rows would
change the sealed population. The valid control is therefore the predecessor's
mass-valid replay-final incumbent distribution. Its band-row SHA-256 is
`c6f4257cfbcb157f5d6ae748d5431c91b5a90a4f77b1b17f12aa156c6cf61316`.
The repaired replay is paired against those exact rows and cutoffs.

## Population and inference

| Property | Value |
| --- | ---: |
| Target dates | 2026-06-03 through 2026-07-30 |
| Date clusters | **50** |
| Market clusters | **12** |
| Promotion-countable market-days | **524** |
| Selected hourly snapshots | **12,289** |
| Binary band rows | **135,179** |
| Routes | **12,289 HGB; 0 other** |
| Repair-changed distributions | **7,112 / 12,289** |
| Mean / max distribution L1 | `0.091876` / `1.295294` |
| Maximum repaired probability-mass error | `6.66e-16` |

Ledger rows were deduplicated to `(market, target_date)` before
`promotion_countable` admission. Settlement authority remained the verified
per-market ledgers. No row crosses the `2026-07-31` provenance boundary.

All paired uncertainty uses shared-weight crossed target-date × market
pigeonhole resampling: 10,000 score/bias/tail draws and 2,000 exact
market-stratified CORP/Murphy decomposition draws. Power is stated before
point interpretation. The paired power values are two-sided normal plug-in
power at the observed effect, with the corresponding 80%-power MDE.

## P0 — market gap

| Stratum / estimand | Pre-repair | Repaired | Paired delta [crossed 95%] | Power; 80% MDE |
| --- | ---: | ---: | ---: | ---: |
| **In-season B ratio** | `1.423260x` | **`1.423246x [1.242584, 1.659022]`** | **`−0.0000140 [-0.0022674, +0.0024795]`** | **0.050; 0.003055** |
| In-season Brier | `0.053380315` | `0.053379789` | `−0.000000526 [-0.00008317, +0.00009121]` | 0.050; 0.0001113 |
| Out-of-season C ratio | `1.526099x` | `1.542244x` | `+0.016145 [-0.009580, +0.043096]` | 0.224; 0.03773 |
| Out-of-season Brier | `0.059483515` | `0.060112820` | `+0.0006293 [-0.0003745, +0.0016679]` | 0.227; 0.001458 |

The in-season primary is effectively flat and not distinguishable from zero.
The out-of-season point is worse, but is also not powered and its interval
crosses zero; it is not evidence of serving harm.

## P1 — findings that depend on the old surface

### 1. Skill decomposition

**STANDS qualitatively; exact `98.88% / 1.12%` is now unciteable as a current
surface estimate.** On the directly comparable in-season corpus, pre-repair
served loss is `84.696%` resolution / `15.304%` reliability. Repaired served
loss is **`84.772%` resolution / `15.228%` reliability**. The paired resolution-
share delta is `+0.07598` percentage points, crossed interval
`[-0.2461, +0.4521]` percentage points, power `0.074`, 80%-power MDE `0.4668`
percentage points.

The repair does not change the conclusion: the gap remains an information/
resolution problem, not a recalibration opportunity. The exact legacy split
came from a different clean panel and cannot be substituted for this estimate.

### 2. Cool bias

**MOVED slightly warm on this corpus, but is not powered; exact `−0.6641 C-eq`
is now unciteable for the repaired surface.** Pooled frozen-base HGB centre
error changes from `−0.70449` to **`−0.64387 C-eq`**. The paired shift is
`+0.06061 C-eq` with crossed interval `[+0.00356, +0.12855]`, power **0.484**,
and 80%-power MDE `0.08850 C-eq` (`D=50`, `M=12`, `MD=524`).

Because power is below the binding 80% bar, the positive point is not promoted
to a directional finding even though the percentile interval is above zero.
At face value it is only about 9% of the old `−0.6641` magnitude and the model
remains materially cool.

### 3. Severe tail

**STANDS.** The same-corpus control reproduces 5,910 severe band rows,
**4.372%** of all band rows, carrying **64.168%** of positive excess loss. The
repaired-native tail is 5,930 rows, **4.387%**, carrying **64.140%**. The
concentration is numerically unchanged.

On the control-frozen tail, mean squared error changes `0.500628 → 0.491692`,
paired delta `−0.008936 [-0.017969, +0.000683]`, power **0.473**, 80%-power MDE
`0.013233` (`D=49`, `M=12`, `MD=485`). The favorable point is not powered.
The legacy `4.26% / 60.2%` exact values remain historical; the current-surface
like-for-like values are the ones above.

### 4. Centre displacement

**The mechanism stands; the exact `74.97%` oracle ceiling is now unciteable.**
This mission did not weaken or bypass the observed-high floor, and the repair
overlay changes only station-derived model inputs. Nothing here overturns the
traced mechanism in which too-cool HGB mass below the trusted floor is
truncated and shifts served centre.

The `74.97%` number came from a different post-boundary 19,265-snapshot,
211,915-band outcome-aware oracle panel. It cannot be pooled with this wholly
pre-boundary seasonal corpus, and its oracle construction is not a retained
canonical CLI that can be rebound to the repaired replay without rebuilding a
new estimator. Therefore no interval or power is reported: **no repaired-
surface centre-oracle percentage is authorized by this mission.** Reusing
`74.97%` as current would be the error this handoff was sent to prevent.

## P2 — pressure training question

**Not run.** P0 and P1 required a 12,289-row exact replay plus the paired
bootstrap and decomposition. The handoff explicitly made P2 droppable when P0
was at risk. No F-market pressure-ablation fit, candidate, or artifact was
produced. The unknowable-at-serve training question remains open.

## Decision

The repaired input surface is a correctness fix, not evidence of scoring gain.
On the one adequately broad like-for-like replay available, it changes many
distributions and leaves the in-season market gap unchanged. Work should not
sequence as though completing the remaining input population will close the
gap; the evidence still points to the unresolved resolution/sharpness problem.

The exact legacy model-performance numbers should be cited as historical
pre-repair findings unless replaced above. Specifically:

- current in-season gap: use `1.423246x [1.242584, 1.659022]`;
- resolution dominance and severe-tail concentration stand, with the new
  same-corpus values above;
- do not cite `−0.6641 C-eq`, `98.88% / 1.12%`, or `74.97%` as measurements of
  the repaired serving surface.

## Evidence and verification

Ignored workstation evidence root:
`C:\Users\Michael\Documents\github\weather\scratch\runs\gap-remeasure-repaired-2026-09-44a`.
It is local research evidence, not a path assumed to exist on production.

| Evidence | SHA-256 |
| --- | --- |
| Repaired full replay summary | `087036097fc2574065c97745c8f18f64debe48f13edec972969b86d29f641fd2` |
| Repaired band rows | `9a70ac80143a7eea9b14003b2f992413d622b167ce35ea4be54273cfdf3e27ae` |
| Repaired snapshot rows | `f8980d2a2013451a7e1d1ec7a832cbf5aeda03f0e4f80bf1e633aec0e1d7c55f` |
| Paired analysis | `d96f3157daf0c5a21d504dd23db20dd005dfddc770c3894ff96936bfd9f41322` |
| Exact paired band rows | `4352e77692893c3ac36add9653eabfe0d014de7a02bf083ec6c10e2944dc4e88` |
| Independent verification receipt | `15af2dce3d8fb543da1d1743ff57a93a5bbcbc7a9bf0efedc00ab83116cb390a` |

The independent verifier returned `PASS` for the retained positive control,
exact paired roster/outcome/market evidence, support, paired score intervals,
cool-bias interval, frozen-tail interval, and decomposition-share intervals.

Repository verification after the report-content commit:

```text
git diff --check
PASS

python -m weather.operations.agent_docs_audit
PASS (18 agent files, 722 Markdown files)
```

No application test is required for this report-only tracked change. The
measurement itself was independently re-read and verified from its sealed CSV,
draw, JSON, source, and predecessor bindings as described above.

## Roll verdict

`scripts\ops\roll_verdict.ps1 -Branch
codex/workstation-remeasure-the-gap-on-the-repaired-model-2026-09-44a`
returned exit **3**, **ROLL-SENSITIVE**: the fallback branch is the cumulative
`-09-43a` stack and differs from `origin/master` by 82 files, 29 importable.
The retained live closures are snapshot, CLOB, and observation-trigger; the
dormant CLOB-enrichment closure is mechanically subsumed.

This mission itself changes only:

| Mission file | Snapshot | CLOB | Observation-trigger | CLOB-enrichment | Verdict |
| --- | --- | --- | --- | --- | --- |
| `docs/roadmap/agent-report-2026-08-09-workstation-remeasure-the-gap.md` | none | none | none | none | Roll-free Markdown |

The branch as a whole must nevertheless be integrated as roll-sensitive in
the 01:00–04:00 quiet window because its required fallback base contains the
model repair. Pushing this branch does not roll production.

## Explicitly not done

- No candidate, calibration, F-market pressure ablation, artifact, release,
  confirmation window, promotion, or serving pointer was fitted or changed.
- No provider, collector, market endpoint, paid source, or network data call
  ran.
- No production `data/`, workstation mirror, ledger, tape, trading evidence,
  scheduled task, collector, supervisor, or live process was written or
  restarted.
- No observed-high floor, probability-mass contract, admission bar, promotion
  gate, or known-defect fixture was weakened.
- No PR, merge, master update, production checkout, or branch deletion was
  performed.

## Production-host acceptance commands

The ignored raw measurement is workstation evidence and is not represented as
a production-host path. These commands use paths that exist on production and
verify the committed handback, exact branch scope, documentation audit, and
mechanical roll classification:

```powershell
$repo = 'C:\Users\micha\Desktop\github\weather'
Set-Location $repo
git fetch origin
$branch = 'origin/codex/workstation-remeasure-the-gap-on-the-repaired-model-2026-09-44a'
$report = 'docs/roadmap/agent-report-2026-08-09-workstation-remeasure-the-gap.md'

git rev-parse $branch
git show "${branch}:$report"
git diff --name-status origin/master...$branch
git diff --check origin/master...$branch
.\venv\Scripts\python.exe -m weather.operations.agent_docs_audit
powershell.exe -NoProfile -ExecutionPolicy Bypass -File `
  .\scripts\ops\roll_verdict.ps1 -Branch $branch
```

Expected report presence: the exact path above. Expected branch roll verdict:
`ROLL-SENSITIVE` (exit 3) because of the fallback `-09-43a` base.

Branch:
`codex/workstation-remeasure-the-gap-on-the-repaired-model-2026-09-44a`.

Report-content commit:
`ee0510160b53dbd0e99b929c7029c07b9b624753`.
