# D — "Shadow agrees with replay" live gate: specification v3.1 (narrow amendment of v3)

> **Repository copy (2026-10-07).** Status: a **superseded base** of the maker replay v2 "shadow agrees with replay"
> live-gate specification, kept so that later versions' citations resolve. **Superseded by
> [v3.2](maker-replay-v2-shadow-gate-spec-v3.2-2026-10-06.md) and then
> [v3.3](maker-replay-v2-shadow-gate-spec-v3.3-2026-10-07.md)**, each a text amendment of its base: v3.1 text that
> neither restates still applies. It is a **draft for owner decision, not a signed registration**, and grants no run, live, merge or transfer
> authority. Owner item: [item 330](items/item-330-maker-economics-refocus-master-plan.md); current status of maker
> replay v2 lives in [the state of play](../operations/STATE_OF_PLAY.md), never here.
>
> **Read when** v3.2 or v3.3 cites a v3.1 section (§2.1, §3.7, §6.3, §6.8, §11 ...) and you need the text they do not
> restate. Read v3.3, then v3.2, first; the later version wins. In particular, v3.1's OD22 text ("lead-0 info events
> only") is superseded.
>
> **Provenance.** The H1 and the text after this note are a copy of the workstation file
> `l-data/swarm-m/D-shadow-gate-spec-v3.1.md` (SHA-256 of the local file, the hash v3.2 and v3.3 cite —
> `f0729884291142d25ea773a9d81f83ef80422a0aaf60898ef68089b694398f29`; that local file already has LF line endings, so no
> CRLF restoration is needed), **except the redactions listed below, so the body is not verbatim.** The redacted text
> (the H1 plus everything after this note, LF) has SHA-256 `c3713b349b2bfbd3de87e8dc9ce9f0aa6d13654020c4878b404dac41b4825075`.
> Local paths and sibling files named in the body are workstation-local; v3 and v2 are not in the repository.
>
> **Redactions (oracle clean room).** The oracle author's worktree is a checkout of this repository, so this copy follows
> the handout form of v3.3 §6.2 item 3 and carries no Kernel code:
> - the two fenced `python` blocks (source lines 255-281 and 373-380) are each replaced by the line
>   `[REDACTED: Annex K, U3 only — see the table and the semantics sentence above]`, as v3.2 §6 says;
> - the G2 row's finding cell (source line 68) → v3.3 §6.2's sentence;
> - the "In `tick` …" sentence (source lines 283-284, up to `` state.legs)`. ``) → "The Kernel's frozen composition step
>   is replaced by `C_book` of the latest public book and the resting legs"; the rest of line 284 is kept;
> - `state.legs` on source lines 187, 382 and 383 → "the resting legs" (on line 383, "`state.legs == ()`" → "the
>   resting legs are `()`").
>
> v3.3 §6.2's substitutions, applied as written, leave three Kernel names that its extended handout check denies:
> `add_own` (source lines 67 and 902) and `value.book` (source line 71). They are names, not code, and are kept; the
> coordinator's handout script must still handle them.
>
> **Update when** never in place: this is a frozen base. A correction or a new version goes in a new dated file that
> v3.3's header and item 330 link.

Swarm M Wave 2, spec author, 2026-10-06. **Spec only.** No gate code, no kernel code, no commits. No gate code may be
written until this spec passes a Defender review and the owner has seen it (CONSOLIDATED §3 holds). Nothing here grants
run authority, lifts the live pause, or authorizes the O9 transfer (on HOLD).

Sources, all read-only:
- in this folder: `D-shadow-gate-spec-v3.md` (the base), `D-v3-defender.md` (W1, W2, M-T, M-CF, M-I, M-L, M-D, M-P,
  M-S, M-U, N-a…N-f), `CONSOLIDATED.md` §4-5 (U7, OD15), `WAVE2-RULES.md`;
- the coordinator's v3.1 decisions of 2026-10-06 night (§0.3, "MA31-1…4");
- the build tree `C:\wt\workstation-chat\m-v2ro` at `501f47579`: `maker_core/replay/v2/kernel.py` (`:153-214`,
  `:302-315`, `:345-376`, `:478-551`), `maker_core/quoting/{policy,prices}.py`, `maker_core/replay/{fill_model,engine,
  re1_counterfactual,calibration}.py`, `maker_core/contracts/__init__.py`, `weather/market/maker_plugin/clock.py`,
  `weather/sources/wu_history.py`, `docs/research/maker-replay-v2-registration-DRAFT.md` §3 and §5;
- the shadow tree `C:\pt\wf` at `b31185d6b`: `maker_core/shadow/runner.py`, `weather/market/maker_shadow.py`;
- `origin/master`: `src/weather/operations/observation_trigger.py`; `docs/operations/FINDINGS_DIGEST.md` lines 25 and
  88-101 only.

No data, panel, settlement, `data/`, `.env*` or credential file was read. No row for 2026-09-30..10-15 was read.

---

## 0. How to read v3.1

### 0.1 Base and markers

v3.1 is a **narrow amendment of v3**. v3 (`D-shadow-gate-spec-v3.md`, frozen in this folder) remains the base text,
and v2 remains v3's base. Any v3 section, table row or mutant not restated here applies unchanged and is cited as
"v3 §x". Every v3.1 section carries one tag against v3:
- `[v3.1 NEW — <finding>]`: not in v3;
- `[v3.1 CHANGED — <finding>]`: v3 text replaced; the v3 text is void;
- `[v3.1 KEPT]`: v3 text applies, restated only where needed for reading;
- `[v3.1 REMOVED — <finding>]`: v3 mechanism withdrawn.

Finding ids are the v3 Defender's (W1, W2, M-T, M-CF, M-I, M-L, M-D, M-P, M-S, M-U, N-a…N-f) and the coordinator's
v3.1 decisions (MA31-1…4).

### 0.2 One switch, two rulings, everything else independent

W1 and W2 need an owner ruling (OD19, OD20 in §17). Each is written as two fully specified alternatives in §3.7:
- **(a) FIX**: the Kernel is corrected before the 10-23 signature, and the correction enters the registration as a
  disclosed engine correction;
- **(b) KED**: the Kernel stays as it is, and the deviation becomes a counted, capped **known engine deviation** class.

**Recommendation: (a) for both.**

Every other section of this spec refers only to two named compositions, defined by the ruling and bound into the
cohort id as `engine_ruling = {W1: FIX|KED, W2: FIX|KED}`:
- `C_book(public, legs)`: the book `decide()` sees for a condition with resting `legs` (§3.7.1);
- `R_book(public)`: the book the same-instant replacement decides on (§3.7.2).

No section outside §3.7 changes with the choice, except where a sentence says "under (b)".

### 0.3 Coordinator decisions applied (2026-10-06 night)

| # | Decision | Where applied |
| --- | --- | --- |
| MA31-1 | The clock fix CF-1 is off the critical path (sha2 = U6+U1+X1). In v3.1 CF-1 is **not** a cohort dependency. The v1-exam disclosure states that the trigger gap affects **lead-0 info events only**. | §2.1, §6.8, §12, §17 |
| MA31-2 | W1/W2: both alternatives are written; the owner chooses; if "fix", they enter the registration as engine corrections with disclosure. | §3.7, §17 OD19/OD20 |
| MA31-3 | All OD15 leak fixes are **required**, not optional. | §4.8 (every rule is normative) |
| MA31-4 | The RE-1 fill-count reconciliation (4 vs 5) is done separately. v3.1 leaves a placeholder citing "pending reconciliation". | §9.4 |

### 0.4 Facts verified in code for v3.1 (new)

| # | Fact | Evidence | Consequence |
| --- | --- | --- | --- |
| G1 | The Kernel's `add_own` iterates only **existing public levels**: own size at a price with no public level is dropped. YES legs go only to `yes_bids`; NO legs only to `yes_asks` at `1 − price`; `no_bids` and `no_asks` never carry own size. Same-outcome legs at one price would overwrite, not sum (a dict comprehension). | `kernel.py:527-531`; the v1 engine has the same rule at `engine.py:415-420` | W1. The overwrite is unreachable today (one leg per outcome in both profiles), but the fix sums. |
| G2 | After a replacement-reason CANCEL, the Kernel decides the replacement on the pre-cancel decision book with `existing = ()`, after its leg ledger has been cleared; so the cancelled size counts as competing liquidity and displayed depth | `kernel.py:546-549` (the `replace` is at **548**, correcting v3 F1's "547", N-e) | W2. |
| G3 | `qualified_mid` uses levels with size ≥ `min_size` from `yb`/`ya` **with** own size added (`prices.py:18-26`, `policy.py:248`). An own leg of size ≥ `min_size` can therefore become the best qualified bid or ask and move the mid. The frozen Kernel already does this at existing levels; a created level extends it. Live sees the same thing on the venue book. | code | Under (a), paper reproduces live's self-reference. Whether informed-v0 *should* exclude own size from the mid is a policy question, outside this gate (OD23). |
| G4 | `touch_buffer` reads `ya` for a YES leg and `na` for a NO leg (`policy.py:343`). Under (a), `na` carries the own YES leg mirrored at `1 − p_yes`. For any eligible pair, the distance between a leg and the other leg's mirror is `d_yes + d_no ≥ 2·d_lo ≥ tick`, so the touch outcome cannot change. | code | (a) changes no `TOUCH_BUFFER` outcome; recorded so that a reviewer does not have to re-derive it. |
| G5 | Blind RE-1 receives the same composed `value.book` (`kernel.py:539-541` → `re1_counterfactual.tick`, which reads `inputs.book` at `:29` and `:61-62`). | code | A W1 fix changes blind RE-1 outputs too. It must be disclosed (§3.7.1(a)). |
| G6 | `Unavailable.kind` ∈ {`missing_input`, `out_of_scope`, `corrupt`, `decided`}, defaulting to `missing_input`. The plugin already uses `out_of_scope` for a scope refusal (`fair_value.py:276`). | `contracts/__init__.py:117-127` | The lead-0 redaction pins `kind = "out_of_scope"` (§2.2). |
| G7 | The trigger loop fetches only the **local current day** (`effective_target_date = local_now.date()`, `observation_trigger.py:347` on `origin/master`). The plugin clock keeps only rows whose detection and observation local dates equal the market's target (`clock.py:72-74`). informed-v0 returns `DECIDED`/`INFO_PULL`/`HORIZON_NOT_ELIGIBLE` before any QUOTE path (`policy.py:255-260`). | code | Observation events act only on lead-0 conditions, which informed-v0 never quotes (M-CF). |
| G8 | `wu_history.py` sends the page-scraped token as `apiKey` (`:97`, `:317`). `_raise_for_status` re-raises the requests error unchanged (`:293-299`), and its text includes the full URL with the query. `redact_api_key` (`:123-138`) and `failure_class_for_exception` (`:155-174`) exist, but only the backfill store uses them. | code | M-T leak paths 1-4. |
| G9 | The shadow CLI prints `str(error)` for every `ValueError` to stderr (`maker_shadow.py:290-292`), and `:151` writes `str(error)` into a record when the message is lower-case. | shadow tree | Two more unredacted `str(exc)` paths. Both must go through §4.8's enumerated-code rule. |
| G10 | The hazard constant `hazard_per_minute` reaches the Kernel config from the replay calibration (`calibration.py:193`, `execution_manifest.py:169`), not from a fixed literal. | code | Its source dates must be bound (M-U, §6.7). |

### 0.5 Change index against v3

| Finding | v3 mechanism | v3.1 resolution | Sections |
| --- | --- | --- | --- |
| **W1** | I2 "added at price", no rule for absent levels or NO arrays; L1 equality ill-defined | Two alternatives: (a) Kernel composes own legs on all four arrays, creating levels, before signature; (b) KED-1 class. `C_book` defined by the ruling. L1 = `paper_compose(V ⊖ O, O)` with an echo check. | §3.7.1, §4.4, §6.3 I2 |
| **W2** | Same-instant replacement on a book holding the cancelled legs | Two alternatives: (a) the replacement decides on `R_book` = the public book (legs gone); (b) KED-2 class. Label `PAPER_SAME_INSTANT_REPLACEMENT` either way; live replaces after the cancel acknowledgement. | §3.7.2, §4.4 L5, §7 |
| **M-T** (OD15) | Four leak paths, no scan | §4.8 Secret hygiene, **required** (MA31-3): API JSON body only; enumerated failure codes; token scan at seal and transfer; logger pins; repository ratchet; MT1-MT4; oracle violations carry identities and hashes only | §4.1, §4.6, §4.8, §5.3, §6.3, §15 |
| **M-CF** | CF-1 a cohort dependency; P4 REFUSED; Kc3 maps S-INFOPULL | CF-1 dropped as a dependency (MA31-1); P4 a reported diagnostic; P2 narrowed; Kc3 removed from the map; a fixture tripwire test | §2.1, §2.4, §6.8, §7, §11, §12 |
| **M-I** | I1-I13; read-log clean room | I14 decision content with the full pull precedence; exact I13 wake field list; event activity at the instant; physical clean room; erratum-only cross-validation; OD18 limits stated; `ORACLE_SPEC_DERIVED_FROM_KERNEL` | §1, §6.3, §15, §17 |
| **M-L** | Tier L unbound and unowned | Byte-identical adapter binding at live preflight; deltas only in `maker_core.live.*`; named unit and owner (OD21); in-flight blocks placements, never pulls; partial-fill race | §4.4, §17 |
| **M-D** | D+1 instance's inputs at 00:00 unspecified | Day-open re-emission at `D+1 00:00:00Z` with payload clocks kept; shadow terms seeding; Kx8; OD4's one-UTC-day shape a hard preflight check | §3.3, §4.4 L7, §7 |
| **M-P** | The proxy test fails on `digest()` | `policy.digest` patched to a constant during the test; a separate `input_hash` coverage assertion | §3.6 |
| **M-S** | One fill path | 12-cell synthetic set plus same-instant injections; only positive fills count | §9.4 |
| **M-U** | U7 called, not bound | U7 guard hash in the cohort; settlement and scoring readers ratcheted out (transitively); hazard provenance bound | §2.3, §6.7, §12 |
| **N-a** | Lead-0 redaction | Emitted, never omitted; `kind` and `as_of` pinned identically on both sides; `input_hash` changes and is excluded | §2.2 |
| **N-b, N-c** | One projection | At-price and strictly-through fills separated; E[power] reported (Jensen); RE-1 count **pending reconciliation** (MA31-4) | §9.4 |
| N-d, N-e, N-f | — | Label kept (§1); citation fixed (G2); WU page fetch interval and separate failure counts (§4.8) | as listed |

---

## 1. What the gate proves, and what it cannot `[v3.1 CHANGED — M-I, W2, N-d]`

v3 §1's table is `[v3.1 KEPT]`, with one change to row R3b's independence column: "Separate code, separate author **in a
physical clean room, different model where available** (§6.3), import ratchet; it shares only `decide()`, the frozen
contract dataclasses **and the design text of §3/§6.3, which transcribes the Kernel's design** (so Tier I proves the
implementation against the ruled design, not the design itself)."

**Not tested** adds:
- the Kernel's design where the spec transcribes it (`ORACLE_SPEC_DERIVED_FROM_KERNEL`);
- the timing of live replacements: paper replaces at the same instant, live after the cancel acknowledgement
  (`PAPER_SAME_INSTANT_REPLACEMENT`);
- B0w's projection semantics, which are common-mode across the shadow, B0w, R_p and production (N-d; v3 §1 R2).

The label is:
`LIVE_GATE_EVIDENCE_NOT_AUTHORITY;DECIDE_COMMON_MODE_UNTESTED;KERNEL_ORACLE_SCOPED;ORACLE_SPEC_DERIVED_FROM_KERNEL;PAPER_FILLS;PAPER_SAME_INSTANT_REPLACEMENT;DAY_SESSION_FLAT;OVERNIGHT_INVENTORY_UNTESTED;PROVENANCE_PUSH_PATH_CHAINED`
- Under (b) for either ruling, add `KNOWN_ENGINE_DEVIATIONS:<KED-1|KED-2|KED-1,KED-2>`.
- The last element becomes `PROVENANCE_SIGNED` if OD8 adopts signing.

---

## 2. Preconditions `[v3.1 CHANGED]`

### 2.1 Cohort dependencies `[v3.1 CHANGED — M-CF, MA31-1, M-U]` (replaces v3 §2.1)

- **CF-1 is not a cohort dependency** (MA31-1). It stays a production-safety fix, owned outside this gate. The v3
  refusal `REFUSED (observation_channel_unsourced)` is **removed**.
- **Why that is sound (G7).** Observation events are produced for the local current day only and kept by the clock
  only for the market's local target day. So they act only on lead-0 conditions, and informed-v0 never quotes at
  lead 0. No compared horizon-{1, 2} decision can depend on the observation channel.
- **Tripwire test** (`tests/maker_core/test_observation_scope.py`, new). Over fixture trigger rows (one per source,
  per local date D−1, D, D+1, and per detection/observation date mismatch), the plugin clock's events must have empty
  `affects ∩ {conditions at horizons 1, 2}`. If CF-1, or any later change, widens `affects` or the date rule, this
  test fails. P4 then returns as `REFUSED` by rule, and the observation channel becomes a cohort dependency again.
- **v1-exam disclosure (MA31-1).** Production emits no observation-sourced info events today (v3 F2). The registration
  disclosure states that this gap affects **lead-0 info events only**, and so no horizon-{1, 2} decision of
  informed-v0.
- **New cohort dependency: U7** (M-U, §6.7). No cohort starts before the U7 MG-1 guard has landed on the build line.
  Its module hash is in the cohort id.
- **New cohort dependency: the engine ruling** (§0.2). Under (a), the corrected Kernel must be on the build line and
  the shadow rebased onto it. Under (b), the KED classifier (§3.7.3) must be in the oracle.

### 2.2 Model allowlist, lead-0 redaction, no settlement `[v3.1 CHANGED — N-a]`

v3 §2.2 items 1, 2, 4 and 5 are `[v3.1 KEPT]`. Item 3 is amended:

3. **Lead-0 redaction (both sides).**
   - **Emitted, never omitted.** For every lead-0 compared condition, every evaluation that would have produced an
     `outcome_view` record produces exactly
     `Unavailable(reason="lead0_not_in_gate_scope", as_of_utc=<record instant>, kind="out_of_scope")`.
     - Omitting the record makes the Kernel pull `MISSING_OUTCOME_VIEW` (`kernel.py:302-305`). That is a refusal
       mutant (MV3c).
   - **Pinned conventions, identical in the gate-purpose exporter and the shadow** (and therefore in B0w and A2):
     - `reason` is the exact string above;
     - `kind = "out_of_scope"` (G6). It is part of `view_state` (`kernel.py:198`), so a different kind on one side is
       a B0w mismatch;
     - `as_of_utc` = the logical instant of the record that carries it;
     - the record is emitted at each evaluation instant of that side's view producer, the same cadence as the
       producer's available views. A re-stamp moves only `as_of_utc`, so it is not a wake (rule 4).
     - The resume latch reads `as_of_utc` (`kernel.py:516`), so this convention fixes the latch reason of lead-0
       conditions identically on both sides.
   - **`input_hash` changes.** `decide()` digests every field, `fair_value` included (`policy.py:192`). The
     redaction therefore changes the `input_hash` of every lead-0 decision. `input_hash` is excluded from B1 and from
     I12/I14 (v3 §6.4; v2 §6.4). The MV3 equality fixture compares the decision fields only.
   - The rest of v3 §2.2.3 (checks at transfer and gate, the equivalence argument, `LEAD0_EXCLUDED`, MV3) is
     `[v3.1 KEPT]`.

### 2.3 Same code `[v3.1 CHANGED — M-U, M-L]`

v3 §2.3 applies. The bound module set adds:
- the U7 guard module;
- the §4.8 secret-hygiene module (`maker_core.shadow.secrets`);
- under (a), the corrected Kernel. Its hash differs from `501f47579`'s, and that difference is the point.

`binding.engine_ruling` records OD19 and OD20.

### 2.4 Every input channel present on both sides `[v3.1 CHANGED — M-CF]`

v3 §2.4 applies, except that its observation sub-channel bullet ("absent when either side holds zero observation-source
reads … `REFUSED (channel_absent:observation)`") is **removed**. Observation-source health is reported by P4 as a
diagnostic (§6.8).

---

## 3. The input-construction agreement `[v3.1 KEPT with changes]`

### 3.1 Row changes to v2 §3.1 `[v3.1 CHANGED — W1, W2, M-CF]`

| Field | v3.1 contract rule |
| --- | --- |
| `book` | Paper: `C_book(public, the resting legs)` (§3.7.1). Replacement: `R_book(public)` (§3.7.2). Live: Tier L L1 (§4.4). |
| `events` | As v3, with "after CF-1" removed: the same observation sources as production, whatever production's set is on the day (§4.1). |
| `fair_value` | As v3, with the pinned lead-0 value of §2.2. |

### 3.2 Raw identity `[v3.1 CHANGED — M-T]`

The v3 §3.2 `info_event` row is replaced:

| Kind | Raw identity kept (shadow tape raw block and gate sidecar) |
| --- | --- |
| `info_event` | Per observation event: source, station, `observed_at`, value, and the **API JSON body** SHA-256 (body stored per §4.8). For a page-backed source, the page body is **never stored**: only its SHA-256, byte length and HTTP status. Per scheduled event: kind, station, `scheduled_at_utc`. |

### 3.3 Composition behaviour `[v3.1 CHANGED — M-D]`

v3 §3.3 applies. The **Day open** row is replaced, and one row is added:

| Behaviour | v3.1 contract rule | Control |
| --- | --- | --- |
| **Day open** | A **fresh** instance for D+1, as v3: no `latest`, `sha`, `trades_seen`, coverage state, latches, `last_quote` or `previous_fair_value`; cash = `caps.cash`; no lots. At `D+1 00:00:00Z` it first ingests the **day-open re-emission** (next row), in engine order. Then its window-start timers fire, then wakes run in condition-id order (`engine.py:132-161`). So a condition whose re-emitted inputs are valid is decided with coverage at 00:00:00, not pulled `MISSING_*` for up to an hour. Conditions whose re-emitted inputs are stale pull exactly as the Kernel rules say (for example `CAPTURE_GAP`, `TERMS_CAPTURE_GAP`), identically on both sides. | Kx7, Kx8 |
| **Day-open re-emission** (new) | At `D+1 00:00:00.000000Z`, for every condition in D+1's universe, the latest record of **each** of the six kinds (`descriptor`, `book`, `terms`, `outcome_view`, `info_event`, `coverage`) as of the end of D is written again.<br>• The logical instant is `D+1 00:00:00Z`; the record is flagged `reopen: true`.<br>• The **payload is byte-identical**, including its payload clocks (`book.as_of_utc`, `terms.as_of_utc`, view `as_of_utc`, coverage `valid_until_utc`). Only the record instant is new. So freshness is never faked: a stale input is still stale at 00:00.<br>• Lead-0 views are re-emitted as the §2.2 redaction value, re-stamped at `D+1 00:00:00Z` (that value's `as_of` is its record instant by definition).<br>• Order within the instant: by condition id, then kind in the order above.<br>• **The same rule applies in the gate-purpose exporter.** Otherwise R_s differs from the shadow and B1 fails the day.<br>• B0/B0w accept a `reopen` record by identity: its payload SHA-256 must equal that of the latest record of the kind in D's tape (or in D's bundle, for R_s).<br>• Carry-state engines (R_p over several days) see the re-emission as an unchanged re-send. Under rules 1, 3 and 4 that is no wake, so R_p's decisions are unchanged (fixture MD2). | Kx8 |
| **Terms seeding** (new) | Terms are polled hourly, so an hourly read just before midnight is what keeps the reopen terms inside the 3600 s window. The shadow schedules **one extra terms read per condition in `[23:58:00, 23:59:30]Z`** each day. Its record is an ordinary D record. It is re-emitted at 00:00 with its own `as_of`, so the D+1 instance is covered until about 00:58. The production exporter's re-emission uses production's latest terms as captured. If its age at 00:00 exceeds 3600 s, R_s pulls `TERMS_CAPTURE_GAP` until the next production terms record. That is symmetric inside R_s and the shadow re-drive and visible only in B3, where it is classed `TIMING`. | — |

### 3.6 Read-set proof by a recording proxy `[v3.1 CHANGED — M-P]`

v3 §3.6 applies, with these changes:
- **`digest` patched out.** During the proxy test, `maker_core.quoting.policy.digest` is monkeypatched to return a
  constant (`"0" * 64`). Otherwise `decide()`'s first statement, `h = digest(i)` (`policy.py:192`), walks every
  dataclass field through `journal.plain` (`journal.py:23-24`). The proxy would then record every path, and the ⊆
  assertion could never hold.
- The proxy records reads **only** while `decide()`'s decision logic runs. The equality
  `decide(proxy(i)) == decide(i)` is asserted on the decision fields, with `input_hash` excluded and `digest` patched
  identically on both calls.
- **Separate assertion** (`test_input_hash_covers_inputs`): with `digest` unpatched, changing any single leaf field of
  `DecisionInputs` (by a hypothesis strategy over every dataclass path) changes `input_hash`.
- New mutant MR2: the proxy test run without the `digest` patch must fail (this proves that the patch is what makes the
  test meaningful).

### 3.7 Own legs and the replacement book: the engine ruling `[v3.1 NEW — W1, W2, MA31-2]`

Each item below is written twice: (a) FIX and (b) KED. The owner picks per item (OD19, OD20). Any combination is
valid. **Recommended: (a) for both.**

Notation:
- `public` = the decoded public book record (four arrays, levels merged by price, zero sizes dropped, bids high-to-low,
  asks low-to-high);
- `legs` = the condition's resting paper legs;
- `O` = live acknowledged own orders.

#### 3.7.1 W1: own legs in the decision book

##### (a) FIX: the decision book holds own legs at their prices on both the YES and NO sides, as live sees them

**Semantics.** Each resting leg appears on its own token's bid array at its price, and mirrored on the other token's
ask array at `1 − price`. A level is **created** when absent. Sizes at the same (array, price) are **summed**. Nothing
else changes: `as_of_utc` and `post_only_available` are carried over.

| Leg | Added to | At price |
| --- | --- | --- |
| YES leg (p, s) | `yes_bids` | p |
| YES leg (p, s) | `no_asks` | 1 − p |
| NO leg (p, s) | `no_bids` | p |
| NO leg (p, s) | `yes_asks` | 1 − p |

This is the venue's display: RE-1 found the YES/NO books mirror (`FINDINGS_DIGEST.md:91`).

**Exact Kernel change** (`maker_core/replay/v2/kernel.py`; U3 is the sole editor of this file, CONSOLIDATED §2).
Add a module-level function:

[REDACTED: Annex K, U3 only — see the table and the semantics sentence above]

The Kernel's frozen composition step is replaced by `C_book` of the latest public book and the resting legs. `decide()`, `policy.py` and the v1 engine are **not**
changed. `external_levels` already removes `existing` from `yb` at `p` and from `ya` at `1 − p`, so a created level
that holds only own size is removed completely; its loop drops a level whose size equals the removed size.

**Replay-semantics impact (to be disclosed).**
- Decisions change wherever a resting leg sits at a price with no public level on its array. Legs sit 1-3 cents
  outward of the qualified mid, and thin bands have gaps, so this happens on most quoting days.
- **The qualified mid can move with own size (G3).** An own leg with size ≥ `min_size` at a fresh level that is
  better than the best qualified public level becomes the best qualified bid or ask. HOLD/requote outcomes
  (`OUTSIDE_REQUOTE_WINDOW`, `UNCALIBRATED_ASYMMETRY`, the eligibility re-check) change accordingly. This is what live
  sees. The frozen rule already did it at existing levels, inconsistently.
- `no_bids`/`no_asks` now carry own size. Their reads in `decide()` are the crossed and off-tick checks (unaffected:
  own legs are on tick, and `p_yes + p_no < 1`) and `touch_buffer` for NO legs (unaffected, G4).
- **Blind RE-1 changes too (G5).** Its retrospective session now decides on books holding own legs as RE-1 live saw
  them. The engine's blind baseline moves toward what RE-1 actually observed.
- Wakes are unchanged: `book_state` reads the public record (`kernel.py:153-165`), not the composed book.
- B1 is unaffected (shared Kernel). Tier I's I2 is written to this rule.
- **Re-run obligations.** Every v2 output produced before the fix is void and must be re-produced: fixtures' expected
  decision SHAs, ceilings and calibration rehearsals, E7 digests, executability and reachability gate numbers. No
  panel date has been run, so no economic outcome exists to motivate or be moved by the fix.
- **Timing.** Land the fix with U3, by 10-11. It must land before the P1-P4 calibration rehearsals (10-13..15), or
  those rehearsals are re-run. Hard limit: before the 10-23 signature. If it misses 10-23, (b) applies by default and
  the fix waits for a successor registration.

**Registration disclosure** (new row in the registration draft §3, "Changes from the signed exam"):

> | C11 | **Own legs in the decision book:** the decision book holds each resting leg on its token's bid array at its price and mirrored on the other token's ask array at `1 − price`, creating levels and summing sizes (`compose_book`) | engine correction (defect) | Defect found in code by the shadow-gate review (2026-10-06): the frozen loop added own size only at existing public levels and only to the YES arrays, so the policy decided on a book that is neither the public book nor the venue's book. Live parity: the venue book shows own orders on both token books (RE-1, YES/NO mirror). Not motivated by any outcome: no panel date had been read or run. | Policy behaviour differs from the frozen loop wherever a leg rests at a price without public liquidity, including the qualified mid and the HOLD/requote path; blind RE-1's baseline changes the same way. Not comparable with the frozen engine on those decisions. |

The registration's "Explicitly not changed" paragraph loses nothing. The fill predicate, sibling cancellation and
replacement cooldown are untouched by C11.

**Oracle I2 under (a):** see §6.3.

**Tier L L1 under (a):** see §4.4.

##### (b) KED: Kernel as-is, with known engine deviation KED-1

**Semantics.** The Kernel keeps `kernel.py:526-531`. The gate rules that the **correct** decision book is (a)'s (the
venue's display), and that the Kernel's book deviates from it in a known, written way:

> **T1 (the KED-1 transform, written from this text, never imported):** a YES leg (p, s) adds s on `yes_bids` at p
> **only if** `yes_bids` has a public level at p; a NO leg (p, s) adds s on `yes_asks` at 1 − p **only if**
> `yes_asks` has a public level at 1 − p; `no_bids` and `no_asks` are unchanged; for the same outcome and price, the
> last leg in leg order wins.

**Classification in Tier I** (applies to I2, I12 and I14 at record-driven decisions):
1. The oracle builds `B_ruled = compose(public, legs)` per (a)'s table and `B_T1 = T1(public, legs)`. It computes
   `D_ruled = decide(inputs with B_ruled)` and `D_T1 = decide(inputs with B_T1)`. Both are decision fields only.
2. If the recorded book equals `B_ruled` → ordinary checks (no KED).
3. If the recorded book equals `B_T1 ≠ B_ruled`:
   - recorded decision = `D_T1` = `D_ruled` → `KED1_SILENT` (counted, no effect);
   - recorded decision = `D_T1` ≠ `D_ruled` → `KED1_DIVERGENT` (counted, capped);
   - recorded decision ≠ `D_T1` → I12 **FAIL** (not a KED).
4. If the recorded book equals neither → I2 **FAIL**.
5. **Re-anchoring.** After a `KED1_DIVERGENT` instant, the oracle's own leg ledger, `last_quote` and
   `previous_fair_value` follow the **recorded** decision (which I1/I7/I8 then check onward). Without re-anchoring,
   one divergence cascades into false violations. The oracle never re-anchors on any other violation.

**Caps (per day, on the shadow tape and separately on R_p).**
- `KED1_DIVERGENT` ≤ **2 %** of record-driven decisions **and** ≤ **10 %** of QUOTE decisions. Otherwise
  `INCOMPLETE (ked_cap:KED-1)`, never FAIL.
- `KED1_SILENT` is reported and uncapped.
- Calibration may lower these caps, never raise them.
- A stratum transition at a `KED1_DIVERGENT` instant earns **no** stratum credit.
- The cohort summary reports the totals.

**Replay-semantics impact.** None on the engine. The exam and the shadow keep the frozen rule.

**Registration disclosure** (new paragraph in the registration draft §5, "Known engine deviations"):

> KED-1: the engine composes own resting legs into the decision book only at existing public levels and only on the YES arrays; the venue displays them at every price on both token books. The shadow gate counts the decisions on which this changes the outcome (`KED1_DIVERGENT`) and caps them. Economic results of this exam are results of the engine as written, not of a venue-faithful book.

**Live consequence under (b).** The live executor is bound byte-identically to the adapter (§4.4), so it decides on
`T1(V ⊖ O, O)`: own size is invisible at fresh levels and on the NO arrays, although the venue shows it. Live then
reproduces paper, and both deviate from the venue in the KED-1 way. This is disclosed in the Tier L receipt.

**Tests under (b).** MKED1-MKED4 (§15).

#### 3.7.2 W2: the replacement book

##### (a) FIX: the replacement decides on a book without the cancelled legs, matching live's in-flight block

**Semantics.** `R_book(public) = C_book(public, ())`, which is the public book. The cancelled legs are gone from the
book exactly as they are gone from `existing`. Live cannot decide while the cancel is in flight (§4.4 L1). It decides
again only after the cancel is acknowledged, on a book from which the cancelled orders are gone. Paper's replacement now
sees that book, at the same instant.

**Exact Kernel change** (`kernel.py:546-549`):

[REDACTED: Annex K, U3 only — see the table and the semantics sentence above]

Under W1(b), `compose_book` is replaced by the frozen composition applied to the resting legs. That gives the public book
too, since the resting legs are `()`. So W2(a) is the same change under either W1 ruling: **the replacement book is the
public book.**

**Replay-semantics impact (to be disclosed).**
- Every same-instant replacement whose cancelled legs shared a level with public size (or, under W1(a), created a
  level) is decided on less displayed liquidity:
  - `competing` falls, so `share` rises and `COMPETITION_OUTSIDE_RANGE` changes;
  - `displayed_depth` falls, so `INSUFFICIENT_DEPTH` becomes more likely;
  - the qualified mid can move back to the public mid (G3).
- Non-replacement decisions are unchanged. Blind RE-1 is unchanged: its path returns before the replacement
  (`kernel.py:539-543`).
- Re-run obligations and timing are as W1(a), and land in the same U3 change.

**Registration disclosure** (new row):

> | C12 | **Replacement book:** the same-instant replacement after a replacement-reason CANCEL decides on the public book, without the just-cancelled own legs | engine correction (defect) | Defect found in code by the shadow-gate review (2026-10-06): the frozen loop re-used the pre-cancel book, so the cancelled own size counted as competing liquidity and displayed depth for the replacement. Live parity: live decides again only after the cancel is acknowledged, on a book without those orders. Not motivated by any outcome. | Replacement QUOTEs differ from the frozen loop where cancelled legs sat on public levels; the replacement still happens at the cancel instant (live: after acknowledgement), and that timing is not changed. |

##### (b) KED: Kernel as-is, with known engine deviation KED-2

**T2 (the KED-2 transform):** the replacement decides on the **pre-cancel decision book** (the book of the CANCEL
decision at the same instant, i.e. `C_book` under the W1 ruling applied to the cancelled legs), with `existing = ()`
and the post-cancel portfolio.

**Classification**, at every same-instant replacement, as §3.7.1(b) steps 1-5 with `B_ruled = public` and
`B_T2 = the CANCEL decision's book`:
- `KED2_SILENT` / `KED2_DIVERGENT` / FAIL by the same rules;
- re-anchoring is the same.

