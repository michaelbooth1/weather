# Maker replay v2 gate spec v3.4, erratum 1 (SIGNED 2026-10-12): §2/§5/§8 amendment for the oracle handout

> **SIGNED (owner, relayed by master-agent, 2026-10-12 ~20:00; DECISION_LOG 2026-10-12).** E1, E3 and E5 are signed as written (E-R1); E-R2 is
> ruled `501f47579` plus re-bind (U3 is on the build line at `1fd0c295f`; re-bind PASS); E-R3/E-R4 are ruled
> option A plus N1. It amends [v3.4](maker-replay-v2-shadow-gate-spec-v3.4-DRAFT-2026-10-07.md) §2, §5 and §8 only.
> The filename keeps its DRAFT date stamp so links stay stable. It follows v3.4's own amendment rule ("Add a new dated file rather than editing
> this copy"), so the accepted file is not edited. It grants no run, cut, transfer, handout or merge authority.
> Owner item: [item 330](items/item-330-maker-economics-refocus-master-plan.md). Status of maker replay v2 and of the
> handout lives in [the state of play](../operations/STATE_OF_PLAY.md), never here.
>
> **Read when** reviewing or signing the H1 handout cut, the host isolation for the oracle author, or the H-11/H-12
> drafts. Companions (all DRAFT, same date): [the H-11 rulings sheet r2](maker-replay-v2-shadow-gate-spec-v3.4-oracle-rulings-r2-DRAFT-2026-10-12.md),
> [the H-12 cover note draft](maker-replay-v2-shadow-gate-spec-v3.4-oracle-cover-note-H12-DRAFT-2026-10-12.md) and
> [the host isolation runbook](maker-replay-v2-shadow-gate-spec-v3.4-oracle-host-isolation-runbook-DRAFT-2026-10-12.md).
>
> **Not a handout item.** Its filename matches the v3.4 §5 exclusion `docs/roadmap/maker-replay-v2-shadow-gate-spec-*`,
> so it is never in the oracle's filtered tree or handout.
>
> **Update when** the owner signs, amends or rejects any proposal below. After signature, a later change is erratum 2,
> in a new dated file.

Workstation unit H1, 2026-10-12. Spec text and cut tooling only; the workstation never authors, drafts or sketches the
oracle (OD18 (b)). Inputs: the H1 scoping note of 2026-10-07 (workstation-only, gaps G1-G6), v3.4 as accepted, the
DECISION_LOG rows of 2026-10-07..10-09 and two dry-run cuts on the workstation (below). No data, panel or settlement row
was read.

## E0. What v3.4 already carries, and what is left

The H1 scoping note found six gaps (G1-G6) in the v3.4 draft at `edd06750c`. The acceptance-day edits (v3.4 §2 item 6,
§5 and §8 points 6-7) closed most of them:

