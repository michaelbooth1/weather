# LFC session 0: owner checklist (10-13 T-24h and 10-14 day-of)

One ordered list. Each step names the runbook section that holds the exact command and its success line:
`docs/research/live-fill-calibration-session0-runbook-2026-10-09.md` on `claude/live-fill-calibration-runbook-20261009`
at `8dbdd6759` or later. Times are EDT, with UTC in brackets. **OWNER ONLY** marks steps no agent may run under any
relay. Every `lfc_cli` step runs in your own interactive PowerShell window: `preflight`, `live` and `session0-attest`
refuse without a real terminal.

Fixed dates (owner, 2026-10-12 19:35 EDT): session 0 on **Tue 10-14 from 11:00 EDT (15:00Z)**. Hard stop **19:50 EDT
(23:50Z)**. Code deadline **20:00 EDT 10-14 (10-15 00:00Z)**. There is no fallback day. Session 1: 10-15 afternoon or
10-18 and later, never 10-16 or 10-17.

## Before 10-13 11:00 EDT

| # | When (EDT) | Who | Step | Runbook |
| --- | --- | --- | --- | --- |
| A1 | 10-13 morning | master-agent | Sends the full sha of master after the N8 merge (the wallet-reader commit). | §3.6 step 2.1 |
| A2 | 10-13, before 10:30 | **OWNER ONLY** | Restart the 8765 wallet reader on that sha: detached reader worktree, unregister the old task, register with `-WhatIf` and then for real, start it. It briefly interrupts the capture host's reads, so you pick the minute. | §3.6 steps 1-2 |
| A3 | right after A2 | **OWNER ONLY** | Write the client config in the pinned worktree. You type the token. Confirm `check-ignore` names `.gitignore` and `status` prints nothing. Never upload it anywhere. | §3.6 step 3 |
| A4 | right after A3 | **OWNER ONLY** | Open windows A and B and paste the §2 setup block plus the helpers into each. Paste the owner-inputs block into window A (the five slugs are unchanged; see "Events" below). Leave `$extra` as a placeholder until D3. | §2 |
| A5 | right after A4 | owner | Run the §3.1 code-and-lock check, the §3.2 imports check and the §3.3 host-assignment check. The workstation agent already saw all three pass on 10-12 at about 19:45 EDT; you rerun them in your own window. | §3.1-3.3 |
| A6 | right after A5 | **OWNER ONLY** | Reader up: a listener on `<ws ip>:8765`, `/health` answers, and `Get-OpenOrderCount` prints `0`. | §3.6 step 4 |

## 10-13 T-24h, about 11:00 EDT (15:00Z)

| # | When (EDT) | Who | Step | Runbook |
| --- | --- | --- | --- | --- |
| B1 | 11:00 | owner | `init-ledger`, **once**. Expect `status: CREATED`, with the ledger under `$root`. | §3.7 |
| B2 | right after B1 | **OWNER ONLY** | `Save-OwnerSnapshot t24`, then `baseline --label t24`. This is a record only; session 0 does not use t24. | §4 |
| B3 | 10-13 to 10-14 10:20 | owner | **Superseded (owner, 10-13 ~10:40 EDT): the no-trade window opens at D5, not here.** You may trade until then. By 10:20 EDT 10-14: zero open orders; no holding in the five events or the two alternates; no position that could settle or redeem between 11:00 and 19:50 EDT. | decision log 2026-10-13 |
| B4 | any time 10-13 | owner | Check by eye: sleep set to Never on AC, toasts on, Focus assist off. | §3.5 |

## 10-14 day-of

