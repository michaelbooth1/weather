# Git LFS Policy

The account exhausted its included Git LFS bandwidth on 2026-07-29. These rules apply to every
host and every agent.

## What is in LFS

One pattern: `artifacts/models/hgb/*.pkl` — 26 files, **~382 MB at HEAD**, largest
`feature_model_hgb_f_pooled.pkl` at 104 MB.

Most of it is live. The model variant registry names only 7 artifacts (~31 MB), but
`model_features.py` builds `feature_model_hgb{spec.artifact_suffix}.pkl` dynamically, which is
how the per-city models load. **Do not prune these as unreferenced.**

## Rules

1. **Never set `lfs: true` in a workflow.** Both CI workflows did, which is what exhausted the
   quota: `retrain.yml` daily (~11.5 GB/month) and `ci.yml` on every master push and PR, against
   a **1 GB/month** included allowance. The test suite stubs these artifacts and never reads
   their bytes.
2. **Never delete `.git/lfs`.** It looks like a rebuildable cache. Rebuilding it costs metered
   bandwidth, so deleting it during a disk cleanup converts free disk into a billed download.
3. **Use `git worktree`, never a fresh clone.** Worktrees share the object store, so LFS objects
   are fetched once and reused.
4. **Fetch selectively when a job genuinely needs a model:**
   `git lfs pull --include="artifacts/models/hgb/<name>.pkl"`
5. **Do not convert LFS objects to ordinary Git blobs.** It dodges the meter, because plain Git
   bandwidth is unmetered, but it is a one-way door: 382 MB permanently in history, growing with
   every model version, and uncleanable without a history rewrite.

Bandwidth is charged on **download, not upload** — pushing costs nothing. Any burn is something
fetching.

## While the quota is exhausted

LFS downloads fail. A host without a warm `.git/lfs` cannot materialise model artifacts until
the allowance resets. The production host's cache is warm; check before assuming a research host
can load a model.

## The structural fix, post-lock

Distribute model artifacts through the release artifact path rather than the repository. That
removes them from every clone and ends the metering entirely. It is not a pre-lock change: the
bootstrap and serving paths currently resolve these artifacts from the working tree.
