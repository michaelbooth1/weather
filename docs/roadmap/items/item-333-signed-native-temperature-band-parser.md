# 333. Signed Native Temperature Band Parser [PARTIAL]

Goal: preserve signed native-unit settlement bands through serving, ledger
selection and maker/taker scoring. Serves Q-09.

Owner/package: `weather.units`, with model, backtesting and market consumers.

Source: [mission 95b](../workstation-handoff-2026-09-95b-signed-band-parser-onto-master.md).

Why this matters: unsigned extraction can select the wrong winter settlement band.

Acceptance: signed and positive bands agree across consumers, with unchanged
recorded positive-band output and guarded production adoption.

- [x] Share one complete-label parser for signed ranges and open thresholds.
- [x] Preserve zero endpoints, native units, probability mass and label bytes.
- [x] Reject inverted, mixed-unit and contradictory bands without manufacturing outcomes.
- [x] Replay tracked Toronto labels against the pre-repair serialized output.
- [ ] Production qualification, current closure verdict and guarded adoption.

## Implementation

The parser accepts whole-degree singles, hyphen or `to` ranges, Unicode minus
and dash spellings, and below/under/lower or above/higher thresholds. It never
converts units or extracts numbers from arbitrary question prose. Numeric row
endpoints remain authoritative for legacy labels that omitted a range's upper
endpoint; contradictory explicit values fail closed. WU cutoff and observed-high
logic are unchanged.

Branch: `codex/signed-band-parser-20260924`. Minimal parser-only extraction from
`016e1c92c006c37eb321e9a549eb3e83b1f19fff`, extended for the handoff's `to` spelling.
Verification evidence: [95b report](../agent-report-2026-09-95b-signed-band-parser-onto-master.md).
