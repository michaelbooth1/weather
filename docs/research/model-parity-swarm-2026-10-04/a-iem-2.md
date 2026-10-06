# A-IEM-2 report (development)

(Reconstructed by the orchestrator from the agent's returned summary; the agent did not leave a report.md. Detail files are in C:\swarm\out\a-iem-2.)

**Verdict/status:** COMPLETE

IEM MOS acquired for NBS, NBE, GFS (MAV), MEX, NAM (MET) and LAV for all 11 stations, runtimes 2026-05-01 to 2026-09-29 (0 rows at or after 09-30). Each model has at least one run per station on 67/67 eval days and 85/85 history days. 330/330 requests succeeded, sequential with >=2 s spacing; one 429 cleared after a 60 s back-off.
Files: C:\swarm\data\iem\mos\mos_<MODEL>.parquet (columns available_utc and availability_basis), raw\*.csv, nbm_text_lastmodified.jsonl, and MANIFEST.json (337 files with sha256, about 103 MB).
IEM keeps NBS only at 00/06/12/18Z and NBE at 00/12Z (hourly only 05-01..05-05). Hourly NBM must come from A-NBH's S3 data.
Availability: NBS/NBE use the measured per-cycle S3 LastModified (median lag 57 and 80 min). The others use fixed lags: MAV +4h30 (NCO prodstat shows GFS MOS completing 04:12Z/16:13Z), MEX +5h, MET +4h, LAV +1h. The MEX, MET and LAV lags are not measured, because the IEM AFOS archive holds no MAV/MEX/MET/LAV bulletins. Refuters should re-run those at +1h/+2h.
Caveats: some S3 LastModified values reflect late re-uploads (for example 09-24 00Z/06Z), which errs on the safe side. The 06-17 00Z NBM listing is empty, so those 22 station-runs are excluded.
The fetch process (PID 40264) has exited and nothing is left running. No git was run and nothing was scored.
Scripts: C:\pt\swarm\tools\research\model_parity\a-iem-2_{mos_fetch,nbm_text_lastmod,mos_tidy}.py. Details are in C:\swarm\out\a-iem-2\result.json, and phase_log.jsonl has an entry.
report.md was not written because the harness blocks subagent .md report files; result.json and MANIFEST.json carry the detail instead.
