# Workstation report 2026-09-57a — panel operating characteristics

## Verdict

**GREEN LIGHT FOR USING THE SEALED PANEL TO REFEREE SEVERITY-TAIL WORK; NO-GO FOR
REUSING IT AS AN UNBOUNDED SEQUENCE OF UNADJUSTED ACCEPT/REJECT TESTS. THE
TAIL-BLINDNESS PREMISE IS FALSIFIED, WHILE THE PRIMARY 09:00–14:00 ENDPOINT
REMAINS TOO BLUNT FOR THE SMALL STEPS THE PROGRAMME WANTS.**

The `-09-44a` positive control reproduced exactly: in-season paired ratio MDE
`0.0030551161` ratio points, **0.7218% of the remaining in-season distance to
parity**. That is good news. The paired design is a fine instrument for that
surface, and `-09-44a` was a precise null rather than a blind test.

The feared endpoint is not blind. On the current-surface frozen severe tail —
5,930 band rows, **4.3868%** of the panel, carrying **64.1402%** of positive
excess loss — the two-sided 80%-power MDE is **`0.0151764` mean SSE**, only
**3.5326%** of the `0.429609` remaining tail distance to market parity. Even the
worse half of a deterministic 25/25 date split is `0.0240857`, **5.6064%** of
the tail gap. The panel can referee a plausibly shippable tail improvement.

It cannot support an unbounded campaign. Under the global null, testing ten
independent candidate surfaces at one-sided `alpha=0.05` and reporting the best
produces a **39.0%** chance of at least one false acceptance and a mean selected
in-season “improvement” of `0.001617` ratio points. At 20 looks those become
**64.2%** and `0.002201`; at 50 looks, **92.2%** and `0.003008` — essentially
the full `-09-44a` MDE manufactured by selection. Candidate estimates share
the panel and are correlated, but that correlation is not identified. Even an
assumed `rho=0.5` leaves false-accept probabilities of **25.7%**, **40.8%**, and
**65.7%** at 10, 20, and 50 looks. Multiplicity discipline is not overhead.

The protocol to use is a **20-decision campaign ledger**: pre-register each
mechanism and endpoint before scoring, spend family alpha `0.05` equally
(`alpha=0.0025` two-sided per decision), retain all deterministic and
non-regression gates, report selection-adjusted evidence rather than the raw
best estimate, and retire the panel after decision 20. A shipped step is
`SELECTED_ON_PREBOUNDARY_PANEL`, not confirmed. Small steps should be batched
until their combined out-of-season effect is confirmable on post-boundary data.

There is no honest single P2 date yet because `-09-56a` is concurrently
estimating the effect size and this mission was forbidden to depend on it.
The dated conditional answer is: a **5% closure of the current out-of-season
gap** reaches 80%-power MDE at **D=73, 2026-10-16**; D=72 does not. A step at
the current out-of-season full-panel MDE (`0.0377305`, 6.9582% of the gap)
reaches it at **D=29, 2026-09-02**; D=28 does not. Under the required crossed
date × market treatment, the 12 fixed market clusters leave an asymptotic MDE
floor of about **`0.0173` ratio points, 3.2% of the out-of-season gap**. A 2.5%
step is therefore not confirmable at any date count under this planning proxy.

No post-boundary row was read or pooled to obtain that schedule. It is a
design simulation over the sealed out-of-season cluster structure, not a new
post-boundary measurement.

## Method and binding limitation

Input is the exact retained `-09-44a` paired band surface:

| Property | Value |
| --- | ---: |
| Target dates | `2026-06-03` through `2026-07-30` |
| Date clusters | **50** |
| Market clusters | **12** |
| Promotion-countable market-days | **524** |
| Band rows | **135,179** |
| Paired input SHA-256 | `4352e77692893c3ac36add9653eabfe0d014de7a02bf083ec6c10e2944dc4e88` |

All P0 uncertainty uses the same shared-weight crossed target-date × market
pigeonhole bootstrap as `-09-44a`, with 10,000 replicates. MDE is two-sided
`alpha=0.05`, 80% power, normal approximation, exactly matching the retained
positive-control definition. Power was priced before interpreting the paired
point deltas.

**An MDE is not a property of date count alone.** Its standard error depends on
the candidate-minus-incumbent cluster-effect field. This mission extends the
hash-bound `-09-44a` repair-minus-control field because that is the only way to
make `0.003055` a real positive control. A future candidate with a different
date/market effect shape has a different MDE. Every number below is therefore
an operating-characteristic proxy for this retained paired surface, not a
universal guarantee about arbitrary candidates.

