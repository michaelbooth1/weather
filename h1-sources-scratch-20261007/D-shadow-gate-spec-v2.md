# D — "Shadow agrees with replay" live gate: specification v2 (amended)

Swarm M Wave 2, spec author, 2026-10-06. **Spec only.** No gate code may be written until this amended spec
passes a Defender review and the owner has seen it (CONSOLIDATED §3 holds). Nothing here grants run
authority, lifts the live pause, or authorizes the O9 transfer (on HOLD).

Sources, all read-only:
- v1 spec `D-shadow-gate-spec.md` and Defender review `D-defender.md` (G1-G17), in this folder;
- the shadow runner tree `C:\pt\wf` at `b31185d6b`: `src/maker_core/shadow/{runner,paper,tape,score}.py` and
  `src/weather/market/maker_shadow.py`;
- the v2 build tree `C:\wt\workstation-chat\m-v2ro` at `501f47579`: `src/maker_core/replay/v2/*`,
  `maker_core/quoting/policy.py`, `maker_core/replay/{payloads,fill_model}.py`,
  `weather/market/{maker_replay_bundle,maker_replay_bundle_v02,maker_plugin_runner,maker_evidence_capture,
  maker_evidence_public}.py` and `weather/market/maker_plugin/{fair_value,clock}.py`.

No data, panel or settlement rows were read.

## How changes are marked

Every section carries a tag against v1:
- `[NEW]` — not in v1;
- `[CHANGED — Gx]` — v1 text replaced, citing the Defender finding that drove it;
- `[KEPT]` — v1 text carried over in substance;
- `[REMOVED — Gx]` — v1 mechanism withdrawn.

### Change index

| Finding | v1 mechanism | v2 resolution | Sections |
| --- | --- | --- | --- |
| G1 swap test tautology | `decide()` re-run with one input row swapped | Swap test **removed**. Replaced by B0 (input provenance from the shadow's own raw records), **B1 (the replay engine re-run on the shadow's own records must reproduce every observed shadow decision)**, B2 (raw-identity record conformance between the two feeds) and daily **counterfactual controls** (planted composition defects that B1 must catch on that day's data) | §6, §7 |
| G2 compositions differ | none | Written **input-construction agreement** (§3) with the engine's semantics as the norm; shadow work unit S1 (§4); conformance tests (§3.5) | §3, §4 |
| G3 identity omits read fields; `input_hash` | wake signatures as identity; `input_hash` compared | Identity is over **every field `decide()` reads**, including `now`, every input clock, `stdev` and the descriptor; `input_hash` is recorded, never compared | §3.1, §6.4 |
| G4 per-minute vs event-driven | latest replay event ≤ `now` vs per-minute shadow decision | Shadow adopts the engine's wake rule; decisions compared **event for event**; resting state compared every minute | §3.2, §6.2, §6.4 |
| G5 D-1 tape needed | none | **Day-session semantics** plus a `day_open` record; the gate never opens a tape or bundle of any day other than D | §3.2, §6.1 |
| G6 clock check void | median over identical stamps | Lower-envelope latency against the venue clock, per hour, both sides; a venue-stamp **sidecar** retained from 88a raw replies | §5.4, §8 |
| G7 O1 incomplete | fair value only | Fair-value **and** info-event providers, descriptor/exposure providers, served-view source, MG-1 model allowlist, CLI change, new cohort | §2, §4 |
| G8 statistics | independent Bernoulli minutes | **Cluster- and transition-aware** model: condition-day clusters per composition stratum, plus kill evidence from controls; fill floor 29 or `FILLS_UNPROVEN` to the owner | §9, §12 |
| G9 never-closing episodes | episode inherits first label | Composition no longer judged by episodes (B1 checks every event). B3 episodes **capped at 30 min and re-anchored**; every differing event attributed on its own | §6.5 |
| G10 thin day hides FAIL | FAIL only once power met | Any FAIL condition makes the day FAIL regardless of power | §10 |
| G11 fill keys collide | key → fill map, ±2 s | Shadow reads the **same public websocket trade channel** as 88a; match by trade id, then multiset with ordinals; `AMBIGUOUS` class; page-full is a gap | §3.3, §6.6 |
| G12 dates not protected twice | gate-side refusal only | **Date allowlist** enforced by the gate-purpose exporter, wrapper, transfer and gate; calibration days pinned at ≥ `GATE_FIRST_UTC_DAY`; timeline restated (earliest MET 11-22) | §2, §5.3, §12 |
| G13 self-declared provenance | `provenance` string | Bundle bound to a **capture-host attestation** (SEALED ledger entry, 88a segment hashes, file hashes) published through the capture host's push path; M16 | §5.2 |
| G14 config binding gaps | four caps | `informed-v0` only, `adverse_markout == 0.0043`, six-cap mapping including `factor_cap`, fill rule = fill bound | §2 |
| G15 diagnostic admission mode | referenced a non-existent mode | Bridge's own guard, specified | §5.1 |
| G16 reward tolerance | 1e-4 tolerance | Reward diagnostic; recomputed by one formula from matched state | §6.6 |
| G17 coverage caps, D+1 minute, common mode | absent | Caps added; D+1 instants classified; receipt label states `decide()` is common-mode | §1, §10, §11 |
| Code drift (new) | — | `policy.py` differs between the shadow tree and the build tree (RE-1 lines); the shadow branch must be rebased onto the build line before a cohort can start | §2 |

---

## 1. What the gate proves, and what it cannot `[CHANGED — G1, G17]`

v1 tried to prove one thing, policy agreement, with one tier. v2 splits the risk into five parts. Each part has a
test whose pass is not implied by construction.

| # | Risk retired | Test | Independence that gives it power |
| --- | --- | --- | --- |
| R1 | The shadow **reads** the venue wrongly: wrong token, truncation, misparse, stale cache | B2: records with the same venue identity on both feeds must project identically | Two capture processes on two hosts; venue `hash`/`timestamp`/trade id as the common key |
| R2 | The shadow **builds records** wrongly from what it read | B0: the gate rebuilds every recorded input from the tape's raw payloads with the contract's projection functions | Contract projection functions are the exporter's semantics, not the runner's code |
| R3 | The shadow **composes** `decide()` inputs and state wrongly: own legs, portfolio, cooldowns, replacement, fills, latches, wakes | B1: `EngineV2` re-run on the shadow's own record stream must reproduce every observed shadow decision, resting state and fill | The engine composes from records with its own code. Daily counterfactual controls prove that B1 can catch each composition defect class on that day's data |
| R4 | Replay does not predict live-forward behaviour: feed divergence | B3: shadow vs replay of the production bundle, state and events aligned. Measured, bounded and attributed | Production capture vs workstation capture |
| R5 | The tape is dishonest or non-deterministic | Tier A: seal, self-replay, deterministic re-drive of the shadow composition | — |

**Not tested (receipt label, G17):** a defect inside `decide()` itself is common-mode. Both sides run the same
module, so the gate cannot see it. The gate also uses paper fills, which say nothing about queue position or
real fill realism. The receipt label is `LIVE_GATE_EVIDENCE_NOT_AUTHORITY;DECIDE_COMMON_MODE_UNTESTED;PAPER_FILLS`.

## 2. Preconditions checked before anything is read `[CHANGED — G7, G12, G14; NEW code-drift check]`

1. **Date admissibility (G12).**
   - `--day` is normalized with `date.fromisoformat(...).isoformat()` before any comparison.
   - D must be closed (`D < today UTC`). `embargo_reason(D)` must be `None`; the embargo constants move into a
     core module the gate, exporter and transfer all import (today they exist only on the shadow branch).
   - D must be `>= GATE_FIRST_UTC_DAY` (`2026-11-14`).
   - **D must appear in the date allowlist** (§5.3) with role `calibration` or `gated`.
   - Refusal is exit 2 with JSON. A test proves that no path under the tape root or bundle root was opened.
2. **Reserved window and MG-1 (G7.4).** Every `OutcomeView.model_id` in the shadow's records and in the
   bundle's `outcome_view` records must be in the **model allowlist** (`MODEL_ALLOWLIST`, a frozen gate
   constant; owner decision OD3). The MG-1 vector, RV-1, HG-1 and any other NBM-guidance candidate are never
   on it. Any other model refuses the day (`view_model_not_allowlisted`). The gate computes no forecast score
   and enumerates no outcome for a forecast candidate. Settlement is read only to price fills (MM paper
   scoring, exempt under the 2026-10-04 MG-1 exemption once the owner confirms OD3).
3. **Same policy, same configuration (G14).** The tape scope must satisfy all of the following, or the day is
   refused (`configuration_mismatch`); a difference is never tolerated:
   - `profile == "informed-v0"`; `blind_re1` is refused, because its engine path (`blind_tick`) records no
     comparable decisions;
   - `adverse_markout == 0.0043` exactly, because the engine never passes it and `DecisionInputs` defaults to
     0.0043;
   - `hazard_per_minute` equals `V2Config.hazard_per_minute`;
   - paper `fill_rule == V2Config.fill_bound`;
   - `max_book_gap_seconds == 60`;
   - the six-cap mapping is exact, as below.

   | Shadow config key (S1 adds `factor_cap`) | `V2Config` field |
   | --- | --- |
   | `caps.cash` | `initial_cash` |
   | `caps.band_cap` | `band_cap` |
   | `caps.order_cap` | `order_cap` |
   | `caps.wallet_cap` | `wallet_cap` |
   | `caps.event_cap` | `event_cap` |
   | `caps.factor_cap` | `factor_cap` |

