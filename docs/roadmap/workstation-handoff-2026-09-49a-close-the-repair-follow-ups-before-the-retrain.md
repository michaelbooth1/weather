# Workstation handoff 2026-09-49a — close both `-09-43a` follow-ups BEFORE the first retrain

Written 2026-08-09 by the production agent. Read on `origin/master` and execute.

## 1. Why now, and not after

`-09-43a` landed on 2026-08-09 01:20 and left two follow-ups explicitly owed. They have sat unowned
because neither changes a served number today. **That changes this week**: the forecast archive is
about to be extended (`-09-33a` made the window target-derived; production runs the ~60-call
backfill next), and the **first retrain becomes runnable immediately after.**

> **Item 2 below is a training-side train/serve skew. If the retrain runs before it is fixed, the
> new candidate is fitted on features that cannot exist at serve time in 11 of 12 markets — and we
> bake this project's dominant defect class into the artifact we have been waiting months to
> produce.** That is the whole reason this is dispatched now rather than queued.

## 2. Item 1 — narrow the parity known-defects fixture to `wind_group`

`tests/fixtures/train_serve_feature_parity_known_defects_v0.1.json` still declares
`nine_empty_base_features_09_to_14`, which requires **nine** base features to be dead at serve in
09:00–14:00. After `-09-43a` routed eight of them, **only `wind_group` still is.** The parity gate
therefore **cannot reach exit 0** no matter how correct serving becomes.

**Narrowing this fixture RECORDS the repair. It does not weaken the gate** — and the distinction is
the whole point, so make it provable:

- The remaining defect must still be **asserted**, not deleted: `wind_group` stays declared, and a
  rediscovery of any of the other eight must still **fail** the gate.
- `tests/reporting/test_train_serve_feature_parity.py` pins `rediscovered is False` and an exact
  `found_markets` set for this defect id — update those deliberately and say in the report what each
  assertion now protects.
- **Do not touch any other defect id**, and do not change the fixture's schema version without
  registering it (an unregistered schema literal turned master red on 2026-08-08).

Report the gate's exit code before and after, and state plainly whether it now reaches 0 or whether
something else blocks it.

## 3. Item 2 — drop `pressure` and `pressure_trend_3h` from **F-market training**

`ESTABLISHED_FINDINGS.md` §5: a feature that is unknowable at serve must not be trained on.

**The asymmetry is the whole difficulty, and getting it wrong damages Toronto:**

| Market class | Station pressure at serve | Correct action |
| --- | --- | --- |
| 11 F markets | **Absent.** METAR carries altimeter / sea-level pressure; the trained feature is *station* pressure. Aliasing them would pass a presence check and be **false**. | **Drop from training** |
| Toronto (C) | **Present** — real captured station pressure | **KEEP. Do not touch.** |

So this is a **per-market-unit** change, not a global feature removal. `pressure` staying dead *at
serve* in the F markets is **correct behaviour and must stay that way** — you are fixing the
training side only.

Required:
1. Make the exclusion follow the market's unit/class from the registry, never a hardcoded market
   list — a 13th market must inherit the right behaviour automatically.
2. **Serving must be unchanged.** Prove it: reproduce the post-anchor replay and show the served
   distributions are byte-identical, or explain exactly why any changed.
3. State what this invalidates. If any bound artifact selected these features in an F market, say so
   — that is a finding, not a footnote.

## 4. What would falsify this mission

- **The features are not actually selected in the F-market fitted artifacts**, making the change
  a no-op for served output. Then it is hygiene that prevents a *future* defect — still worth
  landing, but **report it as a no-op rather than claiming a repair.**
- **Narrowing the fixture does not get the gate to exit 0** because something else blocks. Then name
  the blocker; that is more valuable than the narrowing.
- **The registry does not carry a usable unit/class distinction.** Then stop and report it —
  hardcoding a market list to get green would be exactly the shortcut this project has banned.

## 5. Context you should not re-derive

- `-09-43a` routed 9 of 10 dead base features (parity **196 → 100** blockers, 0 unexpected) and
  **did not move the market gap**: paired **−0.0000140 [−0.0022674, +0.0024795]**, ≤0.6% of the
  distance to parity (§4, `-09-44a`). **Do not cost this work as gap closure.** It is correctness.
- `COMPLETE_DAY_MIN_ROWS = 18` is **not a knob** — it also decides settlement trust and streak
  completeness.
- Master's module-size ratchet was red on 2026-08-09 and is fixed; if you grow a module past 2,000
  lines, add the ownership entry in the same branch rather than bumping the expected count.

## 6. Boundaries

`DELEGATION_CONTRACT.md` §2 in full. **Promote nothing, place no order, enable no live trading, call
no exchange or provider endpoint.** Do not write production `data/`, run the chain, settle a date,
or restart a loop. **Never weaken the serving floor.** Crossed date × market clustering; power
before interpretation; never pool across `2026-07-31`.

Fitting is permitted **only** if a step here requires it and you say so explicitly; this mission is
expected to need none.

## 7. Branch and report

- Branch: `codex/workstation-close-the-repair-follow-ups-2026-09-49a`
- Report: `docs/roadmap/agent-report-2026-08-12-workstation-repair-follow-ups.md`

Base on `origin/master`. Per `DELEGATION_CONTRACT.md` §5, with production-host reproduction paths and
a per-file roll verdict from `scripts\ops\roll_verdict.ps1 -Branch <branch>` — **never hand-derived.**
Touching `feature_store.py` or `model_features.py` will make you roll-sensitive; that is expected.
**Commit and push whenever you finish, at whatever hour.**
