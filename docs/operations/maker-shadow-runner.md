# Maker shadow runner (informed-maker Phase 3)

Status: canonical. Owns the public-reads-only shadow runner, its per-minute quotes
tape, the nightly diagnostic scoring against 88a capture, the evidence embargo it
enforces and its commands. Read when running, reviewing or extending the shadow,
or reading its tapes and reports. This document grants no run or trading
authority: [the state of play](STATE_OF_PLAY.md) does. Plan context:
[informed maker design](informed-maker-design-2026-09-25.md) Phase 3. Guard
contract: [maker trading guard](maker-trading-guard.md).

## What it is

Every minute the runner reads public International Polymarket data, runs the
`maker_core` policy (`informed-v0` by default) on each selected band, and writes
what it **would** quote. It never places, cancels or signs anything:

- **Public reads only.** `maker_core.venue.public_feed` has exactly three GET
  reads: CLOB `/book?token_id=`, CLOB `/rewards/markets/<condition>` and Gamma
  `/events?slug=`. Any other host, path, query, port, user-info, scheme or
  redirect is refused, so Polymarket US hosts and every order, auth or account
  route are unreachable. No proxy, no credential, no `.env`, no SDK.
- **No order client exists.** The runner (`maker_core.shadow.runner`) imports no
  venue module; reads, the wallet book, fair value and the clock are injected.
  Tests assert the CLI import closure loads no order, credential, SDK or wallet
  module, and that the shadow sources name no order call.
- **Every would-quote leg goes through the #180 guard.** The runner owns one
  `OrderGate`. Each minute starts with `gate.check(wallet book)`; each leg of a
  `QUOTE` asks `gate.authorize(...)` for a permit and is "placed" only through
  `GatedPlacement(gate, ShadowSink)`. `ShadowSink` appends to a local list.
  A PAUSE or HALT latches (owner-cleared, as for a live runtime) and its
  cancel-all intent withdraws every hypothetical leg. A band whose second leg is
  refused is withdrawn whole. The shadow runtime passes
  `check_guard_conformance`.
- **Shadow state is hypothetical.** Caps are explicit config values, never wallet
  balances. There is no inventory: fills are simulated only by the nightly scorer.
- **Fair value.** The weather maker plugin is not on master, so the weather
  composition passes `Unavailable("weather_fair_value_provider_not_integrated")`:
  `informed-v0` then quotes the blind width with grade-`none` size caps. The
  provider is injected, so the plugin replaces it without runner changes.

With today's shared wallet the guard HALTs (ledger INCOMPLETE), so every
would-quote is recorded as refused while the policy decisions are still taped.

## Commands

Workstation, from the repository root. Nothing registers a scheduled task; the
owner (or production) decides where and when it runs.

```powershell
# No-network fixture run (deterministic, simulated clock):
.\venv\Scripts\python.exe -m weather.market.maker_shadow run --config <config.json> --offline-fixture <fixture.json> --minutes 3 --output-root <dir>
# Public shadow (owner-started; Ctrl+C or the stop file ends it with a sealed tape):
.\venv\Scripts\python.exe -m weather.market.maker_shadow run --config <config.json> --stop-file <path>
# Nightly diagnostics of a closed, non-embargoed UTC day:
.\venv\Scripts\python.exe -m weather.market.maker_shadow score --day 2026-11-20 --maker-evidence-root <88a root>
```

Exit 0 is success; exit 2 is a refusal printed as JSON (invalid config, stop file
present at start, embargoed or open day, no sealed tape). Initialise the guard
latch first with `python -m maker_core.runtime.guard_latch init --state-dir <dir>`;
an uninitialised latch is a HALT.

Config (`weather.maker_shadow_config.v0.1`, unknown fields refused):

| Field | Meaning |
| --- | --- |
| `profile` | `informed-v0` or `blind_re1` |
| `hazard_per_minute`, `adverse_markout` | Conservative fill bound (required) and settlement loss floor (default and minimum 0.0043) |
| `caps` | `cash`, `band_cap`, `order_cap`, `wallet_cap`, `event_cap` (hypothetical, required) |
| `markets`, `horizons`, `max_conditions`, `rediscover_minutes` | Registry ids (default all), local horizons (default `[1, 2]`), selection cap (default 24, max 60), rediscovery period (default 15 min) |
| `guard` | `policy` (a `maker_guard` policy), `campaigns`, `wallet_book` (portfolio ledger book JSON, re-read every minute), `latch_dir`, `pause_file` |

The offline fixture (`weather.maker_shadow_fixture.v0.1`) holds `clock_start_utc`
and `replies`, a map from allowlisted URL to the recorded JSON reply.

## Selection and inputs

