# Agent report 2026-08-06 — workstation autopsy the learning loop

Branch: `codex/workstation-autopsy-the-learning-loop-2026-09-21a`

Base: refreshed `origin/master` at
`e802233522f455fe857357ea287384f1999538fa`.

## Verdict

**P0 resolves this mission as a note, not a repair. No gate is wrong and no
code change is warranted.** The two gates share the same precondition—a
verified immutable release binding—but they expose its absence at different
layers:

- The live variant settlement scorecard has served rows, but correctly rejects
  all of their eligible partitions because the pre-release rows do not carry
  an explicit immutable release identity.
- Captured-input replay parity has **both sides empty**. The nightly chain was
  given neither a served evidence file nor a replay evidence file; therefore
  it has no keys to join. The evidence generator deliberately cannot create
  either side until a verified active release and fresh release-bound source
  tapes exist.

Release #1 is therefore the necessary fix in lifecycle terms. It is not an
instantaneous side effect of writing `current_release.json`: clearance requires
the already-designed post-cutover sequence—restart binders, collect a fully
release-stamped market day, generate one fresh served/replay parity pair per
routed market, and re-register the chain with those files. Once that sequence
is complete, both gates have the binding they are correctly waiting for. This
is release execution, not a repository repair.

Per the handoff's P0 stop rule, P1–P3 were not attempted.

## The requested join answer

`_parity_row_key` is:

```text
(target_date, market_id, evaluation_point_id, variant_id,
 release_id, evidence_lane, band_identity)
```

That is `PARTITION_KEY_FIELDS` plus `band_identity` in
`live_variant_settlement_scorecard.py:2217-2218` on the audited base.

The observed side disposition is unambiguous: **both sides are empty**, not
populated with incompatible keys.

From `data/backtest/nightly_retrain_status.json`, generated
`2026-08-05T05:00:08.334527+00:00`:

| Field | Observed value |
| --- | --- |
| `release_identity.binding_status` | `RESEARCH_UNBOUND` |
| `release_identity.release_id` | empty |
| `release_identity.served_bindings_verified` | `false` |
| parity `inputs.served_row_count` | `0` |
| parity `inputs.replay_row_count` | `0` |
| parity served source/path list | empty / empty |
| parity replay source/path list | empty / empty |
| expected release ID / manifest | `null` / `null` |
| first mismatch | `no_comparable_rows` |

The same payload separately reports
`served_parity_input_not_configured`,
`replay_parity_input_not_configured`, and
`expected_release_identity_unavailable`. Its candidate release disposition is
`BLOCK / captured_input_replay_parity_blocked / activation=NONE`.

This matters because `no_comparable_rows` alone does not identify a key
mismatch. Here the input counts and configured-source records do: the
comparator built two empty indexes, so their intersection is empty before any
key compatibility can be tested.

## Why the live scorecard is the same release dependency

The retained live scorecard was generated
`2026-08-04T14:46:20.517227+00:00`. It selected all 12 markets and reports:

| Coverage field | Value |
| --- | ---: |
| eligible partitions | 100,842 |
| valid prediction partitions | 0 |
| eligible prediction coverage | 0.0 |
| missing or invalid partitions | 100,842 |
| expected snapshot partitions | 2,176 |
| observed expected snapshot partitions | 2,176 |
| missing expected snapshot partitions | 0 |

All 12 blockers are `invalid_eligible_partitions`; the first is the Atlanta
`9,200 of 9,200` row cited by the handoff. Thus the served tape exists and its
expected snapshot coverage is complete. The release-one chain triage records
the rejected rows' direct cause: blank release ID/manifest/pointer fields,
`release_identity_status=research_unbound_non_countable`, and
`serving_model_binding_status=release_unbound_legacy_base_model`.

The scorecard requires `release_identity_sources == ["explicit"]` when
promotion evidence is requested (`live_variant_settlement_scorecard.py:676-677`).
Rejecting these rows is correct.

## Why release #1 clears the dependency without a patch

Three existing fail-closed contracts prove the intended transition:

1. `captured_input_parity_evidence.generate_captured_input_parity_evidence`
   loads a verified active serving bundle before reading its three source
   tapes. `_verify_served_slice` then requires the exact release ID, manifest,
   pointer, sequence, verified release identity status, verified base-model
   binding, and captured-input hash. Pre-release evidence cannot be silently
   upgraded.
2. `registration_parameters.build_registration_parameters` derives one stable
   served/replay pair per routed market only after verifying the active release
   and complete served bundle. It refuses missing evidence files.
3. Both registration scripts require at least one served parity file and one
   replay parity file. The current empty nightly arguments therefore cannot
   become green merely because a pointer appears; post-cutover evidence
   generation and reviewed re-registration are explicit operator steps.

This is the important nuance behind “clears at release #1”: the release #1
cutover owns the fix, while the pointer write alone does not generate or wire
the evidence. The post-promotion checklist in
`docs/operations/RELEASE_ONE_BUILD_RUNBOOK.md` already requires both the
nightly parity unlock and a nonempty explicitly release-bound settlement
scorecard after cutover.

## Evidence hashes

These are ignored runtime artifacts read from the workstation's synchronized
tree. They were not modified.

| Artifact | SHA-256 |
| --- | --- |
| `data/backtest/nightly_retrain_status.json` | `1B3B42A148D7AC8107C769CD1E5CDDDACB3FCBADEEBE26B99BEE3A2ADCC0582D` |
| `data/backtest/live_variant_replay_parity.json` | `A8B6960716A7DC28BE11B3E30114E0AAF7845D51CDC31EFF457D34A586F96435` |
| `data/backtest/live_variant_settlement_scorecard.json` | `B8FEED62F78FC5BB1CCB2F837C7D36F2CE15176658EE6CE3D51C51711011B101` |

The parity artifact's embedded self-hash is
`172f25c3a8eb379af1a403be20faf08246fcb8707fe39f3d0478cfa29899da36`.

## Safety and contention record

- Checked `docs/operations/reserved-confirmation-window.md` before reading
  evidence. It states that no dates are currently reserved.
- Performed no replay, scoring, backfill, registration, loop start, scheduler
  action, release action, or production write.
- Wrote nothing under `data/`, on the production host, or to the mirror or
  `D:\weather-mirror`; did not read `C:\Users\micha\.weathersync.cred`.
- Did not modify any concurrently owned source file, including
  `nightly_retrain.py`.
- A concurrent `-09-22a` mission switched the shared checkout while this audit
  was reading. This branch was moved to the isolated worktree
  `scratch/w/autopsy-learning-loop-09-21a`; the other mission's clean checkout
  and branch were left untouched.

## Handoff

Do not relax either gate. During release #1 cutover, treat the two green checks
as post-cutover acceptance evidence:

1. prove workers emit only the active release identity on a fully post-cutover
   market day;
2. generate the authenticated served/replay pair for every routed market;
3. render and review the exact registration parameters, then re-register under
   separate operator authority;
4. require parity `PASS` and nonzero explicitly release-bound settlement
   coverage on the next ordinary evidence run.

Failure after those steps would be a real release-binding defect. The current
pre-release blocks are correct.

## Verification

- `git diff --check`: pass.
- `python -m weather.operations.agent_docs_audit`: the audit ran and reported
  one unrelated base-tree failure in
  `docs/roadmap/agent-report-2026-08-02-workstation-spec-contract-repair.md`
  (missing target
  `src/weather/reporting/validation/floor_retrain_gate_harness.py#L1079`).
  This mission did not edit that published historical report or its target.
