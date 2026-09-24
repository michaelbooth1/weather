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
| 1 | High | Selection ranks empty books first; fills follow (sessions 4, 6 and 8 filled on low-competition bands) | **Owner 2026-09-24:** runs paused after session 6 for fixes and analysis; selection change pending that analysis |
| 2 | High | Amended verdicts per session, no pooled rule; stop rule cannot fire if no session is adequate | **Owner 2026-09-24: declined** — no pre-registered pooled verdicts; the owner judges RE-1 results as they come |
| 3 | Medium | Reconcile swallowed every read error | Fixed in `a0967b78a` (only the decode quirk tolerated) |
| 4 | Medium | Cancel re-read waits did not tick the heartbeat main loop (two-leg requote could stall 20 s); one-sided book at open surfaced as `exception` | Fixed in `a0967b78a` with tests (verified in code before fixing) |
| 5 | Medium | Campaign-level worst case unstated | Recorded: wallet at most 200, no top-ups (addendum, STATE_OF_PLAY) |
| 6 | Medium | 23b addendum self-contradiction; 89c boundary rule only in a report | Supersession note in the addendum; fill-toxicity Clarification 10 |
| 7 | Medium | 91a nightly job could hold the lease up to 4h15m | 91a not registered until bounded (STATE_OF_PLAY) |
| 8 | Medium | Fail-forward rule 2 lacked tip/HEAD binding; rule 3 could be read as allowing parallel heavy work | Both rules tightened (Operations agent role §6) |
| 9 | Low-Med | Byte-restore rewrote silently | Logs each rewrite (`5479af6fc`, test `30d1faeb5`) |
| 10 | Low-Med | Settlement hardening last; reward capture gap before 88a | STATE_OF_PLAY records the RE-0 gap (logger stopped 09-22 20:42Z; the "poll to 09-30" line was wrong); sequencing change is an owner call |
| 11 | Low-Med | Ten-step migration before any paid epoch | **Owner 2026-09-24: declined** — no migration gates; the owner sequences the migration by judgement |
| 12 | Low | RE-0 logger stopped | Confirmed; see 10 |
| 13 | Low | 2 s heartbeat triples POSTs; rate limit unverified | Watch next journal for 429 |

**Sound, do not change:** the submit boundary (single sign/post, caps, UTC day, submit counted before signing, ambiguous
transport ends without retry); cleanup ordering; `reserve_budget`; the both-legs opening check; the numeric marker sort; the
addendum's `BELOW_PAYOUT_MINIMUM` fix; fill-toxicity Clarifications 1-9 and the frozen `R` rule; fail-forward row 1 conditions;
the storage inventory's conclusions.

## Follow-up review (same day, after the fixes)

**Verdict:** the fixes on `a0967b78a` are correct and complete, with no new defect; the confirmation stays bound to the exact
selection digest at both check sites; the merge-tool byte restore runs only in rollback paths (parsed and exercised on temp
files: restored the changed file, left the other untouched, logged once). **Main finding (owner decision):** on an empty band
share is 100% at any size or distance, so 75 shares at 1.5 c buy fill exposure for no extra reward; quote the smallest size at
or above the reward minimum near the widest qualifying distance there, and 75 shares close in only where competition makes
size buy share. The four fills are not yet a verdict; their settlement markouts versus the public maker average decide it.

| Finding | Disposition |
| --- | --- |
| STATE_OF_PLAY stale (tips, wallet, session numbering) | Rewritten with the attempt-to-session map; 8 of 10 sessions used |
| 92a missing estimand, mapping, retained-reward view, empty-band counterfactual, read-only clause | Handoff amended (section 2 item 5) |
| Heartbeat timeout could exceed the retry window (bound 7.99 s) | Cap at 5 s goes into the next RE-1 tip with the treatment change |
| Tonight: docs are all `docs/**/*.md` (24 files) | Land by the fail-forward light path, then the tool fix via the tool (roll verdict first), then 89a |
| 89a defaults root at cwd | Runner passes explicit production roots; tip `d3dff0f2b`; hard stop before 08:30 |
| Merge-tool test is text-only; overwrite behaviour undocumented | Exercised on temp files; runbook note added (`9e3f4eea4`) |
| `checkpoint=False` reads outlast the 20 s watchdog | Recorded in the next tip's addendum note; no code change |

## Inventory review (same day): can held shares earn rewards as resting sells?

**Answer (auditor):** in principle yes — the rewards page makes any resting limit order eligible and scores both sides of a
market's book; the market-making page calls buying NO at 0.48 "economically equivalent" to selling YES at 0.52 (exact scoring
equivalence for sells UNVERIFIED; confirm with `/orders-scoring` on a first resting sell). An inventory-backed sell needs no
fresh pUSD and can only shrink a position. Today only the 75 YES Miami lot is at or above the bands' 20-share minimum; the
three NO partials cannot score as sells; no lot has its complement, so merge/split does not apply. Expected value is modest
(~0.25-1 USD per six-hour session at realistic share). RE-1 is BUY-only at every layer (shape, signer binding, fresh-ask
check, collateral maths, `initial_positions` refusal, fill-ends-session); a sell leg would be a new treatment and an authority
widening, and it needs the exchange's conditional-token allowance.

**Owner 2026-09-24:** make no changes now; consider and model every option (hold, sell at market, resting reward-earning sell,
inventory-backed two-sided quoting, merge) and make sure the data to judge them is collected. The binding data gap is
per-minute both-token books and reward terms for the T+1/T+2 bands we would quote (88a, not yet registered; the RE-0 hourly
logger stopped 2026-09-22), so 88a qualification and registration is the first roll-sensitive landing. The resting-sell
behaviour is recorded as a design input for the common maker engine (90a), not an RE-1 change.

## Cash reservation review (same day)

**Answer (auditor):** Polymarket's order-lifecycle documentation (fetched 2026-09-24) reserves cash at placement across all
open buys (`maxOrderSize = balance - sum(openOrderSize - filledAmount)`); pUSD moves on-chain only at atomic settlement, so
the wallet balance does not drop while orders rest, which likely explains the owner's "cash is taken only on fill"
observation. RE-1's reserve model matches the venue rule. The capital-efficiency lever the docs do support is negative risk
on mutually exclusive bands: a multi-band NO basket still needs full cash but its worst-case loss is far below the sum of
reserves. Recorded as Q-12; balance-allowance semantics mid-session and venue treatment of unbacked resting orders are
UNVERIFIED. No code change (owner: model options first).
