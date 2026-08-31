# Workstation handoff 2026-09-79a — qualify the model/PIT foundation and make the workflow reproducible

Written 2026-08-31 by the production agent. Read from
`origin/codex/model-pit-foundation-20260831` and execute on the assigned 32 GB
workstation. This mission is model/research work, not portable live execution.

## 1. Goal

> Turn the restacked loaded-process identity and honest twelve-field free-PIT
> contract into a fully verified foundation, add a deterministic model bill of
> materials, and return either a mergeable branch or a precise NO-GO without
> fitting a candidate or reading a locked outcome.

## 2. Exact source and branch

- Foundation branch: `origin/codex/model-pit-foundation-20260831`
- Exact foundation commit: `42657a1f48c82b81c6f2257f4d2614092862ae94`
- Foundation tree: `033f9bc8644dee34a498ccc627f1436565b193c4`
- Create branch: `codex/workstation-model-pit-foundation-2026-09-79a`
- Report: `docs/roadmap/agent-report-2026-09-03-workstation-model-pit-foundation.md`

Fetch the source branch, verify the exact commit/tree, and create the mission
branch from that commit. Do not branch from the live portable clone, do not
move either existing branch, and do not rewrite published history. Use a new
development worktree with LFS smudging disabled unless a specific test proves
it needs materialized models.

## 3. Start from this; do not re-derive it

Read `docs/operations/STATE_OF_PLAY.md`, `MODEL_SYSTEM.md`,
`ESTABLISHED_FINDINGS.md`, `RETRACTED_AND_FALSE_LEADS.md`,
`reserved-confirmation-window.md`, and `DELEGATION_CONTRACT.md` first.

- We do not beat the market. Calibration, generic distribution reshaping, and
  input-completeness are closed as gap-closing directions. The remaining model
  lever is genuinely new point-in-time information.
- The current identity v0.1/v0.2 surfaces describe filesystem state
  incompletely. The foundation restacks v0.3, which binds path-normalized
  loaded code, nested behavior constants, loaded artifact state, and runtime
  dependencies. Earlier v0.3 focused evidence is a positive control only; it
  does not qualify the current base.
- The free Previous Runs endpoint has a proved twelve-field surface. Nine
  schema-known fields are all-null or rejected. The foundation versions the
  plan/manifest/preflight to v2 and excludes every profile feature that depends
  on an unavailable field. Never substitute stitched settled data.
- No active release store or pointer exists. The base retrain is a correctness
  baseline that freezes parent feature order; it is not the new-information
  challenger.
- No dates are currently reserved, no alpha is allocated, and decision 10 is
  retired. This mission must not fit, freeze, or score a candidate.
- The portable live checkout and the development checkout are separate. The
  workstation wrapper and portable launcher share the host-global mutex.
  Finish all heavy work before anyone seals a new live attempt.

## 4. P0 — prove or reject the foundation

### 4a. Exact environment and isolation

1. Require the assigned workstation host/principal and a clean development
   worktree at the exact foundation commit. Print the imported
   `weather.model.model_identity.__file__` and
   `weather.sources.forecast_training_corpus.__file__`; stop if either resolves
   outside the mission worktree.
2. Use the existing 64-bit CPython 3.11 venv created for the development
   checkout. Do not copy the portable live venv, SDK overlay, credentials,
   attempt files, or `data/`.
3. Run recognized Python work only through
   `scripts/ops/workstation_heavy.ps1`. It must acquire
   `workstation_offline_v1`; do not bypass a busy or poisoned host-global lease.

Use canonical base64 JSON argument arrays. For example:

```powershell
$python = (Resolve-Path .\venv\Scripts\python.exe).Path
function Invoke-WorkstationPython([string]$Kind, [string[]]$Arguments) {
  $json = ConvertTo-Json -Compress -InputObject @($Arguments)
  $b64 = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($json))
  & .\scripts\ops\workstation_heavy.ps1 `
    -Kind $Kind `
    -PythonPath $python `
    -ArgumentsBase64 $b64 `
    -RepoRoot (Get-Location).Path
  if ($LASTEXITCODE -ne 0) { throw "$Kind failed: $LASTEXITCODE" }
}
```

### 4b. Focused verification

Run this matrix serially through the wrapper:

```text
tests/model/test_model_identity_binding.py
tests/model/test_feature_model_calibration.py
tests/sources/test_forecast_training_corpus.py
tests/calibration/test_forecast_training_contract.py
tests/operations/test_base_retrain.py
tests/operations/test_schema_registry.py
tests/operations/test_import_architecture.py
```

Then run worktree compilation, roadmap generation/check, agent-doc audit, and
the complete workstation pytest suite through the same wrapper. Record elapsed
time, peak process-tree memory if the wrapper exposes it, exact pass/skip/fail
counts, and lease cleanup. A partial, interrupted, poisoned, or uncontained run
is not PASS.

### 4c. Required adversarial checks

Add or strengthen tests so all of these are explicit:

- identical loaded behavior hashes equally across different absolute worktree
  paths;
- nested constants, function defaults, loaded estimator bytes, and runtime
  dependency changes move identity;
