# Order-book tape NUL scan, 2026-11-06

Dated evidence moved out of the canonical
[passive maker evidence capture runbook](../operations/passive-maker-evidence-capture.md),
which keeps the rule (drop NUL lines through the pinned shared filter; never repair tapes).

The workstation's byte-level NUL scan (2026-11-06, `scan.json` `432f42ac…`) covered B's 10 markets:

- 08-15..09-29: 460 files. 10 files have one NUL line each, all on 09-02 (los-angeles, san-francisco, seattle) and
  09-03 (atlanta, austin, chicago, dallas, houston, miami, nyc). 6 of those lines exceed the csv limit, and no line
  exceeds it without a NUL.
- 09-30..10-14: 149 files, 0 NUL lines.
