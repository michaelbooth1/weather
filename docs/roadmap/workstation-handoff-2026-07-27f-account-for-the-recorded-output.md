# Workstation handoff — 2026-07-27f: account for the recorded output

Missions 3+ of `workstation-handoff-2026-07-28c-scale-the-mm-corpus.md` are unchanged and
still run in the morning window. This mission needs no vendor call and no full-book read.

## Two things you found that I want to make central

First, thank you for stopping Mission 2 rather than producing it. Refusing to apply alternate
rounding to already-rounded integers because it "would manufacture a circular zero" is the
right instinct, and so is refusing to reuse `settlement_distance_bucket` when it is
outcome-derived, and refusing to substitute my host's "11 of 12" observation into a historical
corpus whose authority summary is `{"unreported": 141}`. My conversion premise was simply
false for the accepted artifact — `prediction_mode = band_binary`, `family_unit = F`, direct
band prediction, with `continuous_density_f` present in source but not this artifact's branch.
That is the third of my framings this week that measurement has killed. Keep doing that.

Second, the result I asked for is not the most important thing in your report. This is:

| Comparator to recorded | Row numeric exact | Whole-partition exact | Mean TV |
| :--- | ---: | ---: | ---: |
| Preblend | 0 / 206,745 | 0 / 18,791 | 0.432 |
| Replay-final | 0 / 206,745 | 0 / 18,791 | 0.243 |
| Incumbent | 9,115 / 206,745 (4.41%) | **0 / 18,791** | 0.152 |

**Zero whole-partition matches against any documented lane.** Recorded is not preblend, not
the reconstruction, and not the incumbent — it is closest to the incumbent and equal to
nothing. And it scores worse than *both* inputs it would have to be built from: 0.073694
against incumbent 0.070310 and preblend 0.065607.

We cannot reproduce our own recorded output from its documented inputs. Until that is closed,
every offline improvement we measure is unfalsifiable, because we cannot show the thing we
would improve is the thing we emit. I think that outranks the scaled-MM queue.

## Mission 1: what function of the available inputs reproduces `recorded_probability`?

Frame this as accounting, not hypothesis-confirmation. Enumerate candidate explanations,
test them, and report which survive — including the outcome where **none** do, which is a
legitimate and important answer.

Candidates I can name, in the order I would try them. I am not asking you to prefer mine:

1. **Solve for the implied blend weight.** If recorded were `α·preblend + (1−α)·incumbent`,
   then α is determined per band row wherever the two inputs differ. Solve it. The diagnostic
   is not whether some α exists — it is whether the implied α is *coherent*: stable within a
   partition, within a market, within an hour, and inside `[0,1]`. Report its distribution and
   the residual after the best per-row, per-partition and per-market α. If the residual does
   not go to zero, recorded is not a convex blend of these two lanes and that is settled.
2. **Temporal lag.** The deficit is smallest at hour 12 (`+0.042`) and largest at hours 22, 23
   and 18 (`+0.263`, `+0.249`, `+0.224`) — worst when the truth is resolving fastest. A stale
   or carried-forward output would have that shape. Test it directly: does recorded at snapshot
   `t` match some lane at an *earlier* snapshot better than at `t`? Sweep the lag and report
   the best-matching offset. **State the null explicitly** — if lag 0 already wins, staleness is
   dead and I want that said plainly rather than a marginal improvement dressed up.
3. **Post-processing after the blend.** Recorded has the lowest resolution of any lane
   (`0.016728`) and the highest reliability error, which is what smoothing, clipping,
   flooring or renormalisation would do. Can any documented postprocess step, applied to a
   lane you already have, move it toward recorded?
4. **A different artifact or code version.** If the frozen inputs cannot produce recorded under
   any of the above, then recorded came from something not in the frozen set. Say so, and say
   what identity evidence would be needed to name it.

Report the surviving explanation, or `NOT_ACCOUNTED_FOR` with the eliminations that got you
there. A clean elimination is worth as much to me as an identification.

## Mission 2: what would it take to bind a lane to production?

You have now written "not an active-release binding" three reports running, and you are right
each time. So specify the fix, in writing, without needing release #1 to exist.

What minimal, concrete evidence would establish that a given probability vector is what
production served for a given market-day-snapshot? Name the artifacts, identity fields, and
invariants — and what would have to be *captured at serving time* that we are not capturing
now. Treat it as a design note for the release-#1 work.

Constrain it: this must be a change to what we record, not a change to how we serve. If the
answer requires touching the serving path, say that explicitly and stop there rather than
designing it.

## Cautions

- I have now been wrong three times by supplying a mechanism and finding it plausible. The
  lag hypothesis in Mission 1 is mine and should be treated with the same suspicion as the
  blend and conversion hypotheses were. Test it, do not serve it.
- An implied-α distribution that looks structured is exactly the kind of tidy result that
  should raise suspicion first. Check it against the residual before believing it.
- Nothing here authorises a serving, config, alpha, floor or release change, and a
  reproduction result would not authorise one either.

## Guardrails

- `data/` read-only with proven deny-write ACL; single declared output root outside the mirror.
- No model, blend, alpha, config, artifact, release, pointer, collector, scheduler, sizing,
  cap, trading or serving change. Measurement and written design only.
- Topic branches only; push without asking; never `master`, no PRs, no merges.
- No vendor request outside the declared window.
- NOT-DONE / NOT-REHEARSED first-class.

## Handback

`docs/roadmap/agent-report-<date>-workstation-account-for-recorded.md`: the accounting result
with eliminations, the implied-α coherence evidence and residuals, the lag sweep including its
null, and the serving-binding design note. Push all topic branches.

Context: master is `5075d5d5` and carries both your reports. Streak 6/14, earliest lock
~2026-08-03. Your mm-measurable branch merges here at 01:15 tonight.
