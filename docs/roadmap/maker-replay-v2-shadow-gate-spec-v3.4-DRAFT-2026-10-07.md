# D — "Shadow agrees with replay" live gate: specification v3.4 DRAFT (text amendment of v3.3 §6.2 only)

> **Repository copy (2026-10-07). DRAFT — NOT IN FORCE until the owner accepts it. No authority.** Status: a proposed
> text amendment of the maker replay v2 shadow-gate specification's oracle-handout section only (v3.3 §6.2). Until the
> owner accepts it, [v3.3](maker-replay-v2-shadow-gate-spec-v3.3-2026-10-07.md) §6.2 stays the text in force. This draft
> grants no run, live, merge, transfer or handout authority, and it does not cut the handout. Owner item:
> [item 330](items/item-330-maker-economics-refocus-master-plan.md). The current status of maker replay v2 lives in
> [the state of play](../operations/STATE_OF_PLAY.md), never here.
>
> **Read when** writing, reviewing or Defending the oracle handout cut script (unit H1), or when ruling on the
> owner-pending point in §8. Read v3.3 first.
>
> **Provenance.** The H1 and the text after this note began as a verbatim copy of the workstation file
> `l-data/swarm-m/D-shadow-gate-spec-v3.4.md` (SHA-256 of the LF local file:
> `d11c0a4e8ed82d2687d1cce36806c15c5c40ff0375dd4bcc85af76fc75414463`). The owner decisions of 2026-10-07 (§8,
> points 1-5) were then applied in this repository copy, which is now the source of truth for the draft text; the
> workstation file is superseded. Line numbers refer to the hash-pinned **workstation** sources, not to the
> repository copies of v3.3, v3.2 and v3.1.
>
> **Not handout-clean.** This file names every denied Kernel string. Its filename matches the excluded pattern
> `docs/roadmap/maker-replay-v2-shadow-gate-spec-*` (§5), so it is never in the oracle's tree or handout.
>
> **Update when** the owner accepts, amends or rejects this draft, or the H1 cut script finds residue the table
> misses. Add a new dated file rather than editing this copy, except for applying owner decisions to this draft
> before it is accepted (as done for §8 on 2026-10-07).

> **DRAFT — NOT IN FORCE until the owner accepts it. No authority.** This file proposes a replacement for v3.3 §6.2 (the
> oracle handout's file list, substitutions and check). Until the owner accepts it, v3.3 §6.2 stays the text in force,
> even though, as written, it fails its own check (§0). Nothing here grants run, live, merge, transfer or handout
> authority. It does not cut the handout. Nothing in v3.3 outside §6.2 changes.

Swarm M, coordinator unit H0, 2026-10-07. **Spec text only.** No gate, kernel or oracle code. The spot-check in §7 was
done with a throwaway script that was not committed.

Sources (all read-only; full SHA-256 pins in §1):
- in this folder: `D-shadow-gate-spec-v3.3.md` (the base of this amendment), `-v3.2.md`, `-v3.1.md`, `-v3.md`, `-v2.md`,
  `ORACLE-timing-answer.md` (the residue finding), `PR256-defender.md` (header residue, deny-list curation, path globs,
  check scope);
- the build line at `501f47579` (the tree the v3.1 sources cite) and the U3 head `f0d97f11f`
  (`claude/mrv2-gate-logic-w1w2f3-20261007`), via `git show` only: `src/maker_core/replay/v2/kernel.py` (names only),
  `src/maker_core/contracts/*.py`, `src/maker_core/quoting/policy.py`;
- the 89a contract text, `docs/roadmap/workstation-handoff-2026-09-89a-fill-toxicity-desk-study-tool.md` (pinned in §1,
  §8 Q2).

No data, panel, settlement, `data/`, `.env*` or credential file was read. No row for 2026-09-30..10-15 was read.

**This file is not part of the handout.** Like v3.3 §6.2, it is the coordinator script's specification and names the
denied strings itself.

---

## 0. Why v3.4

v3.3 §6.2 hands out v3, v2 and parts of v3.1/v3.2 "unchanged" or only partly substituted, but its extended check
denies strings that those texts still contain. A handout cut exactly as §6.2 says fails §6.2's check. The residue:
- v2 l.135-165, 187, 190, 268, 450 (`state.latest[`, `state.legs`, `state.last_quote`, `add_own`, `record_decision`,
  and the Kernel names `record_signature`, `recomputed_portfolio`, `REPLACEMENT_REASONS`), plus `V2Config` in l.89-94;
- v3 l.42, 45 (`view_state`), 169, 268, 566 (`add_own`);
- v3.1 l.67, 71, 151, 299, 310, 653, 872, 900, 902, 946, 962 (`add_own`, `value.book`, `view_state`, `book_state`,
  `REPLACEMENT_REASONS`, `compose_book`), beyond the lines v3.3 already lists;
- v3.2 l.79, 98, 375, 377, 442, 460-461, 557, 602 (`REPLACEMENT_REASONS`, `compose_book`, `view_state`,
  `def compose_book`, `add_own(`).

Since the owner decision of 2026-10-07 (§8 Q1), `compose_book` is a public design name, not residue. Only the literal
`def compose_book` stays denied. The `compose_book` entries in the list above are kept as the historical finding.

The PR #256 Defender also found that the **repository copies** add residue in their headers (v3.2 copy `value.book`;
v3.1 copy `state.legs`; v3.3 copy `def compose_book`, `add_own(`, `value.book` outside §6.2). So no repository copy can
be a handout source (§2 rule 1).

