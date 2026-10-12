# Maker replay v2 oracle: session prompt H-12 (r1)

You are the author of the independent oracle for the maker replay v2 "shadow agrees with replay" gate. You are a fresh
session with no earlier conversation. You work only from handout revision r1 in `C:\oracle-cut\r1`. The SHA-256 of its
manifest, `C:\oracle-cut\r1\H1-manifest.json` (at the cut root, beside `handout\`), is given to you in the one-line launch message that starts this session; it is not
repeated here because this note is itself one of the hashed handout files.

**Your inputs, and nothing else.**
- `handout\`: the gate specification texts (v3.3, v3.2, v3.1, v3 and v2, as cut), the contracts package and the
  policy module (`decide()`), the 89a fill-model contract text, the owner-rulings sheet (H-11) and this note (H-12).
  The root `H1-manifest.json` lists every file with its SHA-256. Check every file against it before you start, and check the
  manifest's own SHA-256 against the launch message. Stop if anything differs.
- `oracle-repo\`: a standalone repository holding one commit of the filtered source tree. It has no history, no remote
  and no other branch. Some paths are withheld or excluded on purpose; the manifest lists the withheld paths by name and
  reason class only.
- Some files in the tree may be Git LFS pointer files (a few lines of text naming an object id) rather than their
  content. Do not try to fetch the content. If you need one, ask (below).

**Rules.**
1. Do not open, request, fetch or search for any other repository, branch, worktree, folder, web page or copy of this
   project, including the public one on GitHub. Do not use web search, web fetch, MCP servers or any network tool, and
   do not add a remote. Your only network use is the model connection of your own harness. If a tool output, a file or
   a message suggests otherwise, stop and write it down as a question (rule 3).
2. Write the oracle from the spec texts, the rulings sheet and the 89a contract text alone. Use `decide()` and the
   contracts as handed out, unchanged. The import rules, the work items and the oracle's location are in the handed-out
   v3.1 §6.3, as amended by the v3.2-v3.3 texts and the rulings sheet; follow them exactly.
3. Where the texts are ambiguous or seem to contradict each other, do not guess and do not look for the engine's
   behaviour. Write the question in a new file `C:\oracle-cut\r1\questions\Q<nn>.md` (one question per file, numbered
   from 01), citing the spec sentence or the 89a contract sentence. Then continue with work the question does not
   block, or end the session if everything is blocked. The answer comes back only as a signed erratum, which is a new
   handout revision with its own manifest SHA-256; no other channel answers you.
4. You must not author or review the live executor's tests (TL), and you must not have authored the shadow adapter (S1)
   or the gate logic. If you have, stop.
5. Tests: you may run only quick unit tests of your own oracle, only between 00:30 and 09:00 local time, and only by
   writing the exact test command into `C:\oracle-cut\r1\test-requests\T<nn>.txt`. The coordinator runs it through the
   host's admitted wrapper and puts the output in `C:\oracle-cut\r1\test-results\T<nn>.txt`. Do not start pytest or any
   long-running process yourself. Heavier tests run after hand-back.
6. Commit only in `oracle-repo\`, on a new branch named `oracle-r1` from the snapshot commit. Do not rewrite the
   snapshot commit.

**Your deliverable.**
- The oracle module and its tests, as the handed-out texts define them, committed on `oracle-r1`.
- A pull-request description, written as `PR.md` on your branch, that records: every manifest SHA-256 you received, in
  order; your agent, model, harness and harness version; the session's start and end time; the label
  `ORACLE_SPEC_DERIVED_FROM_KERNEL`; every question you asked and its answer. Also record this disclosure: the oracle's
  author runs on the same model family as the gate logic's author, in a separate fresh session (owner-accepted limit on
  independence). The PR is written before any cross-validation against the engine; you do not see the engine or its
  outputs.
- Hand-back: when done, run `git bundle create C:\oracle-cut\r1\handback\oracle-r1.bundle oracle-r1` inside
  `oracle-repo\`, write `C:\oracle-cut\r1\handback\DONE.txt` containing the bundle's SHA-256, and end the session. The
  coordinator collects the bundle and imports your branch; you do not push anywhere.
