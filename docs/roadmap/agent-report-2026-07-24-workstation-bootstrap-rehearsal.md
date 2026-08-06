# Workstation Release-#1 Bootstrap Rehearsal — 2026-07-24

## Handoff identity

- Topic branch:
  `codex/workstation-bootstrap-rehearsal-2026-07-23`
- Pulled `origin/master` and based the topic branch at:
  `00032eeafaeaeeb12dca9a9885086ee76f8f7907`
- Accepted hardened comparison identity, inspected in detached worktrees without
  merging or cherry-picking:
  `423eaa59beee83b0345ace0027b97d4df09a0254`
- Input-manifest self-hash:
  `af3beab6e32de7798ff27678f5af1f723f35d1c243dde6f8e57267cc4b5f6b1b`
- Report commit: the commit containing this file. A commit cannot contain its
  own final object ID.

No merge, PR creation, promotion, serving change, release-pointer write,
scheduler change, collector change, sizing change, trading change, or capital
change was performed.

## Executive decision

**NO-GO for release #1 on current master.**

The Phase-4 nightly point-in-time implementation is present on master, so the
2026-07-12 software gap is closed. The path nevertheless cannot construct
release #1 from a fresh Toronto lock today:

1. folder-mode grade authority can silently fall back from the append-only
   ledger to a stale `settlement.json`;
2. real ledger `winning_band` spelling is incompatible with PIT source-row
   spelling;
3. pooled training cannot cover the current-year lock under its historical
   cache rules; and
4. after that condition is synthetically relaxed, pooled rows expose a
   `date`/`target_date` contract mismatch.

The accepted hardening is also **not merge-ready as-is before lock**. It adds
valuable true-positive checks, but current master-generated operational
manifests need migration, its 240-character path budget rejects an otherwise
working workstation layout, and its physical-ratchet reader terminates with an
unhandled receipt-pairing exception on the current legacy artifact.

Neither identity built a release. Both scratch active-release pointers remained
absent. The downstream master candidate, reached only after explicit synthetic
code relaxations, was independently NO-GO: promotion had 0 promote, 10 shadow,
and 1 blocked market; PIT qualification was `BLOCK`.

## Important isolation breach

The selected frozen input files were unchanged, but the rehearsal did **not**
fully satisfy the read-only mirror guardrail.

Although every nightly top-level output argument was redirected under
`scratch/workstation-research-output/`, nested promotion/replay code retained
defaults under `data/backtest/`. The final audit found 12 mirror paths with
rehearsal-time writes. Three were newly created and nine pre-existing files were
overwritten. The old contents of the overwritten ignored files were not
available from Git, so no restoration was attempted; writing again without a
known preimage would have compounded the breach.

This also means the sequential master/hardened comparison was identical for the
hash-frozen PIT folders, ledgers, and source corpus, but not for every mutable
default artifact under `data/backtest/`. Hardened promotion ran after master had
already rewritten at least the promotion allowlist. Conclusions below identify
which results remain valid despite that limitation.

The final mirror state attributable to the rehearsal is:

| Path under `data/backtest/` | Final action | Final SHA-256 |
| :--- | :--- | :--- |
| `f_family_promotion_allowlist.json` | overwritten 00:48 | `2199ab1986f0fe61f2fa6af1189eca01f8fc038f9bf2ce12a56e78bb0a5e4d23` |
| `location_trust.json` | overwritten 01:19 | `da4c27a5fe1dc178d852b8aafd45b0df015b5821873e050c0f43e34a97b0e89c` |
| `pooled_candidate_current_replay_latest_report.md` | created 01:22 | `7125c547c991f98d18f259302e3f64a844c8132b75a59c2b90c8e4979d9a7a98` |
| `clob_overlay_shadow_variants.csv` | overwritten 01:23 | `19928676c4a232903ca666b0a8cb72f0de48c98cb32c5a78c4ba76122aa40442` |
| `source_state_ablation_shadow_variants.csv` | overwritten 01:23 | `c5917c5ed0122e80045e6e7673d19c81efb12c8ddd7f0baded51c8bc8ea5f474` |
| `conservative_bridge_shadow_variants.csv` | overwritten 01:23 | `e3644fb7c963d89dabcb56c3c854899c25e735a54948ae1a3402c2f91c66be38` |
| `pooled_candidate_replay_latest_report.md` | overwritten 01:23 | `175fdf6526ece2ddffdb88203212cd9f1784fd3e361d696dede5551c8151a52e` |
| `pooled_candidate_replay_latest.json` | overwritten 01:23 | `bae7c94f5cba1d6c6e1cecfdb15d0ddca23181d96ea3ee468b597d1ef679df53` |
| `promotion_replay_latest_report.md` | created 01:25 | `ef30c2591d5260027d5aec4b00bfdcbefc56c14e524af4ac317cebacd73bd91e` |
| `serving_gauntlet_manifest.json` | created 01:26 | `13e92b3283db82188808227e4d57b57108295d4d6ed0cfc5226385dc8d13b3c3` |
| `promotion_gauntlet_latest_report.md` | overwritten 01:26 | `0bb22b823d407b95f2511ed31cee837b6428dc47945b6afc1a55c96ce6156016` |
| `f_family_promotion_refresh_incomplete.json` | overwritten 01:26 | `d144a624c89b269f6d7ca27ca9062fe6cac9884d4210135d74f42080c36500f2` |

