# Audit dimension: Config, model artifacts, manifests and releases

Key: `config-artifacts` | Auditor run: 2026-09-19 (production host, read-only) | Health grade: **C-**

## 1. Scope and method

Covered:

- `config/` - `AGENTS.md`, `markets.json`, `locations.json` (head + targeted greps), `model_variant_registry.json`,
  `storage_pressure.json`, `supplemental_stations.json`, `no_market_extra_locations.json`,
  `international_live_execution_host.json`, and `location_market_events.json` (NEVER read whole: `Read` with small
  windows, `Grep` with counts/head limits only).
- `artifacts/` - `AGENTS.md`; non-recursive `ls` of `artifacts/`, `models/`, `models/hgb`, `models/coefs`, `manifests`,
  `calibration`, `misc`, `candidates`, `candidates/residual_distribution_v1`; text manifests only (no binary read).
- `.gitattributes`, `.gitignore`, `requirements.txt`, `.github/workflows/retrain.yml`, `.github/workflows/ci.yml`.
- Code traced end to end for every structural claim: `src/weather/operations/location_config_refresh.py`,
  `scripts/ops/refresh_location_config.ps1`, `scripts/ops/register_location_config_refresh.ps1`,
  `scripts/ops/quiet_window_merge.ps1` (3340-3519), `scripts/ops/training_window.ps1` (330-410),
  `src/weather/operations/release_manifest.py`, `release_candidate_build.py`, `release_promotion.py`,
  `src/weather/runtime_identity.py` (whole), `src/weather/collection/snapshot_store.py` (2195-2240),
  `src/weather/operations/event_day_manifest.py`, `src/weather/reporting/serving_gates/runtime_identity_evidence.py`,
  `src/weather/operations/event_metadata_validation.py` (440-690), `src/weather/model/model_features.py` (30-100,
  1350-1400), `src/weather/artifacts.py` (1077-1190), `src/weather/operations/verified_cold_archive.py` (535-605),
  `scripts/ops/production_cold_archive_run.ps1` (1-130), `src/weather/collection/live_variant_predictions.py`.
- Canon consulted for known-status: `docs/operations/STATE_OF_PLAY.md`, `ESTABLISHED_FINDINGS.md` (s0b, s4a-bis, s4b, s6),
  `RELEASE_ONE_BUILD_RUNBOOK.md`, `REPLAY_DOES_NOT_REPRODUCE_WHAT_WE_SERVED_2026-08-11.md`, `OPERATIONS_AGENT_ROLE.md`,
  `artifact-storage-policy.md`, `config-inventory.md`.
- Whitelisted git only: `git log` (path-scoped), `git show --stat`, `git show <rev>:<path>` piped to `head`/bounded
  `grep`, `git diff --stat`, `git ls-files artifacts`.

No python, no tests, no data/ reads, no network, no project writes other than this file.

## 2. Answers to the brief's questions (short form)