- post-load disk mutation cannot relabel an unchanged process;
- a fingerprint error is visible and cannot masquerade as a complete identity;
- a v1 PIT plan/manifest/preflight cannot pass as v2;
- the v2 plan requests exactly the twelve proved fields and no unavailable one;
- included forecast-profile features depend only on those twelve fields;
- all forecast-profile columns remain partitioned exactly once between included
  and reason-bearing excluded dispositions;
- stitched issue evidence remains rejected;
- the synthetic one-market corpus still materializes atomically and passes the
  exact v2 preflight.

If any property fails, repair it with a descendant commit and rerun the whole
focused matrix. Do not weaken an assertion or schema gate to make it green.

## 5. P1 — implement the deterministic model BOM

Roadmap item 330 Phase A is open. Add the smallest owner-correct implementation
under `weather.model` plus release-verifier integration and deterministic tests.
The BOM must enumerate, in serving execution order:

- stage ID, owner module, and role;
- input/output semantic contract and native-unit/cutoff obligations;
- loaded artifact role/hash or behavior-bearing constant hash;
- stored estimator feature order and a structural-use summary;
- training corpus/fit receipt when present, otherwise an explicit missing
  evidence state;
- runtime/dependency identity;
- the feature-extraction forecast ensemble and the distribution-stage forecast
  context as separate named nodes.

Requirements:

- deterministic across worktree paths and mapping order;
- generated from loaded/release-bound state, not copied prose;
- no ambient global-artifact fallback for a production candidate;
- missing or ambiguous required entries make release verification fail closed;
- research-unbound incumbent output may be `INCOMPLETE`, but must say exactly
  which entries are absent rather than inventing lineage;
- no import edge from `weather.model` back into `weather.calibration`.

Prefer a new narrow module and tests over growing a large facade. Update
`MODEL_SYSTEM.md` and item 330 only for behavior actually implemented.

## 6. P2 — make the next corpus operation executable without violating host roles

Do not call Open-Meteo from the workstation. Audit the existing plan/staging
surface and answer one question:

> Can the production host collect request-bound raw responses for a v2 plan and
> transfer a complete content-addressed non-secret bundle without writing the
> workstation mirror?

If the answer is yes, document exact existing commands and paths with a
no-network workstation verification step. If no repository-owned collector can
consume the immutable plan, return a precise implementation gap and the
smallest proposed owner/files. Do not synthesize raw responses from the staged
long CSVs; those projections cannot recreate lost provider bytes or receipts.

You may add an offline import/verification boundary only if it consumes exact
raw response bytes plus request hash, retrieval/issue evidence, byte count, and
SHA-256. It must not contain an HTTP client and must not treat summary coverage
as row-level proof.

Do not fit the base retrain or challenger in this mission. The next mission
will build the multi-year corpus first, then run a correctness baseline and a
simple regularized market-identity-aware residual/ordinal challenger with no
market-price features.

## 7. Falsification — this mission must be able to fail

Return **NO-GO** rather than a patch when any of these holds:

- v0.3 identity still depends on checkout path or capture-time disk state;
- an unsupported loaded component can yield a confident complete identity;
- the v2 corpus surface cannot partition every forecast profile without an
  undocumented value source;
- old v1 evidence is silently accepted under the new semantics;
- satisfying the twelve-field contract requires a provider call from the
  workstation or reconstruction from projections;
- the BOM cannot enumerate the served graph without ambient artifacts or an
  owner-boundary violation;
- current-tip focused or full verification is not clean and contained.

A clean negative is valuable. Do not fit another model merely because the
foundation code compiles.

## 8. Standing boundaries

`DELEGATION_CONTRACT.md` §2 binds in full.

- No credential read, exchange call, live mutation, Scheduler mutation,
  production write, provider call, branch deletion, history rewrite, release
  promotion, active pointer, model fit, candidate freeze, alpha allocation, or
  reserved-date read.
- Never write the frozen mirror or `D:\weather-mirror`.
- Keep all disposable outputs outside the repository or under ignored scratch;
  commit only source, tests, canonical docs, and small deterministic fixtures.
- Never weaken the observed-high floor, probability-mass checks, native-unit
  contract, WU cutoff semantics, train/serve parity, or release binding.
- The clean portable checkout is out of scope. If a live attempt is being
  prepared or sealed, stop model work and release the shared host-global lease.

## 9. Handback requirements

Verdict first. Include:

1. exact base, final commit, tree, branch, and push proof;
2. complete changed-file list and cumulative diff against the foundation;
3. focused/full verification counts and wrapper/lease cleanup evidence;
4. direct answers to every adversarial check and falsifier;
5. BOM example plus its deterministic identity and incomplete-state behavior;
6. exact corpus collector/export disposition without a provider call;
7. what was not done, explicitly;
8. reproduction commands using paths that exist on the production host where
   applicable;
9. the repository-owned roll verdict if the required live closure evidence is
   available; otherwise state that production must derive it and do not guess.

Commit and push the mission branch. Do not merge it. Production will fetch,
review the load-bearing claims, run the canonical roll verdict, and decide the
verification/adoption path.