Times are America/Toronto on 2026-07-24. This is both a guardrail breach and
evidence for finding A6 below.

## Rehearsal contract and limitations

The handoff requested dry-run/research mode. On both identities:

- `nightly_retrain --dry-run` only plans commands and returns before PIT,
  training, qualification, or release construction
  (`nightly_retrain.py:2013-2044`);
- research-only candidate mode clears the PIT roles
  (`nightly_retrain.py:537-546`); and
- first-inactive-release bootstrap rejects research-only mode
  (`release_bootstrap.py:160-166`).

The only way to exercise the real code path was therefore production candidate
semantics with every intended output and release path aimed at isolated
scratch, a nonexistent scratch pointer, and the explicit first-inactive-release
bootstrap contract. This exercised production code semantics; it did not claim
production evidence.

The fixture was unmistakably synthetic:

- purpose:
  `SYNTHETIC_REHEARSAL_ONLY_DO_NOT_USE_AS_SETTLEMENT_EVIDENCE`;
- `synthetic=true`;
- `production_evidence_authorized=false`;
- 14 contiguous Toronto dates, 2026-07-08 through 2026-07-21, forced to
  `complete` only in a scratch ledger;
- 36 bounded Atlanta dates, 2026-06-06 through 2026-07-21, used because the
  production nightly parser is F-family-only and the latest 14 dates become
  locked, leaving older dates necessary for selection/training; and
- 204 source-ledger, tape, replay, settlement, and optional feature files
  inventoried by size and SHA-256.

The post-run verifier re-read and re-hashed all 204 frozen inputs:
**PASS, 204/204 unchanged**. The Toronto and Atlanta source-ledger hashes were
respectively
`63be41b1bbe9960a4e1f7a022ab98d9fd6b45909d41c69855e07aad384c06c93`
and
`a6b693344a53d49b0cd19675e9b3fa86f628637647c9b2a8487ae9d62060ae65`.

Host gates were disabled only where a workstation cannot supply production
evidence: offline-host capture-resource mode, zero workstation hardware
thresholds, scratch long-job state, and skipped settled-freshness, daily
learning, experiment queue, shadow monitor, and production-readiness checks.
The explicit `--skip-captured-input-replay-parity` waiver was not used.
However, the first-inactive-release bootstrap contract itself deliberately
defers ordinary pre-release parity until the inactive release exists. Because
no release was built, release-bound replay/serve parity was not reached.

The unmodified pooled path blocked before training. To learn whether later
gates were wired, a marked `sitecustomize` relaxation then:

- shifted the model target date to 2027 so 2026 history was available;
- widened the seasonal cache from 7 to 60 days;
- aliased generated row `date` to required `target_date`; and
- reduced bootstrap iterations from 2,000 to 10.

All results after those relaxations are diagnostic-only and cannot satisfy a
release gate.

## Scratch evidence inventory

These scratch files are intentionally ignored and are not part of the pushed
topic branch. Paths are retained here so the workstation operator can inspect
the exact local evidence before scratch cleanup.

