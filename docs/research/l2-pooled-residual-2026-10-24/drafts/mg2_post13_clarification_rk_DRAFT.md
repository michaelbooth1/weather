# DRAFT: MG-2 post-13 Clarification proposal from R-K (HRRR hourly path)

**Status: DRAFT, NOT APPLIED.**
- Drafted by lane L2 on 2026-10-25 under R-K's gate-4 WIN clause (`rule_rk.md` sha `21b5dfe1…7221`, RK-1
  `c825b277…32c7`; result `rungk/rk_summary.md` sha `bf0eb761…256e`).
- It changes nothing in MG-2, its rule, its frozen state or L8's branch.
- Any application is an owner or master decision through MG-2's own Clarification process.

## 1. What binds today

**B binds MG-2 as it is (C7/C8, as relayed by the coordinator).** MG-2's post-13 arm stays exactly as frozen:
- P3d_N 13-23 with the MG-1 fallback;
- the forward state as frozen (`p3d_n_state.pkl` `c6cc39f7…`);
- the gate on as-of-capture inputs per C7.

This draft does not propose replacing, re-fitting or re-gating that arm on the dev evidence. R-K is dev evidence,
and the dev window is MG-2's own selection window.

**P3d_H can enter only through its own forward pre-registration.** That pre-registration needs:
- **(a)** the HRRR forward recorder (companion draft `hrrr_forward_recorder_parity_plan_DRAFT.md`) landed, with
  its parity proven at the stated tolerances;
- **(b)** enough forward capture days, on dates after the pre-registration's sha, for its own pick-or-kill test;
- **(c)** a frozen P3d_H state, fitted on 2021-25 (no dev rows) and sha-bound before the first forward day is
  scored;
- **(d)** release binding of the HRRR inputs per snapshot (`hrrr_cycle_utc`, `hrrr_msg_sha256[]`).

Until all four hold, P3d_H is not a candidate for serving, shadow promotion or MG-2's composite.

## 2. The evidence (dev, selection window; see `rk_summary.md`)

- **LOYO 2021-25, B_H − B_N 13-16:** −0.0139 [−0.0166, −0.0112].
- **Dev P3d_H − P3d_N_fix 13-16:** dR −0.0722 [−0.0979, −0.0471].
- **Against the as-of-capture composite post-13 arm:** the same, WIN.
- **MG-2's G2 form, Brier against MG-1 at 13-16:** P3d_H_mg1 −0.0171 [−0.0213, −0.0134], against the composite's
  −0.0151 [−0.0192, −0.0113].
- **P3d_H is still worse than the market:** R = 1.220 [1.100, 1.349].

## 3. Flags the forward pre-registration must carry

### 3a. San Francisco (per-market sign reversal)

- **The finding:** dev P3d_H − P3d_N_fix at 13-16 is +0.0954 [+0.0268, +0.1735] in san-francisco. The other ten
  markets are negative, four of them with upper bounds below 0.
- **Why it is only a flag:** it is one market in 11 on 43 dates, read after the fact. It is selection evidence and
  cannot by itself define a fallback.
- **Proposed pre-registered per-market check** (to be fixed, with its sha, before any forward day is scored):
  1. **Descriptive prior check (no outcome dated after 09-29).** From the existing R-K LOYO rows
     (`C:\t\l2\rungk\loyo\loyo_rows.jsonl`, sha `bb0bf494…`), report P3d_H − P3d_N_fix and B_H − B_N per market
     at 13-16 with date-clustered intervals.
     - This is reported only and cannot change the forward rule.
     - It shows whether SF's reversal is also present out-of-season (a coastal marine-layer mechanism) or is a
       dev-window artefact.
  2. **Forward per-market guard.** On the forward test, compute per-market dR (P3d_H − P3d_N) at 13-16 with
     date-clustered 95% intervals and a Holm adjustment across the 11 markets.
     - A market whose Holm-adjusted lower bound is above 0 is **HARM** for that market. P3d_H is then not used
       there, and the arm falls back to P3d_N.
     - A market that is not HARM keeps P3d_H only if the pooled forward gate passes.
     - The guard can only remove a market, never add one.
  3. **No SF-specific fallback now.** No market is excluded or special-cased on the dev evidence.

### 3b. h16 weakness

- **Dev:** h16 P3d_H − P3d_N_fix dR is −0.0367 [−0.1012, +0.0237], not significant.
- **LOYO:** P3d_H − P3d_N_fix at h16 is +0.0027 [−0.0020, +0.0075], no gain. The HRRR window at h16 is only
  16:00-17:00 (two forecast hours).
- **Proposed pre-registration:**
  - The forward primary pool is 13-15. h16 is a reported secondary.
  - P3d_H serves h16 only if the forward h16 interval is below 0. Otherwise h16 stays P3d_N.
  - This is fixed before forward scoring and is not re-chosen after.
  - The alternative of pre-registering 13-16 with h16 included is also acceptable, provided the choice is made
    before any forward day.

### 3c. Other carried items

- **No change to 17-23.** R-K's window ends at 17:00 local. Hours 17-23 stay P3d_N.
- **Toronto** is outside R-A's markets and stays on its current path.
- **Spread is not re-tuned.** The R-I kill (spread recalibration at 07-12) is unrelated and not reopened.

## 4. What the forward test would read (proposal, for its own rule)

- **Arms:** P3d_H (frozen, 2021-25 fit) against MG-2's served post-13 arm on as-of-capture inputs, 13-15 primary
  (see 3b), with the MG-1 fallback in both.
- **Statistic:** dR, date-clustered, with a pre-declared minimum detectable effect from the dev interval width. The
  dev 13-16 interval is about ±0.025 on 43 dates.
- **Days:** set by that rule's power statement. A floor of 30 forward capture days with recorder coverage ≥ 0.95
  is proposed, so the interval is comparable to dev.
- **Kill:** if the forward primary upper bound is not below 0, HRRR is closed as a 13-16 input to MG-2.

## 5. Not proposed

- No serving change.
- No MG-2 re-gate.
- No new dependency.
- No paid data.
- No DPT or wind.
- No 07-12 HRRR: that is unfetched and has no ruling.
