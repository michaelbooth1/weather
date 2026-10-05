# refute-pit:T3 report (development)

(Reconstructed by the orchestrator from the agent's returned summary; the agent did not leave a report.md. Detail files are in C:\swarm\out\refute-pit-t3.)

**Verdict/status:** disqualified=False

R-PIT-T3 verdict (development only, HARNESS_SHA256 8db69adc...): t3-r3 is NOT DISQUALIFIED in its best block, 17-23. 13-16 should be downgraded to availability-sensitive and not carried as a LEAD.
- Reproduction: re-running T3's own functions gives exactly what T3 reported (17-23 -0.0219 [-0.0327,-0.0131]; 13-16 -0.0116; all hours -0.0094; 105,187 provided snapshots).
- Code checks for rules 1-5 and 8 all pass. Rule 1: as-of join on valid+10min, then h.assert_point_in_time; the history table uses the same availability column; COR rows excluded. Rule 2: allow-listed inputs only. Rule 3: history labels end at 2026-07-31. Rule 4: harness floor applied. Rule 5: 0 rows after 2026-09-29. Rule 8: no hour gate. No leakage-suspect groups in 5 re-scores.
- Availability: METAR is the only external input. IEM has no per-row receipt time. Production's captured high_so_far (point in time) already showed the new METAR max in 87% of cases at 5-10 min after valid, 93% at 10-15 min and 98% at 20-30 min. So valid+10min holds for about 93% of new maxes. S3, Open-Meteo and NBM availability do not apply (no guidance used).
- Shifted re-runs, 17-23: stays LEAD in every variant: serve-only +1h -0.0221, both +1h -0.0216, serve-only +2h -0.0225, both +2h -0.0207, 11/11 markets each time. METAR running max exceeds the captured floor by at least 1F in only 0.14% of 17-23 rows, so the gain is the late-day no-further-rise shape, not information production lacked.
- Shifted re-runs, 13-16: collapses at serve-only +1h to WEAK -0.0052 [-0.0150,+0.0035] (before -0.0004, 6/11 markets); NULL at serve-only +2h; WEAK at both +2h. It stays LEAD at both +1h only on the 5%-of-gap bar.
- Files: I did not write report.md or the docs copy (refute-pit-t3.md); a tool guard blocked report files for subagents. The orchestrator should write report.md from this output. Code: C:\pt\swarm\tools\research\model_parity\r-pit-t3_refute.py and r-pit-t3_feedlag.py. Scores and result.json: C:\swarm\out\refute-pit-t3\ (copy in C:\swarm\out\r-pit-t3\).

**Defects:**
- 13-16 LEAD collapses under a serve-only +1h METAR shift: WEAK -0.0052 [-0.0150,+0.0035], before -0.0004, 6/11 markets. Under +2h it is NULL (serve-only) or WEAK (both). Treat 13-16 as availability-sensitive, not a LEAD.
- The valid+10min basis is slightly optimistic. Production's own captures show about 7% of new-max METARs arriving more than 10 min after valid (upper bound, since poll cadence is included). This is covered by the shift runs and does not affect 17-23.
- IEM asos.py has no per-row receipt time. Backfilled or replaced rows get valid+10min. 17-23 is insensitive (holds with 2h of serve-time staleness); 13-16 is not.
- Serve-only +2h turns 10-12 HARM (+0.0181). The table and the serve-time feed must share one availability basis in any serving stage.
- Serveability (not PIT): in 00-09 the METAR running max since local midnight is at least 1F above captured high_so_far in 53-57% of rows. The midnight carry-over definition differs, as T3 disclosed.
- The required report.md and docs copy were not written because a tool guard blocks report files for subagents. The content is in this output and result.json.