| Evidence | Absolute path | File SHA-256 |
| :--- | :--- | :--- |
| Frozen input manifest | `C:\Users\Michael\Documents\Codex\2026-07-23\pull-origin-master-and-execute-the-2\work\weather-bootstrap-rehearsal\scratch\workstation-research-output\bootstrap-rehearsal\inputs-atlanta-compatible\input-manifest.json` | `a7a58edcca4283ab2de827095774d1317fe1de39930c253ed518060325483d59` |
| Master unmodified pooled-coverage block | `C:\Users\Michael\Documents\Codex\2026-07-23\pull-origin-master-and-execute-the-2\work\wm\scratch\workstation-research-output\r1\nightly-status.json` | `514ac387ba8db2098516cef6298c8c4cf86667730b8833fb79e3f2c65303a657` |
| Master relaxed `target_date` block | `C:\Users\Michael\Documents\Codex\2026-07-23\pull-origin-master-and-execute-the-2\work\wm\scratch\workstation-research-output\z\nightly-status.json` | `45f0d37522a8feb0ecdd6929c1bc048ce5bfe5e13b32f5ee3e8a9b4d74a6e85d` |
| Master diagnostic continuation | `C:\Users\Michael\Documents\Codex\2026-07-23\pull-origin-master-and-execute-the-2\work\wm\scratch\workstation-research-output\z\continuation.json` | `31b88ceadab72c6905103145e2d64af71db8815a37f7a172ff28104f6bceb402` |
| Hardened terminal status | `C:\Users\Michael\Documents\Codex\h-r1\scratch\workstation-research-output\r\nightly-status.json` | `c10cc230363f745f4aa90551d1c8c8050bdcb630fa47562f09e46c53034dc69f` |
| Hardened terminal report | `C:\Users\Michael\Documents\Codex\h-r1\scratch\workstation-research-output\r\nightly-report.md` | `967835d19eeaeb5164e684ff932c399ce939126665221a758a7dce7b81e43e99` |
| Synthetic code-relaxation marker | `C:\Users\Michael\Documents\Codex\2026-07-23\pull-origin-master-and-execute-the-2\work\weather-bootstrap-rehearsal\scratch\workstation-research-output\bootstrap-rehearsal\harness\relaxation\sitecustomize.py` | `6bc9caecf5b26b3257042afbd1809c2a9c314ed293afcf6051b8483670129313` |
| Post-run input, pointer, and mirror-write audit | `C:\Users\Michael\Documents\Codex\2026-07-23\pull-origin-master-and-execute-the-2\work\weather-bootstrap-rehearsal\scratch\workstation-research-output\bootstrap-rehearsal\final-safety-audit.json` | `fd330a2c6d5d26693d0af6dd12b7e6c1df54b8a59b8bde4089df67da0aba6b63` |

The input manifest's embedded canonical self-hash is `af3beab6…`; its ordinary
file-byte hash is the distinct `a7a58edc…` shown above.

## Phase-4 nightly PIT status

**Software integration: present on master. Production evidence: still open.**

The nightly implementation covers preselection, frozen replay binding,
qualification, and release handoff in
`src/weather/operations/nightly_retrain.py:533-944,970-1002,2045-2238`.
The roadmap itself records the integration as complete while retaining the
production-evidence item at
`docs/roadmap/items/item-321-model-production-readiness-evidence-integrity-and-staged-release-program.md:603-625`.

The workstation reached the real prelock, family-secondary, pooled-training,
promotion, and PIT-qualification commands. It did not reach a successful
candidate-release build.

## Grade-authority result

`market_day_labels.csv` is not in the PIT preselection call chain.

The folder-mode chain on master is:

1. `nightly_retrain.point_in_time_preselection_command()`
   (`nightly_retrain.py:652-708`);
2. `point_in_time_evaluation prelock-production`
   (`point_in_time_evaluation.py:5143-5222`);
3. grade-only `build_promotion_corpus(...,
   admit_promotion_countable=False)`;
4. `load_bounded_preselection_folder_inputs()`
   (`pooled_candidate_replay.py:2326-2425`);
5. `ledger_label_for_slug()` selecting the greatest
   `(revision_number, file order)`
   (`settlement_ledger.py:790-797,892-902,1079-1092`);
