# Agent report - 2026-07-25 workstation skill-gap queue

Status: **MISSION 1 COMPLETE; MISSION 2 COMPLETE WITH SEALED OS PROOF PASS;
MISSION 3 NOT-DONE / NOT-REHEARSED**.

This report closes the ordered queue in
`docs/roadmap/workstation-handoff-2026-07-25b-skill-gap-decomposition.md`
(SHA-256
`dd5aa2634bb8ab22f48fd2db4b7e44b58f5263492deb8f4991865ed658bef863`)
and the post-simplex test-isolation handoff in
`docs/roadmap/workstation-handoff-2026-07-25c-settlement-test-isolation.md`
(SHA-256
`f5d31b695014f2f899909179eed5d0c741d9873d7a000a8476f3bbc3b94633bc`).

## Executive verdict

| Mission / question | Verdict | Basis |
| :--- | :--- | :--- |
| What kind of model-versus-market problem is this? | **RESOLUTION / MISSING-INFORMATION DOMINATED** | The model-minus-market Brier gap is `0.02468748298`; resolution/information explains `0.02441017232` (98.8767%) and reliability/calibration only `0.00027731066` (1.1233%). |
| Is global recalibration the next move? | **NO** | Recalibration cannot manufacture the outcome separation represented by the market's resolution advantage. No model or tuning change was made. |
| Is `price_free_model_learning` corpus-size memory bounded? | **YES, FOR THE MEASURED CONTRACT** | Growing state spills to disposable SQLite, bounded consumers no longer duplicate unbounded detail, exact v0.1 semantics were preserved, and the sealed 5-day/50-day Windows process-tree proof passed. |
| Can pooled H2 be trained now? | **NO - NOT-DONE / NOT-REHEARSED** | Only 15 production-compatible F dates exist, the longest contiguous run is 5 days, no 14-day lock exists, and no immutable training package exists. |
| Does this authorize promotion or live cutover? | **NO** | No promotion, release, pointer, activation, serving, scheduler, collector, sizing, trading, PR, or merge action was run. |

## Final identities and containment

| Purpose | Identity |
| :--- | :--- |
| Rebased `origin/master` | `008a0b82a6f771d53b45dd0f1ee2ba9abcc47810` |
| Accepted simplex ancestry | `09756227` and `d1815774` are both ancestors of that `origin/master` |
| Topic branch | `codex/workstation-skill-gap-2026-07-25b` |
| Mission 1 commits | `c246e51a`, `6e7824a3` |
| Mission 2 implementation commits | `b676d8f0`, `b7f7d0eb`, `2798e1c2` |
| Measured source commit | `2798e1c21500fb26b95a5d4c130eb6dbf2cd26c2` |
| Measured `src/weather` tree | 422 files; SHA-256 `6d58ac9736b5143dfcda8a85f6bc423917f75c4ab5cbaed6c47f88aba81dc19d` |
| Post-simplex test-isolation commit | `79b028a9` |
| Declared output root | `C:\Users\Michael\Documents\github\weather\scratch\workstation-research-output\skill-gap-20260725` |
| Protected mirror | `C:\Users\Michael\Documents\github\weather\data` |

The topic was rebased only after both accepted simplex commits landed. The
proof measured the clean `2798e1c2` source tree. Later changes are confined to
tests and this report; `src/weather` remains byte-identical to that measured
commit.

The protected main data mirror remained OS-denied/read-only. Fresh write
canaries failed with `PermissionError` / errno 13 and were absent afterward.
Every authoritative proof artifact, disposable database, test temporary
directory, bytecode cache, and validation report was directed below the
declared output root.

## Mission 1 - exact model-versus-market decomposition

Mission 1 is complete. It fit or tuned nothing and consumed no opened-window
outcomes.

### Evidence identity and population

