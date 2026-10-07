# D — "Shadow agrees with replay" live gate: specification v3.3 (text amendment of v3.2)

> **Repository copy (2026-10-07).** Status: the current draft of the maker replay v2 "shadow agrees with replay" live-gate
> specification and the registration draft text it carries (OD22, the v1-exam disclosure). It is a **draft for owner
> decision, not a signed registration**, and grants no run, live, merge or transfer authority. Owner item:
> [item 330](items/item-330-maker-economics-refocus-master-plan.md); current status of maker replay v2 lives in
> [the state of play](../operations/STATE_OF_PLAY.md), never here.
>
> **Read when** reviewing the shadow-vs-replay gate, the v1-exam disclosure wording, or OD22 before the v2 signature.
>
> **Provenance.** The H1 and the text between this note and the appendix are a verbatim copy of the workstation file
> `l-data/swarm-m/D-shadow-gate-spec-v3.3.md` (SHA-256 of the CRLF local file; this repo copy is stored with LF line endings, so hash it with CRLF restored —
> `36120634030de0cdef91b5a7b4470390685d92be6d496c580c38dbf26e8940f9`, including its 2026-10-07 defect-2 amendment). The
> appendix adds OD22's text across versions and the v3.2 §4.5 disclosure it cites. v3.3 is a text amendment: any v3.2 text not restated applies unchanged. The bases (`D-shadow-gate-spec-v3.2.md`,
> v3.1, v3, v2) and the Defender files it cites are workstation-local under `l-data/swarm-m/` and are not in the
> repository; local paths in the body are illustrative.
>
> **Update when** a later spec version, an owner decision on OD22, or the host-run incidence for the `[N]` placeholder
> supersedes this text. Add a new dated file rather than editing this copy.

Swarm M Wave 2, spec author, 2026-10-06. **Spec only.** No gate code, no kernel code, no commits. Nothing here grants
run authority, lifts the live pause, or authorizes the O9 transfer (on HOLD). CONSOLIDATED §3 holds apply.

Sources, all read-only:
- in this folder: `D-shadow-gate-spec-v3.2.md` (the base; SHA-256 `e7359abef77cd3b583e772203688edc42142f972c872a93a0257b1ad5d7ce2ab`),
  `D-v3.2-defender.md` (GO-WITH-FIXES, F1-F3 plus the L5, MF-8 and §8.4 notes; SHA-256 `6658ceee…7fd807`),
  `D-shadow-gate-spec-v3.1.md` (SHA-256 `f0729884…8f29`), `WAVE2-RULES.md`;
- the shadow branch `codex/maker-shadow-runner-20261004` @ **`b31185d6b`** (`git show`): `src/weather/market/maker_shadow.py`
  `:196-240`, `src/maker_core/shadow/tape.py` `:121-142`;
- the build tree `C:\wt\workstation-chat\m-v2ro` @ `501f47579`: `weather/market/maker_plugin/universe.py:141-180`.

No data, panel, settlement, `data/`, `.env*` or credential file was read. No row for 2026-09-30..10-15 was read.

**Change note, 2026-10-07 (in-place text amendment, tag `[v3.3: D-1]`).** v3.2 §4.5 and OD22 described only defect 1 of the
clock/SWOB fix (supporting triggers dropped, lead-0 only). The SWOB unit's Defender fix round (`W2-SWOB-report.md`,
"Defender fix round", D-1; branch `claude/mrv2-fix-swob-time-parse-20261007` @ `8269807233e29f144d5e4242582501f53ec016c1`)
found that defect 2 (the `observed_at` raise) reached lead-1 minutes, i.e. scored `informed-v0` T+1 inputs; only the
supporting-pull part is T+0 only. §4.5 below adds the defect-2 sentence and OD22 (§9) points to it. The v1 incidence stays
an `[N]` placeholder until the host run of `tools/research/maker_clock_trigger_disclosure.py` (schema
`maker_clock_trigger_disclosure_v3`, field `events_old_clock_unavailable_observed_at`). Pre-amendment SHA-256 of this file:
`85edfe72a749d5ec4856ff98ff061e1218952918654d6efb29d7c8fa5653dcdb`. Nothing else changed.

---

## 0. How to read v3.3

