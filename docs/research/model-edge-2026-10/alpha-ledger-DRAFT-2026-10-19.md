# DRAFT, UNSIGNED: forward alpha ledger for new-date instruments, 2026-10-19

> **Status: DRAFT-UNSIGNED, NOT ACTIVE.** Written on the workstation (model-edge week 1) for the owner's single
> sign-off on Fri 2026-10-23. Until signed it is a proposed control, not the control; it changes nothing that is
> already signed.
>
> **Signed SHA-256:** `________________________________________________________________` (left blank; recorded in the
> DECISION_LOG signing row). The seed file's SHA-256 is recorded in the same row.

- **Owns:** the forward alpha ledger: one row per (family, date range, alpha spent or reserved, pre-registration
  SHA-256) for instruments scored on **new dates** (>= 2026-09-30). Its machine-readable form is
  [`alpha-ledger-seed.jsonl`](alpha-ledger-seed.jsonl), validated by [`alpha-ledger.schema.json`](alpha-ledger.schema.json).
- **Does not own:** the sealed pre-boundary panel's budget, which stays in
  [CAMPAIGN_LEDGER](../../operations/CAMPAIGN_LEDGER.md) (mirrored here as `CL-PANEL` for the double-spend check only);
  the signed instruments' rules (their own files); date reservations
  ([reserved-confirmation-window](../../operations/reserved-confirmation-window.md) wins on any disagreement).
- **Read when:** drafting or signing any pre-registration that scores dates >= 2026-09-30; checking that a new
  instrument does not double-spend a family or date; recording a look's outcome.

## 1. Rules

1. **Append the row before scoring.** A new instrument gets its rows (status `DRAFT`) when drafted and `SIGNED` (a new
   row superseding the draft row) when the owner signs. A look's outcome is a new row (`SPENT`, `VOID` or
   `UNTESTABLE`) superseding the signed row.
2. **Append-only.** Never edit or delete a row; never reuse a `row_id`. A correction is a new row with `supersedes`.
3. **No double-spend.** A (family, local target date) cell is held by at most one non-superseded row with
   `alpha_state` `reserved` or `spent`. Different families may share dates **only** where no reservation forbids it
   and no signed no-peeking rule is broken by the later instrument's looks (example: EDGE-1 annex §6.3).
4. **Alpha is per family.** Rows that share a `family` and a `prereg_path` are one Holm family; the `alpha` field
   repeats the family's level, it is not additive across those rows.
5. **Provenance per row.** Every row cites the file and the row/section that carries each fact; owner facts cite a
   DECISION_LOG row, and verbatim fragments are quoted.
6. **No outcome enters a row before its look.** Rows hold rules, hashes and dates, never results, until the look.
7. **Validation:** every line validates against the schema (JSON Schema 2020-12). Seed validated 2026-10-19 with
   `jsonschema.Draft202012Validator` (10 rows, 0 errors).

## 2. Seed (2026-10-19), human-readable

Signed instruments (seeded from the docs; they stay exactly as signed):

| Row | Instrument | Family | Dates | Alpha | Pre-registration SHA-256 | Provenance |
| --- | --- | --- | --- | --- | --- | --- |
| `MG1` | MG-1 | forecast/morning-nbm-guidance-read | D0 2026-10-15 fixed; provisional last 2026-11-28, may only move later; 45 countable | 0.025 one-sided, reserved, one look | `b044e0f196512379d2f74a22a2a97a10cf58fdbcf5a255c4eb6a470f7f6ba665` | DL 2026-10-04 (signing), DL 2026-10-16 (window bound); reserved-confirmation-window.md |
| `EVFIX` | Evening lock-in fix scorer | forecast/evening-lockin-anchor-17-23 | 2026-10-16..10-27 (outcome-blind extension to 10-28, 10-29) | 0.025 one-sided, reserved; H2 by fixed sequence; one read 2026-10-29 `--no-market` | `16ed20df6035fbc512b085757dae1d98d6ca5b3b1326fcdf44b0b33708e577ac` | DL 2026-10-13 (signing), DL 2026-10-15 (A6/A7) |
| `T3R3` | t3-r3 13-16 remaining-rise | forecast/remaining-rise-decided-band | first eligible date >= 2026-10-16 (undated), 45 countable | 0.025 one-sided, reserved (separate family, OD-B3 default), one look | `71cdb452cb9f03aba1aa2464faafceaf7d2f42970c910b33424c583c61503081`; artifact `b727fe1a897f8786afcd89514f0bae4a82d9e03ad951f2d72db9e228dd2afb09` | DL 2026-10-16 (signing), DL 2026-10-15 (OD-B1..B5) |
| `CL-PANEL` | Sealed pre-boundary campaign (mirror) | sealed-panel/pre-boundary-2026-06-03-07-30 | 2026-06-03..07-30 | 20 x 0.0025 two-sided; 7 spent, 13 remain | (CAMPAIGN_LEDGER) | CAMPAIGN_LEDGER "Spend to date" |

