# Agent Report - 2026-07-22 Workstation Ordinal Smoothing

## Outcome

**The sealed physical-bandwidth tune replay selected `0.75 C` for Toronto and
`1.25 C = 2.25 F` for the F family. F is supported against its fresh tune W0;
Toronto is directional only. Neither result establishes market edge, and
neither has fresh confirmation.** The separately preregistered July 15-19
one-shot attempt durably consumed its authorization. Non-durable,
contemporaneous terminal output indicated that both arms ran before an identity
gate failed; the apparent same-identity W0-fidelity misclassification is an
operator-session diagnosis, not a committed artifact fact. That five-date
panel is now exposed and must not be retried or described as fresh evidence.

The earlier native-unit experiment remains useful, permanently opened
historical evidence. Its tune-only rule selected weight `1.0` for both
native-unit families at the edge of the tested grid, with sigma fixed at `0.75`
native units:

| Unit family | Holdout dates | Brier delta vs W0 (95% fleet-date CI) | Log-loss delta vs W0 (95% fleet-date CI) | Brier date signs +/-/= | Disposition | Candidate Brier / log-loss gap vs market |
| --- | ---: | ---: | ---: | ---: | --- | ---: |
| F (11 markets) | 15 | `-0.00247123` [`-0.00361674`, `-0.00153635`] | `-0.00867169` [`-0.01196456`, `-0.00581818`] | `15/0/0` | **SUPPORTED vs W0** | `+0.02819555` / `+0.10907112` |
| C (Toronto) | 14 | `-0.00270064` [`-0.00985827`, `+0.00334033`] | `-0.00495087` [`-0.03252573`, `+0.01871061`] | `8/6/0` | **DIRECTIONAL_ONLY** | `+0.02239077` / `+0.10058806` |

Negative candidate-minus-W0 deltas favor smoothing. Positive
candidate-minus-market gaps mean the candidate is worse than market prices.
In that earlier opened holdout, the F result improved over its W0 but remained
materially behind the market; the C interval was too wide to claim support.

This report does **not** authorize re-enabling smoothing, artifact export,
promotion, a serving-pointer change, or trading. The original H1 holdout is
opened and permanently sealed: it must never be used for a larger grid,
reselection, or a second confirmation. The consumed July 15-19 attempt likewise
authorizes no rerun.

## Initial native-unit experiment

The sole swept variable was the serve-stage ordinal blend weight:

- weights: `0`, `0.10`, `0.25`, `0.50`, `0.75`, `1.0`;
- fixed sigma: `0.75` in each market's native settlement unit;
- smoothing scope: whenever feature-model probabilities existed, matching the
  historical serve-stage transform being investigated;
- selection rule, fixed before holdout: require negative tune mean paired
  Brier and log-loss deltas, then rank by Brier, log loss, and smaller weight;
- primary aggregation: score band rows within each native-unit fleet date,
  then weight fleet dates equally;
- uncertainty: deterministic 10,000-replicate paired cluster bootstrap over
  fleet dates, plus paired date signs.

The incumbent is weight `0`, not the historical hard-coded weight `0.5`.
Roadmap item 178 removed that unvalidated serve-only smoother and current
artifacts either explicitly disable it or omit the config, which defaults to
disabled. This experiment therefore tests whether a smoother is worth
reintroducing under a controlled replay; it is not a comparison against a
currently served `0.5` policy.

### Native-unit sigma is not a common physical bandwidth

The ordinal kernel uses raw numeric bucket-key distance. Consequently H1's
numeric sigma `0.75` means `0.75 C` for Toronto but `0.75 F = 0.4167 C` for the
11 F markets. Adjacent-bucket kernel weights are numerically the same, while
the physical bandwidth differs by `1.8x`.

The result is valid as an equal-native-bucket treatment. It is **not** evidence
for a shared physical smoothing width. This motivated the preregistered
physical-C grid with `sigma_F = 1.8 * sigma_C` reported below; one shared
numeric native-unit sigma must not be described as physically comparable.

