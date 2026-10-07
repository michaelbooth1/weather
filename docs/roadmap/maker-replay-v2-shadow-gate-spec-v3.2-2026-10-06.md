# D — "Shadow agrees with replay" live gate: specification v3.2 (text amendment of v3.1)

> **Repository copy (2026-10-07).** Status: a **superseded base** of the maker replay v2 "shadow agrees with replay"
> live-gate specification, kept so that the current draft's citations resolve. **Superseded by
> [v3.3](maker-replay-v2-shadow-gate-spec-v3.3-2026-10-07.md)**, a text amendment: any v3.2 text that v3.3 does not
> restate still applies. It is a **draft for owner decision, not a signed registration**, and grants no run, live, merge or transfer
> authority. Owner item: [item 330](items/item-330-maker-economics-refocus-master-plan.md); current status of maker
> replay v2 lives in [the state of play](../operations/STATE_OF_PLAY.md), never here.
>
> **Read when** v3.3 cites a v3.2 section (§1.4, §3.1, §4, §6, §7, §8, §11 ...) and you need the text it does not
> restate. Read v3.3 first; where they differ, v3.3 wins.
>
> **Provenance.** The H1 and the text after this note are a copy of the workstation file
> `l-data/swarm-m/D-shadow-gate-spec-v3.2.md` (SHA-256 of the local file, the hash v3.3 cites as its base —
> `e7359abef77cd3b583e772203688edc42142f972c872a93a0257b1ad5d7ce2ab`; that local file already has LF line endings, so no
> CRLF restoration is needed), **except the redactions listed below, so the body is not verbatim.** The redacted text
> (the H1 plus everything after this note, LF) has SHA-256 `0847af8a3a14e67c9d603e2c09826ae112408a932649978632e4281f32e84299`.
> Local paths and sibling files named in the body are workstation-local; the v3.1 base has a
> [repository copy](maker-replay-v2-shadow-gate-spec-v3.1-2026-10-06.md).
>
> **Redactions (oracle clean room).** The oracle author's worktree is a checkout of this repository, so this copy follows
> the handout form of v3.3 §6.2 item 2 and carries no Kernel code:
> - Annex K (source lines 614-664, from the line `## Annex K` through the rule before the Summary; U3 only) is cut and
>   replaced by an explicit `[REDACTED …]` line. v3.3 §6.2 cuts everything from that line, but the 10-line Summary after
>   it (source lines 666-677) carries no Kernel code and is kept here;
> - source line 149: "the Kernel's `value.book`" → "the Kernel's composed decision book" (v3.3 names only the
>   backtick span; replacing just that would repeat "the Kernel's");
> - source lines 245-247 (§4.1's second bullet, which holds line 246) → v3.3 §6.1's paraphrase;
> - source line 555 → "W2(a)'s guard against resting legs is an explicit `BundleError`, not an assertion".
>
> References to Annex K elsewhere in the body (for example §6 and §9.1) are left as written; Annex K is not in the
> repository. v3.3 §6.2's substitutions, applied as written, leave two strings that its extended handout check denies:
> `def compose_book` and `add_own(` named in §6's own check sentence (source lines 460-461). They are names, not code,
> and are kept; the coordinator's handout script must still handle them.
>
> **Update when** never in place: this is a frozen base. A correction or a new version goes in a new dated file that
> v3.3's header and item 330 link.

Swarm M Wave 2, spec author, 2026-10-06. **Spec only.** No gate code, no kernel code, no commits. Nothing here grants
run authority, lifts the live pause, or authorizes the O9 transfer (on HOLD). CONSOLIDATED §3 holds apply.

Sources, all read-only:
- in this folder: `D-shadow-gate-spec-v3.1.md` (the base; SHA-256 `f0729884…8f29`), `D-v3.1-defender.md`
  (GO-WITH-FIXES, MF-1…MF-11, N1-N9; SHA-256 `5c451a9c…da0d`), `RE1-fill-reconciliation.md` (SHA-256
  `0d9d42e7793ba666d2775669f994579716ab57683e40ea4ecbc50f64a33a10d0`), `D-shadow-gate-spec-v3.md` §9.4 (the exposure
  base), `CONSOLIDATED.md` §5, `WAVE2-RULES.md`;
- the build tree `C:\wt\workstation-chat\m-v2ro` @ `501f47579`: `replay/v2/{kernel,engine}.py`, `replay/payloads.py`,
  `quoting/{policy,re1}.py`, `weather/market/maker_plugin/universe.py`;
- the shadow branch `codex/maker-shadow-runner-20261004` @ **`b31185d6b`**, read with `git show b31185d6b:<path>`
  (`src/weather/market/maker_shadow.py`). Its former worktree no longer exists; **every shadow citation in v3, v3.1 and
  v3.2 refers to commit `b31185d6b`** `[v3.2: N9]`;
- `origin/master` @ `2ee759c95`: `src/weather/model/source_adapters.py`, `src/weather/operations/observation_trigger.py`,
  `docs/operations/ESTABLISHED_FINDINGS.md` §10m, `docs/operations/FINDINGS_DIGEST.md` line 25;
- branch `claude/wu-token-leak-scan-20261007` @ `3455783db` (OD15 production token work): commit message, file list,
  `src/weather/operations/wu_token_scan.py` patterns, `docs/operations/HISTORY_DATA_DESIGN.md` diff.

No data, panel, settlement, `data/`, `.env*` or credential file was read. No row for 2026-09-30..10-15 was read.

---

## 0. How to read v3.2

### 0.1 Base and markers

v3.2 is a **text amendment of v3.1**, which stays the base (and v3, v2 remain its bases). Any v3.1 section, row or mutant
not restated here applies unchanged and is cited "v3.1 §x". Every change carries a tag `[v3.2: MF-n]` (a v3.1-Defender
must-fix) or `[v3.2: Nn]` (a v3.1-Defender note). A replaced v3.1 passage is void; the replacement is stated in full.

The Defender asked for a spot-check of the changed paragraphs, not a full round. Every changed paragraph is in §1-§10
below; nothing else in v3.1 moves.

### 0.2 Change index

| Finding | v3.1 text | v3.2 change | Section |
| --- | --- | --- | --- |
| MF-1 | §3.7.1(a): crossed check "unaffected" | Own-vs-public `CROSSED_BOOK` path named; G4 bounded; C11 effect column and OD19 text corrected; `OWN_LEG_CROSSED` diagnostic; fixtures MW3, MW3b, MW3c | §1.1-§1.3 |
| N1 | "Every pre-fix v2 output is void and must be re-produced" | **Re-run and attribute**: every changed decision traces to a named W1/W2 class or the re-run fails; estimand values change in every quoting arm, `clock_only` included | §1.4 |
| MF-10, N2 | (b) caps; "(b) applies by default" after 10-23 | Taint for `KED2_DIVERGENT` legs; KED rates measured before the ruling; no automatic fallback, explicit owner re-ruling (OD25) | §2 |
| MF-2 | Lead-0 reopen re-stamped, B0 checks identity | Lead-0 reopen checked against the canonical redaction value; MD1 scoped; MD1b, MD1c | §3.1 |
| MF-3 | Ordering, writer liveness, universe unspecified | Reopen records first in the 00:00 instant; synthesised by the reader, never backdated; universe from D's tape; MD4, MD5, MD6 | §3.1-§3.2 |
| MF-4 | Tripwire on "horizons 1, 2" | Tripwire on the **captured descriptor's** `horizon_days`; local-midnight window fixtures (EDT 04:00Z, PST 08:00Z, DST nights); local-midnight descriptor refresh; decoder `affects` check pinned; disclosure reworded | §4 |
| MF-5 | Production trigger loop out of scope | `source_adapters.py:172` and `observation_trigger.py:827` named as OD15 production work, owned on `claude/wu-token-leak-scan-20261007` (OD24); scope contradiction resolved; `fair_value.py:133` named | §5.1 |
| MF-6 | Patterns, write-then-scan, transfer fetch | `api[_-]?key` with `=`/`:`/`%3D`/`%3A`/`%253D`/`%253A`; scan in memory before the first write; transfer **fails closed** when the exact-token fetch fails | §5.2 |
| MF-7 | MT1-MT4 with placeholder tokens | Run-time generated tokens; placeholder exemption replaced by a value-shape rule; MT1b, MT5, MT6 | §5.3 |
| MF-8 | Kernel code in §3.7.1(a)/§3.7.2(a) handed to the oracle author | Code moved to **Annex K (U3 only)**; the oracle author receives a redacted handout, hash recorded in the oracle PR | §6, Annex K |
| MF-9 | L5: live replacement "equals" paper's same-instant replacement | Explicit rule: same records, `decide()` evaluated at the acknowledgement instant t′; time-invariant inputs compared separately; latency bounded | §7 |
| MF-11 | §9.4 placeholder | 5 = 4 at price + 1 strictly through; exposure recomputed through session 11; strictly-through n = 1; E[power] ≈ 23-30 % (mapping A, 21 d); the first-live cap almost surely binds | §8 |
| N3-N6 | — | `BundleError` instead of `assert`; hazard binds actual dates; executed-code binding; WU API body echo check | §9 |

---

## 1. W1(a): own-vs-public crossing, the corrected disclosure, and the re-run rule

### 1.1 §3.7.1(a) "Replay-semantics impact", third bullet — replaced `[v3.2: MF-1]`

The v3.1 bullet ("`no_bids`/`no_asks` now carry own size. Their reads in `decide()` are the crossed and off-tick checks
(unaffected …)") is void. Replacement:

- `no_bids`/`no_asks` now carry own size. `decide()` reads them in the off-tick check (unaffected: own legs are on
  tick), in `touch_buffer` for NO legs, and in the **crossed check** (`policy.py:239-246`: `max(bids) >= min(asks)` on
  `(yb, ya)` and on `(nb, na)` of the composed book).
- **Own-vs-own** crossing is impossible (`p_yes + p_no < 1`), and the own-vs-own touch distance is `d_yes + d_no ≥ tick`
  (G4).
- **Own-vs-public crossing is a new path.** Under the frozen rule, own size is only added at existing public levels, so
  it can never move a best bid or ask and can never cross the book. Under (a), a leg **creates** its level, and the public
  book record excludes paper orders. When the public book moves onto a resting paper leg **without a print strictly
  through it**, the composed book is crossed:
  - YES leg at p, public `yes_asks` best ≤ p → `(yb, ya)` crossed;
  - YES leg at p mirrored into `no_asks` at 1 − p, public `no_bids` best ≥ 1 − p → `(nb, na)` crossed;
  - NO leg at q mirrored into `yes_asks` at 1 − q, public `yes_bids` best ≥ 1 − q → `(yb, ya)` crossed.

  `decide()` then returns `CANCEL CROSSED_BOOK`. Blind RE-1's `observe` raises `crossed_book` on the same book
  (`re1.py:41-43`).
- **What the frozen loop did instead.** The same state gave `CANCEL TOUCH_BUFFER` (`min(ya) − p < tick`,
  `prices.py:33-34`, `policy.py:343`). `TOUCH_BUFFER` is in `REPLACEMENT_REASONS` (`kernel.py:41-42`), so the Kernel made
  a same-instant replacement. `CROSSED_BOOK` is **not** in that list. Under (a), therefore: cancel, no same-instant
  replacement, then the next wake (the 60 s cooldown end is not a wake source, v3.1 §6.3 I13), then a requote if
  eligible.
- **It is a paper-only state.** On the venue, an ask at or below a resting bid trades with it. Live would have been
  **filled at price**; four of RE-1's five fills were exactly this event (§8). Paper `strictly_through` records no fill,
  because no print went through the leg.
- G4 is restated: "(a) changes no `TOUCH_BUFFER` outcome between own legs. Where the **public** book touches or crosses
  an own leg (distance < tick), (a) changes `CANCEL TOUCH_BUFFER` plus a same-instant replacement into `CANCEL
  CROSSED_BOOK` without one."

### 1.2 `OWN_LEG_CROSSED` diagnostic `[v3.2: MF-1]`

- Definition: a recorded `CANCEL CROSSED_BOOK` (or a blind-RE-1 `crossed_book`) at which the **public** book alone is
  not crossed. It is the paper analogue of a live at-price fill.
- Counted per day on the shadow tape, R_s and R_p; reported in the receipt (`tier_i.own_leg_crossed`, §10). No verdict
  effect, no cap.
- S-REQUOTE yield falls by exactly these cases relative to the frozen engine; calibration (10-13..15) reports both.
- The oracle reproduces each one through `decide()` on its own `C_book` (I2, I14); no special case is written for it.
- Not adopted: making `compose_book` skip own size that would cross. That would invent a second non-venue rule.

### 1.3 C11 disclosure and fixtures `[v3.2: MF-1]`

The C11 row's last column ("Effect") in v3.1 §3.7.1(a) is replaced by:

> Policy behaviour differs from the frozen loop wherever a leg rests at a price without public liquidity, including the qualified mid and the HOLD/requote path. An own leg touched or crossed by the public book without a print now pulls `CROSSED_BOOK` (no same-instant replacement) where the frozen loop pulled `TOUCH_BUFFER` and replaced; on the venue that state is an at-price fill, which paper does not credit. The values of the registered estimands change in every quoting arm (informed-v0, blind_re1 and clock_only); their definitions do not. Not comparable with the frozen engine on those decisions.

New fixtures (a only; in the U3 Kernel tests and in the oracle conformance suite):

| # | Fixture | Required outcome |
| --- | --- | --- |
| **MW3** | Own YES leg resting at p; next public book record moves `yes_asks` best from p + 2 ticks to p; no trade print | Recorded `CANCEL CROSSED_BOOK` at that instant, legs cleared, **no** replacement at that instant; `OWN_LEG_CROSSED` = 1; the oracle reaches the same action and `reasons[0]` through `decide()` (I14) |
| MW3b | As MW3, but via the mirror: public `no_bids` best moves to 1 − p | Same as MW3 |
| MW3c | Own NO leg at q; public `yes_bids` best moves to 1 − q | Same as MW3 |
| MW3-frozen (b only) | MW3 run on the frozen Kernel | `CANCEL TOUCH_BUFFER` plus a same-instant replacement; the oracle classifies it `KED1_DIVERGENT` (this is the routine KED-1 case of §2.2) |

### 1.4 Re-running earlier v2 outputs: the "re-run and attribute" rule `[v3.2: N1]`

v3.1 §3.7.1(a) "Re-run obligations" stays (run-level digests such as decision SHAs and E7 are cumulative, so **every**
pre-fix artefact is re-produced). It is extended into a test of the edit's narrowness.

**Attribution classes** (the only allowed causes of a changed decision):

| Class | Ruling | Cause |
| --- | --- | --- |
| A1 | W1 | A resting leg at a price with no public level on its array (created level), including a qualified-mid move it causes (G3) |
| A2 | W1 | Own size on `no_bids`/`no_asks` (mirror), read by `touch_buffer` or the crossed check |
| A3 | W1 | Own-vs-public crossed book (§1.1; counted as `OWN_LEG_CROSSED`) |
| A5 | W2 | A same-instant replacement whose cancelled legs sat on, or created, a level of the pre-cancel book |

(Summing of same-outcome legs at one price is unreachable today: one leg per outcome in both profiles. Any change
attributed to it fails the re-run.)

**Rule.** For every fixture, ceiling run, calibration rehearsal and E7 digest that existed before the fix, the post-fix
run is produced and compared with the pre-fix run, decision by decision, aligned by (condition, instant, sequence):
1. **Direct check, at every post-fix decision.** The oracle's KED classifier (written for (b), reused here as a
   diagnostic) computes `D_frozen = decide()` on the **same** state with the frozen book (T1; T2 for a replacement). If
   `D_post ≠ D_frozen`, the book difference must be of class A1, A2, A3 or A5. Otherwise the re-run **FAILs**.
2. **Determinism.** An aligned pair with identical `DecisionInputs` (`input_hash` excluded) must have identical decision
   fields. Otherwise **FAIL**.
3. **Cascade.** An aligned pair whose inputs differ in fields other than the book (`existing`, `portfolio`,
   `last_requote_at`, `previous_fair_value`), and every decision present in only one run, must be preceded in the same run
   by a direct A-class difference (rule 1) at an earlier or equal instant. Portfolio fields couple conditions in one
   wallet, so a cascade may cross conditions. The first difference in each run must be direct. Otherwise **FAIL**.
4. The attribution report (counts per class, per arm, per artefact) is published with the re-produced artefacts and cited
   in C11's evidence.

**Estimands.** The fix changes no registered estimand's **definition** (registration §12: mean paired modelled net per
market/UTC-day). It changes its **value** in every quoting arm:
- informed-v0;
- blind_re1, whose composed book is the Kernel's composed decision book (G5); it moves toward RE-1 as actually run, because the
  pinned live `observe` read the venue book with own orders at any price (`re1.py:24-50`);
