# Workstation report - release-admissible clock and all-shadow bootstrap - 2026-07-30

| Toronto date | Verdict | Specific reason | Snapshots | Captured inputs | Release-admissible inputs |
| --- | --- | --- | ---: | ---: | ---: |
| 2026-07-16 | **PASS** | `release_admissible` | 193 | 193 | 193 |
| 2026-07-17 | **BLOCK** | `ledger_not_complete`: latest revision is `partial` | - | - | - |
| 2026-07-18 | **PASS** | `release_admissible` | 205 | 205 | 205 |
| 2026-07-19 | **BLOCK** | `ledger_not_complete`: latest revision is `partial` | - | - | - |
| 2026-07-20 | **BLOCK** | `ledger_not_complete`: latest revision is `partial` | - | - | - |
| 2026-07-21 | **PASS** | `release_admissible` | 191 | 191 | 191 |
| 2026-07-22 | **PASS** | `release_admissible` | 197 | 197 | 197 |
| 2026-07-23 | **PASS** | `release_admissible` | 207 | 207 | 207 |
| 2026-07-24 | **BLOCK** | `replay_invalid_jsonl`: captured-input line 46 is truncated at column 8,156 | - | - | - |
| 2026-07-25 | **PASS** | `release_admissible` | 195 | 195 | 195 |
| 2026-07-26 | **PASS** | `release_admissible` | 185 | 185 | 185 |
| 2026-07-27 | **PASS** | `release_admissible` | 158 | 158 | 158 |
| 2026-07-28 | **BLOCK** | `ledger_label_missing`: no settlement revision exists | - | - | - |
| 2026-07-29 | **BLOCK** | `ledger_label_missing`: no settlement revision exists | - | - | - |

## Outcome

Missions 1 and 2 are complete. The release-admissible clock is implemented,
schema-registered, tested, and exercised against the requested read-only
Toronto range. A verified immutable twelve-market all-shadow release also
exists outside `data/`, with no pointer and no serving or promotion change.

The current receipt-only clock is:

| Field | Value |
| --- | --- |
| Evaluation end date | `2026-07-27` |
| Contiguous release-admissible PASS days | **3** |
| Streak start | `2026-07-25` |
| Latest settled status | `PASS / release_admissible` |
| Receipt count | 14 |
| Receipt-set SHA-256 | `e869f904ae92e820dfd0a535ef70760e40ada9f9c6aab2dc20d1b097dc1729fe` |
| Clock self-hash | `4d0346dbce053968088369c96965bcecd8e5cb6e3a4860d15b8d1d3e59833575` |

An unsettled tail (`ledger_label_missing`) does not reset the latest settled
streak. Any settled BLOCK does. July 24 therefore separates the July 21-23
PASS run from the current July 25-27 PASS run.

## July 24 repair verdict

**The repair described in the handoff is not present in the workstation input
this run could read.** The strict reader independently reproduces the original
failure:

```text
captured-input line 46 is invalid:
Expecting ',' delimiter: line 1 column 8156 (char 8155)
```

The read-only input is 31,069,317 bytes with SHA-256
`7b58a04bbf541b27e7a2cf6466114646cae3b2a0ed43d2c86b5f94fee026e236`.
The small status summary is also the old 457-byte artifact, SHA-256
`428e2523e7e148c05a88335a7a4b8cf6dfab9cd7f63ea7fdbab967fc64fe18b1`,
reporting 194 captured and two evaluation-only snapshots. The failed receipt
still pins all seven inputs, including the malformed replay tape, and has
self-hash
`08c0c67dd289dfbfb813c97b6c3e78ed3032b76261b5a01e683adb67207215c3`.

No repair was attempted because `data/` was explicitly read-only. This is most
consistent with workstation/source divergence: the handoff describes a
different post-repair byte state than the files visible here.

## Daily production-host recipe

Run the bounded expensive grade once, after the date's final settlement
revision is available:

```powershell
venv\Scripts\python.exe -m weather.operations.release_admissibility_clock grade `
  --target-date <YYYY-MM-DD> `
  --snapshots-root data\snapshots `
  --ledger-root data\settlements `
  --receipt data\backtest\release_admissibility\receipts\<YYYY-MM-DD>.json `
  --fail-on-block
