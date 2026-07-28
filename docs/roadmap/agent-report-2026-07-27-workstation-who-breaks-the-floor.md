# Agent report - 2026-07-27 workstation who breaks the floor

Status: **STOPPED BEFORE MISSION 1 CORPUS ACCESS. THE FINAL FRESH HOST
ADMISSION FAILED AT 47.162247 GiB FREE DISK, BELOW THE FROZEN 50 GiB
MINIMUM. THE EX-ANTE LEAKAGE RESULT IS THEREFORE UNKNOWN, AND MISSIONS 2
AND 3 WERE NOT RUN.**

This report executes
`docs/roadmap/workstation-handoff-2026-07-27g-who-breaks-the-floor.md`
from exact `origin/master`
`7068d50e3c2586048a63cb222a69e2c103f4a779` on topic branch
`codex/workstation-who-breaks-floor-2026-07-27g`.

The gate order, population, tolerances, projection rule, scoring units, and
resource ceilings were frozen before measurement in
`scratch/workstation-research-output/who-breaks-floor-20260727g/predeclaration.md`,
SHA-256
`85d7590fe26d18e38ae621053e31e671af352382b2a64e3e6e82d0c15fce98d9`.

## Mission 1 answer first

**`UNKNOWN_NOT_MEASURED`**.

There is no evidence-backed answer yet to either required leakage question:

- whether `high_so_far` is monotone non-decreasing within every frozen
  market-day; or
- whether raw `high_so_far` and
  `ROUND_HALF_UP(high_so_far)` never exceed the frozen settled maximum.

The reason is operational, not statistical. Initial admission at
19:46:43 America/Toronto passed with 51.864444 GiB free disk. Before the
single declared 8.61 GB replay pass, a public market-making reward-cache
refresh and a sampling inspector became active. The audit waited rather than
overlap them. When all Python and robocopy processes had exited, the final
fresh admission at 20:27:27 reported:

| Gate | Requirement | Observation | Result |
| :--- | :--- | ---: | :--- |
| Commit | `< 70%` | 51% | PASS |
| Available physical memory | `> 8 GiB` | 10.553978 GiB | PASS |
| Free disk | `>= 50 GiB` | **47.162247 GiB** | **FAIL** |
| Python or robocopy processes | none | 0 | PASS |
| Training/restore active | false | false | PASS |
| Mirror/robocopy active | false | false | PASS |
| `data/` deny-write ACL | two effective deny entries | 2 | PASS |

The terminal is
**`FAIL_HOST_ADMISSION_STOP_BEFORE_MISSION1`**. This is not the handoff's
leakage failure terminal and must not be reported as evidence that the floor
is contaminated. It means the leakage gate never obtained authority to read
the corpus.

No operational tape, archive, HAR, ledger, or other evidence was deleted to
manufacture disk headroom.

## Exact non-execution boundary

| Operation | Result |
| :--- | :--- |
| Manifest-pinned replay files opened | **0 / 129** |
| Manifest-pinned replay bytes read | **0 / 8,610,897,941** |
| Candidate vector stat or hash | **not performed** |
| Candidate vector scans | **0** |
| Mission 1 monotonicity/settlement tests | **NOT RUN** |
| Mission 2 localization/attribution | **NOT RUN** |
| Mission 3 projection/scoring | **NOT RUN** |
| Modelling or fitting | **none** |
| Vendor requests | **0** |
| Order-book/full-book reads | **0** |
| Writes below `data/` | **0** |

The 156,464,494-byte candidate vector remained unopened as required by the
Mission 1-first contract. Consequently there are no Brier scores,
decompositions, gap-closure estimates, incumbent concentration results, or
case-level worsening results to report.

Missions 3+ of
`workstation-handoff-2026-07-28c-scale-the-mm-corpus.md` were not touched and
remain restricted to their morning window.

## Prepared gate, not an executed result

The shared repository `venv` launcher is broken because its original Python
installation is unavailable to this session. The already repaired,
task-isolated CPython 3.12.13 environment from the accepted measurable-MM
queue was revalidated with the repository's exact NumPy 2.4.6, pandas 3.0.3,
SciPy 1.17.1, scikit-learn 1.8.0, and joblib 1.5.3 packages. The shared
environment was not modified.

A Mission 1-only harness was prepared and its synthetic self-test passed. It
is not a result artifact. Before any future run it:

- binds the exact 129 native-F market-days, 18,793 snapshot IDs, 124 accepted
  hour-20 joins, fixed manifest inputs, and transitive source modules that
  derive `high_so_far`;
- uses the manifest generator's legacy-compatible replay JSON semantics while
  retaining strict parsing for receipts and manifests;
- verifies every pinned record's canonical manifest hash and any embedded
  self-hash that exists;
- bypasses the ambient serving-artifact constructor while calling the exact
  pinned feature extraction path;
- streams every admitted replay file once, with size/mtime stability and hash
  accumulation during that pass; and
- writes failure receipts before returning nonzero on any identity,
  timestamp, finite-value, monotonicity, settlement, or hour-20 mismatch.

An independent static review found and corrected two issues before execution:
same-build comparisons now use the complete build-instant min/max rather than
adjacent values, and legacy replay parsing now matches the manifest's
historical loader. No corpus row was used to make either correction.

## Evidence and receipts

| Evidence | Bytes | SHA-256 |
| :--- | ---: | :--- |
| Frozen predeclaration | 10,618 | `85d7590fe26d18e38ae621053e31e671af352382b2a64e3e6e82d0c15fce98d9` |
| Initial passing host admission | 3,181 | `eba3d8a1ee58c63de28714b5a226f7320e89d7477b95f3c32bcda86f9197c47e` |
| Retained admission rechecks | 3,553 | `716f77fe70dd573d2edb7483f104c445bcecbc285e288eb8ff9f0c7493d95739` |
| Prepared Mission 1 harness | 48,151 | `40b36bef8fe426d3981f9d3d3e89e9e0e42b200a7e327ba97362a357a0a3a0cf` |
| Synthetic self-test receipt | 924 | `eb415d568bf40b8f1e70ec72b16a606a581843517fb2829693bcf2fb715d371b` |
| Reused Python-environment receipt | 1,745 | `ee37837e2383bd13c55b2694799f84716b7feddd7eb86824c09c1ba5deb272ed` |
| Queue-stop receipt | 3,019 | `a924d837497c056510f4a7514b0c319a2a3394f738021b2d6621256b5d80c4b0` |

The queue-stop receipt binds the failed gate and records zero replay/vector
access. The prepared harness and scratch receipts remain outside `data/`.

## NOT DONE and safe resumption

- **NOT DONE:** the ex-ante leakage gate.
- **NOT DONE:** preblend construction proof, 124-case alpha attribution, and
  cadence-neutral incumbent characterization.
- **NOT DONE:** replay-final or recorded floor projection and rescoring.
- **NOT PROVEN:** strict upstream WU readability, exchange settlement
  authority, active-release binding, or deployability.
- **NOT CHANGED:** model, floor order, blend, alpha, config, artifact,
  release, pointer, collector, scheduler, sizing, cap, trading, or serving
  state.

Safe resumption requires sanctioned host cleanup or archival to restore at
least 50 GiB free disk, followed by a new passing admission and a fresh
self-test receipt. The first corpus action must still be exactly one
sequential Mission 1 replay pass. If that leakage gate fails, the queue stops
there; if it passes, only then may Missions 2 and 3 scan the candidate vector.
