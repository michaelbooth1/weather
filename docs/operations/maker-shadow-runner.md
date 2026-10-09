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

- **Public reads only.** `maker_core.venue.public_feed` has exactly four GET
  reads: CLOB `/book?token_id=`, CLOB `/rewards/markets/<condition>`, Gamma
  `/events?slug=` and data-api `/trades?market=<condition>&limit=500` (public
  prints of one condition; a `user` filter is refused). Any other host, path, query, port, user-info, scheme or
  redirect is refused, so Polymarket US hosts and every order, auth or account
  route are unreachable. No proxy, no credential, no `.env`, no SDK.
- **No order client exists.** The runner (`maker_core.shadow.runner`) imports no
  venue module; reads, the guard book, fair value and the clock are injected.
  Tests assert the CLI import closure loads no order, credential, SDK or wallet
  module, and that the shadow sources name no order call.
- **Every would-quote leg goes through the #180 guard.** The runner owns one
  `OrderGate`. Each minute starts with `gate.check(paper campaign book)`; each leg of a
  `QUOTE` asks `gate.authorize(...)` for a permit and is "placed" only through
  `GatedPlacement(gate, ShadowSink)`. `ShadowSink` appends to a local list.
  A PAUSE or HALT latches (owner-cleared, as for a live runtime) and its
  cancel-all intent withdraws every hypothetical leg. A band whose second leg is
  refused is withdrawn whole. The shadow runtime passes
  `check_guard_conformance`.
- **Shadow campaign book.** In shadow mode the guard evaluates a paper ledger
  (`maker_core.shadow.paper.PaperLedger`), never a wallet book: account
  `shadow-paper`, campaign `shadow-maker` with the declared starting cash and
  bleed limit, maker fee 0. Its only trades are the runner's own simulated fills:
  at each minute, the legs that rested since the last check are filled from the
  condition's public prints under the configured desk-study rule
  (`strictly_through` or `at_price`, `min(print size, remaining)`, legs re-placed
  at full size each minute, identical prints once). The guard book is built by the
  real portfolio ledger from a paper snapshot, so bleed is the ledger's P&L on
  paper: cash plus open lots marked at the last two-sided mid read for the asset
  (`held_mark_max_age_seconds` is taped; a band that left the selection keeps its
  last mark; settlement is not applied). A fill sets `fill_seen` for that band's
  next decision (the sibling leg is cancelled). A print-read failure is a taped
  `print_gaps` entry, never read as "no fills". Bleed past the limit HALTs and
  latches exactly as for a live runtime; only the owner's latch command clears it.
  The paper book belongs to one run (a restart starts a fresh book; the latch
  persists). Quoting caps are separate hypothetical config values.
- **Fair value.** The weather maker plugin is not on master, so the weather
  composition passes `Unavailable("weather_fair_value_provider_not_integrated")`:
  `informed-v0` then quotes the blind width with grade-`none` size caps. The
  provider is injected, so the plugin replaces it without runner changes.

The config refuses a `wallet_book` or `campaigns` entry
(`shadow_mode_refuses_real_wallet_book`) and a guard policy naming any campaign
other than `shadow-maker`, so the shadow can never be pointed at the shared
wallet (which would HALT every minute on its INCOMPLETE ledger).

## Commands

Workstation, from the repository root. On the capture host the forward run is
the `WeatherMakerShadowRunner` task (next section); registering it is an owner act.

```powershell
# No-network fixture run (deterministic, simulated clock):
.\venv\Scripts\python.exe -m weather.market.maker_shadow run --config <config.json> --offline-fixture <fixture.json> --minutes 3 --output-root <dir>
# Public shadow (owner-started; Ctrl+C or the stop file ends it with a sealed tape):
.\venv\Scripts\python.exe -m weather.market.maker_shadow run --config <config.json> --stop-file <path>
# Nightly diagnostics of a closed, non-embargoed UTC day:
.\venv\Scripts\python.exe -m weather.market.maker_shadow score --day 2026-11-20 --maker-evidence-root <88a root>
# Replay-v2 bundle.json over a closed UTC day's sealed record streams (create-only):
.\venv\Scripts\python.exe -m weather.market.maker_shadow bundle-day --day 2026-11-20
```

