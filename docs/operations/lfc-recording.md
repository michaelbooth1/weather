# LFC recording evidence

Status: canonical implementation guide. Read when recording venue settlement,
scoring, or incentive evidence for the live-fill calibration pilot. This guide
grants no live-session authority; the [pilot runbook](INTERNATIONAL_MM_LIVE_PILOT.md)
owns the execution gates.

The ledger genesis is bound to `GENESIS_BUDGET_PUSD`; `CAP_PUSD` independently
controls the campaign risk gates. The recording-only checkpoint preserves the
pinned money and session constants. A cap below committed L refuses at start.
An explicit session cap can lower the campaign cap and cannot raise it.

## Venue settlement

Run `python -m weather.market.lfc_settlement_record --condition <condition-id>`
from the analysis lane after resolution; repeat while pending. `--condition`
is repeatable; `--root` overrides the normal pilot root. The verified campaign
ledger supplies leg-intent token identities; local settlement labels are never
read. The public Data API v2 resolution and token
reference responses are retained verbatim with SHA256 and observation time.
Payout slots identify the winner; prices are ignored. Split payouts have no
invented binary winner. A resolved lifecycle without payout evidence remains
pending; missing resolution remains unknown.
For migrated markets, only the reference pair containing the campaign's traded
token IDs is selected. A failed match preserves the raw read under `pending/`
with a reason code. Analysis refuses a leg outside the recorded pair and a
missing settlement directory.

Pending reads go to `settlement/pending/<condition>/<timestamp>.json`;
terminal reads create `settlement/<condition>.json` once. An existing final
file refuses before a network read. Analysis `--settlement` now accepts this
directory; legacy winner maps are refused. The reader verifies response hashes,
condition scope and the derived winner before admitting evidence.

## Reward reads

The owner runs `python -m weather.market.lfc_cli rewards-record --date YYYY-MM-DD`
on UTC D+1 and again D+2; no Scheduler task is installed. `--root` overrides
the pilot root; `--signature-type 3` selects a deposit wallet (default 2).
The command derives the maker and traded conditions from the verified LFC
ledger. It uses the existing accrual collector through the reader's L2-only
GET transport, without constructing a private-key SDK client. This reuses
transport code and does not call or reconfigure the running wallet reader.
The pinned SDK reward models normalize decimal and date fields before the
existing accrual collector sees them.
R3 reads the owner's existing `POLYMM_API_KEY`, `POLYMM_API_SECRET`,
`POLYMM_API_PASSPHRASE`, `POLYMM_WALLET_ADDRESS` and `POLYMM_FUNDER_ADDRESS`
process settings. It opens no `.env` and needs no reader token or private key.
The endpoint and chain are fixed; supplied host/chain settings must match.

Create-only `rewards/<D>-d1.json` and `-d2.json` retain per-condition accruals,
response hashes and raw evidence, and cursor-paginated public v2 REWARD cash
candidates from D+1 to the observation time. Cash credits have no official
earned-period reference; neither candidates nor accruals are labelled verified
payment. Incomplete reads retain failure evidence rather than completed zero.
The account must match the ledger genesis. New passes start only on D+1/D+2;
an unfinished pass can resume after UTC midnight. No record nets credits against L.

## Rebates

The same owner command records public v2 `MAKER_REBATE` activity from UTC D
through the observation time. Rows are account-wide candidates; condition
membership is recorded, never treated as earned-period proof. Every nonzero
`usdc_size` is flagged; unreadable amounts and failed reads are flagged too.
No rebate is netted against L, realised loss or reward accruals.

The D+1 file is `rewards/<D>-rebate.json`; D+2 uses `<D>-d2-rebate.json`
so both observations survive without overwriting. If an interrupted command
left one of the reward/rebate files, rerun it to record only the missing file;
existing evidence must match the ledger account, conditions, date and pass.
Raw response hashes, completed activity walks, derived accrual amounts and
rebate flags are verified before a partial pass resumes. A single UTC cutoff
binds both files even when reads cross midnight; observation times follow the
reads. Activity request bounds and bounded response sizes are retained.
Completed pairs refuse before credentials load. Failed reads remain immutable;
reruns create `-retry-001.json`, `-retry-002.json`, etc., for the failed component.
The latest attempt is validated rather than skipping corrupt newer evidence.
The default selects the pass due on the current UTC day; an unfinished D+1
never blocks D+2. Use `--pass d1` or `--pass d2` to retry that existing pass
after midnight, retaining its names and cutoff. A zero-width REWARD window is
explicitly incomplete. Incomplete reads return 2. The command prints actual output
paths, pass, completeness and rebate flags.

Publication serializes strict JSON, fsyncs a unique same-directory attempt and
atomically publishes without replacing an existing final file. Failed attempts
remain for diagnosis. Duplicate JSON keys and nonfinite numbers are refused;
raw responses and failed-read receipts remain available. Completed accrual
records replay paired requests/responses through a terminal cursor and bind
each derived row to its actual response page.

For a corrupt legacy final file, `--recover-corrupt` on either recorder creates
a separate replacement and immutable recovery manifests bound to the original
and replacement hashes. It never overwrites the original. Conflicting or
unvalidated replacements refuse; ordinary retries never silently skip corruption.

R1/R3/R4 are read-only commands usable from a clean branch worktree without a
live-session pin. M and R2 affect live-session code and retain its pin gates.

## Scoring

The attended controller makes one batched scoring read each minute, before
the public snapshot, for all active order IDs. Each order gets a `scoring` row
with `band` (the condition ID), `order_id`, a boolean and `observed_at_utc`.
An exception or incomplete response records `scoring_missed` and marks evidence
incomplete while the session continues. Accrual stays on its separate
half-hour cadence. Immediate post-time scoring reads keep their existing
request/response journal shape.

## Update when

Update with recorder commands, evidence formats, provenance validation or cadence.
