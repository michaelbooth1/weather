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
| 2026-09-23 | Testing-wallet guard raised from 100 to 200 pUSD | RE-1 | 23b addendum | wallet at most 100 |
| 2026-09-23 | RE-1 cap raised from 3 sessions/6 attempts (an agent default) to 10 sessions/20 attempts | none after 2026-09-30 | 23b addendum | 3-session cap |
| 2026-09-24 | One multi-domain market maker; new maker code domain-neutral behind plugins | strategy | forward plan decision 5 | — |
| 2026-09-24 | Fail-forward rules and the pre-approved recovery table; production PC in bypass permissions | operations | Operations agent role §6 | — |
| 2026-09-24 | No pre-registered pooled RE-1 verdict and no migration gates; the owner judges | RE-1, migration | second-opinion audit | — |
| 2026-09-24 | RE-1 selection amendment: local T+1/T+2 and at least max(75, size) displayed depth each side | sessions 9-10 | 23b addendum; tip `6b5fde587` | empty-band selection |
| 2026-09-24 | Short confirmation `go <6 hex>` | RE-1 | tip `a0967b78a` | long phrase |
| 2026-09-24 | System Restore capped at 2 GB; Windows Search disabled; Defender excludes `data\`; paper maker roll paused (retiring the old maker) | production host | storage plan; host audit | — |
| 2026-09-24 | Model and consider all inventory options (holding, selling, resting sells, merge); no code change now | research | inventory review | — |
