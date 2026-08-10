# Workstation report 2026-09-58a — one own-information feature

## Verdict

**NO-GO: NEITHER PIT-HONEST OWN-INFORMATION DISPERSION SIGNAL PREDICTED OUR
EXCESS LOSS ON THE IN-SEASON B DISAGREEMENT SET. NO FEATURE WAS BUILT, C WAS
NOT SCORED, AND CAMPAIGN DECISION 8 CLOSED UNUSED.**

The cheaper falsifier fired exactly as the handoff required. Seven-run
forecast-high instability and strictly lagged station forecast-error
dispersion both made forward out-of-date excess-loss prediction worse at their
point estimates, and neither crossed interval established a positive
association. Building a conditional smoother after that result would be
working around the mission's most valuable outcome, so P1 did not start.

This is a NO-GO for these two materialized, mechanism-bearing dispersion
surfaces, not a theorem that no future own-information source can ever help.
The other named candidates did not provide a comparable fleet-wide retained
PIT surface on this sealed panel: a free-source multi-source high is not
materialized for all 12 markets, and a cutoff-aligned forecast path for an
intraday trajectory residual is not retained consistently enough to avoid
synthesis. Neither was substituted with stitched or paid-provider data.

## P0 population and method

The sealed `-09-44a` repaired surface reproduced at **D=23 date clusters,
M=12 markets, 204 market-days, 4,636 snapshots, and 50,996 band rows** in
in-season B. Market disagreement was used only for the permitted study-
population rule: a snapshot entered when its maximum bandwise absolute gap
between repaired model probability and normalized market probability was at
least `0.30`.

That selected **1,536 snapshots in D=22, M=12, 196 market-days**. The outcome
was our mean snapshot-level categorical Brier-sum excess over the raw market
probabilities within each date × market cell. Market price entered that
retrospective outcome and the study-population flag only. It entered neither
candidate signal nor any hypothetical serving input.

The two mechanisms were frozen in ignored scratch before their association
numbers were calculated:

1. `run_instability_sd_c`: population standard deviation, in C-equivalent
   units, of the seven `forecast_high_c` values at exact lead days 1–7.
2. `lagged_error_dispersion_sd5_c`: population standard deviation of the
   lead-1 forecast-high error over the last five strictly earlier,
   promotion-countable settled days for that station.

For each signal, an expanding target-date forward chain compared a ridge
baseline (intercept plus market fixed effects) with the same model plus one
training-standardized signal. A date was scored only after six earlier date
clusters. The primary association measure is baseline OOF residual MSE minus
feature OOF residual MSE, so positive is useful. Uncertainty is a 10,000-draw
crossed target-date × market pigeonhole bootstrap over the fixed OOF loss
differences.

## P0 result

| Signal | Available B support D/M/MD | Forward OOF support D/M/MD | OOF MSE improvement [crossed 95%] | Relative | Power / 80% MDE |
| --- | --- | --- | ---: | ---: | ---: |
| Seven-run forecast-high SD | 17/12/148 | **11/12/118** | **`-0.002960 [-0.012636, +0.003834]`** | **-1.332%** | `0.113` / `0.011356` |
| Lagged five-day forecast-error SD | 20/12/144 | **14/12/135** | **`-0.013338 [-0.068979, +0.001003]`** | **-6.169%** | `0.103` / `0.055613` |

Both point estimates have the wrong sign and both intervals include zero.
Neither passes the frozen carry-forward rule of a positive point with a
positive crossed lower bound. The low plug-in powers do not turn this into a
positive result; they say the association screen does not support carrying a
mechanism to C. The negative points must not be redescribed as evidence that
dispersion is protective.

These MDEs describe the **P0 association instrument** in OOF-residual-MSE
units. They are not feature effect MDEs and are not compared with the 3.2%
forecast-effect floor.

## PIT audit — read from the data, not a manifest

Across the 12 retained `forecast_daily_by_issue.csv` files, the data itself
contains:

| `issue_time_basis` / source | Rows | Disposition |
| --- | ---: | --- |
| `fixed_lead_day_offset` / `open_meteo_previous_runs` | **25,620** | accepted |
| `stitched_continuous_archive` / `open_meteo_historical_forecast` | **5,532** | rejected |

Every accepted row has a non-empty issue time before its target date. Exact
leads 1–7 were present for 3,660 market-dates across the retained history.
The accepted source ends at **2026-06-23**. It has **zero rows, zero dates, and
zero markets after B through 2026-07-30**. That is a source-coverage audit;
no C outcome was used or scored to obtain it.

This is the hard wall named in §0a. The stitched rows contain richer settled
weather but no true issue time. Using them would reintroduce
`stitched_forecast_high_without_issue_time`, the declared train/serve parity
defect. The analysis rejects them by row-level `issue_time_basis` and source,
not by what a request manifest claimed it intended to collect.

## Why P1 and P2 did not run

No P0 signal cleared the association rule, so no feature, residual learner,
conditional smoother, artifact, or serving branch was built. C stayed clean:
**zero C outcomes were calculated, fitted, ranked, or scored**. Decision 8's
two-sided `alpha=0.0025` was therefore not spent; the ledger records the slot
as closed unused and forbids reassignment.