```

Then collapse only the small receipts:

```powershell
venv\Scripts\python.exe -m weather.operations.release_admissibility_clock collapse `
  --receipt-root data\backtest\release_admissibility\receipts `
  --clock-out data\backtest\release_admissibility\clock.json
```

The second command verifies each receipt self-hash and never opens a snapshot,
feature, captured-input, or status tape. It is safe for a frequent monitor,
though running it once after the daily grade is cheaper still.
`status.ps1` can read only `clock.json` and place
`contiguous_pass_days` beside its operational streak.

The small JSON shape is:

```json
{
  "schema_version": "release_admissibility_clock_v1",
  "artifact_type": "release_admissibility_clock",
  "market_id": "toronto",
  "as_of_date": "2026-07-29",
  "evaluation_end_date": "2026-07-27",
  "contiguous_pass_days": 3,
  "streak_start_date": "2026-07-25",
  "latest_status": "PASS",
  "latest_reason_code": "release_admissible",
  "receipt_count": 14,
  "receipts": [
    {
      "target_date": "2026-07-27",
      "status": "PASS",
      "reason_code": "release_admissible",
      "receipt_sha256": "<64 lowercase hex>"
    }
  ],
  "receipt_set_sha256": "<64 lowercase hex>",
  "clock_sha256": "<64 lowercase hex>",
  "generated_at_utc": "<UTC ISO-8601>"
}
```

The per-date `release_admissibility_receipt_v1` carries the exact ledger
revision, inventory counts, stable `reason.code`, all reached input byte
counts and SHA-256 hashes, and `receipt_sha256`. Large CSV and JSONL inputs are
bounded and parsed row-by-row. Strict JSON rejects duplicate keys and
non-finite constants. Captured inputs are unique, non-reconstructed,
self-hashed through `captured_input_payload_sha256`, and required to carry a
finite nonnegative unit-mass distribution. Snapshot winner, native settlement
unit, ledger/tape hash, status inventory, and feature-quality quarantine
checks all fail closed.

The cycle's single declared output root is:

```text
C:\Users\Michael\Documents\github\weather\scratch\agent-runs\workstation-second-clock-2026-07-30f
```

## Twelve-market all-shadow bootstrap

The reviewed entry point is:

```powershell
python -m weather.operations.all_shadow_release_bootstrap `
  --candidate-id <reviewed-id> `
  --run-root <dedicated-root-outside-data> `
  [--model-source-release <verified-immutable-release>]
```

The tracked pooled research bundle failed closed because it predates the
mandatory corpus-lineage contract. The first verified source release also
exposed that its bundle intentionally delegates evaluation bounds to its
frozen production qualification. The final entry point therefore reverifies
that immutable source release, copies its exact hash-bound
`pooled_band_model`, and imports the model-bound corpus lineage from its
verified `training_evaluation_corpus` role. It adopts neither the prior
release's runtime identity nor its production capability. The current tracked
research family-secondary manifest, artifact registry, market registry, and
all base-model artifacts are frozen anew.

Final immutable result:

| Field | Value |
| --- | --- |
| Release ID | `workstation-all-shadow-20260730f-d8806fac` |
| Exact code commit | `d8806fac2c8d8a99d187ab7ec3a27a93028552ae` |
| Release manifest SHA-256 | `8c735f9d0f795db4fa88d782aab53c48d257789585da91ed28f820d814a29ded` |
| Bootstrap receipt self-hash | `5f17ad53c1ef6b0c1caf75f974c226a74989001476d8fb1968433d4fba64be2d` |
| Immutable release files | 102 |
| Candidate mode | `research_only` |
| Production capable | `false` |
| Runtime verification | `PASS` |
| Runtime market inventory | Toronto C + eleven F markets |
| Route | 12 `shadow`, 0 `promote`, 0 `blocked` |
| Toronto base graph | seven canonical components |
| All-market base graph | exact seven components for each market |
| Active pointer | absent before and after |
| Activation | `NONE` |