4. **Same code (new finding).**
   - The receipt binds the SHA-256 of every `maker_core` module imported by the gate process, and the module
     hashes the shadow recorded at `day_open`. The two must be equal for `maker_core.quoting.*`,
     `maker_core.replay.v2.kernel`, `maker_core.contracts.*` and the contract projection module (§3.4), or the
     day is `REFUSED` (`code_drift`).
   - **Today they differ.** `C:\pt\wf` `policy.py` lacks the RE-1 hunks present at `501f47579`.
   - The shadow branch must therefore be rebased onto the build line before a cohort can start. Its RE-1-only
     hunks do not affect `informed-v0`, but the hash rule is exact.
   - A change to any bound hash starts a new cohort (§12).
5. **Every input channel present on both sides (G1.4).** All six channels must exist on both sides for the
   day: `descriptor`, `book`, `terms`, `outcome_view`, `info_event`, `coverage`.
   - A whole channel absent from one side is `REFUSED` (`channel_absent:<kind>`). Examples: no event provider,
     or a fair value that is `Unavailable` for every record of the day. It is never treated as feed
     divergence.
   - A channel that is `Unavailable` for part of the day is admissible. Those minutes are attributed in B3.
6. **Provenance (G13).** The bundle verifies against a capture-host attestation (§5.2) and
   `provenance == "captured"`, else `REFUSED`.

## 3. The input-construction agreement `[NEW — G2, G3, G4]`

This is the written contract between the shadow composition and the replay engine. **The engine's semantics
are normative**, because the engine is the registered reference. The shadow must implement each row exactly.
Each row names the conformance test and the counterfactual control (§7) that targets it.

Column "Shadow today" cites `C:\pt\wf` `runner.py`. Column "Engine" cites `m-v2ro` `replay/v2/kernel.py`
unless marked otherwise.

### 3.1 Every field `decide()` reads (`policy.py:185-436`)