## Date firewall

Tune dates were declared before replay:

`2026-06-03, 06-04, 06-05, 06-07, 06-08, 06-09, 06-10, 06-11, 06-12,
06-13, 06-14, 06-15, 06-16, 06-17, 06-19, 06-20, 06-21`.

The holdout remained unopened until both families' selected weights were fixed:

`2026-06-22, 06-26, 06-27, 06-28, 06-29, 06-30, 07-01, 07-02, 07-03,
07-04, 07-05, 07-07, 07-08, 07-09, 07-10`.

The manifest has only Denver on June 27 and nine markets on July 4. The primary
result intentionally honors the preregistered all-pinned corpus; exact-panel
and settlement-source restrictions are reported separately as post-hoc
sensitivity checks and cannot change the selection or disposition.

## Initial tune-only sweep

| Unit | Weight | Dates | Brier delta vs W0 (95% CI) | Log-loss delta vs W0 (95% CI) | Candidate Brier / log-loss gap vs market |
| --- | ---: | ---: | ---: | ---: | ---: |
| C | 0.10 | 15 | `-0.00044893` [`-0.00082070`, `-0.00009039`] | `-0.00187639` [`-0.00341301`, `-0.00044593`] | `+0.00746370` / `+0.02917841` |
| C | 0.25 | 15 | `-0.00100339` [`-0.00190135`, `-0.00013044`] | `-0.00375115` [`-0.00706548`, `-0.00056790`] | `+0.00690924` / `+0.02730365` |
| C | 0.50 | 15 | `-0.00168850` [`-0.00340982`, `-0.00000560`] | `-0.00564816` [`-0.01149879`, `-0.00015755`] | `+0.00622413` / `+0.02540665` |
| C | 0.75 | 15 | `-0.00211140` [`-0.00470513`, `+0.00035906`] | `-0.00657549` [`-0.01469650`, `+0.00097997`] | `+0.00580124` / `+0.02447932` |
| C | 1.00 | 15 | `-0.00227612` [`-0.00578860`, `+0.00105210`] | `-0.00673531` [`-0.01725390`, `+0.00296256`] | `+0.00563651` / `+0.02431950` |
| F | 0.10 | 14 | `-0.00059216` [`-0.00084032`, `-0.00039584`] | `-0.00222566` [`-0.00320603`, `-0.00152160`] | `+0.00993236` / `+0.03588681` |
| F | 0.25 | 14 | `-0.00124075` [`-0.00180068`, `-0.00085837`] | `-0.00464203` [`-0.00680611`, `-0.00318807`] | `+0.00928377` / `+0.03347044` |
| F | 0.50 | 14 | `-0.00207841` [`-0.00314392`, `-0.00137803`] | `-0.00758528` [`-0.01127878`, `-0.00513456`] | `+0.00844611` / `+0.03052719` |
| F | 0.75 | 14 | `-0.00274294` [`-0.00427974`, `-0.00171717`] | `-0.00975050` [`-0.01477840`, `-0.00645282`] | `+0.00778158` / `+0.02836197` |
| F | 1.00 | 14 | `-0.00327494` [`-0.00529939`, `-0.00189889`] | `-0.01137247` [`-0.01756998`, `-0.00728648`] | `+0.00724958` / `+0.02674000` |

Every positive weight improved both tune means. Both families selected `1.0`,
the grid ceiling, so H1 does not locate an interior optimum. That ceiling result
and the unequal physical bandwidth are reasons for a new tune-only experiment,
not permission to extend the opened holdout grid.

## Physically comparable refinement preflight

Before any additional scores were opened, the follow-up was preregistered as a
one-variable, tune-only experiment at fixed blend weight `1.0`:

- physical-C sigma anchors: `0.25, 0.50, 0.75, 1.00, 1.25`;
- native mapping: `sigma_C = x`, `sigma_F = 1.8 * x`;
- eligibility: negative mean paired Brier and log-loss deltas versus W0;
- ranking: Brier delta, then log-loss delta, then smaller physical-C sigma;
- selection is family-specific, but both families use the same physical grid.

An outcome-row-blind cache-transform audit then tested whether the five arms
could be derived safely from the existing final W0 distributions. It **blocked**:
applying the exact production ordinal smoother to final W0 failed to reproduce
the existing final W1 distribution for all `19,820/19,820` tune distributions
and `444,441` probability cells at tolerance `1e-12`. Overall mean/max L1 were
`0.43245262` / `1.25147632`; maximum cell error was `0.62573816`. By family:

| Unit | Distributions | Outside tolerance | Mean / max L1 | Maximum cell error |
| --- | ---: | ---: | ---: | ---: |
| C | `2,298` | `2,298` | `0.39650093` / `0.91829036` | `0.45914518` |
| F | `17,522` | `17,522` | `0.43716766` / `1.25147632` | `0.62573816` |

The failure is structural, not numerical noise. In production replay the
smoother acts on the feature-model distribution before feature blending and
later live/floor/tail/cap transforms. Smoothing the already-final W0 output
therefore does not commute with the real pipeline and cannot create admissible
candidate caches. No outcome row, old holdout row, or fresh-panel score was
read by this audit. A cold replay is required.

## Sealed generation-001 physical tune replay

The required cold replay completed as
`physical-replay-gen2-generation-001`. It used only the sealed June 3-21 tune
corpus: a fresh W0, an independent W0 canary, and five cold physical-bandwidth
candidate arms. It accepted no old H1 result or cache, old holdout, fresh panel,
active release, serving pointer, or promotion path. Start and completion
execution-identity digests are exactly equal:
`009695dd3540d0d67f9d7d2af1ab10ba868427ca7a691fa3153b17caa2a63df4`.

The frozen family selections are:

| Unit | Physical-C sigma | Native sigma | Tune dates | Brier delta vs fresh W0 (95% CI) | Log-loss delta vs fresh W0 (95% CI) | Candidate Brier / log-loss gap vs market | Tune disposition |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| C | `0.75` | `0.75 C` | 15 | `-0.00227612` [`-0.00566133`, `+0.00102089`] | `-0.00673531` [`-0.01694642`, `+0.00295567`] | `+0.00563651` / `+0.02431950` | **DIRECTIONAL_ONLY** |
| F | `1.25` | `2.25 F` | 14 | `-0.00465892` [`-0.00865634`, `-0.00184382`] | `-0.01531136` [`-0.02659335`, `-0.00760403`] | `+0.00586560` / `+0.02280111` | **SUPPORTED vs W0** |

Negative candidate-minus-W0 means favor smoothing; positive
candidate-minus-market gaps mean both selected candidates remain worse than
captured market prices. Selection required negative mean Brier and log loss
and ranked Brier, then log loss, then smaller physical bandwidth. The C
selection is interior to the declared grid; the F selection remains at its
upper edge. These are tune results under `RESEARCH_UNBOUND`, not serving,
promotion, or fresh-confirmation evidence.

## Post-hoc robustness (selection frozen)

The robustness command streamed the two sealed 2.98 GB holdout caches and
recomputed the primary metrics before applying any restriction. Primary parity
passed at tolerance `1e-12` (maximum absolute difference `8.05e-15` for C and
`2.26e-14` for F).