v3.3 amends v3.2, which stays the base (v3.1, v3 and v2 remain its bases). Any v3.2 text not restated here applies
unchanged and is cited "v3.2 §x". Each change is tagged `[v3.3: Fn]`. A replaced v3.2 passage is void, and its replacement
is stated in full. The Defender asked for a spot-check of the changed paragraphs; all of them are in §1-§7.

| Tag | Defender item | v3.3 change | Section |
| --- | --- | --- | --- |
| F1 | MF-3 partial: the cross-side liveness rule fails honest nights | Each side is judged **alone** by run continuity across midnight. On a failed night the window from 00:00 to the first fresh state is excluded from the comparison, counted and capped. Mutants MD8-MD11 | §2 |
| F2 | MF-2 × MF-4: same-instant order at 00:00Z | Order reopen < derived < regular. "Latest in D" includes D's derived descriptors. One zoneinfo lead function. MD7 | §3 |
| F3 | MF-4 partial: the refresh changes shadow, replay and live | Attribution class A6; disclosure row C13 and a registration §4 amendment; refresh bound into the live executor (Tier L); MCF2-L; OD19 and OD22 updated | §4 |
| F4 | MF-9 note: whether a replacement exists at t′ is unstated | The 60 s replacement rule is evaluated at t′ | §5 |
| F5 | MF-8 residue: inline Kernel code at v3.2 line 246 | Paraphrased; the handout check catches inline quotes; v3.1/v3.2 inline redactions listed | §6 |
| F6 | §8.4 wording | "Binds" stated per mapping: A 96.5 %, B 57 % at 21 days | §7 |
| — | Defender's "no blocker for the work v3.1-D cleared" | Marked "can start now" section | §8 |
| D-1 (2026-10-07) | SWOB Defender D-1: defect 2 of the clock fix reached lead-1 minutes | Defect-2 sentence added to the v1-exam disclosure; OD22 points to it | §4.5, §9 |

---

## 1. Shared definitions `[v3.3: F1, F2, F3]`

These definitions are used by §2-§4 and replace every looser wording of the same notions in v3.2 §3.1 and §4.3.

- **Day-roll reader.** One bound module, `maker_core.replay.v2.day_roll` (owner U3, because it changes replay inputs; S1
  and TL import it, never copy it). It synthesises the **reopen records** (v3.2 §3.1) and the **derived local-midnight
  descriptors** (v3.2 §4.3). It is a pure function of a side's sealed records and the market time zones. Its module hash
  is in the cohort binding (`reopen_rule`), and TL binds it byte-identically into the live executor (§4.3).
- **`local_lead(market, target_date, instant)`.** The only lead function: `(target_date − instant.astimezone(zoneinfo(
  market.tz)).date()).days`, the same rule as the plugin's capture-time lead (`universe.py:149`). The lead-0 status of a
  reopen view and the `horizon_days` of a derived descriptor both come from it `[v3.3: F2]`.
- **Record classes within one logical instant** `[v3.3: F2]`: `reopen` (flag `reopen: true`), `derived` (flag
  `derived: "local_midnight"`), `regular` (everything written by a capture writer).
- **Latest of kind in D** `[v3.3: F2]`: the latest record of that kind for the condition over D's sealed tape (D's bundle
  for R_s) **together with D's derived records** (re-synthesised from that tape), ordered by instant and then by the class
  order of §3.

---

## 2. Day roll: each side judged alone `[v3.3: F1]`

### 2.1 What v3.2 got wrong

v3.2 §3.1 said "if either side fails the predicate, neither side gets reopen records". The live shadow ingests its reopen
set at 00:00 (v3.2 MD5). It cannot know then whether production's capture was continuous; it learns that only from the
bundle attestation days later. A capture restart across midnight (a `STALE_CODE` readoption, for example) would strip
reopen from R_s while the shadow's recorded D+1 decisions used it. B1 would then mismatch on an honest night. The 23:59:00Z
row requirement was also brittle: the shadow loop skips minutes whenever a step overruns 60 s (`maker_shadow.py:215-218`
@ `b31185d6b`), and the 00:00 rediscovery runs before that minute's row (`:222-231`).

The v3.2 §3.1 cell's paragraph "**Liveness predicate**" and its sentence "If either side fails the predicate, neither side
gets reopen records for D+1" are void. Replacement: §2.2-§2.5.

### 2.2 Per-side continuity predicate

A side is **continuous across the roll into D+1** iff all of the following hold. Each condition is knowable at
`D+1 00:00:00Z` from that side's own records, so the live shadow can evaluate it in real time and the reader re-evaluates
the same function later.