- **clock_only**, which calls `decide()` outside its pull windows on the same composed book.

C11's text (§1.3) names all three. Not changed: the hazard scalar (it counts public trade-occupied minutes, not engine
decisions, `calibration.py:150-197`), the v1 engine (`engine.py:415-420`) and the signed exam. No existing v2 test
compares v1 and v2 on own-leg books (the lockstep pair EngineV2/ReferenceEngine both inherit `tick`), so the attribution
rule is the only narrowness check; it is required.

---

## 2. (b) KED: taint, measured rates, and no automatic fallback `[v3.2: MF-10, N2]`

### 2.1 Taint for KED-2 divergent replacements `[v3.2: MF-10]` (adds to v3.1 §3.7.2(b))

- Under W2(b), live never runs T2. A `KED2_DIVERGENT` replacement places paper legs that live would not hold.
- **Rule.** Every leg placed by a `KED2_DIVERGENT` replacement is **tainted** from placement until it is cancelled or
  filled. A HOLD that keeps a tainted leg keeps the taint; a requote that replaces it ends the taint.
- No credit comes from a tainted leg: no stratum transition credit, no fill-cluster credit, no synthetic-fill credit
  (§9.4 option 3 injections onto a tainted leg are generated and checked but not counted).
- B1, Tier I and every zero-tolerance check still run on tainted legs: taint removes credit, never checking.
- Reported: tainted leg-minutes per day and the credits withheld (`tier_i.ked.ked2_tainted_leg_minutes`, §10).
- KED-1 needs no taint: live runs T1 too (byte-identical binding), so paper and live hold the same legs.
- Mutant **MKED5** (b only): a fill on a leg placed by a `KED2_DIVERGENT` replacement → no fill-cluster or stratum credit;
  the planted credit makes the test fail.

