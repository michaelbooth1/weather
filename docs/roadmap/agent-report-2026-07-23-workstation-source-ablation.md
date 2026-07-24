# Agent Report - 2026-07-23 Workstation Source Ablation

## Outcome

**Preserve METAR continuity; do not remove or reweight any source from this
result.** The sealed replay and hardened synthesis evaluated 22 single-source
or joint-family removals over one pinned 309-market-day corpus. Removing METAR
was the only treatment that cleared both proper-score intervals and the
predeclared Holm families on the strict fleet panel. METAR/Denver was the only
city result that cleared the separate 210-test-per-score family. No source was
supported as harmful.

Positive deltas below mean that removing the source made the replay worse.

| Scope | Dates / market-days | Brier delta (95% CI; Holm p) | Log-loss delta (95% CI; Holm p) | Disposition |
| --- | ---: | ---: | ---: | --- |
| exact 12-market daily-summary fleet panel, METAR removed | 12 / 144 | `+0.02376045` [`+0.01802365`, `+0.02852212`]; `0.00537109` | `+0.09099478` [`+0.06892451`, `+0.11065121`]; `0.00537109` | source helps both scores |
| configured daily-summary Denver panel, METAR removed | 14 / 14 | `+0.02196783` [`+0.01483871`, `+0.02886700`]; `0.02563477` | `+0.09764770` [`+0.07258913`, `+0.12202342`]; `0.02563477` | source helps both scores |

The result is research-only and binds a 12-model `RESEARCH_UNBOUND` bundle,
not an active release. It does not change Weather Underground's role as the
configured settlement proxy, authorize a collector or station change, prove
market edge, or permit serving, promotion, release, or trading action.

The sealed result uses research schema `source_family_ablation_v0.2`. It cannot
satisfy the current operational `source_family_ablation_v0.3`, inventory v0.2,
or physical-ratchet v0.2 contracts; those require a separately regenerated,
active-release-bound chain in an authorized writable environment.

Subsequent operational hardening preserves that boundary. Operational v0.3
evidence is accepted only through the canonical active-release manifest and
its current-byte-verified artifact chain. Detached candidate artifacts are
rejected before deserialization, and legacy or research artifacts, including
this v0.2 `RESEARCH_UNBOUND` bundle, cannot authorize serving, promotion, or
release action. The hardening did not regenerate a runtime artifact and does
not upgrade this sealed research result into operational evidence.

## Design and inference contract

The replay used the Phase 0 sealed legacy-v0.1 corpus with execution-time
corpus hash
`d7cfdc58e31ecffab1e4e7f0ef19c4773dbf7c16e8eaeffbf19589e22fc0893f`:
309 market-days, 44,178 snapshots, 12 configured markets, and 32 fleet dates.
It scored 6,550,533 band rows. Reconstructed snapshots were excluded.

The 17 tune dates and 15 holdout dates were sealed before replay. The primary
holdout scope requires configured WU daily-summary settlement and an exact
12-market fleet panel. Eleven of the 22 variants have at least one supported
strict-panel test. The strict multiplicity family contains all 11 supported
variant sign tests per score. The city family contains 210 supported
variant-market sign tests per score. Bootstrap intervals resample whole fleet
dates; a positive action requires both score intervals to exclude zero in the
same direction and both Holm-adjusted sign-test p-values to be at most 0.05.

Treatments are terminal removals from captured replay inputs after the recorded
fallback/cache state. They are not simulations of a transient provider outage.
Group variants are joint interventions and are not additive source
coefficients. Structural absence is unsupported coverage, not a zero effect.
An exact zero for a supported treatment can mean the captured source was not
consumed by that bundle; it does not establish that the source is universally
useless.

This synthesis is explicitly non-outcome-blind because earlier incomplete
forensic batches had already opened outcomes. Holm controls the stated
within-analysis families but cannot restore blinding or correct multiplicity
across the entire workstation program.

## Holdout results

METAR is the only strict fleet action. All 12 strict fleet-date Brier and
log-loss signs are positive. Across the broader configured daily-summary scope,
all 14 dates are also positive. Every one of the 12 markets has a positive
holdout point estimate on both scores, but only Denver clears the 210-test Holm
family. That supports fleet continuity and a fresh fleet-level follow-up; it
does not support a Denver-only configuration.

No source removal clears the harmful-source rule. The strongest near miss is
the joint `all_forecasts` removal: Brier `+0.00333575` and log loss
`+0.02041996`, with positive intervals but Holm-adjusted `p=0.06347656` on both
scores. `open_meteo_family` and individual `open_meteo` effects are favorable
to retaining the source family at the point estimate, but do not clear both
Holm criteria. They are not actions. WU history has only one supported strict
date, and the eleven unsupported strict variants cannot be ranked as no-effect
treatments.