**Shadow side:**
1. The D tape and the D+1 tape carry the **same `run_id`** (`tape.py:124`, written into every journal's scope at `:130`).
2. The D tape was closed with reason **`utc_day_closed`** (the roll, `tape.py:139`), not `stop_file`, `interrupted` or a
   crash.
3. **No minute gap over N.** Take the `minute` rows of that run in `[D 23:50:00Z, D+1 00:00:00Z)`, and add the roll
   instant `D+1 00:00:00Z` as the final point. Every gap between consecutive points is ≤ **N = 180 s**. A skipped 23:59
   row, from a step that overran 60 s, therefore passes when the 23:58 row exists; there is no exact-23:59 requirement.

**Production side (R_s):**
1. The bundle attestation names **one capture run spanning `D+1 00:00:00Z`**, with no supervisor restart (including a
   `STALE_CODE` readoption) in `[D 23:50:00Z, D+1 00:00:00Z]`.
2. In the same window, no gap between consecutive book records of any compared condition exceeds N.
3. Absent run identity in the attestation = **not continuous**. This is never a FAIL; §2.3 handles it.

Calibration (10-13..15) may lower N; it may not raise it. N is frozen in the cohort binding.

### 2.3 Reopen per side

- A side that is continuous gets its reopen set for D+1. A side that is not continuous gets none. **Each side is judged
  alone.**
- The live shadow ingests its reopen set at 00:00 iff its own predicate holds at 00:00. The reader re-synthesises exactly
  that set for the re-drive (MD5, kept).
- The no-backdating rule is unchanged: reopen records are synthesised, never written (v3.2 §3.1; MD6 kept).

### 2.4 Comparison on a night where either side is not continuous

When both sides are continuous, nothing changes: the night is compared as in v3.2.

When **either** side is not continuous (a **broken night**):
- **Exclusion window.** B1, B3 and the stratum credit exclude every D+1 decision and condition-minute in `[D+1 00:00:00Z,
  T*)`. T* is the first instant at which, **for every compared condition**, both of these hold:
  1. **inputs:** for each of the six kinds, the latest payload SHA-256 is equal across the two sides;
  2. **state:** the two sides agree on resting legs, the decided and resume latches, `last_quote` while it is inside the
     60 s cooldown, and lots.

  The window is night-wide, not per condition, because the portfolio couples every condition in the wallet.
- **Counted.** The receipt records `reopen.continuity {shadow: bool, production: bool}`, `reopen.window_end` (T*), and
  `REOPEN_WINDOW_EXCLUDED` as both decisions and condition-minutes.
- **Not excluded:**
  - Tier A (self-replay, seal), B0/B0w and Tier I run over the whole day on each side. Each side is internally consistent
    under its own reopen set; the oracle uses the same per-side predicate.
  - Zero-tolerance checks (`secret_in_output`, Tier I) still apply inside the window.
  - Any B1 mismatch **at or after T*** is a FAIL as usual.
- **Caps (per day and per cohort).**
  - `T* − D+1 00:00:00Z ≤ 60 min`. Otherwise the day is `INCOMPLETE (reopen_window_cap)`, never FAIL. 60 min is
    provisional. Calibration measures each kind's first-fresh latency after midnight (info events and descriptors may be
    the slowest) and sets the value before the cohort. It is frozen in the cohort binding, and may later be lowered,
    never raised.
  - Over the cohort, `REOPEN_WINDOW_EXCLUDED` condition-minutes ≤ **1 %** of compared condition-minutes. Otherwise
    `NOT_MET (reopen_exclusion)`.
  - The count of broken nights is reported in the cohort summary.

### 2.5 Mutants `[v3.3: F1]`

| # | Mutant | Required outcome |
| --- | --- | --- |
| **MD8** | R_s not continuous (capture restart at 23:59:30Z), shadow continuous; the two sides differ only inside `[00:00, T*)` | Day is **not** FAIL. `REOPEN_WINDOW_EXCLUDED` > 0, T* is reported, and the B1 mismatches inside the window are excluded |
| **MD9** | As MD8, with T* at 01:15Z (75 min after midnight) | `INCOMPLETE (reopen_window_cap)` |
| **MD10** | As MD8, plus one planted B1 mismatch after T* | FAIL (the exclusion does not leak past T*) |
| **MD11** | Shadow loop skips the 23:59 row (a planted step overrun); same `run_id`, 23:58 row present | Predicate holds, reopen present, night compared normally (no exclusion) |
| MD6 `[kept]` | Writer down 23:58-00:20; a reopen record stamped 00:00 written at restart | Refused (a down writer never stamps 00:00). With F1, that side is not continuous and the night is a broken night |

