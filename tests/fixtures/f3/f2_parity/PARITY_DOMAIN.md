# F3 policy parity domain

Equivalence covers **reconciled clean simulation states only**. It is not a
claim that F3 replays a real account ledger. The extraction pin is recorded in
`PROVENANCE.json`; this document's line references are at F2
`c4c3216b1c98f74fd7dc1716c6cf8e45b70beb4f`.

`SimCashState` must assert available cash equals expected cash, zero cash
quarantined after the bridge, a bridge that exists, a healthy ledger, and no
unknown outgoing, blocking legacy, or other unknown activity. `CapitalState`
must have zero external activity and available gains drawn only from proved
retained redemption gains. Reward/rebate income contributes **zero** to G;
simulated reward accrual belongs to the trial's P. Incentive cash remains
segregated. The simulator constructs only states in this domain.

The following F2 accounting checks are vacuous in that domain and are replaced
by typed `F3NotReconciled(field)` assertions before any policy decision:

| Check | Pinned F2 source |
| --- | --- |
| Bridge existence (`capital_bridge_required`) | `lfc_capital.py:579-580` |
| Ledger halt/mismatch (`capital_ledger_halted`) | `lfc_capital.py:581-582` |
| Unknown outgoing activity (`capital_unknown_outgoing_cost`) | `lfc_capital.py:583-586` |
| Blocking legacy activity (`capital_legacy_unknown_cash`) | `lfc_capital.py:587-588` |
| Unexplained debit (`capital_cash_changed`) | `lfc_capital.py:598-602` |
| Spendable-cash restriction on unrecorded or quarantined incoming cash (`capital_spendable_cash`) | `lfc_capital.py:603-610` |

The usual `capital_spendable_cash` comparison for segregated funds and existing
resting reserves remains in F3. The four original stop witnesses are covered:
`cash_reconciled` agrees with F2; `unexplained_debit`, `unrecorded_incoming` and
`incoming_quarantined` raise `F3NotReconciled` instead of returning a decision.

Fixture outputs come from executing pinned F2 code with the handoff's synthetic
duck-typed gate and ledger adapters. They are not outputs of a reference formula
implemented by the F3 test. All gate cases have cash equal to expected cash and
zero quarantine/unknown/external activity. Input uniqueness, exact output
strings and hashes are checked. Horizon cases use an explicit synthetic
in-memory registry across twelve zones; F2's DTE code is unchanged.

Held observations execute the **active** `F2Band.observe_snapshot` path:
`lfc_f2_controller.py:186-196` calls `re1_attended.observe` at `:75-133`, then
`check_book`. Drift requests a requote (`re1_attended.py:780-793`); a fresh
book refusal becomes `HoldEnd` and ends the band (`:820-828`). F3 therefore
returns `requote` for drift after a passing fresh book check, `retire` for a
fresh refusal, and otherwise `hold`. The legacy `midpoint_drift` exception in
`mm_stage2_hold.py:202-210` is not the active F2 path. In particular, distance
equal to a 3-cent reward maximum and within the inclusive [1,3] window does
not itself retire an active F2 band; the extracted active path is authoritative.

The master ruling resolving handoff falsifier 11.2 authorizes this domain and
the added cash assertion type. Re-extract at the F2 freeze sha at the T033
seal before asserting freeze-bound parity.