There is consequently **no feature-native effect field and no honest
feature-native MDE to derive**. Reusing `-09-57a`'s repair-minus-control proxy
would violate the handoff. No effect is placed against the 3.2% floor, no
post-boundary date is scheduled, and nothing is labelled
`SELECTED_ON_PREBOUNDARY_PANEL`.

The `-09-56a` 85.632% market-replacement ceiling is not used as an expected
delta. It measures what the market knows on the disagreement set; this mission
found no evidence that either screened weather-only dispersion surface supplies
that information. No accuracy number here is translated into expected P&L.

## Independent verification and evidence

An independently written verifier rebuilt the B disagreement outcome, both
signals, and both expanding ridge prediction paths using augmented least
squares rather than the analysis solve. It matched every OOF key and
prediction, recomputed both points and intervals, confirmed zero accepted PIT
rows after B through July 30, and returned **PASS, 14/14 checks**.

Ignored workstation evidence root:
`C:\Users\Michael\Documents\github\weather\scratch\runs\own-information-feature-2026-09-58a`.
It is research evidence and is not claimed to exist on production.

| Evidence | SHA-256 |
| --- | --- |
| P0 predeclaration | `c2bbe831a05b055bdec664d8979f3ba7d3d225bab66d09d1f60b99001c20d085` |
| Analysis script | `3e26bfe53151071f097de240f5805dd95b6f110cd17e9bf39408460cb52fe24f` |
| Result JSON | `ce9f11ded58b6bb15cb76c3f50c3e8882f609032e28657c287943800a28028d9` |
| OOF predictions | `b3b208bedeaf522d311f2770077ed0fa5457fc02e1c72872040c015a91c385ef` |
| Crossed draws | `cf02cddbaf5b9f42f5ca98d1ea223b1a3296deca45ff1f71eea786fe78a23256` |
| Independent verifier | `e269ae0eac8c279fbfab9636246d8e4ac1c7f7d7446a6430dab273e7da4514a0` |
| Verification receipt | `32024b5d4e69c13e50cf6c78eb9234d1c76b75f4904daf5c2aca4cd39e21570a` |

The sealed paired input SHA-256 is
`4352e77692893c3ac36add9653eabfe0d014de7a02bf083ec6c10e2944dc4e88`.
The reserved-window SHA-256 is
`b8a2f9ece4d62403050deab360711eb55b58c06d4bcfe12fa461bbb5c67e6ee4`;
it stated that no dates were reserved.

Exact workstation reproduction:

```powershell
$repo = 'C:\Users\Michael\Documents\github\weather'
$python = 'C:\Users\Michael\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
$run = Join-Path $repo 'scratch\runs\own-information-feature-2026-09-58a'
Set-Location $repo

& $python "$run\analyze_p0_association.py"
& $python "$run\verify_p0_association.py"
Get-FileHash "$run\p0-association-result.json", "$run\p0-verification.json" -Algorithm SHA256
```

The repository venv still points to a removed Python 3.11 installation, so the
already-present bundled Python 3.12 runtime was used. Nothing was installed.

## Roll verdict

The branch changes two Markdown files only. The mechanical verdict is recorded
after running `scripts\ops\roll_verdict.ps1`; both files enter none of the four
capture closures and are roll-free.

| Changed file | Snapshot | CLOB | Observation-trigger | CLOB-enrichment | Verdict |
| --- | --- | --- | --- | --- | --- |
| `docs/operations/CAMPAIGN_LEDGER.md` | none | none | none | none | Roll-free Markdown |
| `docs/roadmap/agent-report-2026-08-19-workstation-own-information-feature.md` | none | none | none | none | Roll-free Markdown |

## Explicitly not done

- No production `data/`, workstation mirror, release store, settlement tape,
  or operational evidence was written.
- No provider or exchange endpoint was called; no chain, settlement,
  collector, scheduled task, supervisor, or loop ran or restarted.
- No feature, candidate, fitted C model, artifact, release, pointer,
  confirmation window, promotion, activation, serving change, order, or live
  trading action was created.
- No market price entered a feature or serving branch. Market disagreement
  defined the P0 population only.
- No observed-high floor, probability-mass rule, admission bar, promotion
  gate, or harvest contract was weakened.
- No registration, PR, merge, master update, production checkout, branch
  deletion, or history rewrite was performed.

## Production-host acceptance commands

The raw measurement is intentionally workstation-local. These commands use
production paths to verify the committed handback, ledger control, exact diff,
documentation validity, and mechanical roll classification:

```powershell
$repo = 'C:\Users\micha\Desktop\github\weather'
Set-Location $repo
git fetch origin
$branch = 'origin/codex/workstation-one-own-information-feature-2026-09-58a'
$report = 'docs/roadmap/agent-report-2026-08-19-workstation-own-information-feature.md'

git rev-parse $branch
git show "${branch}:$report"
git show "${branch}:docs/operations/CAMPAIGN_LEDGER.md"
git diff --name-status origin/master...$branch
git diff --check origin/master...$branch
.\venv\Scripts\python.exe -m weather.operations.agent_docs_audit
powershell.exe -NoProfile -ExecutionPolicy Bypass -File `
  .\scripts\ops\roll_verdict.ps1 -Branch $branch
```

Expected tracked diff: the ledger and report paths above only. Expected roll
verdict: `ROLL-FREE`, exit `0`.

Branch: `codex/workstation-one-own-information-feature-2026-09-58a`.

Initial report and ledger commit: recorded after commit.
