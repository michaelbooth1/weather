# Workstation floor-retrain gate harness report - 2026-08-01

## Verdict

The candidate-independent qualification harness is implemented and the exact
incumbent/incumbent run passes. All four comparative calculations return an
exact tie, the row-level and served-output invariants pass, and all 55 protected
slice rows have zero regression flags.

This is a harness self-check, not candidate qualification. Future qualification
correctly remains `NOT_READY`: the accepted July evidence is band-level and
predates the conditional candidate, inactive release, and candidate-bound
parity/replay receipts.

No candidate was built. No retrain, fit, artifact write, serving action,
promotion, pointer action, or `data/` write occurred.

## Frozen execution identity

- Base: exact `origin/master` `b125e2df013cabc3a2cf853a372a42ebc08bea56`.
- Topic branch: `codex/workstation-gate-harness-2026-08-09a`.
- Declared run root:
  `C:\Users\Michael\Documents\github\weather\scratch\runs\gate-harness-2026-08-09a`.
- Declared corpus: July 22-30 only. The runner rejects any target date outside
  that exact allowlist. No August 6-19 input was read or evaluated.
- Bootstrap: paired market-day blocks, one-sided 95% upper quantile, seed
  `20260809`, 10,000 repetitions.
- Probability tolerance: `1e-12`; severe probability-gap threshold: `0.30`;
  materially bound threshold: removed mass `>1%`; newly severe rate cap:
  `1,065 / (8,380 x 11)`.

The four read-only inputs were verified before evaluation:

| Input | SHA-256 |
| :--- | :--- |
| Accepted promotion corpus | `294a094679d24ff11c13a6f3148a6ec76554152f781af46e8e4f1ada5f6def42` |
| Accepted replay summary | `4be2dbd8823dd3ab6ffac3d62e695645db0a8f0d58149f0438b43d64bce1c96a` |
| Accepted replay band rows | `bc1d4e80d65c98274be6d976ead97a391467124304fba14081e47a11aee5b2e8` |
| Accepted full floor trace | `305435e5a83dad7aabec50ac8dd6acc0a524b6b5b7b90df4dddf257d1d9a6c9b` |

Manifest and adapter checks reproduced the accepted 12 markets, 9 dates, 108
market-days, 19,265 snapshots, and 211,915 mutually exclusive band rows. The
maximum accepted-replay/floor-trace probability mismatch was exactly zero.

## Implemented gates and incumbent result

| Gate | Incumbent mirror | Exact result | Future candidate state |
| :--- | :--- | :--- | :--- |
| Corpus and target | `PASS` | 19,162 floor-available rows; zero `Y<F`; zero invalid winner partitions | `NOT_EVALUABLE` until canonical floor-source and leakage/cutoff receipt fields are exported |
| Total Brier non-regression | `TIE_SELF_CHECK` | baseline = candidate = `0.05255831235690557`; delta = `0`; bootstrap upper bound = `0` | Gate executable; equality is allowed by this non-regression gate |
| Severe-tail improvement | `TIE_SELF_CHECK` | incumbent-frozen = candidate = 9,032 severe rows; positive excess = `1.718715410383236`; every date reduction = `0` | `BLOCK` for a real candidate because strict improvement is absent |
| Newly severe cap | `TIE_SELF_CHECK` | 0 new, 0 retired, rate `0`; exact zero/zero self-check tie | `BLOCK` for a real candidate because retired must exceed new |
| Near-floor allocation | `TIE_SELF_CHECK` | 13,949 materially bound snapshots; band-relative Brier = `0.30171725566936125`; mode accuracy = `0.5872822424546562`; all deltas = `0` | `NOT_EVALUABLE` without candidate-native `D=0`, `D=1`, `D>=2` distributions |
| Probability mass | `PASS` | zero band bounds/mass errors across 19,265 partitions | `NOT_EVALUABLE` for native mass and bucket-to-band conservation without native export |
| Floor invariant | `PASS` | zero final band-proxy sub-floor violations; zero hard 0/1 answer violations; 19,095 raise-`F` metamorphic cases, zero failures | `NOT_EVALUABLE` until all six candidate internal stages, native support, and paired floor-decision receipt exist |
| Train/serve parity | `PASS_SELF_CHECK_MIRROR` | fail-closed receipt checker and positive/negative fixtures exercised | `NOT_EVALUABLE` before candidate C/F parity receipt exists |
| Captured-input replay | `PASS_SELF_CHECK_MIRROR` | fail-closed receipt checker and positive/negative fixtures exercised | `NOT_EVALUABLE` before inactive candidate release replay exists |
| Release binding | `PASS_SELF_CHECK_MIRROR` | fail-closed receipt checker and positive/negative fixtures exercised | `NOT_EVALUABLE` before release #1 and inactive candidate graph exist |

