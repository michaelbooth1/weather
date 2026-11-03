# PT-1 bind-readiness review (2026-11-03)

- **Status:** DRAFT review for master, written by WS lane L59 on 2026-11-03 14:49 -05:00 (Get-Date).
  Outcome-blind and records-only. No price, label, outcome, panel, capture file or post-09-29 data was
  read. Every claim below cites a file and line, and no value was read off any data file.
- **Base:** `origin/master` @ `621d67f0fdbd05556725239cd09f07468c132241`. Other tips are named where
  they are cited.
- **The question (master, 11-03):** what does PT-1 need to bind before 12-12? Each item is marked
  DONE or MISSING with an owner. Is PT-1 on track for 12-12, and what is critical?

## 0. Verdict

**NOT on track for 12-12. As ordered, the premise does not hold.** Master ruling R21 (11-01) already
found that PT-1 with candidate C-PT is **NOT RUNNABLE** under method rules 4 and 6.

- Source: `C:\t\rulings-20261101\rulings.md`. It is a WS-local file with sha256
  `2499b5afec7a258378da9235689b594ae72a7c9f627d79c3b8c64ad489e2b44d`; the ruling is at :174-177.
- DECISION_LOG.md:309 (v) relies on R21: PT-1 "runs only if B is not FAIL AND its own feasibility gate
  passes; otherwise it is retired with an abandonment receipt (R21)".
- The binding checklist below cannot be completed for this candidate. Two things are critical:

1. **Rule 6 coverage fails, and no work can fix it before 12-12.** C-PT's pre-13 L6 arm has training
   coverage only to 12-16 (rulings.md:179; that line cites the L6_G frozen prereg :102-103). PT-1's window
   runs 12-12..01-25 (COOL_SEASON_PAPER_TEST_PREREG.md:174-177). The covered dates therefore number under
   20 even on the widest reading (rulings.md:179, :232).
2. **Rule 4 w fails on dev at the record tier.** See rulings.md:177-181. The prereg's own feasibility gate
   applies as well: if every w_h is below 0.05, PT-1 is NOT RUNNABLE (prereg :76-77).

**Reopen path:** R21 names one (rulings.md:198, :234). A new pre-13 candidate needs:

- training coverage through its last forward date;
- a dev walk-forward w that beats the placebo and floor-only controls;
- power of at least 0.5 at half the dev effect.

It also needs a **new prereg on later dates**, or an owner exemption. None of these exists today. Without
one, a 12-12 binding needs master to reverse R21, and this review does not assume a reversal.

**A records gap master should know about.** R21's own planned artifacts never landed:

- R21 planned them at rulings.md:186, :196-198 and :222.
- None is on `origin/master` or on any of the 40 most recent `origin/*` branches.
- `git log --all -S pt1-not-runnable` returns nothing.

The missing artifacts:

- the receipt `docs/research/pt1-not-runnable-2026-11-03/receipt.md`;
- the EXHAUSTION_REGISTER UNTESTABLE row;
- the DECISION_LOG R21 row;
- the PT-1 draft status note;
- the reserved-window status pointer;
- SoP rows 52/76/82;
- F8-MH Clarification 2;
- the T+1 freeze clause;
- the archive folder. It is not in `C:\archive\ruled-out`, and `INDEX.md` has no PT-1 line.

Because of this gap, live documents still treat PT-1 as bindable:

- STATE_OF_PLAY.md:75 reads "PT-1 ... 12-12..01-25 bound before D0". STATE_OF_PLAY.md:81 has the
  "PT-1 bound" row.
- The T+1 draft rev 11 still gates its final look on PT-1's look. It says "if PT-1 binds as drafted",
  and it holds dates for PT-1 "once bound". Source: `claude/t1-forward-prereg-20261030` @ `8f8158d1f`,
  README:388-402.
- SoP:56 and Clarification 6 row 6 order F8-MH's look "on or after PT-1's look".
- The look order is consistent in only one place. Clarification 6 row 8 already records PT-1 as claiming
  **none**. Source: `claude/b1-clar6-look-chain-draft-20261103` @ `f89e631cb`, :247; that row cites "R28b, rulings:736", which does not match line 736 of the local rulings copy cited here. R21 itself says the same at rulings.md:188 and :201: PT-1 claims no date once its receipt lands.

## 1. Binding checklist (prereg §8.1 :334-346, §9 :367-380, plus master's six items)

