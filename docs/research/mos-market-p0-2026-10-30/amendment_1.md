# MOS against the market P0, amendment 1 (ledger row 89)

Status: written 2026-10-30 before any computation under `rule_mos_p0.md` (sha256
`952cfc52968e8d7dee8be685ecbf71f14bfccc1a6e8cd28d149bd0a58112ebc2`). It follows the coordinator's relay of
master's acceptance. Nothing has been run or read under the rule. Where this file differs from the rule, this file
wins.

## A1. The +1 h sensitivity arm is report-only

This replaces the survival condition in rule §5 and §6.

- The verdict comes from the main arm only:
  - SURVIVE iff the candidate is testable, BH-rejected at q = 0.10 over K = 2, and its Delta 95% lower bound is
    > 0;
  - otherwise KILL, or UNTESTABLE.
- The sensitivity arm (every model lag + 1 h) is computed and reported for both candidates. It reports whether
  it would pass the main arm's BH threshold with a Delta lower bound > 0, and a `flips_verdict` flag. The flag
  never changes the verdict.
- A survivor whose flag is set is reported as `SURVIVE (sensitivity flip)`, so the reader sees it.

## A2. Serve-parity source; no owner question

This replaces the last sentence of rule §7.

- Production captures no MOS. The serve-parity source for a survivor is the IEM MOS forward recorder
  (lane L13, `tools/research/iem_mos_forward_recorder.py`, commit
  `841fb604255825258a5b2ac0d1fa4b1009a2818d`; registered on the owner's yes, per the coordinator).
- A survivor needs no new owner question.
- First readable forward dates under method §5 rule 9, ruled per date, per the remaining-lever map's recorder
  section (`5395f8b1f0a9d7685becae7e27261e7d09f292b2`; IEM MOS ">= 12-15"):
  - forward dates up to about 12-14 are first readable on or after 12-15;
  - PT-1's dates 12-12..01-25 are first readable on or after 01-26.
- A survivor is still not an adoption. It earns a forward test, on recorder dates under a new rule.
- The kill line is unchanged. A KILL closes the MOS-against-the-market family. It reopens only with a captured
  MOS feed (now the recorder) plus a new rule on dates disjoint from the dev window.
