# Workstation report 2026-09-64a — repaired realized-band zero audit

## Verdict

**PRECISE NULL: THE BLIND-FEATURE REPAIR ADDS ZERO REALIZED-BAND ZEROS.** In the sealed paired
panel, repaired and control are identical on every realized-band zero: **28 of 4,636 snapshots
(0.603969%) in B** and **1 of 7,653 (0.013067%) in C**. There are **no repair-only snapshots and no
repair-only market-days** in either stratum. Both repaired rates are below the served-side reference
of 1,017 / 100,040 = **1.016593%**, and both repaired and control have **zero** winners in
`(0, 1e-6)`.

The repair therefore inherited this defect from the paired control/replay input; it did not add it.
The campaign's current-surface numbers and all seven spent decisions stand. This is the handoff's
valuable null, not a failed mission. It does not make the affected rows healthy: Denver
`2026-06-08` remains `0.0` in both paired surfaces while production served `0.5206`. It says only
that the blind-feature repair is not the source of that divergence.

This was an audit of the panel's own integrity. There was **no candidate, fitted parameter, endpoint
comparison, or accept rule**. Reading C therefore spent no alpha. Campaign accounting remains
**7 of 20 spent, 13 available**. Decision 10 remains **CLOSED UNUSED**, is not reassigned, and the
correct `-09-63a` Gate 3 stop is not reopened.

## Pinned population and integrity

Input was the retained `paired-band-rows.csv`, SHA-256
`4352e77692893c3ac36add9653eabfe0d014de7a02bf083ec6c10e2944dc4e88`.

| Stratum | Dates | Markets | Market-days | Snapshots | Band rows |
| --- | ---: | ---: | ---: | ---: | ---: |
| **B** | **23** | **12** | **204** | **4,636** | **50,996** |
| **C** | **27** | **12** | **320** | **7,653** | **84,183** |

The audit verified exactly 11 bands and one `outcome == 1` per snapshot, exact expected support,
the squared-error identities, and unit mass on both model surfaces (maximum error below `1e-15`).
Captured market yes prices were not forced to sum to one; their observed book sums range from
`0.2935` to `1.5940`. Every target date is at most `2026-07-30`. B and C are reported and
bootstrapped separately; nothing is pooled across the `2026-07-31` provenance boundary.

## Exact-zero census and empty interval

| Stratum / surface | Exact zero | Rate | Crossed 95% interval | `(0, 1e-6)` | Affected dates / markets / market-days |
| --- | ---: | ---: | ---: | ---: | ---: |
| **B repaired** | **28 / 4,636** | **0.603969%** | [0.235773%, 1.103283%] | **0** | **11 / 10 / 25** |
| B control | 28 / 4,636 | 0.603969% | [0.235773%, 1.103283%] | **0** | 11 / 10 / 25 |
| **C repaired** | **1 / 7,653** | **0.013067%** | [0.000000%, 0.078783%] | **0** | **1 / 1 / 1** |
| C control | 1 / 7,653 | 0.013067% | [0.000000%, 0.078783%] | **0** | 1 / 1 / 1 |

The repaired-minus-control exact-zero rate is exactly `0.0` in both strata, with a degenerate
crossed interval `[0.0, 0.0]`. This is a row-for-row identity, not a low-powered equality claim.

Against the exact served reference rate, repaired B is **0.412624 percentage points lower** and
repaired C is **1.003527 points lower**. The served census and paired panel have different support,
so this comparison is descriptive rather than paired. The handed-over served census did not include
its 20 market-day identities; the exact same-day claim here is against the paired control. On that
common roster, all **25 / 25 B** and **1 / 1 C** repair-affected market-days are already
control-affected, with no repair-only day.

## Market, date, and unit spread

All 29 repaired zeros occur in Fahrenheit markets. Toronto contributes **0 / 443** B snapshots and
**0 / 647** C snapshots. The Fahrenheit rates are **28 / 4,193 = 0.667780%** in B and
**1 / 7,006 = 0.014273%** in C. Control is identical. Unlike the served census's one Toronto case,
the paired panel contains no Celsius realized-band zero.