| Question | Answer | Basis |
| :-- | :-- | :-- |
| What generates the dirty config? | Scheduled task `WeatherLocationConfigRefresh` (00/06/12/18 local) -> `refresh_location_config.ps1` -> `python -m weather.operations.location_config_refresh`, which rewrites BOTH `config/location_market_events.json` (full Gamma snapshot) and `config/locations.json` (only `event_metadata.last_refreshed_at_utc` changes) in place. | verified_in_code |
| Who commits it? | Two automations: `training_window.ps1:362-384` ("training-window auto-commit", currently idle because training is disabled - STATE_OF_PLAY:36) and `quiet_window_merge.ps1:3487-3494` ("ops: preserve fleet-generated drift (pre-merge, automated)"). Neither pushes by itself. With training disabled, drift is committed only when a merge happens: last one `6dd80bdfa` 2026-09-13; the tree has been dirty since (21,842 changed lines in `git diff --stat`). | verified_in_code + git |
| Why is generated state tracked at all? | Stated rationale (RELEASE_ONE_BUILD_RUNBOOK s1b): "Config hashes are legitimately attested in the release manifest, so excluding config/ from the gate would be wrong." and (quiet_window_merge.ps1:3364-3369) "Commit them rather than ignore them, which both cleans the tree and preserves the drift." The file lives in tracked `config/` rather than ignored `data/` by original placement; nothing requires its history. | doc_claimed + verified |
| Repo growth? | 82 commits touch `location_market_events.json` and 84 touch `locations.json` since 2026-06-21. Each version is ~1.6 MB raw, 20-31k changed lines per commit (token ids are 77-digit numbers and 64-hex condition ids, new every event day, so cross-version delta compression is poor beyond ~3 days). Estimated 0.15-0.25 MB packed per version => roughly 12-20 MB so far, ~40-100 MB/yr depending on commit cadence. **This is an estimate; .git was not measured (forbidden).** It is small next to the pre-LFS pickle history (one full 380 MB model set committed raw 06-13..06-20, including a 103.7 MB blob) and the doc-recorded `.git/objects` 2.11 GiB loose + 536 MiB pack on 2026-06-20. The real cost is not bytes; it is commit noise, HEAD churn and gate interaction (finding 4). | inferred + git |
| Dirty tree vs clean-tree release gate? | `capture_code_identity` (release_manifest.py:127-139) excludes only `artifacts/releases/**`, `artifacts/candidates/**`, `data/**`. The two generated config files count as dirt. Release build (release_candidate_build.py:198-199), promotion (release_promotion.py:994-1004), `base_retrain.py:1579`, `all_shadow_release_bootstrap.py:522` and every verified cold-archive command (verified_cold_archive.py:575-579) fail closed from the production tree within <=6 h of any commit. Archive runners work around it by executing from a separate clean reviewed worktree (production_cold_archive_run.ps1:2, 91-94). | verified_in_code |
| Dirty tree vs code-identity fingerprint? | The runtime `source_fingerprint` covers `*.py`, `*.ps1`, `tools/**`, `requirements.txt` only (runtime_identity.py:19-28): config and model artifacts are NOT in it, so drift commits do not roll the fleet (good) but a changed pickle/calibration/locations file leaves served-row identity unchanged (bad). `git_dirty` is hard-coded `None` (runtime_identity.py:217) and written into every served row as `runtime_git_dirty` (snapshot_store.py:2235). Nothing refuses to serve from uncommitted code. See finding 3. | verified_in_code |
| Model age / provenance? | All 12 served per-market HGB pickles: last content change in git 2026-06-13/14 (`fd728d4a4`, `47635d595`), LFS pointer swap 06-20 (`5b6f5af2d`); on-disk mtimes 06-10..06-13. ~97 days old on 2026-09-19. Toronto calibration: weights 06-07, probability calibration 06-10 (fit on FOUR target dates, selected method `identity`), lag model 06-10, forecast-error model 06-23 (target_date_max 06-22). F-market calibration: 07-07 (target_date_max 07-05). Last commit touching `artifacts/`: 2026-07-15. | verified (git + artifact JSON) |
| Manifests hash-bound to pickles? | Yes for BYTES: registry/externalization `sha256` equals the LFS pointer oid and size equals the on-disk size (checked `feature_model_hgb.pkl` bf53fd60..., 29,230,281 B; `_nyc` a8efd806..., 18,735,619 B). NO for LINEAGE: no training window, training commit, data hash, or trained-at time per pickle; `modified_at_utc` is a checkout mtime (all 2026-07-16T02:56Z, while production mtimes are June). | verified |
| LFS state? | 26 `artifacts/models/hgb/*.pkl` are LFS pointers in git and fully materialized on this host. CI and retrain workflows run with `lfs: false` because LFS checkouts burned ~11.5 GB/month against a 1 GB quota (ci.yml:23-28, retrain.yml:4-8). Pre-LFS raw pickles remain in history (policy forbids rewrite). | verified |
| Has a release ever been cut? | No. `artifacts/releases/` does not exist on disk or in `git ls-files`; ESTABLISHED_FINDINGS:1385-1387 says the same; owner removed Release #1 from the critical path 2026-08-09 (ESTABLISHED_FINDINGS s0b). | verified + doc |
| Registry entries referencing missing artifacts? | None missing on this host. 7 distinct `artifact_path` values in `config/model_variant_registry.json`; 6 are tracked LFS pickles that exist; 1 (`artifacts/candidates/residual_distribution_v1/model.pkl`, `artifact_required: true`) exists only because it sits in a gitignored directory on this host - it is absent from any clone. The promotion preflight never checks existence (artifacts.py:1077-1120). | verified |

