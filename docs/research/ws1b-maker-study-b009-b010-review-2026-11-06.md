# WS-1(b): B009 fixes and B010 re-check

Historical method-review delta to the [first review packet](ws1b-maker-study-review-2026-11-06.md).
This records code corrections and small-check evidence, not a market-day result.
The master prohibited bulk use of the old pin; execution of the revised pin
still requires a separate GO under COMMON.md.

## B009 corrections

1. Execution coverage is checked for each live quote window, starting no earlier
   than the event's local midnight and the tape's first record. Windows must be
   bracketed by recorded prints without an inter-print gap above the declared
   cap. This is a print-coverage proxy, not proof of uninterrupted recording.
   Future-day quotes are reward-only; their fills, net, settlement P&L, N and
   power remain unset. No mixed 88a trades journal was introduced.
2. Every f case, settled counterfactual, N and power is computed at both reward
   multipliers. The reduced-reward case is planning; the full-reward case is
   optimistic. The multipliers are sensitivities, not measured responses.
3. Queue ahead counts displayed size at the exact quote price. Better levels
   are no longer charged again against only at-price-or-worse traded volume.
4. Day outputs are staged as partial files. The final receipt is published last
   and binds their hashes. Execution checks that receipt before reading prices;
   orphan or tampered files cannot become valid inputs. Event outputs use the
   same final-marker discipline. Cleanup closes gzip and SQLite resources.
5. Settlement requires a unique resolved winner in the event catalog. A
   projection must resolve every quoted band. Missing labels, malformed payouts
   and unknown winners raise instead of silently becoming losing positions.
6. Every SQLite connection uses a helper that sets process-local temporary
   paths beneath the attempt's output scratch directory before connecting.
7. Outputs disclose that exposure is limited to the recorder's reward-ranked
   top-ten selection minutes and that the owner's manual orders appear in
   competition during the stated dev period.

## B010 re-check

- **Unknown inventory after a gap:** a partially observed quote sequence cannot
  resume from an assumed empty inventory. Any unobserved live window invalidates
  the whole cohort's net and power. Known-prefix rewards are retained separately;
  they do not turn the incomplete cohort into a profitability observation.
- **Control samples:** ineligible samples remain in the timeline so they cancel
  a preceding quote, including the assumed acknowledgement delay. They create
  no exposure themselves. Dropping them had extended earlier resting quotes.
- **Same-hour rolls:** segments use manifest seal order, and a condition/minute
  is sampled only once across segments. Random UUID order cannot select a later
  segment first or double-count the same minute.
- **Silent defaults and bad data:** timezone-free clocks, nonfinite or boolean
  economic values, missing tick sizes, conflicting event identities and malformed
  mapped trades fail explicitly. Deduplication uses parsed trade time even when
  the optional raw timestamp field is missing. An inactive reward pool is an
  explicit no-quote control, not a malformed positive-rate program.
- **Claim boundary:** net is reward accrual plus counterfactual trading P&L,
  not verified paid profit. The account/day reward-payment threshold, full
  bankroll path, own-order latency calibration, multiplicity and serial-date
  penalties remain unapplied. The script cannot certify fair-trial edge or a
  universal G1 kill. Economic deduplication is not claimed conservative for net.

## Evidence

The revision and prior source are retained under the T002 archives. The B009
and B010 small checks cover coverage boundaries and gaps, unknown inventory,
all reward/f combinations, invalid controls, settlement failures, receipt-last
publication failures, streaming cleanup and same-hour roll ordering. The check
receipt names the exact submitted source hash. A bounded captured-sample trace
also passes with the stricter settlement checks; no bulk tape scan ran.

Receipts: `C:\t\codex\T002r1\out\light_checks_v3.json`,
`tiny_trace_v3.json`, `tiny_manifest_shape.json` and the pin-validation receipt.
The latest external review request names the commit, source hash, exhaustive
input families, resource estimates and verified bundle. Old review packets and
the forbidden old source remain historical evidence, not execution authority.
