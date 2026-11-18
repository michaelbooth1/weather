# S31 P0 AMENDMENT 1 (2026-10-31): Kalshi twin on its Weather Company regime, 08-14..09-29

Status: **master AMENDMENT** to `rule_s31_p0.md`, issued before any read (master ruling 2026-10-31, relayed by
the coordinator). It is not a clarification: it changes the design. The rule file (sha256
`d50112ccf2a22b2f02140e06c68bbbe36936a2ac9dc8e16351a7188ee2ea856e`) and Clarifications 1-4 are not edited:

| file | sha256 |
| --- | --- |
| `clarification_s31_p0_1.md` | `b7bb9f2aafb654bd68389c170416f3efae64b33696723a6c54572ce22e177e5d` |
| `clarification_s31_p0_2.md` | `798dfaa912c7e94da97c0c99340d12726bb9c606b7279324b92ef4b8c670bd26` |
| `clarification_s31_p0_3.md` | `654408acbc40fa981b30947547863ae7140694f530f559f1bb9fefe94db0a340` |
| `clarification_s31_p0_4.md` | `ee35f782f89934095bad84e1c4ad92906c1a1b77ae687ec6d388879c89bc4c2c` |

Where this file and those files disagree, this file wins. Lane L14, written outcome-blind.

## 1. Reasons (written first)

1. **Outcome-blind.** No twin price, label or outcome has been read. The only inputs to this change are the
   Kalshi rules text (allowlist A) and request and row counts. The design change is outcome-blind.
2. **The amended twin measures the same quantity as our market.**
   - The rule's own §1 names CLI settlement as a WEAKNESS. Under S0 falsifier 2, the CLI-minus-WU gap is weather
     we can model, not trader information.
   - From the 08-14 event onward, Kalshi settles on The Weather Company's (TWC) maximum at the same station. TWC
     is our own label source on every scored date (WU before 10-23).
   - The amended twin therefore measures the SAME quantity as our market.
   - A lead, as rationale only and not a separate pre-registration: a TWC-settled twin may sit closer to our
     settlement than a CLI-settled one. That makes the trader-pool channel cleaner to test. It is not a predicted
     sign or size.
3. **One source regime.** The change falls on 08-14, so the whole scored window, 08-15..09-29, is ONE source
   regime. The drop-after-change clause exists to keep the measurement stable. That intent is kept by dropping
   the OTHER side of the change: the CLI-settled dates before it.

## 2. What the literal rule would have done (recorded verbatim)

The literal V0.1 reading would have closed S31 KAL UNTESTABLE. Read literally, a change of source is a changed
measurement, so every one of the 7 cities drops from 08-14 on, leaving 0 scored dates for KAL-MEAN and
KAL-WIDTH. Master chose this amendment on metadata only, before any price read.

V0.1 evidence (rules text, allowlist A, all 7 series, 420 events):

- Events 08-01..08-13: "according to [or as reported by] the National Weather Service's Climatological Report
  (Daily)".
- Events from 08-14 on: "maximum temperature recorded at <City> (CLIxxx) ... according to The Weather Company".
  On 08-14 the rules name only the city, except LAX, which names CLILAX. From 08-15 on, every series names its
  code: CLIATL, CLIAUS, CLIHOU, CLILAX, CLIMIA, CLISFO, CLISEA.