## 3. Findings (most severe first)

### config-artifacts-1 (HIGH, new) - The markets' declared resolution source changed from Weather Underground to NWS `weather.gov` timeseries on the 2026-08-23 event, and nothing in the project noticed

Facts, all checkable:

- Current generated snapshot (`generated_at_utc` 2026-09-19T04:00Z): 103 of 119 active events carry
  `resolution_source_url = https://www.weather.gov/wrh/timeseries?site=<icao>`; only 7 carry a wunderground URL; 9 are null
  (Grep counts on `config/location_market_events.json`).
- All 12 captured markets are in the 103: katl (1219), kaus (2095), kord (5911), kdal (7375), kbkf/denver (8251),
  khou (11179), klax (15871), kmia (19387), klga/nyc (22027), ksfo (24955), ksea (26419), cyyz/toronto (31411).
- The durable registry still says WU for every one of them: `config/locations.json` lines 108, 145, 357, 429, 466, 610,
  861, 1038, 1182, 1324, 1396, 1680 (`https://www.wunderground.com/history/daily/...`, `source_type: wunderground_history`).
  `MarketSpec.resolution_source` defaults to `"wu_history"` (`src/weather/market/market_registry.py:43`).
- Dating the change from git: in commit `a414d5648` (2026-08-22) Toronto's events for 08-21 and 08-22 declare the WU URL and
  the event for **2026-08-23** declares `weather.gov/wrh/timeseries?site=cyyz`; the same boundary holds for katl, klga, ksea
  in that snapshot. `d58b64971` (08-19) is all-WU; `398fbe581` (08-23) is weather.gov for cyyz/klga/kmia.
- The value is taken verbatim from Gamma (`location_config_refresh.py:222`, `event.get("resolutionSource")`), so it is not
  a project-side normalisation artefact.
- `wrh/timeseries` has ZERO hits in `src/`, `tests/`, `scripts/`, `docs/`; `weather.gov` has zero hits in
  `docs/operations/`. The 8 `docs/roadmap` hits predate the change or concern NWS as a forecast source.
- The 6-hourly validator cannot see it: `_compare_events` (`event_metadata_validation.py:495-507`) compares the
  *generated* `resolution_source_url` with the *live Gamma* one - Gamma against Gamma. No code compares the market's
  declared source with `locations.json -> settlement.resolution_source_url` or `MarketSpec.resolution_source`
  (the only other readers, `release_candidate_contract.py:712` and `source_family_inventory.py:1519`, read the durable value).

What I did NOT verify (no network, no data/ access): the market rules text, whether Polymarket actually resolves from the
NWS page, and whether the NWS-timeseries daily high differs from the WU daily-summary high on any settled date. The two
are fed by the same ASOS/AWOS sensor, so many days will agree, but they are different products (WU daily summary vs. the
NWS observation time series, which includes sub-hourly observations with different rounding). A 1-degree difference flips a band.

Why it matters: the settlement label is the project's measuring instrument and, for a maker, the contract term. The
"instrument audit CLOSED - labels FLAT" conclusion (OPERATIONS_AGENT_ROLE.md:246) was reached on WU-era evidence. Every
model-vs-market score for target dates >= 2026-08-23 is computed against WU-derived truth while the counterparty prices a
different stated source. Open question worth one look: whether Polymarket left WU because WU history degraded, which would
also bear on the current settlement hole (10 of the last 14 dates unsettled). That link is **inferred, not shown**.

Recommendation: before any other measurement work, take the settled dates since 08-23 that the ledger does hold and compare
(a) the ledger bucket, (b) Polymarket's resolved winning band, (c) the NWS timeseries max for the station/day. Record the
disagreement rate in ESTABLISHED_FINDINGS. Add a validator rule that fails when the live `resolutionSource` host differs from
the durable settlement source host. Escalate to critical if any settled date disagrees.

### config-artifacts-2 (HIGH, known_open) - What is served is a June model: ~97 days old, fitted on a May-10..Jun-30 archive, Toronto calibration fit on four days

