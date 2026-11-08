# Live fill-calibration — owner approval record for clarification F (2026-11-07)

The owner directed clarification F in three steps in the master chat on 2026-11-07 (America/Toronto). Each is quoted
verbatim and relayed by the master.

1. **About 20:2x, option B.** The master reported that the `share_many` ≥ 0.15 floor, set for 40-share legs, would
   likely idle Monday at 20 shares. The owner chose to rescale it before Monday, conditional on Astra's check:

   > "Yes go with B if confirmed"

   Astra task T041 (final report 20:39, `C:\t\codex\T041\REPORT.md` on the workstation) confirmed the formula
   `s20 = s40/(2 − s40)` (0.15 at 40 = 0.0811 at 20) and recommended 0.08. That built the intermediate executor pin
   `27f169cef80aa93d6c9c52551a040694e8d2a5f5`, which was never used live.
2. **About 21:4x, after the master's honest assessment** put the chance of trading at all at about 50–70%:

   > "I think we over safetyfied this. I want a 95% chance we trade at all. Nothing less seems accepetable to me"

   The master relaxed all three economic selection filters (share, reward rate, depth) for the LFC profile only, and
   kept every money cap and price range.
3. **About 21:5x, on the master's description of that change:**

   > "Yes this is much better. 95% what a made up number it is fine. What I want is us to make use of this, doesn't
   > matter if we get perfect chance we won't always have that I just want real data and lets start collecting a lot
   > of it. If we lose money we learn that path is unprofitable. But we also need to be know that sometimes you take
   > small losses before wins, that is why we should be testing things"

**The text these cover:** [clarification F](live-fill-calibration-clarification-F-2026-11-07.md) as committed with this
record. The owner directed the change in substance, as was done for clarification E. This record cites their words;
it does not invent a signature.

**Code basis:** executor pin `57fe4ce1eeb14e7c0800d5eaecf65fc7eef638e1` on `codex/lfc-f0-sharefloor-20261107`.

- Its parent is `27f169ce…`; the earlier pin is `f531395522d0b0a37495185b2750164008fe586a`.
- The master reviewed the diff on the capture host on 2026-11-07, about 22:2x. Every check on the session path is
  covered: the universe rate floor, `pilot_quote`, the in-session `observe` and the submit-time reward-terms check.
  The depth guard applies to LFC only. RE-1 defaults are unchanged, and `re1_attended_cli cancel-only` is unaffected.
- One noted gap: the RE-1 `collect-payout` replay (`re1_evidence.load_prediction`) still replays at the 40 floor. It
  is not used for LFC rewards, which come from the account flow.
- The workstation pregate receipt at this sha is recorded in `C:\t\pilot1109\PINS-ANNEX-1.md` and in the session-1
  successor lock.

**Money terms:** unchanged.

- 20 shares/leg, the 100 pUSD L budget, 15.80 pUSD per order and 19.60 pUSD per band.
- Leg prices in [0.17, 0.80], mid in [0.20, 0.80], book spread at most 6 c.
- One counted session per Toronto date.
- The owner's 2026-11-06 money re-yes named the earlier pin. The master reads it as carrying to this pin, since no
  money term changed; the owner may correct that.

**Data seen:** see clarification F, F4.
