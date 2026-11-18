# Maker replay v2 oracle: host isolation runbook for the author session (DRAFT, 2026-10-12)

> **Rulings I-1..I-7 given by the owner 2026-10-12 (relayed by master-agent; DECISION_LOG 2026-10-12): option A,
> N1, a fresh Claude Code author session, master-run test wrapper, read-only archive. The master agent fills the
> placeholders on the host; it grants no authority beyond the steps below.**
> It proposes the steps the production (master) agent runs on the capture host so the clean-room oracle author can read
> only the cut directory. It implements [erratum 1](maker-replay-v2-shadow-gate-spec-v3.4-erratum-1-DRAFT-2026-10-12.md)
> E4 (G3). Owner item: [item 330](items/item-330-maker-economics-refocus-master-plan.md); status lives in
> [the state of play](../operations/STATE_OF_PLAY.md). Host load and Scheduler rules stay owned by
> [the host load policy](../operations/HOST_LOAD_POLICY.md) and [the operations agent role](../operations/OPERATIONS_AGENT_ROLE.md).
>
> **Read when** preparing, checking or tearing down the oracle author's session on the capture host.
>
> **Not a handout item.** Its filename matches the v3.4 §5 exclusion `docs/roadmap/maker-replay-v2-shadow-gate-spec-*`,
> and the author never receives it.
>
> **Update when** the owner rules I-1..I-7, the host's edition or accounts change, or a check below fails in practice.

