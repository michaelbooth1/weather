# Agent report 2026-09-60a — conditional tail reshape

**VERDICT: NO-GO AT P0, WITH ZERO CAMPAIGN-LEDGER COST. CONDITIONAL OWN-DISTRIBUTION
RESHAPING DOES NOT BEAT GLOBAL SMOOTHING ON IN-SEASON B.** The frozen conditional rule is worse
on both its own all-B training score and the predeclared chronological B screen. I therefore stopped
before scoring any candidate on C. Decision 9 remains unspent, its allocated ledger row is unchanged,
and no candidate-native MDE was derived because no candidate passed the gate that would license that
work.

My pre-result expectation was the opposite: I expected conditional reshaping to beat global weakly,
because the own-distribution trigger should avoid smoothing the bulk that was already fine. I anchored
that expectation to §1c's global `8.829% [-2.467%, +16.494%]`, not §1f's 27.42% addressability
ceiling. P0 falsified the expectation cleanly.

## P0 result

The retained input is the exact `-09-44a` repaired band surface, SHA-256
`9a70ac80143a7eea9b14003b2f992413d622b167ce35ea4be54273cfdf3e27ae`. P0 used only
in-season B: **D=23 dates, M=12 markets, 204 market-days, 4,636 snapshots, and 50,996 band rows**.
The §1c positive control reproduced: the legacy global power-map fit selected **beta=0.55**.

The predeclared conditional mechanism was:

```text
trigger: max own served band probability >= fitted threshold
reshape on triggered snapshots only:
    q_i = p_i^beta / sum_j(p_j^beta) for p_i > 0
    q_i = 0 wherever incumbent p_i = 0
untriggered snapshots: identity
```

The trigger uses band state only. Market probability, model-market disagreement, settlement outcome,
weather-provider data, and post-cutoff information do not enter the trigger or reshape. The fitted
conditional rule was **beta=0.52**, threshold **0.65**, firing on **46.7860%** of B snapshots.

### Own-training sanity check — failed

| B score | Brier |
| --- | ---: |
| Incumbent | `0.053379789` |
| Global smoothing, beta=0.55 | **`0.050612803`** |
| Conditional, beta=0.52 / threshold=0.65 | `0.051511678` |

Conditional is worse than global by **`0.000898875` Brier** on the same B training surface used to
fit it. Both improve the incumbent, but conditioning discards part of the global benefit instead of
concentrating it.

### Chronological B-only screen — failed in the same direction

The screen trained on the first 10 B dates, then selected parameters using strictly prior dates for
each of the remaining 13 target dates. Support is **D=13, M=12, 135 market-days, 3,096 snapshots,
34,056 band rows**.

| Forward B score | Brier |
| --- | ---: |
| Global smoothing | **`0.053566688`** |
| Conditional reshaping | `0.054804104` |

The paired global-minus-conditional improvement is **`-0.001237416` Brier**, with a descriptive
two-sided crossed date × market 95% interval **`[-0.003005130, +0.000583109]`** and crossed standard
error `0.000903836`. It is not distinguishable from zero, but the point estimate is in the wrong
direction and the P0 rule required conditional to beat global, not merely avoid established harm.

This is the whole decision. The direction is closed under the declared peak-probability trigger and
conditional power reshape. There was no threshold-tuning rescue after the result.

## Floor, mass, and endpoint boundaries

The reshape preserved probability mass and kept every incumbent zero exactly zero. B contains
**12,882 zero-probability band rows**; independent verification found zero candidate mass on all of
them. The serving floor was not weakened.

P0 loaded the sealed file to verify full support, then filtered to B before constructing or scoring
any reshape. It computed **no C candidate score**. Consequently:

- Tail SSE on C was not scored.
- Total excess Brier versus market on C was not scored.
- Decision 9 was not spent and `CAMPAIGN_LEDGER.md` was not edited.
- No candidate was frozen or labelled `SELECTED_ON_PREBOUNDARY_PANEL`.
- No candidate-native sealed-panel or post-boundary MDE was derived. Reusing §1d's proxy would have
  violated the handoff; deriving an MDE for a candidate that failed P0 would have violated the stop
  rule.

