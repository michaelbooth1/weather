# D — "Shadow agrees with replay" live gate: specification v3 (amended)

Swarm M Wave 2, spec author, 2026-10-06. **Spec only.** No gate code, no commits. No gate code may be written until
this spec passes a Defender review and the owner has seen it (CONSOLIDATED §3 holds). Nothing here grants run
authority, lifts the live pause, or authorizes the O9 transfer (on HOLD).

Sources, all read-only:
- in this folder: `D-shadow-gate-spec-v2.md` (the base), `D-v2-defender.md` (V1-V5, M1-M10, N1-N7),
  `D-defender.md` (G1-G17), `CONSOLIDATED.md` §3-4 (holds, U7, MG-1 guard), `WAVE2-RULES.md`;
- the shadow tree `C:\pt\wf` at `b31185d6b` (`maker_core/shadow/runner.py`);
- the build tree `C:\wt\workstation-chat\m-v2ro` at `501f47579`: `maker_core/replay/v2/{kernel,engine,lockstep}.py`,
  `maker_core/replay/{fill_model,_fill89a}.py`, `maker_core/quoting/policy.py`,
  `weather/market/maker_plugin/{clock,fair_value}.py`, `weather/market/{maker_plugin_runner,maker_replay_bundle_v02}.py`,
  `weather/operations/observation_trigger.py`, `weather/model/{model_sources,model_constants}.py`,
  `weather/sources/wu_history.py`;
- `master` at `8e179f18a`: `src/` (searched for live composition), `docs/operations/FINDINGS_DIGEST.md` (RE-1 fill
  lines 25, 89-101 only).

No data, panel, settlement or `data/` row was read. Every master-agent message of 2026-10-06 is applied (§0.3).

---

## 0. How to read v3

### 0.1 Base and markers

v3 is a **complete amendment of v2**. v2 (`D-shadow-gate-spec-v2.md`, frozen in this folder) remains the base text.
Any v2 section or table row not restated or amended here applies unchanged and is cited as "v2 §x".
Every v3 section carries one tag against v2:
- `[v3 NEW — Vn/Mn/MA]`: not in v2 (MA = master-agent requirement);
- `[v3 CHANGED — Vn/Mn]`: v2 text replaced; the v2 text is void;
- `[v3 KEPT]`: v2 text applies, restated only where needed for reading;
- `[v3 REMOVED — Vn/Mn]`: v2 mechanism withdrawn.

### 0.2 Facts verified in code for v3 (new; several correct v2 or the v2 Defender)

| # | Fact | Evidence | Consequence |
| --- | --- | --- | --- |
| F1 | **No informed-v0 live executor exists anywhere.** `DecisionInputs(...)` is constructed only in `kernel.py:533` (and its `replace` at 547), `maker_plugin_runner.py:362` (dry-run, fixed hypothetical portfolio), shadow `runner.py:254` and `tape.py:103`. `git grep "DecisionInputs("` on master `src/` is empty. Master's `mm_live_pilot_cli.py` is the lifecycle/stage probe and never calls `decide()`. | grep over three trees | v2 §4.4's "the live executor must run this composition" is false: there is nothing to compare against today. The live executor must be built (§4.4, Tier L). |
| F2 | **Production emits no observation-sourced info events today.** The trigger loop's `wu_history` and `wu_current` fetchers raise `paid_provider_disabled` first (`model_sources.py:1017-1021, 1090-1094`; `PAID_WEATHER_PROVIDER_ACCESS_ENABLED = False`, `model_constants.py:19`). Only METAR (`aviationweather.gov`, `:1353`) and ECCC SWOB (`dd.weather.gc.ca`, `:1172`) are live. The plugin clock discards every trigger that is not `wu_history_high_increased`/`wu_history` (`clock.py:86-87`). | code on build tree and master | The `new_high`/`decided` gap is **common-mode today**, not shadow-only as the v2 Defender's V2 states. No cross-feed tier can see a common-mode gap; v3 adds an absolute check (§6.8 P4) and makes the clock fix (separate unit, called **CF-1** here) a cohort dependency. |
| F3 | **The public WU history path is free but not literally key-less.** `wu_history.py` has no paid credential (`PAID_PROVIDER_BACKFILL_ENABLED = False`, `:90`). Its public collector scrapes `API_KEY` from the public WU history page at runtime and sends it as the `apiKey` query parameter (`:283-321`). Nothing is stored, configured or owned. | code | It is free and needs no stored secret, but each request carries a page-derived token. That needs an explicit owner ruling (OD15) before the shadow or production uses it. |
| F4 | `decide()` never reads `fair_value` at a horizon outside `eligible_horizons`: `DECIDED`, `INFO_PULL` and `HORIZON_NOT_ELIGIBLE` all return before the view is read (`policy.py:255-262`, view read from `:268`). The kernel still reads the view for wakes (`view_state`, `kernel.py:179-199`) and the resume latch (`kernel.py:513-517`). | code | Lead-0 views can be redacted without changing any lead-0 `decide()` output. Only lead-0 wake counts and latch reasons change, and they change symmetrically (§2.2). |
| F5 | Lots bought on UTC day D cannot settle inside D. A lead-1 band quoted at UTC D hh:mm targets a local day that ends at local midnight, which is at or after 04:00Z D+1 for every registered station (all UTC−4…−8). | `fair_value.py:98`, registry time zones | Settlement never moves paper cash inside a gated day. The gate needs **no settlement record at all** (§2.2, §6.7, M10). |
| F6 | The fallback view (`pit-lead1-normal-fixed-2C-equivalent`) reads production `forecasts` rows (`fair_value.py:172-242`), not a public feed. | code | The shadow cannot reproduce it; this is a declared asymmetry (§4.3). |
| F7 | `view_state` includes the view's `inputs_hash`, which hashes `fetched_at` (`kernel.py:195-196`). | code | Cross-feed view wakes differ by fetch time. This is a B3 `TIMING`/`FEED_VIEW` matter, unchanged from v2. |
| F8 | At a fixed window start, `EngineV2` wakes the condition and `pull` records `NO_QUOTE MISSING_*` while flat (`engine.py:54-57`, `kernel.py:302-305, 369-376`). At the plan horizon `finish()` processes every timer ≤ D+1 00:00 (`engine.py:114-125`), so a condition with legs records `CANCEL OUTSIDE_ACTIVE_INTERVAL` there (`kernel.py:489-493`). | code | The basis of the v3 day-roll alignment (§3.3). |

### 0.3 Change index against v2