6. admission on `quality_grade`, sealed with
   `admitted_by="quality_grade"` (`promotion_corpus.py:232-315`); and
7. independent source verification of the same grade/authority contract
   (`point_in_time_evaluation.py:1507-1552`).

PIT finds the ledger via `SETTLEMENT_LEDGER_ROOT`; nightly's separate
`--ledger-root` option does not route this call.

The authority is nevertheless fail-open. A ledger label is accepted only when
its absolute `snapshot_tape_path` resolves to the current folder tape. If that
comparison fails, the loader silently reads `folder/settlement.json`
(`pooled_candidate_replay.py:2397-2409`;
`settlement_io.py:131-152`). Current Toronto rows contain a production-host
absolute root that differs from the relocated workstation root, so the
workstation would consume the sidecar unless the scratch ledger path were
rewritten.

The fixture rewrote only the scratch synthetic `snapshot_tape_path`.
The bounded prelock screen then returned the synthetic ledger record and its
`complete` grade for all 36 F-family dates. That proves the ledger branch won
in the exercised fixture; it does not cure the master fail-open behavior.

There is a second mode: the production training wrapper hardcodes a previously
staged source trio under
`data/analysis/point_in_time/production_source_2026-07-16`. When supplied, PIT
verifies and byte-copies that trio and does not reread the ledger. A fresh,
date-bound staging action is therefore required when Toronto locks.

## Run comparison

The master and hardened source corpora had identical parquet bytes:
`e66c3e292e77dd4dc3f3532df5fc1dc7bb521cda5c47b5137ca77cc7af37b6cb`.
Both produced the same `window_lock_id`:
`7f23846fc7507b5809b67cfe9ffb77cfee821dd1db97cb8574c322317dd1b3f0`.
Their complete preselection artifacts are not byte-identical because each
binds its branch-native v0.1/v0.2 replay manifest and corpus hash.

Their operational replay manifests intentionally differed:

- master: `promotion_corpus_v0.1`, 36 entries, corpus hash
  `30a9da19a71dbc125d59a96c406033b71809821ec1707ccdd23f2f90a0436706`;
- hardened: `promotion_corpus_v0.2`, 36 entries, corpus hash
  `747c37e6c07f19e64d34f7e11efec43729430a21fdb772041d88dee3e26ad063`.

| Gate | Master `00032eea` | Hardened `423eaa59` |
| :--- | :--- | :--- |
| Raw ledger spellings | PIT source verification rejected `86-87 F` versus materialized `86-87°F` | same underlying input issue |
| Compatible synthetic prelock | PASS, lock `7f23846…` | PASS with branch-native v0.2, same lock |
| Family-secondary artifacts | PASS, 11 ML serving modes | PASS, 11 ML serving modes |
| Unmodified pooled training | BLOCK: current-year/seasonal cache did not cover locked dates | same master-derived BLOCK |
| With only history relaxation | BLOCK: rows had `date`, verifier required `target_date` | same latent contract |
| With all marked relaxations | PASS, 3,164 rows, model SHA-256 `4e14b667…` | PASS, 3,164 rows, model SHA-256 `03767374…` |
| Promotion | command completed; 0 promote, 10 shadow, Atlanta blocked | ERROR after replay: inventory payload/receipt pairing |
| PIT qualification | BLOCK; 14 dates, 23,518 window rows, 149 excluded cutoffs, all `probability_simplex_failure` | not reached |
| Candidate release | skipped | skipped |
| Scratch active pointer | absent | absent |

Master's diagnostic promotion result had Atlanta candidate Brier `0.05338`,
market Brier `0.03791`, delta `+0.01547`; the daily-first candidate was not
within market tolerance. Its serving gauntlet was `PASS_WITH_SHADOWS`, but
readiness remained `OPEN`. These are synthetic-candidate outcomes, not proof of
a master code defect.

Master PIT source quality was `PASS`, but streaming evaluation was `BLOCK`
because 149 cutoffs across nine dates failed the probability simplex. This too
is diagnostic evidence from the relaxed synthetic candidate, not a claim about
the future production artifact.

The mirror-write limitation does not invalidate every comparison:

- A1-A4, B1, and B2 are frozen-input or direct code-path findings observed
  before mutable promotion outcomes;