Proposed and placeholder rows (this programme):

| Row | Instrument | Family | Dates | Alpha | Status |
| --- | --- | --- | --- | --- | --- |
| `CL-B` | Model-edge Stage-B sealed-panel decisions | sealed-panel (mirror) | stratum B only | at most 2 x 0.0025 two-sided from CAMPAIGN_LEDGER, q = 3.1098893; batched survivors only | PROPOSED (master-agent synthesis caveat, relayed 2026-10-19) |
| `EDGE1-A0`, `EDGE1-A1` | EDGE-1 H-A0 / H-A1 | forecast/model-vs-market-edge1 | D0 2026-10-25 (OD-A6 not held) or 2026-10-28 (held); 45 countable; interim 20 | one family, 0.025 one-sided, Holm over 3; interim spends nothing | DRAFT ([EDGE-1 annex](edge1-annex-DRAFT-2026-10-19.md)) |
| `EDGE1-A2` | EDGE-1 A2 (E2) | forecast/model-vs-market-edge1 | none | none | CLOSED_UNUSED: E2 closed in development, all four w_b 0.00 (EDGE-1 annex §1.1) |
| `NBM2` | NBM-2 | forecast/morning-nbm-guidance-read | none; may not use MG-1's window without a new owner decision | none yet | PLACEHOLDER (named in the synthesis; no pre-registration) |
| `E3` | Maker markout, model-gated vs `blind_re1` | maker/model-gated-vs-blind | none | none | PLACEHOLDER; UNTESTABLE on forward weather dates ([GO/NO-GO rule](go-no-go-rule-DRAFT-2026-10-19.md) §2.3) |

### 2.1 Double-spend check on the seed (2026-10-19)

- `MG1` and `NBM2` share a family: NBM-2 cannot hold any date of MG-1's window. Recorded in the `NBM2` row.
- `EDGE1-*` versus `MG1`: different families; EDGE-1 arms read no NBM guidance (EDGE-1 annex §6.1). No conflict.
- `EDGE1-*` versus `EVFIX`: different families; date overlap only on EVFIX's possible extension dates 10-28/10-29, and
  every EDGE-1 join is after 2026-11-13. No conflict.
- `EDGE1-A1` versus `T3R3`: **conflict.** A1 contains the t3-r3 stage, so A1's looks would read t3-r3 holdout outcomes
  before t3-r3's look. Unresolved until the owner rules OD-E1 (EDGE-1 annex §6.3; default: defer A1's looks).
- `CL-B` spends from `CL-PANEL`'s remaining budget; it adds no new alpha and touches no new date.

### 2.2 Instruments deliberately not seeded

- Maker replay v2 (registration DRAFT on `codex/maker-replay-v2-build-20261003`; signature target 10-22..23): its own
  hurdles on panel UTC 2026-09-30..10-13; added as a row when signed.
- The live-fill calibration campaign and the maker-P&L desk study: no forecast alpha (the desk study runs descriptive
  only, DL 2026-10-14).
- The T+1/T+2 NWP-timing market-only study (frozen 2026-10-02): awaits the 88a transfer; added when it is dated.

## 3. Signature

UNSIGNED. On signature the owner adds a DECISION_LOG row with this file's raw SHA-256 and the seed file's raw SHA-256.
From then on the jsonl is appended only, and the production agent records each signing and look in it in the same
commit as the DECISION_LOG row.

## 4. Owner decisions

- **OD-L1:** adopt the forward ledger (rules §1) for every new-date instrument from signature.
- **OD-L2:** confirm `CL-B` (at most 2 sealed-panel decisions, stratum B, batched survivors).
- **OD-L3:** record t3-r3's reservation in reserved-confirmation-window.md (DL 2026-10-15 took the narrow default; the
  file still says no other date is held out). A production docs change, not part of this draft.

## Sources

- [CAMPAIGN_LEDGER](../../operations/CAMPAIGN_LEDGER.md); [reserved confirmation window](../../operations/reserved-confirmation-window.md); [DECISION_LOG](../../operations/DECISION_LOG.md) rows 2026-10-04, 2026-10-13, 2026-10-14, 2026-10-15, 2026-10-16, 2026-10-17.
- [MG-1](../morning-guidance-read-mg1-preregistration-2026-10-04.md); [evening-fix](../evening-lockin-fix-scoring-preregistration-DRAFT-2026-10-13.md); [t3-r3](../remaining-rise-13-16-preregistration-DRAFT-2026-10-13.md).
- [Methods annex](prereg-template-and-methods-annex-DRAFT-2026-10-19.md) M6; [EDGE-1 annex](edge1-annex-DRAFT-2026-10-19.md) §6.