The selected model role is SHA-256
`b142f327496287fac6c1b3bed5d11d62d784e24f1ddbe7722534480de6817809`.
Its source immutable release and model-bound corpus role both reverified
against source manifest
`4865ab19b9a84e7d54a249ecda3c26097bde7003ddbb1e0d25a4830c8e5fcc6a`.
The new base graph hash is
`7fe8f34a5985339cc0b97899b0140866b3281f0baadbdd50e881bf8dbcd0d39b`;
the all-shadow route self-hash is
`0287d21a5142cf968526c2d20c1316c194a21ff96185777de130c1e4cc566d21`.

No release pointer, promotion decision, boundary proof, serving change,
restart, scheduled-task change, or trading authority was created.

## What the first pointer would require

Creating the first pointer is a separate reviewed operation, not authorized by
this handoff. For this exact release, all of the following would be required:

1. The active pointer must still be absent, the release must still verify, and
   its `rollback_target` must remain null.
2. The repository must be clean and checked out at the release's exact
   `d8806fac...` code identity, or the release must be rebuilt at a newly
   approved exact commit. A later report-only branch head does not satisfy the
   exact-commit check.
3. A reviewed `release_promotion_decision_v0.1` must bind release ID and
   manifest hash exactly and declare:
   `decision=PROMOTE`, `gate_status=PASS`, `candidate_only_build=true`,
   `reviewed=true`, nonempty `reviewed_by`, `reviewed_at_utc`, and
   `release_kind=serving_identity_bootstrap`.
4. A fresh `release_market_day_boundary_v0.1` must bind the same release and
   manifest and declare `status=PASS`, `at_market_day_boundary=true`,
   `processes_quiesced=true`, empty `open_market_days`, empty
   `mixed_release_market_days`, an effective target date, and a fresh
   `observed_at_utc`.
5. The reviewed command must explicitly use `--bootstrap-first-release`:

```powershell
python -m weather.operations.release_lifecycle `
  --releases-root <run-root>\release-bootstrap\releases `
  --repo-root <clean-exact-release-worktree> `
  promote workstation-all-shadow-20260730f-d8806fac `
  --decision <reviewed-promotion-decision.json> `
  --market-day-boundary <fresh-boundary-proof.json> `
  --bootstrap-first-release
```

On success, that would create pointer sequence 1 with self-hashed
`serving_identity_bootstrap` origin provenance and return
`restart_required=true`. It would establish only release-bound research,
shadow, and paper identity. `production_capable` would remain false; capital
canary and live-pilot authority would remain blocked.

## Mission 3 disposition

**NOT RUN.** Missions 1 and 2 consumed the cycle, including two valuable
fail-closed bootstrap discoveries and the verified model-bound lineage bridge.
The scaled-MM queue remains behind its existing
`NONTERMINAL_FULL_BOOK_HASHES_REQUIRED` contract, and its earlier
`NOT_VIABLE_CURRENT_TRACK` economics verdict is unchanged. No 147-event
backfill, MM analysis, reward estimate, cool-bias score, 1,619-row-set
equivalence gate, or uniform amendment was attempted.

## Verification and repository state

- Focused clock/bootstrap/schema tests: 14 passed.
- Candidate semantic-contract and release-lifecycle tests: 54 passed.
- Additional non-production candidate-contract selection: 16 passed,
  22 deselected.
- Final combined focused run: 68 passed; `compileall` and
  `weather.operations.agent_docs_audit` passed. The repository's canonical
  `venv` currently points at a missing Python 3.11 installation, so these
  checks used the existing isolated `scratch\r30a\.venv` Python 3.12
  environment.
- Immutable release runtime/hash/semantic reverification: `PASS`.
- `data/` writes: zero.
- Pointer writes: zero.
- Topic branch:
  `codex/workstation-second-clock-bootstrap-2026-07-30f-keystone`.
- Required ancestry: keystone `ea0167a7...` plus merged
  `origin/master` `a29590d6...`.
- The original workstation `master` change to
  `config/storage_pressure.json` was not touched.
- No PR, merge to master, master push, ACL change, capture change, scheduler
  change, mirror change, promotion, or serving change was made.