Discovery reads the Gamma events of each market's **local** T+h dates (rediscovered
every `rediscover_minutes` and at each UTC day change), keeps open, order-book,
currently rewarded bands with an exact YES/NO mapping, and selects at most
`max_conditions`, nearest-to-even Gamma mid first (selection only; no market
price ever enters fair value). Each minute, per band in condition order: both
token books, then the CLOB reward record. The book `as_of` is the local receipt
time of the later read (the venue timestamps are kept beside it); tick and
minimum size come from that book. Levels are sorted and capped at 25 per side
before the policy sees them. Terms sum the reward rates active on the UTC day;
no active rate is `TERMS_MISSING_STALE_OR_FUTURE`. An unreadable input is recorded
as `unevaluated` and withdraws that band's hypothetical legs.

## Tape

Runtime data under `data/maker_shadow/tapes/` (never committed), one file per UTC
day and run: `<day>-<run>.tape.jsonl`, a `maker_core.evidence.journal` chain
(sequence, previous-line SHA-256, fsync per record, create-only), schema
`maker_core.shadow_tape.v0.1` in the opening scope. Records:

| Event | Content |
| --- | --- |
| `opened` | Scope: mode (`public_shadow` / `offline_fixture`), profile, config and guard-policy digests, caps, fill bound, fair-value source, UTC day, run id |
| `universe` / `universe_error` | Selected conditions, candidates, cap drops, refusal counts, missing events |
| `minute` | `minute_utc`; minute guard decision; wallet-book digest; per condition: identity, `outcomes` (YES/NO asset ids), exact policy `inputs`, `decision`, per-leg `gate` outcome (`ALLOW`/`PAUSE`/`HALT`/`REFUSED_AT_REDEEM`, `placed`), venue timestamps; `cancel_all` intents; `resting_after` |
| `terminal` | End reason and minute count |

`inputs` is an exact projection: `maker_core.shadow.tape.inputs_from` rebuilds the
same `DecisionInputs`, whose digest equals the recorded `input_hash` (the token
mapping is stored as `outcomes` because the journal guard strips `token` keys).
At a day roll or exit the runner writes `terminal`, then a create-only
`<day>-<run>.seal.json` (`maker_core.shadow_tape_seal.v0.1`: whole-file SHA-256,
bytes, records, final line hash). A tape without a seal (crash) is listed by the
scorer and never read. The dotted schema names follow the journal's
`maker_core.journal.v0.1` convention and are not schema-registry entries.

## Nightly scoring against 88a

`score` reads the day's sealed tapes (verified against their seals) and the day's
**sealed** 88a segments (`maker_evidence_v2`, [capture contract](passive-maker-evidence-capture.md))
through the existing writer's format: book journals referenced from `books` /
`ranking_books` rows and `last_trade_price` prints in `trades`, each file checked
against its manifest size and SHA-256; unsealed segments are skipped and listed;
duplicate prints count once. 88a code is consumed, never changed. Output is a new
create-only report (`maker_core.shadow_score.v0.1`, default
`data/maker_shadow/scores/<day>-<hash>.json`) labelled `DIAGNOSTIC_NOT_A_VERDICT`:

- **Agreement:** every recorded decision is re-run from its recorded inputs;
  `PASS` only when every decision and input hash match byte for byte.
- **Strata:** `policy` (legs the policy wanted resting: `QUOTE` and `HOLD`) and
  `gated` (legs actually resting after the guard, from `resting_after`).
- **Fills**, in the desk-study rule names: `strictly_through` (print strictly
  below the bid) and `at_price` (at or below), on the leg's own asset, filling
  `min(print size, remaining)` with the leg re-placed at full size each minute
  (60 s life). Spread captured against the 88a mid at the fill; net and adverse
  markouts at +1/+5/+30 minutes against the last two-sided 88a mid at or before
  the mark within 120 s (missing marks are counted, not zeroed).
- **Modelled reward** at `k_share` 1.0/0.5/0.3 from the decision's share and the
  recorded rate. Not paid reward. Legs on bands 88a did not select are counted
  as `legs_not_in_panel`, never scored.

No settlement mark, rebate, hurdle, bootstrap or verdict is computed: economic
scoring belongs to a pre-registered look (maker replay v2, the maker P&L desk
study), not to this diagnostic.

**Embargo.** `score` refuses, before opening any tape or 88a byte, UTC days
2026-09-30..2026-10-15 (maker replay v2 panel and settlement day) and
2026-10-15..2026-11-13 (desk-study decision panel and its pre-registered
extension), and any day not yet closed in UTC. The windows live in
`weather.market.maker_shadow_panel.EMBARGOED_UTC_DAYS`; lifting one is a reviewed
code change. The runner still tapes those days.

## Not yet

Live public-read verification (fixtures only so far: Gamma field names
`orderPriceMinTickSize`/`orderMinSize`/`clobRewards` and the `/book` shape follow
88a and public API usage), the weather fair-value plugin and information clock,
simulated fills inside the live loop, settlement-horizon scoring, the
closed-bundle replay engine comparison, the six drills of the Phase 3 design, a
launcher with resource ceilings, and any scheduled task. Open PR #115 holds an
earlier, larger shadow implementation stacked on the unmerged replay harness.

## Update when

Update with the commands, config or fixture schema, endpoint allowlist, tape or
score format, guard integration, fill or markout rules, or the embargo windows.
