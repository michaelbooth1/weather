# Workstation handoff 2026-09-80a — build the smallest code path that can rest a reward-eligible quote

Paste this whole file into a fresh agent on the 32 GB workstation. `2026-09-80a` is a mission label, not a date.
Issued 2026-09-21 by the production operations agent. Owner priority: **shorten the time to a repository-run live test.**

## Prompt (read this first)

You are an implementation agent on the project's non-capture workstation. Your job is to build, test and push the
**smallest** sealed, attended session that can rest one two-sided, reward-eligible quote on one International Polymarket
weather band and prove what it earned — and to leave it **inert** until the owner authorizes it. You will never place,
cancel or sign an order, never open a credential, never run the live SDK against the venue, and never loosen a control
to make something pass. Everything you run uses fakes, recorded fixtures and public unauthenticated reads. Speed comes
from cutting scope, not from cutting controls: if a control blocks you, the deliverable is the sentence explaining why.
Work the packages in order, push after each one, and write the report even if you stop early.

First read, in this order: `AGENTS.md`; `docs/operations/STATE_OF_PLAY.md`; `docs/operations/DELEGATION_CONTRACT.md` §2–§5;
`docs/operations/INTERNATIONAL_MM_LIVE_PILOT.md`; `docs/operations/PORTABLE_LIVE_EXECUTION_HOST.md`;
`docs/roadmap/items/item-330-…` and `item-67-…`; `src/weather/market/AGENTS.md`; and, on branch
`origin/codex/reward-epoch-design-20260920` (merging to master on 2026-09-21),
`docs/research/liquidity-reward-epoch-preregistration-2026-09-20.md` — the frozen treatment you are automating.

## 1. Goal

A pushed, fully tested branch on which one command can run a **Stage 2 "place-and-hold" session** end to end against a
fake exchange and the live public book, producing the sealed journal, the frozen reward prediction and the evidence
bundle — so that the only things between it and a live attempt are host qualification, the guarded merge, and the owner's
dated authorization.

## 2. Start from this — do not re-derive it (verify each by tracing one instance; a grep is not a trace)

- No code on `master` or on the maker candidate can rest a quote. The only submit is one far-from-mid order per sealed
  stage: `mm_live_lifecycle_probe.py` (~:778, priced one tick from the floor); `OfficialPolymarketGlobalAdapter.place_order`
  is single-token (`mm_official_adapter.py` ~:1257) and its capability is single-use and consumed before signing (~:1334).
- `STAGES = ("stage0","stage1_cancel_all","stage1_dead_man")`; the wrapper sealer rejects any rendered text containing
  "stage2" (`international_live_wrapper_sealer.py` ~:2013). Session ceiling 240 s
  (`international_live_session_runner.py` ~:57-59). Geoblock receipt lifetime 60 s. There is no re-quote loop.
- Ceilings are Python constants, not config: `MAX_STAGE1_ORDER_NOTIONAL = 10` (`mm_official_adapter.py` ~:26),
  `mm_live_pilot_cli.py` ~:541, `mm_live_candidate_cli.py` ~:49, an exact-equality check at `mm_live_lifecycle_probe.py`
  ~:356, the sealer's "exactly 10 pUSD", `mm_policy.py` ~:74-79, `market_making_live_pilot.py` ~:80. Six ratchet tests pin them.
- A reward-eligible two-sided 20-share quote reserves about 19.4 pUSD (worst case 15.8 on one leg), so the 10 pUSD
  ceilings make every quote reward-ineligible (EF §10a).
- Reward scoring, as already ported for the public-read tools: per-order score `S = size × ((v − s)/v)²` with `v` = max
  spread and `s` = distance from the adjusted midpoint; two-sided `Q_min`, with single-sided credit divided by 3 inside
  0.10–0.90; share = own / (own + competing). Reference implementation: `src/weather/**/reward_share_estimate.py`
  (merged 2026-09-20). Reward terms move intraday (a 20-share minimum became 100 within two hours on same-day bands);
  next-day bands keep 20 shares. The venue publishes per-condition terms at the public CLOB rewards endpoints.