---

## 3. Same-instant order at 00:00Z `[v3.3: F2]`

### 3.1 Order rule (replaces v3.2 §3.1 "Order")

Within any logical instant, records are ingested in this order, on both sides and in R_s and R_p:
1. trades (engine rule, `v2/engine.py:135-140`);
2. **reopen** records, by condition id, then by kind in the order `descriptor`, `book`, `terms`, `outcome_view`,
   `info_event`, `coverage`;
3. **derived** local-midnight descriptors, by condition id;
4. **regular** records, in their written order.

So at a market's local midnight a derived descriptor overrides a reopen descriptor of the same instant, and any regular
record of that instant overrides both.

**Why it matters.** For a market whose local midnight is exactly 00:00Z (London on GMT, from 2026-10-25), both a reopen
descriptor (the old horizon) and a derived descriptor (the new horizon) exist at `D+1 00:00:00Z`. If the reopen record
were last, the stale horizon-1 label would become `latest`, and v3.2 §4's window would reopen at 00:00Z.

### 3.2 Reopen and derived checks (replace v3.2 §3.1 "B0/B0w checks" (ii) and §4.3's acceptance sentence)

- **(i) Lead-0 reopen view.** It equals the canonical redaction value (v3.2 §3.1, unchanged). Lead 0 means
  `local_lead(…, D+1 00:00:00Z) = 0` (§1).
- **(ii) Every other reopen record.** Its payload SHA-256 equals that of the **latest of kind in D** (§1, which includes
  D's derived descriptors). Example: NYC's 04:00Z derived descriptor on D is the reopen descriptor's reference when no
  regular descriptor followed it in D.
- **(iii) A derived descriptor.** It equals the day-roll reader's function applied to the latest descriptor before it
  (captured, derived or reopen), with `horizon_days = local_lead(…)` at the derived instant.
- One `local_lead` serves (i) and (iii). There is no second time-zone computation anywhere in the gate.

### 3.3 Mutant `[v3.3: F2]`

| # | Mutant | Required outcome |
| --- | --- | --- |
| **MD7** | At `D+1 00:00:00Z` for a GMT market, the derived descriptor is ingested **before** the reopen descriptor | The fixture asserts that the stale (pre-midnight) horizon became `latest`; the ordering test fails on the mutant and passes on the rule. A companion fixture, with no mutant, asserts `latest.horizon_days` = the derived value |

---

## 4. The local-midnight refresh is a disclosed semantics change `[v3.3: F3]`

### 4.1 What changes

- At `b31185d6b` the shadow recomputes horizons only at rediscovery (`maker_shadow.py:222-231`). `m-v2ro` computes the
  lead only at capture (`universe.py:149-150`). Registration §4 says activity follows "the latest **captured**
  descriptor at or before t".
- v3.2 §4.3 makes the derived descriptor part of the shadow's live loop **and** of the reader that feeds R_s and R_p. So in
  `[local midnight, next captured descriptor)` (15-120 minutes):
  - `HORIZON_NOT_ELIGIBLE` and the eligibility of horizon-dependent paths now follow the new local date at local midnight
    instead of 15-120 minutes later;
  - a condition passing from lead 1 to lead 0 also takes the lead-0 view redaction from that instant on, since the view
    producer's lead and the descriptor's lead are now the same function.
- This is a replay-semantics change of the same kind as C11. It is attributed, disclosed and bound like C11.

### 4.2 Attribution class A6 (adds to v3.2 §1.4)

| Class | Change | Cause |
| --- | --- | --- |
| **A6** | Local-midnight refresh | The decision's inputs differ from the pre-change run **only** in `horizon_days`, or in the lead-0 view value that follows from it, because a derived descriptor exists at or before t and no captured descriptor has followed it |

- **Direct check** (v3.2 §1.4 rule 1, extended): `D_post` is compared with `decide()` on the same state using the latest
  **captured** descriptor's `horizon_days`. If they differ, the input difference must be of class A6 (or of A1-A3/A5 for
  the Kernel changes).
