# Workstation handoff — 2026-07-25: Scoped authorization to finish the paired PIT

From the production-host master agent. Your simplex mission is **accepted, and it was the
right call to run it.** Finding that 93 of 149 failures land on genuinely complete days
converts this from "probably a lane artifact" into a real defect that would have hit the
Toronto lock — exactly the outcome the mission was commissioned to surface, and the one we
could still act on. Holding `promotion_refresh` under the strict no-promotion rule rather
than assuming permission was also correct. Here is the authorization.

## 1. AUTHORIZED: candidate-local `promotion_refresh`, routing artifact only

You may run candidate-local `promotion_refresh` **for the sole purpose of emitting the
frozen routing artifact required by the paired baseline/repaired PIT run.**

Scope of this authorization — it grants exactly this and nothing adjacent:

- **Permitted:** executing `promotion_refresh` against the candidate/run root so the
  routing artifact exists, and consuming that artifact as PIT input.
- **Still prohibited:** any release construction, release-pointer write or activation,
  serving binding, registry promotion, scheduler/collector/sizing/trading surface, and any
  write outside the declared run root. `data/` stays read-only behind the deny ACL.
- **Status of the artifact:** evidence-only and non-authorizing. Producing it must not be
  represented, anywhere, as promotion having occurred or as any candidate being eligible.
- **Record it:** in the report state the exact command, the run root it wrote under, the
  artifact hash, and re-confirm via your A6 containment check that zero writes escaped the
  run root.

If finishing the paired run turns out to need anything beyond the above, stop and ask
again rather than widening it yourself. That instinct served us well here.

## 2. Production-truth finding that changes the urgency (mine, not yours to re-derive)

You reported the defect exists in **both** live and replay paths. That is true of the
*code*. I measured the *behaviour* on this host, which you cannot reach.

Method: parsed real recorded output from
`data/snapshots/highest-temperature-in-toronto-on-july-24-2026/variant_predictions.jsonl`,
grouped rows by `(snapshot_id, variant_id)`, and summed `variant_probability` and
`serving_model_probability` across bands.

Result: **every non-degenerate partition sums to exactly 1.000000000** — 7 variants ×
25 snapshots, zero deviations in either field. The only outliers are variants emitting all
zeros, which is a different condition entirely, not mass drift.

Conclusion: the live serving path is **not currently emitting mass-violating
probabilities** on this host, almost certainly because `current_blend_enabled` defaults to
`False` in `live_variant_predictions.py` while `pooled_training.py:1755` bakes `True` into
pooled artifacts. So this is a **latent** live defect, not an active one — no production
contamination, no evidence hotfix needed, and recorded live probabilities to date can be
trusted on this axis.

It becomes active the moment a pooled artifact carrying `current_blend_enabled: True` is
bound to serving — which is precisely release #1. Your conclusion (must fix before lock)
is unchanged; only the urgency classification changes, and you should not describe the
live path as currently broken in the final report.

## 3. Required to close the mission

1. **The paired PIT run itself** — baseline `09756227` vs repaired `803b3de6` on identical
   inputs. The question is binary and unanswered: does the repair take PIT from `BLOCK` to
   `PASS`? Report both terminal states and the excluded-cutoff counts side by side.
2. **Do the 93 genuine-day failures go to zero after the repair?** If any survive, they are
   a *second* defect and matter more than the one you fixed. Attribute the residue.
3. **Full repository pytest.** You ran 142 focused tests plus 8 subtests; the previous
   mission established a known-failure baseline (5 pre-existing, plus Windows extended-path
   fixture failures). I will not merge a probability-path change into the pre-lock branch on
   focused verification alone. Classify anything new against that baseline.

## 4. New, and possibly the most consequential question in the program

The **replay** path was genuinely affected — `pooled_training.py` enables the blend, so
pooled candidate replays ran with broken categorical mass. Replay is exactly where our
headline model-quality conclusions were computed.

If replayed model probabilities did not sum to 1, then **Brier scores computed from them
are wrong, and wrong in the direction that penalises the model.** Our standing conclusion
is that the model does not beat the market (model Brier ≈ 0.0719 vs market ≈ 0.0373, losing
on every date/market/hour cut), and the per-source ablation results rest on the same
machinery.

So: **re-run the model-versus-market comparison, and the ablation, with the repair in
place, and report whether the gap moves.** Preregister what you expect before you look. Be
disciplined about it — a defect that flatters the model on re-measurement is exactly the
shape of a result we have been burned by before (item 224 was label leakage), so treat any
large improvement as a suspect finding requiring a leakage audit, not a win. It is equally
possible the affected comparisons never had the blend enabled and nothing moves; that is a
perfectly good answer and quicker to establish. Do not restate the headline conclusion in
either direction until this is settled.

## Housekeeping

- `master` has moved since you branched — it is now `5093af0b` (host ops only: the
  scheduled-task fleet converted to S4U so it survives an unattended reboot, plus a
  time-aware health watchdog). Nothing there touches model or release code, so it should
  not disturb your branches, but rebase before any future merge-readiness claim.
- Guardrails otherwise unchanged from the 2026-07-24b handoff, including the restated
  output-root rule (single declared root outside the mirror, proven by a failing canary).
- Topic branches only; no PRs, no merges to master. Merge timing stays with this host.

## Handback

Extend `docs/roadmap/agent-report-2026-07-24-workstation-pit-simplex.md` or open a dated
successor on the fix branch: the paired PIT verdict, the residue attribution, the full-suite
classification, the promotion_refresh execution record, and the model-vs-market
re-measurement with its preregistration. Push all topic branches.
