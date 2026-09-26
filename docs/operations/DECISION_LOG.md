# Owner decision log

- **Owns:** the dated history of owner decisions (append-only, newest last).
- **Read when:** you need to know when and why the owner decided something, or whether a decision was later superseded.
- **Do not use for:** which decisions are in force today (STATE_OF_PLAY "Current authority" owns that), or detail that
  belongs to the linked source.

Append a row in the same commit that records the decision in STATE_OF_PLAY. Never edit an old row; supersede it with a new
row that names the old one.

| Date | Decision | Scope / expiry | Source | Supersedes |
| --- | --- | --- | --- | --- |
| 2026-09-19 | Implementation authority toward live testing; no live trading except RE-1 | standing | STATE_OF_PLAY | — |
| 2026-09-19 | Eligibility resolved; home tunnel down during live sessions | standing | STATE_OF_PLAY | — |
| 2026-09-21 | RE-1 approved as an attended workstation script the owner starts personally | none after 2026-09-30 | mission 84a | — |
| 2026-09-21 | Model work unpaused; pre-register before scoring | standing | STATE_OF_PLAY | — |
| 2026-09-22 | RE-1 capital is a learning budget; hurdle H = 1.00 net/day per 100 deployed | RE-1 | pre-registration | — |
| 2026-09-23 | RE-1 addendum (BELOW_PAYOUT_MINIMUM, either asset, graded adequacy); 10-31 is an owner review | RE-1 | liquidity-reward-epoch-addendum-2026-09-23 | — |
| 2026-09-23 | No second disk; off-PC Drive archive as needed | standing | storage plan | — |
| 2026-09-23 | Two pillars: forecast (timing first) and maker rewards with quotes pulled around information | strategy | forward plan | — |
| 2026-09-23 | `R` frozen as a rule; passive maker-evidence capture approved; K2 floor deferred | research | forward plan decisions 1-3 | — |
| 2026-09-23 | Payment tests may use any band and size within the testing wallet | RE-1 | forward plan decision 4; 84h | — |
| 2026-09-23 | Production PC belongs to the agent; non-project files may be deleted | standing | storage plan | — |
| 2026-09-23 | Testing-wallet guard raised from 100 to 200 pUSD | RE-1 | 23b addendum (on the RE-1 branch) | wallet at most 100 |
| 2026-09-23 | RE-1 cap raised from 3 sessions/6 attempts (an agent default) to 10 sessions/20 attempts | none after 2026-09-30 | 23b addendum (on the RE-1 branch) | 3-session cap |
| 2026-09-24 | One multi-domain market maker; new maker code domain-neutral behind plugins | strategy | forward plan decision 5 | — |
| 2026-09-24 | Fail-forward rules and the pre-approved recovery table; production PC in bypass permissions | operations | Operations agent role §6 | — |
| 2026-09-24 | No pre-registered pooled RE-1 verdict and no migration gates; the owner judges | RE-1, migration | second-opinion audit | — |
| 2026-09-24 | RE-1 selection amendment: local T+1/T+2 and at least max(75, size) displayed depth each side | sessions 9-30 | 23b addendum (on the RE-1 branch); tip `6b5fde587` | empty-band selection |
| 2026-09-24 | Short confirmation `go <6 hex>` | RE-1 | tip `a0967b78a` | long phrase |
| 2026-09-24 | System Restore capped at 2 GB; Windows Search disabled; Defender excludes `data\`; paper maker roll paused (retiring the old maker) | production host | storage plan; host audit | — |
| 2026-09-24 | Model and consider all inventory options (holding, selling, resting sells, merge); no code change now | research | inventory review | — |
| 2026-09-24 | RE-1 raised by 20 sessions (10 -> 30); attempt cap 60 (agent default, two per session) | none after 2026-09-30 | 23b addendum (on the RE-1 branch); tip `622e25bfb` | 10 sessions / 20 attempts |
| 2026-09-25 | Wallet reader is authenticated but read-only (L2 key from the workstation `.env`, never the private key; GET allowlist, no cancel/order/heartbeat) and served on the home LAN to the production PC only (token + IP allowlist + firewall); the owner starts it | workstation, RE-1 | handoff 100a (revised) | keyless public reader |
| 2026-09-25 | 89a Clarification 12: panel B 2026-09-25..2026-10-08 (14 dates) scored once after 10-08; panel A result (INCONCLUSIVE, 0/480) stands; no pooling | research | fill-toxicity pre-registration Clarification 12 (`0df126491`); handoff 100c | panel A only |
| 2026-09-25 | Campaign accounting from recorded wallet reads only (no estimates); baseline `data/wallet_ledger/baseline-2026-09-25T173814Z.json` (cash 102.968694, Chicago 68-69 Sep 25 75 YES held, no open orders) | RE-1 | wallet reader snapshots | marked/estimated campaign P&L |
| 2026-09-25 | Chicago 68-69°F Sep 25 YES (75 @0.43) held to settlement | RE-1 inventory | positions review | resting sell |
| 2026-09-25 | 88a critical disk stop lowered from 50 to 40 GiB (below the suite floor) | 88a | branch `codex/maker-evidence-floor-20260925` @ `d0e06394c` (lands tonight) | 50 GiB |
| 2026-09-25 | **All live trading paused** (incl. RE-1) while the informed maker foundation is built; the reward formula is considered validated by RE-1 | standing until the owner resumes | owner, this conversation | RE-1 30 sessions / 60 attempts |
| 2026-09-25 | Build an informed, domain-neutral market maker: model fair value flows into a maker core that adjusts on information; domain plugins (weather first, YouTube view model next), well encapsulated | strategy | owner; design audit pending | blind reward quoting |
| 2026-09-25 | Approved: T+1/T+2 own-information fair value; test (and disable if not earned) the afternoon centering stage; autumn PIT collection so retraining is possible this season | model | model-lanes audit 2026-09-25 | — |
| 2026-09-25 | Informed maker design approved: `src/maker_core/` package; v0 centre = market mid (fair value sets width, asymmetry, size, veto); contracts v0.1 published now, additive-only; paper maker retired; Stage 2 hold build frozen as fixtures; shadow on the workstation; caps and go-live hurdles decided at Phase 2 | maker | [informed maker design](informed-maker-design-2026-09-25.md); handoff 110a | 90a location `src/weather/market/maker/` |
| 2026-09-25 | GitHub clean-up approved per the hygiene review: close superseded PRs (handoff 110d), archive-tag then delete stale branches, push never-pushed branches, delete merged remote branches after PR closure | repository | github-hygiene-review-2026-09-25 | — |
| 2026-09-25 | Retire the storage-recovery stack (#45, #64, #66, #67, #71, #72) and qualification v2 (#69, #70); preserve executed sources as `deployed/*` tags | repository | owner, this conversation | land as stacks |
| 2026-09-25 | RE-1 PR chain (#78, #82-#85) closed after RE-1 ends 2026-09-30; small PRs #29, #30, #54, #55, #65, #68 triaged by the production agent (#86, #90, #93 stay open) | repository | owner, this conversation | — |
