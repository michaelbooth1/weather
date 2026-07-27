# Workstation handoff — 2026-07-27e: what are we actually serving?

Missions 2+ of `workstation-handoff-2026-07-28c-scale-the-mm-corpus.md` remain live and
unchanged. They stay gated to 01:00–08:30 ET with practical entry after 06:00 ET, which is
correct — my mirror sync writes to `\\DESKTOP-RFCD2GH\weather-mirror` at 04:30 with `/MIR`
and deletes tapes that CLOB tiering has gzipped on my side.

That leaves the evening idle. The two missions below need **no vendor call, no full-book
read, and no new data** — they run on the corpus you already froze. Do them first.

## First, the correction that motivates this

I was wrong about the blend, and your audit was right. Replay-final beats preblend in
aggregate, in all three named windows, and in 20 of 24 hours, with *both* lower reliability
error and higher resolution. The mechanism I named — `current_blend_source_freshness_default_alpha`
collapsing to 0.0 through `min()` — was inactive in the artifact. I described a constant
"median alpha 0.50" that does not exist; alpha is candidate weight, default 1.0, applied per
band. I reasoned from a mathematical property of averaging to a claim about this system and
then treated anecdotes as confirmation.

Please read the missions below in that light and push back where the framing smuggles in an
assumption. **The failure mode to guard against here is not a fake win. It is me handing you a
tidy story and you measuring it instead of testing it.**

## Mission 1: score the output we actually recorded

Your own provenance correction is the most valuable thing in the report. You established that
`probability` is a *reconstruction* — `active_registry_contract = {}`, validation `BLOCK` — so
nothing yet shows production served it. But the frozen vector already carries
`recorded_probability`, the historical output control, and the report defines it without ever
scoring it.

**Score it.** Same corpus, same two lanes, same decompositions, same named cuts as Mission 1
of `-28d`. Report `recorded_probability` alongside `candidate_preblend_probability`,
`probability`, and `market_yes`. Also score `current_probability` (the incumbent input) on its
own — it is a free baseline and if the incumbent alone is competitive that is its own finding.

The specific questions:

1. **Which lane does the recorded output resemble?** Row-level, not just in aggregate score:
   exact-match fraction and mean absolute deviation of `recorded_probability` against preblend
   and against replay-final. A score that lands between them is ambiguous; row-level agreement
   is not.
2. **Is what we served worse than what we could have served?** If recorded tracks preblend
   (0.065607) while replay-final reconstructs to 0.062056, quantify that deficit pooled, by
   named window, and by hour.
3. **Coverage first.** What fraction of the 206,745 rows actually carry a usable
   `recorded_probability`? If coverage is partial or non-random, say so before scoring, and
   report the scored subset's population separately — a coverage-selected subset is not the
   frozen corpus.
4. **Does the recorded output respect the simplex and the physical floor?** You found preblend
   had zero impossible-mass partitions against 108 of 124 for the reconstruction. Where does
   the recorded output sit? That bears directly on
   [the floor defect](agent-report-2026-07-25-workstation-simplex-authorization.md).

This does not require active-release binding, because it is not a claim about *configuration*.
It is a measurement of an artifact we already recorded. Please keep that distinction explicit
in the writeup, and keep saying NOT-PROVEN about anything that would need release binding.

## Mission 2: is the loss concentrated at band boundaries?

Now that the blend is cleared, the promoted suspect is that we predict a continuous
distribution and then bin it, while the market prices bands directly — so our error should
concentrate exactly where binning decides payout. Eleven of twelve markets are Fahrenheit
converted from a Celsius model, which puts a unit conversion between our distribution and the
band edges.

On the frozen corpus, with no new data:

1. **Distance-to-boundary attribution.** For each partition, compute the realized daily max's
   distance to the nearest band edge in native units. Bucket it, and report our Brier, the
   market's, and our excess loss per bucket. If our disadvantage is roughly flat in that
   distance, binning is not the story and this suspect dies cleanly. If it spikes near edges,
   quantify what share of total excess loss lives within, say, 0.5 native units of an edge.
2. **Conversion convention.** For the F markets, does the C→F path that assigns predicted mass
   to bands use the same rounding convention as the settled label? Count how many settled
   labels in the corpus would change band under the alternative convention (floor vs round vs
   nearest). This is cheap and the answer is a count, not an opinion.
3. **A control I want, because it tests my framing rather than confirming it.** Compare the
   Celsius market (Toronto) against the Fahrenheit ones on the same boundary metric. If the
   effect is real and conversion-driven, Toronto should look different. If Toronto looks the
   same, the effect — if any — is about binning generally, not about the unit conversion, and
   my emphasis on conversion is wrong.
4. Report the corpus-wide label-vs-exchange reconciliation rate as context. My host shows 11 of
   12 matching on a recent day with one `local_missing`; if the corpus rate is materially worse
   than that, our training target is polluted and that outranks everything else here.

## Mission 3: the scaled-MM queue, unchanged, after 06:00 ET

Everything in `-28c` still stands and still follows: establish the Data API retention horizon
empirically, backfill all twelve markets, re-run with intervals that mean something, split by
market and by Celsius-versus-Fahrenheit, characterise the 30-minute-to-settlement P&L curve,
and close the rewards gap. Your `NONTERMINAL_FULL_BOOK_HASHES_REQUIRED` gate stands.

Bind your catalog to hashes before 04:30 if any read spans it, so a tape the mirror deletes
surfaces as a hard error rather than a silent truncation.

## Guardrails

- `data/` read-only with a proven deny-write ACL; single declared output root outside the mirror.
- **No model, blend, alpha, floor-order, config, artifact, release, pointer, collector,
  scheduler, sizing, cap, trading or serving change.** Measurement and written design only.
- Topic branches only; push without asking; never `master`, no PRs, no merges. Merge timing
  stays with me.
- No vendor request outside the declared window.
- NOT-DONE / NOT-REHEARSED first-class, as in the last two reports.

## Handback

`docs/roadmap/agent-report-<date>-workstation-what-are-we-serving.md`: the four-lane comparison
with coverage stated before scores, the row-level agreement evidence, the boundary attribution
with the Toronto control, and the conversion-flip count. Push all topic branches.

Context: master is `f3b6c132` and now carries your preblend report. Streak 6/14, earliest lock
~2026-08-03. Your mm-measurable branch merges here at 01:15 tonight — it is verified green on
my side (2 failed / 3172 passed, both failures pre-existing on baseline master), and it is
roll-sensitive because Mission 0 added the two schema-registry files, which is why it waits for
the quiet window rather than landing now.