| `DecisionInputs` field (what `decide()` reads) | Engine (normative) | Shadow today | Contract rule | Control |
| --- | --- | --- | --- | --- |
| `now` | The wake instant `at`, either a record's capture instant or an exact timer instant | Wall clock after the reads (`runner.py:250`) | The **logical instant**:<br>• a record wake uses the instant the read completed, which becomes the record's `captured_at`;<br>• a timer wake uses the exact due instant, never the wall clock.<br>Wall-clock lateness is recorded separately. | K15 |
| `market.condition_id`, `tick`, `min_order_size`, `close_at_utc` (and the whole descriptor, which is in the digest) | `state.latest["descriptor"].market` from the plugin `WeatherUniverse.describe(cid, now)` at export (`maker_replay_bundle_v02.py` `_project`) | Gamma discovery, then `tick`/`min_order_size` overwritten from the live book (`runner.py:240-241`) | Descriptor from the plugin `WeatherUniverse.describe` over the shadow's own discovery and book envelopes. Never overwritten from a book field. | K12 |
| `horizon_days` | Descriptor record's `horizon_days = (target − local date at capture)` | Fixed at discovery, up to `rediscover_minutes` stale (`maker_shadow.py:119-159`) | Recomputed from the event slug's target date and the local date at the record instant, as the exporter does | K13 |
| `book.yes_bids/yes_asks/no_bids/no_asks` | Bundle book payload decoded by `payloads` (levels merged by price, zero sizes dropped, bids descending, asks ascending, **all levels**). **Own resting legs are added** before `decide()` (`add_own`, `kernel.py:527-531`). | Sorted, truncated to 25 levels per side (`runner.py:25,75-82`), own legs **not** added. `decide()` then subtracts legs that were never in the book and overstates competing depth. | Contract projection `contract_book` (§3.4): every venue level, decoded exactly like `payloads` decodes a book record; then `add_own` exactly as the kernel does. No truncation; a size cap on raw bodies is a refusal, not a cut. | K1, K11 |
| `book.post_only_available` | Payload field, default `True` | Default `True` | As engine | — |
| `book.as_of_utc` | `min(capture time of the YES row, capture time of the NO row)` (`maker_plugin_runner.py:242`) | Receipt time of the later read (`runner.py:238-239`) | Per-side receipt times recorded; `as_of = min` of the two | K11 |
| `terms` (`as_of_utc`, `min_size`, `max_spread_cents`, `rate_per_day`) | The exporter's `reward_terms(index, cid, at)` over captured reward records; latest terms record | `terms_from_public` (`runner.py:94-105`) with its own date window | One shared projection: the exporter's `reward_terms` semantics, moved to a neutral module. The shadow keeps the raw reward record body and SHA. | B0 |
| `fair_value` (all fields, including `stdev`, `as_of_utc`, `valid_until_utc`, `calibration_grade`, `joint`, `model_id`, `inputs_hash`) | `state.latest["outcome_view"]`, the plugin `WeatherFairValue.evaluate(descriptor, at)` computed at export at each book capture | `unavailable_fair_value` hard-wired (`maker_shadow.py:162-164,184`) | The same plugin provider, evaluated at the record instant over the shadow's own public inputs (§4.2). Its view becomes a record. `decide()` reads the latest view record. | B0, B2 |
| `events` (each event's `affects`, `decided`, `action_hint`, `severity` and four clocks) | `state.latest["info_event"]` (`kernel.py:508,533`), the plugin `WeatherInformationClock` output at export | Never passed: defaults to `()` (`runner.py:254-260`; `policy.py:126`) | Same plugin clock provider over the shadow's own public inputs; an event record per change | K10 |
| `portfolio.cash` | `kernel.cash`: initial cash minus fill costs plus settlement payouts (`kernel.py:427-470`) | Static `caps.cash` (`runner.py:146`) | As engine, from the shadow's day-session paper fills | K2 |
| `portfolio.reserved_elsewhere` | Sum of other conditions' reserves | Sum of other resting legs' reserves | As engine (`recomputed_portfolio`, `kernel.py:574-601`) | K2 |
| `portfolio.band_cap` | `max(0, band_cap − this condition's inventory_cost)` (`assemble`) | Static `band_cap` | As engine | K2 |
| `portfolio.order_cap`, `wallet_cap`, `event_cap` | Config | Config | As engine | — |
| `portfolio.wallet_used` | `other_reserve + total inventory` | `committed` only (no inventory) | As engine | K2 |
| `portfolio.event_used` | This condition's inventory plus same-event others' reserve and inventory | Same-event others' reserve only | As engine | K2 |
| `portfolio.exposures` | One `ExposureLimit` per descriptor factor, `cap = factor_cap` | `()` | As engine, with the plugin `WeatherExposure().factors(descriptor)` and `caps.factor_cap` | K2 |
| `portfolio.active_other_bands` | Count of other conditions with legs **or lots** | `len(resting others)` | As engine | K3 |
| `portfolio.foreign_open_order`, `unknown_position`, `safety_breached` | `False` | `False` | `False`. The live guard owns these; they are outside the gate's composition. | — |
| `profile`, `hazard_per_minute`, `adverse_markout` | Config; `adverse_markout` never passed (0.0043) | Config | Bound by precondition 3 | — |
| `existing` | `state.legs`, the legs after the last decision. HOLD keeps them; CANCEL/END/NO_QUOTE clears them; QUOTE sets them (`record_decision`). | Resting legs after the guard (`runner.py:258`) | As engine for the **policy book**. Guard refusals are handled by §3.2 row "Guard". | K14 |
| `fill_seen` | Always `False`. A fill is handled at the trade record as an immediate `CANCEL FILL_CANCEL_SIBLING` (`kernel.py:478-481`). | `True` for the minute after a paper fill (`runner.py:258`) | Always `False`; fill handling as §3.2 | K7 |
| `last_requote_at` | `state.last_quote`, the instant of the last QUOTE decision | `placed_at`, set only when every leg passed the guard | As engine | K14 |
| `previous_fair_value` | `p_yes` of the latest view, updated **only** when the final decision at the instant is QUOTE (`kernel.py:550-552`) | Updated on every evaluated minute with a view (`runner.py:265-266`) | As engine | K6 |

### 3.2 Composition behaviour around `decide()`

| Behaviour | Engine (normative) | Shadow today | Contract rule | Control |
| --- | --- | --- | --- | --- |
| **Wake rule** (G4) | `decide()` only on a wake: a changed `record_signature` (book state, terms body, view state, event payload, fill), a due timer (book gap, terms expiry, view expiry, event boundaries, close − 3 h, active-interval edges), or a changed coverage state. Prints are ingested first at an instant, then other records by sequence, then woken conditions in condition-id order (`engine.py:126-161`). | Every condition every minute | As engine. The shadow computes the same signature and timers. On a timer it wakes at the exact due instant with the records it holds; it does not re-read first. A re-read is a later record instant. | K15, K16 |
| Pre-decide pulls | `OUTSIDE_ACTIVE_INTERVAL`, coverage pulls (`MISSING_*`, `CAPTURE_GAP`, `TRADE_CAPTURE_GAP`, `TERMS_CAPTURE_GAP`), `SETTLED`, sticky `DECIDED`, `AWAIT_FRESH_REENTRY_INPUTS` (resume latch after `INFO_PULL`), `REQUOTE_COOLDOWN` when flat within 60 s of the last QUOTE (`kernel.py:484-523`). Each is recorded as a pull decision. | None | As engine, recorded as decision events with the same action and reason | K4, K8, K9, K17 |
| Replacement | A CANCEL with a reason in `REPLACEMENT_REASONS`, when the last QUOTE is ≥ 60 s old, triggers a second `decide(existing=(), portfolio recomputed)` at the same instant (`kernel.py:546-549`) | Cancel now, re-decide next minute | As engine. Both events are recorded with an in-instant sequence. | K5 |
| State update after a decision | `record_decision` (`kernel.py:345-367`) | QUOTE → place through the guard; non-HOLD → clear | As engine for the policy book | — |
| **Fills** | A trade record is ingested before other records. If legs rest, coverage is valid just before `at`, the condition is active and `traded_at ≥ placed_at`, `fill_model.match` normalizes the price to the YES axis. The **first** matching leg in leg order fills `min(print size, leg size)`. Cash falls, a lot is added, and `CANCEL FILL_CANCEL_SIBLING` follows at once (`kernel.py:434-481`, `fill_model.py:31-45`). | `fill_legs` refills every leg from every crossing print of the **same asset** in the window (`paper.py:33-49`); `fill_seen` the next minute | As engine. Prints arrive as trade records from the websocket channel (§3.3). | K7 |
| Latches | `resume_after`, `decided`, settlement, `ended` (blind only) | None | As engine (informed: `resume_after`, `decided`, settled) | K8, K9 |
| **Day roll** (G5) | A one-day bundle starts flat: `initial_cash`, no legs, no lots, no latches | Carries legs, `placed_at`, previous views, paper ledger and latch across midnight | **Day-session semantics** (OD4). At logical instant `D 00:00:00Z` the shadow:<br>• withdraws every policy leg (a `day_roll` intent, not a policy decision);<br>• resets every per-condition field (`last_quote`, `previous_fair_value`, `resume_after`, `decided`, timers);<br>• opens a new decision portfolio with `cash = caps.cash` and no lots;<br>• writes `day_open` (§6.1) as the first record of D's tape. | K18 |
| Universe | Every bundle condition over its declared windows (`windows_of`) | Own Gamma selection, re-ranked every 15 min | The shadow's `universe` records define `active_intervals`. The gate passes them to `stream_source(bundle, active_intervals)` for both replays, so portfolio coupling sees the same band set. A shadow band absent from the bundle is `conditions_not_in_bundle`. | — |
| **Guard** | None | `OrderGate` refusals, partial-band withdrawal, PAUSE/HALT cancel-all | The policy book follows the engine. The **gated book** (what the guard let rest) is recorded separately. A condition with any guard refusal or cancel-all is `GUARD_GATED` from that instant until both books are flat. B1 excludes gated spans from comparison and counts them (§10). | — |

### 3.3 Raw record construction (what both sides turn into records)

| Record kind | Production (exporter, normative) | Shadow (contract) | Raw identity kept for B2 |
| --- | --- | --- | --- |
| `book` | `captured_book` over the 88a `/books` batch reply rows (one row per token) | Per-token `/book` replies projected by `contract_book` (§3.4) | Per side: venue `hash`, venue `timestamp` (ms), raw-body SHA-256. Body kept in full on hash change, by reference otherwise. |
| `terms` | `reward_terms(index, cid, at)` over captured reward replies | The same function over the shadow's reward replies | Raw reward-record SHA-256 |
| `descriptor` | `WeatherUniverse.describe` + `horizon_days` + `WeatherExposure` factors | The same three, over the shadow's discovery and books | Gamma event digest |
| `outcome_view` | `WeatherFairValue.evaluate` at each book capture | The same provider at each shadow book read (§4.2) | NBP `payload_hash`, slot, band partition, `model_id` (`inputs_hash` includes `fetched_at`, so it is not an identity key) |
| `info_event` | `WeatherInformationClock` output | The same provider | Per event: kind, station, `scheduled_at_utc`; triggers by source payload hash |
| `trade` | 88a websocket `last_trade_price` messages: `trade_id = id or sha256(message)`, `traded_at` from venue ms timestamp, availability = capture instant (`maker_replay_bundle.py:230-251`) | **The same public websocket market channel** (OD5), the same projection. data-api `/trades` is kept only as reconciliation, and a full page there is a `print_gap`. | Trade id, venue ms timestamp |
| `coverage` | Per condition: `trade_stream_ok` = every token subscribed and healthy; `valid_until = min(healthy_until, at + 30 s)`; health refreshed on every stream row (`maker_replay_bundle.py:189-195,223-235`) | The same rule over the shadow's own subscription | Subscription and lifecycle rows |

### 3.4 One projection module, imported by both sides

`maker_core.shadow.contract` holds the **neutral** projection functions: `contract_book`, `contract_terms`, the
coverage rule, the trade projection, `add_own` and portfolio assembly.
- No `weather` imports.
- The bodies are moved from (or proven equal to) `captured_book`, `reward_terms`,
  `Projection.coverage`/`stream` and kernel `add_own`/`recomputed_portfolio`.
- The frozen v0.1 exporter is **not edited**. Equality is proven by tests (§3.5); it is not achieved by
  refactoring the exam path.

### 3.5 Conformance tests (the proof that both sides build inputs identically)

1. `tests/market/test_shadow_contract_projection.py`.
   - Feed the same fictional raw venue bodies (books with unsorted, duplicate-price, zero-size and > 25 levels;
     reward records across a date boundary; websocket trade messages with and without `id`; lifecycle gaps)
     to the exporter functions (`captured_book` → `payloads` decode, `reward_terms`, `Projection.stream` and
     `coverage`) and to `maker_core.shadow.contract`.
   - Every decoded record must be byte-equal (`canonical_bytes`).
   - Property test (hypothesis): random level lists, random duplicate prices, random order.
2. `tests/maker_core/test_shadow_engine_differential.py`, the composition conformance test.
   - One scripted fictional day (2027, three bands, two events, one view change per hour, scheduled-print
     pulls, a print that fills a NO leg via a YES print, a replacement, a cooldown, a band exit, a day roll, a
     coverage lapse).
   - Run the **real** S1 shadow adapter (injected reads, simulated clock with timer wakes) and the **real**
     `EngineV2` (`keep=True, debug=True`) over the record stream the shadow wrote.
   - Required: identical ordered `DecisionEvent` lists per condition (fields as §6.4), identical legs after
     every instant, identical fills, identical cash and lots.
   - This is B1 in miniature. Every control K1-K18 must make it fail.
3. Identity-field coverage test.
   - Introspect `DecisionInputs` fields and the attribute reads of `decide()` (AST walk over `policy.py` for
     `i.<field>` and `i.<field>.<attr>`).
   - Assert that every read path appears in the identity projection (§6.4) and in the B0 rebuild.
   - A new field read by `decide()` fails the test until the contract names it.
4. Time-shift purity property.
   - Shifting every clock in a `DecisionInputs` by the same Δ leaves `decide()` equal in every field except
     `input_hash`.
   - This backs the claim that the time-normalized identity in §6.4 is complete.

## 4. Shadow composition change: work unit S1 on the shadow branch `[NEW — G7 / O1 extension]`

S1 is the shadow-branch work unit. It is the precondition for every gated day and **starts a new cohort**
(precondition 4).

The branch is rebased onto `codex/maker-replay-v2-build-20261003` first, so `maker_core` hashes match.

S1 is code only. Running the shadow live still needs the owner (CONSOLIDATED decision 25).

### 4.1 Providers injected into the runner

| Provider | Implementation | Notes |
| --- | --- | --- |
| Descriptor | Plugin `WeatherUniverse.describe` over the shadow's own Gamma discovery envelopes and book envelopes | Replaces `discover`'s hand-built descriptor and the per-minute tick override |
| Horizon | `(target − now.astimezone(spec.tz).date()).days` at each instant | Config `horizons` restricted to `{1, 2}`. `informed-v0` returns `HORIZON_NOT_ELIGIBLE` before reading a view (`policy.py:258-260`), so T+0 needs no served vector. |
| Exposure | Plugin `WeatherExposure().factors(descriptor)` | Feeds `portfolio.exposures`; requires `caps.factor_cap` |
| Fair value | Plugin `WeatherFairValue` (frozen zero-fit NBP CDF; `model_id` from `fair_value.model_id`) over a **workstation public-input store** (§4.2) | No production data. The `_fallback` branch is enabled only if its forecast source is a free public source the shadow can fetch itself. Otherwise S1 disables it, and those minutes are `Unavailable("fallback_not_reproducible_in_shadow")`. |
| Info events | Plugin `WeatherInformationClock(universe, triggers, bulletins)` over the same store | Scheduled prints (`STATION_ROUTINE_MINUTES`) and model cycles are deterministic. Observation triggers come from public METAR reads. |
| Prints | Public CLOB websocket market channel (as 88a) | data-api `/trades` reconciliation, with request limit and row count recorded (G11) |

### 4.2 Served-view source (OD2)

The shadow computes its views itself, on the workstation, with the frozen plugin code (module-hash bound) from
public NOAA NBP bulletins and public Gamma band data that it fetches and stores in its own tape-adjacent
input store.
- No production served vector crosses to the workstation. This respects `DELEGATION_CONTRACT.md` ("cannot see
  production `data/`").
- The live pilot must compute views on the same host for the same reason, so the shadow exercises the live
  path.
- When both feeds hold the same NBP `payload_hash`, slot and band partition, `p_yes`, `joint`,
  `valid_until_utc`, `model_id` and grade must be equal (B2). The view's `inputs_hash` differs by `fetched_at`,
  so it is **not** an identity key.

### 4.3 MG-1 check

- `MODEL_ALLOWLIST` (core constant) holds exactly the model ids the owner rules exempt (OD3): the plugin's
  `nbp-v2-piecewise-linear*` ids, plus `pit-lead1-normal-fixed-2C-equivalent` if the fallback stays enabled.
- The runner refuses to start if the provider's declared model set is not a subset of the allowlist.
- A view outside the allowlist is replaced by `Unavailable("model_not_allowlisted")` and recorded.
- The gate refuses any day containing one (precondition 2).

### 4.4 Live adapter

- New module `maker_core.shadow.live_kernel`.
- Recommended implementation (OD1): subclass `maker_core.replay.v2.kernel.Kernel` with live hooks.
  - `deadline` pushes onto a wall-clock timer queue.
  - `portfolio` uses `recomputed_portfolio`.
  - The run loop interleaves minute reads (records at read-completion instants) with timer wakes at exact due
    instants.
- Code is then shared with the replay. This is deliberate: the live executor must run this composition.
- B1 still has power over everything the adapter owns: the live scheduler, signature and timer bookkeeping
  under minute sampling, record construction, the guard split and day roll. The daily controls (§7) prove it
  on real days.
- If the owner prefers a re-implementation, §3 is the full spec and §3.5 test 2 is the acceptance test.

### 4.5 Tape v0.2 (`maker_core.shadow_tape.v0.2`)

Records, in order:

| Record | Contents |
| --- | --- |
| `day_open` | First record of each tape (§6.1) |
| `record` | One per ingested record, in the exact v0.2 bundle record shape (`kind`, `condition_id`, `captured_at`, `sequence`, payload, `payload_sha256`), plus a `raw` block: per-side venue `hash`/`timestamp`, raw-body SHA-256, and the body itself on change |
| `decision` | One per `DecisionEvent`: `at`, in-instant sequence, condition, the full `inputs_projection` (record-driven decisions) or pull identity (pull decisions), the decision projection, the wake cause (`record` / `timer:<kind>` / `coverage` / `fill`) |
| `gate` | Guard outcome per would-quote leg, cancel-all intents, `day_roll` intent |
| `fill` | Paper fill: trade id, leg, size, cost; lots |
| `minute` | Per-minute state snapshot: policy legs, gated legs, cash, lots, paper P&L summary, guard check |
| `clock` | NTP status sample (`w32tm /query /status` offset) at `day_open` and hourly; per-read latency |
| `universe` / `universe_error` | As today |
| `print_gap` | Reconciliation page-full or read error |
| `terminal` | As today |

Sealed per UTC day exactly as v0.1 (`TapeWriter.close`, seal schema bumped).

Size discipline:
- book bodies are stored only when the venue `hash` changes;
- a raw-body byte cap per read is a refusal recorded as `unevaluated`, never truncation;
- the tape reports its bytes.

### 4.6 CLI and scope

`build_runner` injects the providers.

The scope records:
- `composition` (`weather-maker-shadow-0.2`);
- the provider identities (model ids, module hashes);
- the input-store root hash per day;
- `factor_cap`;
- `fill_source: "clob_ws_market"`.

The literal `fair_value: "unavailable:..."` goes.

`load_config` refuses:
- `profile != informed-v0`;
- `adverse_markout != 0.0043`;
- horizons outside `{1, 2}`;
- a missing `factor_cap`.

### 4.7 S1 tests

- §3.5 tests 1-4.
- Provider-injection tests: the view is a real `OutcomeView` with an allowlisted model; events are non-empty
  on a scheduled-print fixture.
- Day roll writes `day_open` and leaves both books flat.
- The import closure loads no order client, credential, SDK or wallet module (reuse the existing closure test).
- Offline-fixture mode still works.

## 5. Inputs, transfer and provenance `[CHANGED — G12, G13, G15, G6]`

### 5.1 The replay bridge and its guard (G15)

`maker_core.shadow.gate.replay_bridge` drives `EngineV2(V2Config(policy="informed-v0", fill_bound=b,
keep=True, debug=True, …))` through `lockstep.drive` for two sources:

- **R_s, the shadow-fed replay.** The tape's `record` rows are rebuilt through `record_from_row` into an
  in-memory `DaySource` with `provenance="shadow_tape"` and `active_intervals` from the tape's universe.
- **R_p, the production replay.** It runs over the attested bundle (§5.2) via `stream_source(bundle,
  active_intervals)`.

The bridge's own guard, which is not an admission "mode" (no such mode exists):
- it accepts R_p only from `load_attested_bundle`, which requires the §5.2 attestation, the allowlist and
  `day == D`;
- it accepts R_s only from a sealed tape of D;
- the two provenances are type-distinct, so a shadow-built source can never be passed as R_p;
- it never imports `report`, `inference` or `pipeline`;
- it imports no `weather.*` (package-boundary ratchet);
- a test proves all of the above.

The gate never calls `build_report`. It runs no matched-clock rounds and produces no economic verdict.

### 5.2 Provenance bound to the capture host (G13)

For an allowlisted day, the capture host's gate-purpose export (§5.3) writes `attestation.json` beside the
bundle. It contains:
- `day`;
- the export `receipt.json` SHA-256;
- every bundle file's SHA-256 and bytes;
- the sidecar's SHA-256 (§5.4);
- the `SEALED` ledger entry verbatim;
- the 88a sealed-segment manifest hashes (the bundle's `input_hashes`);
- the exporter's module hashes (`replay_export` module-hash method);
- `purpose: "shadow_gate"`.

The capture host appends the attestation's SHA-256 to `config/maker_replay_v2/transfer_manifest.json`
(CONSOLIDATED decision 19, per-bundle keys). It goes through its own push path (`WeatherOneShotPush`), which is
roll-free config.

The gate refuses the bundle unless all of the following hold:
- (a) every file hash matches the attestation;
- (b) the attestation hash appears in `transfer_manifest.json` on `origin/master` in a commit made by the
  capture host's push identity;
- (c) `provenance == "captured"`;
- (d) `input_hashes` equals the attestation's segment hashes;
- (e) `purpose == "shadow_gate"`.

Limitation, stated in the receipt: without a capture-host signing key this is push-path attestation, not
cryptographic proof (OD8). It defeats M16, a bundle synthesized from the tape with a valid self-receipt,
because that bundle has no capture-host commit.

### 5.3 Date allowlist (G12)

`config/maker_shadow_gate/dates.json` lists `{date, role: "calibration" | "gated", approved_by_commit}`
entries. Entries are added only by owner-approved commits (roll-free config).

Enforcement points, each refusing **before opening any input**:

| Point | Rule |
| --- | --- |
| v0.2 exporter, new `--purpose shadow_gate` | Refuse unless the date is allowlisted, not embargoed and ≥ `GATE_FIRST_UTC_DAY`. U6's `export_permitted()` panel-window gate still runs first (CONSOLIDATED decision 3). Other purposes (registration calibration exports ≤ 09-29) are unaffected. |
| Nightly wrapper | Refuses `-Purpose shadow_gate` for an unlisted day; never defaults a shadow-gate day to "yesterday" |
| Transfer tool, both ends | Capture-host packaging and workstation receipt each refuse an unlisted day, or a package without an attestation |
| Gate CLI | Precondition 1 |

Calibration days are pinned at ≥ `GATE_FIRST_UTC_DAY`: **2026-11-14 and 2026-11-15**. Nothing is run "to be
ready" on an earlier date. Fixture days are in 2027.

### 5.4 Venue-stamp sidecar (G6)

The v0.2 bundle book payload is a policy `Book`: `as_of` plus levels. The venue `timestamp`/`hash` are not kept
(`maker_plugin_runner.py:242`). 88a does keep the raw `/books` reply bytes and their request latency
(`maker_evidence_public.py:117-122`).

The gate-purpose exporter therefore writes `gate_sidecar.jsonl` from the **same sealed segments**. Per book
record (`condition_id`, `captured_at`, outcome) it holds:
- venue `timestamp`;
- venue `hash`;
- raw-row SHA-256;
- request latency.

Per trade record it holds the websocket message id and venue ms timestamp.

The sidecar is hashed into the attestation and does not change the signed v0.2 format (OD9). No sidecar means
the day is `INCOMPLETE` (`clock_unmeasurable` / `b2_unpaired`), never silently skipped.

## 6. What is compared `[CHANGED — G1, G3, G4, G9, G11, G16]`

Tiers run in order. Tiers A, B0, B1 and B2 have zero tolerance. B3 is measured and bounded. C covers fills and
money.

### 6.1 Tier A: the tape is honest `[CHANGED — G5]`

- **A0 `day_open` (new).** The first record of every tape of D is `day_open`. It holds:
  - logical instant `D 00:00:00Z` (or the run start, if later);
  - the policy book flat;
  - decision cash `= caps.cash`, no lots, no latches;
  - the guard paper ledger opening snapshot (cash, lots, marks, bleed state);
  - module hashes;
  - provider identities;
  - the previous tape's seal SHA-256, recorded but never opened.

  A missing or non-flat `day_open` → `REFUSED` (`day_open_missing`).
- **A1 Self-replay (kept).** `score_day` agreement: every recorded record-driven decision re-derives from its
  recorded inputs.
- **A2 Deterministic re-drive (changed).** The gate re-runs the bound S1 adapter from `day_open` over the
  tape's own `record` rows and logical instants, with recorded guard outcomes injected. It must reproduce
  exactly every:
  - `decision` event;
  - policy and gated legs;
  - paper fill;
  - `minute` snapshot (cash, lots, paper P&L, trade count; Decimal equality).

  Because `day_open` carries the guard ledger, A2 never needs D−1. A test monkeypatches `open` to raise for
  any tape or bundle path of D−1 or D+1.
- **A3 Seal (kept).** `verify_journal(path, expected_digest=seal.sha256)`.

### 6.2 Tier B0: input provenance (zero tolerance)

For every `decision` with recorded inputs, the gate rebuilds `DecisionInputs` from the tape's `record` rows
alone. It uses the latest record of each kind at the decision instant, `add_own`, portfolio assembly from the
re-drive state, and the contract projections (§3.4) applied to the stored raw bodies.

The result must equal the recorded `inputs_projection` field for field, every clock included.

Additionally, every `record` payload must equal the contract projection of its stored raw body. A record
without its raw body is `REFUSED` for B0 (`raw_missing`).

### 6.3 Tier B1: the replay engine reproduces the observed shadow (zero tolerance; replaces the swap test)

R_s (§5.1) runs `EngineV2` over the shadow's own records at the shadow's own instants. The engine composes
everything itself (own legs, portfolio, cooldowns, replacement, `previous_fair_value`, fills, latches, wakes)
from records.

Outside `GUARD_GATED` spans, the following must hold:
- **Events.** Per condition, the ordered list of R_s `DecisionEvent`s equals the shadow's ordered `decision`
  list: same instants, same in-instant order, same decision fields (§6.4). An event on one side only is a
  mismatch.
- **State.** Policy legs after every instant are equal.
- **Fills.** R_s `Fill`s equal the shadow's paper fills (trade id, leg, size, cost).
- **Money.** Cash and lots are equal after every instant.

Why this is not satisfiable by construction:
- B1 compares two compositions over the same bytes. The engine composes from records with the frozen
  kernel's driver. The shadow composes with its live adapter: timers, sampling, record building, the guard
  split, the day roll.
- If S1 shares `Kernel`, the shared part is exactly what live will run. B1 then has power over the adapter, and
  §7's controls show on each day that a defect in each composition rule would have been caught on that day's
  data.

A B1 mismatch is `FAIL`.

### 6.4 Identity and decision fields (G3)

**Decision comparison fields:**
- `action`;
- `reasons`, order included;
- `legs`: outcome, Decimal price, Decimal size, order;
- `centre`;
- `share_many`;
- `net_per_minute`;
- `profile`.

**`input_hash` is never compared.** Both values are recorded. In B1 the full inputs are compared directly
(B0 plus the R_s event's inputs, rebuilt the same way), which is strictly stronger.

**Time-normalized identity projection N(i),** used in B3. Every field of `DecisionInputs`, with every datetime
replaced by its signed offset from `now` (exact `timedelta`):
- `book.as_of_utc`, `terms.as_of_utc`;
- `fair_value.as_of_utc`, `valid_until_utc`;
- the four clocks of every event;
- `market.close_at_utc`, `settle_at_utc`;
- `last_requote_at`.

`now` itself is reported as the alignment offset. `stdev`, the full descriptor, `horizon_days`, events,
`existing`, `fill_seen`, `previous_fair_value` and all thirteen portfolio fields are compared exactly.
- `input_hash` is excluded.
- `fair_value.inputs_hash` is excluded and replaced by the view's raw identity (§3.3), because it hashes
  `fetched_at`.

By §3.5 test 4, `N(i_s) == N(i_p)` implies equal decisions. Cross-feed identity is therefore a **code-identity
check**, not evidence about policy behaviour: its weight is in B0, B1 and B2. In practice N rarely matches
across feeds, because capture phases differ by seconds and `stdev` moves with time. That is expected and no
longer a power problem (§9).

### 6.5 Tier B2: raw-identity record conformance between the feeds (zero tolerance on pairs)

Pairs are formed only on venue identity, never on time proximity alone.

| Pair | Key | Must be equal |
| --- | --- | --- |
| Book side | Same token, same venue `hash` (shadow tape raw block vs sidecar). On calibration days the gate verifies that equal `hash` ⇒ equal raw levels. If the venue hash is not a content hash, the key falls back to (token, venue `timestamp`). | The contract-decoded levels of that side |
| Terms | Same raw reward-record SHA-256 | `min_size`, `max_spread_cents`, `rate_per_day` |
| View | Same NBP `payload_hash`, slot, band partition | `p_yes`, `joint`, `valid_until_utc`, `model_id`, grade (`stdev` recomputed at a common instant with the plugin's `_view` formula) |
| Scheduled event | Same (kind, station, `scheduled_at_utc`) | Full payload except observation clocks |
| Trade | Same websocket trade id | `outcome`, price, size, `traded_at` (ms), aggressor side |

- A key-equal pair whose projections differ is `RAW_PARSE_MISMATCH` → `FAIL`. One side mis-read the same
  venue bytes.
- Unpaired records are counted, never a failure.
- Floors (§9): paired book sides per day, and the paired fraction of the shadow's book reads.

### 6.6 Tier B3: cross-feed agreement, shadow vs R_p (measured, bounded, attributed) `[CHANGED — G4, G9]`

**State trajectory (every minute).** At each shadow `minute` instant t, the shadow's policy legs for each
compared condition are compared with R_p's legs at t (from R_p intervals). The result is `state_agree` or
`state_differ`.

**Event alignment (G4).**
- For each condition and each shadow instant t_k, take R_p's events in `(t_{k−1}, t_k]`.
- R_p events at one instant are ordered by engine sequence; compare the **last** R_p event in the window with
  the shadow's last event in the same window.
- A window with events on one side only is `one_sided_event`.
- There are no per-minute HOLD comparisons: the shadow emits no event where the engine would not wake.

**Attribution: every differing window gets its own explanation (G9).** For each differing window, the
comparator:
1. computes the rows where `N(i_s)` and `N(i_p)` differ, using the latest records at each side's event
   instant;
2. checks each differing input row against B2 identity.

   | Row | Class |
   | --- | --- |
   | Different venue identity, or one side has no record | `FEED_<KIND>` (book, terms, view, event, coverage, trade) |
   | Same identity | Impossible after B2. If it occurs, it is `RAW_PARSE_MISMATCH` → `FAIL`. |
   | Only clock offsets differ | `TIMING` |
   | Only carried state differs (`existing`, `last_requote_at`, `previous_fair_value`, portfolio, latches) | `STATE`, valid only if a non-`STATE` differing window exists in the same condition, or for the portfolio rows in any condition, within the previous **30 minutes**. Otherwise `STATE_ORPHAN`. |

3. If `N(i_s) == N(i_p)` while decisions differ: `CODE_IDENTITY_FAIL` → `FAIL`.

**Episodes, capped and re-anchored.**
- An episode is a maximal run of differing windows of one condition.
- At **30 minutes** an episode is closed as `OVERLONG`. The next window opens a fresh episode, which must find
  its own non-`STATE` cause within the cap.
- Every episode minute counts against the agreement floor (§9).
- `STATE_ORPHAN` minutes are listed per condition and counted.

Since B1 already proves composition on every event, a long episode can no longer hide a composition defect. It
can only lower the measured agreement, and the cap keeps that measurement honest.

### 6.7 Tier C: fills, inventory and money `[CHANGED — G11, G16]`

- **B1 fills (zero tolerance)** are covered in §6.3. This is where fill-handling composition is judged.
- **Cross-feed prints (C1).**
  - Every trade of a shadow-compared condition is matched to the bundle's trade stream by **trade id**.
  - Where an id is absent on either side, matching is by multiset on `(cid, asset, price, size)` within
    ±2 s of venue time, with counts and ordinals; the key is `(id or tx, asset, price, size, ordinal)`.
  - Classes:

    | Class | Meaning | Disposition |
    | --- | --- | --- |
    | `MATCHED` | Matched | ok |
    | `AMBIGUOUS` | More than one candidate after multiset matching | Counted; capped at 2 % of prints, above which the day is INCOMPLETE |
    | `PRINT_ABSENT` | A recorded gap or coverage exclusion covers the time | Counted; capped at 20 % (O5) |
    | `UNEXPLAINED_PRINT` | Present in one feed while both were covered and gap-free | `FAIL` |

  - This tests the print-reading layer on every print, not only on fills, so n is large.
- **Cross-feed fills (C2, measured).** Shadow paper fills vs R_p fills, keyed by trade id. Reported as
  agreement and attributed as in B3 (a fill on one side only follows from a state difference or a print
  class). Not a FAIL source by itself.
- **Inventory and cash.** Exact between the shadow and R_s (B1). Cross-feed values are reported.
- **Reward (G16).** Diagnostic only. Both sides are recomputed by one formula from each side's resting state
  per minute (`rate/1440 × share_many` of the recorded decision). No tolerance gate.
- **Rebate and settled P&L.** Kept, derived from the matched fill set. `unresolved` when settlement is absent.
- **Markouts.** Diagnostic (O10).

## 7. Counterfactual controls: daily proof that B1 has power `[NEW — G1, G8]`

`maker_core.shadow.gate.controls` defines one **defect variant** per composition rule of §3. It is a separate
module, hashed into the receipt. Each day, after A2, the gate re-drives the shadow adapter once per variant
(same records, same instants, same guard outcomes) and runs the B1 comparison of that output against R_s.

| Control | Planted defect (v1-era runner behaviour where applicable) | Stratum it proves |
| --- | --- | --- |
| K1 | Own legs not added to the book | Quoting with resting legs |
| K2 | Static portfolio: no cash fall, no inventory, no exposures | Portfolio after fills / multi-band |
| K3 | `active_other_bands` counts resting only | Multi-band with lots |
| K4 | No re-entry cooldown pull | Re-entry |
| K5 | No same-instant replacement | Requote |
| K6 | `previous_fair_value` updated every evaluation | View change with legs |
| K7 | Same-asset-only refill-every-print fills, `fill_seen` next wake | Fill → cancel |
| K8 | No `INFO_PULL` resume latch | Info pull and re-entry |
| K9 | No sticky `DECIDED` | Decided event |
| K10 | Events dropped | Info pull / widen |
| K11 | Book truncated to 25 levels and `as_of` = later side | Deep books / freshness |
| K12 | Descriptor tick and min size from the book | Descriptor |
| K13 | Horizon fixed at discovery | Local-midnight horizon change |
| K14 | `last_requote_at` = gated placement time | Cooldown after a gated quote |
| K15 | Timer wakes deferred to the next minute | Timer-driven pulls |
| K16 | Decide every minute (no wake rule) | Quiet periods |
| K17 | Coverage pulls ignored | Coverage lapse |
| K18 | No day-roll reset | Day roll |

**Rules:**
- A control is **killed** on D if its re-drive produces ≥ 1 B1 mismatch.
- A control that is not killed means D did not exercise that transition. The stratum is not credited for D.
  This is not a failure.
- The unmutated re-drive must equal the tape (A2) before any control runs, so a control mismatch is
  attributable to the plant.
- Controls never alter the verdict path except through `controls_killed`. They are not alternate gate
  behaviour, and they write nothing as shadow output.
- **Negative control:** R_s run twice must give byte-identical decision SHA (`EngineV2.summary()["decision_sha256"]`).

## 8. Clock check with real power `[CHANGED — G6]`

**Measure.** Each side's latency against the **venue clock** is `L = receipt time − venue book timestamp`:
- shadow: per-side receipt time from the tape raw block;
- production: the 88a `captured_at` per row, from the sidecar.

**Statistic.**
1. Per hour h and side: the lower envelope `E_h = p05(L)` (robust to the venue timestamp being either response
   time or last-change time) and `P_h = p95(L)`.
2. Skew per hour: `S_h = E_h(shadow) − E_h(production)`.
3. Both NTP samples (tape `clock` records; the attestation carries the capture host's) are reported.

**Bounds.**
- `max_h |S_h| ≤ 2 s`;
- `max_h P_h ≤ 5 s` per side;
- `min_h E_h ≥ −0.5 s` per side (a receipt before the venue time means the clock is behind).
- An hour with < 30 paired observations is unmeasurable. < 18 measurable hours → `INCOMPLETE`
  (`clock_unmeasurable`).

The maximum over hours, not a median, catches bimodal skew. A 6 s injected skew (M11) moves `E_h(shadow)` by
6 s and fails.

**Calibration days** record which venue-timestamp semantics hold: whether the timestamp advances with an
unchanged `hash`. The receipt states it.

## 9. Tolerances and statistics `[CHANGED — G8, G16]`

### 9.1 Zero-tolerance checks

| Check | Why zero |
| --- | --- |
| A0-A3 | Deterministic re-derivation of the tape's own records |
| B0 | Same raw bytes through the contract projection |
| B1 (events, legs, fills, cash, lots) | Same records, same instants, same `decide()`; the engine and the adapter must compose identically |
| B2 key-equal pairs | Same venue bytes |
| `CODE_IDENTITY_FAIL`, `UNEXPLAINED_PRINT` | A difference with no input or feed difference |

### 9.2 Measured quantities and floors

All provisional. Set on the two calibration days, frozen before 11-16, and **never loosened inside a cohort**
(OD10).

| Quantity | Floor / cap | Basis |
| --- | --- | --- |
| B2 paired book sides per day | ≥ 2,000, and ≥ 25 % of the shadow's book-side reads paired | Power for the reading layer. Two minute-cadence samplers of slowly changing weather books should share many snapshots; calibration measures the true rate. |
| B3 state agreement | ≥ 80 % of compared condition-minutes `state_agree` | How well replay predicts live-forward. Below the floor → `INCOMPLETE` (a feed property), unless a FAIL rule fired. |
| `OVERLONG` + `STATE_ORPHAN` minutes | ≤ 5 % of compared condition-minutes | The attribution must stay honest |
| `PRINT_ABSENT` | ≤ 20 % of prints (O5) | Feed quality |
| `AMBIGUOUS` prints | ≤ 2 % | Key quality |
| `REPLAY_EXCLUDED`, `SHADOW_UNEVALUATED`, `GUARD_GATED` (G17) | each ≤ 10 % of condition-minutes | Transparency; denominators cannot silently shrink |
| Per-day distinct contexts | ≥ 200 distinct `N(i)` digests among R_s record-driven events, ≥ 20 QUOTE events, ≥ 10 pull events withdrawing legs, ≥ 2 markets with a QUOTE | Stops one band in one hour from carrying a day (G8c) |

### 9.3 The power model (replaces the independent-minute model)

v1 assumed independent decisions, n ≥ 300 per day.

**Why that model fails.**
- Under purity, `decide()` cannot diverge on identical inputs (G8a).
- Consecutive minutes with unchanged state are one test repeated (G8b).

**Unit and per-trial probability.**
- Composition defects live in **transitions**: placement, requote and replacement, fill → cancel, info pull →
  re-entry, cooldown, band exit, day roll, coverage lapse, and multi-band coupling.
- Within one condition-day, the occurrences of a transition share market regime, book shape and view, so they
  are strongly correlated.
- The unit is therefore the **condition-day cluster per stratum**. A cluster is a qualifying trial if the
  stratum's transition occurred at least once in it (from R_s events).
- Treating all occurrences inside a cluster as one trial is conservative under any within-cluster
  correlation.
- Suppose a defect manifests in a fraction q of qualifying clusters. Then
  `P(detect) = 1 − (1 − q)^n` over n clusters.

| n (clusters per stratum per cohort) | Power at q = 10 % | Power at q = 5 % |
| --- | --- | --- |
| 29 | 95.3 % | 77.4 % |
| 59 | 99.8 % | 95.2 % |

**Cohort requirement.** Each required stratum (S-PLACE, S-REQUOTE, S-HOLDLEGS, S-INFOPULL, S-REENTRY,
S-MULTIBAND, S-DAYROLL, S-BANDEXIT) needs both:
- ≥ 29 qualifying clusters across the counted PASS days, spanning ≥ 3 distinct markets (cities) to limit
  between-cluster correlation by region;
- its control killed on ≥ 3 distinct PASS days.

The controls convert "would a defect of this class have been seen?" from an assumption into a per-day
observation.

**Rare strata.**
- S-COVERAGE and S-GUARD are proven on fixtures. They are reported from live days and not required.
- S-FILL is handled below.

**Fill floor (G8d).**
- Counted fills are B1 paper fills, capped at 3 per condition-day to bound clustering.
- **≥ 29 counted fills** gives 95.3 % power against a defect affecting 10 % of fill events. The v1 floor of 5
  gave 41 %.
- If the cohort reaches 7 PASS days with < 29 counted fills, or 14 days elapse, the summary is
  **`FILLS_UNPROVEN`** and goes to the owner. It never auto-passes (OD11).

## 10. Per-day verdict `[CHANGED — G10, G17]`

Statuses: `REFUSED`, `NOT_RUN`, `PENDING`, `FAIL`, `INCOMPLETE`, `PASS`.

| Status | Condition |
| --- | --- |
| `REFUSED` | A precondition failed: date, allowlist, embargo, model allowlist, configuration, code drift, channel absent, provenance, `day_open`, seal. Nothing else is read after the failing check. |
| `PENDING` | No attested bundle yet. After 3 UTC days it becomes `INCOMPLETE` (`bundle_never_arrived`) and the owner is told. |
| `FAIL` | **Any** of the following, regardless of power (G10): an A1/A2 mismatch; a B0 mismatch; a B1 mismatch (event, legs, fill, cash, lots); `RAW_PARSE_MISMATCH`; `CODE_IDENTITY_FAIL`; `UNEXPLAINED_PRINT`; the negative control not identical. |
| `INCOMPLETE` | Any floor or cap in §9.2 unmet; clock bound or clock unmeasurable; tape coverage of the quoting window < 90 % of minutes; overlapping runs; > 10 % of shadow condition-minutes on bands absent from the bundle; sidecar absent. |
| `PASS` | Everything above holds |

- Order: `REFUSED` > `FAIL` > `INCOMPLETE` > `PASS`.
- A `FAIL` on any day, thin or not, is counted as a `fail_day` and ends the cohort.
- Instants recorded in D's tape are all inside `[D 00:00, D+1 00:00)` by the day-roll rule. A read that
  completes after midnight is a D+1 record. The gate never fetches D+1. A D-tape instant outside D is
  `REFUSED` (`instant_outside_day`) (G17).
- A receipt is never changed. A late bundle for a `PENDING` day produces a superseding receipt that references
  the pending one by hash.

## 11. Missing data `[KEPT, with G11/G17 additions]`

| Missing | Handling |
| --- | --- |
| No tape | `INCOMPLETE` (`no_sealed_tape`); unsealed tapes listed |
| Partial tape | Coverage = minutes with a `minute` record ÷ minutes in the declared quoting window; < 90 % → `INCOMPLETE`, with the gaps listed |
| No attested bundle | `PENDING`, then `INCOMPLETE` |
| No sidecar | `INCOMPLETE` |
| Band absent from the bundle | Not compared in B2/B3 (still in A, B0, B1); `conditions_not_in_bundle`; > 10 % → `INCOMPLETE` |
| Replay excluded interval | `REPLAY_EXCLUDED`; counted; capped |
| Shadow `unevaluated` read | Counted; capped |
| Print gaps (websocket gap, reconciliation page-full, read error) | Prints inside the gap are `PRINT_ABSENT` candidates only if the gap covers the print time; otherwise `UNEXPLAINED_PRINT` |
| Settlement absent | Settled P&L `unresolved`; the day can still PASS |
| View `Unavailable` for part of the day on one side | Those windows attribute `FEED_VIEW`. All day → `REFUSED` (channel absent). |
| Guard HALT/PAUSE | `GUARD_GATED` spans; B1 compares only ungated spans; > 10 % → `INCOMPLETE` |

Nothing missing is read as zero fills, zero exposure or agreement.

## 12. The seven-day rule `[CHANGED — G8, G12]`

- **Cohort.** A cohort starts at the first gated day after any bound hash last changed: shadow and gate module
  hashes, configuration digest, provider identities, `MODEL_ALLOWLIST`, controls module, thresholds. It ends
  when any of them changes. Cohorts are never pooled.
- **MET** requires all of the following within one cohort:
  - ≥ 7 `PASS` days and 0 `FAIL` days, within ≤ 14 calendar days;
  - ≥ 5 distinct local market days with a gated QUOTE;
  - every required stratum meets §9.3;
  - ≥ 29 counted B1 fills.
- **Other outcomes.** Below the fill floor the summary is `FILLS_UNPROVEN` (owner decides). Otherwise it is
  `NOT_MET` with the first unmet rule.
- `INCOMPLETE` and `PENDING` days neither count nor reset; they are listed.
- **Calibration days** 2026-11-14 and 2026-11-15:
  - same code and receipts, flagged `calibration: true`, never counted;
  - they set the §9.2 floors and the venue-timestamp semantics;
  - the thresholds are then frozen into the gate constants by a reviewed change before 11-16. That change
    starts the cohort.
- **Timeline (G12).**
  - S1 must be merged and the shadow running with providers before `2026-11-14T00:00Z`. Tapes written during
    the embargo are never read.
  - The first counted day is 11-16, so the **earliest MET is 2026-11-22**, realistically late November or
    early December.
  - The fill floor may push the result to `FILLS_UNPROVEN`.
  - The gate never shortens because the look was early.

## 13. Receipt and summary `[CHANGED]`

**Day receipt.** Schema `maker_core.shadow_gate_day.v0.2`. Canonical JSON, create-only, at
`data/maker_shadow/gate/<D>-<sha256[:16]>.json` (`weather.paths.data_path`).

```
schema_version, label ("LIVE_GATE_EVIDENCE_NOT_AUTHORITY;DECIDE_COMMON_MODE_UNTESTED;PAPER_FILLS"),
utc_day, calibration, cohort_id, status, reasons[]
binding: tapes[] {name, sha256}, day_open_sha256, bundle {day, attestation_sha256, receipt_sha256, files{},
         sidecar_sha256, transfer_manifest_commit}, allowlist_entry, shadow_scope{}, replay_config{},
         module_sha256{}, controls_module_sha256, model_allowlist, thresholds{}, gate_version
coverage: minutes_declared, minutes_taped, gaps[], condition_minutes, unevaluated, replay_excluded,
          guard_gated, conditions_not_in_bundle
clock: per_hour[] {E_shadow, E_prod, S, P_shadow, P_prod, n}, max_abs_skew, ntp{}, venue_ts_semantics
tier_a: day_open_ok, self_replay {matched, mismatched}, redrive_exact, seal_ok
b0: decisions_rebuilt, records_rebuilt, mismatches[]                               (must be empty)
b1: events_shadow, events_rs, mismatches[] {condition, at, seq, field, shadow, rs}  (must be empty),
    fills_equal, cash_lots_equal, negative_control_identical, decision_sha256 {shadow, rs}
controls: {K1..K18: killed (bool), first_mismatch}
strata: {stratum: {clusters[] (condition-day ids), occurrences}}
b2: pairs {book, terms, view, event, trade}, paired_fraction_book, raw_parse_mismatches[] (must be empty)
b3: compared_condition_minutes, state_agree, one_sided_events, episodes[] {condition, start, end, class,
    capped, windows[] {at, rows[], class}}, timing, state_orphan, code_identity_fail (must be 0)
prints: matched, ambiguous, print_absent, unexplained (must be 0), rows[]
fills: b1_counted (cap 3 per condition-day), cross_feed {matched, shadow_only, replay_only}
money: cash {shadow, rs, rp}, cost_basis, reward_k1 (diagnostic), nominal_rebate,
       settled_inventory_pnl {value | "unresolved", unresolved_fills}, markouts (diagnostic)
```

**Summary.** Schema `maker_core.shadow_gate_summary.v0.2`, create-only, recomputed from the receipts it
references by hash. It holds:
- `cohort_id` and `days[]`;
- `pass_days`, `fail_days`, `incomplete_days`;
- `span_days`, `market_days_with_quotes`;
- `strata{}`, `counted_fills`;
- `gate: MET | NOT_MET | FILLS_UNPROVEN` and `first_unmet_rule`.

A cohort day with no receipt makes the summary `NOT_MET` (`silent_omission`). The live preflight cites the
summary hash (O7).

**CLI** (`python -m weather.market.maker_shadow_gate`):
- `day --day D --tape-root --bundle-root --receipt-root`;
- `summary --receipt-root --cohort`.

Exit 0 on a written receipt, 2 on refusal. It runs on the workstation under `workstation_heavy.ps1`, and never
on the capture host.

## 14. Module layout `[CHANGED]`

**Shadow branch (S1):**

| Module | Responsibility |
| --- | --- |
| `src/maker_core/shadow/contract.py` | Neutral projections (§3.4) |
| `src/maker_core/shadow/live_kernel.py` | Live adapter (§4.4) |
| `src/maker_core/shadow/tape.py` | Tape v0.2 (§4.5) |
| `src/weather/market/maker_shadow.py` | Providers, scope, config refusals (§4.6) |
| `src/weather/market/maker_shadow_inputs.py` | Workstation public-input store (NBP, Gamma, METAR) for the plugin providers |

**Gate (after Defender pass and owner sight):**

| Module | Responsibility |
| --- | --- |
| `src/maker_core/shadow/gate/dates.py` | Embargo constants, `GATE_FIRST_UTC_DAY`, allowlist loader (no `weather` import) |
| `src/maker_core/shadow/gate/provenance.py` | Attestation verification, `load_attested_bundle` (§5.2) |
| `src/maker_core/shadow/gate/replay_bridge.py` | R_s and R_p, bridge guard (§5.1) |
| `src/maker_core/shadow/gate/tier_a.py` | `day_open`, self-replay, deterministic re-drive, seal |
| `src/maker_core/shadow/gate/b0.py` | Input provenance |
| `src/maker_core/shadow/gate/b1.py` | Event-for-event comparison, fills, money |
| `src/maker_core/shadow/gate/controls.py` | K1-K18 defect variants and the kill harness |
| `src/maker_core/shadow/gate/b2.py` | Raw-identity pairing |
| `src/maker_core/shadow/gate/b3.py` | State trajectory, event alignment, attribution, capped episodes |
| `src/maker_core/shadow/gate/prints.py` | Trade-id and multiset print matching |
| `src/maker_core/shadow/gate/clock.py` | §8 |
| `src/maker_core/shadow/gate/strata.py` | Cluster counting (§9.3) |
| `src/maker_core/shadow/gate/day.py` | Thresholds (frozen constants), verdict order |
| `src/maker_core/shadow/gate/receipt.py` | Schemas, create-only writes, cohort id |
| `src/weather/market/maker_shadow_gate.py` | CLI: date normalization, allowlist, `weather.paths` roots, module-hash binding |
| `docs/operations/maker-shadow-gate.md` | Contract (new owner document) |

**Capture-host side** (separate unit, roll-sensitive rules apply): the `--purpose shadow_gate` export with
allowlist, sidecar and attestation; the wrapper `-Purpose` parameter; the transfer tool. All are on HOLD with
O9.

## 15. Tests and mutants `[CHANGED]`

**Fixture rig** (`tests/maker_core/fixtures/shadow_gate_rig.py`):
- one scripted fictional 2027 day produces:
  - the venue raw bodies;
  - a sealed tape v0.2 written by the **real** S1 adapter;
  - an attested v0.2 bundle plus sidecar built through the exporter's projection functions from the same raw
    bodies;
  - a fictional transfer-manifest commit;
- knobs inject feed divergence (different snapshot phases, missing reads) and every planted defect.

v1's claim that the sides "agree by construction" is withdrawn: they agree only because S1 implements §3, and
§3.5 test 2 proves it.

**Mutants.** Each must produce the stated outcome, or its test fails.

| # | Mutant | Required outcome |
| --- | --- | --- |
| M1 | Shadow leg price one tick off on one event | B1 mismatch → `FAIL` |
| M2 | Shadow ignores events (K10 as a tape) | B1 mismatch on the first `INFO_PULL` → `FAIL` |
| M3 | Shadow size cap wrong | B1 → `FAIL` |
| M4 | Paper fill with no print in either feed | B1 fill mismatch → `FAIL` |
| M5 | Paper cash drifts 1e-6 | A2 → `FAIL` |
| M6 | Tape byte changed after sealing | `REFUSED` (`tape_seal_mismatch`) |
| M7 | Bundle of another day | `REFUSED` (`bundle_day_mismatch`) |
| M8 | Comparator ignores `reasons` | The reasons-only plant must still `FAIL`; the mutant makes that test fail |
| M9 | Day with zero B2 pairs | `INCOMPLETE`, never `PASS` |
| M10 | B1 disabled (comparator returns equal) | Controls report 0 kills; a test asserting K1 kills on the rig fails |
| M11 | 6 s skew injected into shadow receipt times | `INCOMPLETE` (`clock_skew`) |
| M12 | 6 PASS + 1 FAIL; 7 PASS across two cohorts; 7 PASS with 10 fills | `NOT_MET`, `NOT_MET`, `FILLS_UNPROVEN` |
| M13 | Bridge fed the tape as R_p | Type guard refuses; no attestation → `REFUSED` |
| M14 | `share_many` flipped by 1e-9 on R_s only | B1 → `FAIL` |
| M15 | Caps differ / `adverse_markout` 0.005 / `blind_re1` | `REFUSED` (`configuration_mismatch`) |
| M16 | Bundle synthesized from the tape with a valid self-receipt and `provenance="captured"` | `REFUSED` (no capture-host attestation commit) |
| M17 | Shadow truncates books to 25 levels (key-equal venue hash) | B2 `RAW_PARSE_MISMATCH` → `FAIL`, and B0 if the raw body is kept |
| M18 | Record payload differs from its raw body's projection | B0 → `FAIL` |
| M19 | `day_open` missing, or non-flat at 00:00 | `REFUSED` |
| M20 | Any code path opens a D−1 or D+1 tape or bundle | The test's patched `open` raises; the test fails |
| M21 | Allowlist bypass: an embargoed or unlisted `--day`, including `2026-11-13` and the non-normalized `2026-11-1` form | `REFUSED` before any open, at the exporter, the transfer and the gate |
| M22 | View with `model_id` outside the allowlist | `REFUSED` (`view_model_not_allowlisted`) |
| M23 | `input_hash` included in the comparison (monkeypatched) | The cross-feed identical-N plant reports `CODE_IDENTITY_FAIL`; the test asserting it does not fails |
| M24 | B3 episode cap removed | The rig's all-day `FEED_EVENT` episode must show `OVERLONG` windows; the mutant hides them and the test fails |
| M25 | FAIL suppressed on a thin day | A B1 mismatch on a day below floors must be `FAIL`; the mutant yields `INCOMPLETE` and the test fails |
| M26 | Two equal-key prints at the same second | `AMBIGUOUS`, never a silent single match |
| M27 | Reconciliation page full, with no gap recorded | `print_gap` recorded; prints in it are `PRINT_ABSENT` candidates |

Mutants are monkeypatch or fixture knobs in tests, never alternate code paths in the gate. The daily controls
(§7) are a separate, hashed harness that cannot change a verdict except through `controls_killed`.

## 16. Disposition of every Defender finding

| Finding | Severity | Disposition |
| --- | --- | --- |
| G1 | BLOCKER | Resolved: swap test removed; B0, B1, B2 and daily controls (§6, §7). Channel-absent → `REFUSED` (§2.5). |
| G2 | BLOCKER | Resolved: §3 contract, S1 (§4), conformance tests (§3.5), `active_intervals` from the shadow universe |
| G3 | BLOCKER | Resolved: §3.1 lists every read field; N(i) covers every field and clock; `input_hash` never compared; §3.5 tests 3-4 |
| G4 | BLOCKER | Resolved: shadow adopts the wake rule; B1 event-for-event; B3 windowed last-by-sequence; state compared every minute |
| G5 | BLOCKER | Resolved: day-session semantics plus `day_open`; A2 from `day_open`; M19, M20 |
| G6 | MUST-FIX | Resolved: §8 venue-clock envelope per hour; sidecar (§5.4); unmeasurable → `INCOMPLETE` |
| G7 | MUST-FIX | Resolved: §4 providers, served-view source, MG-1 allowlist, CLI change, new cohort |
| G8 | MUST-FIX | Resolved: §9.3 cluster/transition model, controls, per-day context floors, fill floor 29 or `FILLS_UNPROVEN` |
| G9 | MUST-FIX | Resolved: per-window attribution, 30-min cap with re-anchoring, minutes counted |
| G10 | MUST-FIX | Resolved: §10, M25 |
| G11 | MUST-FIX | Resolved: websocket trade ids, multiset with ordinals, `AMBIGUOUS`, page-full gap |
| G12 | MUST-FIX | Resolved: allowlist at four points, normalized dates, calibration days 11-14/15, earliest MET 11-22, O9 as OD6 |
| G13 | MUST-FIX | Resolved within limits: capture-host push-path attestation; M16; signing key left to OD8 |
| G14 | MUST-FIX | Resolved: §2.3 |
| G15 | MUST-FIX | Resolved: §5.1 |
| G16 | NOTE | Adopted: reward diagnostic |
| G17 | NOTE | Adopted: caps, D+1 rule, common-mode label |

## 17. Remaining owner decisions (each with a recommendation)

| # | Decision | Recommendation |
| --- | --- | --- |
| OD1 | **Composition (O1 extension).** The shadow adopts the engine's semantics (§3), implemented as a live adapter that subclasses the v2 `Kernel` (shared code is what live will run). This starts a new cohort, and the shadow branch is rebased onto the build line first. | **Yes, the kernel-sharing adapter.** A re-implementation doubles the code that can drift; B1 and the controls still test the adapter. |
| OD2 | **Served-view source.** Views are computed on the workstation by the frozen plugin provider from public NBP/Gamma inputs, with horizons `{1, 2}` only. No production served vector is relayed. | **Yes.** It is the same path the live pilot must use, and it keeps the delegation boundary. |
| OD3 | **MG-1 ruling.** The maker plugin's frozen zero-fit NBP CDF (`nbp-v2-piecewise-linear*`; plus `pit-lead1-normal-fixed-2C-equivalent` if the fallback stays) is the MM fair-value input. Using it in the gate is "MM paper scoring" under the 2026-10-04 exemption, not an MG-1 candidate use. The gate computes no forecast score. MG-1, RV-1 and HG-1 are never allowlisted. Supersedes O2. | **Confirm explicitly.** That model reads NBM station guidance, so the exemption must be stated, not inferred. Record it in `reserved-confirmation-window.md` together with the allowlist. |
| OD4 | **Day-session semantics.** Both sides start each UTC day flat, with a `day_open` attestation; the guard's paper ledger carries over through the snapshot. Multi-day inventory carry is out of the gate's scope. | **Yes.** It is the engine's one-day-bundle semantics, and it is the only option that never needs D−1. |
| OD5 | **Print source.** The shadow subscribes to the public CLOB websocket market channel (as 88a), with data-api `/trades` as reconciliation only. | **Yes.** It gives exact trade-id matching and identical coverage semantics. |
| OD6 | **O9 transfer, amending the delegation boundary.** Only `--purpose shadow_gate` bundles, sidecar and attestation for allowlisted dates move to the workstation, hash-verified at both ends. No other production data moves. | **Yes, narrowly**, and record it in `DELEGATION_CONTRACT.md`. Until then the gate cannot run (HOLD stands). |
| OD7 | **Date allowlist.** `config/maker_shadow_gate/dates.json`, owner-approved commits only. Calibration 2026-11-14 and 11-15; gated days from 11-16. | **Yes.** Add dates in weekly batches, ahead of time. |
| OD8 | **Provenance strength.** Push-path attestation now. A capture-host signing key would be a new secret and is deferred. | **Accept push-path attestation** for the pilot gate; revisit before any scale-up beyond the first live session. |
| OD9 | **Venue stamps.** A gate-purpose sidecar from 88a raw replies; the signed v0.2 format is unchanged. | **Sidecar.** |
| OD10 | **Thresholds.** The §9.2 floors (B2 2,000 pairs and 25 %; B3 80 %; orphan/overlong 5 %; caps 10 %; contexts 200/20/10/2), episode cap 30 min, clock 2 s / 5 s / −0.5 s, `PRINT_ABSENT` 20 % (O5), `AMBIGUOUS` 2 %. | **Adopt provisionally.** Freeze after the calibration days, by a reviewed change before 11-16; never loosen inside a cohort. |
| OD11 | **Seven-day rule (O6 revised).** ≥ 7 PASS, 0 FAIL, ≤ 14 days, ≥ 5 market days with gated quotes, each required stratum ≥ 29 clusters across ≥ 3 markets with its control killed on ≥ 3 PASS days, ≥ 29 counted B1 fills; otherwise `FILLS_UNPROVEN` goes to the owner. | **Yes.** Expect `FILLS_UNPROVEN` to be the likely first outcome. Decide in advance whether a longer cohort (≤ 21 days) is acceptable for fills. |
| OD12 | **Timeline (O3).** `GATE_FIRST_UTC_DAY = 2026-11-14`; earliest MET 2026-11-22; S1 merged and the shadow running with providers before 11-14 00:00Z. | **Yes.** S1 targets the 11-10 unit deadline. |
| OD13 | **Live preflight (O7).** The summary hash is a named first-live precondition, and the label "decide() common-mode untested; paper fills" travels with it. | **Yes.** `decide()` itself needs its own evidence (unit and property tests, replay), not this gate. |
| OD14 | O8 (workstation host) and O10 (markouts diagnostic), unchanged from v1 | **Yes.** |
