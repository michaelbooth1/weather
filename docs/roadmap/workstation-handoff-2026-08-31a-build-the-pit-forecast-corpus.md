# Workstation handoff 2026-08-31a — build the point-in-time forecast corpus

Run this now. **Implementation and tests only: no network, no provider call, no fetch, no fit, no
retrain, no candidate, no fresh dates.** `-08-16a` remains queued for 2026-08-05 04:30.

## Your last mission changed the plan

`-08-30a` proved exact public-WU parity fails — and it failed on the dimension that cannot be
engineered around. Content parity passed cleanly: both unit modes, 60 observations, 13 artifact-era
fields, zero mismatches, with `temp_native`/`dewpoint_native` correctly taken ahead of the lying
`*_c` aliases. But both packets arrived **~23.6 hours after the 10:00 cutoff**.

Public WU history is a next-day product. A next-day response cannot serve a same-day row however
exactly its values reproduce training. That is structural, so **no-refit restoration is impossible in
principle**, and the ten fields can only come back through METAR/ECCC — which requires a retrain.

Stopping there was exactly right, and it collapses the sequencing: **there is no longer a WU gate
preceding the first retrain.** The observation contract folds into the retrain's feature contract. So
`-08-28a`'s "gate WU restoration first" is void, and the forecast corpus is now the critical path on
its own.

## Build it

Implement the corpus lane you specified in `-08-28a` §3 and refined in `-08-29a`. **No network in
this mission** — build the machinery and prove it against fixtures. The single authorized provider
probe and the real build come later, as their own decision.

1. **Planner.** An immutable plan of every market/year/endpoint/window/model/variable request,
   written *before* any network access would occur.
2. **Request-keyed staging.** Each raw response under a staging root with HTTP metadata, retrieval
   time, SHA-256, byte count, validation status.
3. **Resume ledger.** Resume by skipping only hash-verified complete units. An explicit failure
   ledger — **zero rows is never silently success.** Today's `backfill()` catches a year error,
   continues, and overwrites the three canonical CSVs from whatever survived in memory; that
   behaviour must be unreachable from the new lane.
4. **Atomic publication.** Materialize derived files only after every required unit and field matrix
   passes, then publish a content-addressed corpus manifest atomically. **Never overwrite the active
   archive in place.**
5. **Training-only path.** Outside `data/forecast_history`, **undiscoverable by `daily_path_for()`**,
   passed explicitly to the base-retrain candidate and its preflight. The active analog archive stays
   byte-for-byte pinned.

## The contract it must enforce

From `-08-29a`, and I want these as executable gates rather than documentation:

- `issue_time <= row cutoff` for every accepted row. Initialization time alone is insufficient —
  Single Runs publishes 1–6 hours after init, so the conservative `available_at_utc` governs.
- Stitched or empty-issue rows are **rejected**, never relabelled. No compatibility fallback to
  `forecast_daily.csv`.
- Row provenance carried into the immutable training graph: provider, endpoint, request hash, model,
  run ID where exposed, lead, units, normalizer version, raw response SHA-256, and an issue-evidence
  kind.
- **Target year structurally excluded** — `target_year_excluded=true`, years enumerated before
  collection, a target-year response rejected from the training role even if present in a shared raw
  store. That is also the cleanest proof reserved 2026 outcomes never entered training.
- Coverage evaluated **per market, year, date, field, issue contract and cutoff** — not by row count.

## Do not repair only the daily scalars

This is the part `-08-29a` found late and I do not want lost. The same stitched source feeds:

- **all `FORECAST_PROFILE_COLUMNS`** — `forecast_long.csv` *does* retain source, model and issue
  basis, but `load_profiles` discards it. Not in the legacy 168 HGBs, but **in the pooled v0.3
  feature universe**, so the first retrain is exposed through dozens of cloud, radiation and
  thermodynamic features;
- three forecast-relative marine fields;
- the forecast-error secondary artifact (`forecast_rows_from_daily_archive`, Toronto n=332);
- late-day continuation and analog distance.

Each must route through the same cutoff-valid resolver or be explicitly excluded with its exclusion
receipted. Repairing `forecast_high` alone would leave the retrain contaminated through the profile
path.

## What I want back

1. The lane, with tests, on a branch off `master` @ `b7345ab2`.
2. Proof the failure modes are unreachable: partial publication, silent zero-row success, in-place
   overwrite, target-year admission, stitched-row admission.
3. A dry-run plan receipt for the 2021–2025 build showing exactly what *would* be requested — the
   artifact I would review before authorizing a single network call.
4. Which files are roll-sensitive under `SOURCE_PATTERNS`.
5. Anything in your own `-08-28a`/`-08-29a` specs that did not survive contact with the code.

## Sequencing

The release build window is open. **Do not touch the release path, the parity gate, or serving.**
This lane is training-only and must be independently mergeable. The provider probe and real build are
a separate authorization I have not given.

## Constraints — unchanged

- Base on `master` @ `b7345ab2`.
- **No network access. No provider call of any kind.** Fixtures only.
- **Do not read, enumerate, evaluate, or substitute 2026-07-27 → 07-31, 2026-08-01 → 08-03, or
  2026-08-06 → 08-19.**
- **Do not fetch, backfill, refresh, or write any archive, artifact, sidecar, prior, or cache.**
- **POST-regime rows only.** `2026-07-31` is a `rows[-1]` regime boundary.
- **Never weaken the trusted observed-high floor.**
- `data/` strictly read-only with the OS-level deny-write ACL; all output under one declared run root
  outside the mirror.
- **No** promotion, pointer change, serving change, scheduler change, capture restart, PR, merge, or
  master push. **No** mirror topology change, **no** ACL change, **no** paid-provider change.
- Topic branch only. Do not access the production host or the mirror sync credential.

## Handback

Push the topic branch and report the branch and commit. The artifact I care most about is item 3 —
the dry-run plan receipt — because that is what I will review before any network call is authorized.
