# Agent report - 2026-07-30 workstation floor fix

Status: **INPUT-CONTRACT FIX COMPLETE FOR CAPTURED WU ROW PAYLOADS.
TORONTO AND THE ACCEPTED F-FAMILY POST CORPUS CONTAIN NO CAPTURED WU
ROWS, SO THE SANCTIONED FIX HAS ZERO RETROSPECTIVE EFFECT AND DOES NOT
CLOSE ATLANTA'S PROMOTION GAP.**

This report executes
`docs/roadmap/workstation-handoff-2026-07-31b-fix-the-floor-and-check-toronto.md`
from exact `origin/master`
`099072280a7c66156d898a759c8d5a8163d655ca` on topic branch
`codex/workstation-fix-floor-toronto-2026-07-31b`. The branch was pushed
before investigation began.

## Toronto verdict and blank-field mechanism

Toronto is **not clean**, but the defect is not a Celsius/native-unit
mismatch. It emits probability below the stored feature or public-station
high. It has no WU-authoritative floor in this POST slice, so that diagnostic
mass cannot honestly be called mass below the settlement-proxy floor.

The exact July 2-10 POST population contains 1,215 snapshots and 13,365 band
rows:

| Diagnostic floor | Eligible | Violating | Violation rate | Cumulative mass below | Mean mass per eligible |
| :--- | ---: | ---: | ---: | ---: | ---: |
| Stored `feature_vector.high_so_far` | 1,213 | 591 | 48.7222% | 37.511147 | 0.030924 |
| ECCC/station support high | 1,213 | 613 | 50.5359% | 38.288150 | 0.031565 |
| `high_so_far`, hours 18-23 | 284 | 241 | 84.8592% | 16.817434 | 0.059216 |

The 18-23 violation rate is therefore **84.86%, not 100%**, and Toronto
violations are not confined to that late group. The two early snapshots with
no stored feature/support high remain excluded from these diagnostics.

The blank-field mechanism is exact:

1. `SnapshotStore.source_values` writes the legacy-named
   `wu_history_high_c` audit field from `row_max_native(history)`.
2. All 1,215 captured Toronto WU source envelopes are
   `ok = false`, `error = paid_provider_disabled`, `data = {}`.
3. Consequently, there is neither a top-level maximum nor a row from which
   to derive one. All 1,215 `snapshots_long.csv:wu_history_high_c` values are
   blank.

The `_c` suffix is a legacy column name; platform-era values are native-unit.
The same empty source state occurs in F and C captures. The blank is caused
by the configured paid-provider-disabled source, not unit conversion or
F-only presentation.

`feature_vector.high_so_far` is not evidence to the contrary. Feature
extraction rescues a missing WU high from `wu_current` or station
`max_since_7am`. The captured records label the relevant current maximum
`support_only`; promoting that station-rescued value to the WU hard floor
would change the source-authority contract.

## Input-contract fix

The model now has one shared WU-high extractor:

- filter WU rows to the target date;
- retain only parsed rows at or before the effective serving cutoff;
- derive the native-unit maximum from that row population;
- retain the existing top-level native maximum as a compatibility fallback
  only for legacy summary-only payloads;
- return `None` when neither rows nor a summary exist.

The distribution path now computes `history_max` through that helper before
the sanctioned hard-floor stages. Feature extraction and bucket-transition
logic use the same helper, eliminating three competing interpretations of the
WU observed high. No post-hoc projection was added.

The regression test was run red before implementation:

```text
pytest -q tests/model/test_estimate_distribution.py \
  -k "cutoff_aligned or missing_wu_rows"
2 failed, 1 passed
```

Both row-derived floor cases failed because `observed_floor_bucket` was
`None`. After implementation, the same command passed all three tests.

The tests cover:

- Celsius WU rows with no top-level summary: a 26 C cutoff-aligned row makes
  served probability for `<=25` exactly zero;
- Fahrenheit WU rows with no top-level summary: a 91 F cutoff-aligned row
  makes served probability for `<=90` exactly zero;
- a later 15:00 row is excluded at a 14:00 cutoff in both unit families;
- an empty WU row population with no summary leaves both
  `observed_floor_bucket` and `wu_history_floor_bucket` as `None`;
- existing legacy summary-only WU payload behavior remains intact.

## Required correction to the 11,600 / 61 premise

The accepted F-family POST population has 11,661 snapshots and 128,271 band
rows across eleven markets. Exact scans of every bound `replay_inputs.jsonl`
record found **zero captured WU rows**:

| Captured source state | Snapshots |
| :--- | ---: |
| WU null; stored feature high numeric via station/current rescue | 11,600 |
| WU null; stored feature high null | 61 |
| WU-authoritative high present | 0 |

Thus 11,600 is the count with a stored `high_so_far`, not the count with a
reconstructible WU floor. Under the repository's configured source hierarchy,
all 11,661 snapshots are WU-floorless. The requested 61 are only
feature-floorless.

This matters to the fix: treating the 11,600 station-rescued values as WU
hard floors would be the unsanctioned source-contract expansion that this
mission forbids. The implementation instead leaves every genuinely empty WU
input floorless, including the 61, and fixes the row-only WU payload shape
when authoritative rows actually exist.

## Frozen POST Brier effect

Because every frozen captured WU source is disabled/empty, the old
top-level extractor and the fixed cutoff-aligned row extractor both return
`None` on every accepted record. The code branch changed by this mission is
therefore unexercised by the frozen population, and before/after probability
vectors are identical by exact input-contract differential.