- `git log -- artifacts/models/hgb/feature_model_hgb.pkl ..._nyc.pkl ..._miami.pkl` -> only `fd728d4a4` (06-13), `47635d595`
  (06-14), `5b6f5af2d` (06-20, raw->LFS pointer, identical sizes). Post-06-20 commits under `artifacts/models/hgb` touch only
  `clob_overlay_v0_2` and `f_pooled_v0_3` (shadow/diagnostic lanes). Last commit under `artifacts/`: `e72f2f0a9` 2026-07-15.
- `artifacts/calibration/probability_calibration.json:419` generated 2026-06-10; `:1521-1548` trained on 4,763 rows from
  four target dates (05-28, 06-01, 06-02, 06-07); selected method `identity`; it records its own
  `baseline_brier_skill_vs_market: -0.3355`.
- `calibrated_weights.json:1147` generated 2026-06-07; `settlement_lag_model.json` 06-10; `forecast_error_model.json:31`
  06-23 with `target_date_max 2026-06-22` (`:2901`). All F-market calibration files: 2026-07-07, `target_date_max 2026-07-05`.
- Canon already says so: ESTABLISHED_FINDINGS.md:1509 "Every served HGB was fitted 2026-06-10 to 06-13 on that archive, and
  is served in August"; s4b: the archive holds only May 10 - Jun 30 in every year. It is now late September; STATE_OF_PLAY:36
  says training remains disabled; ESTABLISHED_FINDINGS:1383-1392 says the retrain cannot start without an active parent
  release, which does not exist.
- A retrain is maintenance, not "new model-alpha work", but it is blocked behind machinery the owner took off the critical
  path. Net effect: the served forecast drifts further out of season every week with no scheduled remedy.

### config-artifacts-3 (HIGH, known_open) - The runtime identity cannot attest what was served: `git_dirty` is hard-coded `None`, artifacts and config are outside the fingerprint, and one evidence key prints unknown as "clean"

- `src/weather/runtime_identity.py:202-218`: `get_runtime_identity` reads HEAD from `.git` files, never runs `git status`, and
  sets `"git_dirty": None, "dirty_fingerprint": None` unconditionally.
- `src/weather/collection/snapshot_store.py:2229-2238` writes that into every served row (`runtime_git_dirty`,
  `runtime_git_commit`). So a row's `runtime_git_commit` is "HEAD when the process started", with no statement that the loaded
  bytes equal that commit.
- `runtime_identity.py:19-28` `SOURCE_PATTERNS` = py/ps1/tools/requirements; docstring line 8-9: "excluding model/data
  artifacts". A swapped pickle, an edited calibration JSON or an edited `locations.json` does not change `source_fingerprint`.
  (Shadow variants do record an `artifact_hash`, live_variant_predictions.py:584-594; base-model rows instead carry
  `serving_model_binding_status = release_unbound_legacy_base_model`, which is honest labelling.)
- The stale-code guard (`snapshot_store.py:2201-2216`) only compares process bytes with disk bytes. After an in-place edit of a
  loaded module on the production tree the loop goes `stale_code`, is rolled, and then serves the uncommitted bytes under the
  unchanged HEAD commit. No gate refuses to start from uncommitted loaded files.
- `src/weather/reporting/serving_gates/runtime_identity_evidence.py:72-76`: `dirty = ... or ("dirty" if str(runtime_git_dirty).lower() == "true" else "clean")`.
  Because the recorder always writes `None`, every row's evidence key reads `dirty:clean`. `event_day_manifest.py:271-273`
  does the honest thing (`clean_or_unknown`).
- This is the mechanism under the project's own root-cause finding ("324 of 413 fingerprints match no blob in 178 refs",
  REPLAY_DOES_NOT_REPRODUCE...:149-151; OPERATIONS_AGENT_ROLE.md:248-250). The thread was closed for HISTORY; the
  forward-looking defect is still in master: `IDENTITY_SCHEMA_VERSION = "runtime_identity_v0.1"` (line 18), i.e. the v0.2
  binding fix is not merged. Every day served under v0.1 adds more unreconstructable rows.

