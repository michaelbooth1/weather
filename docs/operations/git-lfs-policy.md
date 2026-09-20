# Git LFS Policy

- **Owns:** the rules that keep Git LFS bandwidth from being burned: workflow
  `lfs:` settings, `.git/lfs` retention, worktree and selective-fetch practice.
- **Read when:** you create a clone or worktree, edit a GitHub workflow checkout
  step, clean disk near `.git`, or a model artifact fails to materialise.
- **Do not use for:** artifact size thresholds and manifests
  ([artifact-storage-policy.md](artifact-storage-policy.md)).
- **Verify with:** `git grep -n "lfs" -- .gitattributes .github/workflows`
  (patterns and workflow settings) and `git lfs ls-files --size` (what is
  tracked and how big; reads the index only).

The account exhausted its included Git LFS bandwidth on 2026-07-29. These rules apply to every
host and every agent.

## What is in LFS

The model pattern is `artifacts/models/hgb/*.pkl` (several hundred MB of HGB pickles; get the
current count and sizes from `git lfs ls-files --size`). `.gitattributes` also tracks one dated
roadmap evidence bundle pattern (`docs/roadmap/repair-ceiling-*-runtime-bundle-*.zip`).

Most of the model set is live. The model variant registry names only a few artifacts, but
`src/weather/model/model_features.py:63` builds `feature_model_hgb{spec.artifact_suffix}.pkl`
dynamically, which is how the per-city models load. **Do not prune these as unreferenced.**

## Rules

1. **Never set `lfs: true` in a workflow.** `retrain.yml` (daily) and `ci.yml` (every master
   push and PR) once did, which exhausted a **1 GB/month** included allowance many times over.
   All three workflows now pin `lfs: false`; keep it that way. The test suite stubs these artifacts and never reads
   their bytes.
2. **Never delete `.git/lfs`.** It looks like a rebuildable cache. Rebuilding it costs metered
   bandwidth, so deleting it during a disk cleanup converts free disk into a billed download.
3. **Use `git worktree`, never a fresh clone.** Worktrees share the object store, so LFS objects
   are fetched once and reused. Each worktree still materialises its own copy of every pickle
   on checkout, which costs disk, not bandwidth. Create worktrees that do not need to load a
   model with `GIT_LFS_SKIP_SMUDGE=1` set so they hold pointers only.
4. **Fetch selectively when a job genuinely needs a model:**
   `git lfs pull --include="artifacts/models/hgb/<name>.pkl"`
5. **Do not convert LFS objects to ordinary Git blobs.** It dodges the meter, because plain Git
   bandwidth is unmetered, but it is a one-way door: the whole model set permanently in history, growing with
   every model version, and uncleanable without a history rewrite.

Bandwidth is charged on **download, not upload** — pushing costs nothing. Any burn is something
fetching.

## While the quota is exhausted

LFS downloads fail. A host without a warm `.git/lfs` cannot materialise model artifacts until
the allowance resets. The production host's cache is warm; check before assuming a research host
can load a model.

## The structural fix, post-lock

Status: not scheduled. "Lock" means the Release #1 lock, which is off the critical path
([release-one-is-not-the-mm-critical-path.md](release-one-is-not-the-mm-critical-path.md)).

Distribute model artifacts through the release artifact path rather than the repository. That
removes them from every clone and ends the metering entirely. It is not a pre-lock change: the
bootstrap and serving paths currently resolve these artifacts from the working tree.

## Update this file when

Update when an LFS pattern in `.gitattributes`, a workflow checkout `lfs:` setting, the account
allowance, or the artifact distribution path changes.
