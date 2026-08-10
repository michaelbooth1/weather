# Workstation report 2026-09-68a — Gate 3 satisfiability

## Verdict

**GATE 3 IS A PANEL-SIZE LIMIT, NOT A QUALITY BAR, AT THE OBSERVED SERVED-FLOOR ERROR RATE.** The
third reported B zero is exactly the predicted fallback row: NYC `2026-06-22`, snapshot
`20260622T000103-0400`, has a **blank** `served_floor_bucket`. Production applied no floor there;
the `-09-66a` diagnostic retained the replay floor because no replacement existed. The only two B
zeros attributable to the floor actually served are Chicago `2026-06-14` (floor `70`, settled
`69`) and San Francisco `2026-06-09` (floor `68`, settled `67`).

Those two crossings occur on **2 / 204 B market-days = 0.980392%**, crossed 95%
**`[0.000000%, 4.035874%]`**. Under the requested independent-market-day plug-in projection,
Gate 3 fires with probability **62.6647% at 100 market-days**, **99.2746% at 500**, and
**86.5994% on the observed 204-market-day B panel**. The first panel size strictly above 50% is
**71 market-days**; the first strictly above 95% is **305**.

An unchanged Gate 3 therefore becomes more likely to reject as evidence accumulates, regardless of
candidate quality. **No future re-registration should reuse it unchanged.** That is a prospective
design conclusion in prose only: the frozen protocol was not amended or reinterpreted, the serving
floor was not weakened, and no epsilon mass was added. Decision 10 remains **RETIRED and not
reassigned**. This mission spends and allocates **no alpha**; the campaign stays **7 of 20 spent,
13 available**.

## Reconciliation — all three B zeros

| Market | Target date | Snapshot | Served floor | Settled high | Disposition |
| --- | --- | --- | ---: | ---: | --- |
| san-francisco | `2026-06-09` | `20260609T170137-0400` | `68` | `67` | **Real served-floor crossing** |
| chicago | `2026-06-14` | `20260614T011002-0400` | `70` | `69` | **Real served-floor crossing** |
| nyc | `2026-06-22` | `20260622T000103-0400` | **blank** | `73` | **Fallback row; no served floor existed** |

The deduction in the handoff is correct. For every snapshot with a nonblank floor, the retained
`served_floor_realized_zero` flag is exactly equivalent to
`served_floor_bucket > settlement_high`. The NYC row is the sole blank-floor B zero and is not a
zero the production floor could have created.

The retained Denver production book also confirms the handoff's positive control. Denver
`2026-06-08`, snapshot `20260608T030552-0400`, assigns
**`0.5206313021403224`** to the realized `82–83°F` band. Its 11 bands sum to exactly `1.0`; the
served floor is `68`, the settled high is `82`, and that floor does not touch the realized band.

## Snapshot and market-day rates

The handoff's requested `2 / 10,936` denominator is the count of **all panel snapshots with a
nonblank served floor**, B and C together. I reproduce it exactly. For denominator clarity, the
strict within-stratum rates are also reported; they are not substituted for the requested number.

| Snapshot readout | Crossings / denominator | Rate |
| --- | ---: | ---: |
| Requested B crossings / all panel snapshots with a served floor | **2 / 10,936** | **0.018288%** |
| B crossings / B snapshots with a served floor | 2 / 3,885 | 0.051480% |
| C crossings / C snapshots with a served floor — contrast only | **1 / 7,051** | **0.014182%** |
| C crossings / all panel snapshots with a served floor — direct denominator contrast | 1 / 10,936 | 0.009144% |

| Stratum | Dates | Markets | Market-days | Crossed market-days | Rate | Crossed 95% interval |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| **B** | 23 | 12 | 204 | **2** | **0.980392%** | **[0.000000%, 4.035874%]** |
| **C, contrast only** | 27 | 12 | 320 | **1** | **0.312500%** | **[0.000000%, 1.875000%]** |

Intervals are 10,000-draw crossed target-date × market pigeonhole percentile intervals, with B
and C resampled separately (seeds `20260968` and `20260969`). The lower endpoints are zero because
the event is sparse: 3,403 B draws and 5,957 C draws contain no crossed cell. The point-rate panel
projection below is the requested arithmetic conditional on the observed B rate; it does not
propagate this sampling interval and is not a confidence interval for a future panel.

I read C **only for the requested contrast rate**. There is no candidate, fitted parameter, accept
rule, or C endpoint. B and C remain separate for inference, and no row on or after the
`2026-07-31` provenance boundary is used or pooled.

