# 68. Information-Event Calendar And Quote-Pull Gates [NEW - OPEN]

Goal: prevent stale quotes from resting through scheduled high-information
events that are not captured by source-freshness checks alone.

Why this is missing: item 42 reacts to live observation changes after they
print, and item 45 gates stale sources/books/watchers. Market-making also needs
advance knowledge of predictable information events: forecast model releases,
expected observation print windows, market open/close transitions, reward
campaign changes, settlement cutoffs, and platform status changes.

- [ ] Build a per-market event calendar for WU/METAR/SWOB expected print
  windows, NWP release cycles, forecast archive update windows, market
  open/close/resolution timing, reward campaign epochs, and known platform
  maintenance/status events.
- [ ] Let `mm_policy` consume the calendar and pull, widen, or suppress quotes
  in configurable pre/post windows with explicit reason codes.
- [ ] Persist event-calendar state and quote-pull decisions in quote tapes,
  paper reports, and live run summaries.
- [ ] Score opportunity cost and avoided toxicity in replay/live-forward paper
  so event windows can be narrowed only when evidence supports it.
- [ ] Show the next scheduled information event and current event-gate state in
  the market-making cockpit.
- [ ] Require any exception to event-gated quote pulling to cite a passing
  paper/live-forward slice and a bounded risk cap.

Acceptance: no live-forward or live quote rests through a known high-information
event unless the policy explicitly permits that event class and the paper
evidence shows the exception is safe after markout, fees, rewards, and
operational buffers.