The supported conclusion is therefore narrow:

1. preserve the existing METAR path and monitor its continuity;
2. do not remove, add, reweight, or city-route any source from this panel;
3. repeat only a preregistered METAR-consumption audit after a fresh pooled,
   H2-compliant artifact exists.

## Post-hoc stability audit

The following checks were performed after the sealed result and are
exploratory. They cannot upgrade the preregistered action.

- The 12 strict dates occupy only three Monday-anchored calendar-week blocks.
  Their mean Brier/log-loss deltas are positive in all three blocks:
  `+0.00585059/+0.02155917`, `+0.02576316/+0.10541741`, and
  `+0.02971130/+0.10407865`. If those three weeks, rather than individual
  dates, were treated as independent sign units, the two-sided exact sign-test
  p-value would be `0.25`. A separate contiguous-run grouping produces four
  positive fleet runs and an illustrative p-value of `0.125`. Neither grouping
  was preregistered; both show that formal strength depends on the
  daily-independence approximation.
- On the same strict scope, the nine-date tune METAR effect is much smaller
  than holdout: Brier `+0.00035721` and log loss `+0.00122067` on tune versus
  `+0.02376045` and `+0.09099478` on holdout, a `66.52x` and `74.54x` magnitude
  jump. Tune log loss has eight positive and one negative sign. The direction
  persists, but the scale shift argues for fresh temporal confirmation.
- The all-corpus, band-row-weighted slice audit is concentrated late in the
  day: METAR-removal Brier delta is `+0.01966585` in the late regime versus
  `+0.00681068` early and `+0.00552041` midday. This is descriptive and
  unadjusted, but it makes late-cutoff consumption the most useful monitoring
  target.
- Denver's city action relies on 14/14 positive signs. Removing one non-tie
  makes the raw two-sided sign p-value `0.00024414` and the 210-test Holm value
  `0.05126953`. This fragility check reinforces that Denver is not an
  independently robust city policy.

## Sealed publication and independent verification

The source generation contains exactly `source_family_ablation.json`,
`source_family_ablation.md`, and `COMPLETE.json`. Its start and completion
execution identities are identical at
`4d2d766f907a88cb1060c62c85defc6fceaafb5c48a48671df3a80dff6b919fe`.
The synthesis generation also contains exactly its JSON, Markdown, and commit
marker; its identical start/completion identity is
`6a36093879ff4c241fc123e15c8b09fbde5c4e1353004101e0226b0750186418`.
Both markers say `research_only=true` and
`serving_or_release_authorization=false`.

The final independent verifier replaces an earlier ad-hoc `6,224`-leaf count
whose traversal rule was not preserved. It recomputed all three sealed
inference arrays from `day_effects`, `market_days`, and `split_dates`: 66 paired
rows, 264 robustness rows, and 630 market rows. All 960 rows matched exactly
across 43,404 primitive leaves, including 35,862 numeric and 14,688
floating-point leaves; the maximum floating-point difference was `0.0`.

A separate pooled audit checked exactly 220 fields: 22 variants times the 10
declared support, Brier, log-loss, and helped/hurt-day fields. Its maximum
difference was `3.189115638235762e-14`. The exact focused synthesis collection
also passed all 26 parametrized cases (`26 passed in 0.56s`).

The verifier attempted all 967 source-generation bindings (952 paths and 15
trees). Of those, 966 still match; only the captured `weather_source_tree`
shows expected post-seal drift from the safety-development changes documented
below. The same single tree explains the synthesis-generation drift. The
publication-time start/completion identities remain identical, every terminal
seal still matches, and both generation directories still contain exactly
their two outputs plus `COMPLETE.json`.

The scratch-only v0.2 verification receipt is
`scratch/workstation-research-output/workstream_b/source_ablation/final_sealed_source_verification_receipt_v0.2.json`
(`748,615` bytes; SHA-256
`1c492a34cd215f63d66293cba9cec76a571644853cb0b6a3c390907c01b26d55`;
status `PASS_WITH_LEGACY_COUNT_REPLACEMENT_AND_POST_SEAL_DRIFT`). Its base
verifier SHA-256 is
`cdf945ebc79c157d6e963ee31ff5aa249bc233c7ed4fed8c75ebe02e56337a8b`;
the Windows short-path finalizer SHA-256 is
`4839ec65a2b6c2fcef694cd6d8369006505f9c4500722eb877d61f368f8bd864`.
The first receipt is retained as chronology: its inference checks passed, but
its deeply nested pytest temporary path hit Windows `MAX_PATH`; v0.2 reran the
same 26-test collection under a short system-temporary path outside `data/`.