v3.3 §6.2's own line edits are kept, with three precisions:
- v3.2 l.149 replaces the span "the Kernel's `value.book`". Replacing only the backtick span would read "the Kernel's
  the Kernel's ...".
- v3.2 l.246's paraphrase replaces the whole bullet, l.245-247.
- v3.1 l.283-284 keeps the tail of l.284 ("`decide()`, `policy.py` and the v1 engine are **not**"), which continues on
  l.285.

Line numbers in this file are **1-based lines of the hash-pinned workstation source**, after CRLF → LF. The PR #256
Defender quoted some repository-copy line numbers: v3.2 copy l.115 is source l.79; v3.1 copy l.308 is source l.299, and
its l.655 is source l.653.

---

## 1. Source pins `[v3.4: replaces v3.3 §6.2's inline pins]`

The cut script reads only these files, from `l-data/swarm-m/` on the workstation. It hashes the raw bytes and refuses
on any mismatch before reading a line.

| Source | SHA-256 of the local file (raw bytes) | Line endings |
| --- | --- | --- |
| `D-shadow-gate-spec-v3.3.md` (after the D-1 amendment) | `36120634030de0cdef91b5a7b4470390685d92be6d496c580c38dbf26e8940f9` | CRLF |
| `D-shadow-gate-spec-v3.2.md` | `e7359abef77cd3b583e772203688edc42142f972c872a93a0257b1ad5d7ce2ab` | LF |
| `D-shadow-gate-spec-v3.1.md` | `f0729884291142d25ea773a9d81f83ef80422a0aaf60898ef68089b694398f29` | LF |
| `D-shadow-gate-spec-v3.md` | `2bd3942ec7994a83a627574204024fc3cc3a38d311a4394df218654359bc0a9c` | LF |
| `D-shadow-gate-spec-v2.md` | `58484328bb3675bbbd2b7f9175ce9b0ad9648642a400aa714d993a723db05ca6` | LF |

v3.3's pre-D-1 hash (`85edfe72…dcdb`) is void as a handout pin. Handout spec texts are written with LF endings, and
the manifest hashes those LF bytes.

**The 89a contract text** (§2 item 5; owner decision §8 Q2) is a repository file. It is pinned by path and by the
SHA-256 of its raw bytes, and the cut script refuses on any mismatch before reading a line:

