# Formal state review, 1 November 2026

*Nine reviewers checked the repository read-only from the capture PC, between about 11:00 and 13:00. Every high or critical finding then went to a second reviewer who tried to disprove it. That reviewer refuted none of them and downgraded several from high to medium. Status labels: CONFIRMED = the second reviewer reproduced it; PLAUSIBLE = it holds, with caveats; NOT-VERIFIED = one reviewer checked it directly, but it was not challenged.*

## Executive summary
Capture is healthy. All 10 capture processes and every scheduled task ran on time through the clock change, disk has about 216 GiB free, and B's frozen files still match their recorded fingerprints. The most serious problem is in B itself: as the code stands, its single look (about 12-13) is certain to end VOID. VOID means no verdict, and the 45 dates are spent. The plan requires editing the scorer file, and the scorer refuses any edited copy of itself. No result has been read yet, so a written ruling plus one test fixes it with weeks to spare. Tonight's new replay runner breaks a standing host rule and has a few ways to fail silently. All of these are small edits before the ~21:00 launch. Many records also lag your recent decisions, and nothing in the research record yet beats the market. B is therefore more likely to come back inconclusive or failed than passed, and the next ideas should be lined up now.

## Fix before tonight (scripts start ~20:30-21:00)
At 11:28 neither script had changed since the reviewers read it.
1. **Replay runner: cap math threads** (CONFIRMED). It starts the October replay with no thread limits on the 20-core capture PC. Host rule 11 forbids this: uncapped runs have taken ~17 cores and run ~9x slower. The fix is three environment lines.
2. **Replay runner: silent failures.** One stray git message crashes it with no log line; this quirk was reproduced on this PC. Its replay child is not tied to it, so if the runner dies the replay keeps running with no lease and no deadline. Its memory checks are also looser than every other job's.
3. **Night sequencer: protect the 04:15 B input export.** The rule against starting a suite before 04:20 is checked only once, and never before merges. If a step slips, B can lose a day of input.
4. **Combined branch.** It holds 8 branches, over your cap of 4. Record an exception, keep a smaller fallback, and if its tip isn't ready by 21:00, remove it. Leaving the placeholder in cancels the whole night.
5. **Ten-city capture switch.** All 10 new cities go live at once, where your plan was five first, checked by receipts. Record why, with rollback triggers, or land five first.
6. **Record the one-night overlap** with the 04:45-06:45 tiering slot, as the data plan requires.
7. **Embargo hygiene.** After tonight's merge, the replay tool writes October market prices *by default*. Always pass `--no-market` until the default is fixed.

## Decisions or answers needed from you
- **Ethernet.** The capture PC is still on Wi-Fi. An hour-long drop between 07:00 and 16:00 can cost B a date. Plugging in the cable is the cheapest risk reduction available.
- **Windows Update.** The pause ends 12-02, inside B's last ten days. Approve one attended patch-and-re-pause night in November.
- **Nightly compression policy** expires 11-27. Approve renewal by about 11-24. The last lapse cost two nights.
- **Live-trading pause** is enforced only by typed confirmations. Accept that, or ask for a code-level stop before any pilot restarts?
- **Old Python rollback folder** (venv-cp3110): keep or delete after about 11-05?

## Workstation queue
- Make the host safety guard see heavy work launched by Claude. Today only the 92% memory emergency rule catches it (CONFIRMED).
- Make the replay tool refuse prices after 09-29 by default.
- Re-base and land the 10-22 PowerShell exit-code fixes. They passed testing but never landed, and they stop scripts reporting false success.
- Answer whether the row 72 forward test is actually running.
- Fix the T+1 bundle builder size cap. It blocks the only cheap day-ahead test.
- Enforce "before 12:00" in the docs light path, re-pin Windows CI to Python 3.11.9, have git ignore `venv-*/`, and confirm the GEM recorder is fetching data.

## Master agent queue
1. **B look ruling (critical, CONFIRMED).** Allow the one scorer edit, or move the constant into its own file. Add a test and fix the look-chain draft. The B guard script also refuses that edit until 12-14.
2. **MG-1 countability check and window extension** (check by 11-20; Denver ruling 11-03). Today this is tracked only in a stale private list.
3. **Before the T+1 freeze (~11-03).** Rewrite the held-out-dates file to cover the embargo, MG-3 dropped, the L6_G exemption and blind accrual. Write one look-order rule for tests that share dates, and fix T+1's list of tests claiming dates.
4. **B's frozen-file guard.** Move it into the repo, keyed to B's look receipt instead of the date 12-14. Pin the rule's fingerprint in a test, and stop calling B a "draft" in the indexes.
5. **B coverage counts.** Produce B's daily market-coverage counts.
6. **Watchdog redeploy on 11-02.** It runs a 10-09 status script that cannot see the new city capture.
7. **Stage A on 11-02.** Read the step reasons, not the exit code. The two permanent "critical" stale reports come from Stage B, which has been off since 08-13. Record that as the cause.
8. **PT-1 checklist.** Cover the January serving defect, the robust interval, a start date of 12-13 (not 12-12), and an early feasibility check.
9. **Capture and input safeguards.** Schedule the dropped torn-append fix, which protects capture records. Tag frozen forward-test commits. Check daily that B input arrived, and reach the host by name rather than IP address.
10. **Docs head.** Keep it net-zero: the SoP is at its 95-line cap. Add the 13 missing ruled-out rows. Record B's real false-pass rate (about 4-6.5%, vs a nominal 2.5%). Mark EDGE-1 postponed. Update the delegation and role rules.

## What we may be missing
- **A candidate that can beat the market.** These directions are untried:
  - day-ahead (T+1) markets;
  - day-specific confidence: the gap between our own-observation nowcast and the NBM forecast, used as width;
  - the NWS point forecast as a crowd anchor;
  - foreign cities whose decisive hours fall in the US night.
  The approved reliability-by-bin measurement belongs in this list too.
- **Safeguards:** a receipt-keyed guard for B's files, a daily "inputs arrived" check, an embargo statement backed by a test, and a check that boot recovery's pinned fingerprint still matches its file.
- **Records:** a roadmap item for the B programme, and an owner for building B's venue-rule labels.

## Stale records
- the held-out-dates file
- the ruled-out register and dev-ledger "pending" cells
- item 339 and the active backlog
- OPEN_QUESTIONS (unchanged since 10-16)
- the delegation contract and the operations role
- both docs indexes ("B draft")
- OPERATIONS_DESIGN and the task registry
- the Python version in the docs and CI
- git-workflow.md
- the HOST_LOAD_POLICY guard claim
- several SoP lines (WU-vs-venue, PT-1 dates, head count, economics)
- the private commitments list

## What is healthy
- Capture 10/10, every task ran on time through the clock change, and 215.7 GiB is free.
- B's rule, scorer and MG-1 code match their bound fingerprints. The B input export returned rc 0 today, and the 10-29 and 10-30 bundles were verified.
- No secrets in tracked files. Order sending needs single-use human confirmation, and Polymarket US orders are refused in code. No paid data source is in use.
- Research discipline is strong: rules are frozen before data, and every kill is archived.
- The merge tools cannot change production under a running job, and tonight's branch tips match their remote branches.
- Every owner decision since 10-16 is logged, except the 10-27 export-task yes.

## What this review could not check
- the workstation (tasks, recorders, receipts, its update pause)
- anything under data\ (real date countability, Stage-A reasons, tiering status)
- the combined branch, which is not built yet
- live runtime measurements; nothing was run
- the 1440-line master log was searched, not read in full