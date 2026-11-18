# candidate for a later binding only; not B

**MG-2 pre-13 Clarification (draft): the GEFS member-mean shift on the L6 arm (L6_G).**

- **Status:** DRAFT, NOT APPLIED, written 2026-10-28 by lane L2 under `rule_rn.md` line 144 ("If WIN: a dated MG-2
  pre-13 Clarification text is drafted, not applied"). Rule `rule_rn.md` Clarification 1 sha256
  b25f36cf6e08b4ac69db548163f7f374d5906538224a453f4e5e1f92b075ad24; result `rn_score.json` sha256
  35e0c93b4e4331647a613e54365cb91b3ac9f57d07bb44021604756d95ba1162; run note `ro-g23-run-2026-10-28.md`.
- **It changes nothing today.** Not MG-2 (rule e761cc4e…, binding commit a8833a46…), not its bound L6 part
  07a6742595f535d448569980af7e04dbf4a2a798c00c82fd52f5f01287ee17e9, not the season-matched L6 state
  800072c79af65394cc33134cbaae34af65c4428feb3934e35f8cd6cd153ee2db, and not forward test B
  (`docs/operations/B_FORWARD_TEST_DESIGN.md` (on `origin/master`)), which is frozen and scores MG-2 as bound.
- **Any application** is an owner or master decision through MG-2's Clarification process, and only after the
  forward screen in [l6g_forward_prereg_DRAFT.md](l6g_forward_prereg_DRAFT.md) has returned PASS **and** the powered
  confirmation that PASS earns, on a refit state, has also passed (master's ruling 2026-10-28: the screen's PASS is
  not by itself grounds to apply; its FAIL closes the Oct-Dec state shift, not the G feature).
- **Written blind.** No outcome, label, price, market, settlement or 88a/panel row dated after 2026-09-29 was read.

## 1. Proposed text (would be inserted as an MG-2 Clarification; not inserted)

> **C-RO (pre-13 GEFS shift).** Before 13:00 local, the L6 own-obs centre mu is replaced by mu + s, with
> s = a_h + b_h (G − N), before the mg1 band probabilities. N is the NBM `v2_mean` the L6 arm already reads.
> G is the GEFS v12 06Z member mean of D: the mean over perturbed members of each member's maximum over the f006..f024
> nodes valid on local date D, counting only messages available by h:00 local, with at least 25 of 30 members, else
> s = 0 for that snapshot. h is `local_hour` (07..12). (a_h, b_h) are the frozen per-hour pairs of the refit state that passed
> the powered confirmation, pinned by sha256. From 13:00 nothing changes. If G is missing, the row is the unchanged L6 row.
> Mass is preserved; s = 0 reproduces the bound L6 vector.

## 2. What binds today

- B binds MG-2 as it is. This text is not part of B, of MG-2's gate, or of any reserved-window exemption.
- L6_G may enter MG-2's pre-13 arm only after all of the following:
  1. its own forward pre-registration (the companion draft) is reviewed by master, bound, accrued outcome-blind
     on dates after it lands, and returns PASS at its single look, which is a SCREEN (N = 45, power about 0.49).
     That PASS earns a powered confirmation on a refit state, under its own pre-registration, and that
     confirmation must pass too;
  2. a forward GEFS member-mean recorder exists, with point-in-time availability receipts and a parity check
     against the dev definition (the R-O P C1 parity check passed only at the node definition, on history);
  3. (a_h, b_h) are frozen in a sha256-pinned state file before each forward D0 (the screen's state is frozen;
     the confirmation's refit state is frozen before its own D0);
  4. the GEFS inputs are release-bound beside MG-2's `release-binding.json`;
  5. an owner decision for any NBM-reading candidate scored on 2026-10-15..11-28 (B §10).

## 3. The evidence (dev window 08-15..09-29, in-sample; selection evidence only)

- Population: 43 scored dates, 473 market-days (11 markets, Denver included), 21,664 common covered snapshots at
  local 07-12.
- **Gate 2 / gate 3 (identical comparator, L6):** dR = −0.00932, date-clustered 95% [−0.01939, −0.0000657]: PASS and
  WIN. Per hour: h07 −0.0116 [−0.0252, +0.0017], h08 −0.0130 [−0.0258, −0.0017], h09 −0.0157 [−0.0303, −0.0025],
  h10 −0.0114 [−0.0232, −0.0009], h11 −0.0007 [−0.0101, +0.0074], h12 −0.0010 [−0.0152, +0.0126]. No hour lower
  bound is above 0.
- **Controls:** s = 0 reproduces L6 exactly (diff 0); MG-1 control excess 0.011957; R-A LOYO rows 19,657, max diff
  0; gate 1 rows max diff 4.4e-16, all 30 gate 1 coefficients reproduced.
- **Against the market (reported only, never a gate):** L6_G excess +0.0076 at 07-12, positive in every hour. The
  shift narrows L6's gap to the market; it does not close it.
- **Sibling arm:** P3d_N_fix_G failed gate 2 (−0.00309 [−0.01217, +0.00586]) and is CLOSED under the rule's kill.

## 4. Flags

1. **Marginal.** The upper bound is −6.6e-5, essentially 0. The point is below the forward MDE80
   (about 0.0135 at N = 45; companion draft §8).
2. **Incumbent in-sample.** L6 is in-sample on this window (`rule_rn.md` line 143); the shift was fitted on top of
   an in-sample centre.
3. **The shift is walk-forward on dev outcomes.** (a_h, b_h) for each date were fitted on [08-01, d). The last pairs
   (fit for 09-29) are h07 (0.2, 0.15), h08 (0.2, 0.15), h09 (0.1, 0.2), h10 (0.1, 0.15), h11 (0.0, 0.1),
   h12 (−0.1, 0.1); the first (08-15) were near zero. The mean in-scope shift is +0.099 (native units).
4. **The gain sits in h07-h10.** h11 and h12 are near zero.
5. **Per-market spread is wide.** Point gains in austin, dallas, los-angeles and houston; losses in nyc
   (+0.0357 [+0.0067, +0.0716]), denver and miami. Denver is excluded from B's 10 markets.
6. **Serving source.** Dev G came from the GEFS history corpus; serving would read a forward capture
   (`rule_rn.md` discloses Open-Meteo). Forward G is not captured live today.
7. **Hour field.** Scored by `local_hour`; 9 of 21,695 rows at 07-12 have `local_hour != cutoff_hour`, plus 1
   unparsed `cutoff_hour` (disclosure only).
8. **Scope.** Centre only. No spread input, no other cycle, member statistic or step set (closed under the R-O
   kill wording for any arm that fails).
