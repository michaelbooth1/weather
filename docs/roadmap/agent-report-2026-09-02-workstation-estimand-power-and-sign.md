# Agent report 2026-09-02 — the look is not powered, and the repair mostly sharpens

**Verdict: NO-GO. Close this five-mission thread and keep the alpha.** Under Null C, the premise
most generous to the candidate, the honest standard error of the paired Brier-improvement estimand
is **`0.0397607208`**. Its 80%-power MDE at the campaign quantile is **`0.1571149069`**, larger than
the entire candidate-favourable mean **`+0.1385161075`**. It fails under its own calibration premise,
so it fails everywhere this screen can license. Null I also fails and points to harm. No alpha was
allocated or spent; the ledger remains **7 of 20 spent, 13 available**, and decision 10 stays
**CLOSED UNUSED / NOT REASSIGNED**.

This corrects `-09-77a`'s commissioning defect. The prior `0.4720` ceiling bounded the candidate's
maximum cost, not its benefit, and its non-negative construction made the specified NO-GO branch
unreachable. This mission measures uncertainty on the actual estimand and proved both decision
branches were reachable before reading the checksum-pinned arm vectors.

## Evidence and support

The only analysis input was
`docs/roadmap/repair-ceiling-single-environment-2026-09-77a.csv`. Its SHA-256 reproduced before any
row was parsed:

```text
expected  3d782223e5b882d2bbda233f6abaed42b1a30442126979835720aa7e610611a8
actual    3d782223e5b882d2bbda233f6abaed42b1a30442126979835720aa7e610611a8
```

The population is the frozen B-only decision stratum: **368 paired rows, 11 target-date clusters,
12 market clusters, and 66 market-days**, all before the `2026-07-31` regime boundary. No replay,
snapshot scan, payload read, provider call, C row, realized band, settlement, label, outcome, or
market probability entered the harness. The 4.9 GB pass was not rerun.

## Honest estimand standard error and power

For each row the estimand is

```text
delta_i = Brier(q, b) - Brier(p, b)
        = sum(q_k^2) - sum(p_k^2) + 2*(p_b - q_b)
```

Positive means the candidate `p` is better. The harness used **100,000 replicates per null**, root
seed **`20260978`**, and **`numpy.random.Generator(PCG64)`** under Python 3.11.9 / NumPy 2.4.6.
Every replicate drew one independent categorical band per row and independently drew multinomial
pigeonhole counts for the 11 dates and 12 markets. The date and market weights were shared between
Null I and Null C in the same replicate. The standard deviation of those crossed replicate means is
the reported **SE of the mean estimand**, including the realized-band variance omitted by `-09-77a`.

| Premise | Band draw | Analytic mean | Simulated mean receipt | Crossed SE(delta) | MDE = 3.9515105336 x SE | Result |
| --- | --- | ---: | ---: | ---: | ---: | --- |
| **Null I: incumbent calibrated** | `b ~ Categorical(q)` | `-0.1385161075` | `-0.1384472127` | **`0.0454452902`** | **`0.1795775429`** | **NO-GO** |
| **Null C: candidate calibrated** | `b ~ Categorical(p)` | `+0.1385161075` | `+0.1384916532` | **`0.0397607208`** | **`0.1571149069`** | **NO-GO** |

The two simulated controls miss their analytic targets by only `+0.0000688948` and
`-0.0000244543`, respectively, against the committed absolute tolerance `0.001`. An independent
read-only 100,000-replicate seed check returned `SE_I = 0.0449910476`, `SE_C = 0.0398982145`, and
Null-C `MDE = 0.1576582149`: the same NO-GO.

The campaign-corrected 12-market canonical floor is **`0.0451345675`**. It is not binding here:
the actual field MDEs are `0.17958` and `0.15711`. Equivalently, a NO-GO becomes reachable at
`SE(delta) >= 0.0350539639`; both measured estimand SEs clear that threshold. More dates cannot turn
the omitted realized-band variance into the displacement SE.

## Which way it points

Neither calibration premise is established. Under Null I the sign is negative and the repair
harms; under Null C the sign is positive and the repair helps. For a row whose truth distribution
equals one arm, its expected signed contribution is `+/- ||p-q||^2`. Therefore the most favourable
way to make the overall mean positive is to assign candidate-closeness first to rows with the
largest squared arm distance.

Even under that best placement, the candidate must be the closer arm on at least **57 of 368 rows
(`15.4891%`)**, which carry just over half (`50.2403%`) of total squared arm distance. This is a
lower bound on how many rows must go right, not an estimate that they will go right. If
candidate-closeness is not concentrated exactly on those largest-displacement rows, more than 57
are required.

