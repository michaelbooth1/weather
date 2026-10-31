# DRAFT B-1 look-chain clarification: the per-date extractor joins the closed list

**Status: DRAFT by lane L8, 2026-10-31, for master. Not in force, not signed, and not an owner decision.**
It is a separate research note: it does not edit `docs/operations/B_FORWARD_TEST_DESIGN.md` or
`docs/research/mg2-composite-binding-2026-10-25/`. Due before 2026-11-29.

## 1. Source

Master ruling (i), 2026-10-31, as relayed by the WS coordinator: the post-look per-date extractor is PERMITTED. It
runs:
- in the SAME look session;
- immediately after the B scorer;
- on the SAME sha-pinned `b_transfer` bytes the scorer consumed.

It outputs only the per-date S_t and n_t (plus the 07-12 and 13-16 splits) and is receipted with B's look. That
makes it part of B's receipted look, not a new read, and it reads no byte B did not. It must reproduce B's printed Δ.

## 2. The closed list of look-session steps

The look session runs these steps and no others, in this order. Each runs once.

| # | Step | Entry point | Pinned sha256 | Reads | Writes |
| --- | --- | --- | --- | --- | --- |
| 1 | MG-2 score | `python -m weather.calibration.mg2_composite score` | MG-2 binding | MG-2 binding inputs | `mg2_look.json` |
| 2 | B look | `python -m weather.calibration.b_scorer look` | `f941628a4bfdb0002f9be1b5a2f11425a021a5389c651fb835c340f914883439` | B-1 §9 inputs, the one transfer | `b_look.json`, `b_look_receipt.json`, consumed markers |
| 3 | **Per-date extraction (new)** | `python -m weather.calibration.b_look_per_date` | `<PIN AT FREEZE>` | exactly step 2's verified layout, gate vectors, drop list and transfer bytes | `b_per_date.json`, `b_per_date_receipt.json` beside B's look |

The ruling (b) post-look analysis (`b_post_look_serial`, frozen at `fa380db09980692f6afe50eb48b949b6c21aa88a`,
sha256 `0c485d6e347dc11c95a7cf756e760e292db12536e663c61c1eda5d9650d80bed`) reads only `b_per_date.json` and
`b_look.json`. It opens no transfer byte. It is descriptive and never alters B's verdict.

## 3. What step 3 enforces in code, before it writes anything

- `b_look.json` is the file B's receipt names, its verdict is scored, and its outcomes were opened.
- The running `b_scorer` and scorecard shas equal the ones B's look recorded.
- The gate vectors, drop list and transfer manifest equal B's recorded input shas.
- The transfer files equal their manifest shas.
- The look date set, the drop list and the surviving count equal B's.
- Per range (07-16, 07-12, 13-16), the snapshot count, market-day count, date count, both Briers and sum(S)/sum(n)
  equal B's printed ALL-market row to 1e-12. 07-16 also equals B's decision estimate.
- Both outputs are written with mode "x", so there is one extraction per look.

## 4. Procedural rules (master's answers to (A)-(C), 2026-10-31, relayed by the coordinator)

- **(A) Timing: master's operator rule, verbatim.** "The extractor runs within 60 minutes of B's receipt write, in
  the same operator session. Master records both UTC instants in the look log, and the log shows no other command
  touching the transfer directory in between. If the gap is exceeded, the per-date output is labelled 'late' and
  ruling (b) still runs, with the gap disclosed. It never blocks B."
  - The code cannot prove timing: B's look payload carries no completion instant, and B never trusts file times.
    The extractor's receipt stamps `extracted_at_utc`.
  - The rule is applied in the look log, not in the frozen code.
- **(B) Layout bytes: accepted as is.** B's look payload records no layout sha. The extractor records the layout
  files' shas in its receipt and proves equality through exact reproduction of B's printed rows.
- **(C) Admission:** master directed offline-module allowlist entries for `weather.calibration.b_look_per_date` and
  `weather.calibration.b_post_look_serial`, on `claude/b-look-prep-20261031`, following the ece13f3d pattern.
- **Write location:** master accepted that the extractor writes beside B's look output (not only under its own out
  dir), as "receipted with B's look" requires.

## 5. Unchanged

B's verdict, its VOID conditions, its one-look markers, the embargo and every B-bound file are unchanged. The
`MG1_LOOK_ENTRY_SHA256` sentinel stays BY DESIGN until master's dated clarification (ruling (iii)).
