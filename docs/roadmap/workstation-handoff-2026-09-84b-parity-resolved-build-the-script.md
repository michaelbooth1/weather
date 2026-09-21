# Workstation handoff 2026-09-84b — the parity stop is resolved; build the attended script

Host: the 32 GB workstation. Issued by the production operations agent, 2026-09-21. Successor to `2026-09-84a`
(`codex/reward-test-attended-20260921` @ `955f9a792`), whose handback is accepted: **the stop was correct, and both
differences were defects in the production agent's JavaScript tools, not in the 80b Python.** Everything in the 84a
handoff that this file does not change still applies, including all of its section 0. `2026-09-84b` is a mission label.

## 1. Rulings on the two differences

- **Selection-time depth: the Python rule stands.** Before an order exists, nothing of ours rests in the book, so the
  full displayed depth competes with the hypothetical quote. `re1_select.js` subtracted 20 shares of someone else's
  size from the levels at our proposed prices. That was a defect; it overstated the predicted reward and, as your
  counterexample shows, could admit a band the frozen `>= 2.0` rule rejects. It also agrees with the merged estimator
  on `master` (`src/weather/market/reward_share_estimate.py`, the "estimator's formulas" the pre-registration cites),
  which scores the hypothetical quote against the full displayed book. Our own size is removed from a level only while
  our order really rests there, as `observe_held_quote` already does.
- **Midpoint: the Python rule stands — the size-adjusted midpoint from levels holding at least the reward minimum.** The
  venue documents a size-cutoff-adjusted midpoint for reward scoring; the estimator on `master` names the plain touch
  midpoint as an approximation of it. A one-share order must not move our quotes or force a re-quote. Safety checks keep
  using the true touch, as `price_reward_quote` already does (a buy must stay below the real best ask).
  **Additionally record, every minute, the plain touch midpoint and the share and reward computed under it**
  (`plain_mid`, `share_many_plain_mid`, `P_many_plain_mid`), as a sensitivity column only. The verdict uses the
  size-adjusted numbers. Nothing else about the frozen treatment, selection rule or verdict table changes.
- Both rulings were made on 2026-09-21 before any session and before any earnings could be known. Add them to
  `docs/research/re1m-attended-script-deviation-2026-09-21.md` as dated, outcome-blind corrections, beside the
  attended-script deviation, with your two counterexamples as the evidence.

## 2. What changed on the handoff branch

`origin/codex/reward-test-attended-handoff-20260921` now carries corrected `docs/roadmap/re1-reference/re1_lib.js` and
`re1_watch.js` (the correction is commented in `evaluate`; `re1_watch.js` marks its order `resting: true`). On the
production host the corrected tools reproduce your numbers exactly: selection counterexample `share_many` 0.166667 and
predicted 1.8750; held counterexample midpoint 0.345, `share_many` 0.20, 0.006250 per minute. Merge the branch again.
**Turn your four counterexample tests into parity tests against the corrected reference: equal results are now the
pass.** Keep one test that pins the old defect as a documented regression (the uncorrected formula gives 2.25).

The 17:20Z selection file in that folder was produced by the defective tool; its shares and predictions are overstated.
Keep using it only for what you said it can check (ranking arithmetic, tick rounding, capital). A selection made with
the corrected tool at 17:57Z still found two qualifying bands, so the test remains feasible.

The `config/location_*.json` differences you saw come from `origin/master` being newer than the 80b base (fleet-generated
event metadata). They are not part of this mission; leave them as merged.

## 3. Your other findings, answered

- **Order expiry is available with post-only (GTD, minimum 180 s ahead, 60 s venue threshold).** Use it on every order:
  expiration = the fixed session end plus the venue's threshold. A replacement placed with under 180 s left is not
  placed; the session ends instead.
- **Heartbeat is available.** Use it as the Stage 1 lifecycle does, in addition to explicit cancellation and expiry.
- **You are right that submit limits alone do not prove a loss ceiling against arbitrary bugs.** State in the report
  exactly what is proven and by which test. The run card must tell the owner that the only unconditional ceiling is the
  balance of the account the credentials control, and recommend a dedicated account holding about 50 dollars. That
  choice is the owner's.
- **The lease.** Mission 83c holds the workstation mutex for its full-suite runs. Never interrupt it. Run focused tests
  when the mutex is free; if the owner wants this mission first, the owner tells the 83c session to pause between
  suites.

## 4. Work

One thing to watch when reusing 80b: `observe_held_quote` ends the hold on midpoint drift and re-prices through
`price_reward_quote`, which refuses on conditions the by-hand treatment handles differently. Here, a leg outside the
1.0-3.0 cent window is a **re-quote** (up to four), not an end; the end conditions are only those in the 84a handoff.
Wrap or parameterize without changing 80b's behaviour for its own lane, and keep its tests passing unchanged.

Resume the 84a work order at its step 2, on the same branch, with the rulings above: build the four modes, the tests,
the two rehearsals, the full suite, the run card and the updated deviation note. All 84a hard limits, credential rules,
evidence requirements, boundaries and stop conditions are unchanged. The 84a stop "the Python selection or share differs
from the JavaScript reference" now refers to the corrected reference.

## 5. Report

Append a dated 84b section to the 84a report (do not rewrite the 84a text): verdict first in bold; parity test results
against the corrected reference; how each hard limit is enforced and the test that proves it; expiry and heartbeat as
implemented; rehearsal journal hashes; test counts; the run card; what was NOT done.