- Pinned SDK (`polymarket-client` 0.6.0 contract overlay) already exposes `get_order_scoring`, `get_orders_scoring`,
  `list_user_earnings_for_day`, `get_total_earnings_for_user_for_day`, `list_user_earnings_and_markets_config`,
  `get_reward_percentages`. `master`'s own `/rewards/user/earnings` reader path is wrong, untested and never constructed.
- Taker fee is 0 on all 377,104 captured trades: treat maker rebates as zero; rewards are the whole thesis.
- Code lineage: the only code that has ever run live (Stage 0/1, 2026-09-06, zero fills) is the maker candidate, now
  reconciled onto the reliability stack as `origin/codex/maker-reconcile-20260920` @ `cb95ffe3b`. It carries four control
  relaxations made at the keyboard that day (report: `PR55_RECONCILE.md` content is summarised in §4 W0). It also carries
  `mm_liquidity_earnings_evidence.py` (validator, no I/O), `maker_reward_simulation.py`, `mm_pilot_capital.py`, and
  bootstrap schema v0.6 (artifacts incompatible with master's v0.4).
- Geographic eligibility is closed by owner statement; do not re-raise it, and do not touch geoblock or eligibility code
  except to call it more often. The home file-access tunnel is down for a whole live session (runbook rule).

## 3. The scope cut that buys the time

The pre-registered treatment allows up to four re-quotes in a 360-minute session. **Do not build the re-quote loop.**
Build **place-and-hold**: price both legs once from the live book, submit both, hold under heartbeat, and end the session
(cancel both, confirm zero open orders) on the first of: a fill on either leg; midpoint drift that takes either leg outside
the leave-alone window (1.0–3.0 c from the adjusted mid) or outside the venue's max spread; reward terms changing
(minimum size > 20, rate < 40); book one-sided; geoblock state change; heartbeat loss; session timeout; operator stop.
A day's test is then several short sealed sessions instead of one long one with a loop. This removes the re-quote state
machine, keeps "at most 2 submits per session", and lets two single-token adapters (one per leg, each with its own
single-use capability) replace a new multi-token adapter — confirm that by trace before relying on it.

## 4. Work packages (push after each; cheapest falsifier first)

- **W0 — base and the four relaxations (day 1).** Branch from `origin/codex/maker-reconcile-20260920`. If, by your start,
  `origin/master` does not contain `7efeb6eb3`, note it and continue — the reconcile branch already does. For each
  relaxation, find *why* it was relaxed on 2026-09-06 (item 67's attempt ledger, the stage1-pass docs branch) and then:
  (a) **restore** the typed stage and location/no-circumvention confirmations (remove the hardcoded `True`);
  (b) **restore** the isolated-wallet requirement — Stage 2 uses a dedicated wallet; keep `mm_pilot_capital.py` only as
  an accounting aid; (c) **restore** an expiry on the credential-comparison receipt — if the old lifetime was the
  obstacle, make it "this sealed session", never "forever"; (d) keep fee eligibility `>= 0` **only** behind a check that
  the venue reports fee 0 for the chosen condition, recorded in the journal. *Falsifier:* if restoring (a)–(c) makes the
  Stage 0/1 flow that passed on 09-06 unrunnable, stop and report exactly which step and why — that is an owner decision.
- **W1 — quote pricer (pure, day 1–2).** `reward_quote.py`: from book + reward terms + tick → adjusted mid, YES buy at
  mid − d, NO buy at (1 − mid) − d snapped **outward** to tick, d target 1.5 c; refusal reasons (would cross, mid outside
  0.20–0.80, spread > 6 c, min size > 20, tick ≠ 0.01, post-only impossible); expected per-minute score and share
  (many-competitor and single-competitor bounds). Golden tests must reproduce, to the cent, the 2026-09-20 dry-run rows in
  the pre-registration (e.g. mid 0.345 → YES 0.33 / NO 0.64, reserve 19.40). Property tests: never crosses, never inside
  1 tick of the touch on the wrong side, reserve ≤ per-band ceiling.
- **W2 — envelope profiles (day 2).** Replace the scattered constants with one immutable, hash-bound profile object:
  `stage1_v1` (every number exactly as today) and `stage2_hold_v1` (per-order 16, per-band 20, per-event 25, daily loss
  25, wallet 100, ≤ 2 submits, post-only, no naked sell, stop-on-fill). `stage2_hold_v1` is selectable **only** when a
  dated owner authorization naming it exists in both `STATE_OF_PLAY.md` and `config/international_live_execution_host.json`;
  absent that, selecting it raises. Keep the six ratchets and add their twins: the test suite must fail if any number in
  either profile changes, and must prove `stage1_v1` behaviour is byte-for-byte unchanged. *You add the profile; you do
  not write the authorization.*
- **W3 — session profile and in-loop controls (day 2–3).** A `stage2_hold` session profile: ceiling 45 minutes (not 240 s,
  not 360 min), heartbeat dead-man throughout, geoblock receipt refreshed inside the loop at ≤ 45 s with **fail-closed
  cancel-all** on any non-eligible or unreadable reading, tunnel-down preflight unchanged, reward terms and book re-read
  each minute through public endpoints, every end condition from §3 journaled with its trigger. Tests drive a fake clock
  through every end condition, including heartbeat loss mid-hold and a geoblock flip mid-hold, and assert cancel-all plus a
  zero-open-orders confirmation in each.
- **W4 — stage, template, sealer (day 3–4).** Add `stage2_hold` to `STAGES`, a wrapper template modelled on
  `stage1_cancel_all`, and a sealer stage that (i) admits the literal stage name instead of rejecting "stage2",
  (ii) requires the `stage2_hold_v1` profile hash, the selection-table hash and the condition id in the sealed scope,
  (iii) keeps every Stage 1 sealing rule. Typed literals stay. Tests: sealer rejects a stage-2 wrapper with a stage-1
  profile, a wrong condition, a stale selection table (> 30 min), or a missing authorization.
- **W5 — evidence readers (day 4).** Read-only wrappers over the pinned SDK calls listed in §2, constructed only inside a
  sealed session or an explicit post-session "collect" command, never at import; recorded-fixture tests only (build the
  fixtures from the SDK's own type definitions — you have no account data and must not obtain any). Feed
  `mm_liquidity_earnings_evidence.py`. Outputs: per-minute "is each leg scoring", end-of-session frozen prediction
  (`P_many`, `P_single`, journal SHA-256) written **before** any earnings read, and a next-day collect step that computes
  `k = paid / P_many` and applies the pre-registered verdict table verbatim.
- **W6 — dress rehearsal (day 4–5).** One command, `... stage2-hold rehearse --condition <id>`: real selection rule, real
  public book and reward-terms reads, **fake adapter** (accepts, rests, can be told to fill or reject), full journal,
  frozen prediction, evidence bundle. Run it on three different next-day bands and commit the redacted journals as
  fixtures. This is the acceptance test for the mission. Port the selection rule from the production host's
  `re1_select.js` semantics as written in the pre-registration (universe, filters, predicted ≥ 2.0, ranking, tie order,
  table hash); do not invent a new rule.
- **W7 — documents (day 5).** Runbook: a Stage 2 place-and-hold section with its end conditions and abort card; the
  portable-host runbook: what `stage2_hold` would need authorized (proposal text, clearly marked **not in force**);
  pre-registration: an RE-1A addendum recording the scope cut (place-and-hold, 45-minute sessions, several per day) and that
  the verdict table is unchanged; items 330 and 67; `src/weather/market/AGENTS.md`. Regenerate `active-backlog.md` with its
  generator and run its `--check`. Run `python -m weather.operations.agent_docs_audit`.

Tests: focused per package as you go, then the full suite through `scripts/ops/workstation_heavy.ps1` before the final
push. A second mission (`2026-09-79a`, research) may be running on this workstation; the wrapper's mutex serialises heavy
commands — wait for it, do not bypass it.

## 5. Boundaries (in addition to the delegation contract §2, which binds in full)

- **No live action of any kind.** No order, cancel, signature, authenticated call, wallet, key, `.env`, `*.cred`, `*.key`,
  `*.pem`, or credential store — not to read, not to test. No `RequireLiveSdkContract` run against the venue.
- International Polymarket only. No Polymarket US path. No paid weather source.
- Never build anything that masks, spoofs or routes around location; never weaken, stub or bypass geoblock, tunnel,
  heartbeat, post-only, no-naked-sell, stop-on-fill, typed-confirmation or wallet-isolation checks — in code **or in tests**
  (a test may fake the *exchange*, never the *control*).
- No unattended or scheduled trading path; no scheduled task; nothing that starts at import.
- You do not write an owner authorization, flip a default to the stage-2 profile, or edit
  `config/international_live_execution_host.json` to grant anything. You may add the *schema* for a stage-2 grant.
- Files you own: `src/weather/market/**` files named in §4 and new files beside them, their tests, the documents in W7.
  Touch no capture, collection, model or settlement module. If you need one, report the need.
- Commit and push your branch freely; never merge to `master`; never rewrite history; never delete a branch or another
  task's worktree.

## 6. What would falsify this mission

- W0: the restored controls make the 09-06 Stage 0/1 flow unrunnable ⇒ the fast path is blocked on an owner decision, not
  on code. Report and stop W0 there; continue W1–W3, which do not depend on it.
- §3: two single-token adapters cannot hold two live orders in one sealed session without a control change (capability,
  nonce, heartbeat scope) ⇒ say so, and price the real multi-token adapter instead of forcing it.
- W1: the golden rows cannot be reproduced to the cent ⇒ the public-read tools and the repository scorer disagree; that
  must be resolved before any money rests on the pricer.
- W3: the venue's post-only or heartbeat semantics (from the SDK's own types and documentation) do not allow a held quote
  to be cancelled by dead-man within one heartbeat interval ⇒ place-and-hold is not safe as specified.
- W5: the SDK earnings calls cannot attribute a payout to one condition and one day ⇒ the verdict needs a dedicated wallet
  (already recommended) and the report must say the evidence rests on that isolation.
- If the owner's manual test (RE-1M, target 2026-09-24) returns NOT_PAID, this build loses its reason; check
  `STATE_OF_PLAY.md` at the start of each day and stop if it says so.

## 7. Branch, report, handback

- Branch: `codex/stage2-hold-build-20260921`, from `origin/codex/maker-reconcile-20260920`.
- Report: `docs/roadmap/agent-report-2026-09-80a-workstation-build-the-resting-quote-session.md`, per contract §5:
  verdict first in bold; what each package proves and with which tests; **per-file roll verdict** (expect the reconcile
  base to be roll-sensitive — list which of *your* files enter a capture closure; the aim is none); what was NOT done
  (no live call, no credential, no authorization, no merge); exact reproduction commands; commit hash.
- Also deliver `docs/operations/stage2-hold-owner-authorization-draft.md`: the exact text and config diff the owner would
  have to approve, the four-relaxation disposition you implemented with the reason for each, and a one-page abort card.
- What happens after you: the production agent qualifies the branch on the capture host overnight (bounded suite), lands
  it through the guarded merge in a quiet window, the owner re-runs attended Stage 0/1 on the landed code, and only then
  can a dated Stage 2 authorization be written. Make each of those steps cheap: small commits, no flaky tests, no test that
  needs network, short temp paths.