| Scope | Unit | Dates | Brier delta vs W0 (95% CI) | Log-loss delta vs W0 (95% CI) | Candidate Brier / log-loss gap vs market |
| --- | --- | ---: | ---: | ---: | ---: |
| daily-summary settlement only | C | 13 | `-0.00281829` [`-0.01050728`, `+0.00371273`] | `-0.00517159` [`-0.03493038`, `+0.02023610`] | `+0.02362779` / `+0.10671603` |
| daily-summary settlement only | F | 14 | `-0.00251943` [`-0.00373859`, `-0.00153692`] | `-0.00894098` [`-0.01243670`, `-0.00594007`] | `+0.02985835` / `+0.11525473` |
| exact 12-market dates | C | 13 | `-0.00279564` [`-0.01032170`, `+0.00370548`] | `-0.00554721` [`-0.03440822`, `+0.01960270`] | `+0.02141676` / `+0.10024135` |
| exact 12-market dates | F | 13 | `-0.00275635` [`-0.00398049`, `-0.00174984`] | `-0.00936639` [`-0.01277398`, `-0.00634715`] | `+0.02860499` / `+0.09957641` |
| daily summary + exact 12 markets | C | 12 | `-0.00293102` [`-0.01096477`, `+0.00404362`] | `-0.00583602` [`-0.03766825`, `+0.02138411`] | `+0.02267570` / `+0.10685109` |
| daily summary + exact 12 markets | F | 12 | `-0.00283634` [`-0.00415868`, `-0.00173974`] | `-0.00973845` [`-0.01341073`, `-0.00653875`] | `+0.03057903` / `+0.10599940` |

F remains supported in all three fixed sensitivities. C remains directional
with intervals crossing zero. Leave-one-fleet-date-out results reinforce the
distinction: F stays negative on both metrics after all `15/15` omissions;
C stays negative on both after `12/14`, and its log-loss range crosses zero
(`-0.00911` to `+0.00420`).

Post-hoc per-market intervals support Chicago, Dallas, NYC, and San Francisco;
the other seven F markets and Toronto are directional only. This heterogeneity
does not override the preregistered F-family result, and every per-market
candidate remains worse than market on mean Brier.

The only `snapshot_high` complete panel is June 26. It moves both families in
the favorable direction but is one date and explicitly descriptive, not
confirmatory.

## Replay, mass, alignment, and effect gates

- W0 determinism canary: full 12-market June 21 fleet date, `2,073`
  distributions and `22,814` score rows; zero row or distribution mismatches.
  Baseline/control row hashes are both
  `fb69349efe568c6291ec7c6e288943e52e5259e8f0586b67f7fc01ce7902c28b`;
  distribution hashes are both
  `7894d20c7d7635e1fa710af8352e637ed1f6df5e801a263124f1c667de77d653`.
- Holdout W0 and W1 each replayed all `24,358/24,358` pinned snapshots and
  `268,059` band rows with zero corpus warnings.
- Both holdout caches have `268,059` raw and unique scoring rows, zero duplicate
  extras/conflicts, and exact candidate alignment: zero missing, extra, or
  label-mismatched rows.
- Maximum holdout simplex error was `6.66e-16` for W0 and `5.55e-16` for W1;
  there were zero mass violations.
- W1 changed all `24,358` distributions. Mean L1 by local-hour window was
  `0.34024` at 00-06 (`6,940` snapshots), `0.34717` at 07-20 (`14,632`), and
  `0.41433` at 21-23 (`2,786`). This is an effect audit, not an hour-scope gate:
  the effective printed cutoff can already select the feature path predawn.

The first analysis attempt correctly blocked before touching holdout because
Atlanta June 16 and Toronto June 19 contained 22 equivalent duplicate score
keys, while JSON NaNs made the W0 canary appear unequal under ordinary Python
equality. The repair is fail-closed: keep the first duplicate only when
`replayed_p`, outcome, market price, and unit are canonically NaN-safe equal;
conflicting duplicates block. The canary now compares canonical JSON hashes.
Focused regression tests cover equivalent and conflicting collisions and
independent NaNs.

General replay calls now default to omitting multi-gigabyte distribution rows;
the H1 research command opts in explicitly. This prevents unrelated callers
from retaining the full distribution corpus in memory.

## Immutable artifacts