**Caps (per day).**
- `KED2_DIVERGENT` ≤ **20 %** of same-instant replacements **and** ≤ **1 %** of record-driven decisions. Otherwise
  `INCOMPLETE (ked_cap:KED-2)`.
- **S-REQUOTE credit only from non-divergent replacements.** A cluster whose only S-REQUOTE transitions are
  `KED2_DIVERGENT` is not credited.

**Registration disclosure:**

> KED-2: the engine's same-instant replacement decides on the pre-cancel book, so the cancelled own size counts as competing liquidity and displayed depth. Live decides after the cancel acknowledgement on a book without it. The gate counts and caps the replacements this changes.

**Live consequence under (b).** Live never runs a same-instant replacement (§4.4 L5). Its replacement decides on the
post-acknowledgement venue book, which is (a)'s semantics. So under (b), paper's S-REQUOTE certifies a composition live
does not run, on every divergent replacement. That is why credit is restricted.

#### 3.7.3 Why (a) is recommended, and what does not depend on the choice

- **(a)** costs one reviewed U3 edit and a re-run of pre-signature artefacts, and no panel outcome exists yet. It
  makes paper, the frozen exam engine and live agree with the venue. And the oracle encodes no defect.
- **(b)** keeps two known defects in the exam and in live, and makes the oracle implement T1/T2. That puts kernel
  behaviour into the clean-room module in exactly the area Tier I exists to check. Its caps are judgement numbers, and
  divergent decisions lose stratum credit.