| Market | Rows | Minimum candidate-closer rows for positive mean | Minimum share | Mean `||p||^2-||q||^2` | Sharper rows | Large majority (>=2/3) |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| Atlanta | 51 | 17 | 33.33% | `+0.0243584` | 32/51 (62.75%) | no |
| Austin | 40 | 7 | 17.50% | `+0.0285289` | 21/40 (52.50%) | no |
| Chicago | 25 | 5 | 20.00% | `-0.0286307` | 11/25 (44.00%) | no |
| Dallas | 37 | 12 | 32.43% | `+0.0366895` | **31/37 (83.78%)** | **yes** |
| Denver | 21 | 4 | 19.05% | `+0.0236174` | 13/21 (61.90%) | no |
| Houston | 22 | 5 | 22.73% | `+0.0606622` | **16/22 (72.73%)** | **yes** |
| Los Angeles | 27 | 8 | 29.63% | `+0.1546246` | **26/27 (96.30%)** | **yes** |
| Miami | 25 | 5 | 20.00% | `+0.2471071` | **22/25 (88.00%)** | **yes** |
| NYC | 31 | 6 | 19.35% | `+0.0021786` | 20/31 (64.52%) | no |
| San Francisco | 8 | 3 | 37.50% | `+0.1410028` | **6/8 (75.00%)** | **yes** |
| Seattle | 57 | 12 | 21.05% | `+0.0485229` | 34/57 (59.65%) | no |
| Toronto | 24 | 2 | 8.33% | `+0.1017355` | **22/24 (91.67%)** | **yes** |

Chicago is the only market with a negative mean sharpness delta. Dallas, Houston, Los Angeles,
Miami, San Francisco, and Toronto sharpen on at least two thirds of rows. Small per-market support,
especially San Francisco's eight rows, makes these exposure flags rather than performance claims.

| Window | Rows | Mean `||p||^2-||q||^2` | Sharper rows | Minimum candidate-closer share |
| --- | ---: | ---: | ---: | ---: |
| Peak heating | 163 | `+0.0723894` | **117/163 (71.78%)** | 27/163 (16.56%) |
| Settlement | 205 | `+0.0478624` | **137/205 (66.83%)** | 36/205 (17.56%) |
| **Overall** | **368** | **`+0.0587263`** | **254/368 (69.02%)** | **57/368 (15.49%)** |

The direction is therefore not a generic broadening repair. It is predominantly a sharpening
repair, concentrated especially in six markets, on a project where global sharpening is retired
and the severe tail is centre overconfidence. That is a risk flag, not evidence of skill.

## Draft preregistration repair

`docs/roadmap/observation-recovery-single-environment-preregistration-draft-2026-09-77a.json` is now
draft schema v2 and remains exactly
**`DRAFT_NOT_FROZEN_ALPHA_UNALLOCATED_NOT_EXECUTABLE`**. It was not frozen or executed.

- Removed `candidate_field_mde_at_80_percent_power`; its `0.2164` value came from the ceiling's
  dispersion and was not an MDE for the paired improvement estimand.
- Replaced the ceiling screen with the two 100,000-draw simulated-estimand SEs and their actual
  Null-I / Null-C MDE decisions.
- Kept the correctly oriented primary row formula unchanged.
- Added a concrete intersection-union sharpening guard. The sharper subset is fixed now as the 254
  rows with `||p||^2-||q||^2 > 0`. At a future authorized look, define `candidate_closer_i = 1`
  only where realized `delta_i > 0` (ties count zero); its crossed lower bound at `q=3.1098893`
  must exceed `0.5`. The primary mean rule and this guard must both pass. A mean win cannot pass
  alone.

The power screen says not to authorize that future look. The guard is retained so the draft is
honest if an operator later overrides the NO-GO and separately freezes and allocates it.

## Artifacts and receipts

Evidence commit: **`d0757d7c594f54e50ce07dc61828129c2ffd8e9a`** on branch
**`codex/workstation-does-the-look-have-power-2026-09-78a`**.

```text
3d782223e5b882d2bbda233f6abaed42b1a30442126979835720aa7e610611a8  docs/roadmap/repair-ceiling-single-environment-2026-09-77a.csv
d0d6698ba3216cbf749eec303681888403639f6ac04cd53eae8328fcebd91255  tools/research/measure_estimand_power_and_sign_09_78a.py
62a8429e573f3f10952e24a57b45ac7f2f10ad4241ceceb99e300c245c5d4f4b  tools/research/measure_estimand_power_and_sign_09_78a_seed.json
6a1892222b1a9f46d64b283fce21d616e54e44b62649ddae2356268cce09af37  docs/roadmap/estimand-power-and-sign-2026-09-78a.json
d22be15116773036221b204cba654dfda543d2056cd86f20412204ff50dbfaf5  docs/roadmap/estimand-power-and-sign-breakdown-2026-09-78a.csv
6c0d770947c8a2a40651f4a557882c337a7bad9f059e8a6e94b36035f9a16d74  docs/roadmap/observation-recovery-single-environment-preregistration-draft-2026-09-77a.json
```