Paths are placeholders, filled by the master agent from the host: `<PROD_CLONE>` (the production clone),
`<WORKTREES>` (every pinned or deployed worktree and other clone), `<LDATA>` (the workstation-state and handoff
folders), `<SOURCES>` (the frozen spec sources the cut reads), `<CUT_DIR>` (the new cut directory; H-12 r1 fixes it as
`C:\oracle-cut\r1`), `<AUTHOR>` (the author account), `<OPERATOR>` (the master agent's account). No step reads `data/` contents, credentials or `.env*` files; the checks only prove the author cannot.

## 1. Mechanism (ruling I-1)

| Option | What it is | Assessment |
| --- | --- | --- |
| **A. Dedicated local account** (recommended) | A new standard (non-administrator) local account `<AUTHOR>` that owns nothing else; the author harness runs as it. NTFS grants it only `<CUT_DIR>`; explicit deny entries on the sensitive roots. | Works on every Windows edition, including Home. Isolation is by the OS, not by the harness. Cost: one account, a profile, a harness install under it. |
| B. VM or Windows Sandbox | The cut directory copied into a VM or Sandbox; nothing else mounted. | Strongest file isolation; needs Pro/Enterprise (Hyper-V or Sandbox) and RAM the 16 GB capture host is short of during capture. Use only if the edition allows and the session runs outside the protected windows. |
| C. Harness permissions only | The author runs as the operator's account with the harness's directory allow-list. | **Rejected**: the account can read every clone; one tool call outside the allow-list (or a harness bug) reaches the build line. |

## 2. Preparation (master agent, operator account, outside the 12:00-18:00 graded window)

1. **Cut on the host.** Run the cut script from the build line at the ruled commit (erratum 1 E-R2) with the plan that
   names the signed H-11 and H-12, into a new empty `<CUT_DIR>` outside every clone and outside the operator profile
   (for example a top-level folder). Record the manifest SHA-256.
2. **Verify.** `python tools/research/maker_replay_v2_h1_cut.py verify --out <CUT_DIR> --binding <MANIFEST_SHA256>`
   must exit 0. It reads only `<CUT_DIR>`.
3. **Account (option A).** Create `<AUTHOR>` as a standard local user with a generated password the master agent never
   writes into a repository, a chat or a log (the owner sets or holds it; I-2). Not a member of Administrators,
   Remote Desktop Users or any group that holds rights on the clones.
4. **Grant.** `icacls <CUT_DIR> /inheritance:r /grant:r "<AUTHOR>:(OI)(CI)RX" "<OPERATOR>:(OI)(CI)F" "SYSTEM:(OI)(CI)F" "Administrators:(OI)(CI)F"`
   (`<OPERATOR>` is the master agent's own account: `/grant:r` would otherwise remove it, and the post-ACL verify,
   the test results and the hand-back need it),
   then `icacls <CUT_DIR>\oracle-repo /grant "<AUTHOR>:(OI)(CI)M"`. The author reads `handout\` and the cut's
   top-level files and modifies only `oracle-repo\` (it commits there) and the exchange folders of step 8.
5. **Deny.** Profiles are asserted, not deny-ACLed (master agent, 2026-10-12): every profile root under `C:\Users`
   must grant no allow entry to Users, Authenticated Users, Everyone or INTERACTIVE, and neither may `<PROD_CLONE>`,
   its `.git`, `data`, `src`, `venv` or `config`; any such grant stops the setup for the master agent's call. For each
   non-profile root (`<WORKTREES>`, `<LDATA>`, `<SOURCES>` and every other top-level folder the master agent lists,
   unless recorded as allowed with a reason): `icacls <path> /deny "<AUTHOR>:(OI)(CI)RX"`. Deny entries are added,
   never replacing the existing ACL, so the capture workers' access is unchanged. Record the exact list; the owner
   signs it (I-3).
6. **Scheduler.** The author account gets no scheduled task and no logon-as-batch right; nothing the Scheduler or the
   S4U guard runs is started under it.
7. **Harness.** Install or point the agent harness for `<AUTHOR>` (ruling I-5) with no stored repository credential,
   no MCP connector, web search and web fetch disabled, and shell commands sandboxed without network where the
   harness supports it (ruling I-4; Claude Code's shell sandbox is not available on native Windows, so this is
   recorded and the residual stays disclosed, §6). Permission mode (ruling I-8): `acceptEdits`, with deny rules for
   `WebFetch`, `WebSearch` and `mcp__*`, bypass mode disabled, and a Bash allow-list of `git status`, `git diff`,
   `git log`, `git add`, `git commit`, `git switch`, `git checkout -b` and `git bundle create` only; every other
   command prompts the owner at the machine. Claude Code cannot confine shell commands to a directory, so the NTFS
   rights of steps 4-5 remain the boundary. The cut is owned by `<OPERATOR>`, so git refuses it to `<AUTHOR>` as dubious
   ownership: add exactly `<CUT_DIR>/oracle-repo` to the author's global `safe.directory`, nothing broader.
8. **Exchange folders (H-12 r1), after the §3 verify row.** Create `<CUT_DIR>\questions`, `test-requests`,
   `test-results` and `handback`, then `icacls <CUT_DIR>\<folder> /grant "<AUTHOR>:(OI)(CI)M"` for `questions`,
   `test-requests` and `handback` only; `test-results` keeps the inherited read-only grant (the coordinator writes
   it). Create them last: `verify` refuses any top-level entry the cut did not write.

## 3. Checks (run as `<AUTHOR>`, before the session starts; record every output)

| Check | Expected |
| --- | --- |
| `dir <PROD_CLONE>`, each `<WORKTREES>` entry, `<LDATA>`, `<SOURCES>`, `<PROD_CLONE>\data`, other profiles | access denied for every one |
| `git -C <PROD_CLONE> rev-parse HEAD` | fails (no access) |
| `set GIT` and `set` | no `GIT_*` variable; no variable pointing into a clone |
| `cmdkey /list`; `git config --global --list` | no stored credential; no credential helper |
| `git -C <CUT_DIR>\oracle-repo remote -v`; `for-each-ref`; `rev-list --all --count`; `.git\objects\info\alternates` absent | no remote, one ref, one commit, no alternates |
| `python tools/research/maker_replay_v2_h1_cut.py verify --out <CUT_DIR> --binding <MANIFEST_SHA256>` run from a copy outside the cut, or the master agent's own verify re-run after the ACL change | exit 0 (the ACL change did not alter a byte) |
| Egress (I-4) | web tools denied and no MCP server listed; the shell sandbox, where supported, refuses a request to the public repository host (on native Windows it is unsupported: record reachability, disclosed under §6) |
| Permission mode (I-8) | `/permissions` shows the I-8 deny and allow rules; bypass mode disabled |

Any unexpected result stops the session; the master agent fixes and re-runs every check.

## 4. Session

- The production agent starts the session as `<AUTHOR>` with the signed H-12 as its prompt, and records start time,
  agent, model, harness and version (erratum 1 E1).
- Tests run only as H-12's `<TEST_RULE>` says. Ruling I-6: the author account cannot take the workload lease, so the
  author runs quick unit tests only, inside `<CUT_DIR>`, during 00:30-09:00, through a wrapper the master agent runs
  and that holds the lease on the author's behalf; heavier tests run after hand-back under the master agent's lease.
- **Shared-model disclosure (ruling I-5).** The author is a fresh Claude Code session (web tools off), the same
  harness and model family that wrote the gate logic. The owner explicitly accepted this limit on the oracle's
  independence on 2026-10-12. The oracle PR states it, with the session's agent, model, harness and version (E1).
- Questions go to `<CONTACT>`; answers come back only as a re-hand (erratum 1 E5).

## 5. Hand-back and teardown

1. The author leaves its branch in `oracle-repo/`. The master agent, as the operator account, creates a git bundle (or
   format-patch series) of that branch only, checks that its base is the snapshot commit, and imports it onto the build
   line under v3.2 §6 (coordinator import, then the deletion commit).
2. Archive `<CUT_DIR>` and the full session transcript read-only, in a folder outside every clone, kept until the
   cohort receipt is signed (ruling I-7); audit the transcript for any
   network call, any path outside `<CUT_DIR>` and any tool outside the allowed set (the N1 audit), and record the
   result beside the archive and with the oracle PR.
3. Disable `<AUTHOR>` and remove its deny entries only after the archive; do not delete the account's profile until the
   oracle PR is merged or abandoned.

## 6. Residual exposure

The repository is public on GitHub, so the build line, including the engine, is reachable from any session with
network egress. Option A closes file access, not the network. Closing it fully needs the network sandbox (I-4), a VM
without network (option B), or making the repository private for the session's duration (an owner decision outside
this runbook). Whatever is ruled is disclosed with the oracle PR.

The author's test venv holds pytest, its Windows runtime dependencies and `tzdata==2026.3` only (the oracle needs
tzdata for local midnights; native Windows has no zone database). Tests that need requests, pandas, numpy, pyarrow,
streamlit, websocket, matplotlib or sklearn do not collect. This is a disclosed limit, not a cut defect: the cut
keeps every repository module those tests import, and the author may ask about the errors.

## Rulings (owner, 2026-10-12)

| Id | Question | Ruling |
| --- | --- | --- |
| I-1 | Isolation mechanism (erratum 1 E-R3) | Option A (dedicated standard local account, NTFS deny) |
| I-2 | Who sets and holds the author account's password | The owner, out of band; never in a repository file, chat or log |
| I-3 | Which paths are denied (the `<PROD_CLONE>`, `<WORKTREES>`, `<LDATA>`, `<SOURCES>` lists) | The master agent enumerates them from the host; the owner signs the list |
| I-4 | Network egress (erratum 1 E-R4) | N1: web tools off, no MCP, no GitHub credential, shell network-sandboxed where supported, full transcript audit; residual risk disclosed |
| I-5 | Which harness and model the author runs | A fresh Claude Code session, web tools off; the owner accepts the shared-model limit on independence, disclosed in the oracle PR and in §4 |
| I-6 | How the author's tests take the workload lease | Quick unit tests only, in `<CUT_DIR>`, 00:30-09:00, through a master-run wrapper holding the lease; heavier tests after hand-back |
| I-7 | Where the cut directory and transcript are archived, and for how long | Cut folder plus full transcript, read-only, outside every clone, kept until the cohort receipt is signed, with the N1 audit result beside it |
| I-8 | The author session's permission mode (owner, 2026-10-12 ~21:30) | `acceptEdits` plus a git-only Bash allow-list (status, diff, log, add, commit, switch, checkout -b, bundle create); deny `WebFetch`, `WebSearch`, `mcp__*`; bypass disabled; every other command prompts the owner (§2 step 7) |