| Source | SHA-256 of the file (raw bytes) | Line endings |
| --- | --- | --- |
| `docs/roadmap/workstation-handoff-2026-09-89a-fill-toxicity-desk-study-tool.md` | `ff7e85be0d0bf13667802d58eed464ba900c5f95f033a1fd15496d8eaba9d9d9` | LF |

It is handed out unchanged: it passes the §4 check with 0 hits (§7). It is byte-identical (git blob `f74f9c856`) at
`master`, `501f47579` and `f0d97f11f`.

**The code items** (§2 item 5) are pinned by **commit and path**. The cut script takes one build-line commit as an
argument, reads each path with `git show <commit>:<path>`, and records commit, path and SHA-256 in the manifest.

**Which commit (owner decision §8 Q3).** The code items and the §4 deny-list drift check are pinned to **U3's merged
build-line head**: the head of the maker-replay-v2 build line once U3's branch has merged into it. That head is
re-checked at the cut: the script reads the four code files and the `kernel.py` names at that commit, runs the drift
check and the §4 check there, and records the commit in the manifest. Until U3 merges, `501f47579` is the current
reference: the four code files are byte-identical there and at the U3 head `f0d97f11f` (§7). If the merged head
differs from the reference in any code file, the manifest records the new hashes and the §4 check must still pass.

---

## 2. The handout `[v3.4: replaces v3.3 §6.2's item list]`

**Rule 1: sources.** The handout spec texts are cut from the **hash-pinned workstation sources** of §1, never from
the repository copies under `docs/roadmap/maker-replay-v2-shadow-gate-spec-*`. Those copies carry header residue, and
they are themselves excluded from the oracle's tree (§5).

**Rule 2: contents.** The handout tree holds exactly these files:
1. **v3.3**, with §6.2 deleted (S1).
2. **v3.2**, cut before `## Annex K` (S2), with S3-S14 (S4, S9 and S13-S14 withdrawn, §8 Q1). S2 deletes Annex K
   **and** the 10-line Summary after it, as v3.3 says (owner decision §8 Q4). The v3.2 repository copy keeps that
   Summary; the handout does not.
3. **v3.1**, with S15-S32 (S23, S28, S29, S31 and S32 withdrawn; S25 narrowed; §8 Q1). S20 and S24 are v3.2 §6's two
   fenced-block redactions.
4. **v3** with S33-S39, and **v2** with S40-S58. Neither is handed out "unchanged" any more.
5. `src/maker_core/contracts/__init__.py`, `conformance.py`, `portfolio.py` and `src/maker_core/quoting/policy.py`
   (`decide()`, declared common-mode), at the build-line commit pinned by §1 (§8 Q3). Also **the 89a contract text**,
   as v3.1 says: `docs/roadmap/workstation-handoff-2026-09-89a-fill-toxicity-desk-study-tool.md`, unchanged, at the
   §1 hash pin (§8 Q2).

Not handed out: v3.4 itself, v3.3 §6.2, Annex K, the Defender files, and any `kernel.py` excerpt (as v3.2 §6).

---

## 3. Substitution table `[v3.4: replaces v3.3 §6.2 items 1-4's edits]`

There are 58 numbered entries, S1-S58. Nine are **withdrawn** by the owner decision of 2026-10-07 (§8 Q1: S4, S9,
S13, S14, S23, S28, S29, S31 and S32). Their spans existed only to avoid `compose_book`, which is no longer denied, so
those spans stay verbatim. Their numbers are kept and not reused. Each reverted span was re-checked against every
remaining §4 rule; only S25 still hits one (`state.legs`, rule 3), so S25 is **narrowed** to a minimal substitution of
that span. S10 stays: it removes the literal `def compose_book`. The cut applies **49** substitutions. Each is one of:
- **replace span**: the old text must occur **exactly once** on that source line, and is replaced in place;
- **replace whole line(s)**: the listed lines are replaced by the given lines;
- **delete**: the lines are removed, with no marker line.

