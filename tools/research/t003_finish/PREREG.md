# T085 completion pre-registration

Frozen before reading remaining book payloads. Timestamp is in PREREG.sha256's companion receipt.

MEASURED historical state: T003's prompt/PLAN and final findings did not register a
T3 kill rule. G2 was "any executable arbitrage after fees, depth and latency";
the final report explicitly says no T3 preregistration was drafted or frozen.
This is a new completion registration, informed by the already-read 393 days,
not a retrospective claim that those days were blind.

Hypothesis/direction: completing the parked scan will find no demonstrated
executable net-positive structural arbitrage. One policy arm: T003's q10 ANY,
the winner over its eight unchanged routes. q1/q5/q100 and 5/30/60-second windows
remain descriptive diagnostics; headline source window stays one second.
Fee/depth arithmetic, eligibility, 1e-8 positivity threshold, retained rows,
120-second episode join and consecutive-capture alternative remain unchanged.
No source normalization, row skipping, imputation, new source or fetching.

Data: fixed T003 inventory.json SHA256
39dcdebcb1cd67c8cb9b5a3664b07327dff3bef5e9409dbab30f1f2b0378fde3.
Only order_books_summary.csv from tapes-toronto-0801-0929 and tapes-us-0801-0929
under C:\t\recopy-20261106. Target dates 2026-08-01..2026-09-29 inclusive.
Metadata inventory count: 720 permitted event-days, 60 target dates, 12 cities;
180 of the original 900 dates are 09-30..10-14 and MUST NOT be opened.
The task's requested 900 permitted days do not exist in that fixed inventory.
No outcomes, labels, own-session records, expansion books or maker shadow.

Parser: strict CSV syntax, exact original header allowlist and row width,
1,048,576-character field AND logical-record bound, strict UTF-8. A malformed
or over-bound source stops without counting that event. Raising the parser
limit does not certify the failed event's semantic integrity.

Sanity gate before remaining-day computation: rescan the first 393 input days;
require exact equality of every deterministic per-event JSON value (only
version, script hash, elapsed time and artifact manifest excluded), plus
byte-identical retained gzip/hour/episode artifacts. Source hashes must match.
Reconcile original rows 32,267,972, captures 1,466,726, q10 ANY 16 positive
captures and 10 consecutive episodes. Any discrepancy = DESCRIBE/incomplete,
no kill or remaining-day computation. No copying old outputs as reproduction.

Metric: q10 ANY conservative fee-net positive captures at <=1 second, deduped
episodes and positive event-days per target date. Preserve complete counters
and source hashes. Date-clustered percentile 95% interval for the mean daily
positive-event-day fraction (2,000 resamples, seed 20261110) is descriptive;
report effective dates and no extrapolation to forward dates. No edge test.

Kill rule: KILL only the q10 one-second SUMMARY SCREEN on this finite permitted
inventory if every event completes, reproduction passes, and zero conservative
positive captures occur. If any occur, DESCRIBE (G2 execution unverified unless
T003's historical group/fee/status, raw-ladder and measured latency proof exists).
Incomplete/invalid inputs -> DESCRIBE, never a zero or a kill. No evidence here
can authorize trading, promotion, T3 freeze or a forward edge claim.

Reuse: DEV_WINDOW_LEDGER.md at base 73140b20eed0f81c8fa26bb5faf6defcb269533a
publishes at least 214; conservatively at least 215 including this one arm.
Proposed ledger row belongs in REPORT.md; canonical ledger edited by master only.

Execution: master must GO the exact committed path/hash per COMMON.md; no heavy
run before that. Canonical workstation_heavy wrapper, <=20-minute chunks,
HOLD check, memory/disk/commit guards, no heavy 09:00..19:00 Toronto. Fresh
outputs under T085/out, original T003 evidence immutable.
