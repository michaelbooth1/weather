# S-CANON report (canon writer, DESIGN §6) - DRAFTS PENDING PRODUCTION REVIEW

**Status: DONE.** Canon edits drafted on worktree C:\pt\swarm (branch codex/model-parity-swarm-20261004), based strictly on
docs/research/model-parity-swarm-2026-10-04/SYNTHESIS.md. No git run. No score computed (no HARNESS dependency of my own;
numbers quoted carry the synthesis's HARNESS_SHA256 8db69adc...f74). STATE_OF_PLAY.md NOT edited.

## Files changed
1. docs/operations/ESTABLISHED_FINDINGS.md
   - New section **10q** (DRAFT banner, pending production review): ladder table per block (r0/r1/r2, gap closed),
     evening = serving defect (one served payload), morning = known 10h/10j/10p family with parser-repair dependency and
     10j power cap, no external source adds information (named list; NBH increment), 13-16/15-16 residual and t3-r3
     fragility, 00-16 not at parity, T1 serving-stage form + 81a floor interaction + S7 gate, tail lens on this table's
     definition (6.075% / 70.38%) with EF's 4.387% / 64.140% beside (EF unchanged), defects (M0 etc.), Bonferroni over
     134 rules, consequences as owner-decision proposals, evidence pointers.
   - Section index row 10q.
   - 10e: PARTLY SUPERSEDED banner (one served payload read for lock-ins/S7); original text untouched.
2. docs/operations/FINDINGS_DIGEST.md (183 -> 186 lines, budget 250): 10e bullet updated; one new 10q bullet; two
   closed-thread rows (capturing NBH/other free sources; evening decided-band as information), both marked DRAFT.
3. docs/operations/RETRACTED_AND_FALSE_LEADS.md §1: two entries (evening family = serving defect; capture NBH/other
   source for the morning = false lead), each with what it looked like / what is true / why it fooled us.
4. docs/operations/OPEN_QUESTIONS.md: Q-08 evidence updated (stays OPEN); new Q-18 (replay of the lock-in fix), Q-19
   (t3-r3 on new dates), Q-20 (00-12 residual).
5. docs/README.md: route row for docs/research/model-parity-swarm-2026-10-04/ (links SYNTHESIS.md).
6. NEW docs/research/model-parity-swarm-2026-10-04/state-of-play-proposal.md: proposed "Current truth" bullet and
   replacement for critical-path item 4; notes for the production writer.

## Checks
- weather.operations.agent_docs_audit on C:\pt\swarm: PASS (18 agent files, 1137 Markdown files).
- RETIRED_CLAIMS: no entry added (code file, out of scope). No canonical claim was retracted: 10e is upgraded, and the
  two RF entries are false leads that no canonical file stated as true. Production should confirm.
- No DECISION_LOG row (no owner decision taken). Production should add one if the owner acts on the proposals.

## For production review
- All new text is marked DRAFT pending production review; fold or reject as a block.
- STATE_OF_PLAY critical-path item 4 ("NBS/NBH probe (after 111h)") is answered by this run; see the proposal file.