The cut script fails closed if any span is missing or not unique, or if a line or range is out of bounds. It applies
spans first, then ranges and deletions bottom-up, so the source line numbers below stay valid. In each block, `-` is the
source text and `+` is the handout text.

**Paraphrase vocabulary.** These are design descriptions of what the Kernel does, not identifiers or code:
- *own-leg composition*: the step that adds resting own legs to the public book before `decide()`;
- *composition function*: [withdrawn — §8 Q1] no applied substitution uses it; the U3-fixed form of the step is
  named `compose_book` verbatim, and the oracle's equivalent is `C_book`;
- *post-decision state update*: the step that sets or clears the resting legs and the last-quote instant after a
  decision;
- *view-state / book-state wake signature*: the parts of a view or book record that decide whether the condition
  wakes;
- *closed replacement-reason list*: the six reasons listed in v3.1 §6.3 step 10;
- *portfolio recomputation*: assembling a condition's portfolio from the other conditions' reserves.

`kernel.py:<lines>` pointers are kept. They are line references, not code, and v3.3 itself uses them.

### 3.1 v3.3 (`D-shadow-gate-spec-v3.3.md`)

```text
S1  l.290-322  delete (no marker line)
  first: ### 6.2 The handout (replaces v3.2 §6's item list and its check)
  last:  (blank line)
```

### 3.2 v3.2 (`D-shadow-gate-spec-v3.2.md`)

```text
S2  l.614-677  delete (no marker line)
  first: ## Annex K — U3 only. NOT part of the oracle handout (§6). `[v3.2: MF-8, N3]`
  last:  10. Fills: 5 = 4 at price + 1 strictly through; E recomputed (A = 11 sessions, B = 3 days); strictly-through E[power] at 21 d ≈ 23 % (A), and the first-live cap almost surely binds; OD11 is now decidable.
S3  l.79  replace span
  - in `REPLACEMENT_REASONS` (`kernel.py:41-42`)
  + in the Kernel's closed list of replacement reasons (`kernel.py:41-42`)
S4  l.98  [withdrawn — §8 Q1] no substitution; the span stays verbatim
  = making `compose_book` skip
S5  l.149  replace span
  - the Kernel's `value.book`
  + the Kernel's composed decision book
S6  l.245-247  replace whole line(s) with
  + - But the horizon that the Kernel and `decide()` use is the **captured descriptor's** `horizon_days`. The descriptor record payload carries it (`payloads.py:41,80`). The Kernel passes the latest descriptor record's horizon into the decision inputs (`kernel.py:524,534`). Registration §4 says activity follows "the latest captured descriptor at or before t", amended by C13 (§4.4) to "captured or derived".
S7  l.375  replace span
  - hashed into `view_state`)
  + hashed into the Kernel's view-state wake signature)
S8  l.377  replace span
  - (the `reason` is in `view_state`)
  + (the `reason` is in the view-state wake signature)
S9  l.442  [withdrawn — §8 Q1] no substitution; the span stays verbatim
  = (§3.7.1(a) `compose_book`, §3.7.2(a) the replacement code)
S10  l.460  replace span
  - or the strings `def compose_book`
  + or a denied Kernel string
S11  l.461  replace whole line(s) with
  +   (the denied list is kept with the coordinator's script).
S12  l.555  replace whole line(s) with
  + - W2(a)'s guard against resting legs is an explicit `BundleError`, not an assertion
S13  l.557  [withdrawn — §8 Q1] no substitution; the span stays verbatim
  = `compose_book`'s `unmerged_book_levels` raise
S14  l.602  [withdrawn — §8 Q1] no substitution; the span stays verbatim
  = (`compose_book`: four arrays, created levels, summed)
```

### 3.3 v3.1 (`D-shadow-gate-spec-v3.1.md`)

