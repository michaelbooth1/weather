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

## Reward reads

The owner runs `python -m weather.market.lfc_cli rewards-record --date YYYY-MM-DD`
on UTC D+1 and again D+2; no Scheduler task is installed. `--root` overrides
the pilot root; `--signature-type 3` selects a deposit wallet (default 2).
The command derives the maker and traded conditions from the verified LFC
ledger. It uses the existing accrual collector through the reader's L2-only
GET transport, without constructing a private-key SDK client. This reuses
transport code and does not call or reconfigure the running wallet reader.

Create-only `rewards/<D>-d1.json` and `-d2.json` retain per-condition accruals,
response hashes and raw evidence, and cursor-paginated public v2 REWARD cash
candidates from D+1 to the observation time. Cash credits have no official
earned-period reference; neither candidates nor accruals are labelled verified
payment. Incomplete reads retain failure evidence rather than completed zero.
The account must match the ledger genesis. Existing outputs refuse before
credentials load; dates outside D+1/D+2 refuse. No record nets credits against L.

## Scoring

The attended controller makes one batched scoring read each minute, before
the public snapshot, for all active order IDs. Each order gets a `scoring` row
with `band` (the condition ID), `order_id`, a boolean and `observed_at_utc`.
An exception or incomplete response records `scoring_missed` and marks evidence
incomplete while the session continues. Accrual stays on its separate
half-hour cadence. Immediate post-time scoring reads keep their existing
request/response journal shape.
