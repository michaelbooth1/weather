# Workstation report 2026-09-63a — decision 10 B-only screen

## Verdict

**NO-GO AT GATE 3. DECISION 10 CLOSES UNUSED.** The frozen feature SHA-256 reproduced, but the
pre-fit B-only integrity pass found a realized winning band with incumbent repaired probability
exactly `0.0`. The support-preserving exponential tilt cannot assign that outcome positive mass for
any beta, and the frozen protocol forbids adding epsilon mass. I stopped before fitting.

No beta vector, Gate-1 training delta, Gate-2 expanding-window curve, C state, C endpoint,
candidate-native MDE, bootstrap draw, or clone control was computed. Alpha remains **7 of 20 spent,
13 available**. Decision 10 is retired and must not be reassigned.

## Frozen artifacts and the fatal row

The user-required feature check passed before the screen:

| Artifact | Frozen SHA-256 | Reproduced SHA-256 | Result |
| --- | --- | --- | --- |
| `pit-lead1-daily-features-2026-09-61a.csv` | `60b450f1dd1ee575acde86607d179ae0cae68ddee541feef664923bd62b71ac8` | same | **PASS** |
| Frozen protocol | `336150be1a62e88c2fe40ccd7b77916576d08981617ebbff1e01195007cfc146` | same | **PASS** |
| Retained paired band panel | `4352e77692893c3ac36add9653eabfe0d014de7a02bf083ec6c10e2944dc4e88` | same | **PASS** |

The fatal B record is unambiguous in the retained paired file:

| Field | Value |
| --- | --- |
| Target date / market | `2026-06-08` / `denver` |
| Snapshot / record hash | `20260608T030552-0400` / `b78d94c54bb63f1d72d414c5795946351ec705421b2838fcc7c48652f3bf3e26` |
| Realized winning band | `4` |
| Outcome | `1` |
| Incumbent input | repaired served probability |
| Incumbent probability on winner | **`0.0`** |

The protocol states: if the incumbent assigns zero probability to any realized B winning band,
fail closed rather than add epsilon mass. This is necessary, not cosmetic. For the frozen map,

```text
q[b] ∝ p[b] exp(r[b] x·beta)
```

`p[4]=0` implies `q[4]=0` for every finite beta. Its categorical loss is `-log(0)`, so there is no
finite objective to optimize. Adding epsilon would change zero support, weaken the serving-floor
contract, and alter the frozen candidate after seeing the failure.

## Gate results and requested readouts

| Gate / readout | Result |
| --- | --- |
| Required feature hash | **PASS** |
| Gate 3 winning-band zero / zero-support / floor | **FAIL — fatal** |
| Gate 1 full-B Brier | **NOT RUN** — sequential stop |
| Gate 2 13-date expanding window | **NOT RUN** — sequential stop |
| Full-B beta vector | **NOT FITTED** |
| Expanding-window date curve | **NOT PRODUCED** |

The retained incumbent's established total-B Brier is `0.053379789`; it is shown only as the frozen
reference, not as a newly computed result. Candidate Brier and delta are unavailable because the
candidate was never legally instantiated. The mechanism is therefore **untested**, not contradicted:
there are no coefficient signs from which to infer radiative heating, cloud limitation, ventilation,
convection, precipitation, or evaporation effects. A fabricated beta or an epsilon-rescued fit would
turn a decisive protocol failure into a fluke.

The frozen B population is D=23 dates, M=12 markets, 204 market-days, 4,636 snapshots, and 50,996
band rows. The failure is a row-level algebraic impossibility, not an uncertainty result, so no
interval or power calculation applies.

## The C boundary and alpha accounting

The harness checks the raw fourth CSV token before parsing a row. Non-B lines are rejected as raw
bytes; their outcome and probability columns are never CSV-parsed. For B rows the harness reads only
identity, band index, outcome, and `repair_probability`. It does not read even the B market-price
column.

Consequently:

- no C outcome, C market probability, or C candidate probability was read or computed;
- no C endpoint, C MDE, crossed bootstrap draw, or clone control was built;
- no result used rows after `2026-07-30`, and nothing was pooled across `2026-07-31`;
- amendment A1 was irrelevant because no interval was constructed;
- decision 10 spent no alpha and is **CLOSED UNUSED**;
- campaign accounting remains **7 of 20 spent, 13 available**.

## Determinism and evidence hashes

The bundled runtime was Python `3.12.13` with NumPy `2.3.5`; nothing was installed and no RNG was
invoked. The committed audit seed is `20260963`. Had the integrity gate passed, every one of the
frozen fits would have made one deterministic damped-Newton run from twelve zeros, with analytic
gradient and Hessian and the required `||gradient||_infinity <= 1e-8` convergence gate. That path was
not entered.

| Evidence | SHA-256 |
| --- | --- |
| Committed harness | `86674cfca78d69789ff34e3846cb70f30673cf82698e317ff5c22b6c3306cf89` |
| Ignored result JSON | `b47141b4aad58964eef6a0d484cb6a34f65e6fbaa470377f92d812ed555c3144` |
| Feature manifest | `2bc0dda65ec83e81f0b7c6a08d8d5598bc247acd9fca75a66ebcc889d6d96c28` |

The execution used the harness's pre-fit integrity path. The `--validate-only` flag never affected
the outcome because the winning-band gate fires while the B panel is constructed, before the code
can branch on that flag. Running the no-flag reproduction command below reaches the same fatal gate
before any fit.

## Explicitly not done

- No feature, lambda, start, coefficient, lead, or candidate family was tuned or substituted.
- No epsilon repair, support change, serving-floor weakening, candidate activation, release,
  promotion, production-data write, provider call, exchange call, order, or live-trading action
  occurred.
- No production chain, settlement, collector, scheduled task, supervisor, or loop was run or
  restarted.
- No PR, merge, master update, branch deletion, or production checkout change was performed.

## Reproduction and acceptance

On the workstation holding the retained paired evidence:

```powershell
$repo = 'C:\Users\Michael\Documents\github\weather'
Set-Location $repo
$python = 'C:\Users\Michael\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'

Get-FileHash -Algorithm SHA256 `
  .\docs\roadmap\pit-lead1-daily-features-2026-09-61a.csv
& $python .\tools\research\b_only_screen_09_63a.py
```

Expected exit is `3`, verdict `NO_GO_GATE_3`, failed gate `GATE_3_WINNING_BAND_ZERO`, before any fit.

Production-host acceptance uses only committed paths:

```powershell
$repo = 'C:\Users\micha\Desktop\github\weather'
Set-Location $repo
git fetch origin
$branch = 'origin/codex/workstation-run-the-b-only-screen-2026-09-63a'
$report = 'docs/roadmap/agent-report-2026-08-19-workstation-b-only-screen.md'

git rev-parse $branch
git show "${branch}:$report"
git diff --name-status origin/master...$branch
git diff --check origin/master...$branch
.\venv\Scripts\python.exe -m weather.operations.agent_docs_audit
powershell.exe -NoProfile -ExecutionPolicy Bypass -File `
  .\scripts\ops\roll_verdict.ps1 -Branch $branch
```

## Roll verdict and branch

The repository-owned roll verdict will be recorded after the report and canonical accounting update
are committed. The analysis harness commit is `e9836c9a1a8caab5ff430d66d5e8d74590b55099`.

Branch: `codex/workstation-run-the-b-only-screen-2026-09-63a`.