## Expected zeros and probability Gate 3 fires

The projection treats each market-day as an independent Bernoulli trial with the observed B
probability `2 / 204` of containing at least one Gate-3-triggering zero. In the observed panel each
affected market-day contains exactly one such snapshot, so the expected count below is both the
expected number of affected market-days and the expected zero count under that observed
one-zero-per-affected-day pattern. Gate 3 needs only one.

| Panel market-days | Expected B zero market-days | P(no zero) | **P(Gate 3 fires)** |
| ---: | ---: | ---: | ---: |
| 100 | 0.980392 | 37.335348% | **62.664652%** |
| 500 | 4.901961 | 0.725439% | **99.274561%** |
| 1,000 | 9.803922 | 0.005263% | **99.994737%** |
| 5,000 | 49.019608 | `4.03655e-22` | **`1 - 4.03655e-22`** |

For context, the actual B panel has 204 market-days: expected zeros `2.0`, P(no zero)
`13.400630%`, and **P(fires) `86.599370%`** under the same projection.

| Threshold | First panel size strictly above it | Value at prior size | Value at threshold size |
| --- | ---: | ---: | ---: |
| P(fires) > 0.50 | **71** | 49.825374% at 70 | 50.317282% at 71 |
| P(fires) > 0.95 | **305** | 94.996828% at 304 | 95.045879% at 305 |

The current 204-market-day B fit panel is already well beyond the 50% break-even. A 500-market-day
panel is beyond 99%. The frozen zero-anywhere rule therefore penalizes accumulating evidence: at a
fixed nonzero floor-crossing rate, its pass probability converges to zero as panel size grows.

## Sensitivity check — not an exclusion rule

The production `snapshots_long.csv:model_probability` on the realized band before the floor is:

| Market / snapshot | Pre-floor realized-band probability |
| --- | ---: |
| chicago `20260614T011002-0400` | **`0.014627522421623898`** |
| san-francisco `20260609T170137-0400` | **`0.0001434313351627716`** |

B's served-floor incumbent Brier is `0.053290041051752`. Dropping exactly those two snapshots
(22 band rows) gives **`0.053247700407449`**, a signed change of **`-0.000042340644303`**
(`-0.07945%` relative), on 50,974 remaining band rows.

**This is a sensitivity check, not a corrected result.** It licenses no exclusion, relabelling,
floor exception, protocol amendment, or claim that either snapshot should be removed. The
`-09-67a` instrument audit remains closed and was not reopened.

## Method, support, and integrity

The committed standard-library-only harness verifies every input hash and byte size before reading
model output. It joins the 12,289 retained `-09-66a` snapshot rows one-to-one to the tracked served
floor and many-to-one to the 524 tracked `-09-67a` settlement rows. It then verifies:

- exact floor identity between the tracked floor and the retained snapshot re-score;
- `served_floor_realized_zero` iff `served_floor_bucket > settlement_high` for every nonblank floor;
- retained B served-floor Brier `0.053290041051752` from the snapshot-level squared-error sums;
- the three captured production books' hashes, 11-band mass, and named realized-band probabilities.

The C snapshot rows are used only to count the requested floor-crossing contrast. No C Brier,
candidate score, endpoint, or band-level statistic is computed.

| Stratum | Date clusters | Market clusters | Market-days | Snapshots | With served floor | Band rows used |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| B | 23 | 12 | 204 | 4,636 | 3,885 | 50,996 |
| C contrast | 27 | 12 | 320 | 7,653 | 7,051 | **not scored** |
| **Panel** | — | — | 524 | 12,289 | **10,936** | — |

| Evidence | SHA-256 |
| --- | --- |
| Retained `rescored-snapshot-rows.csv` | `859651b4e50393e5d756cc8acb9e78ede70ba5ffd120ce0a34e5e9afa6095789` |
| Tracked served-floor evidence | `4f9da7539a2dcae5b0b2e2a425499f992ef46812a1abd76b82a1242a3e9effbe` |
| Tracked settlement provenance | `73501415ea8dd31db8816c3fb4b5e8db92eb0d5448b8b5f48e7c57b6c44597cd` |
| Chicago / San Francisco / Denver production books | `8a669321…` / `ddb2ae50…` / `126d5232…` |
| Committed harness | `4848b7bab443b2a9a2c27235636273926f4279a415b715d93993f6245eedfa28` |
| Committed seed | `61c01f0ed4b5d62809a53127057c7ac78d102cfbb4bb3f288c2a023143f62ac7` |
| Ignored deterministic summary | `d08ea945deb9683b663a559ac702d665c003169d82f293251ae22c9cfa100d1a` |