### 2.2 KED-1/KED-2 rates measured before the ruling `[v3.2: N2(i)]`

- W1 bites "on most quoting days" (v3.1 §3.7.1(a)), and every MW3-type state is a `KED1_DIVERGENT` decision under (b)
  (§1.3). So `KED1_DIVERGENT` may exceed its 2 % cap routinely. The caps can only be lowered, never raised.
- **Before OD19/OD20 are ruled**, U3 (with the oracle's classifier text, or a throwaway diagnostic written from §3.7.1(b))
  measures per day: `KED1_DIVERGENT` / record-driven decisions, `KED1_DIVERGENT` / QUOTE decisions, `KED2_DIVERGENT` /
  same-instant replacements and `KED2_DIVERGENT` / record-driven decisions, plus the tainted leg-minute share (§2.1).
- Inputs: fixture days built from workstation data dated **≤ 2026-09-29**, only if the coordinator's unit assignment
  explicitly allows that data (WAVE2-RULES); otherwise fictional fixture days, with that limitation stated. It is a
  replay, so it runs through the workstation queue or `workstation_heavy.ps1`, one run at a time.
- The numbers go into OD19/OD20's text. If the measured rate exceeds a cap on most days, OD19(b)/OD20(b) means "the
  cohort cannot reach MET", and the owner rules knowing that.

### 2.3 No automatic fallback to (b) at 10-23 `[v3.2: N2(ii)]`

v3.1 §3.7.1(a) "Timing", last sentence ("If it misses 10-23, (b) applies by default and the fix waits for a successor
registration") is void. Replacement:

- If OD19(a)/OD20(a) is ruled and the U3 fix has not landed on the build line by the 10-23 signature, **nothing changes
  automatically.** The coordinator raises OD25 (§11) the same day.
- OD25's options: (i) sign without the shadow-gate cohort depending on this registration until a successor registration
  carries the fix (cohort wait); (ii) slip the signature until the fix lands; (iii) an explicit owner re-ruling to (b),
  with §2.2's measured rates in front of the owner.
- Until OD25 is answered, no cohort starts and the oracle is not asked to carry T1/T2. This keeps §3.7.3's argument
  intact: the oracle encodes no defect unless the owner rules (b) explicitly.

---

## 3. Day roll `[v3.2: MF-2, MF-3]`

### 3.1 The "Day-open re-emission" row — replaced

v3.1 §3.3's row "Day-open re-emission" is void. Replacement:

| Behaviour | v3.2 contract rule | Control |
| --- | --- | --- |
| **Day-open re-emission** | **Who produces it** `[v3.2: MF-3]`. Reopen records are **synthesised by the reader** as a pure function of D's **sealed** tape (shadow) or D's bundle (R_s), and of the market time zones. They are **never written** to a tape or bundle afterwards, so nothing can be backdated. The live shadow's D+1 instance ingests the same function applied to its in-memory D records; test MD5 proves the in-memory set equals the function of the sealed tape.<br>**Liveness predicate** `[v3.2: MF-3]`. A side has reopen records for D+1 only if its writer was alive continuously through `D+1 00:00:00Z`: the side's D tape has a heartbeat `minute` row at `D 23:59:00Z` and its D+1 tape one at `D+1 00:00:00Z`, from the same writer session id with no restart in between (for R_s: the equivalent capture-session continuity in the bundle attestation; absent evidence = not continuous). **If either side fails the predicate, neither side gets reopen records for D+1.** The D+1 instance then pulls `MISSING_*` visibly on both sides until fresh records arrive, under v3's gap rules. A writer that was down at midnight never stamps anything at 00:00.<br>**Universe** `[v3.2: MF-3]`. Every condition with a `descriptor` record in D's tape (D's bundle for R_s). It does **not** depend on the 00:00 rediscovery, which can fail and keep the previous universe (`maker_shadow.py:229` @ `b31185d6b`). So the shadow and the exporter cannot differ.<br>**Content.** For each condition in the universe, the latest record of each of the six kinds (`descriptor`, `book`, `terms`, `outcome_view`, `info_event`, `coverage`) as of the end of D, at logical instant `D+1 00:00:00Z`, flagged `reopen: true`:<br>• **non-lead-0 kinds and views:** payload byte-identical to D's latest, payload clocks kept (`book.as_of_utc`, `terms.as_of_utc`, view `as_of_utc`, coverage `valid_until_utc`). A stale input stays stale at 00:00;<br>• **lead-0 `outcome_view`** `[v3.2: MF-2]`: the canonical §2.2 redaction value at the reopen instant, exactly `Unavailable(reason="lead0_not_in_gate_scope", as_of_utc=D+1 00:00:00Z, kind="out_of_scope")`. A condition is lead 0 at the reopen instant iff its target date equals the market's local date at `D+1 00:00:00Z`, computed with the market's `zoneinfo` time zone (this covers a market whose local midnight is exactly 00:00Z).<br>**Order** `[v3.2: MF-3]`. Within the instant `D+1 00:00:00Z`, **every reopen record precedes every regular record** of that instant, on both sides and in R_s and R_p. Reopen records are ordered by condition id, then kind in the order above. Trades are never re-emitted, and the engine ingests an instant's trades before its non-trade records (`v2/engine.py:135-140`), so a 00:00 print reaches a fresh instance with no legs. Because the last non-trade record ingested becomes `latest`, this order guarantees that a regular 00:00 record (the shadow's 00:00 minute belongs to D+1: `utc_day = minute.date()`, `maker_shadow.py:222` @ `b31185d6b`) overrides D's stale value, never the reverse.<br>**B0/B0w checks** `[v3.2: MF-2]`. A reopen record is accepted iff: (i) lead-0 `outcome_view`: it equals the canonical redaction value above (`reason`, `kind = out_of_scope`, `as_of_utc = D+1 00:00:00Z`); (ii) every other reopen record: its payload SHA-256 equals that of the latest record of its kind for that condition in D's tape (D's bundle for R_s). Otherwise the day is refused as v3.1 (MD1, MD1b).<br>**Carry-state engines** (R_p over several days) see the re-emission as an unchanged re-send: no wake under rules 1, 3 and 4. A lead-0 view re-stamp moves only `as_of_utc`, which is excluded from rule 4. R_p's decisions are unchanged (MD2). | Kx8, MD1, MD1b, MD1c, MD2, MD4, MD5, MD6 |

The "Day open" row and the "Terms seeding" row of v3.1 §3.3 stay `[v3.1 KEPT]`. The gate-purpose exporter applies the
same synthesis function (it is one bound module used by both readers), so R_s and the shadow re-drive cannot differ by
construction; v3.1 §5's "the gate-purpose exporter emits the day-open re-emission" now reads "the gate-purpose reader
synthesises the day-open re-emission".

### 3.2 What stays visible, and what does not `[v3.2: MF-3]`

- No double counting: trades are not re-emitted; `trades_seen`, lots and latches are fresh; re-armed timers coalesce per
  instant; `changed()` only updates running totals (`v2/engine.py:207-215`).
- Clocked kinds (book, terms, view, coverage) keep their payload clocks, so a gap stays visible at 00:00.
- `descriptor` and `info_event` carry no staleness clock. A missed late-D observation read is therefore invisible at
  00:00. It is visible in P3/P4, and lead 0 is excluded from B3. Accepted and disclosed here.

### 3.3 Mutants `[v3.2: MF-2, MF-3]` (MD1 rescoped; the rest new)

| # | Mutant | Required outcome |
| --- | --- | --- |
| MD1 `[rescoped]` | **Non-lead-0** reopen record with a re-stamped payload `as_of` | B0/B0w refuse (payload SHA differs) |
| **MD1b** | Lead-0 reopen view with `kind ≠ out_of_scope`, or `as_of_utc ≠ D+1 00:00:00Z`, or a different `reason` | B0/B0w refuse |
| **MD1c** | Lead-0 reopen view byte-identical to D's last redaction (its `as_of` inside D) | B0/B0w refuse (not the canonical value) |
| **MD4** | A reopen record placed **after** a regular 00:00 record of the same condition and kind | The fixture asserts the stale D value became `latest`; the ordering test fails on the mutant and passes on the rule |
| **MD5** | The live shadow's in-memory reopen set differs from the reader's synthesis of the sealed tape by one record | Test fails |
| **MD6** | Writer down from 23:58 to 00:20; a reopen record stamped 00:00 is written at restart | Refused: no side passes the liveness predicate, so no reopen record may exist; B0 refuses the planted record and D+1 shows `MISSING_*` pulls on both sides |

---

## 4. CF-1 tripwire: the captured descriptor's horizon `[v3.2: MF-4]`

### 4.1 Why "horizon 1/2" must be the descriptor's label

- The clock's date rule is sound: it creates observation events only when the detection and observation local dates equal
  the target (`clock.py:72-74`).
- But the horizon that the Kernel and `decide()` use is the **captured descriptor's** `horizon_days`. The descriptor record payload carries it (`payloads.py:41,80`). The Kernel passes the latest descriptor record's horizon into the decision inputs (`kernel.py:524,534`). Registration §4 says activity follows "the latest captured descriptor at or before t", amended by C13 (§4.4) to "captured or derived".
- The descriptor's lead is computed at capture from the local date (`universe.py:149`), and the shadow recomputes it only
  at rediscovery: every `rediscover_minutes` (default 15, bounds 1-120) or at a **UTC** day change (`maker_shadow.py:79,
  222-224` @ `b31185d6b`). So for 15-120 minutes after **local** midnight, a local-today condition is still labelled
  horizon 1, active and eligible.
- The 05:00-08:00Z maintenance exclusion does not cover every local midnight. Using 2026 dates (US and Canadian DST ends
  Sunday 2026-11-01, 02:00 local):

  | Zone | Local midnight in daylight time | In standard time | Exposed window outside maintenance |
  | --- | --- | --- | --- |
  | Eastern (NYC, ATL, MIA, Toronto) | 04:00Z | 05:00Z (inside) | Every local midnight up to and including the one that starts local 11-01 (2026-11-01T04:00Z) |
  | Central | 05:00Z (inside) | 06:00Z (inside) | none |
  | Mountain | 06:00Z (inside) | 07:00Z (inside) | none |
  | Pacific | 07:00Z (inside) | 08:00Z | Every local midnight from the one that starts local 11-02 (2026-11-02T08:00Z) |

  The table assumes the maintenance window is `[05:00, 08:00)Z`; the fixtures cover 07:59Z and 08:00Z, so either reading
  is tested. Both exposed windows fall in the calibration and cohort period.
- Toronto's routine report minute is :00 (`clock.py:15`), so a Toronto trigger can land exactly at local midnight.
- `detect_observation_triggers` fires `wu_history_high_increased` whenever the previous history high is `None`
  (`observation_trigger.py:437`), for example after a failed poll. A new-high or decided event can therefore reach a
  horizon-1-**labelled** condition inside the window. `DECIDED` and `INFO_PULL` precede `HORIZON_NOT_ELIGIBLE` in
  `decide()` (`policy.py:255-260`).
- A second route: the Kernel's resume-latch check reads every event of the latest `info_event` record without an
  `affects` filter (`kernel.py:513`). Only the decoder's per-condition check (`payloads.py:127-128`,
  `BundleError("event_identity_mismatch")`) keeps a foreign event out of a condition's record.

### 4.2 v3.1 §2.1 "Tripwire test" — replaced

- **Predicate.** The tripwire (`tests/maker_core/test_observation_scope.py`) asserts that, for every plugin-clock event,
  `affects ∩ {conditions whose latest captured descriptor at the event's detection instant has horizon_days ∈ {1, 2},
  and which are active at that instant}` is empty, **or** that every such condition is covered by a local-midnight
  descriptor refresh (§4.3) at or before that instant.
- **Fixtures** (all with `zoneinfo`, never fixed offsets):
  - a descriptor captured before local midnight, and a trigger detected 0, 1, 15, 60 and 120 minutes after local
    midnight, with no rediscovery in between;
  - Toronto at local 00:00 (minute 0); Eastern at 04:00Z on 2026-10-31 and 2026-11-01 (EDT); Eastern at 05:00Z on
    2026-11-02 (EST, inside maintenance, still asserted); Pacific at 07:00Z on 2026-11-01 (PDT) and 08:00Z on 2026-11-02
    (PST), plus 07:59Z and 08:00Z;
  - the DST night itself: local date 2026-11-01 has 25 hours; the fixture asserts that the lead and the refresh instant
    come from the local date, not from UTC-day arithmetic;
  - a trigger whose previous WU history high is `None`;
  - per source, local dates D−1, D, D+1, and a detection/observation date mismatch (v3.1's set, kept).
- If CF-1 or any later change widens `affects` or the date rule, the test fails, P4 returns as `REFUSED` by rule, and the
  observation channel becomes a cohort dependency again (v3.1 rule, kept).

### 4.3 Closing the window: local-midnight descriptor refresh (required, S1)

- Of the Defender's two options, (ii) "assert no such trigger can occur before the next descriptor" is not provable, so
  **(i) is the rule**.
- At each market's local midnight (computed with `zoneinfo`), both sides produce one `descriptor` record for every
  condition of that market whose latest descriptor was captured before that instant. It equals the latest descriptor
  except `horizon_days`, recomputed by the plugin's lead rule (`universe.py:149`) for the new local date, and it is flagged
  `derived: "local_midnight"`. A condition whose new lead is outside 0..2 gets no refresh (it is not in scope).
- **Symmetric by construction:** the refresh is synthesised by the same bound reader function as §3.1, on the shadow tape
  and on the bundle. B0/B0w accept a `derived` descriptor iff it equals that function applied to the prior descriptor.
- Descriptor changes are not wake sources (v3.1 I13), so the refresh adds no wake; it changes the horizon read at the
  next wake. The shadow's live process applies the same function at local midnight, so its live decisions match the
  re-drive.
- Mutant **MCF2**: refresh skipped on one side → a horizon-1-labelled condition decided after local midnight → B1 mismatch
  at the first wake after the refresh instant.

### 4.4 Decoder `affects` check pinned

- Test `test_shadow_events_decoded_through_payloads`: an `info_event` record whose event's `affects` lacks the record's
  condition must raise `BundleError("event_identity_mismatch")` **both** in the replay bundle path and in the shadow's live
  ingestion path (`maker_core.shadow.live_kernel`). The test asserts the live path calls the `payloads` decoder (or an
  equivalent check bound in the cohort hash).
- Mutant **MCF1**: the shadow's live ingestion bypasses `payloads` decoding → the test fails.

### 4.5 Disclosure and P2

- The v1-exam disclosure (v3.1 §2.1, MA31-1) is reworded to: "The trigger gap affects **lead-0 conditions, including
  those still labelled horizon 1 by a descriptor captured before local midnight**, until the next descriptor." It must not
  say "no horizon-{1, 2} decision".
- OD22's text carries the same wording (§11).
- P2's FAIL rule (v3.1 §6.8) covers this window at run time. Its sentence "Under G7 this set is empty today" is amended to
  "empty today **only while production emits no observation events** (WU history is disabled, `model_sources.py:1017-1021`
  on `origin/master`)".

---

## 5. Secret hygiene `[v3.2: MF-5, MF-6, MF-7]`

### 5.1 Production error paths: OD15 production work with a named owner `[v3.2: MF-5]`

**The two production paths** (`origin/master` @ `2ee759c95`):
- `src/weather/model/source_adapters.py:172` stores `"error": str(exc)` for any source fetch failure. Through
  `source_status()` (`observation_trigger.py:256-265`) and `observation_state_from_sources` (`:318-319`), that text lands in
  the `previous_observation`/`current_observation` of every trigger context (`:541-557`) and in the diagnostics JSONL
  (`:860-865`).
- `src/weather/operations/observation_trigger.py:827` stores `f"{type(exc).__name__}: {exc}"` per market; it reaches
  `status.json` `last_error` (`:831`) and `poll_results`.
- Once WU history runs through the page-backed client, a requests `HTTPError` text carries `…?apiKey=<token>`. Unchanged,
  the capture host would persist the token (breaking OD15 outside the gate), and every transfer package for a day with one
  WU API error would be refused by §4.8 rule 4: a predictable REFUSED stream.

**Owner and branch.** This is **OD15 production work**, owned by the executor of branch
**`claude/wu-token-leak-scan-20261007`** (OD24 names it as unit **WU-T** and asks the owner to confirm). At `3455783db` that
branch has landed, roll-free:
- `weather.sources.wu_redaction` (`redact_wu_secrets`, `sanitize_exception` over the exception chain and request/response
  URLs, `pin_http_debug_loggers`);
- `weather.operations.wu_token_scan` (a read-only scanner; paths, per-pattern counts and offsets only);
- the non-loop redaction points (`daily_refresh_source_steps`, `historical_backfill_runner`).

Its commit states it touches **no file in a capture-loop import closure**, so `source_adapters.py:172` and
`observation_trigger.py:827` are **not yet converted**. Converting them is roll-sensitive; it merges only through the
quiet-window path with the verdict from `scripts\ops\roll_verdict.ps1` (AGENTS.md).

**Precondition (amends v3.1 §4.1 "Info events" row).** WU history is in the bound observation-source set on both sides
only after WU-T has landed on `origin/master`:
1. `source_adapters.py:172` and `observation_trigger.py:827` (and the `:860-865` diagnostics row) persist §4.8 rule 2 codes
   (or `sanitize_exception`-cleaned text whose residue passes §5.2's scanner, if WU-T chooses that), never raw `str(exc)`;
2. `pin_http_debug_loggers` runs in the trigger loop process at start, and the `debuglevel` check of MT6 (§5.3) runs
   before every WU fetch;
3. a WU-T test plants a token-bearing `HTTPError` through each of the two paths and asserts that `status.json`, the trigger
   rows and the diagnostics JSONL pass the §5.2 scanner.

Until then WU history is off on **both** sides (never one side only, v3.1 §4.1), and P4 reports it.

**Scope contradiction resolved** (replaces v3.1 §4.8's "Scope note" and its sentence "The production trigger loop and the
gate-purpose exporter use the same module on the capture host"):
- Rules 2 and 5 bind production's trigger loop **through WU-T's change**, which uses `weather.sources.wu_redaction`. The
  gate's `maker_core.shadow.secrets` module may wrap the same helper but does not require production to import
  `maker_core`.
- The gate-purpose exporter and the transfer tool use `maker_core.shadow.secrets`.
- Rule 4 (the transfer scan at both ends) stays the backstop for anything production persists.

**Named, not converted.** The bound plugin's free-text path `fair_value.py:133` (`Unavailable(str(exc) …)`, persisted as the
view `reason` and hashed into `view_state`) is listed next to G9's two shadow paths (`maker_shadow.py:151`, `:292` @
`b31185d6b`, which **are** converted). It is unreachable by WU today, because fair value reads NBP bulletins; converting it
would change decisions (the `reason` is in `view_state`), so it is named, not converted, and the seal scan backstops it.

### 5.2 Scanner patterns, scan-before-write, and transfer liveness `[v3.2: MF-6]`

**Rule 3 "the scan looks for" — replaced.**
- **Exact tokens:** every value in the in-memory token set, raw, URL-encoded (`quote`, `quote_plus`), double-URL-encoded,
  JSON-escaped and HTML-escaped.
- **Structural patterns**, on bytes, case-insensitive:
  - a key name `api[_-]?key`, optionally wrapped in a quote (`"`, `'`, backslash-escaped, `&quot;`, `&#34;`, `&#x22;`,
    `&q;`);
  - then optional whitespace and one separator of `=`, `:`, `%3D`, `%3A`, `%253D`, `%253A` (hex case-insensitive);
  - then optional whitespace and an optional quote;
  - then a **token-shaped value**: 16-128 characters of `[A-Za-z0-9]`.

  This covers `apiKey=<tok>`, `'apiKey': '<tok>'` (a params-dict repr), `"apiKey": "<tok>"` (JSON), `API_KEY = '<tok>'`, the
  page's `"API_KEY":"<tok>"`, and single and double URL encoding. Add the "32 hex characters within 64 bytes after an
  `api[_-]?key` name" pattern of `wu_token_scan.PATTERNS["hex32_near_apikey"]` (`3455783db`).
- **Value-shape rule replaces the placeholder exemption.** The literal exemption of `<page-token>` and `<redacted>` is void:
  those strings are not token-shaped, so they never match. Nothing else is exempt.
- **Conformance with WU-T's scanner.** A test runs §4.8's pattern set and `weather.operations.wu_token_scan.PATTERNS` on one
  run-time-generated corpus and requires that every WU-T hit is also a §4.8 hit. (At `3455783db`, WU-T's patterns lack the
  `%3A`, `%253D`/`%253A` and `api-key` forms; that is reported to WU-T, not fixed here.)

**Rule 3 "the writer writes to a temporary file … then scans" — replaced (scan before write).**
- The sealed writer scans the **serialised bytes in memory before the first byte reaches disk**.
- Appended tapes: each record is scanned before it is appended (a token cannot straddle a JSON line); the whole file is
  scanned again at seal.
- Temporary files exist only for atomic rename and are written only from bytes that passed the scan. A crash can
  therefore leave only clean bytes; the transfer tool never picks up temporary names (`*.sealing-tmp`).
- On a hit nothing is written. The "truncate and remove" clause is void (there is nothing to remove). `REFUSED
  (secret_in_output)` with the path class and pattern id, never the matched bytes, plus the alert, as v3.1.
- Scheduled-task stderr capture (rule 5) is a stream the gate cannot pre-scan; it stays scanned at rotation, and MT5/MT6
  (§5.3) keep the token out of it at the source.

**Rule 4 addition (fails closed when the exact token cannot be fetched).**
- The structural scan always runs at both ends.
- If an end's exact-token page fetch fails (any `page_*` code), the transfer **fails closed**: the package is not sent (send
  end) or not unpacked or read (receive end; it stays in the receive quarantine). It is **deferred**, retried at most hourly,
  and `transfer_scan_token_unavailable` is recorded with the enumerated failure code.
- It is never sent without the exact-token scan, and it is never refused permanently for this reason.
- A day still without a completed scan when the seven-day rule evaluates its window counts `INCOMPLETE
  (transfer_scan_token_unavailable)`, not `REFUSED` (§10).

### 5.3 Mutants `[v3.2: MF-7]` (replaces v3.1's MT1-MT4 rows; adds MT1b, MT5, MT6)

**Run-time tokens.** Every token mutant generates its token at run time (`secrets.token_hex(16)`, 32 hex characters,
token-shaped). It inserts the token into the in-memory token set or into the stubbed page fetch, and assembles the page,
URL, row or exception **in memory**. No literal token value is ever in a tracked file, so the repository ratchet (rule 6)
holds without allowlisting. **Test files are never allowlisted in the ratchet.** Outputs go under the test's own
`--basetemp`, which the queue removes. No network: the page fetch is stubbed.

| # | Mutant | Required outcome |
| --- | --- | --- |
| **MT1** | A page body carrying `"API_KEY":"<run-time token>"` handed to the input-store writer | Sealed writer refuses before any byte is written: `REFUSED (secret_in_output)`, pattern id recorded |
| **MT1b** | A page body with **no** token (the `page_token_not_found` case) handed to the input-store writer | Refused by the input-store writer's page-body sniff (an HTML document marker, `<html`, or the page runtime `const data` / `API_KEY` block): `REFUSED (secret_in_output)` with pattern id `page_body`. Rule 1 is enforced even when no token is present |
| **MT2** | `input_gap` row built from `str(HTTPError)` whose URL holds the run-time token | Refused at seal (exact-token and structural hits) |
| **MT3** | Run-time token planted in a production trigger row inside a gate-purpose package | Two runs: send-end scan alone (receive end disabled) refuses; receive-end scan alone (send end disabled) refuses. Each end is proved independently |
| **MT4** | `urllib3` logger left at DEBUG in the shadow | Process refuses to start |
| **MT5** | An uncaught `HTTPError` whose URL holds the token reaches the replaced `sys.excepthook` (and `threading.excepthook`) | The captured stderr holds only the class name, the enumerated code and redacted frames (file:line); the scanner finds nothing |
| **MT6** | `http.client.HTTPConnection.debuglevel = 1` (also `HTTPSConnection`) set after start; it prints the request line through `print`, bypassing logging | The pre-fetch check refuses: no fetch is made and the process exits with an enumerated code. The logger pins and both `debuglevel` values are re-checked **before every fetch**, not only at start |

---

## 6. The oracle author's redacted handout `[v3.2: MF-8]`

- **Annex K (U3 only).** The two verbatim code blocks of v3.1 (§3.7.1(a) `compose_book`, §3.7.2(a) the replacement code)
  are moved to Annex K of this document and are addressed to U3 only. In v3.1 they are void for every other reader. Annex K
  also carries N3's change (§9.1).
- **The handout.** The oracle author (v3.1 §6.3 "Physical clean room", item 2) receives a redacted handout instead of "this
  spec":
  1. this document **without Annex K** (everything after the Annex K heading cut);
  2. v3.1 with its two fenced `python` blocks (lines 255-281 and 373-380 of the file with SHA-256 `f0729884…8f29`) each
     replaced by the line `[REDACTED: Annex K, U3 only — see the table and the semantics sentence above]`;
  3. v3 and v2 unchanged (v3 has no code block; v2's only block is the day-receipt schema);
  4. `maker_core/contracts`, `maker_core/quoting/policy.py` (`decide()`, declared common-mode) and the 89a contract text,
     as v3.1.

  §3.7.1(a)'s table and semantics sentence, T1/T2's text and §6.3's I-rules are sufficient to implement `C_book` and
  `R_book`.
- **Not handed out:** the Defender reviews (`D-v3-defender.md`, `D-v3.1-defender.md`), which quote Kernel lines; Annex K;
  any `kernel.py` excerpt.
- **Production and proof.** The coordinator produces the handout with a deterministic script (cut at the Annex K heading;
  replace the two v3.1 blocks by line range after checking the source file's SHA-256). It writes a manifest of each handout
  file's SHA-256. A check asserts that no handout file contains a fenced `python` block or the strings `def compose_book`
  or `add_own(`.
- The **oracle PR description records the handout manifest's SHA-256**, and the oracle branch's first commit (the deletion
  commit, v3.1 §6.3 item 1) is unchanged.
- The `ORACLE_SPEC_DERIVED_FROM_KERNEL` label stays: the handout removes the code, not the transcribed design.

---

## 7. Tier L L5: an explicit rule `[v3.2: MF-9]`

v3.1 §4.4's L5 "Tier L gate" cell is void. Replacement:

> Fixture differential, with no other record between the cancel at t and its acknowledgement at t′ > t:
> 1. **Inputs (time-invariant fields).** The live replacement's `DecisionInputs` equal paper's same-instant replacement inputs in every field except `now` and the fields derived from it: `book` (= `R_book` of the same public record; under (b), the T2 book for comparison per §3.7.2(b)), `terms`, `fair_value`, `portfolio` (post-cancel), `existing = ()`, `horizon_days`, `events`, `profile`, `hazard_per_minute`, `last_requote_at`, `previous_fair_value`.
> 2. **Decision (explicit rule).** The live replacement equals `decide()` on the oracle-composed `R_book` of the same records, **evaluated at t′**, on `action`, `reasons` and legs (price, size, outcome). It is not compared with paper's decision at t: `decide()` changes with time alone (`sigma_eff` grows with view age, `policy.py:280-290`; `BOOK_STALE_OR_FUTURE` after 10 s, `:232`; the Kernel's 60 s replacement condition).
> 3. **Latency bound.** A separate assertion bounds the modelled acknowledgement latency `t′ − t` used by the fixture (its value is a fixture parameter, reported in the Tier L receipt). A sub-fixture with `t′ − t` = 0 checks that rule 2 then also equals paper's same-instant replacement.
> 4. Under (b), rule 2 compares with `D_ruled` at t′ (the KED-2 counterpart). Venue rejections and partial placement as v3.

---

## 8. Fill evidence: reconciled counts, recomputed exposure and power `[v3.2: MF-11]`

v3.1 §9.4's "RE-1 fill count: PENDING RECONCILIATION" block, its "Illustration only, provisional" bullet and the
placeholders are void. Replacement:

### 8.1 Reconciled counts (from `RE1-fill-reconciliation.md`)

- `RE1_FILLS_TOTAL = 5`, `RE1_FILLS_AT_PRICE = 4`, `RE1_FILLS_STRICTLY_THROUGH = 1`.
- Unit: **fill events**. Session 11's five trades in one second are one event, as paper makes one fill per leg.
- Classifier: the 89a strictly-through rule (a print beyond our price on our token, or beyond `1 − p` on the complement).
  - Fills 1, 3 and 4 were partial, so at price by construction.
  - Fill 2 (Miami 09-24) was full, but its deepest maker leg was at our price.
  - Fill 5 (session 11, Chicago 68-69°F Sep 25) printed its last trade at 0.42 against our 0.43: the only strictly-through
    event.
- The primary record is the RE-1 campaign root (`terminal_trades` rows with an own maker `order_id`); fills 1-4 agree with
  92a's frozen table. `FINDINGS_DIGEST.md` line 25 on `origin/master` @ `2ee759c95` still says "four fills"; the correction
  is the reconciliation's own deliverable, not this spec's.

### 8.2 Exposure recomputed through session 11

v3's E counted sessions 1-8 only (mapping A: 8 sessions; mapping B: the 2 UTC days 09-23 and 09-24; Jeffreys means
3.94/15.75 at 7 days are `4.5 × 7/8` and `4.5 × 7/2`). n = 5 includes session 11, so E must include sessions 9-11
(attempts 10-12):

| Mapping | E (sessions 1-11) | E (sessions 1-10, without session 11's regime) |
| --- | --- | --- |
| A: one session ≈ one shadow quoting day | **11** (10 if session 10, lost to post-read lag, had no quoting exposure) | 10 |
| B: sessions ≈ the UTC days they ran | **3** (09-23, 09-24, 09-25) | 2 (if session 10 ran on 09-24; 3 if on 09-25 — not established here) |

Session 11 ran under the depth rule on a contested band (EF §10m), a different regime from sessions 1-8's thin bands. The
rate is reported with and without it.

### 8.3 Projection (q = 10 %, `E[power] = 1 − (1 + q·t/E)^−(n+0.5)`; expected count in parentheses)

The formula is the Gamma-Poisson mixture with the Jeffreys posterior `Gamma(n + 0.5, E)` (method unchanged). The relevant
n for **real `strictly_through` paper fills is 1**, not 4 or 5.

**Strictly through (real counted fills under `strictly_through`):**

| Window | A, E = 11, n = 1 | A, E = 10, n = 1 | A, without s11 (E = 10, n = 0) | B, E = 3, n = 1 | v3's E (A = 8), n = 1 |
| --- | --- | --- | --- | --- | --- |
| 7 d | 9 % (1.0) | 10 % (1.1) | 3 % (0.3) | 27 % (3.5) | 12 % (1.3) |
| 14 d | 16 % (1.9) | 18 % (2.1) | 6 % (0.7) | 44 % (7.0) | 21 % (2.6) |
| 21 d | **23 % (2.9)** | 25 % (3.1) | 9 % (1.1) | 55 % (10.5) | 30 % (3.9) |

**At price (the option 2 `at_price` re-drive, n = at price + through):**

| Window | A, E = 11, n = 5 | A, without s11 (E = 10, n = 4) | B, E = 3, n = 5 | B, without s11 (E = 2, n = 4) |
| --- | --- | --- | --- | --- |
| 7 d | 29 % (3.5) | 26 % (3.1) | 68 % (12.8) | 74 % (15.8) |
| 14 d | 48 % (7.0) | 45 % (6.3) | 88 % (25.7) | 91 % (31.5) |
| 21 d | 62 % (10.5) | 58 % (9.4) | 95 % (38.5) | 96 % (47.2) |

- v3.1's illustration (mapping A, 21 days: 65 % with n = 4, 72 % with n = 5) was correct arithmetic for the wrong n. For
  real strictly-through fills, mapping A at 21 days falls from about 65 % to **about 30 % with v3's E, and about 23 % with
  the recomputed E**, on about 3 expected fills.
- The at-price projection is conservative: paper `at_price` ignores queue position (live fill 1 had 20 shares ahead).
- `OWN_LEG_CROSSED` (§1.2) is the paper event closest to RE-1's at-price fills; it is reported, never counted as a fill.

### 8.4 Consequence for OD11

- **The pre-decided first-live cap (one band, minimum size, if real fills < 10) will almost surely bind.** P(real
  strictly-through fills < 10): mapping A (E = 11) 100 % at 7 d, 99 % at 14 d, 96.5 % at 21 d; mapping B (E = 3) 94 %, 74 %
  and 57 %.
- Option 3 (synthetic, §9.4 diversified) plus option 2 (`at_price`, reported) remains the recommendation. OD11 is now
  **decidable** on these numbers (the reconciliation has landed in this folder; E is recomputed). A session-minute exposure
  would be a better unit than sessions or days; it needs the campaign journals and is not required for the ruling.
- §13's `fills.re1_reconciliation` is set to `{doc_sha256: "0d9d42e7793ba666d2775669f994579716ab57683e40ea4ecbc50f64a33a10d0",
  canon_commit: "2ee759c95", digest_fix_commit: <the commit that lands the corrected FINDINGS_DIGEST text, when it lands>}`.

---

## 9. Notes applied `[v3.2: N3-N6]`

### 9.1 N3: guards that survive `python -O`
- W2(a)'s guard against resting legs is an explicit `BundleError`, not an assertion
  (Annex K).
- `compose_book`'s `unmerged_book_levels` raise is unreachable from bundles (the decoder merges levels, `payloads.py:90-97`);
  it is kept as a guard for the live adapter.

### 9.2 N4: hazard provenance binds the actual dates
v3.1 §6.7's "exact date set" is the calibration's **actual per-city and pooled `dates`** as computed, never its top-level
`dates=CALIBRATION_DATES` constant (`calibration.py:14, 189`), which always passes. New mutant **MH1b**: a receipt whose
constant is clean but whose actual per-city dates include one ≥ 2026-09-30 → `REFUSED (hazard_provenance)`.

### 9.3 N5: executed-code binding
Hashing `module.__file__` source does not prove the executed code: a stale `.pyc` with the same mtime and size runs instead.
The live preflight (v3.1 §4.4 "Binding") also requires either (i) the live process runs with `PYTHONDONTWRITEBYTECODE=1` and a
fresh empty `PYTHONPYCACHEPREFIX`, so bound modules compile from the hashed source, or (ii) checked-hash pycs
(`PycInvalidationMode.CHECKED_HASH`). New mutant **ML3b**: a stale `.pyc` of a bound module with matching mtime and size →
preflight refuses.

### 9.4 N6: WU API body echo check
Before the cohort, S1 confirms on one WU API JSON reply dated ≤ 2026-09-29 (workstation data, only if its unit allows it;
otherwise a fresh reply for a date ≤ 09-29 fetched under OD15, held in memory) that the body does not echo the key. The
check records only "echo: yes/no" and the pattern id. If it echoes, every input-store write refuses (rule 3), and rule 1
needs a redacted-body form: that becomes owner question OQ-26 before the cohort.

---

## 10. Verdict, binding and receipt deltas `[v3.2]`

- **§10 per-day verdict:** `INCOMPLETE` adds `transfer_scan_token_unavailable` (MF-6). `REFUSED (secret_in_output)` covers
  pattern id `page_body` (MT1b).
- **§12 cohort binding** adds: the reopen and local-midnight synthesis module hash (`reopen_rule` now names both §3.1 and
  §4.3); the oracle handout manifest SHA-256 (MF-8); under (a), the attribution report's SHA-256 (§1.4).
- **§12 timeline:** "OD11 waits for the RE-1 reconciliation" is removed (done); the 10-23 default to (b) is removed (§2.3);
  WU history enters the bound set only after WU-T lands (§5.1).
- **§13 receipt:** `tier_i.own_leg_crossed` (count, per side); `tier_i.ked.ked2_tainted_leg_minutes` and
  `credits_withheld` under (b); `secrets.transfer_scan_deferrals`; `fills.re1_reconciliation` as §8.4.
- **§15 mutants added in v3.2:** MW3, MW3b, MW3c, MW3-frozen, MKED5, MD1b, MD1c, MD4, MD5, MD6, MCF1, MCF2, MT1b, MT5, MT6,
  MH1b, ML3b; MD1 rescoped; MT1-MT3 now use run-time tokens.

---

## 11. Owner decisions (updated; each with a recommendation)

OD2, OD5, OD7, OD10, OD12 and OD14 are unchanged from v2. OD1, OD6, OD8, OD9, OD13, OD16 and OD17 are unchanged from v3.
OD3, OD4, OD15 and OD23 are unchanged from v3.1.

| # | Decision | Recommendation |
| --- | --- | --- |
| **OD19** `[CHANGED — MF-1, N1, N2]` | Own legs in the decision book. (a) Fix the Kernel (`compose_book`: four arrays, created levels, summed) before signature, disclosed as C11. **(a) also creates a paper-only own-vs-public `CROSSED_BOOK` path: where the public book moves onto a resting leg without a print, paper cancels without a same-instant replacement, where the frozen loop replaced after `TOUCH_BUFFER`; live would have been filled at price.** Every pre-fix v2 artefact is re-run **and every changed decision attributed** (§1.4); estimand values change in all three quoting arms, definitions do not. Or (b) Kernel as-is, with KED-1 counted and capped; the KED-1 divergent rate measured per §2.2 is stated here before the ruling. | **(a).** The crossing path is the honest venue analogue (paper cannot invent fills), it is counted (`OWN_LEG_CROSSED`), and skipping crossing own size would be a second non-venue rule. (b) routinely turns each such state into `KED1_DIVERGENT` and may never reach MET. |
| **OD20** `[CHANGED — MF-10]` | Replacement book: (a) the same-instant replacement decides on the public book, disclosed as C12; or (b) KED-2, counted and capped, S-REQUOTE credited only from non-divergent replacements, **and legs placed by a divergent replacement tainted (no stratum, fill-cluster or synthetic credit) until cancelled or filled**. | **(a)**, in the same U3 change as OD19. |
| **OD21** | TL unit and owner (live executor plus Tier L suite), as v3.1; L5 is now the explicit t′ rule (§7) and the binding includes executed code (§9.3). | **Yes.** Assign TL now; never the oracle's author. |
| **OD22** `[CHANGED — MF-4]` | Record CF-1 off the critical path, conditional on the tripwire over the **captured descriptor's horizon** (§4.2) and on the **local-midnight descriptor refresh** on both sides (§4.3). Disclosure: "lead-0 conditions, including those still labelled horizon 1 by a pre-midnight descriptor". | **Confirm**, with the refresh as an S1 deliverable before the cohort. |
| **OD24** `[NEW — MF-5]` | Name the OD15 production unit **WU-T** and its owner: the executor of `claude/wu-token-leak-scan-20261007` (head `3455783db` covers the helper, the scanner and the non-loop points). WU-T converts `source_adapters.py:172` and `observation_trigger.py:827` (plus the diagnostics row) to enumerated codes or sanitised text, pins the loggers and the `debuglevel` check in the trigger loop, and lands through the quiet-window path. WU history enters the gate's bound set only after that. | **Yes.** Confirm WU-T's owner and a landing date before the 10-13 rehearsals, so WU history can be in the calibration days; otherwise WU history stays off on both sides and P4 reports it. |
| **OD25** `[NEW — N2(ii)]` | If (a) is ruled for OD19/OD20 and the U3 fix has not landed by the 10-23 signature: (i) cohort waits for a successor registration that carries the fix; (ii) the signature slips until it lands; (iii) explicit re-ruling to (b) with the measured KED rates. Nothing happens by default. | **(ii)** if the slip is days; else **(i)**. Choose (iii) only if §2.2's rates sit inside the caps. |
| OD11 `[CHANGED — MF-11]` | Fill rule, options 1-4 as v3, now with reconciled counts (5 = 4 at price + 1 strictly through) and E recomputed through session 11 (§8). Real strictly-through E[power] at 21 days ≈ 23 % (A) / 55 % (B); the first-live cap binds with P ≈ 96.5 % (A) at 21 days. | **Option 3 plus option 2 reported**; keep the first-live cap (one band, minimum size, real fills < 10), expecting it to bind. Now decidable. |
| OD18 `[CHANGED — MF-8]` | Oracle authorship as v3.1, plus: the author receives only the redacted handout (§6), whose manifest hash is recorded in the oracle PR; Annex K goes to U3 only. | **Yes**, with the stated design common mode. |
| OQ-26 `[conditional — N6]` | Only if the WU API body echoes the key (§9.4): approve a redacted-body storage form for rule 1. | Raise only if the check says yes. |

---

[REDACTED in the repository copy: Annex K, source lines 614-664 (from the line `## Annex K` through the rule before the Summary), is cut, per v3.3 §6.2 item 2. Annex K is U3 only.]

---

## Summary (10 lines)

1. v3.2 is a text amendment of v3.1 applying MF-1…MF-11 and notes N1-N6, N9; every change is tagged `[v3.2: MF-n]` / `[v3.2: Nn]`; shadow citations now name commit `b31185d6b`.
2. MF-1: W1(a) creates a paper-only own-vs-public `CROSSED_BOOK` path (public book moves onto a resting leg with no print → cancel, no same-instant replacement, where the frozen loop replaced after `TOUCH_BUFFER`); C11, G4 and OD19 corrected; `OWN_LEG_CROSSED` counted; MW3/b/c added.
3. Re-run and attribute: every changed decision must trace to classes A1-A3 (W1) or A5 (W2), directly or as a cascade, or the re-run fails; estimand values change in informed-v0, blind_re1 and clock_only.
4. (b): KED-2-divergent legs are tainted (no credit) until cancelled or filled; KED rates are measured before the ruling; no automatic fallback at 10-23, explicit OD25 instead.
5. Day roll: lead-0 reopen views are checked against the canonical redaction value (MD1b/c); reopen records precede regular 00:00 records; they are synthesised by the reader from D's sealed tape, only if both writers were alive through midnight; universe = D's descriptors.
6. CF-1 tripwire uses the captured descriptor horizon, with fixtures for Eastern 04:00Z (to 11-01), Pacific 08:00Z (from 11-02) and the DST night; a local-midnight descriptor refresh closes the window; the decoder `affects` check is pinned (MCF1).
7. Token: production paths `source_adapters.py:172` and `observation_trigger.py:827` are OD15 production work by WU-T on `claude/wu-token-leak-scan-20261007` (OD24); WU history waits for it on both sides.
8. Scanner covers `api[_-]?key` with `=`, `:`, `%3D`, `%3A`, `%253D`, `%253A`; scans in memory before any write; transfer fails closed and defers if the exact-token fetch fails; mutants use run-time tokens; MT1b, MT5, MT6 added.
9. The oracle author gets a redacted handout (Kernel code moved to Annex K, manifest hash in the oracle PR); L5 compares `decide()` at the acknowledgement instant t′ on the same records, with time-invariant inputs checked separately.
10. Fills: 5 = 4 at price + 1 strictly through; E recomputed (A = 11 sessions, B = 3 days); strictly-through E[power] at 21 d ≈ 23 % (A), and the first-live cap almost surely binds; OD11 is now decidable.