- B3 consumes `physical_feature_family_ratchet.json`, whose SHA-256 is
  `13a436aa…` and whose last write was 2026-06-24, outside this rehearsal; and
- the master promotion metrics and all cross-identity promotion-result
  comparisons are **not** identical-mutable-input evidence.

## Classification (a): blocks or imperils release #1 on master

### A1 — Fail-open ledger authority

**Must fix before lock.**

Absolute path equality controls whether PIT uses the append-only ledger.
Relocation, drive-letter, or repository-root drift silently selects a possibly
lagging folder sidecar. A ledger correction can therefore fail to change the
selected window even though the code appears ledger-first. The loader should
fail closed or bind a portable tape identity; it must not silently downgrade
authority.

### A2 — Ledger/source winning-band spelling mismatch

**Must fix before fresh lock staging.**

Authoritative rows use spellings such as `86-87 F`; bounded PIT source rows use
`86-87°F`. Exact source verification at
`point_in_time_evaluation.py:1507-1562` rejected every affected date. The
rehearsal normalized only the scratch synthetic ledger to continue. Define one
canonical unit/band representation at the ledger-to-source boundary and test
the real ledger spellings.

### A3 — Pooled cache cannot cover a current-year 14-day lock

**Must fix before lock.**

`model_climatology.py:96-104` excludes
`local_date.year >= self.target_date.year` and limits history to
`HISTORY_WINDOW_DAYS`, currently 7 (`model_constants.py:25`). The production
PIT trainer then requires every locked date to exist
(`pooled_feature_assembly.py:897-912`). All 14 rehearsal dates were missing.
Even moving the target year forward left early lock dates outside the
seven-day seasonal window. Align the PIT corpus requirement and historical
cache semantics, with a real current-year lock regression.

### A4 — Pooled feature-row date contract is internally inconsistent

**Must fix before lock.**

`build_historical_feature_record()` emits `"date": local_date`
(`feature_store.py:1368-1370`), while `_pooled_pit_target_date()` reads only
`row["target_date"]` and raises on absence
(`pooled_training.py:296-306`). This became the next deterministic block after
the cache rule was relaxed. Use one field contract and add an end-to-end
production-preselection training test.

### A5 — Toronto lock is not bound to the staged F-family source trio

**Must close operationally, preferably in code, before lock.**

The nightly parser is F-only, while Toronto is C. The wrapper trusts a
hash-bound staged F-family trio but does not prove that its staging decision was
triggered by, or is contemporaneous with, the exact 14 Toronto ledger dates.
The currently hardcoded `production_source_2026-07-16` cannot acquire later
ledger revisions by itself. Require a fresh staging receipt that binds the
Toronto lock dates, latest ledger revisions, and resulting F-family trio.

### A6 — Frozen prelock is followed by mutable rereads and uncontained writes

**Must fix before lock.**

Nightly verifies a frozen replay manifest, then promotion rebuilds a corpus
from live folder paths with promotion-countable admission enabled by default
(`nightly_retrain.py:793-944`;
`promotion/orchestration.py:282-295`). The binding retains the old replay
hashes and a folder/date inventory, not hashes of the freshly rebuilt corpus.
The observed 12 writes also prove that explicit nightly scratch outputs do not
contain nested promotion/replay defaults. This can introduce post-lock drift,
cross-run contamination, and workstation/production path leakage.

Freeze once and consume the frozen generation throughout. Every derived output
path must be rooted under the candidate/run root and checked before heavy work.

## Classification (b): hardened-path-only behavior

### B1 — Legacy operational corpus rejected

**True positive.**

Hardened code rejects master's `promotion_corpus_v0.1` as legacy/research
operational input. Regenerating a branch-native v0.2 manifest from the same
hash-frozen folders succeeded and preserved identical parquet bytes and lock
selection. This is useful integrity hardening, but a pre-lock merge needs an
explicit v0.1-to-v0.2 staging migration.

### B2 — 240-character generation-path ceiling

**Over-strict for this workstation layout.**

The first hardened promotion attempt rejected its generation path at 240
characters. The same code and inputs passed that guard from the short detached
worktree `C:\Users\Michael\Documents\Codex\h-r1` and then replayed the corpus.
The guard is protective, but it currently converts an avoidable Windows layout
choice into a hard block. Verify the exact production path budget or shorten
the generated names before merging.