| Finding | v2 mechanism | v3 resolution | Sections |
| --- | --- | --- | --- |
| **V1** composition is common-mode under the shared Kernel | B1 + K1-K18 claimed to prove composition | **New Tier I**: an independently written composition oracle (clean-room code, import-ratcheted away from `maker_core.replay.*` and the adapter) checks every decision, leg, fill, cash and portfolio value against raw venue records. B1 is restated as **driver equivalence**. Controls are split into three families, each killed by the tier that can actually see it. The false live claim is removed; **Tier L** gates each real live delta. | §1, §4.4, §6.3, §6.4, §7, §15 |
| **V2** input-composition defects survive | B2 pairs only | **Presence conformance** (Tier P), descriptor and mapping pairs, band partition as a compared field, weather-kind B0 (**B0w**) in a `weather.*` module behind a data-only boundary, trigger source decided (shadow reads production's live sources; CF-1 dependency; OD15), absolute observation-channel liveness check, declared fallback asymmetry | §2, §4.1-4.3, §5.4, §6.2, §6.5, §6.8 |
| **V3** lead-0 served views refuse every day | allowlist over all views | **Lead-0 redaction on both sides**: the gate-purpose exporter and the shadow both emit `Unavailable("lead0_not_in_gate_scope")` at lead 0. The allowlist is scoped to horizons {1, 2}. No served vector and no settlement record crosses. | §2.2, §4.2, §5.3 |
| **V4** horizon cancels vs `day_roll` intent | `day_roll` intent, D+1 tape | **One kernel instance per UTC day**: the D instance runs the engine's horizon step at D+1 00:00:00 and writes those CANCELs into D's tape. The D+1 instance starts fresh and emits the engine's window-start pulls. B1 compares the closed day [D 00:00, D+1 00:00]. | §3.3, §6.1, §6.4, §10 |
| **V5** S-DAYROLL / K18 uncreditable | required stratum | S-DAYROLL **removed from MET**. It is fixture-proven and observed daily by B1 at both instants. K18 is removed. A published stratum → control map gives every required stratum a control that can be killed on real days. | §7, §9.3 |
| **M1** day-start flat | flat decision book, guard ledger carried | **Flat, honestly scoped**: label `DAY_SESSION_FLAT;OVERNIGHT_INVENTORY_UNTESTED`; one ledger (the guard paper ledger also resets); 00:00-00:30 transitions not credited; first live session bound to one UTC day, held to settlement (OD4) | §3.3, §9.3, §17 |
| **M2** venue hash/timestamp | single key, single clock statistic | Both branches pre-declared: content-hash book key with an unchanged-content interval; the clock is measured primarily on paired websocket trade receipts, with book-branch fallbacks R and C | §6.6, §8 |
| **M3** AST read test | AST walk | Attribute-**recording proxy** over `DecisionInputs` | §3.6 |
| **M4** live time barrier | none | Single logical-time queue with channel watermarks; lateness bounds | §4.5 |
| **M5** gated spans excluded | B1 skipped gated spans | B1 compares the policy book everywhere; `GUARD_GATED` affects money diagnostics only | §3.3, §6.4 |
| **M6** kill rule | ≥ 1 B1 mismatch of any field | Kill = a **decision-field** mismatch (B1) or the **mapped invariant** (Tier I) or the **mapped record check** (B0/B2/P), at a transition of the control's stratum | §7 |
| **M7** G13 git identity | "push identity" | First-parent, single-file diff, trailer, **hash-chained attestations** confirmed by a successor; signing still OD8; M16b | §5.2 |
| **M8** cluster unit | condition-day, ≥ 3 markets | Cluster = (market, local target day); ≥ 29 per stratum; **no market > 40 %**; contexts counted with clocks bucketed to the minute | §9.2, §9.3 |
| **M9** + MA fill floor | 29 strictly-through fills | **Honest projection** (§9.4): about 3.9 expected by 11-22 under the stated mapping, P(≥ 29) ≈ 0. Floor 29 is removed from MET. Options: longer cohort, `at_price` re-drive, synthetic-print re-drive, lower floor with disclosure, each with its power. Owner picks (OD11). | §9.4, §12 |
| **M10** MG-1 / U7 | settled P&L and markouts in the receipt | The gate reads **no settlement**. Settled P&L is removed from the receipt. Markouts are mid-horizon only and never joined to the view. The gate calls the U7 guard and has a test for it. Nothing the gate needs is a U7-refused metric. | §2.2, §6.7, §13 |
| N1-N7 | — | Adopted: §5.3 (N1), §4.1 (N2), §12 (N3), §6.7 (N4), §6.7 C1 (N5), §6.1 A2 (N6), §5.2 (N7) | as listed |
| MA-1 | — | Tier I is a named tier with its own pass criteria and mutants (§6.3, §15 MI-*) | §6.3 |
| MA-2 | — | Fill projection with an interval and three options with power (§9.4) | §9.4 |
| MA-3 | — | Clock trigger drop referenced as dependency CF-1 | §2.1, §4.1 |

---

## 1. What the gate proves, and what it cannot `[v3 CHANGED — V1]`

| # | Risk retired | Test | Independence that gives it power |
| --- | --- | --- | --- |
| R1 | The shadow **reads** the venue wrongly: wrong token, truncation, misparse, stale cache | **B2** raw-identity pairs; **P** presence conformance; **C1** prints | Two capture processes on two hosts; venue identity as the key |
| R2 | The shadow **builds records** wrongly from what it read | **B0** (venue kinds) and **B0w** (descriptor, view, event kinds): rebuild every record from stored raw inputs | Rebuild code is the exporter's projection semantics, not the runner's wiring |
| R3a | The live **driver** differs from the reference driver: wake order, timers, in-instant order, record ingestion order, barrier, day close/open, guard split | **B1**: `EngineV2` re-run on the shadow's records must reproduce every shadow decision, leg, fill and cash value | The engine's heap/lockstep driver vs the live adapter's queue and barrier. **Kernel composition is common-mode here; B1 does not test it.** |
| R3b | The **composition** around `decide()` is wrong in the shared Kernel: own legs in the book, portfolio, cash, fills, cooldown, replacement, latches, `previous_fair_value`, safety pulls | **Tier I** (new): an independently written oracle recomputes all of it from raw records and checks it against what the shadow recorded | Separate code, separate author, import ratchet; it shares only `decide()` and the frozen contract dataclasses |
| R4 | Replay does not predict live-forward behaviour (feed divergence) | **B3**, measured and attributed | Production capture vs workstation capture |
| R5 | The tape is dishonest or non-deterministic | **Tier A** | — |
| R6 | The live executor differs from the shadow (own orders on the venue, real fills, wallet cash, account flags) | **Tier L** (new): acceptance tests of the live executor against the shadow adapter; a first-live precondition, not daily evidence | Fixture differential per live delta (§4.4) |

**Not tested (receipt label).**
- `decide()` itself is common-mode.
- Paper fills say nothing about queue position or real fill realism.
- Overnight inventory is untested (M1).
- Tier I covers the Kernel only through its listed invariants (§6.3). A Kernel behaviour outside that list stays
  common-mode.

The label is:
`LIVE_GATE_EVIDENCE_NOT_AUTHORITY;DECIDE_COMMON_MODE_UNTESTED;KERNEL_ORACLE_SCOPED;PAPER_FILLS;DAY_SESSION_FLAT;OVERNIGHT_INVENTORY_UNTESTED;PROVENANCE_PUSH_PATH_CHAINED`
(the last element becomes `PROVENANCE_SIGNED` if OD8 adopts signing).

---

## 2. Preconditions checked before anything is read `[v3 CHANGED — V2, V3, M10]`

v2 §2 items 1 (date admissibility), 3 (same policy, same configuration) and 6 (provenance, now §5.2) are
`[v3 KEPT]`. Items 2, 4 and 5 change, and items 7-9 are new.

### 2.1 Cohort dependencies (new, checked at cohort start, bound into the cohort id) `[v3 NEW — V2, MA-3]`

- **CF-1 landed.** The plugin clock's trigger-source rule (F2) is owned by the separate code-fix unit CF-1. The
  cohort cannot start until CF-1 has landed on the build line and the shadow branch is rebased onto it.
- Whatever CF-1 makes the clock accept, the shadow reads **the same observation sources as production, from the
  same public endpoints**, independently on the workstation (§4.1). Any CF-1 change to `clock.py` changes the
  plugin module hash, which starts a new cohort by the v2 §2.4 rule.
- If CF-1 has not landed by 2026-11-10 (the S1 deadline), the gate is `REFUSED (observation_channel_unsourced)` on
  every day. Shipping a gate that cannot see decided bands is not an option.

### 2.2 Model allowlist, lead-0 redaction, no settlement `[v3 CHANGED — V3, M10]` (replaces v2 §2.2)

1. **Scope.** The allowlist applies to every `OutcomeView` that `decide()` can read: views of compared conditions
   at horizons {1, 2}.
2. **Allowlist** (`MODEL_ALLOWLIST`, frozen gate constant, OD3): the plugin's `nbp-v2-piecewise-linear*` ids and
   `pit-lead1-normal-fixed-2C-equivalent`. The fallback id is listed **whatever the shadow's choice**, because
   production may emit it (§4.3). MG-1, RV-1, HG-1 and every other NBM-guidance candidate are never listed. Any
   other model id at horizons {1, 2}, on either side, refuses the day (`view_model_not_allowlisted`).
3. **Lead-0 redaction (both sides).**
   - Every lead-0 `outcome_view` record, in the gate-purpose bundle and in the shadow tape, must be exactly
     `Unavailable("lead0_not_in_gate_scope", at)`.
   - The gate-purpose exporter constructs its fair-value provider **without** `snapshots`, and replaces any lead-0
     result with this value before writing. The shadow has no served snapshots and emits the same value.
   - Any other lead-0 view on either side is `REFUSED (lead0_view_present)`, checked at transfer receipt and at the
     gate. This is the check that no production served vector reached the workstation.
   - Equivalence argument (F4): lead-0 `decide()` outputs are unchanged by the redaction. Only lead-0 wake counts
     and the resume-latch reason of flat lead-0 conditions change, and they change identically on both sides. Lead-0
     lots (bought at lead 1 earlier in D) keep their `inventory_cost`, which does not depend on the view, so the
     portfolio coupling of other conditions is exact.
   - Lead-0 intervals are compared in Tiers A, B0, I and B1 (symmetric). They are excluded from B3 agreement and
     from stratum credit (`LEAD0_EXCLUDED`, counted).
   - A fixture test proves equality of R_p decisions at horizons {1, 2} with and without the redaction (mutant
     MV3).
4. **No settlement (F5).** The gate-purpose bundle carries **no** `settlement` records, and the shadow tape carries
   none. Either present → `REFUSED (settlement_in_gate_input)`. Tier I asserts that no condition holding a lot
   bought in D settles inside D (invariant I4).
5. The gate computes no forecast score, no view-vs-outcome metric and no settlement-joined value (§6.7, M10).

### 2.3 Same code `[v3 CHANGED — V1]` (v2 §2.4, extended)

The bound module set adds `maker_core.shadow.gate.oracle` (Tier I) and
`weather.market.maker_shadow_gate_b0` (B0w). Their hashes are in the cohort id. The oracle's hash must **differ**
from any module it is forbidden to import (a trivial check against the oracle being a re-export).

### 2.4 Every input channel present on both sides `[v3 CHANGED — V2]` (v2 §2.5, extended)

- Channels: `descriptor`, `book`, `terms`, `outcome_view`, `info_event`, `coverage`, plus the new **observation
  sub-channel** of `info_event`.
- A whole channel absent → `REFUSED (channel_absent:<kind>)`, as in v2.
- The observation sub-channel is absent when either side holds zero observation-source reads for a quoting
  market-day (§6.8 P4). That is `REFUSED (channel_absent:observation)`.

---

## 3. The input-construction agreement `[v3 KEPT with changes]`

v2 §3.1 (every field `decide()` reads), §3.3 (raw record construction) and §3.4 (the neutral projection module)
are `[v3 KEPT]`, with these row changes:

### 3.1 Row changes to v2 §3.1 `[v3 CHANGED — V3, V1]`

| Field | v3 contract rule |
| --- | --- |
| `fair_value` | As v2, plus: at lead 0, `Unavailable("lead0_not_in_gate_scope", now)` on both sides (§2.2). The shadow's fallback is disabled (§4.3). |
| `events` | As v2, over the **same observation sources as production after CF-1** (§4.1). The v2 text "Observation triggers come from public METAR reads" is void. |
| `book` | As v2 (engine `add_own` before `decide()`). v3 adds that this is the **paper** rule only. The live rule differs (Tier L, L1). |
| `portfolio.cash` | As v2 (paper cash). The live rule differs (Tier L, L3). |

### 3.2 Row changes to v2 §3.3 `[v3 CHANGED — V2]`

The raw identity kept in the tape adds:

| Kind | Raw identity kept (shadow tape raw block and gate sidecar) |
| --- | --- |
| `descriptor` | Gamma event body SHA-256 **and** the descriptor projection digest: `outcome_tokens`, tick, `min_order_size`, `close_at_utc`, band bounds, `band_basis`, factors |
| `outcome_view` | NBP `payload_hash`, the bulletin text (stored on first sighting), slot, band partition, `band_basis`, `model_id` |
| `info_event` | Per observation event: source, station, observation instant (`observed_at`), value, and the raw source reply SHA-256 (reply stored); per scheduled event: kind, station, `scheduled_at_utc` |
| `book` | Per side: SHA-256 over the raw `bids` and `asks` arrays exactly as received (**content hash**), venue `hash`, venue `timestamp`, receipt instant, body on content change |

### 3.3 Composition behaviour: rows replaced in v2 §3.2 `[v3 CHANGED — V4, M1, M5]`

| Behaviour | v3 contract rule | Control |
| --- | --- | --- |
| **Day close** (replaces v2 "Day roll") | The adapter runs **one Kernel-derived instance per UTC day**.<br>• The D instance is created at logical `D 00:00:00Z` with horizon `D+1 00:00:00Z` and windows from the shadow universe clipped to `[D, D+1]`.<br>• Once the barrier (§4.5) passes `D+1 00:00:00Z`, the D instance runs exactly the engine's horizon step (`finish()`, `engine.py:114-125`): every timer ≤ horizon, with an empty record batch.<br>• This records `CANCEL OUTSIDE_ACTIVE_INTERVAL` for every condition with legs, plus any other decision due at that instant, in condition-id order.<br>• These are written to **D's tape** as `decision` rows flagged `horizon: true`, then `terminal`, then the seal.<br>• The policy book is then flat, and the guard executes those CANCELs as ordinary paper cancels. The v2 `day_roll` intent is **removed**. | Kx6 |
| **Day open** | A **fresh** instance for D+1: no `latest`, `sha`, `trades_seen`, coverage state, latches, `last_quote` or `previous_fair_value`; cash = `caps.cash`; no lots. Its fixed window-start timers at `D+1 00:00:00Z` emit the engine's `NO_QUOTE MISSING_*` pulls (F8) before any record. These are the first `decision` rows after `day_open` in D+1's tape. | Kx7 |
| **Record day assignment** | A record whose logical instant is ≥ `D+1 00:00:00.000000Z` belongs to D+1, exactly as the bundle and `DaySource` assign it. | MV4c |
| **Guard** | The policy book follows the engine everywhere. The gated book is recorded separately. `GUARD_GATED` spans are still counted, but **B1 compares in gated spans too** (M5). Only money diagnostics are split by gating. | — |
| **Guard ledger at day open** (M1-B) | The guard's paper ledger **also resets** at `D 00:00:00Z` (cash = `caps.cash`, no lots, bleed state cleared). There is one ledger and one reset instant. `day_open` records it flat. | MV1b |

### 3.4 Conformance tests (v2 §3.5) `[v3 CHANGED — V1, M3]`

- **Test 1** (projection equality): `[v3 KEPT]`. It now also covers the descriptor and view projections through B0w
  (§6.2).
- **Test 2** (shadow-engine differential): `[v3 KEPT]`. The fixture adds a leg resting at 23:59, the horizon step,
  and the D+1 fresh open. The required equality is over the **closed** day.
- **Test 2b (new): oracle conformance.** Over the same fixture the oracle (§6.3) must report zero violations on the
  unmutated run, and every MI-* mutant (§15) must make it report the mapped invariant.
- **Test 3** (identity-field coverage): replaced by §3.6.
- **Test 4** (time-shift purity): `[v3 KEPT]`.

### 3.5 Removed `[v3 REMOVED — V4]`

The v2 §3.2 "Day roll" row, the `day_roll` intent in the `gate` record (v2 §4.5), and control K18.

### 3.6 Read-set proof by a recording proxy `[v3 NEW — M3]` (replaces v2 §3.5 test 3)

- `tests/maker_core/test_decide_read_set.py` wraps `DecisionInputs` and every nested value (`market`, `book`,
  `terms`, `fair_value`, `portfolio`, each `ExposureLimit`, each event in `events`, each leg in `existing`) in a
  read-only **attribute-recording proxy**. The proxy records the dotted path of every attribute access, including
  access through local aliases, loop variables and helper calls, because it intercepts at the object, not in the
  syntax tree.
- It runs `decide()` over:
  - every decision instant of the fixture day;
  - a hypothesis strategy over `DecisionInputs` (all profiles, horizons, grades, event mixes and portfolio edges);
  - every v2/v3 mutant input.
- It asserts that the union of recorded paths ⊆ the identity projection N(i) (v2 §6.4) ∩ the B0/B0w rebuild ∩ the
  oracle's composed fields (§6.3 I12).
- A path read by `decide()` but missing from any of the three fails the test.
- The proxy must not change behaviour: `decide(proxy(i)) == decide(i)` on every input, with `input_hash` excluded.

---

## 4. Shadow composition change: work unit S1 `[v3 CHANGED]`

v2 §4 applies except as below.

### 4.1 Providers injected into the runner `[v3 CHANGED — V2, N2]`

The rows for descriptor, horizon, exposure, fair value and prints are `[v3 KEPT]`. The info-events row is
replaced, and three rows are added:

| Provider | v3 rule |
| --- | --- |
| Info events | Plugin `WeatherInformationClock` (the post-CF-1 version) over the shadow's own store. Scheduled prints and model cycles are deterministic. **Observation triggers** come from the same sources production's trigger loop uses, read independently by a workstation copy of the trigger detection (`detect_observation_triggers`, unchanged code, module-hash bound) at the same cadence. Today that means METAR (`aviationweather.gov`) and ECCC SWOB (`dd.weather.gc.ca`), both free and key-less (F2). WU history enters on both sides only if OD15 approves the page-backed path (F3); never on one side only. |
| Observation input store | Every source reply is stored in the tape-adjacent input store with SHA-256, fetch instant and HTTP status. Failures are recorded as `input_gap` rows. |
| Hostname pin (N2) | The shadow's outbound hosts are pinned: `clob.polymarket.com` and the websocket host, `gamma-api.polymarket.com`, `data-api.polymarket.com`, the NOAA NBP host, `aviationweather.gov`, `dd.weather.gc.ca`, and `www.wunderground.com` / its API host only if OD15 is yes. Any Polymarket US host is refused. A closure test enforces the list. |
| NBP fetch (N2) | Held-cycle reuse: a bulletin is fetched once per issue, never per minute. |

### 4.2 Served-view source `[v3 CHANGED — V3]`

v2 §4.2 applies, with its false sentence corrected: **under v3 no production served vector crosses to the
workstation**, because the gate-purpose bundle carries lead-0 views only as the redaction value (§2.2.3), and the
transfer receipt refuses anything else.

### 4.3 MG-1 check and the fallback `[v3 CHANGED — V2, V3]`

- The allowlist is as §2.2.2. The runner refuses to start if its provider's model set is not a subset.
- **Shadow fallback disabled.** The fallback reads production forecast rows (F6), so the shadow cannot reproduce
  it. S1 disables it, and those instants are `Unavailable("fallback_not_reproducible_in_shadow")`.
- **Declared asymmetry, not feed divergence.** A B3 window in which R_p's latest view has the fallback model id
  while the shadow holds that `Unavailable` is `FALLBACK_ASYMMETRY`. It is counted in compared condition-minutes,
  capped at **10 %** (else `INCOMPLETE`), and never classed `FEED_VIEW`.
- The live executor must also run without the fallback (OD16), so the shadow matches the live path.

### 4.4 Live adapter, and what live will actually run `[v3 CHANGED — V1]`

- `maker_core.shadow.live_kernel` subclasses `maker_core.replay.v2.kernel.Kernel` with live hooks (OD1, kept).
- **v2's claim "the live executor must run this composition" is withdrawn.** No informed-v0 live executor exists
  (F1). The future live executor must be built **as this adapter plus the live deltas below**. Each delta is gated
  by **Tier L**: an acceptance suite that the live preflight cites by hash (OD13). Tier L is not daily evidence; it
  is a precondition for the first live session.

| Delta | Paper (shadow and replay) | Live | Tier L gate (fixture differential; must pass before first live) |
| --- | --- | --- | --- |
| **L1 Own legs in the book** | `add_own` adds the paper legs to the public book; `decide()` subtracts `existing` via `external_levels` | The venue book already contains own acknowledged orders, so live must **not** call `add_own` | For a venue book V that contains own acked orders O: `live_inputs(V).book == paper_inputs(V − O).book` (after `add_own(O)`), exactly, across partial fills and same-price aggregation. In-flight states (submitted not acked, cancel pending) block `decide()` for that condition until resolved; a test proves no decision is made in flight. |
| **L2 Fills** | `fill_model.match` on public prints | Authenticated user-channel fill messages | A user-channel fill fixture drives the same Kernel transition as the equivalent paper `Fill`: lot, `inventory_cost`, cash, `CANCEL FILL_CANCEL_SIBLING` at the fill instant, and the remainder cancelled on the venue. Duplicate and out-of-order fill messages are idempotent. |
| **L3 Cash** | Paper cash = `initial_cash` − fill costs | A budget ledger: `caps.cash` − live fill costs. The wallet balance is never read into `portfolio.cash` directly. | Wallet balance below the ledger sets `safety_breached = True`, which yields `SAFETY_BUDGET` and cancel-all; tested. |
| **L4 Account flags** | `foreign_open_order`, `unknown_position`, `safety_breached` = False | From account reads | Each flag True yields `UNKNOWN_ACCOUNT_STATE`/`SAFETY_BUDGET` and cancel-all; tested. |
| **L5 Order outcomes** | The policy book is the decision | Venue rejections and partial placement | Live `existing` = accepted legs only; the gated book's mapping is tested. |
| **L6 Time** | Logical time (§4.5) | The same barrier and lateness bounds | The same §4.5 tests run against the live loop. |
| **L7 Session shape** | Day-session flat (M1) | Cannot flatten inventory | First live session = one UTC day; quoting ends at the horizon cancel; lots held to settlement; no next session until all lots settle (OD4). |

### 4.5 The live loop's logical-time barrier `[v3 NEW — M4]`

- **One queue.** Every input is enqueued with its logical instant: book read completions, websocket market messages,
  reward replies, view computations, observation replies and timer due instants. The receipt instant is stamped by
  the receiving thread. The Kernel thread alone consumes the queue.
- **Watermarks.** Each channel c has a watermark `W_c`, the latest receipt instant it has delivered. For the
  websocket, the watermark also advances with each ping/pong (≤ 1 s apart). For polled channels it advances at the
  completion of each poll. Global `W = min_c W_c`.
- **Drain rule.** The thread processes logical instant t only when `W ≥ t`. It then ingests every queued record with
  instant t in engine order: prints first, then other records by enqueue sequence. Only after that does it fire the
  timers due at t, and then wake conditions in condition-id order. This reproduces `engine.py:132-161` exactly.
- **Late records.** A record whose receipt instant is earlier than an instant already processed is ingested at the
  current logical instant. Its original receipt is kept in the raw block, and it is counted as `late_restamped`.
  More than **1 %** of records → `INCOMPLETE (late_records)`.
- **Lateness bounds.** Decision lateness = wall time at `decide()` − logical instant. Timer lateness = wall time at
  fire − due instant. Per day: **p99 ≤ 1 s and max ≤ 5 s** for both, else `INCOMPLETE (live_lateness)`. This bounds
  what the logical `now` hides from `decide()`'s 10 s freshness check (`policy.py:231`).
- **Controls.** Kx1 (records processed in arrival order rather than logical order) and Kx3 (a timer fired before
  the same-instant records) are adapter controls (§7).

### 4.6 Tape v0.3 `[v3 CHANGED]`

v2 §4.5 applies with these changes:
- schema `maker_core.shadow_tape.v0.3`;
- `day_open` holds a flat guard ledger (M1-B);
- `decision` rows carry `horizon: bool`;
- the raw block carries the v3 identity fields (§3.2) and stores Gamma bodies, NBP texts and observation replies on
  change;
- the `gate` record no longer carries `day_roll`;
- a new `input_gap` row records a failed provider fetch;
- `clock` rows add per-channel watermark lag and decision/timer lateness.

### 4.7 CLI and scope; S1 tests `[v3 KEPT]`

v2 §4.6-4.7 apply. In addition:
- `load_config` refuses an enabled fallback, and refuses an observation source set that differs from the bound
  production set;
- the tests add the barrier (§4.5), the day close/open (§3.3) and the hostname pin.

---

## 5. Inputs, transfer and provenance `[v3 CHANGED]`

### 5.1 The replay bridge and its guard `[v3 KEPT]`

v2 §5.1 applies.

### 5.2 Provenance bound to the capture host `[v3 CHANGED — M7, N7]`

The attestation contents are as in v2, plus three fields:
- `prev_attestation_sha256`: the previous gate-purpose attestation the capture host wrote, read from the **capture
  host's local** store, never from `origin`;
- `chain_index`;
- the identity-sidecar SHA-256 (§5.4).

The gate refuses the bundle unless **all** of the following hold:

| Check | Rule |
| --- | --- |
| (a) | Every file hash matches the attestation |
| (b1) | The attestation hash appears in `config/maker_replay_v2/transfer_manifest.json` in a commit **on `origin/master` first-parent history** |
| (b2) | That commit's diff touches **only** `transfer_manifest.json` |
| (b3) | Its message carries the trailer `Capture-Host-Attestation: <sha256>` and `Chain-Index: <n>` |
| (b4) | **Chain confirmation.** A later capture-host attestation (index n+1), or the capture host's daily `chain_head` entry, names this attestation as its `prev`. Until then the day is `PENDING (attestation_unconfirmed)`, inside the 3-day PENDING allowance. |
| (b5) | If OD8 adopts signing: the commit is GitHub-verified with the capture host's registered signing key |
| (c)-(e) | As v2: `provenance == "captured"`; `input_hashes` equals the segment hashes; `purpose == "shadow_gate"` |

- **Strength, stated in the receipt.** Without (b5), (b1)-(b4) defeat an accidental synthesized bundle and any
  forgery that cannot write to the capture host's local chain. A forged commit made from the workstation is never
  named as `prev` by the next real attestation, so it shows up as a **fork** (`attestation_chain_fork` → day
  `REFUSED`, and summary `NOT_MET`). This is not cryptographic proof. The label element is
  `PROVENANCE_PUSH_PATH_CHAINED`.
- **Summary rule.** MET requires an unbroken chain from the first calibration day through one attestation past the
  last counted day.
- **N7.** `WeatherOneShotPush` handles a non-fast-forward `origin/master` by rebasing the manifest-only commit, never
  by merging on the production tree. A test proves the commit stays single-file after the rebase.
- No workstation code path writes `transfer_manifest.json`. A ratchet test enforces this.

### 5.3 Date allowlist and transfer scope `[v3 CHANGED — V3, N1]`

- v2 §5.3 applies, with one change: the transfer tool refuses, at both ends, any package that contains a lead-0
  view other than the redaction value, or any `settlement` record (§2.2).
- The transferred set under OD6 becomes: the gate-purpose bundle (lead-0 redacted, no settlement), the identity
  sidecar and the attestation. **No served vectors and no settlement records.**
- **N1, for the reserved-window owner (OD17).** On the capture host the gate-purpose exporter streams and parses
  whole multi-day files (`settlements/<market>/ledger.jsonl`, `snapshots/observation_triggers.jsonl`), including
  2026-09-30..10-15 rows, and discards them before output (`maker_plugin_sources.py:173-218`).
  - Under v3 the settlement ledger is not needed at all (§2.2.4): the gate-purpose exporter **must not open it**.
  - For the triggers file, the owner decides whether parse-and-discard on the capture host is acceptable. If it is
    not, the exporter seeks by date index or reads a per-day file.
  - The answer is recorded here before any gate-purpose export.

### 5.4 Identity sidecar `[v3 CHANGED — V2, M2]`

v2 §5.4 applies (venue stamps per book and trade record). The sidecar is renamed the **identity sidecar** and
adds:
- per book side: the content SHA-256 of the raw `bids`/`asks` arrays as received, and the 88a receipt instant;
- per trade: the 88a receipt instant of the websocket message;
- per view record: the exporter's `last_nbp_read` identity (payload hash, slot, band partition, `band_basis`) or the
  fallback inputs digest, plus `model_id`;
- per descriptor record: the descriptor projection digest (§3.2);
- per `info_event` record: the source identity (trigger row source, station, `observed_at`, value; bulletin payload
  hash; scheduled kind and time).

The signed v0.2 bundle format is unchanged (OD9).

---

## 6. What is compared `[v3 CHANGED]`

Tiers run in this order: A → B0/B0w → I → B1 → B2/P → B3 → C. A, B0, B0w, I, B1, B2 and the FAIL classes of P
have zero tolerance.

### 6.1 Tier A `[v3 CHANGED — V4, M1, N6]`

- **A0 `day_open`**: as v2, except that the guard ledger snapshot is **flat** (M1-B) and the instance is fresh
  (§3.3). Non-flat → `REFUSED`.
- **A1** and **A3**: `[v3 KEPT]`.
- **A2 deterministic re-drive**: as v2, over the **closed** day including the horizon step. It is run twice, under
  two `PYTHONHASHSEED` values (N6). The two runs must be byte-identical to each other and to the tape.

### 6.2 Tier B0 and B0w: input provenance `[v3 CHANGED — V2]`

- **B0 (venue kinds: book, terms, trade, coverage)**: `[v3 KEPT]`. It lives in `maker_core.shadow.gate.b0` and
  imports no `weather.*`.
- **B0w (weather kinds: descriptor, view, info event; new)**:
  - **Module.** `weather.market.maker_shadow_gate_b0`. It imports only `weather.market.maker_plugin.{universe,
    fair_value,clock,exposure,inputs,nbp}`, `weather.operations.observation_trigger.detect_observation_triggers`
    and `maker_core.contracts`. It **never** imports `weather.market.maker_shadow` (the shadow's provider wiring),
    so it rebuilds independently of how S1 wired the providers.
  - **What it rebuilds.** From the tape's stored Gamma bodies, NBP texts and observation replies, it rebuilds every
    descriptor, view and info-event record at its recorded instant. Each must be byte-equal (`canonical_bytes`) to
    the recorded payload.
  - **Missing raw.** A record without its stored raw input is `REFUSED (raw_missing)`.
- **Import boundary.** The CLI (`weather.market.maker_shadow_gate`) runs B0w first and writes a canonical
  `b0w_result` object: its verdict, the mismatch list and its own module hash. That object is passed to the
  `maker_core` gate **as data**. The `maker_core.shadow.gate` package never imports `weather.*`; a package ratchet
  enforces it. The gate verifies that `b0w_result` names the bound B0w module hash and the tape's seal SHA.

### 6.3 Tier I: the independent composition oracle `[v3 NEW — V1, MA-1]`

**Purpose.** Under OD1 the Kernel is shared by the shadow and the replay, so B1 cannot see a defect inside it.
Tier I is the gate's check that is **independent of the v2 Kernel's composition**. Without it the gate would
measure determinism and call it agreement.

**Independence (enforced).**
- **Module.** `maker_core.shadow.gate.oracle`.
- **Allowed imports.** The standard library, `decimal`, `maker_core.contracts`, and `maker_core.quoting.policy`.
  From `policy` it may take only `decide`, `DecisionInputs`, `Portfolio`, `ExposureLimit`, `QuoteLeg` and the
  profile constants; `decide()` is declared common-mode.
- **Forbidden imports**, by an AST ratchet that fails the build: `maker_core.replay.*` (including `v2.kernel`,
  `engine`, `lockstep`, `fill_model`, `_fill89a`, `payloads`), `maker_core.shadow.{live_kernel,contract,runner,
  paper,tape}`, and `weather.*`.
- **Own code.** It has its own raw-book decoder, written from the venue's response shape, and its own fill
  predicate, written from the 89a contract text ("conservative: a print strictly through the quote on the YES
  axis"; "optimistic: at or through").
- **Clean room.** It is written by an agent that has not authored S1's `live_kernel` or `contract`, working from §3
  and this section only. The author's identity and the absence of the forbidden modules from their read log are
  recorded in the PR.
- **Cross-validation.** A separate test file (not the oracle) checks, by hypothesis, that the oracle's fill
  predicate agrees with `_fill89a.filled_size` and that its decoder agrees with `payloads`. A disagreement is a spec
  conflict that must be resolved before a cohort, never patched by importing.

**Inputs.**
- the tape's raw block: book bodies per side with receipt instants, websocket trade messages and coverage rows;
- the tape's `record` rows for terms, descriptor, view and info event (already proven by B0/B0w);
- the tape's `decision`, `fill` and `minute` rows.

The oracle keeps its own ledger. It never reads the shadow's `minute` cash or legs to drive itself; it only
compares against them.

**Invariants (zero tolerance; each violation has the class `I<n>`).**

| # | Invariant (oracle recomputes; compares with what the shadow recorded) |
| --- | --- |
| I1 Leg ledger | Legs per condition after each decision: QUOTE → the decision's legs; HOLD → unchanged, and the decision's legs equal `existing`; CANCEL/NO_QUOTE/END → none. Equals the next decision's recorded `existing` and every `minute` snapshot. |
| I2 Own legs in book | For each record-driven decision, the recorded `inputs.book` equals the oracle-decoded public book at the latest raw body ≤ the instant per side, with each YES leg's size added at its price on `yes_bids`, each NO leg's size added at `1 − price` on `yes_asks`, and no other change; `as_of = min(side receipts)`. |
| I3 Fills | Each deduplicated (by venue id) trade message, while legs rest, coverage is valid just before the instant, the condition is active and `traded_at ≥ placement`, yields a fill exactly when the oracle predicate says so: first matching leg in leg order, size = min(print size, leg size). The recorded fills equal the oracle's (trade id, leg, size, cost). |
| I4 Money | Cash after each instant = `caps.cash` − Σ oracle fill costs (quantized to 1e-6); lots = oracle fills; per-condition `inventory_cost` = Σ cost. No settlement inside D. Equals the recorded `minute` values and `portfolio.cash`. |
| I5 Portfolio | For each record-driven decision, every `Portfolio` field recomputed from the oracle ledger and descriptor records: `reserved_elsewhere` (Σ other conditions' Σ price×size of legs), `band_cap` room, `wallet_used`, `event_used` (own inventory + same-event others' reserve and inventory), each exposure's `used`, `active_other_bands` (others with legs **or** lots), and the caps. |
| I6 Safety (no stale resting leg) | At every instant where legs rest after processing (all record instants, and the oracle's **own** due instants: book receipt + 60 s, terms + 1 h + ε, view `valid_until`, event boundaries scheduled − 3 min and + 10 min + ε, `active_until` + ε, close − 3 h, window edges): the condition is active; book age < 60 s; coverage valid; terms age ≤ 3600 s; no active event with `decided ≥ .5` or `action_hint == "pull"`; horizon ∈ {1, 2}; the view is valid; now < close − 3 h. |
| I7 Cooldown and replacement | No QUOTE while flat within 60 s after the previous QUOTE, except the same-instant replacement after a CANCEL with a replacement reason when the last QUOTE is ≥ 60 s old. |
| I8 `previous_fair_value` | The recorded value equals `p_yes` of the view current at the most recent instant whose **final** decision was QUOTE (`None` at day open). |
| I9 Resume latch | After an `INFO_PULL` at t_p, no QUOTE until the book freshness clock and the view `as_of` both exceed t_p and no pull-hint event is active. |
| I10 Decided is sticky | After a `decided ≥ .5` event is active for c, no QUOTE for c for the rest of D. |
| I11 Fill → cancel | At each fill instant the condition's next decision is `CANCEL FILL_CANCEL_SIBLING` at the same instant, and there is no QUOTE for c at that instant. |
| I12 Reference composer | For each record-driven decision, the oracle composes `DecisionInputs` itself (market and horizon from the descriptor record, `now`, book from I2, terms, view, events = latest info-event record, portfolio from I5, `existing` from I1, `last_requote_at` = last QUOTE instant, `previous_fair_value` from I8, `fill_seen = False`) and requires `decide(oracle_inputs)` to equal the recorded decision in the decision fields (v2 §6.4). |
| I13 Wake sufficiency | At every instant where the oracle's own change detector fires for an active condition (changed decoded book levels, changed terms body, changed view content, changed event payload, a fill, or an oracle due instant), a decision for c exists at that instant, unless a fill at that instant suppressed it (I11). Decisions occur only at such instants or at the horizon. |

**Second run, on production (diagnostic plus FAIL).**
- The oracle also runs over R_p's event stream and the bundle's decoded records. The bundle has no raw book
  bodies, so I2 uses decoded books, and the result is labelled `ORACLE_RP_PARTIAL_INDEPENDENCE`.
- A violation there is a defect in the **frozen engine**, which is the Kernel live will run. It is `FAIL
  (oracle_engine_violation)` and is escalated to the owner as an exam-engine finding.

**Pass criterion.** Zero violations of I1-I13 on the shadow tape, and zero on R_p, over the closed day. Any violation
→ `FAIL`.

**Tier I mutants (§15).** Symmetric plants in the shared Kernel (B1 must stay clean, Tier I must FAIL with the mapped
invariant), plus ratchet and disablement mutants.

### 6.4 Tier B1: driver equivalence `[v3 CHANGED — V1, V4, M5]`

- **What it proves** (restated). The live driver reproduces the reference driver on the same records: wake
  selection, timers, in-instant order, record ingestion order, the barrier, the horizon step, the fresh open and the
  guard split. Kernel composition is common-mode in B1; Tier I covers it.
- **Comparison.** v2 §6.3's comparison (events, state, fills, money) applies over the **closed day [D 00:00,
  D+1 00:00]**, horizon decisions included, and **including `GUARD_GATED` spans** (M5).
- **FAIL.** A B1 mismatch is `FAIL`.
- **Removed.** The v2 sentence "If S1 shares Kernel, the shared part is exactly what live will run" is removed (F1).

### 6.5 Tier B2: raw-identity conformance `[v3 CHANGED — V2, M2]`

| Pair | Key | Must be equal |
| --- | --- | --- |
| Book side | (token, **content SHA-256 of raw bids/asks as received**), **and** both receipts inside one interval in which production's content hash for that token stayed unchanged | Contract-decoded levels |
| Terms | `[v3 KEPT]` | `[v3 KEPT]` |
| View | (NBP `payload_hash`, slot) | p_yes, joint, `valid_until_utc`, `model_id`, grade, **band partition** and **`band_basis`** (now compared, no longer key) |
| Descriptor (new) | (condition_id, local target date) | Static fields always: `outcome_tokens`, `close_at_utc`, band bounds, event id, factors. `tick` and `min_order_size` are compared only when both captures lie inside one interval in which production's value stayed unchanged. |
| Scheduled event | `[v3 KEPT]` | `[v3 KEPT]` |
| Observation event (new) | (source, station, `observed_at`, value) | Kind, `affects`, `decided`, hint |
| Trade | `[v3 KEPT]` | `[v3 KEPT]` |

**Mapping check (new).** For every compared condition, the shadow's token → (condition, outcome) map must equal the
bundle descriptor's `outcome_tokens`. Any difference → `FAIL (token_mapping_mismatch)`.

**Band partition check (new).** For every event with an equal `band_basis` on both sides, the band partitions must be
equal. Any difference → `FAIL (band_partition_mismatch)`.

A key-equal pair whose projections differ → `RAW_PARSE_MISMATCH` (descriptor: `DESCRIPTOR_MISMATCH`) → `FAIL`.

### 6.6 (reserved: clock, see §8)

### 6.7 Tier C: fills, inventory and money `[v3 CHANGED — M10, N4, N5]`

- C1 prints and C2 cross-feed fills: `[v3 KEPT]`. In addition, calibration reports the trade-id match rate against
  the multiset fallback (N5).
- Inventory and cash: exact in Tier I and B1. Cross-feed values are reported.
- **Gated money (N4).** Paper money is reported both on the policy book and on the gated book. In gated spans the
  receipt states that the policy-book money is not what live would hold.
- **Settled P&L: removed** (M10). The gate reads no settlement (§2.2.4).
- **Markouts:** diagnostic only, **mid-horizon only** (fill price vs venue mid at +5 min and +30 min, from the
  shadow's own books). They are never joined to the view's `p_yes` and never computed against settlement.
- **U7 guard.** Every money-diagnostic function calls the U7 MG-1 metric guard first, declaring its metric class
  (`market_markout`, `paper_cash`, `reward_k1`). None of these is a view-vs-outcome class, so none is refused.
  Tests:
  - an AST check that each diagnostic calls the guard first;
  - a planted view-vs-outcome diagnostic (Brier of `p_yes` against settlement) on a ≥ 10-15 date is refused;
  - **the day verdict never depends on any diagnostic**: a test deletes all diagnostics and the verdict is
    unchanged.
- **The gate does not need OD3's scoring exemption on MG-1 dates.** It still needs OD3's *quoting* exemption,
  because the shadow quotes from the NBP view.

### 6.8 Tier P: presence conformance and channel liveness `[v3 NEW — V2]`

| # | Check | Result |
| --- | --- | --- |
| P1 | For every production identity in the identity sidecar (view `(payload_hash, slot)`; scheduled event; observation event `(source, station, observed_at, value)`; descriptor `(condition, target date)`), the shadow holds the same identity within lag L: **view 15 min, observation 15 min, descriptor 15 min**. Calibration may only lower these. | A miss covered by a recorded shadow `input_gap` or tape gap is `ABSENT_<KIND>` (counted). An uncovered miss is `SHADOW_MISSED_<KIND>`. |
| P2 | A production **pull-class** event (`action_hint == "pull"` or `decided`) affecting a compared condition with no shadow counterpart within L and no shadow gap covering it | `SHADOW_MISSED_PULL` → **FAIL** |
| P3 | Other `SHADOW_MISSED_*` and all `ABSENT_*`, per channel | Capped at **5 %** of production identities per channel, else `INCOMPLETE` |
| P4 | **Absolute liveness (catches common-mode, F2).** For each quoting market-day, each side's observation store must hold ≥ 1 successful read per hour for ≥ 18 hours from each bound observation source. | Fewer on either side → `REFUSED (channel_absent:observation)`. This is source health, not event counts: a day without a temperature rise is legitimate. |
| P5 | Shadow-only pull-class events (production missed) | `PRODUCTION_MISSED_PULL`, counted and reported; not a shadow fault |

---

## 7. Controls: three families, each killed by the tier that can see it `[v3 CHANGED — V1, V5, M6]`

v2's single K1-K18 family is replaced. The harness module, the rule that the unmutated re-drive equals the tape
first, and the rule that controls write nothing are all `[v3 KEPT]`.

**Family X: adapter controls (killed by B1).** Planted in the adapter only, then re-driven; B1 against an
unplanted R_s.

| Control | Plant |
| --- | --- |
| Kx1 | Records processed in arrival order, not logical order |
| Kx2 | Prints not ingested before other records at an instant |
| Kx3 | A timer fired before the same-instant records |
| Kx5 | Band-exit window end not scheduled from the universe (no `OUTSIDE_ACTIVE_INTERVAL` pull) |
| Kx6 | Horizon step skipped at D+1 00:00 |
| Kx7 | Day-open window-start pulls not emitted |
| K14 | `last_requote_at` taken from the gated placement time |
| K15 | Timer wakes deferred to the next minute |

**Family S: symmetric Kernel controls (killed by Tier I).** Planted in the **shared Kernel**, so both the shadow
re-drive and R_s carry the plant and B1 stays clean by construction. Tier I runs on the planted re-drive's output
against the raw records.

| Control | Plant | Mapped invariant |
| --- | --- | --- |
| KS1 | `add_own` omitted | I2 |
| KS2 | NO legs added at `price` instead of `1 − price` | I2 |
| KS3 | `reserved_elsewhere` = 0 | I5 |
| KS4 | `active_other_bands` counts legs only | I5 |
| KS5 | No re-entry cooldown | I7 |
| KS6 | No same-instant replacement | I12 |
| KS7 | `previous_fair_value` updated on every evaluation | I8 |
| KS8 | No `INFO_PULL` resume latch | I9 |
| KS9 | Events dropped from `DecisionInputs` | I12 |
| KS10 | Fill cost not deducted | I4 |
| KS11 | Coverage pulls ignored | I6 |

**Family R: record controls (killed by B0, B0w, B2 or P).** Planted in record construction.

| Control | Plant | Killed by |
| --- | --- | --- |
| K11 | Books truncated to 25 levels, `as_of` taken from the later side | B0, B2 |
| K12 | Descriptor tick and minimum size from the book | B0w, B2 descriptor |
| K13 | Horizon fixed at discovery | B0w |
| Kc1 | YES/NO token swap in record building | Mapping check |
| Kc2 | Band partition from the shadow's own discovery with one band split | B0w, band partition check |
| Kc3 | Observation triggers dropped | P2 / P1 |
| Kx4 | Trade id assigned per receipt instead of the venue id | B0, B2 trade, C1 |

**Kill rule (M6).** A control is killed on D only by:
- **X:** a mismatch in a **decision field** (`action`, `reasons`, `legs`) at an event that is a transition of the
  control's stratum;
- **S:** a violation of its **mapped invariant** at a transition instant of its stratum;
- **R:** a mismatch of its **mapped record kind or check**.

The receipt records the class of the first mismatch. Money-only or state-only differences, and extra HOLD events,
never count.

**Removed:** K16 (decide every minute; it was trivially killed, so it is now a fixture mutant only), K18 (V5), and
K1-K10 and K17 as asymmetric shadow plants (now KS-*).

**Stratum → control map (V5).** A required stratum is credited for a counted PASS day only if ≥ 1 of its mapped
controls is killed that day.

| Stratum (transition, from R_s events) | Required for MET | Mapped controls |
| --- | --- | --- |
| S-PLACE: QUOTE from flat | yes | Kx1, KS3, K11 |
| S-REQUOTE: replacement CANCEL followed by a same-instant QUOTE | yes | Kx3, KS6 |
| S-HOLDLEGS: HOLD with legs resting | yes | KS1, KS2 |
| S-INFOPULL: `INFO_PULL` or `DECIDED` withdrawal | yes | KS9, Kc3 |
| S-REENTRY: QUOTE after `INFO_PULL` or after a cooldown | yes | KS5, KS8 |
| S-MULTIBAND: a decision with `active_other_bands ≥ 1` | yes | KS3, KS4 |
| S-BANDEXIT: `OUTSIDE_ACTIVE_INTERVAL` CANCEL before the horizon | yes | Kx5 |
| S-FILL: a fill and its sibling cancel | per §9.4 | Kx2, KS10 |
| S-DAYCLOSE / S-DAYOPEN | **no** (fixture-proven; B1 compares both instants daily) | Kx6, Kx7 |
| S-COVERAGE, S-GUARD | no (fixture-proven, as v2) | KS11, — |

**Negative controls.**
- R_s run twice gives a byte-identical decision SHA (v2).
- The A2 re-drive under two `PYTHONHASHSEED` values gives byte-identical output (N6).
- The oracle run twice is byte-identical.

---

## 8. Clock check, both venue branches pre-declared `[v3 CHANGED — M2]`

**Primary measure (branch-free): paired websocket trades.**
- Both hosts receive the same market-channel trade messages. For each trade id seen by both:
  `Δ = receipt_shadow − receipt_prod`, where the production receipt comes from the identity sidecar.
- Per 3-hour block b: `S_b = median(Δ)` and `spread_b = p95(Δ) − p05(Δ)`.
- Bounds: `max_b |S_b| ≤ 2 s` and `max_b spread_b ≤ 5 s`.
- A block with < 10 paired trades is unmeasurable.
- If ≥ 6 of 8 blocks are measurable, this measure decides the clock, and the book branches below are reported only.

**Fallback: book receipts.** Calibration decides the branch: does the venue `timestamp` advance while the content
hash is unchanged?
- **Branch R (response-time stamps).** v2 §8 statistic: `E_h = p05(L)`, `P_h = p95(L)`, `S_h`. Bounds `|S_h| ≤ 2 s`,
  `P_h ≤ 5 s`, `E_h ≥ −0.5 s`.
- **Branch C (last-change stamps).** Bound only `E_h ≥ −0.5 s` per side and `|S_h| ≤ 2 s`, using pairs whose content
  changed between the two hosts' consecutive reads (so that L measures the time since the change). `P_h` is not
  bounded.
- Hourly unmeasurability (< 30 pairs) and the 18-hour rule are as v2.
- If neither the primary measure nor the declared branch is measurable → `INCOMPLETE (clock_unmeasurable)`.

The branch is recorded on the calibration days and frozen. Calibration may set numbers only, never the keys or the
statistic (OD10).

---

## 9. Tolerances and statistics `[v3 CHANGED — M8, M9, MA-2]`

### 9.1 Zero-tolerance checks `[v3 CHANGED]`

v2 §9.1, plus:
- Tier I (I1-I13, on the shadow and on R_p);
- B0w;
- the mapping and band-partition checks;
- `DESCRIPTOR_MISMATCH`;
- `SHADOW_MISSED_PULL`;
- `attestation_chain_fork`.

### 9.2 Measured quantities and floors `[v3 CHANGED — M8]`

v2 §9.2 rows are kept, with these changes and additions:

| Quantity | v3 floor or cap |
| --- | --- |
| Per-day distinct contexts | ≥ 200 distinct **N(i) digests computed with every clock bucketed to the minute** (no longer exact offsets); ≥ 20 QUOTE events; ≥ 10 withdrawing pulls; ≥ 2 markets with a QUOTE |
| `FALLBACK_ASYMMETRY` minutes | ≤ 10 % of compared condition-minutes |
| `LEAD0_EXCLUDED` | Reported, uncapped (structural) |
| P3 absent and missed identities | ≤ 5 % per channel |
| `late_restamped` records | ≤ 1 % |
| Decision and timer lateness | p99 ≤ 1 s, max ≤ 5 s |
| `GUARD_GATED` | ≤ 10 % (it now affects money diagnostics only) |

### 9.3 The power model `[v3 CHANGED — M8, V5, M1]`

- **Cluster unit = (market, local target day).** A cluster qualifies for a stratum if that stratum's transition
  occurred in it on any counted PASS day, **outside 00:00-00:30Z** (M1-B), at horizons {1, 2}, and with ≥ 1 mapped
  control killed on that day (§7).
- **Required strata:** S-PLACE, S-REQUOTE, S-HOLDLEGS, S-INFOPULL, S-REENTRY, S-MULTIBAND, S-BANDEXIT. **S-DAYROLL is
  removed** (V5).
- **Each required stratum needs:**
  - ≥ 29 qualifying clusters;
  - spanning ≥ 3 markets, with **no market above 40 %** of the stratum's clusters;
  - mapped controls killed on ≥ 3 distinct PASS days.
- The v2 power table is kept: n = 29 gives 95.3 % at q = 10 % and 77.4 % at q = 5 %. The cluster unit is coarser, so
  it is closer to independence (shared NBP issue and station schedule now fall inside one cluster).
- **Reachability check (disclosed).** With about 11 markets and lead-1/lead-2 targets, a 7-day cohort touches about
  (7 + 2) × 11 ≈ 99 (market, target-day) clusters. The 40 % cap needs at least 3 markets quoting each stratum's
  transition. Calibration reports per-stratum cluster yield per day. If any required stratum projects below 29 in
  14 days, OD11 gets that fact before 11-16. No floor is presented that calibration projects to miss.

### 9.4 Fill evidence: honest projection and options `[v3 NEW — M9, MA-2]` (replaces v2's fill floor)

**The observed rate.**
- RE-1 recorded **4 fills in 8 live sessions** (`FINDINGS_DIGEST.md` line 25).
- Session 1 was one NYC band for 42 minutes, on 2026-09-23. Sessions 2-8 were all on UTC 2026-09-24.
- All four fills were on the thinnest bands (lines 89-101).

**Session-to-day mapping assumed.**
- **Primary (mapping A): one RE-1 session ≈ one shadow quoting day.** This is deliberately conservative.
- **Sensitivity (mapping B): the 8 sessions ≈ the 2 UTC days on which they ran.**

**Projection.** Jeffreys posterior for the rate, Gamma(4.5, exposure); predictive negative binomial for the count
over the cohort window. Counted fills = B1/Tier-I paper fills under `strictly_through`, capped at 3 per
condition-day.

| Window | Mapping A: mean, 95 % predictive interval | P(≥ 29) | P(≥ 10) | Mapping B: mean, 95 % | P(≥ 29) |
| --- | --- | --- | --- | --- | --- |
| 7 counted days (11-16..11-22) | **3.9, [0, 10]** | **≈ 0** | 4 % | 15.8, [3, 36] | 8 % |
| 14 days | 7.9, [1, 19] | 0.1 % | 31 % | 31.5, [8, 69] | 51 % |
| 21 days | 11.8, [2, 27] | 1.9 % | 58 % | 47.2, [13, 102] | 78 % |

The exact 95 % interval for the RE-1 count itself is [1.09, 10.24] fills per 8 sessions.

**Directional biases, not modelled:**
- **Lower.** informed-v0 requires two-sided depth ≥ max(75, size) (`policy.py:345`), which excludes exactly the thin
  bands where all four RE-1 fills happened. `strictly_through` paper fills are stricter than real fills. Each fill
  is followed by a cancel and a 60 s cooldown.
- **Higher.** The shadow quotes many bands at once, while RE-1 quoted one band per session.

The net direction is unknown. The calibration days measure it.

**Conclusion.** A floor of 29 real counted fills by 11-22 is expected to be missed (P ≈ 0 under A, 8 % under B). It
is **removed from MET**.

**Options for the owner (OD11), each with the evidence it gives and its power** (power = 1 − (1 − q)^n against a
defect that manifests in a fraction q of fill events):

| n | q = 5 % | q = 10 % | q = 20 % | q = 30 % |
| --- | --- | --- | --- | --- |
| 5 | 22.6 % | 41.0 % | 67.2 % | 83.2 % |
| 10 | 40.1 % | 65.1 % | 89.3 % | 97.2 % |
| 15 | 53.7 % | 79.4 % | 96.5 % | 99.5 % |
| 20 | 64.2 % | 87.8 % | 98.8 % | 99.9 % |
| 29 | 77.4 % | 95.3 % | 99.8 % | ≈ 100 % |

1. **Longer cohort (up to 21 days), real `strictly_through` fills only.**
   - Under mapping A: expected 11.8 fills, so power ≈ 70 % at q = 10 %; P(reaching 29) = 1.9 %.
   - The earliest MET moves to about 12-06.
   - It still mostly measures common-mode code, but Tier I now checks every fill independently.
2. **Pre-declared `at_price` re-drive.**
   - Each day the adapter is re-driven against R_s, both at `fill_bound="at_price"`. B1 and Tier I run on it, and its
     fills are counted as `fills_at_price`, separately.
   - Its yield is unknown until calibration; it is bounded below by the `strictly_through` count.
   - It adds fill → cancel → cooldown → requote evidence on real-day states.
3. **Pre-declared synthetic-print re-drive.**
   - Each day the gate injects synthetic trade records into **both** the adapter re-drive and R_s. For each
     condition-day, at the midpoint of each of the first ≤ 3 resting-leg spans of ≥ 2 min, it injects one print one
     tick strictly through the first leg, alternating full and half size, with a fixed seed. B1 and Tier I (I3, I4,
     I5, I11, I7) must hold.
   - The yield is controlled: ≥ 29 clusters is reachable within a few days wherever S-HOLDLEGS is.
   - It tests fill **composition** on real states, not print reading (C1 covers that on every print) or fill realism
     (never tested; `PAPER_FILLS`).
4. **Lower real-fill floor with disclosure.** For example, n = 10: 65 % at q = 10 %, 89 % at q = 20 %. Even this is
   met by 11-22 with only 4 % probability under A. Only useful together with option 1.

**Recommendation.**
- MET's fill rule = option 3 (≥ 29 synthetic fill clusters, per §9.3's cluster and 40 % rules) **plus** option 2
  reported.
- Real `strictly_through` fills are reported with their power disclosed in the summary (`real_fills: n,
  power_q10: …`), with no floor.
- If real fills < 10 at MET, the owner's pre-decided limit applies to the first live session (OD11: one band,
  minimum size).

---

## 10. Per-day verdict `[v3 CHANGED — V4]`

v2 §10 applies, with these changes:
- **`REFUSED` adds:** `lead0_view_present`, `settlement_in_gate_input`, `channel_absent:observation`,
  `observation_channel_unsourced`, `attestation_chain_fork`, `raw_missing` (B0w).
- **`PENDING` adds:** `attestation_unconfirmed` (§5.2 b4).
- **`FAIL` adds:** any Tier I violation (shadow or R_p), any B0w mismatch, `token_mapping_mismatch`,
  `band_partition_mismatch`, `DESCRIPTOR_MISMATCH`, `SHADOW_MISSED_PULL`, the A2 double-seed run not identical.
- **`INCOMPLETE` adds:** `live_lateness`, `late_records`, the P3 caps, the `FALLBACK_ASYMMETRY` cap.
- **Instant rule (replaces v2 §10 bullet 3).** Records in D's tape are inside `[D 00:00, D+1 00:00)`. Decisions are
  inside `[D 00:00, D+1 00:00]`, and decisions at exactly `D+1 00:00` must carry `horizon: true`. Anything else is
  `REFUSED (instant_outside_day)`. The gate never opens D+1's tape.

## 11. Missing data `[v3 CHANGED]`

v2 §11 applies, with these changes:
- "Settlement absent" is removed: settlement is never read.
- "Guard HALT/PAUSE": B1 still compares; only money diagnostics are split.
- New row: **observation source down on one side**. Gap-covered misses are `ABSENT_OBSERVATION` (P3). Below the P4
  read floor the day is `REFUSED`.

## 12. The seven-day rule `[v3 CHANGED — M9, V5, M7]`

- **Cohort binding** adds: the oracle, B0w and CF-1 hashes; the lead-0 redaction constant; the observation source
  set.
- **MET** requires all of the following within one cohort:
  - ≥ 7 PASS and 0 FAIL days within ≤ 14 calendar days, or ≤ 21 if OD11 chooses option 1;
  - ≥ 5 distinct local market days with a gated QUOTE;
  - every required stratum per §9.3;
  - **the fill rule chosen in OD11** (recommended: ≥ 29 synthetic fill clusters with no market above 40 %, plus
    `at_price` and real fills reported with power);
  - an unbroken attestation chain (§5.2).
- **Other outcomes.** `FILLS_UNPROVEN` is kept only if OD11 picks a real-fill floor and it is missed. Otherwise
  `NOT_MET` with the first unmet rule.
- **Calibration days** (11-14, 11-15) additionally measure:
  - the stratum cluster yields;
  - the `at_price` and synthetic yields;
  - the real fill rate;
  - the clock branch;
  - the fallback asymmetry rate.

  The thresholds freeze by a reviewed change before 11-16.
- **Timeline (N3).**
  - Calibration needs attested bundles for 11-14/15, which needs OD6. If OD6 is unanswered by about 11-17, both
    calibration days are `INCOMPLETE (bundle_never_arrived)` and the earliest MET moves out day for day.
  - CF-1 must land before 11-10 (§2.1).
  - The earliest MET stays **2026-11-22** under the recommended fill rule. It is about 12-06 under option 1.

## 13. Receipt and summary `[v3 CHANGED]`

The v2 §13 schema becomes `v0.3`, with these changes:
- `label` as §1;
- `binding` adds `oracle_sha256`, `b0w_sha256`, `cf1_commit`, `observation_sources`, `attestation_chain {index,
  prev, confirmed_by}`;
- new `tier_i: {shadow: {violations[]}, rp: {violations[], partial_independence: true}}`, which must be empty;
- `b0` adds `b0w {records_rebuilt, mismatches[]}`;
- `b1` adds `horizon_events`, `open_events`, `gated_span_events`;
- new `presence: {per_channel {identities, matched, absent, missed}, missed_pull[] (must be empty),
  production_missed_pull, liveness {source: reads_per_hour[]}}`;
- `b2` adds `descriptor`, `observation_event`, `mapping_ok`, `partition_ok`;
- `controls` becomes `{family: {id: {killed, class, at}}}`;
- `strata` adds `clusters[] (market, target day)` and `max_market_share`;
- `fills` adds `real_strictly_through`, `at_price`, `synthetic`, and `power {q05, q10, q20}`;
- `money`: `settled_inventory_pnl` is **removed**; markouts are mid-horizon only; `u7_guard_calls[]`;
- `clock` adds `branch` (primary / R / C) and `trade_pairs_per_block[]`;
- `timing` adds `lateness {decision_p99, decision_max, timer_p99, timer_max}` and `late_restamped`.

The summary adds the fill evidence block, the chain head and `kernel_oracle_scope` (the list I1-I13). The live
preflight cites the summary hash **and the Tier L receipt hash** (OD13).

## 14. Module layout `[v3 CHANGED]`

v2 §14 applies, plus:

| Module | Responsibility |
| --- | --- |
| `src/maker_core/shadow/gate/oracle.py` | Tier I (clean-room; import ratchet) |
| `src/maker_core/shadow/gate/presence.py` | Tier P |
| `src/maker_core/shadow/gate/synthetic.py` | Synthetic-print and `at_price` re-drives (§9.4), hashed like the controls |
| `src/weather/market/maker_shadow_gate_b0.py` | B0w (data-only boundary to the core gate) |
| `src/maker_core/shadow/live_kernel.py` | Adds the barrier (§4.5) and the per-day instance (§3.3) |
| `tests/maker_core/test_decide_read_set.py` | §3.6 |
| `tests/maker_core/test_oracle_independence.py` | Import ratchet and cross-validation (§6.3) |
| Tier L suite (live executor unit, not this gate) | §4.4 L1-L7 |

`src/weather/market/maker_shadow_inputs.py` stores observation replies from the bound sources, not "METAR" alone.

## 15. Tests and mutants `[v3 CHANGED]`

v2 mutants M1-M27 are kept, with these changes:
- **M10** now asserts that Family X controls report 0 kills.
- **M19** now asserts that a non-flat guard ledger at `day_open` is refused.
- **M22** applies at horizons {1, 2} only.

New mutants:

| # | Mutant | Required outcome |
| --- | --- | --- |
| MI1-MI11 | Each KS1-KS11 plant applied to the shared Kernel on the rig (both sides) | B1 PASS (proves common-mode) **and** Tier I `FAIL` with the mapped invariant |
| MI12 | Oracle imports `maker_core.replay.v2.kernel` (or `fill_model`, `contract`) | Ratchet test fails |
| MI13 | Oracle disabled (returns no violations) | The test asserting MI1 detection fails |
| MI14 | Oracle reads the shadow's `minute` cash to drive its own ledger | A test that plants a cash drift into `minute` and requires an I4 violation fails |
| MI15 | Frozen-engine defect visible only on R_p (fixture bundle) | `FAIL (oracle_engine_violation)` |
| MV3 | Lead-0 view left as `served:` in the bundle | `REFUSED (lead0_view_present)` at transfer and at the gate; plus the R_p horizon-{1, 2} equality fixture |
| MV3b | Settlement record in a gate-purpose bundle | `REFUSED (settlement_in_gate_input)` |
| MV4a | Horizon step skipped in the adapter | B1 `FAIL` at D+1 00:00 |
| MV4b | D+1 instance reuses D's `latest` | B1 `FAIL` at the D+1 open pulls |
| MV4c | Record at exactly 00:00:00.000000 assigned to D | `REFUSED (instant_outside_day)` |
| MV1b | Guard ledger carried across 00:00 | A0 `REFUSED` |
| MP1 | Shadow observation triggers dropped while production holds a pull | `FAIL (SHADOW_MISSED_PULL)` |
| MP2 | Both sides without observation reads (common-mode, F2) | `REFUSED (channel_absent:observation)` |
| MP3 | YES/NO token swap in shadow record building | `FAIL (token_mapping_mismatch)` |
| MP4 | Shadow band partition splits one band | `FAIL (band_partition_mismatch)` and B0w if the raw is kept |
| MP5 | Shadow descriptor tick from the book while production is unchanged | `FAIL (DESCRIPTOR_MISMATCH)` |
| MP6 | Production fallback view vs shadow `Unavailable` all day | `INCOMPLETE` (`FALLBACK_ASYMMETRY` cap), never `FEED_VIEW` |
| MB1 | Kx1 arrival-order processing on a rig with a websocket print delayed behind a book read | B1 `FAIL` |
| MB2 | Lateness 6 s injected | `INCOMPLETE (live_lateness)` |
| MG1 | B1 skips gated spans | The rig's gated-span mismatch must `FAIL`; the mutant hides it, and the test fails |
| MK1 | K16-style extra HOLD events counted as a kill | The kill-rule test fails |
| MA1 | Workstation commit with a correct trailer, same git identity (M16b) | `PENDING`, then `REFUSED (attestation_chain_fork)` once the next real attestation names a different `prev` |
| MA2 | Manifest commit touching a second file | `REFUSED` |
| MU1 | A gate diagnostic that skips the U7 guard | The AST test fails |
| MU2 | Diagnostics deleted | The verdict is unchanged (test) |
| MS1 | Synthetic re-drive applied to the shadow side only | Harness refuses (it must be symmetric) |
| MR1 | `decide()` read through an alias not in N(i) (fixture policy patch) | The §3.6 proxy test fails |

## 16. Disposition of every v2-Defender finding

| Finding | Severity | Disposition |
| --- | --- | --- |
| V1 | BLOCKER | **Resolved.** Tier I independent oracle (§6.3) with mutants MI1-MI15; B1 restated as driver equivalence (§6.4); controls split into families X/S/R (§7); live claim withdrawn (F1) and Tier L L1-L7 gating each delta (§4.4). |
| V2 | BLOCKER | **Resolved, with a correction.** Production also lacks WU triggers (F2): the gap is common-mode, so v3 adds absolute liveness P4 and the CF-1 dependency (§2.1). Presence conformance P1-P3 (§6.8); descriptor, observation, mapping and partition checks (§6.5); B0w behind a data-only boundary (§6.2); trigger source = production's live sources (§4.1); WU page-backed path → OD15 (F3); fallback asymmetry declared (§4.3). |
| V3 | BLOCKER | **Resolved.** Lead-0 redaction on both sides with an equivalence argument and test (§2.2.3, F4, MV3); allowlist scoped to {1, 2} with the fallback id; no served vector or settlement crosses (§5.3). |
| V4 | BLOCKER | **Resolved.** Per-day Kernel instance; horizon CANCELs written into D's tape; fresh open with the engine's pulls; closed-day B1 (§3.3, §6.4, §10; MV4a-c). |
| V5 | BLOCKER | **Resolved.** S-DAYROLL removed from MET; K18 removed; stratum → control map with real-day-killable controls (§7, §9.3). |
| M1 | MUST-FIX | Option B adopted with label, a single ledger reset, 00:00-00:30 not credited, first live session one UTC day held to settlement (§3.3, §9.3, OD4). |
| M2 | MUST-FIX | Content-hash key with an unchanged interval; trade-receipt primary clock; branches R and C pre-declared (§6.5, §8). |
| M3 | MUST-FIX | Recording proxy (§3.6). |
| M4 | MUST-FIX | Barrier, watermarks, lateness bounds, Kx1/Kx3 (§4.5). |
| M5 | MUST-FIX | B1 in gated spans (§3.3, §6.4; MG1). |
| M6 | MUST-FIX | Family-specific kill rule (§7; MK1). |
| M7 | MUST-FIX | First-parent, single-file, trailer, hash chain with successor confirmation; strength stated; MA1/MA2 (§5.2). |
| M8 | MUST-FIX | (market, local target day) clusters, 40 % cap, minute-bucketed contexts (§9.2-9.3). |
| M9 | MUST-FIX | Projection with intervals; floor 29 removed; options with power; owner fallback (§9.4, OD11). |
| M10 | MUST-FIX | No settlement read; settled P&L removed; markouts mid-horizon only; U7 guard calls and tests; scoring exemption not needed (§6.7). |
| N1 | NOTE | Settlement ledger not opened; parse-and-discard of the triggers file → OD17 (§5.3). |
| N2 | NOTE | Hostname pin; WU only under OD15; held-cycle NBP (§4.1). |
| N3 | NOTE | Timeline (§12). |
| N4 | NOTE | Gated-book money reported (§6.7). |
| N5 | NOTE | Trade-id match rate on calibration (§6.7). |
| N6 | NOTE | Double-seed A2 (§6.1). |
| N7 | NOTE | Non-fast-forward handling (§5.2). |

## 17. Remaining owner decisions (each with a recommendation)

OD2, OD5, OD7, OD10, OD12 and OD14 are **unchanged from v2**: recommend yes as before. Changed or new decisions:

| # | Decision | Recommendation |
| --- | --- | --- |
| OD1 `[CHANGED]` | Composition: a kernel-sharing live adapter **plus** an independently authored oracle (Tier I, clean-room, import-ratcheted). Live is built as the adapter plus deltas L1-L7. | **Yes.** Sharing removes drift; the oracle restores independence where sharing removed it. |
| OD3 `[CHANGED]` | MG-1 ruling, narrowed. The NBP view (`nbp-v2-*`, plus the fallback id) may be used for **quoting** in the shadow and the gate. The gate computes no view-vs-outcome metric and reads no settlement, so it does **not** need the scoring exemption. | **Confirm the quoting exemption explicitly** in `reserved-confirmation-window.md`, with the allowlist. U7 needs no gate-specific exemption id. |
| OD4 `[CHANGED]` | Day-session flat (option B): a single ledger reset at 00:00Z, label `DAY_SESSION_FLAT;OVERNIGHT_INVENTORY_UNTESTED`; **the first live session is one UTC day, quoting ends at the horizon cancel, lots are held to settlement, and there is no next session until they settle.** | **Yes.** Carried state (option A) needs a frozen-kernel seed hook and is deferred until after the first live session. |
| OD6 `[CHANGED]` | O9 transfer, narrowed: the gate-purpose bundle (lead-0 redacted, **no settlement**), the identity sidecar and the attestation, for allowlisted dates only; refused at both ends otherwise. | **Yes, narrowly**, recorded in `DELEGATION_CONTRACT.md`. No served vectors and no settlement rows cross. Answer by about 11-12 so the calibration days are not lost (N3). |
| OD8 `[CHANGED]` | Provenance: a hash-chained push-path attestation now; a capture-host commit-signing key later. | **Accept the chain** for the pilot gate. Adopt signing before any scale-up beyond the first live session. |
| OD9 `[CHANGED]` | Identity sidecar (venue stamps, content hashes, receipts, view/descriptor/event identities). | **Yes.** |
| OD11 `[CHANGED]` | Fill rule. Options (§9.4): (1) a 21-day cohort on real fills; (2) an `at_price` re-drive; (3) a synthetic-print re-drive; (4) a lower real floor with disclosure. | **(3) as the MET fill rule plus (2) reported, with real fills and their power disclosed.** Pre-decide now: if real fills < 10 at MET, the first live session is capped at one band at the minimum size. Do not adopt a real-fill floor of 29 (P ≈ 0 by 11-22). |
| OD13 `[CHANGED]` | The live preflight cites the gate summary hash **and the Tier L receipt hash**, with the label. | **Yes.** |
| OD15 `[NEW]` | Observation trigger source. Production's WU history and WU current fetchers are disabled (F2), so no `decided` event can occur today on either side. The public WU history path is free, with no stored credential, but sends a page-scraped `apiKey` token (F3). | **Approve CF-1** so that the clock accepts METAR/SWOB triggers as pull-only (free, key-less, already live in production). The shadow reads the same sources. **Separately rule** whether the page-backed WU history path may feed triggers on both hosts. I recommend yes (free, nothing stored, and it is the only `decided` source), applied to production and shadow together, never to one side. |
| OD16 `[NEW]` | The fallback view stays disabled in the shadow **and** the live executor; production's fallback minutes are a declared, capped asymmetry. | **Yes.** |
| OD17 `[NEW]`, for the reserved-window owner | May the capture-host gate-purpose exporter parse and discard 2026-09-30..10-15 rows of the multi-day triggers file? The settlement ledger is no longer opened. | **Yes for parse-and-discard on the capture host only**, with nothing written. If no, fund a per-day trigger index first. |
| OD18 `[NEW]` | Oracle authorship: Tier I is written by a different agent than S1's adapter, from §3/§6.3 only, with its read log attached to the PR. | **Yes.** |