| Artifact | Bytes | SHA-256 |
| --- | ---: | --- |
| repaired H1 result | `168,013` | `0ba6c2567a805615d5488cb062182546ce2729392335852967c89e13fd897ab8` |
| repaired H1 Markdown | `5,210` | `3fb1b7fdf62e4719ca45b8d46b10eb17084643bfff5e493cc856a1ee639e73c2` |
| holdout W0 cache | `2,977,552,689` | `949238000b590060cc43eef96c53ee4cb6dc71406ca06230e0f976203d0a184b` |
| holdout W1 cache | `2,977,519,713` | `7bbf965db8dcfe0c25028fafbd8a0ba6e39369d07f74298f3bfd474e9ff88e1e` |
| post-hoc robustness JSON | `275,667` | `b9f80157a91ff5d11c32c6b975391617ca8c89ff02405ba54432de2cae991023` |
| post-hoc robustness Markdown | `7,423` | `9c893d1534505213005ab79a1a62d2d1911572ca24b268a5b62164a3cb9e2f54` |
| physical cache-transform audit JSON | `13,732` | `fa5463c593930b199759ad243352425513eea6e5e00fc3d61d094842c924903c` |
| physical cache-transform audit Markdown | `2,866` | `49f2ee02de7d8c0fc3f7b1da38e26563006455aa080a666463e1ae59b9aeccf9` |
| gen2 generation commit (`COMPLETE.json`) | `4,325` | `0eb3dc7990c04a16efa76779c9fcc7ba1c75e107677fb67fb78184ed5f484e2a` |
| gen2 result | `98,786,664` | `890fa4218ed6f4075fa62777ec3a489d60b4e1bbb676eb97e49baa5a2d28a81d` |
| gen2 Markdown | `2,331` | `6cdd0a00d4681eec135a15885c42a818dfbcc033a262025b8bdbb8984b9a65b3` |
| consumed confirmation attempt marker | `1,451` | `5adc6326b5d0fa84c0d8a72f033ccc4a4bc1ec52096aae623495aedf20372f5e` |

Cache metadata:

- W0 fingerprint
  `5f19f0dddddd2751be891746937ce84517eeb3009f3d32b8e63c8aecaded62c7`;
- W1 fingerprint
  `645359d025db9646fc30d8b9d02a6e8d1790c1e2df3417926486ac014bde7deb`;
- both schema `ordinal_smoothing_sweep_v0.1`, split `holdout`, sigma `0.75`;
- the result status is `COMPLETE`, tune and holdout are `PASS`, technical
  blockers are empty, the process exited `0`, the lock is gone, and no temporary
  file remains.

The earlier blocked diagnostic remains separate evidence; it was not
overwritten. Its SHA-256 is
`561e56708ccff0f7b6f8e53ff24b3ecf9501e3d4c271509fcaff00083c82bed8`.

## Mirror provenance and isolation

- Isolated scratch worktree:
  `scratch/worktrees/weather-workstation-research-2026-07-22`
- Branch: `codex/workstation-research-2026-07-22`
- Base: `99c0616419ce75a402e5b752fc87b4f9bebec54c`
- Input root: the repository-local, ignored `data/` mirror (read only); its
  exact resolved runtime root remains bound in the machine evidence
- Output root: `scratch/workstation-research-output`
- Pinned manifest file SHA-256:
  `4CAFCF1AA827BBF0B2B4C85AF898192A50637C49D0B270C5006EF56F3CACD1F5`
- Canonical corpus hash:
  `d7cfdc58e31ecffab1e4e7f0ef19c4773dbf7c16e8eaeffbf19589e22fc0893f`
- Corpus verification: `309/309` entries, zero warnings.

The clone-local mirror and its major subtrees were created July 21 at about
14:07 ET. The newest event folders came from the July 22 mirror pass around
04:32 ET; `data/backtest` had observed content through about 01:00 ET. No copy
receipt binds every subtree to a named upstream sync batch, so the observed
mirror state and content hashes are the strongest honest provenance.

