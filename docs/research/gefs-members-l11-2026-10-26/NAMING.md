# Naming

Rule a9ca45f063a39b8ad2408414aab4658d5f4f96c855a51d11b34236b8045fa18c (file `rule_rn.md`) is rung **R-O, GEFS member-mean centre**. "R-N" is held by L3 (HRRR-minus-NBM at 00-06, c1694f75...); the pinned file is not edited, so its sha is unchanged.

## Added fetch scope for lane L15 (R-Q), coordinator approval 2026-10-25

- **What is added.** One further pass, for lane L15's R-Q rule (`C:\t\l15\rule_rq.md`, sha 5703f065...). It is not an R-O input.
  - Cycle 18Z of D-1, product `pgrb2ap5` (0.5 deg grid 3.0, 720 x 361), `TMP:2 m above ground`.
  - Members gec00 + gep01..30, steps f018..f036 every 3 h (valid 12Z D .. 06Z D+1).
  - The same 367 target dates; the latest cycle is 2026-09-28 18Z.
- **Where.** A separate corpus, `C:\t\l11pb\gefs\corpus_18z_ap5\`, with its own byte cap (15 GB, lowered so the two passes
  together stay within about 60 GB).
- **When.** It runs serially after the 06Z fetch and after R-O's gate 1 and P jobs.
- **R-O is unchanged.**
  - The fetcher's defaults are still 06Z D, `pgrb2sp25`, f006..f024.
  - Rows now also carry `product` and `cycle_hour` fields.
  - The R-O loader reads only the pinned 06Z sp25 corpus.
- **Decoder.** Re-proven bit-exact against eccodes 2.49.0 after the change:
  - 21 ap5 messages (target 2026-08-10, gec00/gep01/gep30): receipt `C:\t\l11pb\gefs\probe_ap5\eccodes_check.json`
    (sha 96797f91...);
  - 14 sp25 06Z regression messages: receipt `C:\t\l11pb\gefs\probe_sp25b\eccodes_check.json` (sha 5d9cd596...);
  - max abs diff 0.0, no identity or corner mismatch, templates 3.0/4.1/5.3 only.
- **Timing.** The latest 18Z D-1 object in the ap5 probe was available at 22:05Z on D-1.
