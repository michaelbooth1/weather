# 242. Decisive Model Proof Packet And Gate Stack Ratchet [COMPLETE 2026-06-22 - WEATHER-ONLY PROOF PACKET AND RATCHET LIVE]

Goal: collapse the current overlapping model-readiness gates into one
decision-grade proof packet for the active weather-only model, so future work
has to prove or reject the model on the hard slices instead of adding more
diagnostics.

Source: `docs/roadmap/audits/closed-roadmap-model-progress-audit-2026-06-22.md`.
The audit found that most concrete technical gaps already have active roadmap
owners, but the remaining direction risk is volume and complexity: the roadmap
has many closed gates and many active gates, which can make it easier to add
diagnostic structure than to force the active model through a decisive
market-relative proof.

Why this matters: the project now has enough evidence infrastructure to block
bad claims. The next risk is using that infrastructure as a substitute for a
clear decision. Model work should converge on a single packet that says which
markets can promote, which stay shadow, which are blocked, and exactly which
slice prevents each blocked market from clearing.

## Design

1. Define a single `weather_only_model_proof_packet` artifact that joins the
   active artifact identity, promotion refresh, hourly gate, ten-minute gate,
   exact-band/distance-zero gate, bottom-location gate, source/missingness
   gate, live-forward evidence state, and broad-claim gate on the same corpus.
2. For every active model-repair item, require its acceptance evidence to point
   to the proof-packet field it changes. Items that only add diagnostics without
   changing a proof-packet blocker stay `PARTIAL` or `OPEN`.
3. Emit one market disposition table: `PROMOTE`, `SHADOW`, `BLOCK`, with the
   first blocking slice, delta versus current, delta versus market, and whether
   the evidence is active-artifact, active-replay-contract, row-export
   surrogate, or diagnostic-only.
4. Add a gate-stack ratchet: new model-readiness gates must either replace an
   existing proof-packet field or be explicitly marked diagnostic-only until
   they prove they change a promotion decision.
5. Keep market-informed and trading/taker proof packets separate. CLOB overlays
   and taker profitability can inform quote-risk or trading decisions, but they
   cannot satisfy the weather-only proof packet.

- [x] Specify the proof-packet schema and required input artifacts.
- [x] Generate the proof packet from the current active reports.
- [x] Add a roadmap/backlog check that active model items reference a
  proof-packet blocker or mark themselves diagnostic-only.
- [x] Add a ratchet report listing duplicate, superseded, or diagnostic-only
  gates that should not drive the next work order.
- [x] Update the actionable work order to use proof-packet blockers as the
  ordering source for weather-model work.

Acceptance: one canonical weather-only proof packet exists; broad model claims
and per-market promotion decisions read from it; active model-repair items map
to concrete packet blockers; and the roadmap no longer treats new diagnostic
reports as progress unless they change or retire a packet blocker.

Related: items 48, 147, 160, 178, 219, 224, 228, 230, 233.

## Completion - 2026-06-22

Implemented `weather.reporting.weather_only_model_proof_packet` with schema
`weather_only_model_proof_packet_v0.1`. The generated artifacts are:

- `data/backtest/weather_only_model_proof_packet.json`
- `data/backtest/weather_only_model_proof_packet_report.md`

The current packet is intentionally fail-closed: status `BLOCK`, 11 blocking
gates, 0 promote markets, 3 shadow markets, and 8 blocked markets. The first
blocker is `gates.active_artifact_identity`: the active pooled-F artifact is
loaded but stamped with `toronto_feature_store_v1.13` while runtime uses
`toronto_feature_store_v1.14`.

The packet now joins active artifact identity, promotion refresh readiness,
hourly, 10-minute, exact-band/distance-zero, bottom-location,
source/missingness, live-forward, broad-claim, served-distribution, positive
daily-first, and lane-separation gates. Market dispositions expose the first
blocking slice, delta versus current, delta versus market, and evidence basis.

The roadmap ratchet is live in the packet: active model-repair items 48, 147,
160, 178, 219, 224, 228, 230, and 233 reference concrete proof-packet fields or
are explicitly diagnostic-only. The actionable work order now cites the proof
packet and orders weather-model work from packet blockers instead of standalone
diagnostic reports.

Verification:

- `python -m weather.reporting.weather_only_model_proof_packet`
- `python -m pytest tests\reporting\test_weather_only_model_proof_packet.py tests\operations\test_schema_registry.py -q`
