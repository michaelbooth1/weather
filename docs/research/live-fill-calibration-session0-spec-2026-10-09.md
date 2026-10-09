# Live Fill-Calibration Session 0 Spec (DRAFT for owner signature)

Status: DRAFT, 2026-10-09. Not signed. Session 0 was approved in principle
by the owner (relayed ~14:55); this spec is the version to sign. It
authorizes no order. Session 0 is a live, owner-started limit and dead-man
exercise on a market outside every panel. It counts toward the campaign L
ledger and toward **no** estimand.

Owns: the session-0 market rule, size, duration, sub-runs and pass criteria.

Read when: building the session-0 mode, starting session 0, or judging
whether it passed.

Update when: only by a dated clarification at the end, before session 0
starts.

Parent: [live fill-calibration pre-registration](live-fill-calibration-preregistration-2026-10-09.md)
§§6, 7 and 9. Session 1 may not start until every pass criterion below
holds.

## 1. Target date

Session 0 runs as soon as the code branch (pre-registration P4) passes its
fakes and tests. The ideal dates are 2026-10-12 or 2026-10-13. It must run
before 2026-10-15T00:00Z so that session 1 can start on 10-15.

Session-0 artefacts are live operational records dated inside 09-30..10-15.
They are not 88a, panel or settlement data. Even so, a sub-agent working
under the workstation embargo rules reads them only with the coordinator's
clearance.

## 2. Market choice rule (mechanical, checkable)

The selector, a `session0` mode of the campaign script, lists the
International Polymarket CLOB markets that pass **all** of these:

1. The event slug matches **no** slug prefix of the 12 built-in markets in
   the canonical registry, and **no** YouTube market slug. This keeps it
   outside every built-in T+1/T+2 band and every panel.
2. No condition of the event appears in:
   - the 88a `--extra-conditions` file in force;
   - the shadow-panel scope;
   - `panel_exclusions.jsonl`.

   Together these mean it is outside 88a's retained scope.
3. The wallet baseline (T − 40 min) holds no position and no open order in
   any condition of the event.
4. The market's end date is ≥ 7 days after the session date, so it cannot
   resolve during session 0.
5. The book is two-sided and uncrossed, mid ∈ [0.20, 0.80], the tick is
   0.01, and `min_order_size` ≤ 20.

**Pick:** the passing market with the largest displayed two-sided depth
within 3 c of the mid. Ties go by ascending condition ID.

The script writes the full candidate table and the pick to
`session0/selection.json`, and records its SHA-256 in the journal. The
owner checks rules 1–2 by eye against the registry before typing
`go <6 hex>`.

## 3. Size, quote, duration

| Item | Rule |
| --- | --- |
| Size per leg | The market's `min_order_size` (expected 5), never above 20. |
| Quote | The RE-1 two-leg post-only GTD BUY shape, at offset d = 5 c from the mid, snapped outward. The offset makes a fill unlikely; a fill is allowed, ends the sub-run and counts in L. |
| Relaxed limit | Only the reward-terms check (rate/min size) is skipped in `session0` mode. Every other RE-1 hard limit and the L rule apply unchanged. |
| Worst case | At most 2 × 20 × 0.80 = 32 pUSD in L. Expected ≤ 8 pUSD at size 5. |
| Duration | Sub-runs 0a–0e, each started by the owner, ≈ 60 min in total. Sub-run 0a has a fixed 20-min end; 0b–0d are each ≤ 10 min; 0e is < 2 min. |
| Attendance | The owner is present, because the owner causes 0b and 0c. The pass criteria are judged only by the commands below. |
| Status | Not counted in `c_at`, `c_thr`, `q_ahead`, any markout or `f̂`. It is not one of the 8 sessions. It adds no panel exclusion. |

## 4. Sub-runs (each is one owner-started run)