The severe result independently reproduces the accepted 9,032 rows and
`1.7187154103832492` positive-excess total to floating-point accumulation error.
The total-Brier result independently reproduces the accepted daily-first replay
Brier `0.052558312356905584`.

## Protected reports

The harness emits total-Brier delta, incumbent-frozen tail delta, baseline and
candidate severe counts, new/retired membership, and deterministic regression
flags for every required dimension:

| Dimension | Emitted rows |
| :--- | ---: |
| Market | 12 |
| Capture hour | 24 |
| Floor source | 2 (`unknown` and `none`; see specification correction) |
| Floor-binding strength | 5 |
| Forecast-relative winner position | 8 |
| `D` class | 4 |
| **Total** | **55** |

There are zero Brier, frozen-tail, or severe-count regression flags in the
incumbent mirror. The scorecard also emits floor-band/one-above/upper-tail mode
confusion by market and capture hour. These flags make a slice regression
mechanical; the word "catastrophic" still needs an adopted numerical threshold
before it can be an automatic hard gate.

## Specification defects and corrections

1. **Strict comparative gates need a self-check state.** Incumbent versus itself
   cannot satisfy strict severe-tail, retirement, near-floor Brier, or mode-lift
   inequalities. `TIE_SELF_CHECK` is now explicit and can never qualify a real
   candidate. The newly-severe exception is limited to the exact 0-new/0-retired
   self-check tie.
2. **The accepted replay cannot implement the native continuation gate.** It
   exports final 11-band probabilities, not native `P(D=0)`, `P(D=1)`, and
   `P(D>=2)` or a lossless native bucket-to-band map. The harness implements the
   native gate, accepts a hash-bound JSONL native export, and remains
   `NOT_EVALUABLE` when that export is absent. The July run reports only a
   clearly labeled band-relative proxy.
3. **The accepted floor trace omits canonical floor-source provenance.** It can
   prove floor availability, bucket, materiality, `Y>=F`, final served band
   behavior, and the raise-`F` proxy, but the required floor-source slice is
   necessarily `unknown`. Candidate qualification now requires a hash-bound
   corpus receipt and paired floor-decision/source/disposition receipt.
4. **A structurally conditional candidate needs stage evidence that the
   incumbent cannot supply.** Candidate qualification requires below-floor mass
   for conditional model, conditioned prior, post-blend, post-hard-floor,
   post-calibration, and final served stages. Missing stages do not pass.
5. **Parity, replay, and binding are receipt gates, not derivable metrics.** The
   accepted pre-release corpus has no candidate feature-order/NaN/decode chain,
   inactive-release replay identity, complete immutable role graph, or release
   pointer receipt. The harness implements fail-closed schemas for each; the
   incumbent run exercises the logic as a mirror without claiming evidence that
   does not exist.
6. **"One catastrophic slice" is not numerically defined.** The report emits
   every required slice and flags any positive Brier/tail regression or severe
   count increase. It does not invent a catastrophe threshold before a lock.

These are evidence-contract corrections. None changes a frozen statistical
threshold or uses July 27-30 to make a tuning decision.

## Implementation and verification

The pure gate engine is
`src/weather/reporting/validation/floor_retrain_gate_harness.py`. The read-only,
hash-bound adapter and report writer is
`src/weather/reporting/validation/floor_retrain_gate_cli.py`. Both payloads have
registered schemas, and focused tests cover exact ties, native mass/mapping
failure, fail-closed missing receipts, deterministic bootstrap, metamorphic
input immutability, all protected dimensions, and the July-only date guard.

Verification completed:

- focused harness and schema-registry tests: 14 passed;
- compile of both new reporting modules: passed;
- incumbent run: `PASS`, zero protected-slice regressions;
- `git diff --check`: passed.

The broader import-architecture suite passed all behavioral checks but its
clean-tree ratchet correctly reports newly created critical files as untracked
until they are staged. It will be rerun after the intentional commit.

## Evidence outputs

| Output | SHA-256 |
| :--- | :--- |
| `floor-retrain-gate-scorecard.json` | `b5f0c3220b0ff8a2e65cedd0601b5723b2038128333b7e270cecbd7f9f45ddf8` |
| `floor-retrain-protected-slices.csv` | `75def5c9a21d3ca4dca9a2730e97514c366867db63ccc75a276a2db81b2c182e` |
| `floor-retrain-gate-report.md` | `7eaa2f8c5cc676b2a81cbd16d7cfc166a300deb65d6e94fdcbd16d657da7d191` |

All three outputs are under the declared run root outside the replay mirror.
The mirror and `data/` remained read-only.
