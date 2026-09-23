# Workstation handoff 2026-09-84a — run the first paid reward test as an attended script

Host: the 32 GB workstation. Issued by the production operations agent, 2026-09-21, at the owner's request.
`2026-09-84a` is a mission label. **This mission places real orders with real money. Read section 0 before anything
else.**

## 0. Authority — what this file is and is not

- **This file carries no authority.** It is a technical specification written by an agent. Under
  `docs/operations/DELEGATION_CONTRACT.md` an agent's handoff cannot authorize a live order, and `AGENTS.md` reserves
  live orders to the sealed `portable_execution_v1` lane.
- **The authority is the owner's, and it must reach you directly.** The owner told the production agent on 2026-09-21:
  move the live test up, run it from the workstation, script it so the evidence is captured exactly, and a worst case of
  20-30 dollars is acceptable. Before you write any code that can sign, ask the owner to confirm that in your session in
  their own words. If they do not, build and rehearse against fakes only and hand back.
- **The owner's exception is narrow.** It covers the by-hand test already pre-registered as RE-1M
  (`docs/research/liquidity-reward-epoch-preregistration-2026-09-20.md`, on
  `origin/codex/reward-epoch-design-20260920`), executed by an attended script instead of by hand: **at most three
  sessions in total, none after 2026-09-30, International Polymarket only.** It changes nothing in the sealed lane, sets
  no precedent for it, and ends with this mission.
- **You never start a live session.** You write, test and rehearse. **The owner starts the live command in their own
  terminal and types the confirmation the script displays.** You do not run live mode, type the phrase, script the
  phrase, or add a flag that skips it. While a session runs you may read its journal; you do not touch the process
  except to tell the owner to run the panic command.

## 1. Goal

One command the owner runs, attended, that executes the frozen RE-1M treatment on one band for 360 minutes inside one
UTC day, captures every measurement in the pre-registration (M1-M6) with hashes, freezes the prediction before any
payout can be known, and **cannot lose more than the treatment's worst case (15.8 dollars) whatever goes wrong,
including a bug, a crash or a lost connection.** A second, read-only command collects the payout evidence the next day.

Target first session: **Tuesday 2026-09-22, 13:00-19:00 Eastern (17:00-23:00Z)**. The production host's hourly dry runs
found a qualifying band in 20 of 26 hours; the misses were mostly between 05Z and 16Z. If no band qualifies at the
start, the script may re-run the selection every 15 minutes until 14:00 Eastern, then gives up for the day (360 minutes
must end before 00:00Z).

## 2. Start from this — do not re-derive it

- Work on a new branch `codex/reward-test-attended-20260921` from `origin/codex/stage2-hold-build-20260921`
  (`88aa7e43a`, mission 80b, reviewed and accepted). Merge this handoff branch into it. 80b already contains, tested:
  the frozen RE-1 ranking and public reads (`src/weather/market/mm_stage2_selection.py`), the reward-share prediction,
  the hash-chained journal and frozen-prediction writer (`mm_stage2_hold.py`), the scoring and earnings parsers over
  the pinned SDK (`mm_stage2_rewards.py`), the two-token user stream (`mm_stage2_user_stream.py`), the official
  adapter (`mm_official_adapter.py`) and the fakes (`tests/market/stage2_fakes.py`). **Reuse them; do not rewrite
  them.**
- The reference implementation of the by-hand tools is in `docs/roadmap/re1-reference/` beside this file:
  `re1_lib.js` (estimator formulas), `re1_select.js` (selection), `re1_watch.js` (minute journal, `P_many`/`P_single`,
  alerts), and one real selection output from 2026-09-21 17:20Z. The Python must produce the same selection and the
  same per-minute share as the JavaScript on the same inputs; show it with a test on the recorded file as far as its
  recorded inputs allow, and say what could not be compared.
- The frozen treatment, selection rule, measurements and verdict table are in the pre-registration. Do not restate or
  reinterpret them; implement them. The one recorded deviation is "orders placed and cancelled by an attended script
  instead of by hand". Write it as a dated deviation note (section 6). Nothing else about RE-1M changes. The
  place-and-hold addendum from 80b is **not** used here: this test re-quotes as the pre-registration says.