| Run | What it does | Expected end reason |
| --- | --- | --- |
| 0a — fixed end | The script posts both legs, rests 20 min, then ends on schedule. | `fixed_end` |
| 0b — foreign order | Two parts. **Pre:** the owner places one small post-only BUY far from the mid on the session-0 market *before* start, and preflight must refuse. **Run:** with no foreign order, the script posts; the owner then places the same foreign order, and the script must end. `cancel_all` is account-wide, so it cancels the owner's test order too. That is expected. | pre: preflight refusal; run: `foreign_open_order` |
| 0c — crash | While both legs rest, the owner runs `taskkill /F /PID <script pid>`. atexit does not run, and venue cancel-on-disconnect must clear the orders. | (none, process killed) |
| 0d — heartbeat drop | A session-0-only test flag stops heartbeat sends 120 s after posting while the main loop stays alive. The venue must cancel, and the script must end and clean up. | `order_no_longer_resting` or heartbeat stale |
| 0e — L refusal | A session-0-only test flag sets the L budget below the reserve of the selected quote. The script must refuse before any submit. | `l_budget_refused` |

An optional 0f (main-loop stall) is included if the code branch has a
stall flag. A forced 20 s main-loop stall must stop heartbeats. Pass
criteria are as in 0d.

## 5. Pass criteria and verify commands

Run from the repository root on the session host. Set
`$python = ".\venv\Scripts\python.exe"`. The wallet-reader commands exist on
master (see [wallet reader](../operations/wallet-reader.md)). The campaign CLI
and its `session0` flags are built by pre-registration P4 and do not exist
yet. Their names may change in the code branch, and this file is amended by
clarification if they do.

**Open-order count helper** (prints the number of open orders, or `ERR`):

```powershell
& $python -m weather.market.wallet_reader_client open-orders |
  & $python -c "import json,sys; v=json.load(sys.stdin); print('ERR' if isinstance(v,dict) and 'error' in v else len(v if isinstance(v,list) else next((x for x in v.values() if isinstance(x,list)),[])))"
```

**Time-to-zero loop** (for 0c and 0d; start it at the kill or the drop):

```powershell
$t0 = Get-Date
do {
  $n = & $python -m weather.market.wallet_reader_client open-orders |
    & $python -c "import json,sys; v=json.load(sys.stdin); print(len(v if isinstance(v,list) else next((x for x in v.values() if isinstance(x,list)),[])))"
  if ($n -ne '0') { Start-Sleep -Seconds 2 }
} until ($n -eq '0' -or ((Get-Date) - $t0).TotalSeconds -gt 60)
"open=$n seconds=$([int]((Get-Date) - $t0).TotalSeconds)"
```

| # | Criterion | Check |
| --- | --- | --- |
| S0-1 | After every sub-run: zero open orders account-wide. | The helper prints `0`. |
| S0-2 | 0c and 0d: zero open orders within **20 s** of the kill or drop (10 s cancel-on-disconnect + 5 s buffer + reader latency). | The time-to-zero loop prints `open=0 seconds=<= 20`. |
| S0-3 | 0a, 0b, 0d and 0e: `session_end.json` exists, its end reason matches §4, its cleanup is clean, and there is no `PANIC` line. | Inspect `session0/<run>/session_end.json` and the console log. |
| S0-4 | 0b pre: preflight refuses with a foreign open order present, and the journal has no submit. | Campaign CLI `preflight` exit code non-zero; `journal.jsonl` has no submit record. |
| S0-5 | 0e: no submit at all, with the refusal reason recorded. | `journal.jsonl` has no submit record; `session_end.json` reason `l_budget_refused`. |
| S0-6 | L reconciles. Recomputed L from venue trades for our order IDs equals the `l_ledger.json` value to 0.01 pUSD, and only our order IDs are counted (the pre-existing positions are unchanged against the T − 40 min baseline). | `& $python -m weather.market.wallet_reader_client trades --since <session0 start epoch>`, compared with `l_ledger.json`; `positions` is diffed against the baseline. |
| S0-7 | Every order the script submitted was GTD with expiration ≤ run end + 60 s. | The journal submit records. |
| S0-8 | The notification arrived for each sub-run end, including 0c via the next-start reconcile, or its failure was recorded. | Owner confirms; `session_end.json` notification field. |

**Fail rule.** A failure of S0-1, S0-2 or S0-6 blocks session 1 until it
is fixed and that sub-run is repeated. A repeat is still session 0 and still
counts toward L. Other failures need a written fix before session 1.

## 6. Signature

- Owner: ______________________  Date (UTC): ____________
- Data seen at signature: ______ (expected: none)