The severity tail is frozen on the **current repaired incumbent before any
future candidate**: incumbent SSE exceeds market SSE and absolute incumbent /
market probability disagreement is at least 30 points. The primary slice is
effective cutoff 09:00–14:00. Nothing sees a future candidate's outcome when
membership is defined.

## P0 — per-endpoint operating characteristics

| Endpoint | D / M / MD / rows | Paired point delta [crossed 95%] | Current → parity gap | 80% MDE | MDE / gap |
| --- | --- | ---: | ---: | ---: | ---: |
| **In-season ratio** | 23 / 12 / 204 / 50,996 | `−0.0000140 [−0.0022674, +0.0024795]` | `1.423246 → 1.0 = 0.423246` ratio | **`0.0030551` ratio** | **0.7218%** |
| **Out-of-season ratio** | 27 / 12 / 320 / 84,183 | `+0.0161453 [−0.0095803, +0.0430959]` | `1.542244 → 1.0 = 0.542244` ratio | **`0.0377305` ratio** | **6.9582%** |
| **Current-surface severity-tail SSE** | 49 / 12 / 487 / 5,930 | `+0.0162202 [+0.0062849, +0.0275638]` | `0.502030 → 0.072422 = 0.429609` mean SSE | **`0.0151764` SSE** | **3.5326%** |
| **09:00–14:00 Brier** | 49 / 12 / 523 / 34,694 | `−0.0000651 [−0.0012109, +0.0011578]` | `0.069062 → 0.051158 = 0.017904` Brier | **`0.0016776` Brier** | **9.3700%** |

The tail point delta is not a claim that the repair harmed the tail: it uses
current-incumbent-frozen membership to estimate the future instrument's
covariance. The MDE is the deliverable.

The primary-window consequence is unchanged: its MDE is 9.37% of the whole
remaining gap, larger than the small individual steps under discussion.
`ESTABLISHED_FINDINGS.md` §5 already records the approximately 504-date
requirement for the prior declared primary-slice design. This mission does not
re-litigate or replace that requirement with a different paired surface. The
window remains an aspiration and readout, not a useful accept/reject rule for
small increments.

## P1 — selection inflation and the campaign budget

The multiplicity simulation null-centres each endpoint's real crossed-bootstrap
draws, samples 50,000 best-of-k campaigns, and applies an empirical one-sided
5% threshold to every individual candidate. The table below is the in-season
ratio result. `rho` is the assumed correlation between candidate estimates;
the panel identifies the marginal null distribution but **does not identify
cross-candidate correlation**.

| Looks k | Mean best “improvement”, rho=0 | Any false accept rho=0 | rho=0.5 | rho=0.9 |
| ---: | ---: | ---: | ---: | ---: |
| 5 | `0.001093` | **23.1%** | 15.5% | 8.1% |
| 10 | `0.001617` | **39.0%** | 25.7% | 10.1% |
| 20 | `0.002201` | **64.2%** | 40.8% | 12.9% |
| 50 | `0.003008` | **92.2%** | 65.7% | 18.2% |

The defect generalises. At k=10 and independent candidate noise, the mean
best null improvement is `0.020520` out-of-season ratio points (3.78% of that
gap), `0.007928` tail SSE (1.85% of the tail gap), and `0.0009086` primary
Brier (5.07% of the primary gap). The primary window's entire plausible small
step can be manufactured by selection before a test even crosses its own
threshold.

### Costs of the four priced protocols

1. **25/25 date split.** Dates were split deterministically and
   stratum-balanced before scoring: in-season 12/11, out-of-season 13/14, 25
   dates per global fold. The two half-panel MDEs are:

   | Endpoint | Fold 0 MDE | Fold 1 MDE | Worse-fold gap share |
   | --- | ---: | ---: | ---: |
   | In-season ratio | `0.003831` | `0.006688` | **1.5801%** |
   | Out-of-season ratio | `0.051548` | `0.052304` | **9.6459%** |
   | Tail SSE | `0.014029` | `0.024086` | **5.6064%** |
   | 09:00–14:00 Brier | `0.002335` | `0.002139` | **13.0397%** |

   The tail survives, but the split can confirm only one selected campaign
   winner before its confirmation half is consumed. The asymmetry also shows
   why `sqrt(2)` is not an adequate price for this cluster structure.

