# Workstation handoff 2026-09-111h — does corrected NBM guidance at all hours double the morning effect?

Written 2026-09-29 by the production agent; owner approved 2026-09-29 (pillar A, measurement first). Research only:
no serving, capture or model change; no candidate fitted; no α spent. Allowed during the exam period because nothing
here lands on production code paths. Branch `codex/guidance-all-hours-20260930`, base `origin/master`.

## Start from this, do not re-derive it (FINDINGS_DIGEST; EF §10h-§10l)

- Captured NBM percentiles, read with no fitted parameter, beat the served model on morning rows but still trail the
  market (EF §10h). Scored on every US morning row, zero-parameter C1 (NBM with floor) minus served is
  -0.006672 [-0.011525, -0.002373], ratio to market 1.356; the minimum-effect falsifier fired; with 11 market clusters
  **no effect of that size can be confirmed at any season length; roughly twice the effect is needed** (EF §10j).
- The NBM parser v1 picks tomorrow morning's minimum from 12Z/13Z/19Z bulletins: 67% of captured NBM rows. That is why
  guidance "disappears" after about 10:00 local (EF §10k). Parser v2 (branch `codex/nbm-target-fix-20260921` @
  `2e17ce0eb`, not on master) selects the correct 00Z maximum or returns `target_max_not_in_cycle`; from 12Z on the
  newest bulletin holding today's maximum is 07Z, so afternoon guidance is 5-24 h old by construction (EF §10l).
- The event-day `forecast_payloads` manifests record `cycle_key` and `provider_update_time` for every snapshot, and
  the national bulletins are retained in `data/forecast_payload_cas/sha256/<xx>/<key>.blob` (EF §10k, 111a).

## The question

Re-derive guidance at every captured snapshot with parser v2 (only bulletins that existed at capture time), then
re-score 81a's two zero-parameter candidates on **all hours**, not only 06:00-09:59. Does the pooled effect reach
about twice 81a's (≈ -0.0133), the affordability line for a confirmation under crossed date × market clustering?

## Part 1 — extractor (built here on fixtures; production runs it)

`python -m weather.research.guidance_extract --data-root <dir> --out <dir> --from 2026-08-01 --to 2026-09-29`:
for each captured snapshot of the 11 US settlement markets on promotion-countable market-days, emit one row: market,
target date, snapshot capture time (UTC and local), NBM v2 percentiles for today's maximum with cycle, issue and
valid times (or the v2 unavailable reason), HRRR and NWS-grid point highs with their issue times where captured, the
observed floor at capture, the served band probabilities, the market mid per band, and the settled outcome. Nothing
dated after the snapshot's capture time may enter its row. Import parser v2 from a pinned detached worktree of
`2e17ce0eb` using `python -P` and a module-path probe (the pattern in `scripts/ops/manual_order_journal.ps1`), so no
production code changes. Bounded: streamed reads, per-file caps, explicit input budget, runtime at most 2 h under the
shared lease; output one compressed table (target under 1 GiB) plus a manifest with row counts, per-source bytes read,
the parser worktree SHA and SHA-256 of every output file.

## Part 2 — analysis (here, on the transferred table)

Freeze a pre-registration commit before the first score: C1 and C2 exactly as 81a defined them, v2 values, fallback to
served where guidance is unavailable; strata split at 2026-08-23, never pooled across it except where 81a pooled;
crossed date × market bootstrap, 2,000 draws; report by local hour block (00-05, 06-09, 10-12, 13-16, 17-23), ratio to
market, power and MDE, and whether the pooled effect reaches twice 81a's. Also report how many 79a/81a scored rows used
a v1 wrong-period value that passed the floor (EF §10k's uncounted item).

## What would falsify this mission

If v2 guidance at afternoon hours scores no better than served (stale 07Z adds nothing), or the pooled effect stays
near 81a's, the all-hours route is closed for the US markets under the current rules. Report that plainly.

## Transfer (production to workstation)

The repository is public: data never goes through git or GitHub. Production writes the extract to
`C:\Users\micha\Desktop\github\weather\data\exports\nbm-guidance-111h\` with a `SHA256SUMS` file. The owner pulls it
from the workstation over SSH (production host `MICHAEL`, 192.168.1.247, sshd on port 22) with `scp` and the owner's
Windows password, then verifies the hashes. The workstation session must not copy it anywhere else.

## Deliverables

Fixture tests (built with production writers, including a 13Z bulletin, a missing 07Z file and an after-capture
bulletin that must be excluded), the repo-wide audits, green CI. Report
`docs/roadmap/agent-report-2026-09-111h-guidance-all-hours.md`, first with the exact production extractor command,
then (after the transfer) the analysis results.
