# 110o part 9 — Polymarket US adapter refuses order mutation (owner decision 9, D2-05) [DONE]

**Verdict: DONE. `PolymarketUSHTTPAdapter` now raises the typed `PolymarketUSOrderMutationRefused` (naming AGENTS.md's
International-only rule) for place, preview, cancel and cancel-all, before any signing or transport call; it reports
`supports_trading: False`, `read_only: True`. Read paths and US request-plan building are unchanged.** Roll verdict:
expected roll-free (D2-05 static trace: `mm_exchange.py` is not in a capture closure); production must confirm.

Branch `codex/110o-us-adapter-refusal-20260929`; handoff
[workstation-handoff-2026-09-110o](workstation-handoff-2026-09-110o-repo-health-owner-decisions.md) part 9; audit row
D2-05 ([D2](audits/repo-health-audit-2026-09-26/dimensions/D2.md)).

## What changed

| File | Roll | Change |
| --- | --- | --- |
| `src/weather/market/mm_exchange.py` | expected roll-free; **confirm with `roll_verdict.ps1`** | `US_ORDER_MUTATION_ACTIONS`, `PolymarketUSOrderMutationRefused(RuntimeError)` with `.action`; the guard sits in `_request`, so every mutation verb and any direct `_request("create_post_only")` refuses. `supports_trading = False`; diagnostics add `order_mutation: refused_international_only`. |
| `tests/market/test_mm_exchange.py` | roll-free | The four US tests that drove mutations through the adapter now test the same latency-stopgap classifiers directly (`classify_polymarket_us_response` / `_exception`, unchanged). New: every mutation verb refuses with the typed error and sends nothing; reads (`open_orders`, `positions`) still send signed GETs; the US order request plan is still buildable. |

`preview_order` is refused too: it is a signed POST to the US venue, and AGENTS.md forbids new US probes.
`supports_trading = False` also makes the existing live gates (`mm_exchange.py` live-mode check, `mm_live_bootstrap`,
`mm_live_lifecycle_probe`, `mm_live_pilot_cli`) refuse this adapter; no source factory builds it (D2-05).

## Verification

`tests/market/test_mm_exchange.py`, `test_mm_live_bootstrap.py`, `test_mm_live_lifecycle_probe.py` plus the repo-wide
audits (`test_agent_docs_audit`, `test_import_architecture`, `test_module_size_audit`, `test_path_policy`,
`test_schema_registry`, `test_structure_inventory`, `tests/app/test_app_architecture`): 131 passed, 4 subtests passed;
`agent_docs_audit` PASS; `roadmap_backlog --check` OK. Fixtures only; `RecordingTransport`, no network.

## What was NOT done

No registration, no production write, no restart, no merge, no venue call. US fixtures, readers and historical evidence
are untouched; the schema registry is untouched.

## Production steps

1. CI green on the exact head; `scripts\ops\roll_verdict.ps1 -Branch codex/110o-us-adapter-refusal-20260929`.
2. Roll-free → roll-free light path when the exam-period merge policy allows; roll-sensitive → 01:00-04:00 via
   `quiet_window_merge.ps1` after 10-13 (it is not exam tooling).