| Local-hour group | Rows | Snapshots | Current before = after | Post-blend before = after | Pre-blend before = after |
| :--- | ---: | ---: | ---: | ---: | ---: |
| 00-02 | 16,907 | 1,537 | 0.077246578 | 0.072092696 | 0.071933877 |
| 03-08 | 34,166 | 3,106 | 0.076604338 | 0.072826003 | 0.075693875 |
| 09-14 | 30,371 | 2,761 | 0.070734649 | 0.064962562 | 0.066917399 |
| 15-17 | 15,224 | 1,384 | 0.049772406 | 0.024391796 | 0.017105607 |
| 18-23 | 31,603 | 2,873 | 0.042444868 | 0.010845760 | 0.000205136 |
| **Overall** | **128,271** | **11,661** | **0.063698529** | **0.049848537** | **0.047567961** |

Every after-minus-before delta is exactly `0.0`. This is not a post-hoc
projection result. The frozen old post-blend was independently reconstructed
through canonical `blend_with_current` plus existing mass restoration; its
maximum absolute difference from stored `probability` was
`2.7596813723107516e-12`, below the predeclared `1e-10` tolerance. Maximum
simplex error across all lanes was below `7.8e-16`.

## Atlanta and the remaining `0.001357`

Atlanta contains 948 snapshots, 10,428 band rows, and seven settled days.
Before and after are identical:

| Lane / weighting | Candidate Brier | Market Brier | Delta versus market | Distance beyond `market + 0.003` |
| :--- | ---: | ---: | ---: | ---: |
| Post-blend, daily-first | 0.049159572 | 0.032483947 | 0.016675625 | 0.013675625 |
| Post-blend, row-weighted | 0.050799658 | 0.035166853 | 0.015632805 | n/a |
| Pre-blend, daily-first | 0.036841072 | 0.032483947 | 0.004357125 | **0.001357125** |
| Pre-blend, row-weighted | 0.041170031 | 0.035166853 | 0.006003178 | n/a |

The input-contract fix does **not** close the `0.001357`; neither Atlanta lane
passes the daily-first market-tolerance gate.

## Point-in-time and source-authority attestation

The implemented contract admits only target-date WU rows whose parsed minute
is at or before `effective_cutoff_hour * 60`. The C and F regression fixtures
both contain a hotter post-cutoff row and prove that it does not set the
floor. On the frozen measurement:

| Check | Result |
| :--- | :--- |
| Captured WU rows | 0 |
| Selected WU rows | 0 |
| Future or unparseable selected rows | 0 |
| Future information used | **false** |
| Input hashes unchanged before/after | **true** |

There is no measured lift to suspect of leakage. No settlement label,
post-cutoff observation, post-hoc floor projection, station-rescued value, or
future row informs the fixed WU floor.

## Verification

| Check | Result |
| :--- | :--- |
| Red regression | 2 failed, 1 passed before implementation |
| Green regression | 3 passed after implementation |
| Focused model boundary | 122 passed |
| Legacy summary-only calibration compatibility | 22 passed |
| Full repository suite | 3,218 passed, 27 unrelated failures, 4 skipped, 820 subtests passed |
| `compileall -q app src tests` | pass |
| `weather.operations.agent_docs_audit` | pass: 18 agent files, 529 Markdown files |
| `git diff --check` | pass |

No model or calibration test failed in the full run. Its 27 failures are in
unmodified collection, operations, and reporting code and are specific to the
host verification environment: Windows receipt-stat identity, sandbox/process
containment, disabled PowerShell script execution, and one peak-memory
threshold. The docs-audit test also saw the temporary verification
environment while the full suite was active; the required direct audit passed
after that temporary tree was removed.

The repository's checked-in `venv` points to a removed Python 3.11 runtime.
Verification used an untracked task-local virtual environment with the
repository's pinned dependencies; it is not part of the handback.

## Evidence and operational boundary

The declared read-only research root is:

`scratch/agent-runs/workstation-floor-fix-2026-07-31b`

| Evidence | SHA-256 |
| :--- | :--- |
| `predeclaration.md` | `0fcc51afd1a367a631cd7886c63c6485d4197bf4a623dff26f363e2713cd19d9` |
| `analyze_toronto_floor.py` | `f719354c374b732d510c4bb2a275c762a5b7af1ffdef6031da966696ba365f8b` |
| `toronto_production_floor_post.json` | `8abb75c452152f5cc55016ded0809603e30facc9c57c0fd3126411afaee3c800` |
| `replay_fixed_floor.py` | `b50eefadfc3cef586a69d6f9331f007bd013ce0b9006e04dbdb71993e0ccf274` |
| `fixed_floor_replay_post.json` | `dec95e7f5535f8d287e53965a9aafc07a7e461625a5436618f5c824dcfd11755` |
| `fixed_floor_candidate_rows_post.csv` | `7856f93a49f1a676492c6cd462f610a6af74d37dfc4bf81b2a0b1970d79292fb` |

The Toronto and F-family input hashes were identical before and after their
respective scans. `data/` was not written. There were no live vendor,
order-book, serving, scheduler, capture, ACL, mirror-topology, release,
pointer, promotion, merge, or master changes. The loop-loaded
`model_distribution.py` change has not been adopted by any runtime.

No checked `mirror_status.json` exists at either expected host location or
repository-local candidate path. The evidence covers frozen July 2-10 POST
records and cannot certify mirror freshness for the most recent approximately
36 hours.

## Recommendation

Merge the code change only when the operator is ready for the roll-sensitive
model reload. It fixes the real row-only WU input contract in both unit
families and preserves summary-only compatibility, but it does not repair the
current capture reality: the configured WU source is disabled and supplies no
rows.

Do not promote station or METAR highs into the WU settlement-proxy hard floor
under the existing contract. If a free/public authoritative observed-high
source is desired, define that source hierarchy explicitly, preserve captured
point-in-time evidence, and validate or retrain against the new contract.
Only after that capture contract is settled would a C-family candidate run be
informative; recommend one then, but do not start it from this handback.
