# Informed, domain-neutral market maker — design and build plan (2026-09-25)

- **Owns:** the architecture, plugin contract, quoting and adjustment rules, reuse map, evaluation harness and phased build plan
  for the informed maker the owner commissioned on 2026-09-25 (DECISION_LOG).
- **Read when:** building or reviewing any maker code, a domain plugin (weather, YouTube), or the replay harness.
- **Do not use for:** current state ([STATE_OF_PLAY](STATE_OF_PLAY.md)); measured results (digest, EF); maker history
  ([item 330](../roadmap/items/item-330-maker-economics-refocus-master-plan.md)).

Source: Fable read-only design subagent, 2026-09-25; the production agent verified its code citations (reward kernels at
`src/weather/market/reward_share_estimate.py:134-265`, the import ratchet at `tests/operations/test_import_architecture.py:1109`,
`Re1Heartbeat`/`OwnerVenue`/`build_client` on `origin/codex/re1-wallet-200-20260923`, `observation_clock` and timing-shadow
branches, `pyproject.toml` `packages.find where = ["src"]`, and the T+0-only capture at
`src/weather/collection/snapshot_tracker.py:147-148`). Owner decisions are listed at the end; nothing here is authority until
the owner decides them.

## Direction

1. One domain-neutral maker core, new top-level package `src/maker_core/` (contracts, quoting kernel, portfolio ledger, venue
   port, runtime safety, evidence journal, replay harness), with **zero `weather.*` imports**, enforced by a ratchet.
2. Weather is the first plugin (`src/weather/market/maker_plugin/`) implementing `MarketUniverse`, `FairValueProvider`,
   `InformationClock`, `SettlementResolver` (optional `ExposureModel`). YouTube implements the same four in its own repo
   against a pinned `maker_core.contracts` tag.
3. "Informed" v0: fair value + uncertainty set **width, side asymmetry, size and veto**; the **centre stays the
   size-qualified market mid** until a pre-registered replay shows a centre skew wins (EF §1b: skewing to the model loses).
4. "When to adjust" = typed events from the plugin (scheduled, detected, decidedness) plus core triggers (book, fills, reward
   terms, freshness). RE-1's constants become the frozen `blind_re1` profile and the baseline.
5. T+1/T+2 fair value (the bands the maker quotes; the served model does not cover them) = zero-parameter NBM percentile read
   plus PIT lead-1 `forecast_high`, with an honest validity horizon.
6. Nothing goes live before an offline replay on 88a evidence beats `blind_re1` and no-quote under conservative fills, then a
   live-forward shadow agrees with replay. The owner judges; no pooled gate.
7. Build and test on the workstation; production only captures (88a) and exports bounded, hashed evidence; any live run is
   owner-started on the workstation.

## Architecture

```
 plugins (domain)                src/maker_core/   (no weather.* imports; ratchet)
 weather.market.maker_plugin --> contracts/  MarketDescriptor, OutcomeView, InfoEvent, SettlementFact, Protocols, conformance
 youtube_maker_plugin (own repo) quoting/    rewards (Q kernels), prices (tick/touch), policy decide() (pure), triggers
   provide descriptors,          portfolio/  ledger (one wallet), reservation, limits, exposure
   probabilities, events,        venue/      Polymarket port: public reads, account reads, stream, heartbeat, submit_once, cancel
   settlement -- never orders    runtime/    capabilities (read/cancel/submit), watchdogs, session state machine, cleanup
                                 evidence/   hash-chained journal, verdict replay
                                 replay/     event-sourced harness over captured evidence
 inputs: 88a maker_evidence (books, terms, trades), plugin captured inputs, settlement ledgers
 outputs: quotes tape / journal, replay reports, verdicts; wallet reader = read-only account view
```