- V0.2: all 420 of 420 events tile. The event metadata tickers equal the /markets tickers on all 420.
- The V0 table is `v0_table.json`, sha256 `0f34fbf0176a6fbd75cb5132753caaf826f57068ae7c7ca65f2845f6d43948e5`,
  in the R13 archive `C:\archive\ruled-out\_s31-intake\s2_fetch\runs_20261031_kalshi\v0\`.

## 3. The amendment

- **Event range.** KAL keeps events 08-14..09-29 (TWC-settled) for all 7 same-station cities:
  - atlanta KATL;
  - austin KAUS;
  - houston KHOU;
  - los-angeles KLAX;
  - miami KMIA;
  - san-francisco KSFO;
  - seattle KSEA.

  Events 08-01..08-13 (CLI-settled) are DROPPED from all scoring and from every fit. Their snapshots are
  uncovered for KAL: no twin value, no σ_s or g_z contribution, and no placebo donor.
- **Burn-in.** For KAL the burn-in becomes 08-14 only. The fit table is 08-14 plus the scored dates. The
  survivors-only walk-forward w starts there: the first scored date's w fits on nothing, then each date d fits on
  dates ≤ d − 2, from 08-14.
- **Scored dates** are unchanged: 08-15..09-29.
- **Controls unchanged.** The positive controls in rule §7(a) run on the unamended tables: served R 1.774 / 1.526,
  MG-1 07-12 excess 0.0120, and the w = 0 identity. They concern only our own market.
- **V0.1 restated.** A city stays in KAL iff two things hold:
  - from 08-15 on, its rules name its CLI-coded station, which is our WU label station above;
  - its rules name The Weather Company as the source.

  An event whose rules name any other source or station is dropped.
- **K = 3 unchanged:** KAL-MEAN, KAL-WIDTH and FEX-MEAN.
- **FEX** is UNTESTABLE with p = 1 in the BH family. Reopen-if: "a public ForecastEx filing or contract spec
  that names each city's settlement station."
- **N** as in Clarification 1: class SCREEN, N80 78. The realised N is reported at run.
- **Verdict labels** as in Clarification 2 (D3, Δ_edge = 0.224).

## 4. §3 and §4 restated on our market's WU day and effective-print-cutoff semantics

Before any price read, every CLI-specific semantic in rule §1 (where §3 points to it), §3 and §4 is restated
here. Each change is listed with the old text against the new. Our cutoff applies to the twin too.

**Definitions used below.**

- **t_c:** the snapshot's `captured_at_utc`, the instant our market m is read.
- **Our WU day:** the target date's local civil calendar day in the city's zone (America/New_York, Chicago or
  Los_Angeles, with DST), midnight to midnight. This is our label day.
- **h_cut:** the snapshot's `cutoff_hour`. This is the effective WU print cutoff: the wall-clock hour capped by
  the latest retained WU observation minute.
- **T_cut:** the UTC instant of h_cut:00 local on the target date.
- **t_eff:** the earlier of t_c and T_cut.

| # | Where | Old text (CLI semantics) | New text (our semantics) |
| --- | --- | --- | --- |
| 1 | §1 "Kalshi settles on a different quantity" | "Kalshi settles on the **NWS Daily Climate Report (CLI)**: a continuous-sensor daily maximum over the local-standard-time day (01:00-00:59 local during DST)." | From the 08-14 event, Kalshi settles on The Weather Company's daily maximum at the same station, over our WU day (local civil midnight to midnight, DST-aware). The LST 01:00-00:59 day does not apply to any kept event. |
| 2 | §1 "Thin or stale twin prices", which defers to §3 | "A price taken after the high is known is excluded by the capture-time rule (§3)." | No twin candle ending after t_eff is used. This applies our cutoff to the twin: the twin is never read later than the WU print our own features admit at that snapshot. There is no separate "high known" rule. The snapshot population and the label are our layout's, and no twin price after the end of our WU day is ever read. |
| 3 | §3 V0.1 station | "A city stays in KAL iff its post-08-15 rules name the same station as its pre-08-15 CLI code." | A city stays in KAL iff its rules from 08-15 on name its CLI-coded station, and that station is our WU label station (§3 of this file). The 08-14 event (burn-in only) names the city without a code; it is kept as burn-in and never scored. |
| 4 | §3 V0.1 measurement | "It also must not name a different measurement than the NWS CLI daily maximum. ... A changed measurement drops it for the dates after the change." | The rules must name The Weather Company's daily maximum (TWC is our label source). The CLI-settled events 08-01..08-13 are the dropped side of the change. Any later change of source or station drops that city from the changed date on. |
| 5 | §4 quote | "take the latest 1-minute candle with `end_period_ts` ≤ t_c and ≥ t_c − 60 min." | Take the latest 1-minute candle with `end_period_ts` ≤ t_eff and ≥ t_eff − 60 min. A snapshot with no finite h_cut is uncovered: our cutoff cannot be applied to it. The bid/ask and spread conditions are unchanged. |
| 6 | §4 coverage | "a snapshot is covered only if all six markets of the event have a quote." | A snapshot is covered only if its target date is in 08-14..09-29, its event passed V0, and all six markets have a quote at t_eff. |
| 7 | §4 moments | "with W = 2 and integer °F intervals from V0.2" (CLI whole °F) | Unchanged in form. TWC's maximum is whole °F, as our WU label is. The intervals come from allowlist A's strikes: `less` X covers ≤ X − 1, `between` a..b covers a..b, and `greater` Y covers ≥ Y + 1. The tails are placed as the rule states: (X − 1) − W/2 and (Y + 1) + W/2, with W = 2, which is the sweep's open-band convention (the included end value ∓ W/2). |
| 8 | §2 dates (for KAL) | "burn-in 2026-08-01..08-14; scored 2026-08-15..09-29" | KAL: burn-in 2026-08-14 only; scored 2026-08-15..09-29. 08-01..08-13 are dropped from every fit and score. |

FEX-MEAN, the FEX ladder and FEX's V0.3 and V0.4 are not restated. FEX is UNTESTABLE and none of its rows is
read.

## 5. Falsifier 2, updated

S0 falsifier 2 said that part of any Kalshi-minus-us gap is the CLI-minus-WU gap: modelable weather, not trader
information. On the scored dates (08-15..09-29) that gap no longer applies, because every kept Kalshi event
settles on TWC's maximum at our station over our WU day. The residual TWC-versus-our-label gap is near zero by
construction. What remains is integer rounding at the same source and any TWC-versus-WU display difference;
neither is a weather signal the twin could carry. Falsifier 1 (shared public information, cross-venue arbitrage)
is unchanged and is what the P0 tests.

## 6. Code binding

The P0 module (`weather.calibration.s31_p0`) pins this file's sha256. It refuses to run when the file in the
tree or its byte-identical pinned copy in the run's `--out` does not match, and the receipt records the sha. It
implements the event range, the 08-14 burn-in, t_eff and coverage exactly as §3 and §4 of this file state. Ledger
row 99 carries this file's sha256 before the P0 runs. Nothing runs until the coordinator admits the P0.