No production host, scheduler, release pointer, serving config, promotion path,
or live/paper order path was touched. All generated experiment outputs are
outside `data/`.

## Fresh-confirmation feasibility

The July 11-20 preflight audit completed as
`NO_COMPLETE_FRESH_CONFIRMATION_PANEL` for the requested ten-day interval. It
did, however, identify a smaller strict panel and a separately labeled
counterfactual panel before any outcome score or candidate replay:

| Tier | Eligible dates | Dates | Meaning |
| --- | --- | ---: | --- |
| **Tier 1: exact recorded-current identity** | July 15-19 | 5 | Exact 12 markets, pins, daily-summary settlement, and full replay identity on every snapshot |
| **Tier 2: counterfactual current-code** | July 14-19 | 6 | Same structural contract plus clean outcome-blind W0 replay; July 14 identity differs only in code hash |

Tier 2 did not relax or upgrade Tier 1. It remains feasibility evidence only.
The later attempted paired experiment used the stricter Tier 1 dates.

### Why the ten-day interval is incomplete

All 120 registered market-date folders exist, with no duplicate market-date
folder, but only 83 are corpus-admissible:

- Seattle July 11 has partial quality, leaving an 11-market date;
- all 12 folders on July 12 and all 12 on July 13 have partial quality and are
  not promotion-countable;
- all 12 July 20 folders lack a settlement label in this mirror;
- July 14-19 are exact 12-market, hash-pinned, daily-summary-settled panels.

The new manifest binds 83 market-days, 13,306 snapshots, and 146,366 band rows.
Every admitted input was immediately rehashed with zero warnings. This audit
used settlement labels only to test existence/source; it never evaluated a band
outcome or calculated Brier/log-loss.

### Identity and outcome-blind W0 gate

July 15-19 contain 11,300 snapshots whose complete recorded identity exactly
matches current code/artifacts. July 14 contributes 660 additional snapshots
whose recorded identity differs only in `code_hash`:

- recorded code hash:
  `593a5f3e0fe80291886698572e4ac4e0a078a0ffeb6e97b223a0e3a657964af0`;
- current code hash:
  `1c975faa3e52a05de27083725f06f3959e27956ce02d31285d9edde8e52c66b3`;
- per-market artifact hashes, model version
  `v0.5.10 HGBC feature-based ML model`, and active path `hgb` are unchanged;
- counterfactual-current W0 versus the recorded distribution has L1 exactly
  `0.0` for all 660 changed-identity snapshots.

The bounded W0 source replay covered all `11,960/11,960` snapshots on July
14-19 in `640.44s`: zero replay failures, missing recorded distributions,
corpus warnings, or simplex failures. Exact-identity fidelity is `11,300`
snapshots with mean/max L1 `0.0`; the changed-identity cohort is `660`, also
mean/max L1 `0.0`. An independent replay of all 1,790 July 14 distributions had
zero hash mismatches.

This made July 14-19 technically replayable under the then-current W0, while
the stricter July 15-19 panel needed no identity exception. Five fleet dates
were a small confirmation, especially for one-market C, so the panel and
decision thresholds were preregistered before the attempted outcome-scored
run.

### Consumed one-shot attempt: blocked, no fresh result

The exact July 15-19 Tier 1 attempt consumed its create-if-absent authorization
at `2026-07-23T02:36:16Z`. The marker binds:

- fresh-corpus file SHA-256
  `b9ea179b2fe6305f33771c2ee6a0dc6336e30ea995a89454fbf257775b5cfeba`;
- gen2 `COMPLETE.json` SHA-256
  `0eb3dc7990c04a16efa76779c9fcc7ba1c75e107677fb67fb78184ed5f484e2a`;