| # | When (EDT) | Who | Step | Runbook |
| --- | --- | --- | --- | --- |
| C1 | 10:00 | all agents | **Heavy-work freeze on the workstation**: no qtest, pytest, compileall, replay or training until master reports session 0 done. | §3.4 step 1 |
| C2 | 10:00-10:15 | owner | Windows A and B: paste §2 again if they were closed, then rerun §3.1-3.3. | §2, §3.1-3.3 |
| D1 | 10:20 (14:20Z) | master-agent | T-40: master makes the byte-exact copy of the 88a `extra_conditions.json` on the capture host, records its sha256, and puts it in `C:\Users\micha\Desktop\lfc-transfer\`. | §2 `$extra` step 1 |
| D2 | 10:20 | **OWNER ONLY** | Move that file to `$env:USERPROFILE\.weather-lfc-20261009-inputs\` on the workstation (LAN share or USB). | §2 `$extra` step 2 |
| D3 | right after D2 | owner | Set `$extra` and `$extraHostSha` in window A and run the sha check. **A mismatch means no session.** Then rebuild `$s0` with the real path. | §2 `$extra` step 3 |
| D4 | right after D3 | owner | `shadow-scope-union --date 2026-10-14 --out $scope`. Expect exit 0; record the `sha256` line. If it fails closed (`shadow_scope_event_missing`), rerun a few minutes later. | §2 `$scope` |
| D5 | right after D4 | **OWNER ONLY** | `Save-OwnerSnapshot t40`. Re-confirm for 10-14: "pre-existing positions, pinned by baselines". **The no-trade window opens here** and closes at F2: no trade, cancel, redeem, merge, split, transfer, deposit or withdrawal, except the two 0b test orders. | §4, decision log 2026-10-13 |
| D6 | right after D5 | owner | `baseline --label t40` must show PASS with `open_orders: 0`. Then record the **`t40_start` line** (`Get-LatestT40Row`) and send it to master. | §4 |
| D6a | right after D6 | owner | Held-event check against the t40 baseline (block below). Every line must read `held=0`; a `held` above 0 on one of the five events means swap in an alternate that reads 0 and rebuild `$s0`. | below |
| D7 | right after D6 | owner | Reader up (§3.6 step 4) and `Test-HostFree` (MUTEX FREE). | §3.4, §3.6 |
| E1 | 11:00 (15:00Z) | owner | **0a**, the standard cycle: `Test-HostFree`, `Get-OpenOrderCount` = 0, `baseline --label t40`, `Compare-T40ToStart` = PASS, `preflight @s0 --run 0a` = PASS, then `live @s0 --run 0a`. Check the event and `neg_risk=False` on both tokens, type `go <6 hex>`, and wait the full 20 min. After the run: count = 0, `session_end.json`, the expiration check by eye (S0-7), `verify` = PASS. Record the run line. | §5, §6 0a |
| E2 | ~11:35 | owner + **OWNER ONLY UI orders** | **0b**. Pre-part: you place the foreign order (an off-panel market not in the list) and the count reads 1; `preflight --run 0b` must FAIL with `account_has_open_orders`; record its folder; you cancel the order and the count reads 0. Run part: `baseline t40`, a fresh `preflight` = PASS, `live`; once the count reads **2**, place the foreign order again. Expected end: `foreign_open_order`. | §6 0b |
| E3 | ~12:00 | owner | **0c** (binding S0-2): `live`, wait for count = 2, then no reader call. Find the process and run the one-paste `Wait-ReaderQuiet` + `taskkill` + `Measure-TimeToZero`. Record `kill_utc`, `helper_zero_utc` and seconds (20 or less). Then `Test-HostFree` (ABANDONED cleared), `reconcile`, `verify`. | §6 0c |
| E4 | ~12:30 | owner | **0d**: at the `go` prompt, run `Wait-ReaderQuiet 125` in window B first, then type `go`. One count read within 60 s of the post. Run the drop wait/measure block and record `DROP_WINDOW`. Expected end: `heartbeat_stale` or `order_no_longer_resting`. | §6 0d |
| E5 | ~12:50 | owner | **0e**: expected end `l_budget_refused`, with no submit and the count staying 0. | §6 0e |
| E6 | optional | owner | **0f**: only if time allows; same as 0d with `main_loop_stall`. | §6 0f |
| E7 | ~13:10 | owner, **MANUAL TRADING PAUSED** | **0g** (always last): from before `preflight --run 0g` until the result is read, place and cancel nothing anywhere. Run `Wait-ReaderQuiet 125` at `go`. Pass: `venue_deadman_cancelled`. `venue_deadman_not_observed` is a **permanent halt**. | §6 0g |
| F1 | after 0g | owner | `verify`, `wallet-verify`, then the final `baseline --label t40` and `Compare-T40ToStart` (PASS, otherwise STOP and report). | §7 |
| F2 | right after F1 | **OWNER ONLY** | `Save-OwnerSnapshot after-session0`. **The no-trade window closes here.** | §4, §7 |
| F3 | right after F2 | owner | `session0-attest --s0-2-seconds <S> --s0-2-helper-zero-utc <0c helper_zero_utc>`. Compute the gap first, then type `attest session0 <6 hex>`. Then `verify`. | §8 |
| F4 | right after F3 | owner | One message to master with the §8 "Send to master" list. Never send raw positions, balances, addresses or snapshot files. | §8 |
| F5 | 19:50 (23:50Z) | n/a | **Hard stop.** Any run that is not done by then is not done; session 0 cannot be run after 20:00 EDT. | §1 |
| G1 | later | **OWNER ONLY** | `Save-OwnerSnapshot after-settlement`, only if a session-0 order filled. | §4 |

## D6a held-event check (window A, counts only)

Reads your own latest t40 baseline and the public Gamma API. It prints counts, never assets or sizes.

```powershell
$r = Get-LatestT40Row; $f = Join-Path $root $r.file
if ((Get-FileHash -LiteralPath $f -Algorithm SHA256).Hash.ToLower() -ne $r.sha256) { 'STOP t40_sha_mismatch' }
$b = Get-Content -LiteralPath $f -Raw | ConvertFrom-Json; $held = @($b.position_conditions) + @($b.open_order_conditions | Where-Object { $_ })
"t40=$($r.file) open_orders=$(@($b.open_order_ids).Count)"
foreach ($s in 'netanyahu-out-before-2027', 'iran-oman-hormuz-management-agreement-byptptpt-20260804222725871',
               'china-x-philippines-military-clash-before-2027-20260723214807932', 'will-russia-capture-all-of-bilytske-by-june-30',
               'turkey-rejoins-f-35-program-byptptpt-20260708215709215',
               'houthis-enter-saudi-arabia-byptptpt', 'next-us-iran-senior-diplomatic-meeting-byptptpt') {
  $e = @(Invoke-RestMethod "https://gamma-api.polymarket.com/events?slug=$s")
  if (-not $e.Count) { "$s NOT_FOUND"; continue }
  $c = @($e[0].markets | ForEach-Object { "$($_.conditionId)".ToLower() })
  "$s held=$(@($c | Where-Object { $held -contains $_ }).Count) of $($c.Count)"
}
```

Expect `open_orders=0` and `held=0` on all seven lines (the last two are the alternates).

## Repeats and stops

- A run that fails its pass rule is repeated within the same day (§6). Repeats count in L.
- Any `Compare-T40ToStart` STOP means **stop session 0** and report the line to master.
- Anything that looks wrong while our orders may rest: Ctrl+C, then `cancel-ours` and the §9 sequence (**OWNER ONLY**).
- Rough clock: about 3 h including checks. If you start at 11:00 EDT, 0g ends around 13:30. Repeats have until
  19:50 EDT.

## Events (re-checked 10-12 about 19:45 EDT, public Gamma and CLOB reads only)

All five listed events are open. Each has at least one market that passes the public-read rules: fee-free, tick 0.01,
min size 5, ends 10-21 or later, two-sided book, mid inside 0.20-0.80, legs inside 0.17-0.80. **No swap is needed.**
The two alternates are open too, and each has passing markets. The off-panel, 88a and shadow-scope exclusions cannot be
checked by an agent (read clearance); `preflight` applies them. The books will move by 10-14, so the selector's choice
at preflight is the one that counts.