```text
S15  l.67  replace span
  - The Kernel's `add_own` iterates
  + The Kernel's own-leg composition iterates
S16  l.68  replace the G2 row's first cell (text between '| G2 | ' and ' | `kernel.py:546-549`')
  + After a replacement-reason CANCEL, the Kernel decides the replacement on the pre-cancel decision book with `existing = ()`, after its leg ledger has been cleared; so the cancelled size counts as competing liquidity and displayed depth.
S17  l.71  replace span
  - the same composed `value.book`
  + the same composed decision book
S18  l.151  replace span
  - part of `view_state` (`kernel.py:198`)
  + part of the Kernel's view-state wake signature (`kernel.py:198`)
S19  l.187  replace span
  - `C_book(public, state.legs)`
  + `C_book` of the public book and the resting legs
S20  l.255-281  replace whole line(s) with
  + [REDACTED: Annex K, U3 only — see the table and the semantics sentence above]
S21  l.283-284  replace whole line(s) with
  + The Kernel's frozen composition step is replaced by `C_book` of the latest public book and the resting legs. `decide()`, `policy.py` and the v1 engine are **not**
S22  l.299  replace span
  - `book_state` reads the public record
  + the Kernel's book-state wake signature reads the public record
S23  l.310  [withdrawn — §8 Q1] no substitution; the span stays verbatim
  = summing sizes (`compose_book`)
S24  l.373-380  replace whole line(s) with
  + [REDACTED: Annex K, U3 only — see the table and the semantics sentence above]
S25  l.382  replace span  [narrowed — §8 Q1: `compose_book` stays; `state.legs` still hits rule 3]
  - applied to `state.legs`.
  + applied to the resting legs.
S26  l.383  replace span
  - since `state.legs == ()`.
  + since the resting legs are empty.
S27  l.653  replace span
  - `REPLACEMENT_REASONS`, `kernel.py:41-42`, transcribed
  + the Kernel's replacement-reason constant, `kernel.py:41-42`, transcribed
S28  l.872  [withdrawn — §8 Q1] no substitution; the span stays verbatim
  = | `compose_book`; the replacement book
S29  l.900  [withdrawn — §8 Q1] no substitution; the span stays verbatim
  = | `compose_book` drops created levels
S30  l.902  replace span
  - KS1 (`add_own` omitted)
  + KS1 (own-leg composition omitted)
S31  l.946  [withdrawn — §8 Q1] no substitution; the span stays verbatim
  = (`compose_book`, four arrays, created levels, summed)
S32  l.962  [withdrawn — §8 Q1] no substitution; the span stays verbatim
  = (exact `compose_book` code;
```

### 3.4 v3 (`D-shadow-gate-spec-v3.md`)

```text
S33  l.42  replace span
  - (`view_state`, `kernel.py:179-199`)
  + (its view-state wake signature, `kernel.py:179-199`)
S34  l.45  replace span
  - | F7 | `view_state` includes
  + | F7 | The Kernel's view-state wake signature includes
S35  l.169  replace span
  - (engine `add_own` before `decide()`)
  + (the engine's own-leg composition before `decide()`)
S36  l.268  replace span
  - | `add_own` adds the paper legs
  + | The Kernel's own-leg composition adds the paper legs
S37  l.268  replace span
  - must **not** call `add_own`
  + must **not** apply that composition
S38  l.268  replace span
  - (after `add_own(O)`)
  + (after composing O in)
S39  l.566  replace span
  - | KS1 | `add_own` omitted |
  + | KS1 | Own-leg composition omitted |
```

### 3.5 v2 (`D-shadow-gate-spec-v2.md`)