- **Independent of the choice:** §2.2, §3.3, §3.6, §4.5-4.8, §5, §6.1-6.2, §6.4-6.8 (except the KED counters), §8,
  §9 (except the KED credit rule), §10-§14 structure, and every mutant other than MKED*/MW*.
- **Choice-dependent:** I2's book (`C_book`), I12/I14's replacement book (`R_book`), the KED counters and caps, the
  label element, two registration texts, and L1's live composition.

---

## 4. Shadow composition change: work unit S1 `[v3.1 CHANGED]`

### 4.1 Providers injected into the runner `[v3.1 CHANGED — M-CF, M-T, N-f]`

v3 §4.1 applies, with these row changes:

| Provider | v3.1 rule |
| --- | --- |
| Info events | Plugin `WeatherInformationClock` **as on the build line** (CF-1 not required, MA31-1) over the shadow's own store. Observation triggers come from the same source set production's trigger loop uses on the day, read independently by a workstation copy of `detect_observation_triggers` (unchanged code, module-hash bound). WU history is in that set on both sides **only** under OD15, which is decided yes (CONSOLIDATED §5), and only with §4.8 in force. Never on one side only. |
| Observation input store | Every **API JSON body** is stored with SHA-256, fetch instant and HTTP status. Page bodies are never stored (§4.8). Failures are `input_gap` rows carrying enumerated codes only (§4.8). |
| WU page fetch (new, N-f) | The token is scraped from the public history page at most **once per 30 min** per process and held **in memory only**. A token-rejected API reply (401/403) triggers at most one re-scrape, then backs off. Page failures (`page_*` codes) and API failures (`api_*` codes) are counted separately. |
| Hostname pin | As v3, with `www.wunderground.com` and its API host **in** the list (OD15 decided). |

