# Replay does not reproduce what we served

**Established 2026-08-11 by `-09-75a` (merged `7b2ece24`), from `-09-74a` (merged
`8f7a408a`), and extended by `-09-76a`.**
Verified on production: artifact SHA-256 match, `ROLL-FREE` exit 0, every headline recomputed from
the committed CSV.

## 1. The result

The 368-event decision stratum of the `-09-73a` artifact was replayed against its **recorded**
probability vectors, using each row's own captured runtime commit, at a bit-exactness tolerance of
L1 `1e-12`.

| | |
| --- | ---: |
| Runtime-commit bound | **358 / 368 (97.28%)** |
| **Matched** | **114 / 358 (31.84%)** |
| **Diverged** | **244 / 358 (68.16%)** |
| Whole-B replay ceiling | **16,143 / 28,254 (57.14%)** |

Failures occur **in every market and in both decision windows**, under 8 of the 10 represented
runtime commits. Every row recorded and replayed active kind `hgb`, so this is not a model-kind
switch. These are exact finite-population counts; no interval applies to a deterministic
reproduction question.

**Divergence magnitude** over the 244 failures — median L1 **0.0154**, mean **0.0299**, p90
**0.0424**, p99 **0.3849**, max **0.7728**. Mostly small, with a real tail. Note the tolerance is a
*bit-exactness* bar, so "small" here still means the replayed system is not the served system.

## 2. It is the environment binding, not the inputs

| Evidence | Reading |
| --- | --- |
| **158 of 244** failures have **zero** feature differences | inputs identical, only the model environment differs |
| **19 of 114** matches have **nonzero** feature differences | the differing fields are ones the model does not consume — a control that passes |
| 10 runtime commits carry **7** code hashes, **15** artifact hashes, **54** identities | a commit does not determine what ran |
| **all 358** captured identities differ from their own commit tree | checking out historical `HEAD` never reconstructs the served system |
| all 358 record model version **`v0.5.10`** | **the artifact changed 15 times under one version label** |

`src/weather/model/model_identity.py:100` fingerprints code files by reading `SRC_ROOT` **from disk
at capture time** — not the loaded module — while the recorded `git_commit` is repository `HEAD`.
Three states can therefore disagree at once: the code the process loaded at start, the working tree
on disk, and `HEAD`. Our roll rules make this expected rather than exotic: a commit that touches no
loaded module is roll-free, so `HEAD` advances while the running process keeps its old code.

**This was the diagnosis to test, not a proven chain.** `-09-76a` found that none of the 63
decision-stratum identities can be fully rebuilt from reachable Git blobs. The diagnosis therefore
remains unidentifiable on the historical decision rows: a mismatch after a partial reconstruction
cannot distinguish an unresolved disk byte from code retained by a running process.

## 3. Two hypotheses this killed

**Toronto source switch — dead.** All four B `M4_source_switch` events are toronto pre-dawn at
~00:08. The three bound ones fail with **identical sources and zero feature differences**; non-`M4`
toronto rows match 0/2 and 0/9 on the same runtimes, and non-toronto rows fail too. Neither `M4` nor
toronto explains anything.

**"The incumbent reproduces recorded output" — retired.** The 2026-07-29 forward shadow matched
austin to `2.23e-16` on **one market, one market-day, diagnostic grade**, and said in its own words
that closure required **toronto at strict grade**. That was never done. It is now done, and it
fails. Do not cite that result as closure again.

## 4. What this licenses, and what it does not

**It licenses:**

- Refusing to allocate α to the frozen `-09-73a` pre-registration. It is unexecutable for a reason
  that has **nothing to do with the recovery candidate**, and the `-09-74a` ceiling mission must not
  resume until this clears.
- Treating **57.14%** as only the old commit-bound availability ceiling, not a trustworthy replay N.
  Exact identity reconstruction is available for just **111 / 28,254 (0.39%)** whole-B rows and
  **0 / 368** decision rows.

**It does not license:**

- Concluding the model is wrong. The served output is what it is; **we cannot currently rebuild the
  environment that produced it.**
- Discarding paired replay comparisons wholesale. A candidate scored against an incumbent **inside
  the same replay environment** is internally consistent — it simply answers "what would this change
  do under *this* environment", not "what would it have done to what we served". **State which
  question is being answered.** We have shipped the wrong-lane error before.
- Any change to serving, the floor, collection or scoring. Nothing here is a serving defect.

## 5. Identity binding does not recover the historical decision runtime

`-09-76a` resolved every captured per-file fingerprint against every blob reachable from 178 refs,
including the 27 unmerged remote branches, then assembled and replayed one synthetic tree per
decision identity. Captured SHA-256 fingerprints are SHA-256 over decoded Git blob bytes, not Git
object IDs. Of 413 distinct captured fingerprints, **89 resolve and 324 do not**.

The selected 63 identities each record 17–19 present files, but only 4–11 files per identity are
recoverable. **Zero of 63 are fully resolved.** On the same 358 commit-bound rows, the partial trees
match 105 / 358 (**29.33%**), versus 114 / 358 (**31.84%**) under commit binding. They rescue no
commit-binding failure and lose nine prior matches. This partial-tree rate is diagnostic only; it is
not a restored replay rate. The eight identity-only rows are also only partially resolved (1 match,
7 failures), while two rows have no identity.

Across whole B, 12 / 702 identities are fully resolved, covering **111 / 28,254 rows (0.39%)**;
23,683 identity-bearing rows are partial and 4,460 rows have no identity. In plain words: **what we
served on the historical decision stratum cannot be rebuilt from what we recorded.** Every replay
number that claims comparison to the served incumbent remains untrusted unless it is explicitly
limited to a fully reconstructed identity population.

The forward repair belongs in capture, not in further mining of this history: preserve immutable,
content-addressed source and artifact bytes for the loaded runtime, capture hashes from the modules
the process actually loaded, and bind them to process start/restart and dependency versions.
`model_identity.py` was deliberately left unchanged by this measurement.

## 6. Reproduction

```powershell
$branch = 'origin/codex/workstation-is-replay-trustworthy-2026-09-75a'
git show "${branch}:docs/roadmap/agent-report-2026-08-30-workstation-replay-trust.md"
git show "${branch}:docs/roadmap/replay-trust-2026-09-75a.sha256"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File `
  .\scripts\ops\roll_verdict.ps1 -Branch $branch
```

Artifacts: `docs/roadmap/replay-trust-2026-09-75a.csv` (372 rows: 368 decision + 4 `M4`
diagnostics), `-manifest.json`, `.sha256`, harness and versioned seed under `tools/research/`.
Predecessors: `docs/roadmap/agent-report-2026-08-29-workstation-repair-ceiling.md` (`-09-74a`),
and the candidate this blocks is in
`docs/operations/GATE_3_FIRED_ON_A_FLOOR_WE_NEVER_SERVED_2026-08-10.md` §5c.

Identity-binding evidence is on
`origin/codex/workstation-rebuild-the-runtime-from-the-identity-2026-09-76a`:
`docs/roadmap/agent-report-2026-08-31-workstation-identity-binding.md`,
`identity-binding-2026-09-76a.csv`, `-manifest.json`, `.sha256`, harness, and versioned seed.