```text
S40  l.89  replace span
  - `V2Config.hazard_per_minute`
  + the replay engine config's `hazard_per_minute`
S41  l.90  replace span
  - `fill_rule == V2Config.fill_bound`
  + `fill_rule` equals the replay engine config's `fill_bound`
S42  l.94  replace span
  - | `V2Config` field |
  + | Replay engine config field |
S43  l.135  replace span
  - `state.latest["descriptor"].market`
  + the latest descriptor record's market
S44  l.137  replace span
  - (`add_own`, `kernel.py:527-531`)
  + (the Kernel's own-leg composition, `kernel.py:527-531`)
S45  l.137  replace span
  - then `add_own` exactly as the kernel does
  + then the own-leg composition exactly as the Kernel does
S46  l.141  replace span
  - `state.latest["outcome_view"]`
  + the latest outcome-view record
S47  l.142  replace span
  - `state.latest["info_event"]`
  + the latest info-event record
S48  l.144  replace span
  - (`recomputed_portfolio`, `kernel.py:574-601`)
  + (the Kernel's portfolio recomputation, `kernel.py:574-601`)
S49  l.153  replace span
  - | `state.legs`, the legs after the last decision.
  + | The resting legs after the last decision.
S50  l.153  replace span
  - QUOTE sets them (`record_decision`).
  + QUOTE sets them (the Kernel's post-decision state update).
S51  l.155  replace span
  - | `state.last_quote`, the instant of the last QUOTE decision
  + | The instant of the last QUOTE decision (the Kernel's last-quote latch)
S52  l.162  replace span
  - a changed `record_signature` (
  + a changed record signature (
S53  l.164  replace span
  - a reason in `REPLACEMENT_REASONS`,
  + a reason in the Kernel's closed replacement-reason list,
S54  l.165  replace span
  - | `record_decision` (`kernel.py:345-367`)
  + | The Kernel's post-decision state update (`kernel.py:345-367`)
S55  l.187  replace span
  - `add_own` and portfolio assembly
  + the own-leg book composition and portfolio assembly
S56  l.190  replace span
  - kernel `add_own`/`recomputed_portfolio`
  + the Kernel's own-leg composition and portfolio recomputation
S57  l.268  replace span
  - uses `recomputed_portfolio`.
  + uses the Kernel's portfolio recomputation.
S58  l.450  replace span
  - `add_own`, portfolio assembly
  + the own-leg book composition, portfolio assembly
```

---

## 4. The check `[v3.4: replaces v3.3 §6.2 "Check (extended)"]`

**Where and when.** The check is a **scripted step of cutting the handout**. It runs on the **actual handout tree**: the
output directory that holds exactly the §2 files as written, after every substitution. It runs before the manifest is
written. Any hit means no manifest is written and no handout is given out.

The check never runs on a repository checkout, and a plain repository checkout is **never** the handout. Two reasons:
- `\bstate\.[a-z_]` alone matches about 28 other tracked files, including `src/weather/**` code, so a whole-tree run
  would fail falsely;
- a passing run over the wrong tree would prove nothing.

