# S31 P0 Clarification 3 (2026-10-31): the R13 raw archive as the one second write root

Status: third clarification to `rule_s31_p0.md` (sha256
`d50112ccf2a22b2f02140e06c68bbbe36936a2ac9dc8e16351a7188ee2ea856e`, approved by master 2026-10-31). It sits
beside Clarification 1, `clarification_s31_p0_1.md` (sha256
`b7bb9f2aafb654bd68389c170416f3efae64b33696723a6c54572ce22e177e5d`, approved), and Clarification 2,
`clarification_s31_p0_2.md` (sha256 `798dfaa912c7e94da97c0c99340d12726bb9c606b7279324b92ef4b8c670bd26`,
approved). None of those three files is edited. This file answers master's review finding F7 on the fetch module
at `30bb432cb`. Lane L14, outcome-free: no venue price or outcome was read to write this file.

## 1. The contradiction

Rule §6 says two things that do not fit the R13 archive rule (keep everything, never clean):

- The module "writes only under its `--out` dir".
- "The raw body is never written."

The fetch module archives every raw response body, exclusive-create and never overwritten, under a root that must
lie outside `--out`.

## 2. The clarification

- **One permitted second write root.** Besides `--out`, the module may write to
  `C:\archive\ruled-out\_s31-intake\s2_fetch\raw\` and nowhere else. Below it, each run writes to
  `<run_id>\`. Bodies with a dropped late item go to `<run_id>\_quarantine_late\`. Bodies a parser refuses
  (wrong shape, or JSON or UTF-8 that cannot be decoded; master F6) go to `<run_id>\_quarantine_refused\`. A
  body sent with an authentication refusal is also written to the late quarantine, with the `.auth` suffix.
- **"The raw body is never written" means never written to `--out`, and never read.** The archived raw bodies are
  write-only evidence. No lane, script or rule reads them: not to compute, not to inspect, and not to refetch. A
  later rule that wants to read one must name it, and it needs master's approval first. This matters because a
  raw `/markets` body still holds the fields that allowlist A drops (prices, volume, `result`,
  `settlement_value`). Only the allowlisted extracts under `--out` are inputs to this P0.
- **Receipts.** Each archived body has one receipt row in `--out\receipts.jsonl`. The row gives the URL, the
  status, the sha256 and byte length of the raw body, and the archive path. For a refusal it also gives the stop
  reason. A receipt never copies a field from the body.
- **Unchanged.** The dev window, the late-timestamp guard, allowlists A, B and C, the rate limit, the no-auth
  rule, the `--network` gate and every pre-registered section of the rule stay as written. The candle-window
  bound now also respects `GLOBAL_BOUND_UTC` (2026-09-30T04:00Z) and the code-bound series zones (master F5).
  That tightens the rule's dev-window bound and does not relax it.
