# Clarification 3 to the R-ODC / X13 released-cell P0 rule (ledger row 103, lane L16, 2026-10-31)

Applies to `rule_rodc_released_p0.md` (sha256 `9bff5c02762a27ef604219b305e6a8043497cbf0316ec2403b879f4ed09a2f11`),
Clarification 1 (sha256 `064c4f267fab1e70d5b046c00da2b9796adae77031918ce08caee2030cd48be6`) and Clarification 2
(sha256 `cec81d4fa556866a162e47ee990385f5c471973ced9a1fd35a93d98deef182c2`). None of them is edited. Where this
clarification differs from any of them, this clarification wins.

This is master's ruling of 2026-10-31 (option b), relayed by the coordinator. It was written before any rehearsal and
before look2.

**This is the only repair.** Any further look refusal, of any kind, closes row 103 as BLOCKED: it is counted, it
gets no label, and there is no look3.

## Why: look1 refused at control C-g before any statistic

- look1 refused at C-g before any statistic. No Δ was computed, and no label or price was inspected.
- The refusal log is `C:\t\l16\rodc-look1-console.log`, sha256
  `68755c85f13da8edbf88758368147c563f9c222bf7cc6f0deb40ebc78b7c871d`.
- look1's marker is `C:\t\l16\rodc\look1\look_started.json`, sha256
  `1f3ee224f8a1775f4360a00543e7a7fbf91a75c7af11ea6344529cbf204d8b93`. It stays untouched.
- **The cause was a scale mismatch.** C-g compared two values on different scales:
  - the WU whole-degree low_so_far: `wu_whole_f` half_up on the exact T-group °F;
  - the raw T-group °F `high_so_far` from the layout.
- At hour 7, a single observation can be both the low and the high. For example, 64.94 °F rounds to a low of 65 while
  the raw high stays 64.94. That is a false violation.

## 1. C-g compares both sides on the WU whole scale

- Every use of the bounds check in the driver compares on the WU whole scale: `wu_whole_f(high_so_far, "half_up")`
  against the rounded low_so_far and the rounded current temperature. This covers the C-g layout comparison and the
  `odc.check_bounds` inputs.
- **Rounding is monotone, so raw low ≤ raw high still implies rounded low ≤ rounded high. The fix therefore removes
  false violations and hides no real ones.**
  - Here, `wu_whole_f` is a non-decreasing function: an exact tenth-of-°C T-group snap, followed by half-up rounding.
- The running-minimum check and the low ≤ current check are unchanged. Both sides of each were already on the WU
  whole scale.

## 2. odc_metar_features stays frozen, and the fix lives in the driver

- `odc_metar_features.py` stays blob-unchanged (`1cc4d565468bf4959137a8f6f6cec5b10adfce24`, the blob at 0e11b018f),
  and a test checks this. The fix is applied in the driver, by rounding the high it passes to `odc.check_bounds`.
- **Can `odc.check_bounds` drop or flag serve-side snapshots in the look's feature path? No.**
  - It is a refusal. It raises `OdcMetarRefused` on any violation, and otherwise returns the number of hours
    checked. It never drops, edits or flags a snapshot.
  - The look's feature path calls only `odc.odc_features` and `odc.kept_rows`. Neither of them calls
    `check_bounds`.
  - The driver's C-g is the only caller. With the frozen raw-high comparison, it refuses the whole run, as look1
    showed.
- **The receipt still counts what the frozen comparison would have done:**
  - the snapshots whose rounded low exceeds the raw layout high;
  - the (market, date) cells whose `check_bounds` would refuse with the raw high.

  These are the would-refuse counts. No snapshot is dropped either way.

## 3. A rehearsal is required before look2

- `rehearse-to-table` runs the exact look2 path:
  1. guards;
  2. controls C-a, C-b, C-d and C-e;
  3. the release layout load;
  4. the feature loop under the trainer rule;
  5. C-g;
  6. the US10 power projection.
- It stops before `sc.Table`. It never calls `sc.Table`, C-c or `p0_candidate`, so no Δ is computed.
- It writes only below `C:\t\l16\rodc-rehearse\`, as exclusive-create files, and creates no `look_*` file.
- **Its receipt holds:**
  - the C-g verdict;
  - feature_reasons;
  - the would-refuse counts;
  - N and projected power per arm.
- **look2 needs a rehearsal PASS.** A failed rehearsal exposes no outcome, so it may be fixed and rehearsed again.

## 4. The guard for look2

- look2's `--out` lives under the new guard root `C:\t\l16\rodc-look2\`. look1 stays untouched.
- **The guard refuses if either of these holds:**
  - any `look_*` file exists under `C:\t\l16\rodc-look2\`;
  - anything other than look1's marker (sha256 `1f3ee224…8b93`) exists under `C:\t\l16\rodc\*\look_*`. So there
    can be no look receipt and no second marker there.
- The guard runs before the run starts, and again in `begin_look` immediately before the marker is written.
- look2's receipt records look1's marker sha and the refusal log sha.
- **The approval string is pinned, exactly:** "master 10-31 R-ODC row 103 look2: one bounded C-g WU-scale repair
  (Clarification 3) after look1 refused at C-g before any statistic; rehearsal PASS required; no look3".

Nothing else changes: the statistic, the fit (coef sha256 `24bdb0a6…`), parity2 (receipt sha256 `163bc040…`), the
trainer rule, the US10 exclusions, C-c, the EPS guard and the labels.