2. **Campaign alpha ledger — selected protocol.** Equal Bonferroni spending of
   family alpha `0.05` over 20 pre-registered decisions uses `alpha=0.0025`
   each. It preserves the full panel and multiplies every MDE by **1.3796**:

   | Endpoint | 20-decision MDE | Gap share |
   | --- | ---: | ---: |
   | In-season ratio | `0.004215` | **0.9958%** |
   | Out-of-season ratio | `0.052052` | **9.5993%** |
   | Tail SSE | `0.020937` | **4.8734%** |
   | 09:00–14:00 Brier | `0.002314` | **12.9265%** |

   This is the protocol the next campaign should actually follow. It is finite,
   mechanically auditable, and keeps the tail endpoint useful.

3. **Pre-registration alone.** MDE cost is zero, but multiplicity cost is not.
   Pre-registration stops target-aware design changes; it does not make the
   best of k honest tests unbiased or keep family false acceptance at 5%.
   Pre-registration is required inside the alpha-ledger protocol, not a
   substitute for it.

4. **Post-boundary confirmation.** This is the only true holdout, and its cost
   is calendar time plus the fixed-market MDE floor in P2. It should confirm a
   batched material step, not be represented as capable of validating every
   tiny increment separately.

After decision 20, stop. Do not silently start a 21st look. Either declare a
new operator-approved campaign budget against a newly frozen panel or wait for
post-boundary evidence. An accepted change may be shipped under the operator's
“better model” standard, but its evidence label remains provisional until the
post-boundary rule above can decide it.

## P2 — when a real confirmation panel exists

Planning assumptions are exactly the handoff's: D=5 on `2026-08-09`, net one
new settled target date per day, and the armed `08-05` through `08-08`
backfills make D=9 on `2026-08-13`. The design resamples the sealed
out-of-season paired cluster surface to hypothetical D while keeping all 12
market clusters and the crossed treatment. It never opens a post-boundary row.

| D | Calendar date | 80% MDE | Out-of-season gap share |
| ---: | --- | ---: | ---: |
| 5 | 2026-08-09 | `0.081657` ratio | **15.0591%** |
| 9 | 2026-08-13 | `0.061657` | **11.3706%** |
| 15 | 2026-08-19 | `0.048939` | **9.0254%** |
| 27 | 2026-08-31 | `0.038207` | **7.0461%** |
| 30 | 2026-09-03 | `0.036569` | **6.7441%** |
| 60 | 2026-10-03 | `0.028834` | **5.3176%** |
| 90 | 2026-11-02 | `0.025525` | **4.7073%** |
| 365 | 2027-08-04 | `0.019654` | **3.6245%** |
| asymptotic 12-market floor | — | about **`0.0173`** | about **3.2%** |

The variance-curve fit has maximum relative error 1.63% on the declared grid.
The two decision boundaries were therefore checked directly with 60,000
crossed draws each:

- D=28: `0.0378418` > the `0.0377305` target; D=29:
  `0.0371551` ≤ target. **Date: 2026-09-02.**
- D=72: `0.0271514` > the 5%-gap target `0.0271122`; D=73:
  `0.0269999` ≤ target. **Date: 2026-10-16.**
- D=100,000 still gives `0.0173087`, above a 2.5%-gap target
  `0.0135561`. More dates cannot clear the 12-market floor under the binding
  crossed design.

`-09-56a`'s gap decomposition is deliberately not copied, fitted, or guessed
here. The nearby **15.228% served-loss reliability share is the wrong estimand**
and cannot be substituted for the pending gap decomposition. Once `-09-56a`
returns an effect size, apply it to the conditional curve above. If it implies
a 5% out-of-season gap closure, the honest date is October 16. If it implies
2.5% or less, this 12-market confirmation design cannot certify it at any D.

## Falsification outcomes

- **Tail MDE small — FALSIFIED THE BLINDNESS PREMISE.** The panel can referee
  the loss-bearing tail at 3.53% of its remaining gap, or 4.87% under the
  selected 20-decision alpha ledger.
- **Many decisions with negligible inflation — FALSIFIED.** Ten unadjusted
  independent looks raise false acceptance to 39%; 50 raise it to 92%.
- **`-09-44a` positive control fails — DID NOT OCCUR.** Expected
  `0.003055116056564756`; reproduced `0.003055116056564762`, absolute difference
  `6.1e-18`.

## Evidence and independent verification

Ignored workstation evidence root:
`C:\Users\Michael\Documents\github\weather\scratch\w\panel-certify-09-57a\scratch\runs\panel-operating-characteristics-2026-09-57a`.
It is local research evidence, not a production path.

