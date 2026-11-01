# C1 result: R-ODC low_so_far on SM-L6, Oct-Dec LOYO (ledger row 85)

Status: RESULT, history only (2021-10-01..2025-12-31, 07-12). **Verdict: DROP.**

- Rule: `proposal.md` §2 C1, sha256 `ef761fec0eec6716c0625a0ec8d0a59b7b917486c8eb6f0caa05d19a734ba458`.
- Code: `claude/successor-c1-run-20261030` @ `105f1696b`, `successor_odc_low.py` sha256
  `efcbc0b6e7b1246cc718e9ede53cb8ae85b92a07fca5fd5c7fbe19ad963ef59b`. This is the launch after the crash-before-output dtype fix in
  the row 85 amendment.
- Output: `C:/t/l3succ/c1/c1.json`, sha256 `c881a5bba59c36f6dd409b055910ee2ba83a36833735ca679bd8475c053dbe14`
  (outside the repository).
- Run: queued under `workstation_heavy.ps1 -Queue`, with a thread cap of 10. It used 23,509 to 24,381 scored rows on
  375 dates.

## Control

The incumbent arm gives ΔBrier −0.0052457 [−0.00801, −0.00248] against MG-1. This reproduces the SM-L6 LOYO pooled
Oct-Dec estimate exactly (`C:/t/l3/sml6/loyo.json`: −0.005245663923351247).

## Arm − incumbent (ΔBrier, negative = helpful; date-clustered 95%)

| Cell | Point | 95% |
| --- | --- | --- |
| **Pooled Oct-Dec** | **−0.0000426** | **[−0.000312, +0.000215]** |
| 2021 | −0.000197 | [−0.000537, +0.000140] |
| 2022 | +0.000510 | [+0.000086, +0.000918] (CI-worse) |
| 2023 | −0.000143 | [−0.000756, +0.000458] |
| 2024 | −0.000165 | [−0.000768, +0.000459] |
| 2025 | −0.000221 | [−0.001276, +0.000711] |
| Oct | −0.000057 | [−0.000514, +0.000382] |
| Nov | +0.000001 | [−0.000437, +0.000470] |
| Dec | −0.000100 | [−0.000684, +0.000472] |
| h07..h09 | −0.00037 / −0.00021 / −0.00039 | h09 upper −0.00002 |
| h10..h12 | −0.00033 / +0.00031 / +0.00074 | h12 [+0.00028, +0.00120] |

Hours are reported for description only and are not a rule cell.

## Redundancy screen (outcome-free)

Spearman ρ(t_minus_low, RATE-0712) = **0.887** (n 23,509). This is at or above 0.80, so the feature is redundant with
the RATE-0712 lever that was killed 10-30 (row 81).

## Decision

C1 fails all three conditions of the pre-declared rule:

1. The pooled upper bound is ≥ 0.
2. The 2022 interval lies entirely above 0.
3. The redundancy screen fires.

R-ODC-low is therefore **dropped** from the successor batch. The forward R-ODC P1 parity test (row 72) is a separate
bound test and is not affected.

## Sizing (descriptive)

| Measure | Value |
| --- | --- |
| σ_d | 0.00276 |
| lag-1 | +0.094 |
| block-3 ratio | 1.10 |
| AR(1) VIF | 1.21 |

The history effect of −0.00004 is about 1/20 of the R-ODC joint estimate on the HRRR comparator (row 69). Measured
against the live SM-L6 incumbent, the low_so_far component carries essentially nothing.

## Consequence for the batch

The batch reduces to R-PD at 00-06 alone, which depends on C2. Its gates are:

- an Oct-Dec 01Z NBM fetch;
- the C2 ledger row, kill check and §10w and cache gates;
- a reviewed allowlist entry.

If C2 also fails, there is no successor batch.
