# Workstation handoff — 2026-07-28d: are we serving a worse model than we built?

**This supersedes the ordering in `workstation-handoff-2026-07-28c-scale-the-mm-corpus.md`.**
That queue is still live and still wanted — it moves to Missions 2+ below. One experiment
jumps ahead of it because it is nearly free and could reframe everything.

Mission 0 (green the ratchets your branch reddened) is unchanged and still first.

## The hypothesis

Our decomposition says the model-market gap is **98.88% resolution and 1.12% reliability** —
we are well calibrated and insufficiently sharp.

Now look at what the serving path does. `current_blend` mixes the candidate with an incumbent
on **97.29% of rows at median α = 0.50**. Averaging two forecasts is mathematically a
sharpness-destroying, calibration-preserving operation. **That is precisely the fingerprint we
measured.** We may be manufacturing our own resolution deficit.

The supporting receipts are already in your own reports:

- Dallas 2026-07-07: preblend winner probability `0.999999927` → final `0.501756776`.
- On the 86 partitions where the printed floor identified the winner, **preblend categorical
  Brier was `0.000499319`** with mean winner probability `0.986569` — near perfect — and the
  blend damaged them.
- Preblend had **zero** partitions with impossible mass; the final output had 108 of 124.
- In `src/weather/model/current_blend.py`, `current_blend_source_freshness_default_alpha`
  defaults to `0.0` and is combined with `min()`, so an unrecognised or degraded source state
  collapses weight away from the candidate — and all 38 catastrophic above-floor cases
  reported failed `weather_forecast` / `wu_current` / `wu_history`.

## Mission 1 (new, ahead of corpus scaling): score preblend against the market

You already capture the preblend vector. Score **preblend vs final vs market** on the frozen
corpus you used for the decomposition. No fitting, no tuning, no model change.

Report, for each of preblend and final:

1. **Brier against the market's**, pooled and with the full Murphy decomposition —
   reliability, resolution, uncertainty. The specific question: does preblend recover the
   resolution that final lacks, and what does it cost in reliability?
2. **By hour**, with the named cuts: predawn 03–05, primary 09–14, evening 20–23. I expect
   the blend to help somewhere or it would not have been built — find where, and whether that
   help is worth what it destroys elsewhere.
3. **Split by the populations you already identified**: the 86 floor-aligned and the 38
   above-floor cases. The blend rescues the 38 and damages the 86; quantify the exchange rate
   in Brier terms, pooled and per-row.
4. **Effective bands and mean top probability** for both, so sharpness is visible directly
   rather than inferred.
5. **α sensitivity**: what does the pooled score look like as α sweeps 0 → 1? If the current
   median 0.50 is far from optimal, that is a configuration finding, not a research finding.

### Why this matters more than another measurement

If preblend beats final in the uncertain hours, **the model is not our problem — the serving
path is**, and the fix is configuration rather than a research programme. If preblend also
loses, then the roughly 30% distance to the market in genuinely uncertain hours is real
forecasting distance, and we would be choosing whether that is closable rather than assuming
it is.

Either answer is decision-grade. Neither requires new data.

### Cautions

- **This is a leakage-shaped result waiting to happen.** "Turn off the blend and everything
  improves" is exactly the kind of large, tidy improvement that has twice turned out to be a
  bug here. Verify preblend is genuinely the pre-blend vector at the same cutoff with the same
  inputs, and that nothing downstream of it has seen the outcome.
- Do **not** change `current_blend`, any alpha, or any serving surface. Measure and report.
  Turning the blend off is an operator decision and I want the exchange rate quantified before
  anyone proposes it.
- Remember the blend was presumably built for a reason. If it is protecting against a failure
  mode that only shows up in conditions your corpus under-represents, say so.

## Missions 2+: the corpus scaling queue, unchanged

Everything in `workstation-handoff-2026-07-28c-scale-the-mm-corpus.md` still stands and
follows this: establish the Data API retention horizon empirically, backfill all 12 markets,
re-run the market-making measurement with intervals that mean something, split by market and
Celsius-vs-Fahrenheit, characterise the 30-minute-to-settlement P&L curve, and close the
rewards gap.

## Guardrails

- `data/` read-only with proven deny-write ACL; single declared output root.
- **No model, blend, alpha, collector, trading, sizing, cap, serving, scheduler, promotion,
  release or pointer change.** Measurement and written design only.
- Topic branches only; push without asking; never master, no PRs, no merges.
- NOT-DONE / NOT-REHEARSED first-class.

## Handback

`docs/roadmap/agent-report-<date>-workstation-preblend-vs-market.md`: the three-way comparison
with full decompositions, the hour and population splits, the sharpness measures, and the α
sweep. Push all topic branches.

Context: streak 6/14, earliest lock ~2026-08-03. Master is `cbaadf96`. Your mm-measurable
branch is validated but held pending Mission 0.
