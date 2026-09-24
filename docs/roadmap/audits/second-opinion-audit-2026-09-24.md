# Second-opinion audit — 2026-09-24

- **Owns:** the 2026-09-24 independent (different-model, read-only) review of RE-1 code, pre-registrations, operations
  fixes, workstation handbacks and the forward plan, and the production agent's disposition of each finding.
- **Read when:** deciding RE-1 selection or verdict changes, the migration gate, or reviewing the fail-forward rules.
- **Do not use for:** current state (`docs/operations/STATE_OF_PLAY.md`) or authority.

**Verdict (auditor):** the RE-1 safety envelope is intact (hard caps at submit, post-only, single UTC day, cleanup then
cancel-all, attempt markers); the operations fixes are mechanically correct; the pre-registrations are candid about what was
seen when. The problems are structural: (1) ranking by modelled reward share selects the emptiest, fastest-moving books,
where our quote is the only liquidity an informed taker can hit, and a fill ends the session before 180 minutes, so the
campaign can neither pay nor fail adequately; (2) the amended verdicts are per session with no pooled rule across ten
sessions; (3) the plan front-loads a ten-step migration and a long nightly lease holder while settlement hardening is last.

| # | Sev | Finding | Disposition |
| --- | --- | --- | --- |
| 1 | High | Selection ranks empty books first; fills follow (sessions 4, 6 and 8 filled on low-competition bands) | **Owner decision:** pause posting and pre-register a competition floor plus a mid-stability filter |
| 2 | High | Amended verdicts per session, no pooled rule; stop rule cannot fire if no session is adequate | **Owner decision:** pre-register pooled `k`, consequences per amended verdict, an interim fill-rate stop, before 09-26 collection |
| 3 | Medium | Reconcile swallowed every read error | Fixed in `a0967b78a` (only the decode quirk tolerated) |
| 4 | Medium | Cancel re-read waits did not tick the heartbeat main loop (two-leg requote could stall 20 s); one-sided book at open surfaced as `exception` | Fixed in `a0967b78a` with tests (verified in code before fixing) |
| 5 | Medium | Campaign-level worst case unstated | Recorded: wallet at most 200, no top-ups (addendum, STATE_OF_PLAY) |
| 6 | Medium | 23b addendum self-contradiction; 89c boundary rule only in a report | Supersession note in the addendum; fill-toxicity Clarification 10 |
| 7 | Medium | 91a nightly job could hold the lease up to 4h15m | 91a not registered until bounded (STATE_OF_PLAY) |
| 8 | Medium | Fail-forward rule 2 lacked tip/HEAD binding; rule 3 could be read as allowing parallel heavy work | Both rules tightened (Operations agent role §6) |
| 9 | Low-Med | Byte-restore rewrote silently | Logs each rewrite (`5479af6fc`, test `30d1faeb5`) |
| 10 | Low-Med | Settlement hardening last; reward capture gap before 88a | STATE_OF_PLAY records the RE-0 gap (logger stopped 09-22 20:42Z; the "poll to 09-30" line was wrong); sequencing change is an owner call |
| 11 | Low-Med | Ten-step migration before any paid epoch | **Owner decision:** gate migration step 4 onward on a paid or accrued-as-modelled verdict |
| 12 | Low | RE-0 logger stopped | Confirmed; see 10 |
| 13 | Low | 2 s heartbeat triples POSTs; rate limit unverified | Watch next journal for 429 |

**Sound, do not change:** the submit boundary (single sign/post, caps, UTC day, submit counted before signing, ambiguous
transport ends without retry); cleanup ordering; `reserve_budget`; the both-legs opening check; the numeric marker sort; the
addendum's `BELOW_PAYOUT_MINIMUM` fix; fill-toxicity Clarifications 1-9 and the frozen `R` rule; fail-forward row 1 conditions;
the storage inventory's conclusions.
