# Workstation handoff 2026-09-110c — contract additions and policy fixes before the v0.1 tag

Written 2026-09-25 by the production agent from the [maker contract review](audits/maker-contract-review-2026-09-25.md)
(read it first; it cites file:line). **The tag `maker-core-contracts-v0.1` waits for this mission.** All live trading is paused.

## 1. Build

Two commits, one per branch:

**A. `codex/maker-core-phase0-20260925`** (from its current tip `853cba778`):
1. **Contract additions (additive only, defaulted, trailing fields):** `MarketDescriptor.group_relation: str | None = None`
   ("partition" | "nested_ge" | "nested_le"; validate the value); `InfoEvent.active_until_utc: datetime | None = None` (UTC,
   ≥ the event's reference time); `Unavailable.kind: str = "missing_input"` (missing_input | out_of_scope | corrupt | decided);
   `SettlementFact.resolved_value: str | None = None`; relax `OutcomeView` to allow `stdev == 0` iff `p_yes in (0.0, 1.0)`.
   Update `docs/operations/maker-core-contracts.md` (field meanings; the rule that the core never passes extra keyword
   arguments to v0.1 Protocol methods; "runtime passes every loaded secret to SecretGuard").
2. **`decide()` fixes (policy, not contract):** (a) half-tick mid: after outward snapping, if distance > `d_hi` and one tick
   inward still ≥ `d_lo`, step inward (or cap width at `d_hi − tick/2`); (b) requote: "adverse" only when fair value moved
   (asymmetry change ≥ 1 tick or `|Δp| > max(σ_eff, 1 c)`), otherwise HOLD while legs stay within [1,3] c, honour cooldown;
   (c) `Unavailable` in `informed_v0` → `size_cap = grade_size_caps[0]`; (d) subtract own `existing` legs' size at their
   price before competition scoring; (e) honour `InfoEvent.active_until_utc` in `_event_active`; (f) move weather literals out:
   eligible horizons become a `Profile` field (`informed_v0` default {1, 2}); pulls keyed off `action_hint`, not `kind`;
   (g) `blind_re1`: per-leg replacement and `max_requotes = 5` to match RE-1 (`re1_attended.py:34-35,131-134,582-593`), or,
   if that is out of scope, state "first-minute price parity only" in the contract doc.
3. **Ratchet (test-only):** compare on `module + "."` so package `__init__` modules are checked; `dotenv` only in
   `maker_core.runtime.credentials`; add `http.client`, `ssl`, `websocket`, `websockets`, `aiohttp`, `web3` to the SDK/HTTP set.
4. **SecretGuard:** substring match on a normalised token set (key, secret, passphrase, token, bearer, mnemonic, seed,
   private); unlink the journal file if the opening record fails.

**B. `codex/weather-maker-plugin-20260925`** (merge A in first):
5. Weather clock sets `active_until_utc` (bulletin issue/fetch + 10 min for `model_cycle`; METAR windows per design);
   descriptors set `group_relation = "partition"`; decided outcomes may return `stdev == 0` views instead of `Unavailable`.
6. T+0 adapter records the release's calibration method in `model_id`/`inputs_hash` and returns
   `Unavailable(kind="out_of_scope", reason="market_informed_release")` if it is `market_shrink`; amend the pre-registration
   with a dated clarification scoping the no-market-input claim to T+1/T+2 (freeze rules: clarification, not rewrite).

## 2. Tests (add all nine from the review)

Half-tick mid at max width quotes within 3 c; ±1-tick mid move with unchanged fair value → HOLD; `Unavailable` size ≤ 30;
own legs subtracted from competition; RE-1 full-minute journal replay (attempts 1-12, per-minute HOLD/requote, replacement
prices, end reason) if journals are readable, else skeleton; ratchet catches `import weather` in `maker_core/__init__.py`
and `import dotenv` in `venue/`; NBP row-parser differential against `origin/codex/integrate-2-parser-20260921` fixtures
`tests/fixtures/nbm_target_fix/*.txt`; two old bulletins do not widen today permanently; SecretGuard scrubs `x-api-key`
and `POLY_PASSPHRASE`. Plus contract tests for each new field (defaults preserve v0.1 behaviour).

## 3. Boundaries and deliverables

No venue calls, credentials, `.env`, production data, scheduled tasks or live trading. Push both branches. Report:
`docs/roadmap/agent-report-2026-09-110c-maker-contract-and-policy-fixes.md` (verdict first, each finding's disposition,
tests, both tips). The production agent then lands Phase 0 (if not already) and the fix, and creates the tag.
