# Workstation handoff 2026-09-25a — re-specify the maker settlement gate to materiality

## Goal

The maker execution-capture producer is registrable under a settlement-coverage gate that measures
whether the evidence can score P&L honestly, rather than whether a network connection happened to
stay unbroken.

## Why this mission exists

`-09-18a` built the narrowed execution-only producer and it passed every resource limit with wide
margin: 11.34 MiB/day against a 100 MiB budget, 45.91 MiB peak RSS against 64 MiB, 1.79% of one
core, zero `RawTapeWriterBusy`, zero book-writer errors. It returned **NO-GO on one thing**: a remote
WebSocket loss opened a **2.165004-second** coverage gap at 00:08:24 ET, so no single complete bound
receipt spanned the 00:00–00:30 settlement interval, and the harness returned
`settlement_period_not_continuously_covered`.

**Do not re-run that soak hoping for a clean night.** The same soak logged **4 remote connection
losses in 6 h 52 m** — about one per 1.7 hours. Against a half-hour settlement window that implies
roughly a **75% chance of a clean window and 25% chance of failure**, so:

- re-soaking is a coin flip, and
- a PASS obtained that way would certify a producer that still fails about a quarter of settlement
  windows in production, permanently taxing the market-making decision clock.

That is the same lottery shape as the slice gate in
[`RETRACTED_AND_FALSE_LEADS.md`](../operations/RETRACTED_AND_FALSE_LEADS.md), where a frozen bar
falsely rejected a better candidate 99.885–99.9905% of the time. A pass obtained by luck carries no
information.

**The operator decided on 2026-08-06 to re-specify this gate to materiality.** This mission executes
that decision. It is not authorisation to loosen any other gate.

## Start from this, do not re-derive it

Read [`ESTABLISHED_FINDINGS.md`](../operations/ESTABLISHED_FINDINGS.md) and
[`DELEGATION_CONTRACT.md`](../operations/DELEGATION_CONTRACT.md) first. Additionally, measured on the
production host on 2026-08-06 — take these as given:

| Fact | Value |
| --- | --- |
| Maker paper quotes generated | `quote_rows = 116,556` |
| Maker execution evidence | `quote_legs = 0`, `fill_rows = 0`, `clob_recon_book_rows = 0`, `vacuous = true` |
| Fill-evidence gate | `status = BLOCK`, `blockers = ['no_quote_legs']` |
| Recon coverage source | `missing_precomputed_recon_no_active_book_folders` |
| MM live-forward days accumulated | `0`, against `min_edge_allowed_live_days = 14` |

**The market-making decision clock is at zero and cannot advance until this producer is registered.**
It is not blocked by `clob_freshness`, not by the reservation (cleared 2026-08-04, nothing is
reserved), and not by promotion. This gate is the single blocking dependency on the operator's
end goal. That is why it is worth doing carefully rather than quickly.

Two facts already establish that the current bar is a specification accident rather than a
considered choice:

1. **The same harness already uses a tolerance.** It accepts a worst per-event book gap of
   `3.490662 s` against a declared `<= 10 s` bar, while applying zero tolerance to settlement
   coverage. Nobody chose that asymmetry.
2. **The evidence is granular where the verdict is binary.** `-09-18a`: "All gaps and reasons are
   explicit in the 60 bound per-event receipts; they are not silently treated as zero executions."
   The physical gap was **0.1203%** of the half-hour.

## The anti-tuning control — read this before writing code

The failure mode this mission must avoid is obvious and fatal: choosing a threshold that admits the
2.165 s gap because it is the gap we happen to have. That would be relaxing a gate to make it pass,
and it would poison every maker P&L number that follows.

**Therefore the rule and its threshold must be committed and pushed BEFORE any new soak evidence is
generated.** The commit timestamp must precede the soak's earliest receipt timestamp, and both must
appear in the report. This ordering is checkable and it will be checked. A rule authored or amended
after seeing a soak result is void, and the honest thing at that point is to report it as such.

**Derive the threshold from measured market behaviour, not from the observed gap.** The defensible
anchor is trade cadence: a gap is immaterial only if a resting quote could not plausibly have been
filled and cancelled inside it undetected. Measure inter-trade intervals per market from CLOB tape
already on disk, state the statistic and the corpus you used, and derive the bound from it.