**Rules.** A handout file fails if any line contains:
1. a fenced `python` block, meaning a line that matches `^\s*```\s*python` (case-insensitive);
2. any of the literal strings `def compose_book`, `add_own`, `record_decision`, `replace(value`, `value.book`,
   `state.latest[` (`def compose_book` stays: it marks a code definition, even though the name itself is public,
   §8 Q1);
3. a match of the regex `\bstate\.[a-z_]`;
4. a backtick span (`` `…` `` on one line) that contains a **denied Kernel identifier** as a whole token. The match is
   case-sensitive, and no identifier character `[A-Za-z0-9_]` may touch the token on either side.

**Denied Kernel identifiers (curated, explicit).** These are the distinctive module-level and method names of
`src/maker_core/replay/v2/kernel.py`. The list is the union of the pre-fix build line (`501f47579`) and the U3 head
(`f0d97f11f`), less `compose_book` (moved to the excluded list by §8 Q1):

```text
MAX_OUTPUTS MAX_CLOCK_WINDOWS CAP_FIELDS REPLACEMENT_REASONS V2Config CState _Exclusions
interval_key make_interval coverage_ok book_state freshness_clock view_state record_signature
info_boundaries recomputed_portfolio group_by_instant by_condition
set_legs coverage_touched total_reserve decision_book replacement_book valid_coverage in_clock
event_window record_decision on_trade reset_day add_own
```

**Excluded on purpose.** These are common words, or names shared with handed-out code. Denying them would fail honest
text such as the descriptor field `tick` or the decision input `portfolio`:

```text
D EPSILON POLICIES Interval Kernel __init__ __post_init__ append before changed deadline deadlines
schedule active outputs pull exclude ingest tick portfolio evaluate merged crossed assemble
compose_book
```

`D`, `before`, `changed`, `active`, `pull`, `exclude`, `tick`, `portfolio` and `evaluate` also occur in the handed-out
`policy.py` or `contracts`. `policy.py` names stay exempt, as in v3.3. `compose_book` is excluded for a different
reason: the owner ruled it a public design name (§8 Q1), as the registration draft's C11 row already names it. It stays
on the excluded list, so the drift check still accounts for it. No denied identifier occurs as a token in the
handed-out code files at either commit.

**Deny-list drift.** The cut script extracts every module-level and method name of `kernel.py` at the commit pinned
by §1 (U3's merged build-line head, re-checked at the cut; §8 Q3).
If any name is in **neither** list above, the script refuses. The list is then extended by a text amendment, so a new U3
name cannot pass silently.

State-attribute names (for example `legs`, `latest`, `last_quote`) are covered by rule 3 when they are written as
`state.<attr>`. They are not denied as bare words.

**Fixtures.**
- **MO1** (kept): plant v3.2 l.246 unchanged (skip S6). The check must fail on it.
- **MO2** (new): feed a repository copy (for example the v3.3 copy) as a source. The cut must refuse on the §1 hash pin
  before any line is read.

The oracle PR records the manifest SHA-256, as v3.2.

---

## 5. The oracle's filtered tree: build-line kernel paths `[v3.4: defines "every build-line kernel path"]`

The oracle works in a fresh worktree (v3.1 §6.3 item 1). That worktree is a **filtered tree**, never a plain checkout.
At the build-line commit it is cut from, it excludes these path globs (relative to the repository root):

```text
src/maker_core/replay/**
src/maker_core/shadow/live_kernel.py
src/maker_core/shadow/contract.py
src/maker_core/shadow/runner.py
src/maker_core/shadow/paper.py
src/maker_core/shadow/tape.py
src/maker_core/live/**
src/weather/market/maker_replay_*.py
tests/maker_core/test_replay_*.py
tests/maker_core/test_kernels.py
tests/market/test_maker_replay_*.py
tools/research/maker_replay_v2/**
docs/roadmap/maker-replay-v2-shadow-gate-spec-*
docs/roadmap/agent-report-*-mrv2-*.md
docs/research/maker-replay-v2-registration-DRAFT.md
```

The first six globs are v3.1 §6.3 item 1's deletion set. The rest are build-line files that do one of these:
- import, test, transcribe or quote the Kernel (the mrv2 agent reports quote Kernel functions);
- name the denied strings (the registration draft quotes `state.` attributes, which rule 3 denies; its C11 row also
  names `compose_book`, which is public since §8 Q1 and is not itself a reason to exclude the file).

The §4 check does **not** run over this tree; it runs only on the handout tree. The tree filter is a second, separate
control.

---

## 6. Unchanged from v3.3 §6

§6.1 (the paraphrase of v3.2 §4.1) stands, and S6 applies it. The oracle PR records the manifest SHA-256. The
`ORACLE_SPEC_DERIVED_FROM_KERNEL` label stays: the handout removes code and identifiers, not the transcribed design.
By the owner decision of 2026-10-07 (§8 Q5), v2's prose, including its `kernel.py` line pointers and its description of
Kernel structure, is accepted under that label and handed out as cut by S40-S58.

---

## 7. Spot-check (2026-10-07, coordinator unit H0; re-run after the §8 decisions)

A throwaway scratchpad script (not committed) applied the table to the five pinned sources. It then ran the §4 check
(rules 1-4, with the curated list) over the resulting handout tree. The first run applied all 58 entries with
`compose_book` denied. The re-run applies the 49 live entries (§3) with `compose_book` moved to the excluded list.

| Run | Tree | First run (58 entries) | Re-run (49 entries, §8 applied) |
| --- | --- | --- | --- |
| Raw sources, no substitutions | 5 spec files | 119 hits | 104 hits (the 15 `compose_book` token hits are gone) |
| v3.4 handout, spec texts only | 5 cut files | **0 hits** | **0 hits** |
| Handout plus code and 89a text at `501f47579` | 5 cut files + 4 code files (+ 89a text in the re-run) | **0 hits** | **0 hits** |
| Handout plus code and 89a text at `f0d97f11f` | 5 cut files + 4 code files (+ 89a text in the re-run) | **0 hits** | **0 hits** |
| 89a contract text alone (§1 pin) | 1 file | — | **0 hits** |
| MO1 (S6 skipped) | 5 cut files | 2 hits, exit 1 | **2 hits, exit 1** on the planted v3.2 line (`state.latest[`, `\bstate\.`), as required |
| Deny-list drift (`kernel.py` names only) | `501f47579`, `f0d97f11f` | — | **0 unlisted names** at both (48 and 53 names) |

Handout spec text SHA-256 (LF bytes), re-run:

| File | SHA-256 |
| --- | --- |
| v3.3 handout | `70437cb34b8a77aa9141daaaed4997d9828853f3ba35c0fa4569d71db5485ef0` (unchanged) |
| v3.2 handout | `abd9337c6cf332a694a246f88bbc940a448195e5fcda2b59053244495643d987` (first run: `25d008fa…fdf71`) |
| v3.1 handout | `08f6d87c15995017fb1514511bde61812669b3968c75a0df57d07c9eb2c524d9` (first run: `ca90b169…faa5`) |
| v3 handout | `2c24c9f01c62836edffbd49a2496f76f6751955d16680f4b1b4831b3c3eb9a38` (unchanged) |
| v2 handout | `66668f9c6d8e7ccb138f1a5d6fdede9cd7463f3604146b13efa6159b22c1cacb` (unchanged) |

The code files are identical at both commits: `contracts/__init__.py` `92f9f721…a3b1`, `conformance.py`
`414acf14…e7bb`, `portfolio.py` `23b4d696…8b49`, `policy.py` `60171f9d…62a8`.

These hashes are evidence for this draft only. H1's cut script must reproduce the re-run hashes from the same pins, or
explain the difference, before the Defender tests it.

---

## 8. Owner decisions (2026-10-07)

Relayed by the master agent on 2026-10-07. Points 1-5 are **decided** and applied in this draft. Point 6 is **open**.
The draft as a whole stays DRAFT, NOT IN FORCE until the owner accepts it.

1. **Decided: `compose_book` is not secret.** It is public through the registration draft's C11 row. It is dropped from
   the §4 denied-identifier list and moved to the excluded list. The ten substitutions that existed only to avoid it
   (S4, S9, S13, S14, S23, S25, S28, S29, S31, S32) are reverted: nine are withdrawn and their spans stay verbatim.
   S25 is narrowed to a minimal substitution instead, because its span also holds `state.legs` (rule 3). S10 stays,
   for the literal `def compose_book`, which rule 2 still denies.
2. **Decided: the 89a contract text** is `docs/roadmap/workstation-handoff-2026-09-89a-fill-toxicity-desk-study-tool.md`.
   §1 pins it by full SHA-256, and it passes the §4 check with 0 hits (§7).
3. **Decided: the build-line commit.** The code items and the deny-list drift check are pinned to U3's merged
   build-line head, re-checked at the cut (§1). `501f47579` stays the current byte-identical reference.
4. **Decided: v3.2's Summary is cut** from the handout with Annex K (S2), as v3.3 says. The repository copy keeps it.
5. **Decided: v2's transcription depth.** v2's prose, with its `kernel.py` line pointers and Kernel structure, is
   accepted under the `ORACLE_SPEC_DERIVED_FROM_KERNEL` label (§6). No further amendment.
6. **Open (owner-pending): OD18 and OD21** must still be ruled before the oracle author session
   (`ORACLE-timing-answer.md` §3).