### config-artifacts-4 (MEDIUM, known_open) - Generated runtime state lives in tracked `config/`, so the production tree is dirty by construction; the cost is gates, HEAD churn and commit noise, not bytes

- Generator rewrites both files every 6 h (`register_location_config_refresh.ps1:33-38`; `location_config_refresh.py:388-390`).
- `config/locations.json` is classified "Durable ... Hand-authored ... Volatile market-event fields are not stored here"
  (`docs/operations/config-inventory.md:9`, `config/AGENTS.md:5-6`), yet the generator stamps
  `event_metadata.last_refreshed_at_utc` into it on every run (`location_config_refresh.py:321-325`; live value
  `locations.json:1848`). 84 commits touch it; a genuine hand edit to a station/settlement fact is indistinguishable in
  `git log` from 80+ timestamp-only diffs.
- Drift is swept into authored commits: `6444cc199` is titled "docs: Gate 3 retired decision 10..." and carries 5,034 changed
  lines of `location_market_events.json`; `d09d8a821` ("research: ...") likewise. Commit subjects stop describing contents.
- Gate interaction (verified): see the table in s2. RELEASE_ONE_BUILD_RUNBOOK s1(b) documents it and makes "commit the drift"
  a build step; `training_window.ps1:356-384` automated that, but training is disabled, so today only a quiet-window merge
  cleans the tree. Promotion additionally requires `current HEAD == manifest commit` (`release_promotion.py:1003-1004`), so any
  later drift (or docs) commit invalidates a built-but-unpromoted release.
- Because the production tree can never pass a clean-tree gate on its own, clean-tree tools are run from separate reviewed
  worktrees (`production_cold_archive_run.ps1:2, 91-94`). That is sound, but it is one structural reason the repo carries ~200
  worktrees (inferred).
- 39 of the 51 locations in the snapshot are not captured markets (`locations.json` has 51 `id` entries; the platform
  captures 12), i.e. roughly three quarters of each 1.6 MB version is for markets the project does not trade.
- Accidental benefit, worth keeping: the committed history is what made finding 1 datable. If the snapshot moves out of git,
  archive each refresh append-only under `data/` instead of discarding it.

Recommendation: move the volatile snapshot (and the `last_refreshed_at_utc` stamp) out of tracked `config/` into `data/`
with an append-only archive; keep `locations.json` genuinely hand-authored; have releases attest the snapshot by hash at build
time from its new location. That removes both auto-committers, the merge-tool allowlist, and the permanent-dirty state.

### config-artifacts-5 (MEDIUM, new) - The only serving path that has ever run loads the base model fail-open and unverified

- No release pointer exists, so `_bound_base_component` returns `(False, None)` and `_read_feature_model_hgb`
  (`src/weather/model/model_features.py:59-71`) does `pickle.load` on `artifacts/models/hgb/feature_model_hgb<suffix>.pkl`
  with no hash check against any manifest. Missing file -> `None` with no log; any exception (an unsmudged 133-byte LFS
  pointer, an sklearn mismatch, a truncated file) -> `logger.warning` and `None`.
- `feature_model_distribution_for_cutoff` (`model_features.py:1361-1366`) then silently serves LR-only, or `"empirical"` if the
  coefs also fail. The row records `active_model_kind`, so it is detectable after the fact, but no file under
  `src/weather/operations/` or `src/weather/reporting/fleet/` references `active_model_kind` - there is no alert.
- CI never loads the pickles ("The test suite stubs these artifacts and does not read their bytes", `ci.yml:23-28`), so the
  production loop is the only place the sklearn==1.8.0 pin (`requirements.txt:9`) is ever exercised against the real bytes.
- The hash-verified loader exists (`release_serving.py:203`, "immutable, hash-verified release artifact") but is unreachable
  until a release exists.

Recommendation: verify the pickle's SHA-256 against `model_artifact_registry.json` on load in the legacy path, fail loud
(status + alert) on load failure, and add a fleet alert on any change of `active_model_kind` per market.

### config-artifacts-6 (MEDIUM, new) - Artifact registry binds bytes but not lineage, and its vocabulary inverts reality