The `.sha256` receipt reproduces all six entries. No artifact uses Git LFS.

## Verification and roll verdict

```text
input CSV checksum gate                                PASS
estimand orientation and reachable NO-GO self-test    PASS
100,000 draws per null / analytic mean receipts       PASS
independent-seed Null-C verdict                        NO_GO_UNPOWERED
JSON parse (seed, result, repaired draft)              PASS
six-file SHA-256 receipt                               PASS
git diff --check                                       PASS
python -m weather.operations.agent_docs_audit          PASS (18 agent files, 816 Markdown files)
```

The host's ordinary local `master` was stale, so an initial script invocation incorrectly included
127 upstream files and was rejected as an invalid base comparison. I did not move or modify that
branch. I reran the **unchanged repository-owned** `roll_verdict.ps1` in a disposable sparse clone
under `scratch/`, with `master = d153bae9` (the actual mission base), evidence commit `d0757d7c`,
and copied read-only live closure receipts. It returned exit 0:

```text
base:     master (d153bae)
changed:  6 file(s); 0 importable
VERDICT: ROLL-FREE
```

The report is a seventh documentation-only file and cannot enter a Python closure. Per-file:

| Changed file | Roll verdict |
| --- | --- |
| `docs/roadmap/agent-report-2026-09-02-workstation-estimand-power-and-sign.md` | ROLL-FREE — documentation |
| `docs/roadmap/estimand-power-and-sign-2026-09-78a.json` | ROLL-FREE — evidence JSON |
| `docs/roadmap/estimand-power-and-sign-2026-09-78a.sha256` | ROLL-FREE — receipt |
| `docs/roadmap/estimand-power-and-sign-breakdown-2026-09-78a.csv` | ROLL-FREE — evidence CSV |
| `docs/roadmap/observation-recovery-single-environment-preregistration-draft-2026-09-77a.json` | ROLL-FREE — non-executable draft |
| `tools/research/measure_estimand_power_and_sign_09_78a.py` | ROLL-FREE — non-serving research harness |
| `tools/research/measure_estimand_power_and_sign_09_78a_seed.json` | ROLL-FREE — research seed |

Production should re-run the normal command against the pushed branch before merge:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts\ops\roll_verdict.ps1 `
  -Branch origin/codex/workstation-does-the-look-have-power-2026-09-78a
```

## Production-host reproduction

Run from the production repository root using its existing Python 3.11. Install nothing. This reads
only the committed arm-vector CSV and writes regenerated small artifacts inside the disposable
verification worktree.

```powershell
$repo = 'C:\Users\micha\Desktop\github\weather'
$branch = 'origin/codex/workstation-does-the-look-have-power-2026-09-78a'
$python311 = Join-Path $repo 'venv\Scripts\python.exe'
$verifyRoot = Join-Path $repo 'scratch\w\verify-estimand-power-09-78a'

Set-Location $repo
git fetch origin '+refs/heads/*:refs/remotes/origin/*'
git worktree add --detach $verifyRoot $branch
Set-Location $verifyRoot

$csv = 'docs\roadmap\repair-ceiling-single-environment-2026-09-77a.csv'
$expected = '3d782223e5b882d2bbda233f6abaed42b1a30442126979835720aa7e610611a8'
$actual = (Get-FileHash -Algorithm SHA256 -LiteralPath $csv).Hash.ToLowerInvariant()
if ($actual -ne $expected) { throw "STOP: CSV checksum mismatch: $actual" }

& $python311 tools\research\measure_estimand_power_and_sign_09_78a.py self-test
& $python311 tools\research\measure_estimand_power_and_sign_09_78a.py run `
  --repo-root $verifyRoot `
  --seed tools\research\measure_estimand_power_and_sign_09_78a_seed.json

Get-Content docs\roadmap\estimand-power-and-sign-2026-09-78a.sha256
```

Expected verdict:
`NO_GO_UNPOWERED_UNDER_CANDIDATE_CALIBRATION_CLOSE_THREAD_KEEP_ALPHA`. Expected primary values:
`SE_I = 0.0454452902`, `MDE_I = 0.1795775429`, `SE_C = 0.0397607208`, and
`MDE_C = 0.1571149069`.

## What was not done

No realized band, settlement, label, outcome, market price, market probability, or C endpoint was
read. No historical environment, commit binding, identity binding, or synthetic historical tree was
constructed. No replay, snapshot scan, raw payload read, provider call, exchange call, model fit,
candidate production, promotion, activation, release, trading action, registration, scheduled-task
mutation, production write, restart, or merge occurred. The serving floor was not changed. Nothing
was written under production `data/`; the roll validation copied four read-only closure receipts
only into a disposable directory under `scratch/`. No branch was deleted, rebased, reset, moved, or
otherwise modified; only the specifically requested mission branch was created and committed.
