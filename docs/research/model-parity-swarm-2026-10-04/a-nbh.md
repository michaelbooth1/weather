# A-NBH report (development)

(Reconstructed by the orchestrator from the agent's returned summary; the agent did not leave a report.md. Detail files are in C:\swarm\out\a-nbh.)

**Verdict/status:** COMPLETE

I fetched all of NBH and NBS: 1,608 of 1,608 objects each for 2026-07-25..09-29, every cycle 00-23Z. Nothing was missing, nothing failed, and the parser flagged nothing. All 11 stations are in every object, so every station-day has 24 of 24 cycles.
Outputs: C:\swarm\data\nbh\nbh_tidy.parquet (15.5M rows, sha256 0124b674...) and C:\swarm\data\nbs\nbs_tidy.parquet (12.5M rows, sha256 a54a7e44...). Each has a MANIFEST.json beside it (C:\swarm\data\nbs\MANIFEST.json for NBS) with per-object URL, S3 LastModified, ETag, bytes, sha256, coverage and S3 lag by cycle.
Tidy format is one row per station, field, forecast hour and cycle, with columns station, nbm_version, field, fhr, value, cycle_utc, valid_utc, product, available_utc. For NBS TXN, valid_utc is the end of the 12-h period, so the 00Z column holds the daytime max.
Availability: available_utc is each object's own S3 LastModified. Median lag is about 38-48 min on off-cycles, 77 min at 00Z and 95 min at 12Z.
Late uploads, kept as measured: 2026-09-24 00Z-12Z reached S3 4-14 h late. Also late: 08-31 12-13Z (+2 h), 09-14 17-18Z (+3 h), 09-23 19-20Z (+2-3 h).
Raw files were deleted after extraction (93.4 GB transferred, one object at a time). The loop (PID 41356, 00:23-01:02) exited by itself and nothing is left running. Nothing was scored and no STOP condition was hit.
Code was copied to C:\pt\swarm\tools\research\model_parity\a_nbh_acquire_loop.py and a_nbh_build_manifest.py. C:\swarm\out\a-nbh\result.json is written and the phase_log line is appended.
report.md was not written because the harness blocked .md report files. The full report text is in result.json instead.