### 4.4 Live adapter, and what live will actually run `[v3.1 CHANGED — W1, W2, M-L, M-D]`

v3 §4.4's text is `[v3.1 KEPT]`, with these additions and row replacements.

**Binding (new).**
- **Byte-identical import.** The live preflight hashes every cohort-bound adapter module (`maker_core.shadow.
  live_kernel`, `maker_core.shadow.contract`, `maker_core.replay.v2.kernel`, `maker_core.quoting.policy`, the plugin
  modules) **as imported by the live process** (`module.__file__` bytes), and refuses to start unless they equal the
  cohort binding.
- **Deltas only in `maker_core.live.*`.** Live deltas L1-L7 live only in `maker_core.live.*` modules. They may
  subclass or wrap the adapter, never edit it. The Tier L receipt binds the `maker_core.live.*` hashes.
- **Any change to a bound module voids MET for live use**, until a new cohort reaches MET.
- **Owner.** Tier L is a named work unit, **TL (live executor and Tier L suite)**, with an owner named by the owner
  (OD21). It must deliver before any live preflight cites a MET summary. OD13's Tier L receipt hash is TL's deliverable.

**Row replacements:**

| Delta | Paper (shadow and replay) | Live | Tier L gate (fixture differential; must pass before first live) |
| --- | --- | --- | --- |
| **L1 Own legs in the book** | `C_book(public, legs)` (§3.7.1) | The venue book V already shows acknowledged own orders O. Live decides on `live_inputs(V) = paper_compose(V ⊖ O, O)`.<br>• `⊖` removes each acknowledged own order's open size from all four arrays by the mirror rule (§3.7.1(a)'s table): `min(level size, own size)` per (array, price).<br>• `paper_compose` is `C_book` under the ruling: (a)'s composition, or T1 under (b).<br>• **Live never decides on raw V.** | • (1) `⊖` tests across partial fills (open size, not original size), same-price aggregation of own and public size, and mirroring.<br>• (2) Under (a), `live_inputs(V) == V` on every fixture where the venue echoes O by the mirror rule.<br>• (3) **Echo check:** an array whose level at an own price is smaller than the own open size is counted as `OWN_ECHO_SHORT`. Persisting over 2 consecutive book snapshots → the condition's pull `UNKNOWN_ACCOUNT_STATE`. Tested.<br>• (4) **In-flight rule:** while an order of the condition is submitted-not-acknowledged or cancel-pending, the adapter still runs the full Kernel chain (I14 precedence) on the best-known composition, with in-flight placements treated as resting. If the outcome is any **pull or CANCEL** (`DECIDED`, `INFO_PULL`, `SAFETY_BUDGET`, `UNKNOWN_ACCOUNT_STATE`, `OUTSIDE_ACTIVE_INTERVAL`, every coverage pull, `LAST_THREE_HOURS`, any `decide()` CANCEL), it is **issued immediately**, cancelling in-flight orders by client id. Only a QUOTE, replacement or HOLD-dependent placement waits for resolution. Test: an order in flight plus a `DECIDED` event, and plus `SAFETY_BUDGET` → cancel issued at the same logical instant. |
| **L2 Fills** | `fill_model.match`, one fill per leg, then the sibling cancel | Authenticated user-channel fills, possibly several per leg | v3's L2 tests, plus a **partial-fill race fixture**: partial fill on leg A → `CANCEL FILL_CANCEL_SIBLING` sent → a second fill on leg A **and** a fill on sibling leg B arrive before the cancel acknowledgement.<br>• The ledger accepts every post-cancel fill (lots, `inventory_cost`, ledger cash); band room shrinks; `active_other_bands` and exposures update.<br>• No QUOTE for the condition until every cancel is acknowledged and the I14 chain passes.<br>• The extra inventory over paper is reported as `LIVE_POST_CANCEL_FILLS` (paper cannot produce it; disclosed). |
| **L5 Order outcomes and replacement** | Same-instant replacement on `R_book` (§3.7.2) | The replacement decision runs only **after** the cancel acknowledgement, at a later logical instant, on `live_inputs` of the then-current V | Fixture differential: with no other record between cancel and acknowledgement, the live replacement equals paper's same-instant replacement in decision fields (under (a); under (b) it equals `D_ruled`, the KED-2 counterpart). Venue rejections and partial placement as v3. |
| **L7 Session shape** | Day-session flat | Cannot flatten inventory | v3's rule as a **hard preflight check** (M-D, OD4), not a recommendation. The live preflight refuses unless:<br>• (i) the session's quoting window lies inside one UTC day and ends at that day's horizon cancel;<br>• (ii) no lot from any earlier session is unsettled;<br>• (iii) no earlier session is open.<br>Tested by three refusal fixtures.<br>**NOTE (paper/live gap):** a print stamped exactly `D+1 00:00:00` is processed by the flat D+1 instance, while the venue can still fill a resting order until the horizon cancel is acknowledged. Live counts such fills as `LIVE_POST_CANCEL_FILLS` (L2). |

