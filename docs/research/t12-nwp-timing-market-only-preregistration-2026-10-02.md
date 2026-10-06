# T+1/T+2 market moves around NWP availability — market-only pre-registration (2026-10-02)

Status: **FROZEN 2026-10-02, committed before any input is transferred or read.** Docs-only. Owner-approved as
option A of the 2026-10-02 T+1/T+2 question (DECISION_LOG 2026-10-02). Not a model-panel candidate, not an edge
claim, no α spent, no live or quoting authority. Changing anything below after the transfer arrives requires a new
dated amendment that names this file, written before the affected quantity is read.

## Premises found while scoping (recorded so the question is not asked again in its original form)

1. **The served model has no T+1/T+2 output.** Serving targets the market-local *today* event
   (`default_target_date()`, `src/weather/market/market_config.py`); all 293 event folders retained on the workstation
   (`data/snapshots/highest-temperature-in-*`, target dates through 2026-08-12) begin on their target date (lead 0
   in 293 of 293). The maker design says the same (`docs/operations/informed-maker-design-2026-09-25.md`, decision 5).
   "Served model versus market on T+1/T+2" therefore has no data. The T+1/T+2 number we would quote with is the maker
   plugin fair value, already frozen for a single read on 2026-10-15 by
   `docs/research/t1-fair-value-preregistration-2026-09-25.md` (exam branch; Amendment 3 adds a reported-only
   NWP-availability breakdown).
2. **The public execution tape is T+0 only.** `run_live_capture` reloads its seeds with `now`, and
   `load_market_day_seeds` selects the event whose date is the market-local today
   (`src/weather/market/execution_tape_capture.py`). It holds no T+1/T+2 trades, so it is not an input here.
3. **88a is the only capture of T+1/T+2 books and public trades** (`docs/operations/passive-maker-evidence-capture.md`:
   per-minute YES/NO books for up to ten selected conditions per city, at least three per day-ahead, plus public
   `last_trade_price` connections over the selected universe). It was approved 2026-09-23, so the permitted window
   (UTC days before 2026-09-25) holds at most about two days; the exact first day is a production fact.

## Question