- **Cascade rule:** unchanged.
- **Ruling-independent.** The refresh is not part of OD19/OD20. Under (b) for both rulings, the re-run and attribute rule
  still applies, with A6 as its only class.
- **Run separation.** U3 may run the refresh as its own attributed re-run, before or after the Kernel edit. The two
  attribution reports are then cited separately.
- **Reopen class A7 (conditional).** The day-open re-emission only affects fresh per-day instances. If the registered
  exam's per-day reader also applies it, its changes are class A7 ("decision in `[00:00, first fresh)` that differs only
  through reopen-ingested inputs"), disclosed in C13's second sentence. If the exam reader does not use it, A7 does not
  arise.

### 4.3 Live binding (Tier L)

- The live executor's descriptor provider produces the same derived descriptor at each market's local midnight, by
  importing `maker_core.replay.v2.day_roll` byte-identically. It is part of v3.1 §4.4's binding set and of v3.2 §9.3's
  executed-code check.
- **New L-delta row:**

  | Delta | Paper | Live | Tier L gate |
  | --- | --- | --- | --- |
  | **L8 Local-midnight horizon** | Derived descriptor at each market's local midnight (§1, §3) | The same function in the live descriptor provider; a captured descriptor arriving later overrides it as on paper | Fixture: live at Eastern 04:00Z (EDT) and Pacific 08:00Z (PST) with a pre-midnight descriptor and a horizon-dependent decision in the window; live's `horizon_days` and decision equal paper's |

- **MCF2-L** (extends v3.2 MCF2): the live executor skips the refresh → the L8 differential fails, and live preflight
  refuses (binding mismatch on the day-roll module).

### 4.4 Disclosure and registration wording

- **Registration §4 amendment:** "activity follows the latest **captured or derived** descriptor at or before t. A
  derived descriptor recomputes `horizon_days` at each market's local midnight (time zone database rule) and is
  otherwise identical to the descriptor before it."
- **New disclosure row** (registration draft §3, "Changes from the signed exam"):

> | C13 | **Local-midnight descriptor refresh:** at each market's local midnight the engine's inputs carry a derived descriptor whose `horizon_days` follows the new local date; a later captured descriptor supersedes it | input-construction correction | Found by the shadow-gate review (2026-10-06): captured descriptors kept the previous day's horizon for 15-120 min after local midnight (rediscovery cadence), so horizon-gated decisions and the lead-0 boundary lagged the market's local date. Live parity: the live executor applies the same function. Not motivated by any outcome: no panel date had been read or run. | Horizon-gated decisions in `[local midnight, next captured descriptor)` differ from the frozen loop. If the exam's per-day reader applies the day-open re-emission, decisions in `[00:00, first fresh record)` of each UTC day differ too (class A7). |

- **Timing.** The day-roll reader and C13 must land before the 10-23 signature, like C11/C12. If they miss, OD25's
  options apply to C13 as well. There is still no automatic fallback.

### 4.5 v1-exam disclosure: clock defect 2 `[v3.3: D-1, 2026-10-07]`

v3.2 §4.5's reworded disclosure ("The trigger gap affects lead-0 conditions, including those still labelled horizon 1 by a
descriptor captured before local midnight, until the next descriptor") stays, and now covers **defect 1 only** (supporting
triggers dropped). The disclosure gains this sentence, and OD22's text carries it too:

> Defect 2 (an unparseable trigger `observed_at` raised before the point-in-time filter) made the event's clock unavailable
> for the whole UTC bundle day, which can include lead-1 minutes before local midnight; its v1 incidence is [N event-days,
> from the disclosure counter's `events_old_clock_unavailable_observed_at` on the allowed days 09-27..29 / expected 0
> because live producers write aware times].

- "Lead-0 only" and "no horizon-{1, 2} decision" must not be said of defect 2. The T+0-only claim holds for the
  supporting-pull part alone; the refusal fix can change T+1 inputs wherever a refused row exists.
- `[N]` stays a placeholder until the host run of `tools/research/maker_clock_trigger_disclosure.py` (schema
  `maker_clock_trigger_disclosure_v3`). Its host-run preconditions are unchanged: live trigger file only, allowed days
  only, output to a new file, lease held.

---

## 5. Tier L L5: replacement existence at t′ `[v3.3: F4]`

v3.2 §7's rule 2 is extended. Rules 1, 3 and 4 are unchanged.