| # | Item | State | Owner | Evidence |
| --- | --- | --- | --- | --- |
| 1 | Candidate C-PT pinned by sha: MG-2 binding commit + `release-binding.json` sha; L6 part sha; w table sha; PT-1 engine sha (binding manifest, §8.1 item 7) | **MISSING**. The L6 part sha is DONE (`07a67425…ee17e9`, prereg :48). The MG-2 binding commit and release-binding sha are not pinned in PT-1. There is no w table, no engine and no binding manifest. The candidate itself is ruled NOT RUNNABLE (R21). | master (pin); model lane (w table, engine) | prereg :44-50, :340-341; rulings.md:177 |
| 2 | w fit + feasibility gate + dev replay + sizing (§2, §5.3), DEV_WINDOW_LEDGER `pending` row | **MISSING**. DEV_WINDOW_LEDGER.md has no PT-1 row (PT-1 appears there only inside row 104's F8-MH look-order text). Planned "by 2026-12-05" in §9. R21 already finds that rule 4 fails at the record tier. | model lane (after model priorities); master rules | prereg :76-77, :339, :375; rulings.md:177-181 |
| 3 | Emitter/recorder state: MG-2 exporter running; counts-only book field added to the exporter; G fixed by the §3.2 check | **MISSING**. The price store is named: DONE (`order_books_summary`, prereg :374). The counts-only exporter field is not added. G = 15 s is fixed by a master ruling (DECISION_LOG.md:276), but PT-1 has no §3.2 check receipt. R21's successor notes forbid any exporter edit before B's look receipt (rulings.md:198). This lane made no emitter change and does not propose one. | master (field); capture-host ops | prereg :132, :363-365, :372-374; rulings.md:198 |
| 4 | The §7.1 counts-only field (`n_snapshots`, `n_full_decision_coverage`, `n_clock_fail`; no `market_ws_events`) | **MISSING**. By ruling it is "specified at PT-1 binding" (rulings.md:121). Today only the draft §7.1 text exists (prereg :294-308). There is no field spec, schema or test. | master (spec at binding) | rulings.md:121; prereg :294-308; DECISION_LOG.md:276 |
| 5 | Rule finalised, raw sha256 pinned in a pushed commit and in DECISION_LOG; `prereg_check` passes | **MISSING**. The status is DRAFT with `PT_D0: UNSET` and no rule sha pinned. No prereg_check receipt exists for PT-1. | master | prereg :1-10, :336-337 |
| 6 | Owner gates (DECISION_LOG rows): the paper-test approval with this file's sha; the embargo carve-out for PT-1's single read; the α allocation | **Partly DONE, partly MISSING**. DL 276 records the 10-25 answers and the economics. The reserved window :40 has a dated "PT-1 single read" line. **MISSING:** a DL row approving the paper test *with the bound file's sha*, the α allocation, and a CAMPAIGN_LEDGER row for PT-1's one decision (a CAMPAIGN_LEDGER.md grep finds no PT-1). **Owner question Q-PT (for master to put, never treated as approved here):** does the owner's paper-mode scope cover PT-1 at all once R21 stands? If it does, does the 10-25 "Yes to all" (DL 276) approve a re-bound file under a new candidate and sha, or does a successor need its own approval and α? | owner (via master) | prereg :216, :338-343; DECISION_LOG.md:276; reserved-confirmation-window.md:40 |
| 7 | Reserved-window PT-1 row recording PT_D0, the 45th-date rule, moves-only-later, scope "PT-1 economic question only" | **Partly DONE.** The single-read line exists (:40), but PT_D0 and the 45th-date mechanics cannot be recorded while PT_D0 is UNSET. R21 planned a status pointer there that has not landed. | owner's file; master | reserved-confirmation-window.md:40; prereg :340-341; rulings.md:222 |
| 8 | Claimants: disjoint dates, and the rule-9 order agreed across all live claims | **MISSING (inconsistent).** PT-1's own §4.1 calendar is dated before R28b (prereg :162-170). T+1 rev 11 README:388-402 and SoP:56/75 still reserve dates and look order for PT-1. Clarification 6 row 8 (`f89e631cb`:247) and R21 (rulings.md:188, :201) say PT-1 claims **none**. The row-28b forward draft (Clarification 6 row 9) is also a candidate claimant. One record must win before anything binds. | master (look-chain owner) | prereg :162-188; t1 README:388-402 @ `8f8158d1f`; Clar 6 :245-248 @ `f89e631cb`; STATE_OF_PLAY.md:56, :75, :81 |
| 9 | Power under rules 16 and 19: N from measured σ at half the dev effect, at least 20 dates and power of at least 0.5 (rule 6); realised population (rule 16); SD from a same-kind contrast or a stated conservative bound (rule 19) | **MISSING.** §5.3 is planning arithmetic only, and "the binding recomputes it" from a dev replay of T and SE(E) (prereg :228-248). There is no dev replay, so there is no measured T or SE on the realised population, and §5.3's per-entry SD constant has no rule-19 same-kind source cited. The NOT-RUNNABLE sizing gate (MDE80 above 0.10 at N = 60, or T below 3) is unevaluated (prereg :246-248). Under rule 6 the covered N is already under 20 (R21). | model lane (replay); master (rule-19 bound) | prereg :228-248; MIM rules 6/16/19 (DECISION_LOG.md:291); rulings.md:179 |
| 10 | Look precondition: B's look receipt exists | **MISSING (later by design).** It is not needed to bind, but the look is defined after it. | master | prereg :378 |

Count: no item is fully DONE. Items 6 and 7 are partly DONE; the rest are MISSING.

## 2. What would have to happen for any PT-1-like test to bind

This lists conditions only; none is proposed or approved.

1. Master either keeps R21, in which case PT-1 is retired with the abandonment receipt (DECISION_LOG.md:309
   (v)), or reverses it with stated grounds.
2. If R21 is kept, a successor uses R21's reopen path (rulings.md:198). It needs a new candidate covering
   its last forward date, dev w beating the placebo and floor-only, power of at least 0.5 at half the dev
   effect, a new prereg, **later dates** (not 12-12) and its own owner approval and α.
3. In either case R21's planned records should land first: the receipt, register row, DL row, SoP 52/76/82,
   the F8-MH Clarification 2 and the T+1 clause. Until they land, T+1 and F8-MH wait on a look that will
   not happen (rulings.md:702, C11).

## 3. Boundaries kept

- Records only: no fit, no replay and no data read.
- No file under any panel store, the sealed panel, 88a or 09-30..10-15 data was opened.
- No emitter, scheduled task, exporter edit or approval was created or assumed.
- No B-bound file, `B_FORWARD_TEST_DESIGN.md` or MG-2 binding folder was edited.
- rulings.md was read, not edited; it is cited by its sha.
