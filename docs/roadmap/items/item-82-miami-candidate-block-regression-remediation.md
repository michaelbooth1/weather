# 82. Miami Candidate Block Regression Remediation [COMPLETE 2026-06-16 - CURRENT FALLBACK CLEARS BLOCK]

Goal: clear the Miami F-family `BLOCK_CANDIDATE` regression without weakening
the promotion gate for other markets.

Source: `data/backtest/f_family_promotion_refresh_report.md`, generated
`2026-06-16T02:15:46Z`, now marks Miami as `BLOCK_CANDIDATE`: candidate Brier
`0.0357` versus current `0.0250` and market `0.0238`, with delta versus
current `+0.0107`, above the `0.0030` regression tolerance.

- [x] Attribute the Miami candidate regression by cutoff hour, band type,
  settlement distance, source freshness, and CLOB taxonomy using generated
  replay slices rather than hand-written diagnosis.
- [x] Decide whether Miami needs a per-market fallback, source-freshness cap,
  current-serving blend, or a separate model variant.
- [x] Re-run item 69 multi-variant shadow scoring for the proposed Miami fix
  and prove it improves current replay without increasing aggregate blocker
  risk.
- [x] Update `f_family_promotion_refresh_report.md` so Miami is no longer
  `BLOCK_CANDIDATE`, or keep the generated blocker with a concrete next
  remediation artifact.

Acceptance: Miami candidate replay is no longer worse than current by more than
the promotion tolerance, the market remains explicitly blocked if evidence is
insufficient, and item 48 has no unexplained Miami blocker.

Completion update 2026-06-16:

- Chose the conservative current-serving blend for Miami in the base F-family
  postprocess: `current_blend_market_alpha["miami"] = 0.0`. This matches the
  already-scored dynamic-source variant fallback and changes only serving
  postprocess policy, not model weights.
- Updated the saved `feature_model_hgb_f_pooled_v0_3.pkl` postprocess metadata
  so the canonical promotion replay uses the same Miami fallback as future
  retrains from `default_band_postprocess()`.
- Full Item 82 replay artifact:
  `data/backtest/item82_miami_fallback_candidate_replay_with_clob.json`; report:
  `data/backtest/item82_miami_fallback_candidate_replay_with_clob_report.md`.
  The replay verdict is `PASS_WITH_SHADOWS` / `PER_MARKET_ONLY`.
- Miami is no longer a hard block: candidate Brier is `0.025046`, current Brier
  is `0.025046`, delta versus current is `+0.000000`, and market Brier is
  `0.023776`. Miami remains `SHADOW` because it is not proven better than
  current replay.
- Generated attribution confirmed the fallback does not create a new current
  regression above tolerance. The worst current-regression slices after the fix
  are below the `0.0030` block threshold: cutoff hour 17 is `+0.000649`, band
  type `lte` is `+0.000038`, settlement distance `2` is `+0.000761`, and source
  freshness `failed:metar` is `+0.000930`. The CLOB-taxonomy overlay remains a
  non-serving diagnostic; its generated taxonomy table is preserved in the full
  Item 82 replay report.
- Item 69 rerun:
  `data/backtest/item82_miami_fallback_multi_variant_shadow_report.md` returned
  `OK`, with 67,430 scored rows, 44 market-days, 11 markets, zero errors, and
  zero warnings. Daily-first candidate Brier is `0.042045` versus current
  `0.043496` (`-0.001452`) and market `0.037830` (`+0.004215`).
- Canonical promotion refresh:
  `data/backtest/f_family_promotion_refresh_report.md`, generated
  `2026-06-16T05:44:55Z`, now reports 4 promote, 7 shadow, and 0 blocked F
  markets. Item 48 remains open only for aggregate market skill and remaining
  shadow-market proof.

## Completion Notes

Validated in the 2026-06-24 complete-roadmap sweep:

- `ROADMAP.md` and this item file both mark the item `COMPLETE` with status text `COMPLETE 2026-06-16 - CURRENT FALLBACK CLEARS BLOCK`.
- The file contains 4 checked implementation checklist item(s); no unchecked implementation checklist items remain.
- Validation result: accepted as properly implemented for this completed disposition based on the existing checked implementation evidence; no active roadmap work was reopened for this item.
- Future validation should rerun `python -m weather.reporting.roadmap_backlog --fail-on-lint` and the referenced modules, generated artifacts, and checked implementation bullets in this file.