| Item | Value |
| :--- | :--- |
| Repaired candidate rows | `cf661e9fb396e95db4e98f2aa29fd32dda2fb9b992099e4d0d6fcfea89b68a4b` |
| Frozen corpus manifest | `128db63ec78c92a4126f886caec078dcab6786b47d0d65ad0aff10f5f1dc1dc5` |
| Decomposition JSON | `32eef5baf0418de1805de63292993edffbe11879254222b273e6b7f4b8036965` |
| Decomposition Markdown | `a6608ee786a97ee9c733d946f4f311936f07e62171ae007da17f0a1ce827b931` |
| Worst-case CSV | `2c4df1dc88730152e93eaeca6d8a21b4941b16c6c0697a676f5b6eb8a37b134b` |
| Population | 206,745 rows; 18,793 partitions; 11 F markets; 129 market-days |
| Integrity | 0 incomplete/invalid partitions; 0 probability-mass violations; maximum residual `6.66e-16` |

The market-stratified exact Murphy identity gives:

| Metric | Model | Market | Difference |
| :--- | ---: | ---: | ---: |
| Brier score | `0.06205611377` | `0.03736863079` | `0.02468748298` |
| Reliability contribution | - | - | `0.00027731066` (1.1233%) |
| Resolution/information contribution | - | - | `0.02441017232` (98.8767%) |

The direct global-pool sensitivity still assigns 95.006% to
resolution/information. Categorical sharpness agrees: the model spreads mass
over 3.9427 effective bands versus 2.6465 for the market, and its mean top
probability is 0.5242 versus 0.6680.

Named time cuts show the smallest plausible frontier is still not edge:

| Cut | Model Brier | Market Brier | Gap |
| :--- | ---: | ---: | ---: |
| Predawn 03:00-05:00 | `0.075141` | `0.058793` | `0.016349` |
| Primary 09:00-14:00 | `0.066870` | `0.050851` | `0.016020` |
| Lock-in 20:00-23:00 | `0.045434` | about `0.000001` | `0.045433` |

Hour 20 is widest at a `0.048180` gap, or 58.30% of available uncertainty.
High forecast-disagreement cases contribute 78.93% of positive excess loss.
The evidence therefore points toward missing time-valid information - model
spread/source reliability, current-high trajectory, and observation history -
not a global probability remap. Any later change still requires leakage review
and an untouched preregistered confirmation window.

## Mission 2 - bounded `price_free_model_learning`

### Implementation and semantic parity

Growing rows, labels, exact distincts, partitions, and checkpoints now spill to
a disposable SQLite store. Global checkpoint reduction and partition metrics
remain exact while only one bounded partition is materialized at a time.
Production consumers use bounded projections: daily-refresh status retains
scalars/maps plus `score_error_count` and at most 20 examples, while the
canonical v0.1 artifact retains full detail.

The frozen July 1-3 parity corpus contained 36 scored market-days, 59,554
all-snapshot rows, 9,493 hourly checkpoint rows, and zero score errors.

| Output | Legacy SHA-256 | Candidate SHA-256 | Verdict |
| :--- | :--- | :--- | :--- |
| JSON | `9fd00e64ad21a95de6e6ca215c363c85890e927aa2930eb6701074b9253b13b2` | `773de83936f21da21e7258bfb9d43be94952a4bf785f4c9373e76cfbf008ff1b` | Parsed equality after removing only root generation time |
| Markdown | `6e3eb8850bc9180b0f82813b5eb9d2dac1295121c50c7aa7182f823f76dab2e0` | `64a5db996c923abc6da1b3ec760aa52069e497bcc4f98d06d76a95646ebecb75` | Exact after normalizing only the Generated line |
| Hour CSV | `0a6674061f047de4155555114cad9e68f8b26cba87b3f59981bd4f35f53c7f42` | same | Byte-identical |
| Current-max CSV | `55e9006b8498a53cebf6f96cfa940a85d52be15480cea342ab2d19b92e291215` | same | Byte-identical |

A separate diagnostic scale smoke completed 444 market-days, 782,265
all-snapshot rows, 113,905 checkpoint rows, and a 59,692,883-byte JSON
artifact. It is scale evidence, not an eligibility claim.

### Frozen v0.2 result - FAIL, evidence preserved

The requested frozen base harness is `memory_proof.py`, 101,280 bytes,
SHA-256
`3391e67b93b0e6619d64db19f274eabf6049932feb6192bb1c021a84257a4bc8`.
Its immutable v0.2 evidence remains:

| Artifact | SHA-256 |
| :--- | :--- |
| Predeclaration | `9d94d146f5548059c435c13744ef022026aee961ba411d37228ddd0b67349c31` |
| Measurement start | `8561d2497d7bdab1ae2d039c5a5596b2903395e9c0ed1205729e9c5084f81826` |
| Receipt | `9a6a26c371eeaf6a7d81f4188aae011703af9a0e5afe13d1caa34f9f30668848` |
| Report | `61cdcc80437d02abfb7302c3c52d64fda957a2c7f35f9294c8305bf85ec01f8c` |
| Import probe | `7be6bf5d782049eb052d227f355047253c3c132a71ee3796ff33282053d74871` |

v0.2 is an honest **FAIL** because its single-process lifetime assertion was
invalid for the complete Windows Job process tree. The memory growth itself
was small, but that instrumentation could not support an acceptance claim.
The evidence was not overwritten or relabeled.

### v0.3 replacement proof - PASS

The replacement is an external wrapper over the frozen v0.2 harness:

| Artifact / identity | Value |
| :--- | :--- |
| Wrapper `memory_proof_v0_3.py` | 24,591 bytes; `151e6e4ec6c86560085bf3b4ac5e5bcc87ab5819190b97d6cbf20a89c338f1e1` |
| Frozen v0.2 base | `3391e67b93b0e6619d64db19f274eabf6049932feb6192bb1c021a84257a4bc8` |
| Process-lifetime tracker | `cef5c17cf74b94dc2baa6b20d5c53c60af070f82d69c2b11547c8c4716b3208c` |
| Long-job guard | `65829605beac7f06818f376ef065a031e258343ba2ebe3e77b0a3249c368dc87` |
| Predeclaration | `57a198cf8a7260b46344ebd65d85346a5e1e601a17a06c8512f01b5718f92354` |
| Measurement start | `7951cb185d30898340d8bc8b69586391e1f9cb761235517fd7ac5a309e88d16e` |
| Receipt | `74de253317d919358d0fe51a8987176d03cda697e9eeb1ca48b16b0a08c0bd8d` |
| Report | `3848507426beb435f6708b4a5a0891098618d3118ae7202ad3d505a68dd136ac` |
| Import probe | `f894b5a3f7c397f76406be78e787cda713a0b39c7d0b152ede533d417113e548` |
| Combined corpus identity | `249bbe132579b8d0a683ed96edf0d49accef4185edf96ace1f60fc5c5ba6698b` |

The predeclaration sealed a 4,096 MiB private-commit limit, 2,560 MiB
working-set limit, 3,600-second timeout, source/runtime/corpus identities, and
the still-denied protected mirror. The controller associated a Job completion
port before resuming the child, retained exact Job-verified handles keyed by
PID and creation time, queried terminal PSAPI peaks after exit, and reconciled
Job `TotalProcesses`.

| Case | Job/tracked/retained/closed | Terminal WS sum | Sampled WS | Exact Job peak commit |
| :--- | :---: | ---: | ---: | ---: |
| 5 days | `2/2/2/2` | 219,807,744 | 219,340,800 | 1,720,774,656 |
| 50 days | `2/2/2/2` | 220,897,280 | 220,450,816 | 1,722,064,896 |

Both cases ended with zero active, terminated, duplicate, overflow, or capture
failure records. Working-set growth was 1,089,536 bytes and Job peak-commit
growth was 1,290,240 bytes, both below the sealed 67,108,864-byte growth
ceiling and far below the production absolute limits.

The receipt passed 15/15 global checks, five integrity gates at 15/15 each,
67/67 checks per case, and 19/19 lifetime checks per case. An independent
validator passed 69/69 assertions; a second independent immutable-evidence
audit rehashed the full chain, inventories, runtime trees, two-process
terminal arithmetic, mirror guards, and preserved v0.2 tree and also returned
**PASS** with no discrepancy.

## Mission 3 - pooled H2 artifact

Status: **NOT-DONE / NOT-REHEARSED**.

The audit was read-only. All 12 canonical settlement ledgers passed history
verification. Current inventory is:

| Population | Result |
| :--- | ---: |
| Current labels | 585 |
| Complete / manual override | 172 / 0 |
| Grade-qualified with tape and replay | 169 |
| Distinct all-market captured dates | 18 |
| Production-compatible F market-days / dates | 152 / 15 |
| Longest F contiguous run | 5 days, July 14-18 |
| Latest F run | 3 days, July 21-23 |
| Toronto complete suffix | 3 days, July 21-23 |

