# LFC recording evidence

Status: canonical implementation guide. Read when recording venue settlement,
scoring, or incentive evidence for the live-fill calibration pilot. This guide
grants no live-session authority; the [pilot runbook](INTERNATIONAL_MM_LIVE_PILOT.md)
owns the execution gates.

The ledger genesis is bound to `GENESIS_BUDGET_PUSD`; `CAP_PUSD` independently
controls the campaign risk gates. The recording-only checkpoint preserves the
pinned money and session constants. A cap below committed L refuses at start.
The compatibility name `BUDGET_PUSD` is not a ledger identity setting.

## Venue settlement

Run `python -m weather.market.lfc_settlement_record --condition <condition-id>`
from the analysis lane after resolution; repeat while pending. `--condition`
is repeatable; `--root` overrides the normal pilot root. No ledger or local
settlement labels are read. The public Data API v2 resolution and token
reference responses are retained verbatim with SHA256 and observation time.
Payout slots identify the winner; prices are ignored. Split payouts have no
invented binary winner. Missing resolution remains unknown.

Pending reads go to `settlement/pending/<condition>/<timestamp>.json`;
terminal reads create `settlement/<condition>.json` once. An existing final
file refuses before a network read. Analysis `--settlement` now accepts this
directory; legacy winner maps are refused. The reader verifies response hashes,
condition scope and the derived winner before admitting evidence.

## Update when

Update with recorder commands, evidence formats, provenance validation or cadence.

## Scoring

The attended controller makes one batched scoring read each minute, before
the public snapshot, for all active order IDs. Each order gets a `scoring` row
with `band` (the condition ID), `order_id`, a boolean and `observed_at_utc`.
An exception or incomplete response records `scoring_missed` and marks evidence
incomplete while the session continues. Accrual stays on its separate
half-hour cadence. Immediate post-time scoring reads keep their existing
request/response journal shape.