> 2a. **Existence.** Whether live makes a replacement at all is decided **at t′**. A replacement exists iff, at t′, there is no previous QUOTE or `t′ − last_quote ≥ 60 s`, with `last_quote` the last QUOTE before the cancel. Otherwise the expected live outcome at t′ is `REQUOTE_COOLDOWN` and no placement. The next decision follows at the next wake, as v3.1 I13. Paper's existence at t is never the reference.
>
> 2b. **Sub-fixtures:**
> - (i) the 60 s condition holds at t and at t′ → both replace; rule 2 compares;
> - (ii) it fails at t and holds at t′ → paper has no same-instant replacement and live replaces at t′. **Expected**; counted as `L5_EXISTENCE_DIFFERS` in the Tier L receipt and disclosed under `PAPER_SAME_INSTANT_REPLACEMENT`;
> - (iii) it fails at both → no replacement on either side.
>
> Since t′ > t, "holds at t, fails at t′" cannot occur. A fixture asserting that case is a mutant (**ML4**) and must fail.

---

## 6. Oracle handout: inline Kernel quotes `[v3.3: F5]`

### 6.1 Paraphrase of v3.2 §4.1

v3.2 §4.1's second bullet is void. Replacement:

> - But the horizon that the Kernel and `decide()` use is the **captured descriptor's** `horizon_days`. The descriptor record payload carries it (`payloads.py:41,80`). The Kernel passes the latest descriptor record's horizon into the decision inputs (`kernel.py:524,534`). Registration §4 says activity follows "the latest captured descriptor at or before t", amended by C13 (§4.4) to "captured or derived".

v3.3 itself quotes no Kernel code outside the v3.2 Annex K, which remains U3-only.

### 6.2 The handout (replaces v3.2 §6's item list and its check)

The oracle author receives the following files. Each is produced by the coordinator's deterministic script, and each
file's SHA-256 goes in a manifest.

1. **v3.3 with §6.2 cut** (from its heading to the next `---`). That subsection is the coordinator's script specification and names the denied strings itself; the rest of v3.3 has no annex and no inline Kernel code.
2. **v3.2, cut before the line `## Annex K`** (line 614 of the file with SHA-256 `e7359abe…7ce2ab`), with these line
   substitutions:
   - line 149: "`value.book`" → "the Kernel's composed decision book";
   - line 246: replaced by §6.1's paraphrase;
   - line 555: "W2(a)'s guard against resting legs is an explicit `BundleError`, not an assertion".
3. **v3.1** (SHA-256 `f0729884…8f29`):
   - the two fenced blocks are redacted as v3.2 §6 says;
   - the G2 row's first cell (line 68) becomes: "After a replacement-reason CANCEL, the Kernel decides the replacement on
     the pre-cancel decision book with `existing = ()`, after its leg ledger has been cleared; so the cancelled size counts
     as competing liquidity and displayed depth";
   - lines 283-284 ("In `tick` …") become "The Kernel's frozen composition step is replaced by `C_book` of the latest
     public book and the resting legs";
   - `state.legs` on lines 187, 382 and 383 → "the resting legs".
4. v3 and v2 unchanged; `maker_core/contracts`, `maker_core/quoting/policy.py` and the 89a contract text, as v3.1.

**Check (extended).** Before the manifest is written, the script fails the handout if any handout file contains:
- a fenced `python` block;
- any of the strings `def compose_book`, `add_own`, `record_decision`, `replace(value`, `value.book`, `state.latest[`;
- a match of the regex `\bstate\.[a-z_]`;
- any backtick span that contains a `kernel.py` identifier from a deny list kept with the script (the Kernel's
  module-level and method names).

`policy.py` names are exempt, since `decide()` is handed out and declared common-mode. The check's own fixture plants
v3.2 line 246 unchanged, and the check must fail on it (mutant **MO1**).

The oracle PR records the manifest SHA-256, as v3.2.

---

## 7. §8.4 wording `[v3.3: F6]`

v3.2 §8.4's first bullet is void. Replacement:

> - **The pre-decided first-live cap (one band, minimum size, if real fills < 10) binds with P ≈ 57-96.5 % at 21 days**: 96.5 % under mapping A (E = 11) and 56.6 % under mapping B (E = 3). By window: A 100 %, 99.2 %, 96.5 % at 7, 14 and 21 days; B 93.7 %, 73.6 %, 56.6 %. "Almost surely" holds under mapping A only, which is the primary, deliberately conservative mapping.