L3, L4 and L6 are `[v3.1 KEPT]`.

### 4.6 Tape v0.3 `[v3.1 CHANGED — M-T, M-D]`

v3 §4.6 applies, with these changes:
- the raw block stores Gamma bodies, NBP texts and **observation API JSON bodies** on change, **never a page body**
  (§4.8);
- `record` rows carry `reopen: bool` (§3.3);
- `input_gap` rows carry only `{source, channel, code, http_status|null, at}`, where `code` is from §4.8's enumeration;
- every segment is written through §4.8's sealed writer.

### 4.8 Secret hygiene (OD15 condition) `[v3.1 NEW — M-T, MA31-3; every rule below is REQUIRED]`

OD15 permits WU history access that sends the page-scraped token, on the condition that **the token never goes into
logs, tapes, commits or anything pushed**. The rules below implement that condition. Each one is a gate precondition.
A cohort whose bound code lacks any of them cannot start.

**Module.** `maker_core.shadow.secrets` (bound, §2.3). It holds:
- the process's **in-memory token set**: every token value scraped in this process's lifetime, never written anywhere;
- the scanner;
- the sealed writer.

The production trigger loop and the gate-purpose exporter use the same module on the capture host.

1. **Store only the API JSON body.**
   - The API reply body (JSON) is the only stored observation input. B0w rebuilds from it.
   - The **page body is never stored**: not in the input store, the tape, a bundle or a log. Only its SHA-256, byte
     length and HTTP status are recorded.
   - The **request URL and query string are never stored**. A request is identified by
     `(source, station, endpoint path without query, date range)`.
2. **Enumerated error codes only.** `input_gap` rows, missing-data reasons, receipt `presence`/`missing` entries,
   `clock` rows and any error field in any persisted object carry exactly one code from this closed set:
   - `page_http_<status>`, `page_timeout`, `page_connection_error`, `page_token_not_found`, `page_parse_error`;
   - `api_http_<status>`, `api_timeout`, `api_connection_error`, `api_json_invalid`, `api_token_rejected`;
   - `tls_error`, `rate_limited`, `unclassified:<ExceptionClassName>`. The class name is checked against an
     allowlist of exception classes; anything else becomes `unclassified:other`.

   Codes are produced by `failure_class_for_exception` (`wu_history.py:155-174`) plus the HTTP status. Never
   `str(exc)`, `repr(exc)`, a traceback, a URL or a query string. The shadow's `type(error).__name__` pattern
   (`maker_shadow.py:230`) is the model. The two existing `str(error)` paths (G9, `maker_shadow.py:151`, `:292`) are
   converted.
3. **Token scan at seal.**
   - Every persisted output passes through the sealed writer: tape segments, input-store files, the identity sidecar,
     gate-purpose bundles, attestations, receipts, summaries, `b0w_result`, control and re-drive outputs, and log
     files this code writes. The writer writes to a temporary file in the target directory, then scans its bytes.
   - The scan looks for:
     - every value in the in-memory token set, in raw form, URL-encoded (`quote` and `quote_plus`) and JSON-escaped;
     - the structural patterns of `redact_api_key` (`wu_history.py:123-138`), case-insensitive: `apiKey=<non-empty
       value>`, `"API_KEY": "<non-empty>"`, `'API_KEY': '<non-empty>'`, and the URL-encoded `apiKey%3D`. The literal
       values `<page-token>` and `<redacted>` are exempt.
   - **On a hit:** the write is refused and the temporary file is truncated and removed (the only deletion this
     module may perform, of a file it created and never published). The day records `REFUSED (secret_in_output)`
     with the output's path class and the pattern id, **never the matched bytes**, and an alert is raised through
     the existing alert channel.
4. **Token scan at transfer, both ends.**
   - The transfer tool on the capture host (send) and on the workstation (receive), and the gate before reading, scan
     every file of the package with the structural patterns.
   - Each end also scans with an **exact current token**: the end obtains it with one fetch of the public page, under
     OD15. It is held in memory only and discarded after the scan.
   - The production trigger rows, the identity sidecar and the gate-purpose bundle are covered by this scan.
   - A hit → transfer refused, `REFUSED (secret_in_output)` for the dates in the package, and an alert. The package
     is not moved.
