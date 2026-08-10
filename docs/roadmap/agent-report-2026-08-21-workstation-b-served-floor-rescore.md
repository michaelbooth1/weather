# Workstation report 2026-09-66a — B served-floor diagnostic re-score

## Verdict

**THE SERVED FLOOR MAKES THE B INCUMBENT LOOK SLIGHTLY BETTER, BUT THE EFFECT ON THE GAP IS
COSMETIC.** B incumbent Brier moves from `0.053379789` to **`0.053290041`** against the unchanged
market `0.037505658`. The gap moves from `0.015874131` to **`0.015784384`**: signed change
**`-0.000089748`**, a **0.5654% reduction**. Fully **99.4346% of the old B gap remains**.

The wrong replay floor therefore did not materially handicap B's incumbent score. **The B screens
stand as run.** This does not reopen or reverse any decision. In particular, `-09-63a`'s Gate 3
stop still fires: realized-band zeros fall from 28 to **3**, and all three are survivors from the
original 28. Decision 10 remains **CLOSED UNUSED**.

The floor changes probability at all in **560 / 4,636 B snapshot rows (12.0794%)**, spanning
**5,127 / 50,996 band cells (10.0537%)**. That is the previously uncounted mass-shift surface; it is
far larger than the 25 realized zeros removed even though its net Brier effect is small.

## Requested readouts

| B readout | Current replay floor | Served floor | Signed change |
| --- | ---: | ---: | ---: |
| Incumbent Brier | `0.053379788858189` | **`0.053290041051752`** | **`-0.000089747806437`** |
| Market Brier | `0.037505657502549` | `0.037505657502549` | `0` |
| Incumbent-minus-market gap | `0.015874131355640` | **`0.015784383549203`** | **`-0.000089747806437`** |
| Realized-band zeros | `28` | **`3`** | `-25` |

Exactly **3 / 28** original zeros survive; there are no new served-floor realized-band zeros.
The direction is plain: **the served floor makes the incumbent look better**, by too little to
change the B screening conclusions.

## C control — exact identity

C was re-scored first with the identical intervention. It returned **byte-identical** against its
untouched baseline under big-endian IEEE-754 binary64 comparison:

| C control | Result |
| --- | ---: |
| Snapshot books changed | **0 / 7,653** |
| Band cells changed | **0 / 84,183** |
| Incumbent Brier | `0.060112820227262` before and after |
| Market Brier | `0.038977498485442` before and after |
| Gap | `0.021135321741820` before and after |
| Realized-band zeros | `1` before and after |

I read C **only for this control re-score**. There was no candidate, fitted parameter, accept rule,
endpoint selection, or alpha allocation. `G = 0.021135322`, sections 1c–1g, and all seven spent
decisions were not reopened.

## Pinned method and support

The harness verifies every source/input hash before running, loads the exact captured replay record
for every panel snapshot by canonical record hash, and compiles the pinned
`DistributionMixin._estimate_distribution_result` in memory with one AST replacement. A supplied
non-empty `served_floor_bucket` replaces the method's local `hard_floor_bucket`; when production's
handoff has no served floor for a row, the original assignment is retained rather than inventing a
`None` floor. Every other AST node is unchanged. No repository model, replay, floor, calibration,
or scoring module is edited.

The removed 3.11 venv cannot run, and the bundled Python 3.12 runtime does not contain sklearn.
Nothing was installed. The harness loads only the frozen sklearn tree state and evaluates those
numeric trees with NumPy. Its untouched positive-control surface reproduces the retained incumbent
to maximum absolute band-probability error **`1.4989e-15` in B** and **`5.5512e-16` in C**; every
baseline and intervened route is HGB in all 12 markets. The paired delta is applied to the exact
retained Brier reference so portable-runtime rounding cannot become a reported floor effect.

| Stratum | Dates | Markets | Market-days | Snapshots | Band rows |
| --- | ---: | ---: | ---: | ---: | ---: |
| **B** | **23** | **12** | **204** | **4,636** | **50,996** |
| **C control** | **27** | **12** | **320** | **7,653** | **84,183** |

B and C are evaluated separately. Nothing is pooled across the `2026-07-31` provenance boundary.
This is an exact deterministic paired census, not a statistical endpoint or accept/reject test, so
no uncertainty interval, observed-effect power, or MDE applies. It spends and allocates **no alpha**:
the campaign remains **7 of 20 spent, 13 available**, and decision 10 remains **CLOSED UNUSED**.

## Evidence and independent verification

The supplied served-floor seed was verified before use: 744,043 bytes, 12,289 data rows, SHA-256
`4f9da7539a2dcae5b0b2e2a425499f992ef46812a1abd76b82a1242a3e9effbe`.