The OD11 row is amended the same way (§9).

---

## 8. Work that can start now `[v3.3: marked section; from D-v3.1-defender "Conditions for GO" and D-v3.2-defender]`

These items depend on no open owner decision, and on none of F1-F3. Each goes through its unit's executor and Defender
under WAVE2-RULES, with fictional fixtures.

| Item | Spec owner text | Unit |
| --- | --- | --- |
| S1 barrier (§4.5 of v3) | v3 §4.5, unchanged | S1 |
| `maker_core.shadow.secrets` | v3.1 §4.8 as amended by v3.2 §5.2 (patterns, scan-before-write, transfer fail-closed) | S1 |
| B0w | v3 §6.2, v3.1 §2.2 pinned lead-0 value | S1 |
| The ratchets | v3.1 §4.8 rule 6 repository ratchet (v3.2 value-shape rule, no test allowlist); v3.1 §6.7 transitive import closure | S1 |
| U7 guard (MG-1) and its binding | v3.1 §2.1, §6.7 | U7 |
| The token mutants | v3.2 §5.3: MT1, MT1b, MT2, MT3 (each end alone), MT4, MT5, MT6, with run-time tokens | S1 |

**Waits:**
- The day-roll reader (§1-§4: reopen, derived descriptors, continuity predicate) waits for a spot-check of v3.3's
  changed paragraphs.
- The U3 Kernel edit and the oracle's I2/I12/I14 composition wait for the OD19/OD20 rulings.
- WU history in the bound set waits for WU-T (OD24).

---

## 9. Owner decisions (updated)

Unchanged from v3.2 §11: OD18, OD20, OD21 (scope extended below), OD23, OD24, OD25 and OQ-26, plus everything v3.2 lists
as unchanged.

| # | Decision | Recommendation |
| --- | --- | --- |
| **OD19** `[CHANGED — F3]` | As v3.2, plus: whatever the ruling, the gate also brings **C13 (the local-midnight descriptor refresh)**. It is attributed as class A6 in the same re-run discipline, disclosed in registration §3, and changes registration §4's "captured descriptor" to "captured or derived". | **(a)** as before. Rule C13 together with C11/C12, so registration §3 and §4 change once, before 10-23. |
| **OD22** `[CHANGED — F3]` | Record CF-1 off the critical path, conditional on the descriptor-horizon tripwire and on the local-midnight refresh. The refresh is a **disclosed engine-input change (C13)**, run identically in the shadow, the replay readers and the **live executor** (L8; TL binds the day-roll module). Disclosure as v3.2 §4.5 for defect 1, plus the defect-2 sentence of §4.5 `[v3.3: D-1, 2026-10-07]`: "Defect 2 (an unparseable trigger `observed_at` raised before the point-in-time filter) made the event's clock unavailable for the whole UTC bundle day, which can include lead-1 minutes before local midnight; its v1 incidence is [N event-days, from the disclosure counter's `events_old_clock_unavailable_observed_at` on the allowed days 09-27..29 / expected 0 because live producers write aware times]." | **Confirm.** |
| OD21 `[scope]` | TL also delivers L8 and the t′ existence rule (§5), and binds `maker_core.replay.v2.day_roll`. | **Yes**, as before. |
| OD11 `[CHANGED — F6]` | As v3.2. The first-live cap binds with P ≈ 96.5 % (A) / 57 % (B) at 21 days. | **Option 3 plus option 2 reported.** Keep the cap. Expect it to bind under A, and likely (more than even) under B. |
| **OD26** `[NEW — F1]` | Freeze the broken-night caps after calibration: N (≤ 180 s), the T* cap (provisional 60 min) and the cohort exclusion cap (1 %). | **Yes.** Set N and the T* cap from the calibration's measured first-fresh latencies. They can be lowered later, never raised. |

---

## Summary (10 lines)