5. **Loggers pinned.**
   - In the shadow, the trigger loop, the exporter, the transfer tool and the gate CLI, the `urllib3`,
     `urllib3.connectionpool` and `requests` loggers are set to `WARNING` or above at process start.
   - The process **refuses to start** if any of them, or the root logger's handler chain, would emit DEBUG or INFO
     records from those loggers (checked with `isEnabledFor`).
   - `sys.excepthook` and `threading.excepthook` are replaced by a handler that writes only the exception class name,
     the enumerated code and a redacted traceback (frames' file:line, no locals, every message passed through
     `redact_api_key` plus exact-token replacement).
   - Scheduled-task stderr capture files are scanned when they rotate (rule 3's scanner); a hit raises the alert.
6. **Repository check.**
   - A ratchet test (`tests/maker_core/test_no_wu_token_in_repo.py`) runs over every tracked file (`git ls-files`).
     It fails on any `apiKey=` value or `"API_KEY"`/`'API_KEY'` value other than the literal placeholders
     `<page-token>` or `<redacted>`.
   - Fixtures use `<page-token>`.
   - The test also fails on any tracked file that contains a WU API URL with a query string.
7. **Mutants** (§15): MT1-MT4.
8. **Tier I.** The oracle reads no observation replies (§6.3 inputs). Its violation list carries **identities and
   hashes only**: invariant id, condition id, logical instant, record kind, payload SHA-256, field path, and the
   SHA-256 of the canonical expected and observed values. Never raw input bytes, decoded levels or messages.

**Scope note.** These rules bind the shadow, the gate and the capture-host components this gate adds or uses (the
exporter, the transfer tool and the trigger rows they read). Production's existing trigger loop is changed only by CF-1
and OD15 work owned elsewhere. Rule 4's transfer scan protects the gate from that loop regardless.

---

## 5. Inputs, transfer and provenance `[v3.1 CHANGED]`

v3 §5 applies, with these changes:
- **§5.3:** the transfer tool also runs §4.8 rule 4 at both ends; a hit refuses the package.
- **§5.4:** the identity sidecar's `info_event` source identity is `(source, station, observed_at, value, API body
  SHA-256)`, never a URL.
- The gate-purpose exporter emits the day-open re-emission (§3.3).

---

## 6. What is compared `[v3.1 CHANGED]`

### 6.3 Tier I: the independent composition oracle `[v3.1 CHANGED — W1, W2, M-I, M-T]`

v3 §6.3 applies, with these changes.

**Independence (amended).**
- **Forbidden names, stated explicitly (M-I).** The oracle may not import `policy._event_active`, `policy.
  external_levels` (nested), `prices.*` or any `policy` name other than `decide`, `DecisionInputs`, `Portfolio`,
  `ExposureLimit`, `QuoteLeg` and the profile constants. It implements its own event-activity predicate, its own
  composition (`C_book`, `R_book` and, under (b), T1/T2) and its own coverage, freshness and pull chain, all from
  this section's text.
- **Physical clean room (M-I; OD18 amended).**
  1. The oracle author works in a fresh worktree from which `src/maker_core/replay/**` and
     `src/maker_core/shadow/{live_kernel,contract,runner,paper,tape}.py` are **deleted before the session starts**.
     The deletion commit is the first commit on the oracle branch, and the PR shows it.
  2. The author is given only this spec, v3 and v2, `maker_core/contracts`, `maker_core/quoting/policy.py`
     (`decide()` is common-mode and declared) and the 89a contract text.
  3. The author is a **different agent from S1's adapter author, and a different model or harness** (for example
     Codex vs Claude) where one is available.
  4. The oracle PR is **opened before** the cross-validation test file is written.
- **OD18 limits, stated honestly.**
  - The clean room removes the Kernel's *code* from view, not its *design*: §3, §3.7 and this section transcribe the
    Kernel's rules. A defect that lives in the written design (as W1 and W2 did) is reproduced, not caught.
  - "Absent from the worktree" does not prove "never seen". The author may have read `kernel.py` in an earlier session,
    and swarm agents share training and habits. A different model reduces that common mode but does not remove it.
  - The label element `ORACLE_SPEC_DERIVED_FROM_KERNEL` says this. Tier I proves the implementation against the ruled
    design.
- **Cross-validation resolution rule (M-I).** A disagreement between the oracle's fill predicate or decoder and
  `_fill89a.filled_size` or `payloads` is resolved only by a **written ruling against the 89a fill contract text**,
  recorded as a numbered spec erratum (`D-shadow-gate-errata.md`, append-only, each entry cites the contract sentence).
  - A ruling for the contract against the engine becomes a KED (or, before signature, an engine fix under OD19's
    mechanism).
  - A ruling for the engine amends the oracle **from the erratum text**.
  - The oracle is **never** conformed by copying, importing or reading engine code.

**Inputs (amended).** v3's list, plus `reopen` records (§3.3). Never observation replies or page bodies.

**Event activity (M-I).** I6, I9, I10 and I14 judge an event's activity at instant t from the **latest info-event
record with record instant ≤ t** for the condition, never from a record that arrives later. The oracle's activity
predicate, written from the contract:
- inactive if `active_until_utc` is set and `t > active_until_utc`;
- otherwise active iff `detected_at_utc ≤ t` when `detected_at_utc` is set;
- else iff `observed_at_utc ≤ t` when `observed_at_utc` is set;
- else iff `scheduled_at_utc − 3 min ≤ t ≤ scheduled_at_utc + 10 min`.

**Invariant changes.**

| # | v3.1 text |
| --- | --- |
| I2 Own legs in book `[CHANGED — W1]` | For each record-driven decision, the recorded `inputs.book` equals `C_book(public_t, legs_t)`, where `public_t` is the oracle-decoded public book at the latest raw body ≤ t per side and `legs_t` is the oracle's leg ledger. Under (a): the four-array, level-creating, size-summing composition of §3.7.1(a). Under (b): the same, with §3.7.1(b)'s KED-1 classification. `as_of = min(side receipts)`; `post_only_available` unchanged. For a same-instant replacement, the recorded book equals `R_book(public_t)` (§3.7.2; under (b), with the KED-2 classification). |
| I12 Reference composer `[CHANGED — W2]` | As v3, with the book from I2 (replacement: `R_book`). |
| I13 Wake sufficiency `[CHANGED — M-I]` | See the exact field list below. |
| **I14 Decision content** `[NEW — M-I]` | For **every** recorded decision, including Kernel pulls, the oracle independently runs the precedence chain below and requires the same `action` and the same `reasons[0]`. Decisions not reached by step 9 are pulls: action `CANCEL` if legs rest, else `NO_QUOTE`. `input_hash` is excluded. |

**I14 precedence chain** (at a wake of condition c at instant t, after every record at t is ingested; first match
wins):
1. **Inactive.** t is not inside one of c's active windows: if legs rest → `CANCEL OUTSIDE_ACTIVE_INTERVAL`; else
   **no decision** (a recorded decision here is a violation).
2. **Coverage.** In this order:
   - `MISSING_DESCRIPTOR`, `MISSING_BOOK`, `MISSING_TERMS`, `MISSING_OUTCOME_VIEW`, `MISSING_INFO_EVENT`,
     `MISSING_COVERAGE` (first kind with no record yet this instance);
   - `CAPTURE_GAP` if the book age `t − book.as_of_utc ∉ [0, max_book_gap_seconds)`;
   - `TRADE_CAPTURE_GAP` if the coverage is not `trade_stream_ok` or `t ≥ coverage.valid_until_utc`;
   - `TERMS_CAPTURE_GAP` if the terms age `∉ [0, 3600] s`.
3. *(Not in gate scope: `BASELINE_NO_QUOTE`, `CLOCK_ONLY_PULL`; informed-v0 only. Any occurrence is a violation.)*
4. **Fill instant.** A fill of c at t → **no further decision** at t beyond the sibling cancel (I11).
5. **Latched.** `DECIDED` if the decided latch is set. The latch is set when an info-event record is ingested whose
   event has `decided[c] ≥ .5` and is active at ingestion, or at step 6. (`SESSION_ENDED` and `SETTLED` are
   unreachable in scope; any occurrence is a violation.)
6. **Decided now.** An event active at t with `decided[c] ≥ .5` → `DECIDED`, and the latch is set.
7. **Resume latch.** If set at `t_p`, and no active event has `action_hint == "pull"`: if the freshness clock (the
   latest book's `as_of_utc`) ≤ `t_p` or the latest view's `as_of_utc` ≤ `t_p` → `AWAIT_FRESH_REENTRY_INPUTS`;
   otherwise the latch clears.
8. **Cooldown.** Flat, a previous QUOTE exists, and `t − last_quote < 60 s` → `REQUOTE_COOLDOWN`.
9. **`decide()`** on the oracle-composed inputs (I12). If it returns `INFO_PULL` and the resume latch is clear, it
   latches at t.
10. **Replacement.** If step 9 returned `CANCEL` with `reasons[0]` ∈ {`OUTSIDE_REQUOTE_WINDOW`, `TOUCH_BUFFER`,
    `SIZE_BELOW_MINIMUM`, `ADVERSE_LEG_CHANGED`, `REQUOTE_REQUIRED`, `UNCALIBRATED_ASYMMETRY`} (the closed list
    `REPLACEMENT_REASONS`, `kernel.py:41-42`, transcribed in the oracle as text)
    and (no previous QUOTE or `t − last_quote ≥ 60 s`) → a second decision at t: `decide()` on `R_book`, with
    `existing = ()` and the post-cancel portfolio.

I14 makes spurious pulls visible: a wrong coverage or `CAPTURE_GAP` computation in the Kernel produces a recorded pull
whose reason the oracle does not reach.

**I13 exact wake-field list (M-I).** The oracle's change detector fires for condition c at t if and only if one of
these changes across the instant (registration draft §5 rules 1-6):
- **Book (rule 1):** the decoded public `yes_bids`, `yes_asks`, `no_bids`, `no_asks` (merged, zero sizes dropped,
  sorted) and `post_only_available`. **Excluded:** `as_of_utc`, own legs, the composed book. An invalid book record
  is a change.
- **Coverage (rule 2):** the coverage state (`trade_stream_ok`, validity at t). A refresh that leaves the state
  unchanged is not a change.
- **Terms (rule 3):** `(min_size, max_spread_cents, rate_per_day)`. **Excluded:** `as_of_utc`.
- **View and events (rule 4):**
  - an available view's `(condition_id, p_yes, joint sorted, valid_until_utc, calibration_grade, model_id,
    inputs_hash)`; an unavailable view's `(reason, kind)`. **Excluded:** `as_of_utc` and `stdev`;
  - the info-event record's payload SHA-256.
- **Fill (rule 6):** a fill of a resting leg of c at t.
- **Timers (rule 5)**, at their due instants:
  - book `as_of + max_book_gap_seconds`;
  - terms `as_of + 1 h + ε`;
  - an available view's `valid_until_utc`;
  - each event's `scheduled − 3 min`, `scheduled + 10 min + ε`, `active_until + ε`;
  - `close_at_utc − 3 h`;
  - the active-window edges and coverage `valid_until_utc`.

**Excluded as wake sources:** descriptor changes (they move only the close timer), other conditions' events,
portfolio changes, the 10 s staleness threshold, the 60 s cooldown end and the `sigma_eff` crossing. I13 holds when
every firing has a decision for c at t (unless a fill suppressed it, I11), and every decision is at a firing or at the
horizon.

**Pass criterion (amended).** Zero I1-I14 violations on the shadow tape and on R_p over the closed day, and, under
(b), KED counts within their caps.

### 6.7 Tier C and MG-1 `[v3.1 CHANGED — M-U, G10]`

v3 §6.7 applies, with these additions:
- **U7 bound.** The U7 guard module hash is in the cohort binding, and no cohort starts before U7 lands (§2.1). The
  AST "guard called first" test stays.
- **Settlement and scoring readers ratcheted out.** A package ratchet (`tests/maker_core/test_gate_import_closure.py`)
  computes the **transitive** import closure of `maker_core.shadow.gate.*` and `weather.market.maker_shadow_gate*`.
  It fails if the closure contains any settlement, ledger or scoring reader:
  - any module whose dotted name contains `settlement`, `fair_value_score` or `scor` under `weather.model`/
    `weather.market`;
  - the settlement-ledger loaders in `weather.market.maker_plugin_sources`;
  - any module on an explicit deny list kept in the test.

  This stops a diagnostic from declaring a harmless metric class and then joining settlement. If B0w's closure
  through `maker_plugin.fair_value` hits a denied module, S1 must split the import before the cohort, not allowlist
  it.
- **Hazard constant provenance.** `hazard_per_minute` (required by `policy.py:261-264`) comes from the replay
  calibration (`calibration.py:193`). The cohort binding records:
  - the calibration receipt's SHA-256;
  - its recipe (the registration's hazard recipe and the `max_m U_m` scalar);
  - the **exact date set** it was computed from.

  The gate refuses (`REFUSED (hazard_provenance)`) if any of those dates is ≥ 2026-09-30, or if the provenance is
  absent. Both sides use the identical value (v2 §2 item 3).

### 6.8 Tier P `[v3.1 CHANGED — M-CF]`

| # | v3.1 rule |
| --- | --- |
| P1 | `[v3.1 KEPT]` |
| P2 `[CHANGED]` | `SHADOW_MISSED_PULL` → **FAIL** only for a production pull-class event affecting a compared condition that, at the event instant, **has resting legs or is at horizon 1 or 2**. Under G7 this set is empty today, so P2 stays as a tripwire. Other missed pull-class events are counted under P3. |
| P3 | `[v3.1 KEPT]` |
| P4 `[CHANGED — demoted]` | **Reported liveness diagnostic.** Per side, per bound observation source, per quoting market-day: reads per hour, with page and API failures separate (§4.1). No verdict effect. If the §2.1 tripwire test ever fails, P4 returns as `REFUSED (channel_absent:observation)` by rule. |
| P5 | `[v3.1 KEPT]` |

---

## 7. Controls `[v3.1 CHANGED — M-CF, M-D, W2]`

v3 §7 applies, with these changes:
- **Family X adds Kx8:** the day-open re-emission is skipped in the adapter's D+1 instance (§3.3). It is killed by B1
  at the D+1 window-start wakes (R_s holds the reopen records).
- **Kx7 redefined:** "window-start wakes at `D+1 00:00` not emitted" (no longer "MISSING_* pulls").
- **Family R:** Kc3 (observation triggers dropped) stays as a fixture mutant (MP1). It is **removed from S-INFOPULL's
  map** (M-CF).
- **Family S adds** KS12 (replacement decides on the pre-cancel book) → I12/I2. Under (a) it is an ordinary control.
  Under (b) it **is** the engine, so KS12 is replaced by MKED1-style fixture mutants only.
- **Stratum map changes:**

| Stratum | Required for MET | Mapped controls |
| --- | --- | --- |
| S-REQUOTE: replacement CANCEL followed by a same-instant QUOTE (paper; label `PAPER_SAME_INSTANT_REPLACEMENT`) | yes | Kx3, KS6, KS12 (under (a)) |
| S-INFOPULL: `INFO_PULL` or `DECIDED` withdrawal | yes | KS9 (scheduled `pull` prints and model-cycle events feed it, `clock.py:35-36`) |
| S-DAYCLOSE / S-DAYOPEN | no | Kx6, Kx7, Kx8 |

Under (b), S-REQUOTE credit follows §3.7.2(b), and every stratum excludes transitions at `KED*_DIVERGENT` instants.

---

## 9. Tolerances and statistics `[v3.1 CHANGED]`

### 9.1 Zero-tolerance checks

v3 §9.1, with "Tier I (I1-I13)" replaced by "Tier I (I1-I14)" and `secret_in_output` added. `SHADOW_MISSED_PULL` is
restricted as P2 (§6.8).

### 9.2 Measured quantities

v3 §9.2 rows apply, plus:

| Quantity | v3.1 floor or cap |
| --- | --- |
| `KED1_DIVERGENT` (under W1(b)) | ≤ 2 % of record-driven decisions and ≤ 10 % of QUOTE decisions per day |
| `KED2_DIVERGENT` (under W2(b)) | ≤ 20 % of same-instant replacements and ≤ 1 % of record-driven decisions per day |
| `KED*_SILENT` | Reported, uncapped |
| `OWN_ECHO_SHORT`, `LIVE_POST_CANCEL_FILLS` | Tier L only; not daily gate quantities |

### 9.4 Fill evidence `[v3.1 CHANGED — M-S, N-b, N-c, MA31-4]`

**RE-1 fill count: PENDING RECONCILIATION (MA31-4).**
- `FINDINGS_DIGEST.md` line 25 says RE-1 has four fills.
- Lines 89-101 describe a session-1 fill **and** "four fills" in sessions 2-8, which reads as five.
- The reconciliation is being done separately. **Until it lands, v3 §9.4's projection table is provisional**, and
  OD11 may not be decided on its numbers.
- Placeholder for the reconciled values: `RE1_FILLS_TOTAL = <pending reconciliation>`,
  `RE1_FILLS_AT_PRICE = <pending reconciliation>`, `RE1_FILLS_STRICTLY_THROUGH = <pending reconciliation>`.
- When filled, the table is recomputed by the formulas below and the result is recorded here, with no other change to
  the rule.

**Separate at-price fills from strictly-through fills (N-b).** RE-1's fills are live fills, which include fills at the
quoted price from queue position. Session 1's fill was a taker trading at the quote price against makers ahead of
ours (`FINDINGS_DIGEST.md:93-94`). Paper `strictly_through` never counts such an event.
- The projection for **real `strictly_through` paper fills** uses only `RE1_FILLS_STRICTLY_THROUGH` (prints strictly
  through the quoted price on the YES axis).
- The projection for the **`at_price` re-drive** (option 2) uses `RE1_FILLS_AT_PRICE + RE1_FILLS_STRICTLY_THROUGH`.
- The classification of each RE-1 fill is part of the reconciliation, and the classifier is the 89a contract text
  (conservative vs optimistic).
- If a fill cannot be classified, it counts as at-price only. That is the conservative direction for the
  `strictly_through` projection.

**Formulas (unchanged method).**
- Jeffreys posterior `Gamma(n + 0.5, exposure)` for the rate; predictive negative binomial for the count.
- **Report expected power, not power at the expected count (Jensen, N-b):**
  `E[1 − (1 − q)^N] = 1 − (1 + q·t/E)^{−(n + 0.5)}`, where t is the window (in mapping units) and E the exposure.
- *Illustration only, provisional:* mapping A, q = 10 %, 21 days, n = 4 gives 65 % (v3 quoted ≈ 70 % at the
  expected count); n = 5 gives 72 %.

**Synthetic-print re-drive, diversified (M-S)** (replaces v3 option 3's single-print design):
- For each condition-day, for each of the first ≤ 3 resting-leg spans of ≥ 2 min, the generator draws one cell from a
  fixed-seed cycle over **12 cells**: {YES-token print, NO-token print} × {target first leg (YES), target second leg
  (NO)} × {one tick strictly through, exactly at price, oversize (through, print size = 2 × leg size)}.
- NO-token prints are generated on the NO price axis, so the `1 − price` normalisation (`fill_model.py:37-40`) is
  exercised.
- The "second leg" cells are placed strictly through the NO leg and not through the YES leg (the two are disjoint on
  the YES axis), so `match`'s leg-order loop reaches the second leg.
- **At-price cells are negatives:** under `strictly_through` they must produce **no** fill. Under the `at_price`
  re-drive they must fill. A fill (or no fill) other than the predicate's → I3 violation.
- **Oversize cells:** fill size = leg size exactly.
- **Same-instant placement:** at least **one injection per day** (per side, symmetric) is placed **at the logical
  instant of a real book record** of that condition. It is ingested first, as prints are (`engine.py:132-161`), which
  exercises Kx2 and the §4.5 barrier on a non-vacuous instant. The remaining injections go at span midpoints, as v3.
- **Counting:**
  - only **positive** synthetic fills count toward the 29 synthetic fill clusters;
  - negatives are counted separately, and every one of the 12 cells must occur ≥ 5 times over the cohort, or the fill
    rule is unmet (`NOT_MET (synthetic_cell_coverage)`).
- **Limits, stated:** I3 is tautological for positive synthetic cells, because the generator satisfies the predicate.
  B1 is common-mode on them. Their power comes from I4, I5, I7, I11 and I14 (Tier I), and from the negatives.

Options 1, 2 and 4 and the recommendation are `[v3.1 KEPT]`, pending the reconciled numbers.

---

## 10. Per-day verdict `[v3.1 CHANGED]`

v3 §10 applies, with these changes:
- **`REFUSED` removes** `observation_channel_unsourced` and `channel_absent:observation`. The latter returns only by the
  §2.1 tripwire rule.
- **`REFUSED` adds** `secret_in_output`, `hazard_provenance`.
- **`FAIL` adds** any I14 violation, and any I2/I12/I14 violation not classified as a KED under (b).
- **`INCOMPLETE` adds** `ked_cap:KED-1`, `ked_cap:KED-2` (under (b) only).

## 11. Missing data `[v3.1 CHANGED — M-CF]`

v3 §11's row "observation source down on one side" is replaced: gap-covered misses are `ABSENT_OBSERVATION` (P3).
P4 reports the read rate and does not refuse.

## 12. The seven-day rule `[v3.1 CHANGED]`

v3 §12 applies, with these changes:
- **Cohort binding:** removes `cf1_commit`. Adds:
  - the U7 guard hash;
  - `engine_ruling`;
  - the corrected-Kernel hash under (a);
  - the `maker_core.shadow.secrets` hash;
  - the hazard calibration receipt and its date set;
  - the reopen rule version.
- **MET** adds the synthetic cell-coverage rule (§9.4). Under (b), it also adds the KED caps on every counted day.
- **Timeline:**
  - "CF-1 must land before 11-10" is **removed** (MA31-1);
  - under (a), the Kernel fix lands by 10-11 (U3) and before the 10-13 rehearsals;
  - U7 lands before the cohort start;
  - OD11 waits for the RE-1 reconciliation (MA31-4).

## 13. Receipt and summary `[v3.1 CHANGED]`

v3 §13 applies, with these changes:
- `binding` adds `u7_guard_sha256`, `engine_ruling`, `secrets_sha256`, `hazard {receipt_sha256, dates[]}` and
  `reopen_rule`. It removes `cf1_commit`.
- `tier_i` violations are `{invariant, condition_id, at, kind, payload_sha256, field, expected_sha256,
  observed_sha256}` only (§4.8 rule 8).
- `tier_i` adds `ked {ked1_silent, ked1_divergent, ked2_silent, ked2_divergent}` under (b).
- `presence.liveness` is diagnostic and carries `{source: {page_failures, api_failures, reads_per_hour[]}}`.
- `fills` adds `synthetic_cells {cell: {positive, negative}}` and `re1_reconciliation: "pending" | <commit>`.
- `secrets {outputs_scanned, transfer_scans, hits: 0}`. A non-zero `hits` makes the day `REFUSED`.
- The summary's `kernel_oracle_scope` lists I1-I14.

## 14. Module layout `[v3.1 CHANGED]`

v3 §14 applies, plus:

| Module | Responsibility |
| --- | --- |
| `src/maker_core/shadow/secrets.py` | §4.8 token set, scanner, sealed writer, logger pins, exception hook |
| `src/maker_core/replay/v2/kernel.py` (U3, under (a) only) | `compose_book`; the replacement book (§3.7) |
| `src/maker_core/live/*` (TL unit) | Live deltas L1-L7 only; never edits bound modules |
| `tests/maker_core/test_observation_scope.py` | §2.1 tripwire |
| `tests/maker_core/test_no_wu_token_in_repo.py` | §4.8 rule 6 |
| `tests/maker_core/test_gate_import_closure.py` | §6.7 transitive ratchet |
| `docs/.../D-shadow-gate-errata.md` (location by the docs owner) | Cross-validation rulings (§6.3) |

## 15. Tests and mutants `[v3.1 CHANGED]`

v3 mutants apply, with these changes:
- **MP2** now asserts that P4 **reports** both sides without reads and the verdict is **not** `REFUSED`, unless the
  tripwire test is also planted to fail.
- **MI1-MI11** run unchanged.
- **MV3** compares decision fields only (`input_hash` excluded).

New mutants:

| # | Mutant | Required outcome |
| --- | --- | --- |
| **MT1** | Page body written to the input store | Sealed writer refuses: `REFUSED (secret_in_output)`, file removed |
| **MT2** | `input_gap` row built from `str(HTTPError)` with the token in the URL | Refused at seal |
| **MT3** | Token planted in a production trigger row in a gate-purpose package | Transfer refused at the send end, and independently at the receive end |
| **MT4** | `urllib3` logger left at DEBUG in the shadow | Process refuses to start; the test that asserts the refusal passes, and the mutant run fails the test |
| MI16 | Kernel plant: `CAPTURE_GAP` computed with `≤` instead of `<` (spurious pull at the boundary) | B1 clean; Tier I `FAIL` I14 |
| MI17 | Kernel plant: resume latch checks only the book clock | Tier I `FAIL` I9/I14 |
| MI18 | Oracle change detector wakes on view `stdev` | The oracle's own conformance test (Test 2b) fails on the unmutated fixture |
| MI19 | Oracle reads an info-event record later than t for activity at t | Conformance test fails |
| MI20 | Oracle violation list carries a decoded level or raw bytes | The schema test fails (identities and hashes only) |
| MW1 (a only) | `compose_book` drops created levels (frozen rule restored) | Tier I `FAIL` I2 |
| MW2 (a only) | Replacement uses the pre-cancel book (frozen rule restored; = KS12) | Tier I `FAIL` I2/I12 |
| MKED1 (b only) | KS1 (`add_own` omitted) under KED classification | Still `FAIL` (I2): not absorbed by KED-1 |
| MKED2 (b only) | A book matching neither `B_ruled` nor `B_T1` | `FAIL` (I2) |
| MKED3 (b only) | KED-1 divergent rate 3 % | `INCOMPLETE (ked_cap:KED-1)` |
| MKED4 (b only) | KED classifier disabled | Every KED instance `FAIL`s (proves classification is reached) |
| MD1 | Day-open re-emission with a re-stamped payload `as_of` | B0/B0w refuse (payload SHA differs) |
| MD2 | Re-emission fed to a carry-state engine | Decisions identical to the run without it |
| MD3 | Live preflight with a session crossing 00:00Z, or an unsettled earlier lot | Refused (L7) |
| ML1 | In-flight order plus `DECIDED` event | Cancel issued at the same instant (L1) |
| ML2 | Partial-fill race (L2) | Ledger accepts post-cancel fills; no QUOTE before the acknowledgement |
| ML3 | Live process imports an adapter module differing by one byte | Live preflight refuses |
| MS2 | Synthetic at-price negative fills under `strictly_through` | Tier I `FAIL` I3 |
| MS3 | One of the 12 cells never generated | `NOT_MET (synthetic_cell_coverage)` |
| MR2 | §3.6 proxy test without the `digest` patch | Test fails (proves the patch is required) |
| MU3 | Gate diagnostic imports a settlement loader transitively | Import-closure ratchet fails |
| MH1 | Hazard receipt with a date ≥ 2026-09-30 | `REFUSED (hazard_provenance)` |

## 16. Disposition of every v3-Defender finding

| Finding | Severity | Disposition |
| --- | --- | --- |
| W1 | BLOCKER | **Ruling required (OD19).** Two fully specified alternatives (§3.7.1): (a) the Kernel composes own legs on all four arrays with created levels, before signature, disclosed as C11; (b) KED-1, counted and capped. I2 written to `C_book`. L1 = `paper_compose(V ⊖ O, O)` with an echo check. Recommend (a). |
| W2 | BLOCKER | **Ruling required (OD20).** (a) the replacement decides on the public book, disclosed as C12; (b) KED-2, counted and capped, with S-REQUOTE credit only from non-divergent replacements. Live replaces after the acknowledgement (L5); label `PAPER_SAME_INSTANT_REPLACEMENT`. Recommend (a). |
| M-T | MUST-FIX | Adopted in full and required (MA31-3): §4.8 rules 1-8, MT1-MT4, the repository ratchet, the transfer scan at both ends. |
| M-CF | MUST-FIX | Adopted: CF-1 is not a dependency (MA31-1); P4 is a diagnostic; P2 narrowed; Kc3 unmapped; tripwire test (§2.1, §6.8, §7). |
| M-I | MUST-FIX | Adopted: I14; the exact I13 list; event activity at the instant; forbidden names explicit; physical clean room; erratum-only resolution; OD18 limits; label element (§6.3). |
| M-L | MUST-FIX | Adopted: byte-identical binding; `maker_core.live.*` deltas; TL unit and owner (OD21); in-flight blocks placements only; partial-fill race (§4.4). |
| M-D | MUST-FIX | Adopted: day-open re-emission with payload clocks kept; terms seeding; Kx8; L7 a hard preflight check (§3.3, §4.4). |
| M-P | MUST-FIX | Adopted: `digest` patched; separate `input_hash` coverage test; MR2 (§3.6). |
| M-S | MUST-FIX | Adopted: 12-cell synthetic set, same-instant injections, negatives counted separately, cell coverage (§9.4). |
| M-U | MUST-FIX | Adopted: U7 bound and a cohort dependency; transitive import ratchet; hazard provenance (§2.1, §6.7). |
| N-a | NOTE | Adopted (§2.2): emitted, `kind = out_of_scope`, `as_of` = record instant, `input_hash` change stated. |
| N-b | NOTE | Adopted (§9.4): at-price vs through separated; expected power reported. |
| N-c | NOTE | Placeholder **pending reconciliation** (MA31-4, §9.4). |
| N-d | NOTE | Kept in the label text (§1). |
| N-e | NOTE | Corrected (G2: `kernel.py:548`). |
| N-f | NOTE | Adopted (§4.1): page fetch at most once per 30 min; page and API failures counted separately. |

## 17. Owner decisions (updated; each with a recommendation)

OD2, OD5, OD7, OD10, OD12 and OD14 are unchanged from v2 (recommend yes as before). OD1, OD6, OD8, OD9, OD13, OD16 and
OD17 are unchanged from v3 (recommendations as v3 §17).

| # | Decision | Recommendation |
| --- | --- | --- |
| **OD19** `[NEW — W1]` | Own legs in the decision book: (a) fix the Kernel (`compose_book`, four arrays, created levels, summed) before signature, disclosed as C11, with every pre-fix v2 artefact re-run; or (b) Kernel as-is with known engine deviation KED-1, counted and capped, and disclosed. | **(a).** It makes paper, the exam engine and live agree with the venue at the cost of one U3 edit (by 10-11, before the 10-13 rehearsals). No panel outcome exists to motivate or be moved by it. (b) keeps a defect in the exam and in live, and puts it into the oracle. |
| **OD20** `[NEW — W2]` | Replacement book: (a) fix the Kernel so the same-instant replacement decides on the public book, disclosed as C12; or (b) KED-2, counted and capped, with S-REQUOTE credited only from non-divergent replacements. | **(a)**, in the same U3 change as OD19. |
| **OD21** `[NEW — M-L]` | Name the TL unit (live executor plus Tier L suite) and its owner and deadline. Bind live to the cohort's adapter modules byte-for-byte, with deltas only in `maker_core.live.*`. | **Yes.** Assign TL now, with a deadline before any live preflight that cites a MET summary. The author may be S1's, never the oracle's. |
| **OD22** `[NEW — M-CF, MA31-1]` | Record that CF-1 is off the gate's critical path and not a cohort dependency, with the tripwire test as the condition, and the v1-exam disclosure "lead-0 info events only". | **Confirm** (decided by master-agent; record it in the owner's log). |
| **OD23** `[NEW — G3]` | Under (a), informed-v0's qualified mid can move with its own resting size, as live's would. Should the policy exclude own size from the mid? | **No change before the exam.** `decide()` is frozen and common-mode, and a policy change is a new registration. Report a shadow diagnostic: the count of decisions whose qualified mid differs with own size removed. |
| OD3 `[CHANGED]` | MG-1 quoting exemption, as v3. U7 is now a **cohort dependency** (the gate binds its hash). | **Confirm the quoting exemption, and approve building U7 now**, so the cohort start is not blocked. |
| OD4 `[CHANGED]` | As v3, with the one-UTC-day first live session a **hard preflight check** (L7), not a recommendation. | **Yes.** |
| OD11 `[CHANGED]` | Fill rule, as v3 options 1-4, with the diversified synthetic set (§9.4). **Not decidable until the RE-1 fill-count reconciliation lands (MA31-4).** | **Option 3 plus option 2 reported**, as v3, confirmed after the reconciled numbers are in. Keep the pre-decided first-live cap (one band, minimum size) if real fills < 10. |
| OD15 `[DECIDED, condition recorded]` | WU history with the page-scraped token is acceptable; the token is never persisted in logs, tapes, commits or anything pushed. | **Implemented by §4.8 as required rules** (MA31-3). Master-agent records it in DECISION_LOG. |
| OD18 `[CHANGED]` | Oracle authorship: a physical clean room (forbidden files deleted from the author's worktree before the session), a different agent **and** a different model or harness where available, the PR opened before cross-validation, and erratum-only resolution. The limits are stated (design common mode). | **Yes**, accepting the stated limits and the `ORACLE_SPEC_DERIVED_FROM_KERNEL` label. |

---

## Summary (10 lines)

1. v3.1 is a narrow amendment of v3. Every change is tagged against v3, and the four coordinator decisions (MA31-1…4) are applied.
2. W1 (own legs in the book) and W2 (the replacement book) are each written as (a) a Kernel fix before signature (exact `compose_book` code; C11/C12 registration rows; a re-run of every pre-fix v2 artefact) and (b) a KED-1/KED-2 class (written transforms T1/T2, classification with re-anchoring, caps, lost stratum credit). (a) is recommended for both.
3. Everything else refers only to `C_book`/`R_book` and is independent of the choice. The ruling is bound into the cohort as `engine_ruling`.
4. §4.8 secret hygiene is required (MA31-3): API JSON body only, no page body, no URLs; enumerated error codes; a token scan at seal and at both transfer ends; urllib3/requests pinned at WARNING; a repository ratchet; MT1-MT4; the oracle emits identities and hashes only.
5. CF-1 is no longer a cohort dependency (lead-0 only; tripwire test), P4 is a diagnostic, P2 is narrowed, Kc3 is unmapped, and the v1-exam disclosure covers lead-0 info events only.
6. Tier I adds I14 (every pull's content and precedence), an exact I13 wake-field list, activity judged at the instant, a physical clean room with a different model, and erratum-only cross-validation, with the OD18 limits stated.
7. Tier L binds live to the byte-identical adapter (deltas in `maker_core.live.*`) under a named TL unit (OD21). In-flight blocks placements, never pulls. A partial-fill race is tested, and L7 is a hard preflight check.
8. Day roll: re-emission at D+1 00:00 keeps payload clocks, the shadow takes an extra terms read just before midnight, and Kx8 is added. The proxy test patches `digest()`. The lead-0 redaction is pinned (`out_of_scope`, `as_of` = record instant), and the `input_hash` change is noted.
9. The synthetic re-drive covers 12 cells (NO token, second leg, at-price negatives, oversize) plus same-instant injections. U7 is bound, settlement readers are ratcheted out transitively, and the hazard constant's dates are bound (≤ 2026-09-29).
10. Fill projection: at-price and strictly-through fills are separated, expected power is reported, and the RE-1 count (4 vs 5) is a placeholder pending reconciliation. OD11 waits for it. New ODs: OD19-OD23.