- gen2 result SHA-256
  `890fa4218ed6f4075fa62777ec3a489d60b4e1bbb676eb97e49baa5a2d28a81d`;
- intended generation
  `physical-confirmation-0eb3dc7990c0-b9ea179b2fe6`.

Contemporaneous terminal output, which was not retained as a durable artifact,
indicated that the fresh W0 and the single frozen mixed-family candidate arms
both completed before the run failed with
`candidate gate failed: same-identity replay fidelity canary failed`. The
operator-session interpretation is that the candidate arm deliberately applied
the physical-bandwidth ordinal transformation through a research subclass, but
at attempt time that subclass retained the base replay model version and
identity. `run_partition_arm` therefore appears to have classified the
intentionally changed candidate distributions as same-identity W0 replays and
applied the recorded-distribution equality canary to them. No committed error
or arm artifact independently verifies that sequence or diagnosis; it is not
evidence that the tune generation is corrupt.

The failure committed no confirmation cache, JSON, Markdown, or
`COMPLETE.json`; the intended generation directory does not exist. The
persistent attempt marker is the only durable confirmation-attempt artifact
and intentionally survives failure. It proves authorization consumption and
binds the declared inputs, but contains no arm-completion state, error field, or
fresh score, so no confirmation metric or durable failure sequence is
recoverable or reportable. The contemporaneously observed attempt opened the
five-date outcomes for this candidate; July 15-19 is no longer a fresh panel
and must not be rerun, reconstructed, or retrospectively scored for a
confirmatory claim.

Before any future one-shot design, the transformed research candidate must
carry a distinct research model version/identity so only the true W0 arm is
eligible for recorded same-identity fidelity comparison. Candidate
mass/alignment/effect gates remain mandatory; the W0 fidelity threshold must
not be weakened. All deterministic replay-fidelity preflight must also finish
before authorization is consumed, followed by bound post-consumption checks to
close the time-of-check/time-of-use window. A post-consumption failure receipt
should persist the failing phase, measured value, and threshold without
publishing outcome scores.

### Pre-attempt cost estimate

Before the consumed attempt, observed workstation arm costs implied:

- a shared-native numeric sigma-by-weight expansion over the old tune dates is
  15 new arms with validated cache reuse: about `6.25h` and `31.0 GiB`; cold
  start is 21 arms, about `8.75h` and `43.4 GiB`;
- that two-variable grid is not the recommended design because it compounds
  overfitting and retains unequal physical bandwidth;
- the preferred one-variable, physically declared sigma refinement at fixed
  W1 was estimated to need four new tune arms: about `1.67h` and `8.27 GiB`;
- after tune-only selection was frozen, a two-arm W0/candidate confirmation was
  estimated at `20.78m` and `1.85 GiB` for the strict five dates, or `24.94m`
  and `2.22 GiB` for the six-date Tier-2 panel.

The old H1 holdout, July 15-19 labels, and outcome-blind W0 distributions remain
forbidden selection inputs. The estimate is historical and authorizes no
rerun. Any later experiment requires a genuinely new preregistered panel after
the identity/gating correction, with no reselection after outcomes are opened.

Fresh-audit artifacts:

| Artifact | Bytes | SHA-256 |
| --- | ---: | --- |
| pinned July 11-20 manifest | `3,646,709` | `4ff50585a1b2cbdb7bd1a5f4be633b7b3cecf5bba6a42f4109080d4c98c6d180` |
| feasibility JSON | `166,604` | `8ac5ffb2685f5c50c28ceb39073ed036ad6c2a50d6b77bdb0b929c50f5123dfd` |
| feasibility Markdown | `10,006` | `e3dc55df1a84c418cdb9848da38226d3f9254c35a29efc84a5d87bd14a3f9cea` |

The manifest's canonical corpus hash is
`1117ad38a60ef128f4881dbf6d89db36034a15d93b12fec586af75cfd2f3c288`.
These artifacts cannot alter the already-opened H1 result.