## Verification and retained evidence

An independent verifier reloaded the sealed input and reproduced the full-B scores, the 13-date OOF
scores, the crossed interval, the beta=0.55 positive control, probability mass, and zero-support
preservation. It also confirmed that no candidate specification exists, no C score was recorded, and
the campaign decision is unspent. All checks returned `PASS`.

Workstation evidence root:
`C:\Users\Michael\Documents\github\weather\scratch\runs\conditional-tail-reshape-2026-09-60a`.

| Retained artifact | SHA-256 |
| --- | --- |
| `predeclaration.json` | `48bc1e71d4ca2ac2ea3ba98740511a50fbff235121be90a83cd0658bf110623f` |
| `conditional_tail_reshape.py` | `44283a0fde7306c89c8f4a42e80642f315bb15f64debe76ef89c4d41542c9994` |
| `p0-result.json` | `be1e691768273d9ddf99923e709b033399549d368c5ec44113aa013b22498a68` |
| `p0-crossed-draws.csv` | `ba51a1e637f52bcefb62731a827689ef5f6c3ddcc3ef48f96000b0434229af06` |
| `verify_p0.py` | `e717ef9c0b2454b3606a65e247064b1ade7b9ab9b74bd99876d32eb636759eb4` |
| `verification.json` | `5fbf12742e01fecd1a1ab4287b77229639d01aa126451082634965b58b2b0653` |

The analysis used the bundled Codex Python 3.12 runtime. Nothing was installed and no network call
was made.

### Exact workstation reproduction

These paths exist on the workstation retaining the sealed evidence:

```powershell
$repo = 'C:\Users\Michael\Documents\github\weather'
$python = 'C:\Users\Michael\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
$run = Join-Path $repo 'scratch\runs\conditional-tail-reshape-2026-09-60a'
Set-Location $repo
& $python (Join-Path $run 'conditional_tail_reshape.py') p0
& $python (Join-Path $run 'verify_p0.py')
Get-FileHash -Algorithm SHA256 -LiteralPath (Join-Path $run 'verification.json')
```

## Safety and handback

What I did **not** do: no C candidate scoring; no campaign-ledger spend; no provider or exchange
call; no production `data/` or workstation-mirror write; no settlement, chain, scheduled task,
collector, supervisor, or loop run/restart; no release-store write; no candidate promotion,
activation, serving change, order, or live trading; no serving-floor, probability-mass, admission,
promotion, or harvest-only relaxation; no PR, merge, registration, branch deletion, or production
checkout change.

The only tracked file changed is this report. Its retained-closure membership and mechanical roll
verdict are bound in the provenance follow-up commit after running
`scripts\ops\roll_verdict.ps1 -Branch codex/workstation-conditional-tail-reshape-2026-09-60a`.

Exact production-host acceptance commands:

```powershell
$repo = 'C:\Users\micha\Desktop\github\weather'
$branch = 'codex/workstation-conditional-tail-reshape-2026-09-60a'
$report = 'docs/roadmap/agent-report-2026-08-19-workstation-conditional-tail-reshape.md'
Set-Location $repo
git fetch origin $branch
git show "origin/$branch`:$report"
git diff --name-status origin/master..."origin/$branch"
git diff --check origin/master..."origin/$branch"
.\venv\Scripts\python.exe -m weather.operations.agent_docs_audit
powershell.exe -NoProfile -ExecutionPolicy Bypass -File `
  .\scripts\ops\roll_verdict.ps1 -Branch "origin/$branch"
git rev-parse "origin/$branch"
git ls-tree -r --name-only "origin/$branch" | Select-String `
  'agent-report-2026-08-19-workstation-conditional-tail-reshape.md'
```

Branch: `codex/workstation-conditional-tail-reshape-2026-09-60a`.

Base: `99ea070666107a3c2d7e36d41f12ca1ea13d43da`.

