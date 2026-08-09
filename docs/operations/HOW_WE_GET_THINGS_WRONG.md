# How this project characteristically gets things wrong

**Written 2026-08-09** from a one-month retrospective (2026-07-09 → 2026-08-09). Canonical.

`RETRACTED_AND_FALSE_LEADS.md` owns **which claims were false** — 31 of them. **This file owns the
*shape*.** Instances there are symptoms; the five patterns here are the disease, and every one of
them recurred at least twice in a single month.

**Read this before designing a gate, commissioning a mission, or trusting a green signal.**

---

## The month in numbers, stated plainly

| | |
| --- | ---: |
| Commits | **617** |
| Missions dispatched | **130** |
| Agent reports returned | **125** |
| Claims retracted as false | **31** |
| **Shipped changes that improved a served number** | **1** |
| Retrains completed, ever | **0** |
| Trades made, ever | **0** |
| Maker days with `fills.jsonl` written, ever | **0** |

The one shipped win is the serving floor (2026-07-31): served ratio **1.6639 → 1.4980**, crossed CI
**[−0.3553, −0.0698]** — and **only ~2.2% of it landed in the 09:00–14:00 primary objective window.**
The blind-feature repair that followed moved the in-season gap **1.423260 → 1.423246**, at most
**0.6% of the distance to parity**.

**That is enormous throughput converted overwhelmingly into elimination rather than capability.**
Eliminations are real progress and they are permanent — nobody will ever again search for a quotable
model edge. But the honest sentence is: *we spent a month learning what does not work, and most of
it could have been learned in the first week.*

---

## Pattern 1 — The self-referential gate

**A gate whose reference standard comes from the thing being checked is satisfied by construction.**
It will read green forever, including on the day the thing it guards is completely broken.

| Instance | Standard came from | Result |
| --- | --- | --- |
| `fleet-coverage` | the archive's own `season_window` | **OK 12/12** while covering **0%** of target dates, for five weeks |
| Retrain admission | the candidate's own manifest | gate shrinkable 20,160 → 2,520 cells |
| Parity known-defects fixture | a hardcoded list of 9 dead features | after 8 were repaired it still demanded 9, so the gate **could never reach exit 0** |
| Model input surface | nothing watched it at all | 10 of 19 features dead for 5 weeks |
| **The `-09-50a` rehearsal design** | **the production agent, hours after this file was written** | a test structurally incapable of failing on the condition it was meant to check |

**Detection question: *what would make this check fail?*** If the answer is "the thing would have to
contradict its own declaration," the check is decorative.

**The fourth row is the sharpest instance, because it was committed the same day this file was.**
The `-09-50a` handoff asked for a rehearsal target that was simultaneously **(a)** in-season, so the
archive would not be the blocker, and **(b)** able to exercise the Denver `2025-07-28` exclusion that
`-09-42a` had just landed. **Those are mutually exclusive under a single `--target-date`:**
`2026-06-10` selects June 3–17 in each prior year, so its code-owned exclusion set is *empty*, and
any target whose window reaches a July date necessarily needs archive rows after June 30.

So the rehearsal could report "exclusion set clean" **no matter what `-09-42a` did** — the check
could not fail. The workstation caught it and invoked the handoff's own declared falsifier instead of
returning a number that looked like an answer.

**Two transferable lessons.** *Writing the pattern down does not immunise you against it* — it is a
property of designs, not of awareness. And **a mission's falsification section is not boilerplate**:
it is the mechanism by which a badly-specified question gets refused rather than answered wrongly.

---

## Pattern 2 — We instrument eligibility, never outcome

**The most expensive pattern of the month.** Every meter we built measures whether conditions were
*permitted*, not whether the thing *happened*.

- **A "countable day" never required a quote.** The live-forward gate certifies that paper-evidence
  preflight passed. `2026-07-12` counted with 1,848 intent rows and **zero quote permissions**.
- **`fills.jsonl` has never been written on any of 55+ maker days**, and no monitor said so.
- **The maker has emitted `NO_QUOTE` on 100% of rows** across every run ever examined — 554,004
  post-boundary rows, zero quotes — while we tuned freshness, planned reward qualification, and
  tracked a countable-day clock toward a 22–43 day bar.