- `artifacts/manifests/model_artifact_registry.json:2199-2206`: 93 of 103 artifacts are `unregistered_runtime_artifact`,
  including all 12 served per-market HGBs, `f_pooled`, and every calibration JSON. The single `active_promoted` artifact
  (`:1713-1714`) is `feature_model_hgb_f_pooled_clob_overlay_v0_2.pkl`, which the variant registry marks
  `promotion_status: diagnostic_only` (`config/model_variant_registry.json:124-142`).
- `artifacts/misc/afternoon_residual_centering.json` is `registry_use: "unreferenced"` (`registry:1053-1054`) while it is
  `enabled: true` and loaded by the serving model (`src/weather/model/toronto_model.py:147, 254`). "Unreferenced" means "not in
  the variant registry", not "unused"; a storage clean-up reading it literally would delete a live serving input.
- No per-pickle lineage: `feature_schema_version`, `model_schema_version`, `schema_version` are `null`; `modified_at_utc` is a
  checkout mtime (all 2026-07-16T02:56Z). `models/coefs/*.json` carry no metadata block at all. The only training provenance is
  inside some calibration JSONs.
- Machine-specific absolute paths are committed in `f_family_secondary_artifacts.json` (e.g. `:4`, `:21`, `:86`) and
  `forecast_error_model.json:2872-2897`; that manifest is also the live per-market serving gate for the 11 F markets
  (`model_features.py:1373-1394`) and binds its artifacts by path only, not by hash.
- Registry, externalization, size-audit and preflight manifests were all generated 2026-07-16T03:21Z. They are still
  byte-accurate only because nothing under `artifacts/` has changed since 07-15.

### config-artifacts-7 (LOW, new) - Generator write safety and newline contract

- `write_json` (`location_config_refresh.py:63-67`) writes in place with `Path.write_text` - not temp-file + atomic replace -
  to two files that capture paths read (`market_microstructure_capture.py:988-1009`, `execution_tape_capture.py:40-131`,
  `snapshot_tracker.py`). A kill or power loss mid-write (the host's documented top uncontrolled risk) leaves a truncated
  tracked config. `snapshot_tracker.atomic_write_json` already exists in the codebase.
- Text-mode write on Windows emits CRLF into a file pinned `eol=lf` (`.gitattributes:4`); `git diff --stat` warns for both files
  today, and `quiet_window_merge.ps1:3513-3517` records that this exact warning killed a merge dry-run on 2026-07-25. One-line
  fix: `newline="\n"`.

### config-artifacts-8 (LOW, new) - Promotion preflight never checks that registry-referenced artifacts exist

- `_variant_local_path_checks` (`src/weather/artifacts.py:1077-1120`) only flags `artifact_path` values under `data/` for
  `lifecycle == "active"` variants. The only other checks are manifest identity drift and an unreadable registry.
- `residual_distribution_v1` has `artifact_required: true` and points into gitignored `artifacts/candidates/`
  (`config/model_variant_registry.json:252-253`; `.gitignore:21`); on any clone the file is absent and preflight still PASSes.
  At runtime a missing artifact becomes a per-variant error string (`live_variant_predictions.py:580`), not a gate.
  Bounded today because that variant is `lifecycle: shadow`, `live_capture_enabled: false`.

### config-artifacts-9 (LOW, known_open) - LFS and object-store state

- CI/retrain run `lfs: false` after exhausting the 1 GB/month LFS bandwidth quota (`ci.yml:23-28`, `retrain.yml:4-8`). A fresh
  clone that needs the 382 MB of model bytes may not be able to `git lfs pull` them; with the data mirror paused, the
  materialized pickles are reliably present only in the two hosts' working trees and `.git/lfs`. (Backups are a closed owner
  decision; noted once, not raised.)
- Pre-LFS raw pickles (one full set, 06-13..06-20, incl. a 103.7 MB blob and ~8 versions of the overlay) stay in history by
  policy. `artifact-storage-policy.md:110-120` recorded 2.11 GiB loose objects on 06-20 and conditions `git gc` on "active
  branches are settled and the worktree is clean" - a condition finding 4 shows is never true on this host.