There is no valid trailing 14-day fleet lock. The default
outer-14/inner-7/embargo-3/step-7 topology requires at least 29 distinct dates,
or 36 for contiguous daily fixtures. No immutable source corpus, source
manifest, replay/staging receipt, or preselection lock exists. The old
`promotion_corpus.json` admits partial and mixed-unit legacy rows and is not a
substitute.

No prelock, trainer, fit, calibration, qualification, replay, artifact, or
outcome-evaluation command ran. No H2 model or artifact-specific future panel
exists. Weakening the lock or substituting mutable legacy inputs would
manufacture evidence.

## Test isolation and validation

The post-simplex handoff identified seven tests whose real event slugs could
resolve production settlement ledgers. Commit `79b028a9` redirects only those
fixtures to temporary ledger roots. Production settlement identity strictness
was not weakened. The same commit fixes the app architecture ratchet's empty
legacy-wrapper set, whose empty alternation otherwise matched every import.
The eight implicated tests pass together.

Final checks:

- Focused post-rebase proof/guard/ratchet suite: 48 passed.
- Seven settlement-isolation nodes plus app architecture ratchet: 8 passed.
- `python -m compileall -q app src tests`: passed, with bytecode redirected
  below the declared output root.
- `python -m weather.operations.agent_docs_audit`: passed (18 agent files,
  472 Markdown files).
- `git diff --check`: passed.
- Source comparison against measured commit: no `src/weather` difference.
- Final fetch: `origin/master` remained `008a0b82`; it is an ancestor of the
  topic, and both accepted simplex commits remain its ancestors.

The full pytest run requires a split Windows-path interpretation on this host:

- An extended-length-path run completed 3,137 passed, 3 skipped, and 812
  subtests passed, with 13 failures.
- Four failures were PowerShell child tests blocked by the host execution
  policy; those nodes passed when rerun with inherited process-scope bypass.
- Nine failures were `experiment_executor` tests. With extended paths their
  Win32 Job child rejected an extended `cwd`; with normal paths under the
  required 96-character evidence root their nested sandbox paths exceeded
  `MAX_PATH`. The host reports `LongPathsEnabled=0`.
- An earlier substituted-drive full run was invalidated because pytest
  canonicalized the drive back to the long physical path; it is not cited as
  passing evidence.

These are disclosed host validation limitations, not green results. The
changed tests, all Mission 2 focused tests, the sealed production-policy proof,
compile gate, documentation audit, and source-identity checks are the
authoritative completion evidence. No unqualified all-tests-green claim is
made.

## Protocol incidents

Two incidents are retained explicitly:

1. An early, non-authoritative parity attempt ran before `TEMP` and `TMP` were
   pinned, so its disposable SQLite directory appeared below
   `C:\Users\Michael\AppData\Local\Temp`. It auto-cleaned; a later inventory
   found zero `weather-price-free-learning-*` remnants. It wrote no durable
   artifact or protected-mirror data and is invalidated as proof.
2. An accidental default `module_size_audit` invocation created exactly two
   ignored files in this topic worktree's local
   `data\backtest`: `module_size_audit.json` and
   `module_size_audit_report.md`. They were created in that turn, not in the
   protected main data mirror. Exactly those files and the newly empty local
   directories were removed; deletion is unrecoverable. The command output is
   invalidated as evidence. The protected mirror was untouched.

## First-class NOT-DONE and NOT-REHEARSED

### NOT-DONE

- Mission 3 pooled H2 artifact and every artifact-specific receipt/proof.
- Any model change, tuning, recalibration, or metric-chasing response to
  Mission 1.
- Any promotion, release, pointer, activation, serving binding, scheduler,
  collector, sizing, trading, PR, or merge action.
- An unqualified all-tests-green claim on this Windows host.

### NOT-REHEARSED

- Mission 3 prelock/training/qualification, because prerequisites are absent.
- Promotion or release paths, because authorization is spent and none was
  requested.
- Opened-window outcome evaluation or artifact-specific confirmation panel,
  because no H2 artifact exists.

All retained evidence is diagnostic/research evidence only. It authorizes no
cutover or live action.
