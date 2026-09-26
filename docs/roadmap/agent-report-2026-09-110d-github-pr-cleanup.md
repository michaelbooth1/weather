# Agent report 2026-09-110d — GitHub PR cleanup

**PASS: all 39 PRs in updated handoff groups A–D CLOSED; 0 SKIPPED.
PRs #91 and #80 retargeted to master and remain OPEN. Open PR count: 63 → 24.**

Executed 2026-09-25 America/Toronto (2026-09-26 03:30–03:33 UTC), using `gh` on the
workstation. Authority is the owner's updated task and
[handoff 110d at ed0489d29ed7978924e158ea983f9229f95bbae5](https://github.com/michaelbooth1/weather/blob/ed0489d29ed7978924e158ea983f9229f95bbae5/docs/roadmap/workstation-handoff-2026-09-110d-github-pr-cleanup.md),
including the added group D retirement decision. No PR was changed under the earlier handoff revision.

## Bound refs and checks

| Ref | Checked commit |
| --- | --- |
| `origin/master` (report branch base) | `e4dcef601b1b67afa9f3c8a6e361ebbb8ff92fb7` |
| `origin/codex/stage2-hold-build-20260921` | `88aa7e43a71d5870575261280b45c9deae667668` |
| `origin/codex/re1-wallet-200-20260923` | `2b9a0ca9e586d510b4aa879fad8f0e7331cfe2c8` |
| `archive/workstation-roll-free-daytime-control-plane-independent-review-2026-09-98a` | `ca75c2e476e865047f07dc9856e5897533834684` |

Every PR was OPEN, in the named repository, and its GitHub head matched its fetched
and live retained remote branch before mutation. Each head was re-read immediately
before its closure. All group A heads passed `git merge-base --is-ancestor` against
the bound master. All group B heads except #13 passed against **both** newer branches.

**#13 used the handoff's explicit archive-tree exception.** Its head is not an ancestor
of either newer branch. It is exactly the archived 98a commit above (so archive ancestry
also passes), and both trees are `1c2a7fd18dacc84c6a0e9abd4afe837c0bab3801`.
The mandated group B comment was posted verbatim; its newer-branch containment wording
does not describe #13's proof. The archive exception, not newer-branch ancestry,
is the actual basis for that closure.

Groups C and D have no stated ancestry gate: group C explicitly closes retained
research lineage without merge; group D is the explicit owner retirement decision.
Their remote branches were verified retained. The `deployed/*` tags were present
in the fetched/live remote inventory; this task did not inspect production runtime
or independently requalify the production-source claims in the supplied comment.

## Per-PR results

Each CLOSED result below was read back through `gh pr view`, with unchanged head,
null `mergedAt`, and an exact match for the required comment. The result links point
to the verified closing comments. No PR was skipped.

| PR | Group | Result / comment receipt | Verified head | Check |
| --- | --- | --- | --- | --- |
| #92 | A | [CLOSED](https://github.com/michaelbooth1/weather/pull/92#issuecomment-5842794721) | `cb759b2b907d65adfcb1c507b4a1913f45fde972` | Ancestor of master: PASS |
| #89 | A | [CLOSED](https://github.com/michaelbooth1/weather/pull/89#issuecomment-5842794928) | `0f40e8608dcd7b4a76ab932da84ce591911b5a5b` | Ancestor of master: PASS |
| #88 | A | [CLOSED](https://github.com/michaelbooth1/weather/pull/88#issuecomment-5842795154) | `265b5150f1e32427b920dac0315a8e33c5bbc7ab` | Ancestor of master: PASS |
| #75 | A | [CLOSED](https://github.com/michaelbooth1/weather/pull/75#issuecomment-5842795357) | `7edd82ebb37bdc423fd7978a4b64344a833f07c1` | Ancestor of master: PASS |
| #73 | A | [CLOSED](https://github.com/michaelbooth1/weather/pull/73#issuecomment-5842795561) | `7a78ff1b56c11c0ad90800ce0433b2ad44901488` | Ancestor of master: PASS |
| #23 | A | [CLOSED](https://github.com/michaelbooth1/weather/pull/23#issuecomment-5842795778) | `54da9076c10e6d109062c635211fcd273022f94e` | Ancestor of master: PASS |
| #22 | A | [CLOSED](https://github.com/michaelbooth1/weather/pull/22#issuecomment-5842795979) | `5e9b60e9d9f346346c0d8ef7de751fc43130d402` | Ancestor of master: PASS |
| #18 | A | [CLOSED](https://github.com/michaelbooth1/weather/pull/18#issuecomment-5842796217) | `aea427fb7faf0b5fd67b8893b62b11fe649e71ea` | Ancestor of master: PASS |
| #6 | B | [CLOSED](https://github.com/michaelbooth1/weather/pull/6#issuecomment-5842797484) | `ca64296fb944a65c0ccfbf0e9a17b2d913413a68` | Ancestor of both newer branches: PASS |
| #13 | B | [CLOSED](https://github.com/michaelbooth1/weather/pull/13#issuecomment-5842797758) | `ca75c2e476e865047f07dc9856e5897533834684` | 98a identical commit/tree: PASS |
| #21 | B | [CLOSED](https://github.com/michaelbooth1/weather/pull/21#issuecomment-5842797998) | `244d8ababbae76bfa4d9b42b75665782f4c98487` | Ancestor of both newer branches: PASS |
| #24 | B | [CLOSED](https://github.com/michaelbooth1/weather/pull/24#issuecomment-5842798253) | `644bc8acb86e3f2e13526f54c0f1e0c14ff27fad` | Ancestor of both newer branches: PASS |
| #25 | B | [CLOSED](https://github.com/michaelbooth1/weather/pull/25#issuecomment-5842798467) | `8a665a8a21a6c9a8dd5009d7b94ac883c9c88efc` | Ancestor of both newer branches: PASS |
| #26 | B | [CLOSED](https://github.com/michaelbooth1/weather/pull/26#issuecomment-5842798687) | `06979f4a577bd20f00c9ef2606f1030d3218dd8a` | Ancestor of both newer branches: PASS |
| #27 | B | [CLOSED](https://github.com/michaelbooth1/weather/pull/27#issuecomment-5842798907) | `a679e1847e4cdbc4f17bd636b65b8a959f5ef0e0` | Ancestor of both newer branches: PASS |
| #28 | B | [CLOSED](https://github.com/michaelbooth1/weather/pull/28#issuecomment-5842799133) | `0a0804f0721e1e0942cd8d302b5d2b01785491e8` | Ancestor of both newer branches: PASS |
| #40 | B | [CLOSED](https://github.com/michaelbooth1/weather/pull/40#issuecomment-5842799345) | `2027991c1af107d6e72ffec0255c61e00e59c9af` | Ancestor of both newer branches: PASS |
| #41 | B | [CLOSED](https://github.com/michaelbooth1/weather/pull/41#issuecomment-5842799573) | `96c3c1286958a4f6c5c7ac5acab4b1f29808affa` | Ancestor of both newer branches: PASS |
| #42 | B | [CLOSED](https://github.com/michaelbooth1/weather/pull/42#issuecomment-5842799821) | `c2e0765dd65e666a7e461c7387ccd268b0c1ebb3` | Ancestor of both newer branches: PASS |
| #49 | B | [CLOSED](https://github.com/michaelbooth1/weather/pull/49#issuecomment-5842800094) | `7150bc3c735027ffc8478274928d7b42cbc2af3b` | Ancestor of both newer branches: PASS |
| #50 | B | [CLOSED](https://github.com/michaelbooth1/weather/pull/50#issuecomment-5842800326) | `87091e1171ebfb52d6c00457db6e4c7d902927d3` | Ancestor of both newer branches: PASS |
| #51 | B | [CLOSED](https://github.com/michaelbooth1/weather/pull/51#issuecomment-5842800576) | `ff8936f24ad0cc8a0cec0fee1628a2291e775574` | Ancestor of both newer branches: PASS |
| #53 | B | [CLOSED](https://github.com/michaelbooth1/weather/pull/53#issuecomment-5842800868) | `09814ea49008f5b17ddaaa94d9331ead2d991c99` | Ancestor of both newer branches: PASS |
| #7 | C | [CLOSED](https://github.com/michaelbooth1/weather/pull/7#issuecomment-5842801868) | `2e20e59aae08e7367dc79e1b8102c0551e7f6904` | Research-lineage authorization; branch retained |
| #8 | C | [CLOSED](https://github.com/michaelbooth1/weather/pull/8#issuecomment-5842802166) | `e7d61f0b1425c84bc50ff21fd13329f6d9e8a47a` | Research-lineage authorization; branch retained |
| #9 | C | [CLOSED](https://github.com/michaelbooth1/weather/pull/9#issuecomment-5842802376) | `9a403705309f784066de6d34af98e817049f7952` | Research-lineage authorization; branch retained |
| #10 | C | [CLOSED](https://github.com/michaelbooth1/weather/pull/10#issuecomment-5842802615) | `41236d7935cdc7c2a039606a8d3810383b6aaf1f` | Research-lineage authorization; branch retained |
| #12 | C | [CLOSED](https://github.com/michaelbooth1/weather/pull/12#issuecomment-5842802829) | `2ae55453133b7e8108132d45555dbd8a316d3914` | Research-lineage authorization; branch retained |
| #14 | C | [CLOSED](https://github.com/michaelbooth1/weather/pull/14#issuecomment-5842803167) | `f8c70762e4204ad7e90f310411d9eeeeb2f3b820` | Research-lineage authorization; branch retained |
| #15 | C | [CLOSED](https://github.com/michaelbooth1/weather/pull/15#issuecomment-5842803346) | `2a231f9d5f0351dffce854b7e29398636f648fdd` | Research-lineage authorization; branch retained |
| #52 | C | [CLOSED](https://github.com/michaelbooth1/weather/pull/52#issuecomment-5842803568) | `1ed125ca64c0611e4716476bf76eb642313a5a64` | Research-lineage authorization; branch retained |
| #45 | D | [CLOSED](https://github.com/michaelbooth1/weather/pull/45#issuecomment-5842804312) | `4e37b5c1cfa19ba6d01bd445af0ffa1d20b74f7c` | Owner retirement authorization; branch retained |
| #64 | D | [CLOSED](https://github.com/michaelbooth1/weather/pull/64#issuecomment-5842804545) | `241663fc491b33765569395164ab42be6702535e` | Owner retirement authorization; branch retained |
| #66 | D | [CLOSED](https://github.com/michaelbooth1/weather/pull/66#issuecomment-5842804777) | `8709141901882f2635c80deba72f4294ca0da48e` | Owner retirement authorization; branch retained |
| #67 | D | [CLOSED](https://github.com/michaelbooth1/weather/pull/67#issuecomment-5842804960) | `021cd6d387ce2c76e240b00cff8f2da73fd5231e` | Owner retirement authorization; branch retained |
| #71 | D | [CLOSED](https://github.com/michaelbooth1/weather/pull/71#issuecomment-5842805146) | `8c6826d7cd093c5b98c8e68e1fca52507ac6ebb5` | Owner retirement authorization; branch retained |
| #72 | D | [CLOSED](https://github.com/michaelbooth1/weather/pull/72#issuecomment-5842805404) | `324b360dbe4a3c278e61e2151565362586159040` | Owner retirement authorization; branch retained |
| #69 | D | [CLOSED](https://github.com/michaelbooth1/weather/pull/69#issuecomment-5842805707) | `7dda3847e094cde9384c2b331df5d4828db9d0c0` | Owner retirement authorization; branch retained |
| #70 | D | [CLOSED](https://github.com/michaelbooth1/weather/pull/70#issuecomment-5842805927) | `bf1580c8c61f236c29fe5401da3847e8d715c315` | Owner retirement authorization; branch retained |

## Exact comments posted

Group A:

> Closing: this branch was merged into master locally through the quiet-window/light-path tool (the head is an ancestor of origin/master), so GitHub never registered the merge. No content is lost.

Group B:

> Closing as superseded: every commit here is contained in a newer tracked branch (codex/stage2-hold-build-20260921 or codex/re1-wallet-200-20260923). The branch is retained; nothing is dropped.

For #6, appended exactly:

> origin/codex/live-gate-provenance-20260831 remains the execution PC's recorded lineage and must not be deleted.

Group C:

> Closing without merge: September workstation research lineage, recorded in ESTABLISHED_FINDINGS §1m as evidence that by design never lands on master. The branch stays.

Group D:

> Closing: retired by owner decision 2026-09-25. Storage is now handled by closed-day compression and the verified archive path; the qualification problem was solved by the fixed bounded suite. The branches are retained, and the exact sources that ran in production are preserved as `deployed/*` tags. A future need gets a small fresh branch, not this stack.

## Retargets and remaining open PRs

| PR | Previous base | Previous base commit | Result |
| --- | --- | --- | --- |
| [#91](https://github.com/michaelbooth1/weather/pull/91) | `codex/reward-test-attended-handoff-20260921` | `200e222d90f140abdcf148f65c59a0fe7f1292e9` | Base ancestry PASS; base changed to `master`; OPEN; head unchanged |
| [#80](https://github.com/michaelbooth1/weather/pull/80) | `codex/integrate-1-research-20260921` | `c04200081e87b4607c149cb502ce34b4ad7410cf` | Base ancestry PASS; base changed to `master`; OPEN; head unchanged |

At **2026-09-26 03:33:54 UTC**, `gh pr list --repo michaelbooth1/weather --state open
--limit 200 --json number` returned **24** open PRs:

#29, #30, #38, #54, #55, #65, #68, #74, #76, #77, #78, #80, #81, #82, #83, #84,
#85, #86, #90, #91, #93, #94, #95, #96.

The final open set is exactly the original open set minus the 39 authorized closures.
All remaining titles, heads and bases match the initial snapshot, except the two
requested base changes. #76 and #77 were not listed for action and were untouched,
as were all other protected PRs. The report is published as a docs branch, without
creating an additional PR that would change this post-cleanup count.

The before/after `git ls-remote --heads --tags origin` inventories were identical
(295 ref records, including annotated-tag dereferences). All branch tips and tags
were preserved, including `codex/live-gate-provenance-20260831`. This comparison was
made before publishing the new report branch.

## Reproduction and validation

Run from a fetched checkout. The commit hashes in the table bind the observed
checks even if branch names subsequently advance. Use `gh` on the workstation;
production does not have it.

```powershell
git fetch origin
git show ed0489d29ed7978924e158ea983f9229f95bbae5:docs/roadmap/workstation-handoff-2026-09-110d-github-pr-cleanup.md
gh pr view 92 --repo michaelbooth1/weather --json state,headRefOid,mergedAt,comments
git merge-base --is-ancestor cb759b2b907d65adfcb1c507b4a1913f45fde972 e4dcef601b1b67afa9f3c8a6e361ebbb8ff92fb7
git merge-base --is-ancestor ca64296fb944a65c0ccfbf0e9a17b2d913413a68 88aa7e43a71d5870575261280b45c9deae667668
git merge-base --is-ancestor ca64296fb944a65c0ccfbf0e9a17b2d913413a68 2b9a0ca9e586d510b4aa879fad8f0e7331cfe2c8
git rev-parse 'ca75c2e476e865047f07dc9856e5897533834684^{tree}'
git rev-parse 'archive/workstation-roll-free-daytime-control-plane-independent-review-2026-09-98a^{tree}'
gh pr view 91 --repo michaelbooth1/weather --json state,headRefOid,baseRefName
gh pr view 80 --repo michaelbooth1/weather --json state,headRefOid,baseRefName
gh pr list --repo michaelbooth1/weather --state open --limit 200 --json number --jq length
git ls-remote --heads --tags origin
```

For each authorized PR, the mutation was `gh pr close <number> --repo
michaelbooth1/weather --comment <exact group comment above>` after its checks.
The two base mutations were `gh pr edit 91 --repo michaelbooth1/weather --base master`
and `gh pr edit 80 --repo michaelbooth1/weather --base master`. All returned exit 0.
Do not re-run those mutations to reproduce the read-only verification.

Documentation validation: focused `tests/reporting/test_roadmap_backlog.py` and
`tests/reporting/test_correspondence_index.py` ran through
`scripts/ops/workstation_heavy.ps1`: **19 passed**. The command used project CPython,
`-m pytest`, those exact two files, `-q`, and an isolated `--basetemp`.
The report's correspondence index is regenerated after the report commit so its
Git-added date is available; the generated index is part of the docs handback.
Backlog parity and correspondence-index parity passed. The agent documentation
audit passed (18 agent files, 969 Markdown files); Git whitespace checks passed.

## Publication and boundaries

- Docs branch: `codex/docs-github-pr-cleanup-110d-20260925`.
- Initial report commit: `30a4740d40b24d62e693599667a2ef253c89e5a9`; the follow-up
  docs commit adds the generated index and these validation/publication details.
- Base: `e4dcef601b1b67afa9f3c8a6e361ebbb8ff92fb7` (fresh `origin/master`).
- Isolated workstation worktree: `C:/Users/Michael/Documents/github/weather/scratch/w/github-pr-cleanup-110d`.
- Only the report and its required generated correspondence-index update belong to this change.
- Existing worktrees and the original clean `master` checkout were preserved.

| Changed file | Per-file roll disposition |
| --- | --- |
| `docs/roadmap/agent-report-2026-09-110d-github-pr-cleanup.md` | Roll-free documentation under delegation §3; no Python import closure change |
| `docs/roadmap/correspondence-index.md` | Roll-free generated documentation under delegation §3; no Python import closure change |

Production closure evidence was not accessed; no production-host roll verdict or
adoption is claimed. The production integration owner retains its normal
`scripts/ops/roll_verdict.ps1 -Branch <branch>` gate if this docs branch is adopted.

**Not done:** no merge (Git or GitHub), branch deletion, force-push, Scheduler
registration/change, capture restart, production runtime write, model change,
credential operation, or trading action. No other PR was closed, edited or commented on.