Two complete runs into separate ignored output directories reproduced the summary hash byte for
byte. Runtime: bundled Codex Python `3.12.13`; nothing was installed, and no provider, exchange, or
other network endpoint was called.

## Verification

| Check | Result |
| --- | --- |
| Harness against every pinned input | **PASS** |
| Second complete run in a separate output directory | **PASS**, byte-identical summary |
| `python -m weather.operations.agent_docs_audit` | **PASS**, 18 agent files / 773 Markdown files |
| `python -m compileall -q app src tests tools/research/analyze_gate_3_satisfiability_09_68a.py` | **PASS** |
| `tests/operations/test_agent_docs_audit.py` with bundled 3.12 plus the venv's pure-Python pytest | **4 passed** |

The full suite could not collect in this mandated runtime. The bundled Python 3.12 has no pytest;
loading only pytest from the retired venv then exposes that venv's CPython-3.11 binary extensions,
and collection stops with 66 environment errors from incompatible `sklearn`, `scipy`, `pyarrow`,
and `matplotlib` modules. Nothing was installed or changed to mask that incompatibility. The
mission-owned harness is standard-library-only and its direct execution, deterministic replay,
compile check, documentation audit, and focused pure-Python tests all pass.

## Reproduction

On the workstation holding the retained ignored `-09-66a` evidence and snapshot mirror:

```powershell
$repo = 'C:\Users\Michael\Documents\github\weather'
$worktree = "$repo\scratch\w\gate-3-satisfiable-09-68a"
$python = 'C:\Users\Michael\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
$out = "$worktree\scratch\runs\gate-3-satisfiability-reproduction-2026-09-68a"

Set-Location $worktree
& $python .\tools\research\analyze_gate_3_satisfiability_09_68a.py `
  --repo-root $worktree `
  --evidence-root $repo `
  --output-dir $out
Get-FileHash -Algorithm SHA256 "$out\summary.json"
```

Expected exit is `0`, verdict `GATE_3_IS_A_PANEL_SIZE_LIMIT`, B snapshot rate `2 / 10,936`, B
market-day rate `2 / 204`, break-even sizes `71` and `305`, and summary SHA-256
`d08ea945deb9683b663a559ac702d665c003169d82f293251ae22c9cfa100d1a`.

Production-host acceptance uses committed paths only; ignored workstation evidence is not claimed
to exist there:

```powershell
$repo = 'C:\Users\micha\Desktop\github\weather'
Set-Location $repo
git fetch origin
$branch = 'origin/codex/workstation-is-gate-3-satisfiable-2026-09-68a'
$report = 'docs/roadmap/agent-report-2026-08-23-workstation-gate-3-satisfiability.md'

git rev-parse $branch
git show "${branch}:$report"
git show "${branch}:tools/research/analyze_gate_3_satisfiability_09_68a.py"
git show "${branch}:tools/research/gate_3_satisfiability_09_68a_seed.json"
git diff --name-status origin/master...$branch
git diff --check origin/master...$branch
.\venv\Scripts\python.exe -m weather.operations.agent_docs_audit
powershell.exe -NoProfile -ExecutionPolicy Bypass -File `
  .\scripts\ops\roll_verdict.ps1 -Branch $branch
```

## Branch and roll verdict

Base: `6444cc199d2b21bd6ce8b89ea2a7e7b70c70bade` (`origin/master`).

Branch: `codex/workstation-is-gate-3-satisfiable-2026-09-68a`.

Analysis/report commit: `TO_BIND_AFTER_COMMIT`.

The authoritative roll verdict and per-file closure table will be bound after the analysis/report
commit is created.

## Explicitly not done

- No fitting, candidate, beta vector, Gate-1/Gate-2 computation, C endpoint, accept rule, or alpha
  allocation was performed. Decision 10 was not reopened or reassigned.
- No protocol, serving floor, `high_so_far`, collection, settlement, replay, model, calibration,
  scoring, or production source was changed. No epsilon mass was added.
- No production `data/`, mirror, ledger, tape, artifact, scheduled task, collector, supervisor, or
  process was written, registered, started, restarted, or mutated.
- No PR, merge, master update, production checkout change, branch deletion, order, or trade was
  performed.