Exit 0 is success; exit 2 is a refusal printed as JSON (invalid config, stop file
present at start, embargoed or open day, no sealed tape; for `bundle-day` an open day,
an unsealed or changed record stream, or an existing `bundle.json`). Initialise the guard
latch first with `python -m maker_core.runtime.guard_latch init --state-dir <dir>`;
an uninitialised latch is a HALT.

Config (`weather.maker_shadow_config.v0.1`, unknown fields refused):

| Field | Meaning |
| --- | --- |
| `profile` | `informed-v0` or `blind_re1` |
| `hazard_per_minute`, `adverse_markout` | Conservative fill bound (required) and settlement loss floor (default and minimum 0.0043) |
| `caps` | `cash`, `band_cap`, `order_cap`, `wallet_cap`, `event_cap` (hypothetical, required) |
| `markets`, `horizons`, `max_conditions`, `rediscover_minutes` | Registry ids (default all), local horizons (default `[1, 2]`), selection cap (default 24, max 60), rediscovery period (default 15 min) |
| `guard` | `policy` (a `maker_guard` policy with `campaign_id` `shadow-maker`), `latch_dir`, `pause_file`; `wallet_book`/`campaigns` are refused |
| `paper` | `starting_cash_pusd` (> 0), `bleed_limit_pusd` (0..starting cash), `fill_rule` (`strictly_through` or `at_price`) |

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
Legs of a band that leaves the selection are withdrawn. Before the guard check, the
prints of every band with resting legs are read once (paper fills above).

## Tape

Runtime data under `data/maker_shadow/tapes/` (never committed), one file per UTC
day and run: `<day>-<run>.tape.jsonl`, a `maker_core.evidence.journal` chain
(sequence, previous-line SHA-256, fsync per record, create-only), schema
`maker_core.shadow_tape.v0.2` in the opening scope (v0.1 before the record stream). Records:

| Event | Content |
| --- | --- |
| `opened` | Scope: mode (`public_shadow` / `offline_fixture`), profile, config and guard-policy digests, caps, fill bound, fair-value source, UTC day, run id; code identity `git_commit` / `git_dirty` / `git_error` (below) |
| `universe` / `universe_error` | Selected conditions, candidates, cap drops, refusal counts, missing events |
| `minute` | `minute_utc`; minute guard decision; guard-book digest; `paper` (fill rule, this minute's simulated fills, print gaps, paper cash, P&L, status, bleed state, held-mark age); per condition: identity, `outcomes` (YES/NO asset ids), exact policy `inputs`, `decision`, per-leg `gate` outcome (`ALLOW`/`PAUSE`/`HALT`/`REFUSED_AT_REDEEM`, `placed`), venue timestamps; `cancel_all` intents; `resting_after` |
| `terminal` | End reason, minute count and (v0.2) the record stream's seal |

`inputs` is an exact projection: `maker_core.shadow.tape.inputs_from` rebuilds the
same `DecisionInputs`, whose digest equals the recorded `input_hash` (the token
mapping is stored as `outcomes` because the journal guard strips `token` keys).
At a day roll or exit the runner writes `terminal`, then a create-only
`<day>-<run>.seal.json` (`maker_core.shadow_tape_seal.v0.2`: whole-file SHA-256,
bytes, records, final line hash, and `records_stream` binding the stream's SHA-256,
bytes and records). The seal is computed streaming (`tape.seal_digest`, one line in
memory, the `verify_journal` checks). A tape without a seal (crash) is listed by the
scorer and never read. `sealed_tapes` and `score` read v0.1 and v0.2 tapes side by side
and report each tape's `tape_schema`. The dotted schema names follow the journal's
`maker_core.journal.v0.1` convention and are not schema-registry entries.

**Code identity.** `run` computes the checkout's commit once at start
(`weather.market.maker_shadow.code_identity`: `git -C <weather.paths.REPO_ROOT> rev-parse HEAD`
and `git status --porcelain --untracked-files=no`) and records it in the `opened` scope of
every tape of the run: `git_commit` (hex), `git_dirty` (tracked changes present) and
`git_error` (`null`, or `git_unavailable` / `git_failed` / `git_timeout` /
`git_output_invalid` / `git_status_failed`). A git failure never stops the recorder; the tape
then says the code was not bound. Code changes do not apply to a running process, so the
recorded commit is the code the run imported; tapes written before this field read as
`not_recorded`.

### Tape v0.2 record stream

So replay-v2's `stream_source` reads shadow days directly (owner decision 2026-10-08, parity
blocker 1), each run also writes `tapes/records/<day>/<day>-<run>-records.jsonl`: raw
public replies in bundle v0.2 row format (`sequence captured_at condition_id|group_id kind
payload payload_sha256 source_hashes`), fsynced per batch, then a create-only
`-records.seal.json` (`maker_core.shadow_records_seal.v0.1`). `maker_core.shadow.records` owns it:

- `RecordingReads` wraps the public feed and keeps the last raw book, reward and Gamma reply
  with its local receipt time. A trade poll taken before each minute's step is served once to
  the runner's own paper-fill read, so the tape and the paper book see the same prints. The
  shadow's decision inputs are the minute's own reads, unchanged by the recorder.
- **Every record is stamped at its receipt time** (`captured_at`), never at the decision
  instant. `book`: full raw levels of both tokens (before the runner's 25-level cut, plus venue
  scalars), `captured_at = as_of` = receipt of the later of the two reads. `terms`: the reward
  record's receipt, every minute (an `absent` record when the shadow had none, which replays as
  `MISSING_TERMS`). `descriptor` and the allowlisted Gamma market (`plugin_input`, with its own
  `received_at_utc`): at the minute's book receipt, on change. The CLOB reward record
  (`plugin_input`, allowlisted): at its receipt, on change. `outcome_view` and `info_event`
  (on change): at the decision instant, where the shadow computes them. New public prints as
  `trade` and one `coverage` record for the condition's group (`cov-<condition id chars
  3-26>`): at the poll's receipt, valid 60 s from it.
- **Mid-minute refresh** (live mode, minute+30 s, `TapeWriter.poll` ->
  `RawRecorder.between`): per band with a recorded descriptor, one trade poll and both books
  read again, so no recorded book is older than the replay engine's 60 s freshness limit at the
  next decision, even when a minute's reads start late (Gamma rediscovery). Record stream only.
  Cost at 12 bands: 24 extra CLOB book GETs a minute (the 12 trade GETs at +30 s already
  existed), from 60 to 84 public GETs a minute, about +4.6 s of sequential reads at 190 ms
  each. The first minute of a run (or of a newly selected band) replays as
  `MISSING_COVERAGE`: its first poll precedes its first descriptor.
- Trade polls: the first poll of a run is a baseline (nothing emitted); the baseline and the
  seen print keys are per run, so a print just before 00:00 UTC that is first polled after the
  roll lands in the next day's stream. A full page (`TRADES_PAGE` 500) that does not reach the
  previous newest print, an unreadable print, or a print more than 5 s after its poll's receipt
  sets that poll's `trade_stream_ok` false. Deduplicated on the paper-fill print key, with no
  wallet or profile fields.
- Gamma and reward provenance is allowlisted (`records.GAMMA_MARKET_KEYS`,
  `REWARD_KEYS`, `REWARD_CONFIG_KEYS`); any other key or an address-like value
  (`0x` + 40 hex, for example `submitted_by`) is dropped and counted in `dropped_keys`.
- A new day's stream re-states each known band's last descriptor at its first record, so the
  day's coverage group is described from the first poll.
- Sequences continue across runs of a day (the next run starts after every sealed and
  unsealed stream's last sequence). A record behind the stream clock, outside the day,
  over 1 MiB or a coverage group before its member's first descriptor is dropped and
  counted in the minute's `raw.dropped` and the stream seal.
- **Fault boundary.** A recorder or file fault never stops the runner. `TapeWriter` codes
  it (`minute:<Error>`, `between:<Error>`, `write:<Error>`), counts it in the stream seal's
  `faults` and writes not-OK coverage for every described band from that instant; the
  minute's `raw` block carries the code. A failed write or fsync marks the stream broken:
  later writes are skipped, and the seal records the bytes actually on disk with
  `status: broken` and `broken_reason`. `bundle-day` refuses a day with a broken stream
  (`broken_record_stream`). If sealing the stream itself fails, the quotes tape is still
  sealed, with `records_stream_error`.
- `bundle-day` (`records.bundle_day`) writes `records/<day>/bundle.json`
  (`maker_core.replay.bundle.v0.2`, provenance `captured`, conditions from first to last
  recorded minute, one coverage group per condition) after the UTC day has closed.
  `records.day_active_intervals` gives the per-run windows for `stream_source(...,
  active_intervals=...)`; `records.records_summary` is the scorer's verified read.
- Size and replay limits: the Defender's synthetic 12-band day (decision-time stamping) was
  about 121 k records and 104 MB of record stream plus 62 MB of quotes tape. The mid-minute
  book refresh adds one book record per band-minute (about 5 KB at those depths), an estimated
  140 k records and 190 MB of record stream at 12 bands (about 280 k and 380 MB at 24). The
  replay reader's default `Limits` (64 MiB, 100 k records, 300 s) refuse such a day; read it
  with `Limits(**records.SHADOW_REPLAY_LIMITS)` (600 k records, 1 GiB, 900 s). Nothing prunes
  record streams.
- The round-trip test admits a bundle through a vendored copy of the reader rules
  (`tests/maker_core/fixtures/replay_v2_reader_contract.py`, pinned to build-line
  `2d8cccb13`) until the reader is on master.

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
- **Own-size mid (OD23, #267):** `own_size_mid` sums the minutes' `books_with_own_legs`
  and `mid_differs` counts; `minutes_not_recorded` counts minutes from tapes written
  before the field. Each tape row also names its `tape_schema` and `records_stream`.
- **Fills**, in the desk-study rule names: `strictly_through` (print strictly
  below the bid) and `at_price` (at or below), on the leg's own asset, filling
  `min(print size, remaining)` with the leg re-placed at full size each minute
  (60 s life). Spread captured against the 88a mid at the fill; net and adverse
  markouts at +1/+5/+30 minutes against the last two-sided 88a mid at or before
  the mark within 120 s (missing marks are counted, not zeroed).
- **Modelled reward** at `k_share` 1.0/0.5/0.3 from the decision's share and the
  recorded rate. Not paid reward. Legs on bands 88a did not select are counted
  as `legs_not_in_panel`, never scored.

- **Code:** each entry of `tapes` carries its `git_commit` / `git_dirty` / `git_error`, and
  `code` summarises the day: distinct `git_commits`, `tapes`, `dirty_tapes`, and
  `unbound_tapes` (no commit, or not provably clean). The CLI's one-line output repeats `code`.
  It is surfaced, never judged: parity-day counting uses it (the gate's parity definition).

No settlement mark, rebate, hurdle, bootstrap or verdict is computed: economic
scoring belongs to a pre-registered look (maker replay v2, the maker P&L desk
study), not to this diagnostic.

**Embargo.** `score` refuses, before opening any tape or 88a byte, UTC days
2026-09-30..2026-10-15 (maker replay v2 panel and settlement day) and
2026-10-15..2026-11-13 (desk-study decision panel and its pre-registered
extension), and any day not yet closed in UTC. The windows live in
`weather.market.maker_shadow_panel.EMBARGOED_UTC_DAYS`; lifting one is a reviewed
code change. The runner still tapes those days.

## Forward runner on the capture host

`scripts/ops/register_maker_shadow_runner.ps1` registers `WeatherMakerShadowRunner`:
one long-lived `pythonw -m weather.market.maker_shadow run --config
data\maker_shadow\shadow_config.json --stop-file data\maker_shadow\STOP` under an
S4U/Limited principal at BelowNormal priority (task priority 7). Its five-minute
repetition only respawns a crashed or rebooted run (IgnoreNew while one runs). The
registrar refuses a missing config, a config naming a wallet book or a non-paper
campaign, and an uninitialised latch, and supports `-WhatIf`. Registration is an
owner/production act; editing or testing the registrar arms nothing.

- **Stop** by creating the stop file: the run writes `terminal`, seals its tape at the
  next minute and exits; every respawn then refuses (exit 2) until the file is
  removed. `Stop-ScheduledTask` or a reboot kills the process and leaves an unsealed
  tape, which the scorer lists and never reads. A restart starts a fresh paper book
  (the latch persists).
- **Readout** (read-only, any hour): `scripts\ops\maker_shadow_readout.ps1
  [-ParityStartUtc <yyyy-MM-dd>]` prints one line: process, sealed days, last tick,
  the live run's code (`code <12 hex>`, `DIRTY`, `unbound (<git_error>)` or `not recorded`),
  rows and MB today (quotes tape plus record stream), crashed tapes, parity days and the
  embargo. It reads names and sizes, seal
  JSONs, the first line (at most 64 KiB) and at most the last MiB of the open tape and,
  with `-ParityStartUtc`, score agreement status; it never starts Python or reads 88a.
- **Restart** (after any merge that touches the runner's modules, and **at the engine
  freeze**): create the stop file; wait until no `maker_shadow run` process remains and the
  newest tape has its `.seal.json`; apply the change; delete the stop file (the next
  five-minute repetition respawns the run, or `Start-ScheduledTask WeatherMakerShadowRunner`
  starts it at once); confirm the readout shows the new `code`. The runner is not a
  STALE_CODE supervisor, so nothing restarts it automatically. Parity days count only from
  the first UTC day whose every sealed tape records the frozen commit (or a later reviewed
  one) with `git_dirty` false.
- **Resources, measured on the workstation 2026-10-08 with 24 bands** (`max_conditions`
  24): about 35 MB working set and 22 MB private, about 1.5 s CPU per minute, 14-20 s
  of sequential public GETs per minute (about 75 requests) after a first minute of
  about 65 s with discovery; about 88 KB of tape per minute, so about 126 MB per UTC
  day. Nothing prunes tapes. **The day-roll seal** (`TapeWriter.close`) was measured
  reading and verifying the whole day's tape in memory (about 1.3 GB private for about 12 s
  at UTC midnight on a full 24-band day); tape v0.2 seals streaming, one line in memory,
  not yet re-measured on the host. `score` of one full
  day holds about 1.2 GB for its tapes before the 88a panel (up to 2 GiB of panel
  reads), so it belongs in the leased night window.
- **Parity.** The `score` agreement is a self-consistency check (each recorded decision
  re-run from its recorded inputs). It is not a comparison with the v2 replay engine,
  and parity days count only from the engine freeze (STATE_OF_PLAY).

## Not yet

Status 2026-10-08; each item names its next step.

- **Live public-read verification:** partly done. A four-minute workstation run on
  2026-10-08 read Gamma events, CLOB books and CLOB reward records live: 24 bands were
  selected with no `unevaluated` band and no `universe_error`, and the guard allowed
  every minute. Every decision was `NO_QUOTE` (blind width without fair value), so no
  leg rested and the data-api `/trades` read and the paper fill path were not exercised
  live. Next: the first host days; the readout's print-gap count shows it.
- **Paper settlement of resolved bands:** open, unscheduled; it needs an owner
  decision on whether the shadow paper book matters before the v2 look.
- **Weather fair-value plugin and information clock:** open; the plugin is not on
  master (maker replay v2 line). Until it lands the shadow quotes blind width.
- **Settlement-horizon scoring:** open; it belongs to a pre-registered look, not this
  diagnostic.
- **Closed-bundle replay engine comparison:** open; it needs the frozen v2 engine
  (W1/W2/F3 merged) and is what shadow parity means for live readiness.
- **The six Phase 3 drills:** open, unscheduled; owner to say whether they gate the
  live pilot.
- **Launcher with resource ceilings:** open. The scheduled task runs at BelowNormal
  without a Job memory ceiling. Tape v0.2 replaces the in-memory day-roll seal with a
  streaming one; `score` still holds a day's tapes in memory.
- **Tape v0.2 on the host:** open; the runner picks it up at its next restart, and the
  record stream's live size and the bundle's admission by the real reader are measured on
  the first host day.
- **Scheduled task:** registrar present (2026-10-08); host registration waits for
  the owner.

Open PR #115 holds an earlier, larger shadow implementation stacked on the unmerged
replay harness; #192 supersedes its runner, tape and nightly path (the #192
description lists the pieces).

## Update when

Update with the commands, the registrar or readout, config or fixture schema, endpoint allowlist, tape or
score format (including the code-identity fields and the v0.2 record stream or day bundle), guard integration, fill or markout rules, or the embargo windows.