| B market | Zeros | B market | Zeros |
| --- | ---: | --- | ---: |
| Denver | 7 | Atlanta | 4 |
| Chicago | 3 | NYC | 3 |
| San Francisco | 3 | Seattle | 3 |
| Dallas | 2 | Houston | 1 |
| Los Angeles | 1 | Miami | 1 |
| Austin | 0 | Toronto | 0 |

C contains one zero: Seattle on `2026-07-16`. B's date counts are:

| Date | Zeros | Date | Zeros |
| --- | ---: | --- | ---: |
| 2026-06-08 | 3 | 2026-06-09 | 1 |
| 2026-06-12 | 4 | 2026-06-13 | 4 |
| 2026-06-14 | 4 | 2026-06-15 | 1 |
| 2026-06-16 | 2 | 2026-06-19 | 3 |
| 2026-06-20 | 3 | 2026-06-22 | 1 |
| 2026-06-26 | 2 | — | — |

The retained affected-market-day CSV records all 26 stratum-specific market-days and shows equal
repair/control counts on every row.

## Brier attribution

A realized-band zero contributes squared error exactly `1`. The contribution to the project's
band-row mean Brier is therefore `zero snapshots / band rows`; no approximation is involved.

| Quantity | B | C |
| --- | ---: | ---: |
| Repaired incumbent Brier | `0.053379789` | `0.060112820` |
| Control Brier | `0.053380315` | `0.059483515` |
| Market Brier | `0.037505658` | `0.038977498` |
| Repaired gap vs market | `0.015874131` | **`0.021135322`** |
| Realized-zero SSE | 28 | 1 |
| Realized-zero contribution to mean Brier | `0.000549063` | `0.000011879` |
| Share of total repaired Brier | **1.028597%** | **0.019761%** |
| Contribution as share of reference C gap `G=0.021135322` | **2.597844%** | **0.056204%** |

The current served stratum is C. Its one realized-band zero carries only **0.0562% of G** and
**0.0198% of incumbent Brier**. This is materially negligible for sections 1c–1g. B has more zeros,
but they are all already present in the control; they cannot be attributed to the repair.

## Diagnostic only — exclude complete affected snapshot books

This deliberately changes the estimand. To preserve categorical scoring coherence, the diagnostic
removes the complete 11-band snapshot book whenever repaired probability on its realized band is
exactly zero; it does not remove only the winning row. This sizes an artifact. It is **not a
corrected score, candidate, repair, or proposed operating rule**.

| Stratum | Full gap | Excluded snapshots / band rows | Diagnostic gap | Change [crossed 95%] |
| --- | ---: | ---: | ---: | ---: |
| **B** | `0.015874131` | 28 / 308 | `0.015478521` | `-0.000395611` [`-0.000815424`, `-0.000129118`] |
| **C** | `0.021135322` | 1 / 11 | `0.021132393` | `-0.000002929` [`-0.000016975`, `0.000000000`] |

For B the diagnostic reduction is 2.4922% of B's full gap (1.8718% of reference G). For C it is
only **0.01386% of G**. The incumbent remains behind the market by essentially the full C gap.
Nothing in this table licenses row exclusion from future evaluation.

## Interval treatment and alpha

The exact census is primary. Descriptive intervals use 10,000 crossed target-date × market
pigeonhole draws per stratum, seeds **20260964 for B** and **20260965 for C**, with market-day cell
sums and snapshot/band denominators reweighted together. B and C have independent date resamples
and are never pooled. These intervals describe cluster dispersion; they are not attached to an
accept/reject rule.

No model was fit and no endpoint was selected or compared. Observed-effect power and campaign MDE
are therefore not applicable. This audit spends **no alpha and allocates none**.

## Determinism and evidence hashes

The bundled Codex runtime was Python `3.12.13`, pandas `3.0.1`, and NumPy `2.3.5`. Nothing was
installed and no network endpoint was called. A second complete run reproduced the summary hash
exactly. An independent PowerShell `Import-Csv` pass reproduced the B/C winner counts, zero counts,
empty interval, band counts, and model/market Briers.

