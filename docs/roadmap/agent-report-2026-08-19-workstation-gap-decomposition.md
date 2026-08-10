# Workstation report 2026-09-56a — current-surface gap decomposition

## Verdict

**INFORMATION DOMINATES THE CURRENT OUT-OF-SEASON GAP. THE USABLE, SIMPLEX-NATIVE
RECALIBRATION ESTIMATE RECOVERS 8.829% OF EXCESS BRIER, BUT ITS CROSSED INTERVAL
IS [−2.467%, +16.494%] AND THE RECOVERY IS NOT DISTINGUISHABLE FROM ZERO. AT
LEAST 83.506% OF THE GAP REMAINS INFORMATION/RESOLUTION DEFICIT UNDER THIS
DESIGN. THE PREDECLARED ISOTONIC MAP IS A NO-GO, AND MARKET-INFORMATION CONTROLS
CLOSE LARGE SHARES OF THE GAP WITHOUT ESTABLISHING ANY INDEPENDENT MODEL EDGE.**

The current surface is therefore not calibration-dominated. The point split on
the stratum actually served is **8.829% recalibration / 91.171% information**.
The honest interpretation is not that exactly 8.829% is available: the
recalibration point is underpowered and may be zero. The useful result is the
bound: the crossed 95% interval leaves **83.506% to 102.467%** of the gap after
the fitted mapping, so information dominates throughout the interval.

No mapping, model, candidate, artifact, release, promotion, or serving change
was activated. All fits were diagnostic scratch work.

## Question and denominator

This report estimates exactly the handoff's requested quantity on the repaired
current surface:

```text
raw gap                 = raw current-model Brier − market Brier
calibration recovery    = raw current-model Brier − mapped-model Brier
information residual    = mapped-model Brier − market Brier
calibration share       = calibration recovery / raw gap
information share       = information residual / raw gap
```

The two shares sum to one. Negative calibration recovery is retained rather
than clipped; it means the mapping made the score worse.

The old **84.772% / 15.228%** Murphy number was not reused. It is a descriptive
same-panel decomposition and does not score a mapping fitted only on earlier
dates. This report fits on stratum B and scores on the later stratum C.

## Evidence and controls

The input is the exact current-surface `-09-44a` repaired replay export,
SHA-256 `9a70ac80143a7eea9b14003b2f992413d622b167ce35ea4be54273cfdf3e27ae`.
It is the retained workstation evidence, not a fresh read of the lagging
production mirror.

| Population | Dates | Markets | Market-days | Snapshots | Band rows |
| --- | ---: | ---: | ---: | ---: | ---: |
| Full current surface | **50** | **12** | **524** | **12,289** | **135,179** |
| B, in-season fit | **23** | **12** | **204** | **4,636** | **50,996** |
| C, out-of-season test | **27** | **12** | **320** | **7,653** | **84,183** |

No row is later than `2026-07-30`; nothing crosses the `2026-07-31`
provenance boundary. Settlement labels, roster, admission, and probability
mass are inherited from and hash-bound to the independently verified
`-09-44a` replay. Maximum current-model mass error is below `1e-9`.

The independent verifier reproduced all four score controls:

| Stratum | Current model Brier | Market Brier | Ratio |
| --- | ---: | ---: | ---: |
| **B, in-season** | `0.053379789` | `0.037505658` | **`1.423246x`** |
| **C, out-of-season / served** | `0.060112820` | `0.038977498` | **`1.542244x`** |

These are the current-surface values from `-09-44a`. The verifier passed
**22 / 22** checks, including the exact source and predeclaration hashes,
support, both ratios, probability mass, rank preservation, point estimates,
and all draw-file hashes.

## Method

The method was frozen in ignored scratch before any new mapping result was
calculated, at predeclaration SHA-256
`d8e49409eb432751da3999b8bf3a6553ec97f7c762430aab7de44309a1c55fda`.

The strict primary fitted an exact scalar PAVA/isotonic map on all B binary
band rows, applied that frozen monotone map to C, and renormalized within each
snapshot. It saw no C outcome and preserved every snapshot's band order.
Inference resampled B fit dates, C evaluation dates, and the shared markets,
then refitted the map in every one of 1,000 draws.

That primary is a **mapping NO-GO**, not a recoverability estimate: it worsened
C Brier by `+0.018168 [ +0.012980, +0.022995 ]`, and the verifier showed why.
Binary PAVA followed by categorical renormalization also worsened its own B
training score, `0.053380 → 0.078717`. The implementation is correct—zero
mass failures and zero order violations—but its fitting objective does not
survive the simplex projection. Per-market and daily-expanding isotonic
sensitivities also worsened C materially.