| Gap | v3.4 as accepted | Left for this erratum |
| --- | --- | --- |
| G1 author (OD18 (b)) | §5 "Author" and §8 point 6 | §2 has no cover-prompt item although the cut script writes H-12 and the 2026-10-07 DECISION_LOG row says the production agent writes it (E1); the oracle PR does not have to record the author session's agent, model and harness (E1) |
| G2 cut commit | §5 "Commit" (R2: cut at `501f47579`, re-bind on U3's merge) | what a re-bind does and does not re-cut; what happens if the owner wants the cut at a later build-line head (E2) |
| G3 clean room | §5 "Clean room" (R1: standalone parentless repository) | R1 fixes the repository's form, not who can read what on the host, and the repository is public on GitHub (E4) |
| G4 glob holes | §5 R4, R4b, glob semantics, engine-output shape | output controls on the written cut (E3, stricter-only) |
| G5 rulings in the handout | §2 item 6 (sheet r1) | the OD23 wording was signed on 2026-10-08 and later rulings exist; sheet r2 is drafted separately |
| G6 timing and re-hand | not in v3.4 | the re-hand, re-bind and after-look rules (E5); dated targets stay out of the spec |

## E1. §2 rule 2: add the cover prompt as item 7 (G1)

Proposed text, appended to v3.4 §2 rule 2 after item 6:

> 7. **The cover prompt** (H-12): the exact session prompt the production agent gives the oracle author. By the
>    2026-10-07 DECISION_LOG row (OD18), the production agent writes it; the workstation may supply a draft only. It is
>    handed out byte-identical, pinned by the SHA-256 of its raw bytes at the cut, and §4-checked like every other
>    handout file. Anything said to the author outside the bound handout is an unhashed channel and is not allowed; a
>    later instruction is a re-hand (E5). A manifest without a signed cover prompt is not bindable (the cut script
>    marks it `bindable: false`).

Proposed text, appended to v3.4 §5 "Author":

> The oracle PR records, besides the manifest SHA-256 (v3.2 §6), the author session's agent, model, harness and harness
> version, and the start and end time of the session. The production agent starts the session; the author never
> chooses its own inputs.

## E2. §5 "Commit": what a re-bind covers (G2)

Measured on the workstation, 2026-10-12, with the cut script on this erratum's branch:
- At `501f47579` the cut completes: filtered tree `b3f1e258`, 2,748 files, the same tree as the 2026-10-07 dry-run.
  Two cuts give byte-identical manifests, file lists and tars.
- The build line is now `155848313`. The four code items and the 89a text are byte-identical there (same git blob ids
  as at `501f47579`), so a re-bind to it passes. U3 (the W1/W2/F3 gate logic) is **not** merged into it.
- A cut **at** `155848313` refuses: three files added to the build line since `501f47579` (the export-gate wiring) name
  the v1 replay package outside every glob, and none is on the R4b list. Paths and reason classes: a nightly export
  wrapper script (path mention), a plugin runner module (package import) and its gate test (string literal).

Proposed text, appended to v3.4 §5 "Commit":

> A re-bind (R2) re-checks only the four code items and the 89a text at the new commit. It does **not** re-cut the
> filtered tree: the author keeps the snapshot of the cut commit, and the manifest binding is unchanged. A cut at a
> later build-line head is a new handout revision (E5); it needs the R4b list re-reviewed at that head, and every new
> entry is a recorded ruling of the master agent, as R4b was.

Ruling requested (E-R2): keep the cut at `501f47579` with a re-bind when U3 merges (recommended: the snapshot the
author needs, the contracts and `decide()`, is byte-identical at every head measured), or cut at U3's merged head
after an R4b extension for the three files above.

## E3. §5: output controls on the written cut (G4, stricter-only)

The 2026-10-07 DECISION_LOG row allows the production agent stricter-only rulings on the handout's form. These controls
are implemented on this erratum's branch in `tools/research/maker_replay_v2_h1_cut.py` and measured at **0 hits** at
both `501f47579` and `155848313` (the only blob match is the empty file, which is exempt).

Proposed text, appended to v3.4 §5 after "Engine-output shape":

> - **Output controls (erratum 1, stricter-only).** (1) Any kept tree file that carries a §4 rule-2 literal refuses,
>   whatever its path, and cannot be withheld by the R4b list. (2) Any kept tree file byte-identical (same git blob)
>   to a glob-excluded or withheld file refuses, except the empty file. (3) The cut writes `filtered-files.sha256`, the
>   SHA-256 of every tree file, and records its hash in the manifest. (4) Before the manifest is written, the cut
>   re-reads every output byte from disk: the handout as written passes §4 again, the working tree, the committed
>   blobs and the file list agree, the tar rebuilds from the snapshot's own blobs, no tree path matches a glob or a
>   replay-v2 name, the output holds no other file, and R1 holds. The same check runs on the host after transfer
>   (`verify --binding <manifest SHA-256>`), reading nothing outside the cut directory.

Considered and **not** proposed: refusing the strings `replay_v2` and `replay.v2` in the tree. They hit four files at
`501f47579` (the admission hook, the admission script and two admission tests: process names, not engine text) and two
more at `155848313`, which R4 already refuses. The curated Kernel identifiers are not scanned in the tree either: they
collide with generic names elsewhere, which is why v3.4 §4 runs only on the handout.

## E4. §5: host isolation (G3)

Proposed text, appended to v3.4 §5 "Clean room":

> R1 fixes the repository's form. **Host isolation** fixes what the author session can reach: on the capture host,
> the session can read only the cut directory (the handout and the standalone repository); it cannot read the
> production clone, any other worktree or clone, the workstation-state folders, `data/`, other user profiles or the
> frozen spec sources, and it holds no repository credential. The production agent prepares and checks this before
> the session starts, by [the host isolation runbook](maker-replay-v2-shadow-gate-spec-v3.4-oracle-host-isolation-runbook-DRAFT-2026-10-12.md),
> and records the check results with the oracle PR. **Residual exposure:** the repository is public on GitHub, so the
> build line is reachable over the network from any session with web or shell egress. The mechanism that closes or
> accepts that exposure is the owner's ruling (E-R4).

Rulings requested: E-R3 (isolation mechanism) and E-R4 (network egress); the runbook lists the options and a
recommendation for each.

## E5. §5: re-hand, re-bind and after the look (G6)

Proposed text, a new §5 paragraph:

> **Revisions.** The signed text is the bytes of every handout file (H-1..H-12) plus the filtered snapshot.
> - Any byte difference (an owner amendment, a changed code item, a new erratum, a rulings-sheet or cover-prompt
>   change, a cut at a new commit) is a **re-hand**: cut revision rN+1 from scratch, re-run every check, record the
>   new manifest SHA-256 in a dated repository file with a `supersedes rN` line, and give the author the complete
>   rN+1 handout plus a §4-checked file-level diff from rN. The oracle PR lists every manifest SHA-256 it received, in
>   order.
> - A **re-bind** (only the pinned commit changes, every handout and snapshot byte is identical) is a recorded
>   re-bind note with the new commit and the same hashes. Nothing is re-handed.
> - **Before the look**, the binding (the manifest SHA-256) is recorded in a dated, docs-only repository file whose
>   name matches the §5 exclusion globs, in the oracle PR and in the cohort binding (v3.2 §10).
> - **After the look**, a re-hand is allowed only by erratum, citing the 89a contract or a spec sentence, never Kernel
>   code; it is §4-checked before hand-over and disclosed in the cohort receipt. It never replaces the pre-look binding.

Dated targets (the scoping note's "H1 by about 10-10") stay out of the spec: timing lives in the state of play.

## E6. §8: record of this erratum

Proposed new §8 point, written in on signature:

> 8. **Erratum 1** (signed 2026-10-12): E1 (cover prompt as §2 item 7; author session recorded in the PR), E2 (re-bind
>    scope; cut commit per E-R2), E3 (output controls), E4 (host isolation per E-R3 and E-R4), E5 (revisions).

## Rulings requested

| Id | Question | Recommendation |
| --- | --- | --- |
| E-R1 | Sign E1, E3 and E5 as written | Yes. E3 is stricter-only, measured at 0 hits on both heads |
| E-R2 | Cut commit: `501f47579` plus a re-bind at U3's merge, or a cut at the merged head after an R4b extension | `501f47579` plus re-bind |
| E-R3 | Host isolation mechanism | A dedicated standard local account with NTFS deny rules (runbook option A); a VM if the host edition allows it |
| E-R4 | Network egress of the author session (public GitHub exposure) | Shell commands without network (harness sandbox), web tools disabled, transcript audit afterwards; the residual risk accepted and disclosed with the oracle PR |