## 3. Hard limits — constants in the module, asserted at the single place an order is submitted

No command-line option, environment variable or config file may widen any of these.

| Limit | Value |
| --- | --- |
| Venue | the International Polymarket CLOB host, hard-coded; refuse anything else; refuse if any proxy variable is set (reuse `live_path_security`) |
| Side and type | BUY only; resting limit; post-only. No sell, no market order, no taker exit, ever |
| Size | exactly the band's reward minimum, which must be 20 shares |
| Price | the selection's computed price for that leg, inside 0.17-0.80, **strictly below the token's best ask read immediately before the submit**; otherwise do not submit |
| Cost | one leg <= 15.8; both legs together <= 19.6 |
| Open orders | at most two of ours at any moment; zero account-wide before the first submit, exactly our first order before the second |
| Submits | at most 10 per session (two legs, four re-quotes); one session per process; at most three sessions ever (persist the count beside the journals and refuse a fourth) |
| Duration | 360 minutes; the end time is fixed and journaled before the first submit and must be before 00:00Z |
| Expiry | if the SDK lets a post-only order carry an expiration, set it to the fixed end time plus the venue's minimum margin, so the orders die without us. If it cannot, say so in the report and rely on the rows below |

**Every way out cancels.** Normal end, any end condition, any exception, Ctrl-C and interpreter exit all run the same
routine: cancel our order ids, then account-wide cancel-all as a backstop (safe because the account was empty before
we started), then an authenticated read that shows zero open orders, all journaled with the venue's acknowledgement.
If that read cannot show zero, print a loud instruction telling the owner to run the panic command and to check the
account in the browser. Provide that **panic command** (`cancel-only`): it cancels everything on the account, prints
what remains, needs no confirmation, and the owner can run it at any time from a second terminal. If the pinned SDK
offers the heartbeat / cancel-on-disconnect the Stage 1 lifecycle used, use it as well and say so.

End conditions, all from the pre-registration: any fill on either leg, even partial (cancel the other leg, **keep the
inventory to settlement**, end); reward minimum above 20; rate below 40; one-sided book; **geoblock state blocked or
unreadable** (check the official endpoint at start and at least every 45 seconds; fail closed); a fifth re-quote
needed; the fixed end time. Re-quote only when a leg rests outside 1.0-3.0 cents from the current midpoint: cancel that
leg, confirm the cancel, then place the replacement under every limit above.

**Nothing in this mission may mask, alter or route around location or eligibility.** The owner confirms in the typed
prompt that the home file-access tunnel is down. The geoblock endpoint is read, never influenced.

## 4. Credentials

- The owner says the credentials are in `.env` at the repository root on the workstation. **You never open, print, cat,
  grep, diff, copy or summarize that file, and never echo an environment variable.** Ask the owner for the variable
  *names*, or list names only with a one-liner that prints the text left of each `=` and nothing else.
- The script loads the values in-process at start, in live and panic modes only. Rehearsal mode must run with the file
  absent.
- Before every journal write and every print, a guard checks the text against the loaded secret values and refuses to
  write if any appears. Test the guard. Request and response journaling drops authentication headers and signatures.
- Confirm `git check-ignore .env` succeeds before your first commit; stage files by name, never `git add -A`. Do not
  write credentials into the Windows vault, the sealed lane's stores, or anywhere else.

## 5. What the script records (this is the point of the test)

One session directory per run, outside the repository's tracked tree, with a hash-chained journal (reuse 80b's):

- Before the first order: the full selection table and its SHA-256; the owner's typed confirmation text and time; the
  fixed end time; account-wide open orders (must be none); positions in the chosen condition's two tokens (must be
  none); balances in **both** candidate reward assets named in the pre-registration; the venue fee for each token
  (finite, >= 0); the geoblock response.
- Every submit and cancel: the request (redacted), the venue's full response, order ids, local send and receive times.
- Every minute: the live reward record, both books, whether each leg is visible at its price, `share_single` and
  `share_many` with our own size removed from its level, and running `P_single` / `P_many` (M3, M6).
