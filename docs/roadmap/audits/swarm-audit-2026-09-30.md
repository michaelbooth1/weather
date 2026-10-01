# Swarm audit — 2026-09-30

- **Owns:** the 23-agent read-only swarm audit of 2026-09-30 (exam line, disk, wallet/journal, docs canon, host, research
  priorities), its verified synthesis, the claims it corrected, and the owner's dispositions.
- **Read when:** planning exam-line, disk, learning-lane, workstation or research work in the following two weeks.
- **Do not use for:** current state ([STATE_OF_PLAY](../../operations/STATE_OF_PLAY.md)) or decisions in force
  ([DECISION_LOG](../../operations/DECISION_LOG.md)).

**Method.** 23 parallel read-only agents (no orders, no credentials, no heavy work), each claim that would change a decision
checked by a verifier or by the production agent against code or the host. Where a verifier refuted or corrected a claim,
only the corrected form is kept here. Pre-flight for the night of 09-30/10-01 was audited separately (GO WITH CHANGES; all
changes applied).

**Dispositions (owner, 2026-09-30 ~22:30; night 10-01 results).** Approved with the production agent's recommendation
except items 2 and 8, declined. Rows are in DECISION_LOG 2026-09-30.

| # | Item | Recommendation | Owner | Disposition / result |
| --- | --- | --- | --- | --- |
| 1 | Sign Clarification 2 (`a8c0b846b`) | yes, after reading; before the calibration rehearsal | approved | owner step, open |
| 2 | Phone alerts + dead-man heartbeat | yes (Telegram) | **declined** | — |
| 3 | Fixed-market date-clustered estimand | future pre-registrations only, V4 guardrails | approved | applies from the next pre-registration |
| 4 | Execution-tape fsync fix (rare; 3-4 min capture outage) | build now, land after 10-13 | approved | workstation |
| 5 | Desktop `BUILTIN\Users` Modify ACE (old sandbox accounts can edit pinned task sources) | remove | approved | owner runs the icacls command |
| 6 | Cleanup: 26 spent one-shot tasks, merged worktrees | yes, rescue branch first | approved | 10-01: rescue `codex/stage2-build-20260921-rescue` pushed; 26 tasks unregistered; 33 worktrees removed, 2 dirty kept (receipts `data/alerts/cleanup-20261001/`) |
| 7 | Learning lane silent since 08-13 | read-only diagnosis, then unblock | approved | 10-01 diagnosis: Stage B `WeatherEveningEvidenceRefresh` disabled since 08-13; Stage A's in-chain learning steps GAPPED by a DIAGNOSTIC_ONLY settled-day barrier; unblock needs a non-colliding Stage B trigger |
| 8 | UPS | yes | **declined** | — |
| 9 | WeatherOneShotPush without a logon | not now | approved (stays Interactive) | — |
| 10 | Fill-toxicity desk study (decides the maker P&L sign: +1.7 to -5.7 pUSD per band-day) | top research priority | approved | workstation |
| 11 | Hourly NBS/NBH guidance probe | after 111h | approved | queued |
| 12 | One reward scan incl. a YouTube market | yes (public reads) | approved | workstation |
| 13 | YouTube plugin | hold until after 10-15 | approved | held |
| 14 | Workstation fix batch (111e follow-up, plugin identity check, #130 ledger cap, #142/#143 registry rows, repo tools, CI, LAN IPs) | yes | approved | prompts prepared 10-01 |
| 15 | 91a stop-vs-skip on zero savings | keep stop; review after a week | approved | 10-01 apply PASS with tiny files skipped |
| 16 | Candidate 2 (#115/#137) | pinned worktree; decide by 10-12 | approved | open |

## Verified findings that drove the items

- **Exam line.** The 111j fix binds bands end to end; the stricter pass bar requires complete probability mass at lead 1.
  10-01 re-run: lead-1 end-to-end 2,512, band-identity mismatch 0, but mass partial on every record (selected-band capture
  and non-increasing percentile knots). #134 stays held.
- **Disk.** 91a needed the tiny-file skip (111i) and a pinned registration worktree; registration pins the task to the
  registering worktree, so cleanup must exclude it. The nightly and any 00:30 suite collide on the lease.
- **Journal 403s** were a missing User-Agent header (fixed in #127 `ebe72984`), not the geoblock first suspected.
- **Docs canon.** Order-journal pin, batch status and hook wording had drifted; the Codex user-layer hook does not exist for
  Claude Code (the S4U guard covers `claude.exe`). Root `AGENTS.md` line on the hook still needs the same correction (not
  docs-only, so outside the light path).
- **Host.** No usable restore points existed, so the shadow-storage cap cost nothing; Windows Update forced restarts are now
  confined to 03:00-09:00.

## Corrected along the way

- The production agent's claim that roll-free merges are refused at 06:30 was wrong: the merge tool refuses only
  12:00-00:30 for every branch and requires 01:00-04:00 only for roll-sensitive branches.
- The test-flake premise, "token expiry breaks the push task" and "the hazard is unmeasured" were each refuted by a verifier.
- The first reading of the journal's 403s as a geoblock, and of the wallet reader's failure as its S4U logon, were wrong
  (missing User-Agent; a DENY ACL on the main checkout's data folder, fixed by a dedicated reader worktree in #150).