| Evidence | SHA-256 |
| --- | --- |
| Retained paired band panel | `4352e77692893c3ac36add9653eabfe0d014de7a02bf083ec6c10e2944dc4e88` |
| Retained repaired band identity | `9a70ac80143a7eea9b14003b2f992413d622b167ce35ea4be54273cfdf3e27ae` |
| Retained measurement manifest | `cf21b67e3236395da800176c27e5c3a571a838e8cc28a491ec48e23e497e7c3e` |
| Committed harness | `8becea6b1d57c81d9ed6295fd4016c7ea8d1a4a2f40caa178c1b5e49ff7c4ee5` |
| Committed seed | `58f28de3dab66398be44e7c72e879f9c1ac6d5d6d6a4341eade4c72cfc0a833c` |
| Ignored summary JSON | `43a33a94273ca067cf79dd45666c74e314d381c9eeef1a3190854376de68594b` |
| Ignored 135,179-band re-score | `833ddb80c9ebb1f87161d8380ac12a746bc60a55af3527566d82c768cbd05f39` |
| Ignored 12,289-snapshot re-score | `859651b4e50393e5d756cc8acb9e78ede70ba5ffd120ce0a34e5e9afa6095789` |

Two complete runs in separate ignored directories reproduced both re-score CSV hashes byte for
byte and reproduced every requested readout. An independent PowerShell `Import-Csv` pass recomputed
B/C support, changed rows, zero survival, and all three Brier surfaces from the emitted cells.

Runtime: bundled Codex Python `3.12.13`, NumPy `2.3.5`, pandas `3.0.1`. No package was installed and
no provider, exchange, or other network endpoint was called.

## Reproduction

On the workstation holding the retained ignored `-09-44a` evidence and captured replay records:

```powershell
$repo = 'C:\Users\Michael\Documents\github\weather'
Set-Location $repo
$python = 'C:\Users\Michael\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
$out = '.\scratch\runs\served-floor-rescore-reproduction-2026-09-66a'

Get-FileHash -Algorithm SHA256 `
  .\docs\roadmap\served-floor-for-panel-2026-09-66a.csv
& $python .\tools\research\rescore_served_floor_09_66a.py --output-dir $out
Get-FileHash -Algorithm SHA256 `
  "$out\rescored-band-rows.csv", `
  "$out\rescored-snapshot-rows.csv"
```

Expected exit is `0`, C changes are `0 / 7,653` snapshots and `0 / 84,183` bands, and the two
output hashes are the last two rows of the evidence table.

Production-host acceptance uses committed paths only; ignored workstation evidence is not claimed
to exist there:

```powershell
$repo = 'C:\Users\micha\Desktop\github\weather'
Set-Location $repo
git fetch origin
$branch = 'origin/codex/workstation-rescore-b-on-the-served-floor-2026-09-66a'
$report = 'docs/roadmap/agent-report-2026-08-21-workstation-b-served-floor-rescore.md'

git rev-parse $branch
git show "${branch}:$report"
git show "${branch}:tools/research/rescore_served_floor_09_66a.py"
git show "${branch}:tools/research/rescore_served_floor_09_66a_seed.json"
git diff --name-status origin/master...$branch
git diff --check origin/master...$branch
.\venv\Scripts\python.exe -m weather.operations.agent_docs_audit
powershell.exe -NoProfile -ExecutionPolicy Bypass -File `
  .\scripts\ops\roll_verdict.ps1 -Branch $branch
```

## Roll verdict and branch

The authoritative repository command will be bound after the mission commit. The mission changes
only the three roll-free paths below; none is in the snapshot, CLOB, observation-trigger, or dormant
CLOB-enrichment retained closure.

| Changed file | Snapshot | CLOB | Observation-trigger | CLOB-enrichment | Verdict |
| --- | --- | --- | --- | --- | --- |
| `tools/research/rescore_served_floor_09_66a.py` | none | none | none | none | Roll-free one-off research tool |
| `tools/research/rescore_served_floor_09_66a_seed.json` | none | none | none | none | Roll-free research seed |
| `docs/roadmap/agent-report-2026-08-21-workstation-b-served-floor-rescore.md` | none | none | none | none | Roll-free Markdown |

Base: `292037ab81d4ac1d162ffa01f6e8ff39cdee8252` (`origin/master`).

Branch: `codex/workstation-rescore-b-on-the-served-floor-2026-09-66a`.

## Explicitly not done

- No candidate, fitted parameter, accept rule, alpha allocation, promotion, re-decision, release,
  pointer, activation, order, or trade was produced.
- No replay, floor, model, calibration, scoring, serving, or production source was changed. The
  serving floor was not weakened.
- No production `data/`, mirror, ledger, tape, artifact, scheduled task, collector, supervisor, or
  process was written, registered, started, restarted, or mutated.
- No PR, merge, master update, production checkout change, or branch deletion was performed.