Boundaries: plugins import `maker_core.contracts` only; `maker_core.venue` is the sole SDK/HTTP mutation owner; `quoting` and
`portfolio` import neither venue nor SDK; `maker_core` never imports `weather`. Per tick: books/terms + `OutcomeView` +
`InfoEvent`s + portfolio → `decide()` → `QuoteDecision` (reason codes, input hashes) → runtime under capabilities → journal.
The same `decide()` runs in replay and live (the maker's train/serve parity).

Ratchet (Phase 0, beside `test_package_dependency_edges_follow_documented_ratchet`): (a) no `weather` import under
`src/maker_core/**`; no `polymarket`/`eth_account`/`dotenv` outside `maker_core/venue/`; no credential read outside
`maker_core/runtime/credentials.py`; (b) `src/weather/market/maker_plugin/**` imports only `maker_core.contracts`; (c) a
fictional-domain fixture plugin passes the conformance kit and drives a full replay without core edits; (d) edges documented
in `docs/operations/package-boundaries.md` in the same change.

## Plugin contract (v0.1, frozen by tag; additive changes only)

```python
@dataclass(frozen=True)
class MarketDescriptor:
    domain_id: str; event_id: str; condition_id: str
    outcome_tokens: Mapping[str, str]          # {"YES": token_id, "NO": token_id}
    tick: Decimal; min_order_size: Decimal
    neg_risk_group: str | None                 # mutually exclusive siblings (weather bands of one event)
    close_at_utc: datetime; settle_at_utc: datetime | None
    native_unit: str | None                    # informational only
    plugin_version: str; source_hashes: Mapping[str, str]

class MarketUniverse(Protocol):
    def discover(self, as_of_utc: datetime, horizon_days: int) -> UniverseSnapshot: ...
    def describe(self, condition_id: str, as_of_utc: datetime) -> MarketDescriptor: ...
    # Reward terms are not here: the core reads CLOB /rewards/markets (authoritative; terms change intraday, EF §10m).

@dataclass(frozen=True)
class OutcomeView:
    condition_id: str
    p_yes: float; stdev: float                 # stdev > 0, probability units
    joint: Mapping[str, float] | None          # optional distribution over siblings (sums to 1)
    as_of_utc: datetime; valid_until_utc: datetime
    inputs_hash: str; model_id: str
    calibration_grade: str                     # "none" | "shadow" | "scored"; the core caps trust by grade

class FairValueProvider(Protocol):
    def evaluate(self, market: MarketDescriptor, as_of_utc: datetime) -> OutcomeView | Unavailable:
        """Point-in-time inputs only, never market prices. Unavailable is not p=0.5."""

@dataclass(frozen=True)
class InfoEvent:
    kind: str                                  # scheduled_print, model_cycle, new_high, decided, upload, count_update
    scheduled_at_utc: datetime | None; observed_at_utc: datetime | None; detected_at_utc: datetime | None
    affects: tuple[str, ...]; severity: float  # 0..1 expected |move| relative to max spread
    decided: Mapping[str, float] | None        # P(outcome already determined)
    action_hint: str                           # pull | widen | recentre | observe (core may override)

class InformationClock(Protocol):
    def upcoming(self, markets, from_utc, to_utc) -> tuple[InfoEvent, ...]: ...
    def observe(self, markets, as_of_utc) -> tuple[InfoEvent, ...]:  # replayable from captured inputs

class SettlementResolver(Protocol):
    def resolve(self, market: MarketDescriptor, as_of_utc: datetime) -> SettlementFact | Pending: ...

class ExposureModel(Protocol):                 # optional; default independent
    def factors(self, market: MarketDescriptor) -> Mapping[str, float]: ...
```

Weather: universe from `market_registry` + event slugs for local T+0..T+2 (as 88a's `build_universe`); fair value as below;
clock from the observation clock (station routine minutes, `decided`), NBM 01/07/13/19Z with observed fetch time, NWP +210 min,
detected new highs; settlement from the settlement ledgers with reconciliation status (WRH caveat, EF §10c). YouTube (its
repo): universe = view-count threshold markets; fair value = P(views ≥ threshold by deadline) with backtest stdev; clock =
upload time (scheduled) and count polls (detected), `decided` once the count passes the threshold; settlement = the count the
venue rules name.

## Quoting policy `informed_v0` (pure function, testable offline)

1. **No quote** if: book one-sided/crossed or older than 10 s at submit; no size-qualified mid; terms missing or older than 60
   min; mid outside [0.20, 0.80]; an active `pull` event; `decided ≥ 0.5`; safety budgets breached; a foreign open order or
   unknown position.
2. **Centre** = size-qualified mid `m` (fair value never moves the centre in v0).
3. **Width** `d = clip(max(d0, z·σ_eff·100, w_info), d_lo, min(d_hi, v − tick))`, `σ_eff² = σ² + σ_stale²(age)`, `z = 1`,
   `d0 = 1.5 c`, `[d_lo, d_hi] = [1, 3] c`; Unavailable fair value → blind width `d0`.
4. **Asymmetry**: `skew = p − m`; `d_yes = d − λ·skew·100`, `d_no = d + λ·skew·100`, `λ = 0.5`, clipped; a leg beyond `d_hi`
   is not posted (protect the adverse leg, not the centre).
5. **Size**: largest of {20, 30, 50, 75} with `s ≥ s_min`, legs fit cash, and no quote where displayed depth within `v` is
   < max(75, s) on either side (empty bands only buy fill exposure, EF §10m).
6. **Net screen** per minute: `reward = rate/1440 · share_many(Q_min own, competing)` minus `fill_cost = hazard · adverse
   markout · size`; quote only if positive; until measured on T+1/T+2, use the public-tape −0.43 c/share settlement markout and
   an 88a-trade hazard as upper bounds.
7. **Cash and caps**: each band's legs within cash (venue rule, EF §10n); **no cross-market over-commitment** until Q-13 is
   measured; per-event, per-exposure-factor and wallet caps; maker fee 0, taker exit `0.05·p(1−p)`/share (EF §10o) → hold or
   resting reward-eligible sell unless the model move exceeds fee plus expected adverse move.
8. **Band choice**: local T+1/T+2; `|p − m| ≤ σ`; low `decided`; mid near 0.5; competition share 0.15-0.70.

`blind_re1` (d0 1.5 c, [1,3] c requote, one band, first fill ends) must reproduce the recorded RE-1 journals (parity test).

## When to adjust

| Trigger | Core rule | Measured? |
| --- | --- | --- |
| Fair-value move | requote when `|Δp| > max(σ_eff, 1 c)` or a leg's asymmetry moves ≥ 1 tick; 60 s cooldown | T+1/T+2 move distribution unmeasured |
| Scheduled prints (station-minute METAR, NBM cycles, NWP +210 min) | pull −3/+10 min around METAR; widen around model cycles; re-enter on fresh book + fair value | station minutes measured (89b); NBM lag unmeasured |
| Detected new high / decided band | pull on `new_high`; permanent no-quote at `decided ≥ 0.5` | detectors exist; latency unmeasured (89a panel B) |
| Book | requote outside [1,3] c of qualified mid; pull if share falls below 0.05; re-price near touch | measured (92a, 86c) |
| Fills / inventory | cancel the sibling leg on any fill; re-evaluate with inventory skew | 5 fills recorded |
| Reward terms | re-read CLOB terms every minute; cancel if `s_min` rises above size; re-evaluate on rate/spread change | measured 09-25 (100 → 20) |
| Time to resolution | re-describe at local midnight; never quote in the last 3 h | known |
| Safety | heartbeat 8 s, main loop 20 s, stream 30 s, geoblock 45 s, snapshot 300 s → pull/cleanup | RE-1 proven |
| YouTube | upload = scheduled widen; count update = detected event | plugin-owned |

## Reuse map

| Component | Source | Disposition |
| --- | --- | --- |
| Venue wrapper, single checked post, fresh-ask after signing, reads | RE-1 `re1_transport.py` | lift → `maker_core/venue/` |
| Heartbeat + watchdog, freshness budgets, bounded retry | RE-1 `re1_transport.py`, `re1_resilience.py` | lift |
| Cancel / cleanup / reconcile (lost ack never re-posts) | RE-1 `re1_attended.py` | lift, generalised to N orders |
| Hash-chained journal, secret guard | `mm_stage2_hold.py` HoldJournal, RE-1 | lift → `maker_core/evidence/` |
| Session caps, sizes, reserve | RE-1 `re1_sizing.py` | frozen profile `blind_re1` |
| Reward kernels | `reward_share_estimate.py:134-330` | lift **by copy behind a facade** (88a imports it on production; editing it rolls the evidence worker) |
| Quote proposer | RE-1 `reward_quote.py` | lift; policy rewritten as a state machine |
| Selection | RE-1 `mm_stage2_selection.py` | rewrite as `policy.rank()`; date logic to the plugin |
| Session controller | RE-1 `Session` | rewrite as `runtime/session.py`; RE-1 as a parity profile |
| Stage 2 hold build | `88aa7e43a` | do not migrate; freeze as fixtures |
| 88a capture | master | keep on production; harness reads its segments |
| Wallet reader | `codex/wallet-public-reader-20260925` | lift as `venue/account_read.py`; bleed rule → portfolio limit |
| Markout + clustered inference | `execution_tape_markout.py` | reuse in `replay/score.py` |
| Fill simulation | 89a `fill_toxicity_model.simulate` | lift as the harness fill model |
| Observation clock, info calendar | `observation-clock` branch, `info_event_calendar.py` | weather plugin (fixed :52 replaced by station minutes) |
| Paper worker (`mm_policy`, `market_making_run*`) | master, paused | retire; keep `mm_risk` region groups as the weather `ExposureModel` |
| Served T+0 probabilities | captured snapshot rows | weather plugin reads captured output, never recomputes |

## Evaluation harness (`maker_core/replay/`)

Inputs (captured, hashed): 88a segments (per-minute both-token books, reward records on change, public trades), plugin
captured inputs (retained NBM bulletins with `provider_update_time`, served T+0 snapshot rows, observation triggers),
settlement ledgers; production exports a bounded, hashed bundle per closed UTC day. Event-sourced by capture time; providers
see only inputs captured at or before `t`. Fill model: 89a Clarifications 2/3 (strictly-through primary, at-price
sensitivity). Scores per policy per band-day: reward accrual (k = 1.0, 0.5 sensitivity), nominal rebate, markouts 1/5/30 min
and settlement, held-inventory settlement P&L, cash-hours, pulled-minute fraction, requotes, fills in vs out of event windows.
Baselines: no-quote, `blind_re1`, clock-only pull at matched pulled fraction. Inference: date and date×market bootstrap, 90%
intervals, `UNDERPOWERED` below 10 clusters, pre-registration before the first scored read. Parity: a replay of a live day
reproduces its decisions byte for byte.

Evidence proposed for the owner before live: ≥ 14 closed 88a dates, ≥ 10 clusters, `informed_v0` net beats `blind_re1` and
no-quote with the lower bound above both under conservative fills; pulls remove ≥ 2x the large moves per pulled minute of the
clock-only baseline; a T+1 fair-value reliability table; ≥ 7 days of live-forward shadow agreeing with replay; drills (kill
switch, stale feed, cancel-all, restart, terms change, lost ack); the item 330 accounting identity with the wallet reader as
cash source.

## Weather fair value (Phase 1)

- **T+1/T+2**: newest retained NBP bulletin at or before `t` whose TXN row holds `D`'s maximum (parser v2 slot rule; right at
  every cycle for tomorrow, EF §10k; T+2 presence unverified). Piecewise-linear CDF through p10/p25/p50/p75/p90, linear tails,
  integrated over each band, renormalised across the event; declared zero-parameter stdev; `valid_until` = next cycle
  availability, never more than 24 h after issue. Fallback: PIT lead-1 `forecast_high` with a fixed climatological spread
  named in the pre-registration. No market price enters. `calibration_grade = "none"`.
- **T+0**: the latest captured served band probability (release-bound), valid 15 min; carries the live afternoon centering
  stage whatever its fate (the plugin exposes the stage id).
- Not a model-panel candidate and not an edge claim; scored only on 88a T+1/T+2 mids and settlements under its own
  pre-registration.

## Phased plan

| Phase | Deliverables | Host | Effort |
| --- | --- | --- | --- |
| 0 Foundation | `src/maker_core/` contracts v0.1 (tagged), conformance kit, fictional-domain plugin, ratchet + `package-boundaries.md`, reward/price kernels copied with differential tests, `blind_re1` profile reproducing RE-1 journals, journal/secret-guard lift | workstation (new files, expected roll-free) | 4-6 days |
| 1 Weather plugin | `maker_plugin/{universe,fair_value,clock,settlement,exposure}.py`, T+1/T+2 provider, T+0 adapter, station-minute clock, fair-value pre-registration | workstation; production bounded export under the lease | 5-8 days |
| 2 Replay harness | loader for 88a v2 segments, fill model, scorer, baselines, clustered inference, report | workstation (`workstation_heavy.ps1`) | 5-8 days |
| 3 Paper/shadow | public-reads-only shadow runner writing a quotes tape per minute; nightly scoring vs 88a; drills | workstation | 3-4 days build, 7-14 days elapsed |
| 4 Owner-started live (RE-2) | attended sessions on the `maker_core` runtime with `informed_v0`, pre-registered sizes/caps/dates | workstation, owner starts each session | per session |

YouTube hand-off from Phase 0: the contracts tag, the fictional plugin as template, the conformance test and the replay input
format. Contract rules for them: point-in-time inputs only, `Unavailable` rather than a guess, and `valid_until`.

## Owner decisions

1. Package location `src/maker_core/` (recommended; importable by the YouTube repo) vs `src/weather/market/maker/`.
2. Initial caps (band, event, exposure factor, wallet) and the held-inventory rule.
3. Centre rule for v0: market mid; fair value only for width, asymmetry, veto and size.
4. The T+1/T+2 fair-value pre-registration and its scoring date.
5. "Good enough" hurdles: net per band-day vs `blind_re1`, pull efficiency, shadow-vs-replay tolerance.
6. Shadow runner host (workstation recommended); whether production ever hosts a quoting process.
7. Stage 2 hold build and the four 80b relaxations: freeze as fixtures, do not migrate.
8. RE-1 sessions 12-30: paused by the owner on 2026-09-25 (decided).
9. Formally retire the paused paper maker.
10. Publish contracts v0.1 now; additive-only changes after.

## Risks and not yet

Fair value must never consume the market mid (conformance test checks it); replay optimism (queue position, invisible
cancels, 60 s books: keep both fill bounds); simultaneous fills beyond cash (Q-13, no over-commitment); editing
`reward_share_estimate.py` rolls 88a (copy behind a facade); 88a disk brakes leave holes (gaps are exclusions, not zeros);
T+1 guidance is 5-24 h stale after 12Z by construction; 11-12 market clusters cap per-market power (~40%). Not yet:
unattended quoting, negRisk baskets, cross-market over-commitment, a fitted T+1 model, centre skew, a YouTube plugin in this
repo, a second wallet ledger or heartbeat owner, paper reward P&L, production-hosted quoting.

## Unverified

95a/94a build state; T+2 presence in every NBP cycle; availability of RE-1 attempt journals on the workstation for the parity
test; path-policy test reaction to a second top-level package; the exact served T+0 probability field in snapshot rows; any
YouTube model interface details (none exist in this repository).