- Coverage, countability, freshness, parity: **all upstream proxies.** Not one of them could detect
  that the bot has never traded.

**Detection question: *which artifact would be empty if this never actually worked?*** Then check
that artifact is non-empty, on a schedule. **A proxy is not evidence that the outcome occurred.**

---

## Pattern 3 — The decisive question is cheap, and we ask it last

Every question that actually redirected the project was answerable in hours, from data already on
disk, and was asked **after** months of work premised on its answer.

| Question | Cost to answer | Asked after |
| --- | --- | --- |
| "Does the maker ever emit a quote?" | one query over retained CSVs | **months** of MM gate work |
| "Is there any cell where we beat the market?" (`-09-46a`) | days, pre-registered | months of assuming yes |
| "Can executions be reconstructed?" (`-09-47a`) | days | a mission commissioned on the assumption |
| "Does the archive cover the target dates?" | one manifest read | five weeks of `OK 12/12` |

**Detection question: *what is the cheapest observation that would kill this whole track?*** Ask it
in week one, not month three. **Sequence work by what could falsify it, not by what builds on it.**

---

## Pattern 4 — Building on a premise nobody opened

Distinct from Pattern 3: not *when* you asked, but whether you **looked at the thing itself**.

- The production agent confirmed the tape's **schema** had trade columns and that **265 files**
  existed, then commissioned a mission — **without opening one file.** The tape held 71 executions
  in 1.1 million rows. *A schema is not data; a file count is not content.*
- The same agent then hypothesised the known-edge map was **incomplete**. It matched **100%** of
  rows. That guess stayed out of canon **only because it was written into the handoff as a
  hypothesis to trace rather than a finding** — which is the practice that saved it.
- `SEASON_START = (5,10)` carried a comment explaining why it was correct. **It was correct when
  written** and expired silently on 2026-06-30.

**Detection question: *have I opened the actual artifact, or only its description?*** And when you
must pass an unverified belief to someone else, **label it a hypothesis to trace.** That label is
load-bearing; it is the difference between a corrected guess and a corrupted canon.

---

## Pattern 5 — Filing a risk is not mitigating it

**Log rotation was filed as rank 1 of `OPEN_BACKLOG` on the evening of 2026-08-08 and took capture
down for 5 h 54 m the next morning.** The `-09-35a` handoff had predicted the failure three days
earlier and named the exact file. The streak day survived only because the outage happened to fall
before the graded window.

**Detection question: *is this item's rank reflected in what is scheduled next, or only in a
document?*** A backlog that outruns dispatch is a list of incidents waiting for a date.

---

## What actually worked — do not lose these

The month's negative results are **trustworthy**, and that is not luck:

1. **Pre-registration before measurement.** `-09-46a` froze its method in the first commit, four
   commits before any result. Note the honest caveat: those guardrails prevent false *positives*, so
   for a uniformly negative result they were never load-bearing — **cite the interval, not the
   prereg.**
2. **Crossed date × market clustering, with power and MDE.** It converted "not powered" hand-waving
   into decisions. The `-09-44a` null is *precise*, which is why it could close a question.
3. **Reproducing handbacks on the production host before changing canon.** It caught a stale tip
   hash, a wrong roll verdict derivation, and a `_quarantine` miscount this month.
4. **Distinguishing *unidentified* from *underpowered*.** `A` and `f` are not weak estimates; there
   is no valid observation unit. Saying so stopped a doomed measurement programme.
5. **Reports that say what would falsify them.** Every mission that returned a hard NO had that
   section.

---

## The one-line version

> **We are excellent at measuring whether we were allowed to do the thing, and we have never once
> measured whether the thing happened.**

## Update this file when

A new instance of one of these patterns is found (**add it to the table — the count is the
argument**), or a genuinely new pattern appears. **Do not add an instance to
`RETRACTED_AND_FALSE_LEADS.md` without asking which pattern it belongs to here.**