| Evidence | SHA-256 |
| --- | --- |
| Analysis script | `0764b44bd3cda7acc2faacf247597b059b004336cbdbae5d582545d67f14e958` |
| Independent verifier | `c8c5b05bc986b7ef9f910bd8eadd87c1cf64c78af28d0f5108ef6bb37fe166b0` |
| Analysis JSON | `05b4868f427d93e57ac68a0278f84daf7617f47ce337757fb218b1a4a2162382` |
| Saved endpoint draws | `94d5695233bfe66ba1a2546edce0f7722d55bb51e436ad6d093b09c73adc85a5` |
| Selection simulation | `d8f708f53a864442111eef9743d6b5826e6044a59aba9b8b38b7002f81d773f1` |
| Direct confirmation checks | `5a6c6e219248c1711efb58c08012917ce9635257f849d4f287fec19f810794f4` |
| Evidence manifest | `a8309a16581f1ee48444346cf34823404b1d8cb81708071af68cf225e9bf43de` |
| Verification receipt | `2effdd975ee5e9b993ec080ce3b67b5b20efcb6fae103cf277ac8866e0c2ebff` |

The independent verifier returned `PASS`. It rechecked the retained input hash
and D/M/MD/row support; all four endpoint SEs, MDEs, intervals and parity
fractions from saved draws; the exact positive control; current-surface tail
membership; fold and alpha-budget consistency; one-look alpha calibration and
monotone selection inflation; the direct D=28/29 and D=72/73 boundaries; the
market floor; and every evidence-manifest receipt.

Exact workstation reproduction commands:

```powershell
$repo = 'C:\Users\Michael\Documents\github\weather\scratch\w\panel-certify-09-57a'
$python = 'C:\Users\Michael\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
$paired = 'C:\Users\Michael\Documents\github\weather\scratch\runs\gap-remeasure-repaired-2026-09-44a\paired-band-rows.csv'
$run = Join-Path $repo 'scratch\runs\panel-operating-characteristics-2026-09-57a'
Set-Location $repo

& $python "$run\analyze_panel.py" --paired-rows $paired --output-dir "$run\output"
& $python "$run\verify_panel.py" --paired-rows $paired --evidence-dir "$run\output"
```

The repository project venv is currently unusable on this workstation because
its `pyvenv.cfg` names a removed Python 3.11 installation. The bundled offline
Python 3.12 runtime above was used; NumPy 2.3.5 and pandas 3.0.1 were already
present. Nothing was installed and the project venv was not changed.

## Roll verdict

Mechanical branch verdict: **TO BE BOUND AFTER THE REPORT-CONTENT COMMIT**.

Per-file result:

| File | Snapshot | CLOB | Observation-trigger | CLOB-enrichment | Verdict |
| --- | --- | --- | --- | --- | --- |
| `docs/roadmap/agent-report-2026-08-19-workstation-panel-operating-characteristics.md` | pending mechanical result | pending | pending | pending | pending |

## Explicitly not done

- No `-09-56a` estimand, output, file, or concurrent worktree was duplicated or
  used.
- No model, mapping, diagnostic fit, candidate, calibration, artifact, release,
  confirmation reservation, promotion, or serving pointer was created or
  changed.
- No post-boundary row was read. Nothing was pooled across `2026-07-31`.
- No provider, exchange, collector, chain, settlement, scheduled task, loop,
  supervisor, production `data/`, workstation mirror, release store, credential,
  order, or trading mode was called, written, registered, restarted, or enabled.
- No observed-high floor, probability mass, admission rule, promotion gate, or
  evidence contract was weakened.
- No PR, merge, master update, branch deletion, or production adoption occurred.

## Production-host acceptance commands

The raw evidence is intentionally workstation-local and is not represented as
a production path. These commands use paths that exist on production to verify
the committed handback, exact branch scope, documentation audit, and mechanical
roll classification:

```powershell
$repo = 'C:\Users\micha\Desktop\github\weather'
Set-Location $repo
git fetch origin
$branch = 'origin/codex/workstation-what-can-this-panel-certify-2026-09-57a'
$report = 'docs/roadmap/agent-report-2026-08-19-workstation-panel-operating-characteristics.md'

git rev-parse $branch
git show "${branch}:$report"
git diff --name-status origin/master...$branch
git diff --check origin/master...$branch
.\venv\Scripts\python.exe -m weather.operations.agent_docs_audit
powershell.exe -NoProfile -ExecutionPolicy Bypass -File `
  .\scripts\ops\roll_verdict.ps1 -Branch $branch
```

Branch:
`codex/workstation-what-can-this-panel-certify-2026-09-57a`.

Report-content commit: **TO BE BOUND AFTER COMMIT**.