- M1 order-scoring status at placement and every 30 minutes; M2 reward percentages and accrued earnings every 30
  minutes; M5 any fill with price, size, fee and time.
- At the end: cancellation acknowledgements, the zero-open-orders read, balances again, then the **frozen prediction
  file** (`P_many`, `P_single`, visible two-sided minutes, re-quotes, journal SHA-256). Print its path and hash.
- `collect-payout` (read-only, owner-run on a later UTC date): refuses unless the frozen prediction file exists; records
  the earnings row for that condition and UTC day, total earnings, and both balances; computes `k = paid / P_many` and
  `k_accrued`, and prints the verdict from the pre-registration's table without editing any threshold.

## 6. Work order

1. Owner confirmation (section 0). Variable names (section 4).
2. Build `src/weather/market/re1_attended.py` (or the nearest fitting name) plus a thin CLI with four modes:
   `rehearse` (public books + fakes, no credentials), `live` (owner only), `cancel-only` (owner only), `collect-payout`
   (owner only, read-only). Keep it outside the sealed lane: the lane's modules must not import it, and it must not
   edit, relax or bypass any lane gate, grant check, template, sealer or test.
3. Tests with the 80b fakes and a fake clock: every end condition leaves zero open orders; an exception between the two
   submits cancels leg one; Ctrl-C cancels; every hard limit refuses at the submit point (wrong side, size 21, price at
   or above the ask, an eleventh submit, a third open order, a fourth session, an end time after 00:00Z); the secret
   guard; a partial fill ends the session and never sells; re-quote arithmetic matches `re1_watch.js`.
4. Rehearse the full 360-minute flow accelerated, and one real-time rehearsal of at least 15 minutes against live public
   books with the fake exchange. Retain the journals.
5. Full suite through `scripts/ops/workstation_heavy.ps1`; zero new failures.
6. Write the owner's run card (one page, in the report): the exact commands for `live`, `cancel-only` and
   `collect-payout`; what the owner checks before starting (tunnel down; the geoblock page reads not blocked in the
   browser; the account has no open orders in any rewarded market today; at least 25 dollars free; they can stay within
   reach for six hours); what each alert means; when to run the panic command.
7. Write `docs/research/re1m-attended-script-deviation-2026-09-21.md`: the one deviation, the exception's limits from
   section 0, and "owner confirmation: recorded in the session journal". Push the branch. **Never merge to `master`.**
8. When the owner runs a live session: watch the journal, answer questions, and afterwards add the session's frozen
   prediction hash and outcome to the report. Report every session, including failed and inconclusive ones.

## 7. Boundaries

Everything in `docs/operations/DELEGATION_CONTRACT.md` §2 still binds except the single owner exception in section 0.
No paid data source. No production-host, Scheduler or capture change. No change to any floor, gate or lane control. No
second strategy, no extra band, no larger size, no extension of the three-session cap or the 2026-09-30 end date,
whatever the first result looks like. If any hard limit in section 3 cannot be implemented as written with the pinned
SDK, **stop and report; do not substitute a weaker one.**

## 8. What would stop the mission

- The owner does not confirm in your session => rehearsal only.
- The SDK cannot place a post-only resting BUY, or cannot cancel by id and read open orders outside the sealed lane
  without editing lane code => stop and report the exact call and error.
- Any end condition leaves an order open in a fake-clock test => NO-GO.
- The Python selection or share differs from the JavaScript reference on the same inputs => stop; report both numbers.

## 9. Report

`docs/roadmap/agent-report-2026-09-84a-workstation-run-the-reward-test-attended.md`, per contract §5: verdict first in
bold (READY FOR THE OWNER TO RUN / REHEARSAL ONLY and why / BLOCKED and why); which 80b modules were reused; how each
section 3 limit is enforced and the test that proves it; whether order expiry and heartbeat were available; test
counts; rehearsal journal hashes; the run card; what was NOT done. After each live session append: start and end times,
band, prices, visible minutes, re-quotes, fills, `P_many`, `P_single`, the frozen prediction hash, and later the payout
and verdict.