## Reproduction commands

These commands reproduce the earlier completed analyses only. The consumed
one-shot confirmation command is intentionally omitted and must not be run
again. Paths are repository-relative representations of the isolated run.
They require the local ignored `data/` mirror and the existing ignored
`scratch/workstation-research-output/` state; they are not clean-checkout
commands.

```powershell
.\venv\Scripts\python.exe -m weather.reporting.research.ordinal_smoothing_sweep `
  --mirror-data-root data `
  --staged-data-root data `
  --snapshots-root data\snapshots `
  --corpus data\backtest\promotion_corpus.json `
  --tune-dates-file scratch\workstation-research-output\workstream_a\h1\tune_dates.txt `
  --holdout-dates-file scratch\workstation-research-output\workstream_a\h1\holdout_dates.txt `
  --json-out scratch\workstation-research-output\workstream_a\h1\ordinal_smoothing_sweep_repaired.json `
  --report-out scratch\workstation-research-output\workstream_a\h1\ordinal_smoothing_sweep_repaired.md `
  --cache-root scratch\workstation-research-output\workstream_a\h1\cache `
  --lock-path scratch\workstation-research-output\workstream_a\h1\ordinal_smoothing_sweep_repaired.lock `
  --resume

.\venv\Scripts\python.exe -m weather.reporting.research.ordinal_smoothing_robustness `
  --h1-result scratch\workstation-research-output\workstream_a\h1\ordinal_smoothing_sweep_repaired.json `
  --corpus-manifest data\backtest\promotion_corpus.json `
  --baseline-cache scratch\workstation-research-output\workstream_a\h1\cache\holdout-weight-0p00.json `
  --candidate-cache scratch\workstation-research-output\workstream_a\h1\cache\holdout-weight-1p00.json `
  --json-out scratch\workstation-research-output\workstream_a\h1\ordinal_smoothing_robustness.json `
  --report-out scratch\workstation-research-output\workstream_a\h1\ordinal_smoothing_robustness.md

.\venv\Scripts\python.exe -m weather.reporting.research.ordinal_smoothing_fresh_confirmation_audit `
  --snapshots-root data\snapshots `
  --start-date 2026-07-11 --end-date 2026-07-20 --as-of 2026-07-22 `
  --manifest-out scratch\workstation-research-output\workstream_a\h1\fresh_confirmation_manifest_2026-07-11_20.json `
  --json-out scratch\workstation-research-output\workstream_a\h1\fresh_confirmation_audit_2026-07-11_20.json `
  --report-out scratch\workstation-research-output\workstream_a\h1\fresh_confirmation_audit_2026-07-11_20.md `
  --measured-tune-arm-minutes 25.0 --measured-tune-cache-bytes 2219652377 `
  --reference-holdout-dates 15 --measured-holdout-arm-minutes 31.17 `
  --measured-holdout-cache-bytes 2977536201
```

## Disposition

1. Keep current serving at W0. Do not set weight `1.0` in an artifact or serving
   config from this report.
2. Treat the sealed gen2 F tune result as supported against tune W0 but not
   market edge; treat Toronto as directional only. Neither is fresh-confirmed.
3. Permanently retire the June 22-July 10 holdout from all ordinal-smoothing
   selection and confirmation.
4. Permanently retire July 15-19 from fresh ordinal-smoothing confirmation. Its
   one-shot authorization is durably consumed; terminal-observed arm execution
   has no committed result or error artifact, and no retry is authorized.
5. Before a new preregistered panel is opened, give the transformed research
   candidate a distinct version/identity, retain strict W0 fidelity and
   candidate mass/alignment/effect gates, and complete deterministic preflight
   before consuming the one-shot marker.
6. Preserve item 178's governing contract: any smoother must be folded into
   tuning, exported in the artifact, and proven train/serve-identical. A
   serve-stage diagnostic cannot authorize a hard-coded W1 transform.