| Evidence | SHA-256 |
| --- | --- |
| Input paired panel | `4352e77692893c3ac36add9653eabfe0d014de7a02bf083ec6c10e2944dc4e88` |
| Committed audit script | `0747839df4eff36074ca59e83db78c857c247915c5529f976622e4a665e8c775` |
| Committed seed manifest | `6faec5d5d77299492e0babe4c6685aa4ddfd0fb6de14ce9d606c1167da49586f` |
| Ignored summary JSON | `507c4ddd82eca10bcb8a18c7ce28ae77dda6f81fdd84ca9bebbf38ecc171220c` |
| Ignored crossed draws | `a1bb5bbf3847e701684a17ad4c1583dce2ef1a1734c23b6f7d9cfcae5bacb2f6` |
| Ignored affected market-days | `b68c037c93393aab667e5c46de782fde81fdbfdad5da9d6e341c6a0212798e76` |

Ignored workstation evidence root:
`C:\Users\Michael\Documents\github\weather\scratch\runs\repair-zero-audit-2026-09-64a`.

## Roll verdict

`ROLL_VERDICT_PENDING`

| Changed file | Snapshot | CLOB | Observation-trigger | CLOB-enrichment | Verdict |
| --- | --- | --- | --- | --- | --- |
| `tools/research/audit_repaired_realized_band_zeros_09_64a.py` | none | none | none | none | Roll-free one-off research tool |
| `tools/research/repair_zero_audit_09_64a_seed.json` | none | none | none | none | Roll-free research seed |
| `docs/roadmap/agent-report-2026-08-19-workstation-repair-zero-audit.md` | none | none | none | none | Roll-free Markdown |

## Explicitly not done

- No repair fix was proposed or implemented, and the realized-band loss point was not traced.
- No production `data/`, workstation mirror, settlement ledger, snapshot tape, release store, or
  durable artifact was written. Ignored output was written only under `scratch/runs/`.
- No provider or exchange endpoint was called; no collector, chain, settlement, scheduled task,
  supervisor, or loop was run, registered, or restarted.
- No candidate, fitted parameter, epsilon support repair, release, pointer, promotion, activation,
  serving change, order, or live-trading action occurred.
- No observed-high floor, probability-mass contract, admission rule, promotion gate, or
  `harvest_only` contract was weakened.
- No PR, merge, master update, production checkout change, or branch deletion was performed.

## Reproduction and production-host acceptance

On the workstation holding the retained paired evidence:

```powershell
$repo = 'C:\Users\Michael\Documents\github\weather'
Set-Location $repo
$python = 'C:\Users\Michael\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'

Get-FileHash -Algorithm SHA256 `
  .\scratch\runs\gap-remeasure-repaired-2026-09-44a\paired-band-rows.csv
& $python .\tools\research\audit_repaired_realized_band_zeros_09_64a.py
Get-FileHash -Algorithm SHA256 `
  .\scratch\runs\repair-zero-audit-2026-09-64a\audit-summary.json
```

Expected input and summary hashes are the table above. The raw panel is ignored workstation
evidence and is not claimed to exist on production.

Production-host acceptance uses committed paths only:

```powershell
$repo = 'C:\Users\micha\Desktop\github\weather'
Set-Location $repo
git fetch origin
$branch = 'origin/codex/workstation-does-the-repair-zero-the-winner-2026-09-64a'
$report = 'docs/roadmap/agent-report-2026-08-19-workstation-repair-zero-audit.md'

git rev-parse $branch
git show "${branch}:$report"
git show "${branch}:tools/research/audit_repaired_realized_band_zeros_09_64a.py"
git show "${branch}:tools/research/repair_zero_audit_09_64a_seed.json"
git diff --name-status origin/master...$branch
git diff --check origin/master...$branch
.\venv\Scripts\python.exe -m weather.operations.agent_docs_audit
powershell.exe -NoProfile -ExecutionPolicy Bypass -File `
  .\scripts\ops\roll_verdict.ps1 -Branch $branch
```

Audit implementation and initial report commit: `COMMIT_PENDING`.

Branch: `codex/workstation-does-the-repair-zero-the-winner-2026-09-64a`.
