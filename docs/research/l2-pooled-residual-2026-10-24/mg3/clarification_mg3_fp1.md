# Clarification FP-1 to rule_mg3_forward_parity.md (`2c6e6045…`): pre-start messages in F2

- **Status:** written and hashed by lane L2 on 2026-10-26, before any further parity read. Master ruling 10-26,
  through the coordinator.
- **Defect.** F2 (latency) as written counts every used message, including messages that S3 published before the
  recorder process first existed. Their capture delay measures the recorder's start time, not its latency. The
  first read (through 2026-10-26) had 20 such messages, all captured at about 14:54Z for cycles published from 13:55Z.

## The clarification (no tunable parameter)

1. In F2 only, a used message is **excluded** when max(`grib_last_modified`, `idx_last_modified`) is strictly
   before `meta.json` `first_started_utc` (the recorder's FIRST start, today `2026-10-26T14:54:54.122052Z`).
2. Nothing else is excluded. Messages published while the recorder was down after its first start (for example the
   restarts near 17:45Z and after 18:12Z on 10-26) **count** against F2 and, through `k_miss`, against F4. They were
   real outages.
3. F0, F1, F3 and F4 are unchanged. The excluded count is reported beside F2 (`excluded_prestart`).
4. **Clock.** The 14-day clock's first full day is 2026-10-27 (from 00:00Z). The parity read covers local dates
   2026-10-27..2026-11-09 (`--through 2026-11-09`); expected MG3_D0 is 2026-11-11.
5. **Recorder changes.** L13's tightening of the post-publication polling is a recorder change. It gets a dated note
   in the recorder's record and does not restart the clock. The parity read covers the days before and after it
   alike under this rule.