**If the cadence-derived threshold lands below 2.165 s, then the `-09-18a` soak stays FAIL and a
fresh soak is required. Report that outcome plainly.** It is a legitimate and useful result. Do not
adjust the derivation to avoid it.

## P0 — specify and commit the rule

A settlement period is **countable** only if all of the following hold:

1. **Bounded** — total gap duration within the period is at or below the cadence-derived threshold,
   and the gap count is at or below a declared maximum.
2. **Provably empty** — for every gap, the bound receipts **positively establish** that no quote was
   resting, no decision was emitted, and no fill occurred inside it. *Absence of observation is not
   proof of absence.* If emptiness cannot be established from the receipts, the period is
   uncountable.
3. **Overlap-excluded** — any decision, quote, or fill whose attribution window overlaps a gap is
   marked **uncountable** and excluded from scoring, rather than silently included.
4. **Carried forward** — the gap inventory is written into the evidence artifact so downstream
   scoring can exclude affected windows without re-deriving them.

Note that this is **stricter than the current gate in every respect except duration**. Today a
passing soak proves only that no reconnect happened that night; it says nothing about the reconnects
that will certainly occur in production. Requirements 2–4 handle them explicitly and permanently.
If your implementation is not strictly stronger on 2–4, you have built the wrong thing.

Commit and push this before P1.

## P1 — re-soak under the committed rule

Run a fresh public soak with its own isolated evidence root, exactly as `-09-18a` did. Do not
reproduce it under the production checkout and do not touch production state. Report GO or NO-GO
under the committed rule, with the gap inventory in full.

## P2 — registration readiness only

State whether `WeatherMakerExecutionCapture` is registrable, and render the exact registration
command. **Do not register it, do not start it, and do not schedule anything.** Registration is a
separate operator decision.

## Boundaries

[`DELEGATION_CONTRACT.md`](../operations/DELEGATION_CONTRACT.md) §2 binds this mission in full. In
addition:

- **Do not relax any other gate.** This decision covers the maker settlement-coverage gate only. In
  particular `clob_freshness`, chain admission, and the promotion gates are out of scope, however
  similar their pathology looks.
- **Do not relax the promotion gate for `harvest_only` rows.** That remains an explicit operator
  decision and is not delegated.
- No production, mirror, or `D:\weather-mirror` writes. Never read
  `C:\Users\micha\.weathersync.cred`.
- Concurrent file owners — do not edit: `model_features.py` (`-09-22a`, `-09-20a`),
  `schema_registry_data.py` (`-09-19a`, `-09-20a`), `forecast_history.py`, `nightly_retrain.py`,
  `daily_refresh.py`, `base_retrain.py`, `live_variant_settlement_scorecard.py`.
- Give the roll verdict from the retained `runtime_identity.source_scope_files` arrays in the four
  capture status files, not from `SOURCE_PATTERNS`. Do not merge.

## What would falsify this mission

State plainly if any of these hold. Each is a useful result and none is a failure of the mission:

1. **The cadence-derived threshold is below 2.165 s** — the materiality re-specification does not
   rescue the `-09-18a` soak, and a fresh soak is required regardless.
2. **Gap emptiness cannot be established from the bound receipts.** If the receipts record that a
   gap occurred but cannot prove nothing happened inside it, then requirement 2 can never be
   satisfied and materiality is not implementable on this evidence. Say so — that redirects the work
   to the receipt format, not the threshold.
3. **Reconnect gaps are not the binding constraint.** If a re-soak fails on something else, the
   premise that continuity specification is what blocks registration is wrong.
4. **Gaps correlate with market activity.** If reconnects cluster where trading is heaviest, then
   "provably empty" will rarely hold and the whole approach is weaker than it looks. Check this;
   do not assume independence.
5. **The producer's steady-state failure rate stays materially above zero** under the new rule. If
   so, quantify it, because it prices the MM clock directly.

## Deliverables

- Branch: `codex/workstation-respecify-the-maker-settlement-gate-2026-09-25a`
- Report: `docs/roadmap/agent-report-2026-08-06-workstation-respecify-the-maker-settlement-gate.md`
- Report structure per [`DELEGATION_CONTRACT.md`](../operations/DELEGATION_CONTRACT.md) §5.
- Push the branch only. No PR, no merge, no force-push, no branch deletion.