1. v3.3 amends v3.2 with the confirmation Defender's F1-F3 and three notes, tagged `[v3.3: Fn]`; a "can start now" section lists the cleared work (S1 barrier, `secrets.py`, B0w, ratchets, U7, token mutants).
2. F1: each side is judged alone: same `run_id` across the roll, D tape closed by `utc_day_closed`, no minute gap over 180 s in 23:50-00:00. There is no exact-23:59 row, since the shadow loop skips overrun minutes.
3. On a broken night, B1/B3/stratum credit exclude `[00:00, T*)`, where T* is the first instant both sides agree on inputs and state for every condition. It is counted as `REOPEN_WINDOW_EXCLUDED` and capped (T* ≤ 60 min provisional; ≤ 1 % per cohort). Mutants MD8-MD11.
4. F2: the order within an instant is trades, reopen, derived local-midnight descriptor, regular. "Latest in D" includes D's derived descriptors, and one zoneinfo `local_lead` serves both the lead-0 reopen view and the derived horizon. MD7 added.
5. F3: the refresh is a disclosed semantics change: attribution class A6 (A7 conditional for reopen), registration row C13, registration §4 "captured or derived descriptor".
6. F3, live side: the refresh is bound into the live executor via the shared `day_roll` module, with Tier L delta L8 and mutant MCF2-L. OD19 and OD22 say so.
7. L5: whether a replacement exists is the 60 s rule evaluated at t′. "Fails at t, holds at t′" is an expected, counted `L5_EXISTENCE_DIFFERS`; the impossible case is mutant ML4.
8. MF-8 residue: v3.2 §4.1's inline Kernel quote is paraphrased. The handout lists every inline redaction in v3.1 and v3.2, and the check now catches inline Kernel identifiers and state-attribute quotes, not only fences (MO1).
9. §8.4: the first-live cap binds with P ≈ 96.5 % under mapping A and 57 % under mapping B at 21 days; "almost surely" applies to A only.
10. Owner decisions: OD19, OD22, OD21 scope and OD11 updated; new OD26 freezes the broken-night caps after calibration. The day-roll reader waits only for a spot-check of v3.3.

---

## Appendix (repository copy): OD22 text and the disclosure it cites

Copied verbatim from the workstation spec versions so the registration draft text is reviewable in one place. The
current text is the v3.3 row (§9 above) plus the §4.5 defect-2 sentence.

### OD22 across versions

| Version | # | Decision | Recommendation |
| --- | --- | --- | --- |
| v3.1 §11 | **OD22** `[NEW — M-CF, MA31-1]` | Record that CF-1 is off the gate's critical path and not a cohort dependency, with the tripwire test as the condition, and the v1-exam disclosure "lead-0 info events only". | **Confirm** (decided by master-agent; record it in the owner's log). |
| v3.2 §11 | **OD22** `[CHANGED — MF-4]` | Record CF-1 off the critical path, conditional on the tripwire over the **captured descriptor's horizon** (§4.2) and on the **local-midnight descriptor refresh** on both sides (§4.3). Disclosure: "lead-0 conditions, including those still labelled horizon 1 by a pre-midnight descriptor". | **Confirm**, with the refresh as an S1 deliverable before the cohort. |
| v3.3 §9 (current) | **OD22** `[CHANGED — F3]` | Record CF-1 off the critical path, conditional on the descriptor-horizon tripwire and on the local-midnight refresh. The refresh is a **disclosed engine-input change (C13)**, run identically in the shadow, the replay readers and the **live executor** (L8; TL binds the day-roll module). Disclosure as v3.2 §4.5 for defect 1, plus the defect-2 sentence of §4.5 `[v3.3: D-1, 2026-10-07]`: "Defect 2 (an unparseable trigger `observed_at` raised before the point-in-time filter) made the event's clock unavailable for the whole UTC bundle day, which can include lead-1 minutes before local midnight; its v1 incidence is [N event-days, from the disclosure counter's `events_old_clock_unavailable_observed_at` on the allowed days 09-27..29 / expected 0 because live producers write aware times]." | **Confirm.** |

### v3.2 §4.5 "Disclosure and P2" (verbatim; still applies, covers defect 1 only per v3.3 §4.5)

- The v1-exam disclosure (v3.1 §2.1, MA31-1) is reworded to: "The trigger gap affects **lead-0 conditions, including
  those still labelled horizon 1 by a descriptor captured before local midnight**, until the next descriptor." It must not
  say "no horizon-{1, 2} decision".
- OD22's text carries the same wording (§11).
- P2's FAIL rule (v3.1 §6.8) covers this window at run time. Its sentence "Under G7 this set is empty today" is amended to
  "empty today **only while production emits no observation events** (WU history is disabled, `model_sources.py:1017-1021`
  on `origin/master`)".