The usable sensitivity was predeclared separately: the simplex-native mapping

```text
q_i(beta) = p_i ** beta / sum_j(p_j ** beta)
```

The exponent was selected only on B (`beta = 0.55`, smoothing) and frozen for
C. A 10,000-draw full-pipeline bootstrap resampled B dates, C dates, and shared
markets, reselected beta in every draw, and scored the corresponding C map.
The selected-beta median was `0.55`, crossed 95% range `[0.44, 0.70]`.

## Power and MDE before interpretation

| Endpoint | Observed-effect power | 80%-power MDE | Crossed 95% interval |
| --- | ---: | ---: | ---: |
| Temperature-map Brier delta | **0.390** | **0.003110 Brier** | `[-0.003955, +0.000427]` |
| Calibration share of gap | **0.458** | **13.344 percentage points** | `[-2.467%, +16.494%]` |

Power is below the binding 80% bar. The favourable point therefore is not a
scoring win. The interval is nevertheless useful for decomposition: even its
upper endpoint assigns only 16.494% of the current served gap to recoverable
calibration under this leakage-safe family.

## P0 result — the split

| Quantity, out-of-season C | Value | Crossed 95% interval |
| --- | ---: | ---: |
| Raw current-model Brier | `0.060112820` | — |
| Market Brier | `0.038977498` | — |
| Raw excess gap | `0.021135322` | — |
| Mapped-model Brier | `0.058246745` | — |
| Brier improvement | `0.001866075` | `[-0.000427, +0.003955]` |
| **Recoverable calibration share** | **8.829%** | **`[-2.467%, +16.494%]`** |
| **Remaining information share** | **91.171%** | **`[83.506%, 102.467%]`** |

The mapped point moves the ratio from `1.542244x` to `1.494368x`, but the
paired improvement is not distinguishable from zero. This rules out
calibration as the dominant workstream. It does not prove that every possible
monotone family has exactly zero value.

## P1 — ranked worklist

Rank is expected served delta per unit of effort, with strategic limitations
kept in the ranking rather than hidden after it.

| Rank | Addressable candidate | Sized served delta on C | Effort / uncertainty | Cheapest falsifier and limitation |
| ---: | --- | ---: | --- | --- |
| **1** | **Disagreement-gated contemporaneous market probability as an explicit input** | Fixed 50% shrinkage on the predeclared `max |model-market| >= 0.30` set improves Brier by **`0.013761 [0.010011, 0.018194]`**, closing **65.111% `[60.514%, 70.111%]`** of the gap; ratio `1.542x → 1.189x` | Small replay implementation; effect interval tight. Strategic uncertainty is maximal because the input is the benchmark itself | The cheapest test is already positive. A residual learner must then beat the contemporaneous market out of sample. `-09-46a` found zero positive model-skew cells, so fixed shrinkage is a **market-aware baseline, not evidence of independent edge** |
| **2** | **Global temperature smoothing** | Improvement **`0.001866 [-0.000427, +0.003955]`**, 8.829% gap closure point | Very small implementation; effect not powered and unstable historically | Keep diagnostic only unless a fresh forward walk proves the delta. Do not globally sharpen; selected beta is smoothing and the interval includes harm |
| **3** | **Season-matched base-HGB refit on the target-derived window** | If C merely reached B's current gap, the proxy improvement is **`0.005261 [-0.003531, +0.013480]`**, or 24.893% `[-20.496%, +55.190%]` of C gap | Medium/high effort; **proxy, not intervention effect**. Power 0.230; Brier MDE 0.012100 | Fit one diagnostic season-matched HGB and replay C. The current contrast is non-causal and cannot be booked as expected value; even B remains `1.423x` market |
| **4** | **One new point-in-time forecast-resolution feature targeted to disagreement rows**—for example ensemble/source spread or a forecast-error residual, not more completeness | **Unidentified.** Market replacement on the disagreement set is only an opportunity ceiling: `0.018099 [0.012472, 0.024704]` Brier, 85.632% `[79.319%, 90.660%]` gap closure | Medium/high implementation and high effect uncertainty | Add one mechanism-bearing feature at a time to a regularized walk-forward residual model. Do not infer an expected delta from the ceiling; it consumes market information and says where information is missing, not which weather input supplies it |

A fixed 25% global move toward contemporaneous normalized market probabilities
is a useful control: it improves C Brier by
`0.009437 [0.007316, 0.011937]`, closing 44.652%
`[42.055%, 48.722%]` of the gap. This confirms that the missing information is
present in the market benchmark. It cannot be cited as a route to beating that
same benchmark.