| Artifact | Bytes | SHA-256 |
| --- | ---: | --- |
| source generation `COMPLETE.json` | `4,343` | `10bc52cc46b7f167aa2e85aacb11f0071fbd08c550ba65bbb5bc45f5714c313d` |
| source result JSON | `9,819,173` | `829dd50e0385659b41ec25b6540b0edf8258ae2074f3d0ce9f9d9988160331ae` |
| source result Markdown | `61,818` | `0429fa64b362378ceee7f11fd021e9b7f6c897e49c217815ab07083bb79f45b9` |
| synthesis `COMPLETE.json` | `3,575` | `1135cef8ca6bc56c1a86944f201dabd73ceccd11ac480be6d628eac1739da33c` |
| synthesis JSON | `1,315,975` | `fd9627232748bd00f536c17b2cd5dfc36a4434e7f6bc2178d5bed985e92d715f` |
| synthesis Markdown | `9,353` | `c282e8252bb1b3dc9a988f5f1552db7e036303c6ebe7d038a715923ed58ab503` |

The ignored local generations live below
`scratch/workstation-research-output/workstream_b/source_ablation/`. They are
durable evidence on this workstation but are not assumed to exist in a clean
checkout.

## Failure and correction chronology

The first producer attempt failed closed before publication. Runtime support
was 19,654 rather than the sealed 19,653 snapshots for `wu_history/tune`, and
2,263 rather than 2,262 for `eccc_swob/tune`. The common record was Toronto
2026-06-15 snapshot `20260615T104352-0400`: its post-model wrapper was nonempty
but explicitly had `target_date_match=false`. No generation-001 directory,
`COMPLETE.json`, temporary leaf, result, or surviving process existed.

The outcome-blind correction makes an explicit false target-date match
unusable support. It read no settlement or score outcome and changed no
treatment or inferential result. The sealed correction then matched all 44
variant/split runtime-support pairs with zero mismatches. Its SHA-256 is
`105429a593c149dc9d59518e1623368c6c34ba7a125042f5f4f61ee770956fad`;
the corrected helper SHA-256 is
`089b0ac356e7a15f849e6f6227e06406669ae59a00edabcf9c125c8f12946489`.

Two synthesis validation defects were found before publication. One compared a
repository-relative captured path with an absolute terminal receipt without
normalizing both under the captured root grammar. The other let sorted JSON
object-key order change the order of tune/holdout inference arrays. Both fixes
remain strict: path escape, mtime, size, and hash checks still fail closed, and
inference arrays are not sorted or otherwise normalized. The actual source
artifact then recomputed exactly, and all 26 focused synthesis tests passed.

For complete run history, one invocation targeted the hardened implementation
module directly. That module intentionally has no executable `__main__`; it
exited without output, target, process, publication, or additional outcome
exposure. The dispatcher module subsequently published synthesis generation-002
once.

## Isolation and provenance

- Isolated worktree: `scratch/worktrees/weather-workstation-research-2026-07-22`
- Branch: `codex/workstation-research-2026-07-22`
- Base: `99c0616419ce75a402e5b752fc87b4f9bebec54c`
- Input: repository-local ignored `data/` mirror, treated as read only
- Output: `scratch/workstation-research-output`
- Staged corpus file SHA-256:
  `4cafcf1aa827bbf0b2b4c85af898192a50637c49d0b270c5006ef56f3cacd1f5`
- Preregistration SHA-256:
  `a98a1be7383b7bac200e0baea6f680ad5505a5bfc1054b2bc14fc192973e176f`
- Support seal SHA-256:
  `55af741c35a6b4fcaa1df89cfcdcb479bb84603f91dfefae4b42a53e49470cf7`
- Feasibility seal SHA-256:
  `09b8d7c20930d9a37dd0310c41071c4344d274bae11bf7d688a486f38af4d148`

The nightly mirror refreshed before source replay. The source run used a
staged, content-addressed corpus manifest outside `data/`, while reading the
manifest-bound, hash-verified snapshot and WU inputs from the read-only
`data/` mirror. No file was created, changed, or deleted under `data/` by this
source-ablation experiment; that no-mutation statement is scoped to this
experiment. No production host, scheduler, release pointer, serving
configuration, promotion path, or live/paper order surface was touched.

## Disposition

1. Preserve the current METAR collection and fallback path. Add continuity and
   feature-consumption monitoring, especially for late cutoffs.
2. Do not change source weights, city routing, provider configuration, or the
   WU settlement contract from this report.
3. Train a fresh pooled artifact through the corrected H2 path with a complete
   execution receipt, then run one narrow, preregistered METAR ablation on new
   dates. The current result cannot certify that new artifact in advance.
4. Stop same-panel provider mining. `all_forecasts`, Open-Meteo family, and all
   unsupported/no-op variants require new evidence rather than more thresholds
   on these outcomes.
