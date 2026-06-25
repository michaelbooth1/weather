# 311. Taker Evidence-Starvation Classification And Upstream Liveness Gate [OPEN 2026-06-24 - LATEST-TICK STARVATION STILL PASSES LIVENESS]

Goal: make taker daily-roll health and trading evidence fail closed when the
current run is starved of latest-tick scoring inputs, even if the taker process
is alive and cumulative artifacts keep refreshing.

Source: the 2026-06-24 taker run
`data/taker_runs/2026-06-24/taker-20260624-d11521e2/` produced 19,184 active
rows, zero fills, zero spend, and 147,906 counterfactual rows with zero
would-buy rows across every strategy. The generated run report flagged
`latest tick rows=0`, zero-trade root cause `crashed_before_scoring`, first
failing gate `scoring`, and remediation
`python -m weather.market.market_microstructure ensure`. At audit time, the
regular snapshot loop was `DEAD` after a stale-code exit around 14:07 EDT and
CLOB capture was `DEAD` with last books around 11:39 EDT, while the taker
daily-roll status still showed an alive process and artifact liveness `PASS`.

Why this matters: zero-buy days are valuable only when they can be classified as
risk-clean no-edge or intentional policy guardrails. A run with empty latest
ticks and dead upstream books/snapshots produces little strategy-quality
evidence, but today it could still look alive at the taker supervisor layer and
create a misleading no-trade/counterfactual summary.

Why it is not already covered: item 152 covers disk, discovery, and broad
preflight fail-closed behavior; item 272 covers stale useful-artifact liveness;
item 303 covers post-settlement zero-fill canonicalization; and items 157, 161,
and 307 own snapshot/CLOB cadence and loop stability. None makes latest-tick
scoring starvation a first-class taker liveness gate before settlement, or
distinguishes zero counterfactual would-buys caused by policy rejection from
zero would-buys caused by an empty scoring tape.

## Design

1. Add latest-tick scoring health to taker daily-roll liveness: latest tick row
   count, newest snapshot timestamp, scoring root cause, first failing gate, and
   countability status.
2. Treat `latest_tick_rows=0`, `crashed_before_scoring`, stale model inputs,
   stale books, dead CLOB capture, or dead regular snapshots as restart/blocking
   conditions unless the run is explicitly tagged as a diagnostic.
3. Split zero-trade and zero-would-buy classification into
   `risk_clean_no_edge`, `policy_guardrail_no_trade`, `infra_starved_snapshot`,
   `infra_starved_clob`, `latest_tick_empty`, `scoring_crash`, and
   `market_unresolved_pending`.
4. Surface upstream dependency status in the taker report: snapshot/CLOB state,
   last-good timestamps, heartbeat age, first failing dependency, and the
   concrete repair command.
5. Mark counterfactual evidence as uncountable when the no-would-buy result is
   caused by latest-tick starvation rather than actual policy rejection.
6. Feed the classification into trading evidence, daily learning, and operator
   status so an alive process cannot mask an uncountable active day.

- [ ] Add latest-tick scoring health fields to taker run summaries and
  daily-roll status.
- [ ] Fail or restart taker daily-roll liveness when latest-tick scoring is
  empty or upstream snapshot/CLOB dependencies are dead.
- [ ] Add zero-trade and zero-would-buy root-cause classes that separate
  policy no-edge from input starvation.
- [ ] Include upstream dependency state, last-good times, and remediation
  commands in the taker operator report.
- [ ] Add a regression fixture for the 2026-06-24 shape: alive taker PID,
  artifact liveness `PASS`, latest tick rows `0`, snapshot loop `DEAD`, and
  CLOB capture `DEAD`.
- [ ] Collect a future active-day proof where a zero-buy taker run is either
  classified as risk-clean with fresh latest ticks or fails closed as input
  starvation before end-of-day review.

Acceptance: a taker process that is alive but has empty latest-tick scoring or
dead upstream snapshot/CLOB dependencies is marked restart/blocking and
non-countable in daily-roll status, run reports, trading evidence, and daily
learning. A valid zero-buy day remains countable only when latest ticks are
fresh, upstream dependencies are healthy, and the no-trade/no-would-buy
classification is policy or risk driven rather than infrastructure driven.

Related: items 152, 157, 161, 162, 238, 256, 272, 273, 303, 307.
