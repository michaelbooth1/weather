# NBM capture-freshness audit (lever map rank 8): CLOSED, hygiene-clean on S1

Lane L8, 2026-10-30. A batch note for the coordinator's morning docs batch. It has no ledger row and no P0.

## Provenance

| Item | Path | sha256 |
| --- | --- | --- |
| Stated reason, written before any read | `C:\t\l8tor\nbmf\nbmf_reason.txt` | `03dfbfb87ae738db56b8727a712d0cce4df991c33700697bdbe0762494441d5a` |
| Addendum 1, input substitution written before any value was read | `nbmf_reason_addendum1.txt` | `560973c0a00166712937d7ace215564aa87575e18cc0a6c2636a53afd2904797` |
| S1 script, metadata only | `nbmf_s1.py` | `5479db32607d5669ec6eb2923a307f23b16a423e1557225a4ba227c6b30cf768` |
| S1 output | `nbmf_s1_sample.json` | `168ecb7b042d5516495e06875c60b95f6abcfe305fd13453ef6b1a801a1262fe` |

## Sample scope

The S1 read served (v1) NBP timing metadata from `data/inbox/replay-inputs-le0929`. The fields were issued cycle,
`url`/`tried_urls`, `fetched_at`, `captured_at` and cache status. It covered every market on 2026-08-15 and
2026-09-15: 1,108 snapshots at local 07-12. It read no percentiles, maxima, distributions, labels or prices.

## Result

There were no stale reads.

- Zero snapshots used 00Z/01Z or a previous-day cycle at 07-12. Every available read at h07-h08 is 07Z.
- Fetch-to-capture is p50 0.05 min and p99 at most 0.48 min.
- One fallback/stale_cache read in 1,108.
- Toronto is unavailable on v1 by construction (CYYZ is outside the v1 station list).

## v2 half: BLOCKED

- The local v2 tables (`v2_available_at`, `v2_newest_cycle_key`) exist only under another lane's results directory.
- `data/inbox/mg2-inputs` is a B input and also holds dates after 09-29.
- v2 picks the newest cycle whose recorded availability is at or before capture, so it cannot be stale against its
  own availability estimate. Checking that estimate needs an S3 LastModified listing, which is network.

## Full scan: considered, not run, EV ≤ 0.0003

The full table is 57 GB, which would be a queued heavy scan. Given zero older-cycle reads in the sample and an
inventory EV of at most 0.0003 Brier, the scan was not run.

## Pointer for the coordinator's EF §10l cross-reference

From h09 the served v1 replay records move to the 12Z/13Z bulletins. On nyc 08-15 the period is valid
2026-08-16T12Z, so the reads are from the wrong period. This is the known v1 defect, a pointer only, and it is not
a freshness finding.
