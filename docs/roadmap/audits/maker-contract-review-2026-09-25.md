# Maker contract and plugin review — 2026-09-25

- **Owns:** the pre-freeze review of `maker_core` contracts v0.1, `decide()`, the weather plugin and the ratchet, with dispositions.
- **Read when:** changing the maker contracts, the quoting policy or the weather plugin.
- **Do not use for:** the design ([informed maker design](../../operations/informed-maker-design-2026-09-25.md)).

Reviewer: Fable read-only subagent, on `codex/maker-core-phase0-20260925` @ `853cba778` (P0) and
`codex/weather-maker-plugin-20260925` @ `a4900d2e0` (P1). The production agent verified the `Unavailable` size-cap inversion
(P0 `policy.py:253-261`: `size_cap = 75` unless a view exists) and the ratchet prefix hole (`test_import_architecture.py:1142-1155`
matches `startswith("maker_core.")`, so package `__init__` modules are unchecked).

## Verdict

The contract needs no breaking change for weather or YouTube; every gap closes additively. Add the cheap additive fields
**before** tagging to avoid an immediate v0.1.1. `quoting/policy.py` is not contract and has three HIGH money-relevant defects
to fix before Phase 2 replay. Disposition: handoff **110c** does both; the tag `maker-core-contracts-v0.1` waits for 110c.

## Findings (condensed)

| Sev | Area | Finding | Fix (110c) |
| --- | --- | --- | --- |
| HIGH | decide() | Half-tick mid + width in (2.5, 3] c snaps outward past `d_hi` → silent NO_QUOTE (`OUTSIDE_REQUOTE_WINDOW`), exactly during max-width windows (P0 `policy.py:251,265,295,323`) | step the leg one tick inward when snapped distance > `d_hi` and ≥ `d_lo` remains, or cap width at `d_hi − tick/2` on half-tick mids |
| HIGH | decide() | Informed profile cancels both legs on every 1-tick mid move; the [1,3] c hold window and cooldown never apply (P0 `policy.py:356-362`) | "adverse" = fair-value driven only; otherwise HOLD while legs stay within [1,3] c |
| HIGH | decide() | `Unavailable` fair value gets size cap 75 while an unscored view gets 30 (P0 `policy.py:253-261`; test asserts it) | `size_cap = grade_size_caps[0]` (or lower) when `view is None` in `informed_v0` |
| MED | decide() | Own resting orders counted as competition on the HOLD path (P0 `policy.py:270-275,344`) | subtract `existing` legs' size at their price before scoring |
| MED | core | Weather literals in the neutral core (`HORIZON_NOT_T1_T2`, `kind == "new_high"`) | eligible horizons as a `Profile` field; pulls keyed off `action_hint` |
| MED | contract/plugin | Detected events never expire: every historical bulletin is a live `model_cycle` widen → permanent max width; YouTube count polls would pull forever | add `InfoEvent.active_until_utc`; honour it; weather clock sets issue + 10 min |
| MED | contract | Nested threshold ladders (YouTube "≥ N views") cannot declare coherence; non-binary outcomes not expressible | add `MarketDescriptor.group_relation` ("partition" / "nested_ge" / "nested_le") |
| MED | contract | `stdev > 0` forces decided outcomes (p ∈ {0,1}) into `Unavailable` | allow `stdev == 0` iff `p_yes ∈ {0,1}`; add `Unavailable.kind` |
| MED | ratchet | Package `__init__` modules unchecked; `dotenv` allowed in `venue`; HTTP list misses `http.client`, `ssl`, `websocket(s)`, `aiohttp`, `web3` | compare on `module + "."`; `dotenv` only in the credentials owner; extend the list |
| MED | journal | `SecretGuard` key scrub is exact-match (`x-api-key`, `POLY_PASSPHRASE` pass) | substring token match; document "runtime passes every loaded secret" |
| MED | parity | `blind_re1` diverges from RE-1 on requote (RE-1 replaces only the drifted leg, caps 5 requotes); parity proven for first-minute prices only | per-leg replacement + `max_requotes`, or document first-minute price parity only; add a full-minute journal replay test |
| MED | contamination | Served T+0 adapter cannot tell a `market_shrink` release (today's deployed method is `identity`) | record the release's calibration method; `Unavailable("market_informed_release")` if `market_shrink`; scope the pre-registration's no-market claim to T+1/T+2 |
| LOW | various | conformance price-perturbation hook; `SettlementFact` recorded time; synthetic close time (88a drops `endDate`); unhashable events; journal leaves an empty file on open failure | additive later |

## Sound, leave alone

Contract validation; `outward` rounding; qualified-mid and touch buffer; band integration `[lo−0.5, hi+0.5]` with open tails
(matches `bin_probability`); partition/gap fail-closed; renormalisation; `valid_until` next-cycle rule; v2 slot selector
(byte-identical); NBP refusals; lead-1-only PIT fallback; T+0 15-min expiry and release binding; settlement chain checks;
per-band cash; reward terms from inputs; net-screen units; full input hash; journal chain; kernel differential tests.

## Unverified

Explanation sidecar key name; `release_identity_status` value on production rows; real venue `endDate` vs derived close;
`provider_issue_time` population; `min_order_size` semantics in 88a captures; NBP `-99`/3-token rows beyond fixtures; T+2
presence in NBP cycles.