### B3 — Unreceipted physical-ratchet input

**True positive integrity finding with an over-strict failure mode.**

The mirror's `physical_feature_family_ratchet.json` is status `BLOCK`,
`physical_feature_family_ratchet_v0.1`, SHA-256
`13a436aa0ea21cde95078c222517b3dc1c6674a71833ec52b6fadb23037b96ef`,
and contains neither inventory nor ablation receipts. Hardened correctly
refuses to treat it as current operational evidence.

However, the reader passes a loaded payload without the missing paired receipt
and raises:

`ValueError: loaded inventory payload and receipt must be supplied together`

from `physical_feature_family_ratchet.build_ratchet()`. Promotion exits as an
unhandled error instead of returning a structured unauthorized/BLOCK result
that the first-release shadow bootstrap can evaluate. Migrate/regenerate the
receipted inputs and make the reader fail closed without crashing before any
pre-lock merge.

### B4 — Promotion authorization and bootstrap route separation

**True positive; traced, not reached as a release in this run.**

The hardened path treats the current non-authorizing promotion allowlist as
incapable of authorizing promotion, demotes recommendations to shadow, and
allows only the exact inactive bootstrap contract. Its duplicate-route,
non-authorizing-evidence, schema, finite-number, and path-ancestry checks are
appropriate integrity protections. They were not the terminal block in this
rehearsal, so they do not offset B2/B3's migration requirements.

## Classification (c): cosmetic or deferred

- The handoff's “dry-run/research mode” wording does not match executable
  semantics. Document a supported rehearsal mode or a canonical scratch
  wrapper; do not make operators infer production-mode-with-isolated-paths.
- Master also encountered ordinary Windows `WinError 206` failures with long
  candidate/family paths. Short worktrees removed them. Standardize a short
  rehearsal root.
- Several initially considered market days were excluded before the frozen
  fixture because of oversized replay files, duplicate pinned records, or
  absent pooled features. They were not silently repaired or used.
- The reduced bootstrap iteration count was a runtime-only rehearsal
  relaxation. A production-scale SLA remains unmeasured.

## NOT-REHEARSED host-bound gates

The following remain explicit production-host checklist items:

- the real Toronto 14-day streak and the fresh source-staging decision;
- settled-day freshness and finalization;
- daily learning;
- experiment-queue processing;
- shadow A/B monitoring;
- the production-readiness software gate;
- Windows Task Scheduler registration, delegated-child identity, and live
  scheduled fire;
- production memory, disk, growth-rate, and capture-resource admission;
- capture-supervisor quiescence, PID agreement, restoration, and heartbeat
  freshness;
- production long-job lock ownership and timeout/SLA behavior;
- production repository cleanliness, Git/LFS identity, and exact deployed
  commit;
- exact production staged trio, release-store, and active-pointer state;
- release-bound captured-input replay/serve parity;
- active serving-route and worker readiness;
- market-boundary/quiescence proof;
- reviewed promotion authorization;
- the real inactive release write, pointer review/write, worker restart, and
  post-restart verification.

## Mission 2

**Not reached.**

Primary-mission blocker isolation consumed the available capacity and never
produced a gate-valid release candidate. No fresh pooled H2 artifact, training
receipt, parity proof, replay-identity proof, or future-panel preregistration
was created. No opened-window outcome evaluation was performed.

## Production-host action order

1. Preserve/inspect the 12 modified mirror paths before cleanup; three were
   newly created, and nine have no captured preimage in this report.
2. Fix A1-A4 and add one end-to-end test that stages from current ledger rows
   through pooled training without shims.
3. Replace the hardcoded source with an A5 receipt binding the exact Toronto
   streak to a fresh F-family staged trio.
4. Fix A6 by making the entire promotion/qualification tree consume one frozen
   generation and one output root; prove a read-only-mirror rehearsal.
5. Re-run master first with production-scale bootstrap iterations and all
   selected mirror paths write-protected at the OS level.
6. For hardening, regenerate v0.2/receipted operational inputs, fix the B3
   exception, and verify the exact production path budget.
7. Only then repeat the two-identity comparison and decide pre-lock versus
   post-lock hardening integration.

Until those steps pass, do not build, promote, activate, or serve release #1.