### Closed or deprioritized by this result

- **More input completeness is not a ranked gap-closing candidate.** `-09-44a`
  already bounded the largest repair at ~0.6% of the distance to
  parity; no new mechanism was found here.
- **Scalar isotonic probability mapping is NO-GO** on this categorical surface.
- **Global sharpening remains retired.** The fitted exponent is below one.
- **No model-skewed quoting work follows.** `-09-46a` remains controlling.

## Evidence hashes

Ignored workstation evidence root:
`C:\Users\Michael\Documents\github\weather\scratch\runs\gap-decomposition-2026-09-56a`.
It is diagnostic evidence and is not claimed to exist on production.

| Evidence | SHA-256 |
| --- | --- |
| Predeclaration | `d8e49409eb432751da3999b8bf3a6553ec97f7c762430aab7de44309a1c55fda` |
| Analysis script | `7ac6b2a8f8ae5ad86bffe5a06ef0e5ba0f14bef704a51329d025282df6dda37d` |
| Result JSON | `f3ac46d49ef924d4481de5adedf603e3d7610d5a9e35758aedc012ae7189291c` |
| Conditional crossed draws | `b13dc5c7b308b50229101a951d1a19ece5002769e8a3b49870a01da69363dfbf` |
| Full isotonic-pipeline draws | `11250dd8daeb10dc2ce3711631403c0872a5835790a0a00420caacb7aea60f16` |
| Full temperature-pipeline draws | `5ee69304d0e912eb273e83826609d1e53413110baa06e5fbec35ae0b2d9079f0` |
| Seasonal-proxy draws | `2a7979d8648d3b18d000ded56550ffac7176de7dc9939291b166fb517fa3d3e6` |
| Verification receipt | `3b65557ac05cb2a5bf9f9d246b61c5949b8c9c34ea74dc7e43dacda006324e0c` |

The workstation project venv pointed to a missing Python 3.11 installation.
The diagnostic ran with the Codex bundled Python 3.12.13 runtime and its
NumPy/pandas packages. The analysis is dependency-light and does not use
SciPy or network access.

## Roll verdict

`scripts\ops\roll_verdict.ps1 -Branch
codex/workstation-decompose-the-gap-2026-09-56a` returned exit **0**,
**ROLL-FREE**. This workstation's local `master` is intentionally behind the
refreshed `origin/master`, so the script reported the cumulative branch as 15
files with one importable file, `src/weather/operations/operating_reference.py`;
it classified that importable file `free`. The mission diff against its actual
base, `origin/master` at `453b5aa9`, is exactly the Markdown report below.

This mission's intended tracked scope is one roll-free Markdown file:

| Changed file | Snapshot | CLOB | Observation-trigger | CLOB-enrichment | Verdict |
| --- | --- | --- | --- | --- | --- |
| `docs/roadmap/agent-report-2026-08-19-workstation-gap-decomposition.md` | none | none | none | none | Roll-free Markdown |

## Explicitly not done

- No production `data/`, workstation mirror, settlement ledger, snapshot tape,
  market-making evidence, or release store was written.
- No provider or exchange endpoint was called; no collector, chain, settlement,
  scheduled task, supervisor, or loop was run or restarted.
- No candidate, durable artifact, release, pointer, confirmation window,
  promotion, activation, serving change, order, or live-trading action occurred.
- No observed-high floor, probability-mass rule, admission rule, promotion
  gate, or harvest-only contract was weakened.
- No PR, merge, master update, production checkout, registration, or branch
  deletion was performed.

## Production-host acceptance commands

The raw measurement is ignored workstation evidence. The following commands
use paths that exist on production and verify the committed handback, exact
scope, documentation validity, and mechanical roll classification:

```powershell
$repo = 'C:\Users\micha\Desktop\github\weather'
Set-Location $repo
git fetch origin
$branch = 'origin/codex/workstation-decompose-the-gap-2026-09-56a'
$report = 'docs/roadmap/agent-report-2026-08-19-workstation-gap-decomposition.md'

git rev-parse $branch
git show "${branch}:$report"
git diff --name-status origin/master...$branch
git diff --check origin/master...$branch
.\venv\Scripts\python.exe -m weather.operations.agent_docs_audit
powershell.exe -NoProfile -ExecutionPolicy Bypass -File `
  .\scripts\ops\roll_verdict.ps1 -Branch $branch
```

Expected tracked diff: the report path above only. Expected roll verdict:
`ROLL-FREE` / exit `0`.

Branch: `codex/workstation-decompose-the-gap-2026-09-56a`.

Report-content commit: `f48301aea56eff148589fa71e33dc0b8d2be8fba`.
