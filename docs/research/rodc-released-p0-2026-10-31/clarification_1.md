# Clarification 1 to the R-ODC / X13 released-cell P0 rule (ledger row 103, lane L16, 2026-10-31)

Applies to `rule_rodc_released_p0.md`, sha256 `9bff5c02762a27ef604219b305e6a8043497cbf0316ec2403b879f4ed09a2f11`.
The pinned rule is not edited. Where this clarification and the rule differ, this clarification wins.

These are master's rulings of 2026-10-31, relayed by the coordinator, on the rule's section 7 open points. They were
written before any computation or read for this test.

1. **Arm form (open point 1): ACCEPTED as the linear surrogate.**
   - Arm 1 is named **"R-ODC-lin (linear surrogate on frozen R-ODC features)"** in every output, receipt and
     register line.
   - **Register text:** a kill of R-ODC-lin closes only the linear market tilt on these features on these cells.
     Row 72's HGB candidate keeps its forward P1.
2. **Pooling (open point 5): ACCEPTED.** The decision pools all 14 dates, as row 80 did. Pre (10-01..10-09) and
   post (10-10..10-14) are reported but do not decide. 10-10..10-14 stay excluded from EXHAUSTION_REGISTER §5
   order 6.
3. **Coverage (open point 2): ACCEPTED.** An arm whose inputs are not capture-time available is UNTESTABLE through
   the run's own coverage count against the rule's floor (10 dates, 1,000 population snapshots). No value is read
   before the run to decide this.
4. **Rule-14 intake (open point 4): opened by master's dispatch.**
   - **Mechanism, stated as a hypothesis:** the market under-uses overnight-boundary-layer information in the
     07-12 morning.
   - **Falsifier:** the market already prices METAR lows and dewpoint. A KILL at edge size is consistent with the
     falsifier at edge size only.
   - **X13 on history:** it is sub-edge but real on Oct-Dec history (row 95, D3 rerun, Δ [−0.00169, −0.00058]).
     That history result is not evidence against the market.
5. **Power (open point 3).** The binding in-run gate is computed at the **measured 07-12 SE**: the larger of the
   run's date-clustered and REV-2 block-3 bootstrap SDs, consistent with the wider bounds. Below 0.5, the only
   labels are UNTESTABLE at edge or at sub-edge. The projected 0.99999 from row 80's 13-16 SE is not binding.
