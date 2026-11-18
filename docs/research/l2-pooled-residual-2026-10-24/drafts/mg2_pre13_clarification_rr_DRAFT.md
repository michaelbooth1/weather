# DRAFT: MG-2 pre-13 Clarification proposal from R-R (HRRR hourly path, 07-12)

**Status: DRAFT, NOT APPLIED.**
- Drafted by lane L2 on 2026-10-26 under R-R's gate-4 WIN clause.
  - Rule: L13's `rule_rr.md`, sha `e3d92e1a…bb22`.
  - Result: `rungr/rr_summary.md` on `claude/rung0712-20261025`, with `rr_score.json` sha `577b689b…1dab`.
- It changes nothing in MG-2, its rule, its frozen L6 state (`07a67425…e17e9`), its nowcasts (`3806687c…a31f3`) or
  L8's branch.
- Any application is an owner or master decision through MG-2's own Clarification process.

## 1. What binds today

**B binds MG-2 as it is (C7/C8).** MG-2's pre-13 arm stays MG-1 + L6, as frozen, with no refit and no re-gate on dev
evidence. R-R is dev evidence, read on MG-2's own selection window, and its rule says it was chosen *because* R-K won
(disclosure 2).

**blend_l6_H can enter the pre-13 arm only through its own forward pre-registration.** That pre-registration needs:
- **(a)** the HRRR forward recorder landed with parity proven, extended to h07-12 and to RN-1's point rule (companion
  draft `hrrr_forward_parity_rr_addendum_DRAFT.md`);
- **(b)** forward capture days dated after that pre-registration's sha, enough for its own pick-or-kill test;
- **(c)** a frozen P3d_H 07-12 state, fitted on Aug-Sep 2021-25 only and sha-bound before the first forward day;
- **(d)** release binding of the HRRR inputs per snapshot: `hrrr_cycle_utc`, `hrrr_msg_sha256[]`, and
  `point_rule = RN-1` with `land_sha256` `22069beb…d7fd6` and the chosen index per station.

**The walk-forward weight is frozen too.** The blend weight w(h) must be frozen or fitted by a walk-forward procedure
fixed in that pre-registration. The dev means (0.54-0.78 by hour) are reported, not adopted.

## 2. The evidence (see `rr_summary.md`)

- **LOYO 2021-25 (the only gate on data not previously seen with HRRR):**
  - B_H − B_N 07-12: −0.0092 [−0.0112, −0.0073];
  - P3d_H − P3d_N_fix: −0.0223 [−0.0248, −0.0198].
  - Every hour from h07 to h12 is negative with its interval excluding 0.
- **Dev gate 3, P3d_H − P3d_N_fix dR:** −0.0598 [−0.0813, −0.0401].
- **Dev gate 4, blend_l6_H − L6 dR:** −0.0402 [−0.0603, −0.0198], WIN. Every hour's interval lies below 0.
- **The HRRR increment inside the blend (blend_l6_H − blend_l6):** −0.0307 [−0.0451, −0.0167].
- **MG-2's G2 form (Brier against MG-1):** blend_l6_H −0.0059 [−0.0079, −0.0040], against L6's −0.0038
  [−0.0059, −0.0018].
- **Against the market:** the arm is still worse. blend_l6_H R = 1.112 [1.072, 1.159]; L6 R = 1.152.

## 3. Flags the forward pre-registration must carry

1. **The incumbent is in-sample** (disclosure 3), which favours L6. The forward test removes this.
2. **Overlap with the exhaustion register.** h07-09 overlaps S6's 06-09 hours (HRRR-latest, TESTED-UNDERPOWERED).
   - R-R differs in source, timing, estimand, model and training. S6, S7 and §10q stand as recorded.
   - If this is applied, the register entry should cite R-R as a distinct construction, not as a re-score.
3. **Per-market behaviour:**
   - nyc is the only market with a positive gate-4 point estimate: +0.0053 [−0.0588, +0.0722];
   - houston is the only market with a positive gate-3 point estimate: +0.0168 [−0.0578, +0.0862].
   - Neither is significant. Carry R-K's proposed forward per-market Holm guard, which can only remove a market.
4. **San Francisco under RN-1** improves at 07-12 (gate 3 −0.0534 [−0.0948, −0.0151]). R-K's 13-16 result used
   nearest-cell inputs. Any 13-16 forward pre-registration should state which point rule it uses, so the two hours
   blocks are not mixed silently.
5. **Missing cycles** (`k_miss` = 1) must be produced identically live. Two LOYO cycles were absent. The forward
   recorder must emit `k_miss` = 1, not a stale cycle, when no cycle satisfies availability + 10 min ≤ h:00.
