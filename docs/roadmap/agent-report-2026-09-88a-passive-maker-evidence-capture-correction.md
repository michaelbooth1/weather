# Mission 88a — published evidence hash correction

**Verdict unchanged: PARTIAL.** This corrects only the evidence-file hash in
the [published handback](agent-report-2026-09-88a-passive-maker-evidence-capture.md),
without editing that historical report or any capture evidence.

The report's `e77d7988f97104bbed278f8b908dfc194f374d31ec344efdead163e2cd9cbb58`
hash identifies the 10,264-byte workstation CRLF representation. Git's repository
text policy normalized the adjacent evidence JSON to LF when it was committed.
The **published 9,944-byte JSON blob** at report commit
`4031d55efcb167b0c53cd28b1fff6435a12d0216` has SHA-256:

`2bbe13397cb2eb8ce4d8b2a792bdc0ce59c06637c18d4fb13bf78c442b3b308d`

This hash was calculated from the raw `git show` stdout bytes, without a text
decode/re-encode. JSON values, capture metrics, source hashes and the raw capture
manifest hash are unchanged. Use the published-blob hash when verifying the
[checked-in evidence](agent-report-2026-09-88a-passive-maker-evidence-capture.json).