Do T+1 and T+2 band markets move more, quote wider, or trade more in fixed windows after scheduled GFS and ECMWF
availability than in the matched windows just before, beyond what matched placebo windows show? A clear yes would
support scheduled maker pulls at those times; it would not show that pulling pays (fills and rewards are the
desk study's question, `docs/research/fill-toxicity-desk-study-preregistration-2026-09-23.md`).

## Data (frozen)

- **Only** 88a records in `data\maker_evidence\<UTC-day>\` with `<UTC-day>` ≤ `2026-09-24`. Nothing dated
  2026-09-25 or later; never anything for UTC 2026-09-30..10-14 (exam), from any store.
- Books (two-sided YES top of book) and deduplicated public trades only. **No settlement, fair value, served snapshot,
  NBM bulletin or exam bundle is read.** Books captured on 2026-09-23/24 for target dates 2026-09-25/26 are inputs the
  frozen T+1 panel also samples; this study reads their mids only, never a label or fair value, so it does not
  compute or reveal that panel's estimand.
- Leads: market-local lead 1 and lead 2 at the window anchor. Lead 0 is out of scope.

## Windows (frozen, UTC; all dates are in North American summer time)

Availability anchors are engineering assumptions, not measured latency:

- **G (GFS):** cycle 00/06/12/18Z + 210 min (`nwp_release_cycles` default, `src/weather/market/info_event_calendar.py`):
  anchors 03:30, 09:30, 15:30, 21:30. Pre [a−45, a), post [a, a+45) minutes.
- **EN (ECMWF with NBM, inseparable):** ECMWF IFS open data at cycle + 7 h 40 min — ECMWF's real-time dissemination
  schedule (read 2026-10-02) ends the 00Z/12Z medium-range control run at 07:34/19:34 UTC and open data follows the end
  of that schedule; 06Z/18Z take the same offset by assumption. Anchors 01:40, 07:40, 13:40, 19:40. NBM 01/07/13/19Z
  availability (+1 h, the T+1 pre-registration's assumption) falls 20 minutes later, so ECMWF cannot be separated from
  NBM; the class is reported as one. Pre [a−45, a), post [a, a+65) (covers NBM + 45).
- **S (placebo):** anchors 05:35, 11:35, 17:35, 23:35 — the midpoints of the gaps between real windows; pre [a−45, a),
  post [a, a+45). Each placebo half is at least 35 minutes from any real window.
- **Exclusion:** a (market, anchor) pair is dropped if either half overlaps [local midnight − 30 min, + 60 min] of that
  market (lead rollover and new listings): 04:00 UTC Eastern (NYC, Atlanta, Miami, Toronto), 05:00 Central (Chicago,
  Dallas, Austin, Houston), 06:00 Mountain (Denver), 07:00 Pacific (Los Angeles, San Francisco, Seattle).

## Measures, per (UTC date, market, event, lead, condition, anchor, half)

- **M1 (primary): mid variation per minute** — sum of |mid(t) − mid(t−1)| over consecutive captured minutes both inside
  the half (pairs more than 2 minutes apart dropped), divided by the number of pairs. Mid = (best bid + best ask)/2 of
  the YES book; one-sided or crossed minutes dropped.
- **M2:** mean quoted spread (best ask − best bid) per captured minute.
- **M3:** public trades per minute and shares per minute, deduplicated by the existing collapse rule
  (`src/weather/market/execution_tape_markout.py`), YES and NO legs mapped to one condition.

## Estimands and inference

- Intensity ratio per class c ∈ {G, EN, S}, lead and measure: R_c = (Σ post quantity / Σ post minutes or pairs) ÷
  (Σ pre quantity / Σ pre minutes or pairs), pooled over conditions, markets and dates in the cell.
- **Primary:** the placebo-adjusted excess **E_c = R_c / R_S** for c ∈ {G, EN}, M1, per lead.
- Secondary: E_c for M2 and M3; R_c per cycle (00/06/12/18Z), per city, and for mids outside [0.10, 0.90]
  (primary uses mids inside); the pre-window level against the placebo pre-window (anticipation).
- Intervals: 10,000-replicate date-clustered bootstrap (resample UTC dates), seed 20261002, two-sided 90% percentile;
  the crossed date x market bootstrap (independent date and market multiplicities) reported beside. Ratios are formed
  inside each replicate.
- Labels, applied per class and lead to M1 only; descriptive, no α:
  - fewer than 10 date clusters **or** fewer than 10 market clusters in the cell → `INCONCLUSIVE_UNDERPOWERED`, forced;
  - `NWP_MOVES_T12`: date-clustered 90% lower bound of E_c ≥ 1.5 and crossed lower bound > 1.0;
  - `NWP_NOT_THE_LEVER`: date-clustered 90% upper bound of E_c ≤ 1.2;
  - otherwise `INCONCLUSIVE`.

## Falsifiers

- **F1:** both E_G and E_EN have upper bounds ≤ 1.2 at a powered read — scheduled NWP times are not where T+1/T+2
  markets move; drop NWP-timed pulls for T+1/T+2.
- **F2:** R_S is as large as R_G or R_EN (point estimates within each other's intervals) — the post/pre contrast is a
  generic intra-hour or diurnal pattern, not NWP.
- **F3:** a supportive EN result with a null G result cannot be attributed to ECMWF (NBM is confounded by design).
- **F4:** if the median window has fewer than one public trade, M3 is reported as uninformative, not as a null.

## Exclusions (declared)

- Conditions named in any 88a raw-update subscription on a UTC day (RE-1 session bands and controls; our own resting
  orders were in those books) — excluded for that whole UTC day, counts reported.
- A half-window with book coverage below 90% of its minutes; 88a cap events, gaps and disconnects inside a half.
- Duplicate public trade identities (collapse rule above); records failing segment-manifest hash verification
  (refuse the segment, report it, never repair).

## Power statement

The permitted window has at most about two UTC dates, so every cell is `INCONCLUSIVE_UNDERPOWERED` by construction and
no MDE can be computed. This read is a **feasibility pilot**: it verifies the reader, coverage, exclusion rates and the
variance components needed to size a powered read, and it reports the numbers above as description only. Market
clusters (12, fewer after exclusions) also cap crossed-interval power whatever the date count (EF §1d, §5).

**Earliest powered option, not authorized here:** the same frozen design on 88a UTC 2026-10-15..10-24 (ten dates,
after the exam exclusion and inside the 10-15..10-30 retention hold). It needs a separate owner decision and a dated
amendment fixing its window before any of those dates is read.

## Transfer manifest (production scp; analysis waits until it arrives and is verified)

Production selects and copies, read-only, under the host load policy (a small copy; not inside 12:00–00:30):

| # | Source on the capture host | Selection |
| --- | --- | --- |
| 1 | `data\maker_evidence\<YYYY-MM-DD>\<HH>-<segment>\*` | every day directory with `YYYY-MM-DD` ≤ `2026-09-24`, recursively, as stored (lossless archives allowed with their manifests) |
| 2 | `data\maker_evidence\extra_conditions.json` | the current file, for its schema only (it is overwritten per session) |
| 3 | `transfer-receipt.json` (written by production) | for every file in 1–2: relative path, bytes, SHA-256; the list of day directories found; the explicit statement that no directory dated 2026-09-25 or later was included |

Destination on the workstation: `data\research_inbox\t12-nwp-timing-2026-10-02\` (ignored runtime state, never git).
Explicitly **not** transferred: the public execution tape (T+0 only, premise 2), `data\snapshots`, settlements, NBM
bulletins, exam roots and any 88a day ≥ 2026-09-25. On arrival the workstation verifies the receipt and each segment's
`manifest.json` before any record is decoded.

## Update this file when

Never edited after freeze; add a dated amendment section before the affected quantity is read.