- `feature_model_hgb_f_pooled.pkl` is 103,734,643 B = 98.9 MiB, inside the 90-100 MiB single-artifact warn band; the audit
  PASSes only because LFS-managed bytes are exempt.
- `.github/workflows/retrain.yml` is a dead manual workflow: with `lfs: false` it would upload pointer files as "candidate
  artifacts", and it still runs a network backfill on a hosted runner.

### config-artifacts-10 (INFO, known_accepted) - No release has ever been cut; the release machinery has never run on real evidence

- `artifacts/releases/` absent on disk and in `git ls-files`; RELEASE_ONE_BUILD_RUNBOOK:14 "This is the first release the
  project has ever built"; ESTABLISHED_FINDINGS:1385-1387 verified absent; owner decision 2026-08-09 (ESTABLISHED_FINDINGS
  s0b) took Release #1 off the critical path.
- For scale: `release_*.py`, `base_retrain.py`, `nightly_retrain.py`, `all_shadow_release_bootstrap.py` in
  `src/weather/operations/` total ~450 KB of source that has never executed against production evidence, while the live path
  is the legacy fallback in finding 5. The known circularity stands: `base_retrain` requires an ACTIVE parent release.
- A release would also freeze a copy of the ephemeral 1.6 MB events snapshot as a "frozen location role"
  (`release_candidate_contract.py:487-491, 1504-1508`); nothing consumes that frozen copy.

## 4. Strengths

- Byte-level integrity is real: registry and externalization `sha256` equal the LFS oid and sizes match disk
  (`artifacts/manifests/model_artifact_registry.json:1558` vs `git show HEAD:artifacts/models/hgb/feature_model_hgb.pkl`).
- scikit-learn is pinned exactly with the reason written down (`requirements.txt:1-9`).
- Clean-tree gates fail CLOSED and distinguish `False` from unknown (`release_candidate_build.py:198`,
  `release_promotion.py:994-1004`, `verified_cold_archive.py:557-579`).
- The two auto-committers are narrow and careful: exact two-path allowlist, JSON validation before commit
  (`training_window.ps1:362-384`), SHA-256 of the pre-merge bytes and a journaled rollback that preserves the generated
  content (`quiet_window_merge.ps1:3421-3512`).
- The variant registry is honest about quarantine: leak-tainted item-224, the density lane and every legacy candidate carry
  explicit `promotion_block_reason` text (`config/model_variant_registry.json:24-29, 183, 190-205`).
- Checked-in config contains no credentials; `international_live_execution_host.json` holds hashed public ids only;
  `storage_pressure.json` default preserves capture as its AGENTS.md requires.
- The refresh is followed by an independent live validation that gates task success (`refresh_location_config.ps1:58-70`) -
  good design, even though it has the blind spot in finding 1.

## 5. Not covered / limits

- `.git` size, LFS store size and pack statistics: not measurable under the rules; growth figures are estimates.
- `data/` status files (`event_metadata_validation.json`, `nightly_retrain_status.json`, settlement ledgers): not permitted
  by this brief, so the settlement-vs-resolution comparison in finding 1 and the live cause of the failed archive tasks were
  not examined.
- Pickle contents and whether the working-tree pickles hash to their LFS oids (no python, no hashing tool used).
- Contents of other branches/worktrees (e.g. the unmerged identity v0.2 fix `4050f1ee`) were not inspected.
- `config/location_market_events.json` was sampled by grep and four small windows, never read whole.
- Tests covering config/artifact code were not read.

## 6. Open questions for the owner

1. Do the settled dates since 2026-08-23 agree between the WU ledger bucket, Polymarket's resolved band and the NWS
   timeseries maximum? (Finding 1 - the one question that could change what every recent score means.)
2. Did Polymarket leave WU because WU history degraded, and is that related to the current settlement hole?
3. In `f_family_secondary_artifacts.json`, `artifact_replay_brier` exceeds `baseline_brier` for the family and 10 of 11
   markets, including one whose selected method is `identity` (:480-485). The two metrics are evidently not the same pipeline;
   what does each measure? (Not raised as a finding: I could not trace it without running code.)
4. Is there any reason to keep the events snapshot in git once an append-only archive exists?
5. Should the legacy serving path get hash verification now, given that a release is not coming soon?
