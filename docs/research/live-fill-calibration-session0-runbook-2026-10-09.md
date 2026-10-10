# Live Fill-Calibration Session-0 Runbook (owner-attended)

Owns: the copy-pasteable owner procedure for session 0 of the live
fill-calibration campaign on the workstation. Read when: preparing for or
running session 0, or reviewing what the owner will do.

- **Not a signed text.** This runbook adds no rule. Where it differs from a
  signed file, the signed file governs; section 11 lists every difference found
  against the code, and the draft
  [clarification D](live-fill-calibration-clarification-D-2026-10-09.md)
  carries the ones that need a signature.
- Rules it follows, at the hashes in the
  [signature record](live-fill-calibration-signature-2026-10-09.md) and the
  [C signature record](live-fill-calibration-clarification-C-signature-2026-10-09.md):
  pre-registration (PR), session-0 spec (S0), panel clarifications,
  clarification A/2, and clarification C (sha256
  `4d6ae37a4f2cb6a098ef709dd0148b9babba6e465c3d202dff2ab4242d369054`).
- Code: the pinned worktree `C:\wt\lfc-pinned-acd052a2d` at the final session-0 tip `acd052a2d`
  (`acd052a2d0c38e701e951f7e5efd53d0a7e11781`, branch `claude/lfc-pinned-ext-20261009`; it replaces
  `6c45aaa14`). The main session creates and locks it after the Fable delta-3
  review over `468607b13..acd052a2d` (section 3.0). Every command below was
  checked against the CLI at that commit (`python -m weather.market.lfc_cli
  --help` and the source). Commands that touch the venue or the wallet reader
  were **not** run while drafting.
- Data seen while drafting: none. No 88a, panel or settlement data, and no
  session-0 artefact.

**Who runs what.** Every command in this file is run by the owner, in an
interactive PowerShell window on the workstation. `preflight`, `live` and
`session0-attest` refuse without a real terminal (`owner_terminal_required`),
so no agent can run them. Steps marked **OWNER ONLY** are never run by an agent
under any relay.

## 1. Timing

| Item | Rule | Source |
| --- | --- | --- |
| Session 0 date | **UTC 2026-10-12, starting about 15:00Z** (owner-confirmed 2026-10-09 evening, D9). | owner, D9 |
| Session 0 deadline | Before 2026-10-15T00:00Z. **Enforced:** `preflight` and `live` with `--session0` refuse `session0_deadline_passed` at or after that instant. | S0 §1, D10, `SESSION0_DEADLINE_UTC` |
| One UTC date | Run every sub-run on one UTC date. `live` accepts only a PASS preflight from the same UTC date and commit. | code (`clean_preflight`) |
| Hard stop | Each run's start + duration must end by 23:50Z (0a = 20 min, others = 10 min), else `past_hard_stop_2350z`. | PR §4, code |
| Plan for 10-12 | T − 24 h steps on 10-11 about 15:00Z; T − 40 min steps (including the shadow scope, section 2) about 14:20Z on 10-12; first preflight about 15:00Z (11:00 Toronto, EDT). Total ≈ 3 h with checks; 10-13 and 10-14 are the fallback days. | this runbook |
| Earliest counted session | 2026-10-15, owner's local afternoon, e.g. 17:00Z. The code's own floor is 2026-10-15T00:00Z (session 0 is exempt). | PR §4, `EARLIEST_START_UTC` |
| Markets | Session 0 uses **non-panel markets only**: the owner lists ≥ 3 off-panel events, and the selector refuses any condition in the 88a extra conditions, the shadow scope or `panel_exclusions.jsonl`. | S0 §2, C2 |

## 2. Shell setup (every new window)

Open Windows PowerShell (not an agent tool). Paste this into **each** window
you use; window A runs `live`, window B runs the helpers.

```powershell
Set-Location C:\wt\lfc-pinned-acd052a2d
$python = 'C:\Users\Michael\Documents\github\weather\venv\Scripts\python.exe'
$env:PYTHONPATH = 'C:\wt\lfc-pinned-acd052a2d;C:\wt\lfc-pinned-acd052a2d\src'
$env:PYTHONDONTWRITEBYTECODE = '1'
$root = Join-Path $env:USERPROFILE '.weather-lfc-20261009'
$snapDir = Join-Path $env:USERPROFILE '.weather-lfc-20261009-owner-snapshots'

# Open-order count helper (S0 §5): ONE fresh venue read through GET /open-orders?fresh=1
# (wallet_reader_client.open_order_count(fresh=True); no 30 s cache). Prints the count, or ERR <reason>.
# Every call counts in the reader's 30-per-60 s cap, shared with the capture host's 5-minute journal.
function Get-OpenOrderCount {
  & $python -c "import weather.market.wallet_reader_client as c`ntry:`n print(c.open_order_count())`nexcept c.ReaderError as e:`n print('ERR', getattr(e, 'reason', 'refused'))"
}

# Time-to-zero (S0 §5, D6) with the UTC time the helper read 0 (N-10): a fresh read every 3 s from t0
# until it reads 0 or 21 s have passed (at most 8 fresh reads, inside the cap). ERR never counts as 0.
function Measure-TimeToZero([datetime]$t0) {
  do {
    $next = (Get-Date).ToUniversalTime().AddSeconds(3)
    $n = "$(Get-OpenOrderCount)".Trim()
    $at = (Get-Date).ToUniversalTime()
    if ($n -ne '0' -and ($at - $t0).TotalSeconds -le 21) {
      $wait = ($next - (Get-Date).ToUniversalTime()).TotalMilliseconds
      if ($wait -gt 0) { Start-Sleep -Milliseconds ([int]$wait) }
    }
  } until ($n -eq '0' -or ($at - $t0).TotalSeconds -gt 21)
  "open=$n seconds=$([math]::Ceiling(($at - $t0).TotalSeconds)) t0_utc=$($t0.ToString("yyyy-MM-dd'T'HH:mm:ss.fff'Z'")) helper_zero_utc=$($at.ToString("yyyy-MM-dd'T'HH:mm:ss.fff'Z'"))"
}

# Host gate: run before every preflight and every live start.
function Test-HostFree {
  . .\scripts\ops\workload_admission.ps1
  "holder=" + (Get-WeatherHeavyWorkloadHolderSummary -RepoRoot (Get-Location).Path | ConvertTo-Json -Compress)
  "poison=" + (Test-Path 'C:\ProgramData\WeatherProject\heavy_workload_v1.poison')
  "queued=" + @(Get-ChildItem 'C:\ProgramData\WeatherProject\heavy_workload_queue_v1' -Filter 'ticket-*.json' -ErrorAction SilentlyContinue).Count
  $m = [Threading.Mutex]::new($false, 'Global\WeatherProjectHeavyWorkloadV1')
  try { if ($m.WaitOne(0)) { $m.ReleaseMutex(); 'MUTEX FREE' } else { 'MUTEX BUSY' } }
  catch [Threading.AbandonedMutexException] { $m.ReleaseMutex(); 'MUTEX WAS ABANDONED (now cleared)' }
  finally { $m.Dispose() }
}

# Owner-private wallet snapshot: raw reader output stays on this machine; only hashes are shared.
function Save-OwnerSnapshot([string]$label) {
  New-Item -ItemType Directory -Force $snapDir | Out-Null
  $ts = (Get-Date).ToUniversalTime().ToString("yyyyMMdd'T'HHmmss'Z'")
  foreach ($r in 'summary', 'open-orders', 'positions') {
    $f = Join-Path $snapDir "$label-$r-$ts.json"
    & $python -m weather.market.wallet_reader_client $r | Out-File -Encoding utf8 $f
    '{0}  {1}' -f (Get-FileHash -Algorithm SHA256 $f).Hash.ToLower(), (Split-Path $f -Leaf)
  }
}
```

**Owner inputs** (window A only; fill in before section 5). The five events
are the proposed session-0 list (all plain binary, fee-free, non-weather; the
pinned selector picked the Netanyahu market in 3 of 3 checks on 10-10 about
00:40Z). Paste as is:

```powershell
$ev1 = 'netanyahu-out-before-2027'
$ev2 = 'iran-oman-hormuz-management-agreement-byptptpt-20260804222725871'
$ev3 = 'china-x-philippines-military-clash-before-2027-20260723214807932'
$ev4 = 'will-russia-capture-all-of-bilytske-by-june-30'
$ev5 = 'turkey-rejoins-f-35-program-byptptpt-20260708215709215'
# Alternates (swap one in only if an event above is closed or refused):
#   'houthis-enter-saudi-arabia-byptptpt'   'next-us-iran-senior-diplomatic-meeting-byptptpt'
$extra = '<prod checkout>\data\maker_evidence\extra_conditions.json'
$scope = Join-Path $env:USERPROFILE '.weather-lfc-20261009-inputs\shadow_scope_20261012.json'
$s0 = @('--session0', '--event-slug', $ev1, '--event-slug', $ev2, '--event-slug', $ev3,
        '--event-slug', $ev4, '--event-slug', $ev5, '--extra-conditions', $extra, '--shadow-scope', $scope)
```

- At least **3 distinct** slugs (case-insensitive), else
  `session0_requires_three_candidate_events`. Slugs must match the Gamma event
  slug exactly, else `session0_event_unreadable`.
- `--extra-conditions` and `--shadow-scope` are both required with
  `--session0` (`session0_requires_event_slug_extra_conditions_shadow_scope`).
  Agents may not read either file (read clearance).
- **`$extra`** is the 88a file in force,
  `<prod checkout>\data\maker_evidence\extra_conditions.json` (the production
  checkout, `C:\Users\micha\Desktop\github\weather` on the capture host),
  passed **as is**: the code accepts its
  `{"extra_conditions": [...], "update_windows_utc": [...]}` shape. If the
  session runs on the workstation, set `$extra` to a byte-identical copy and
  check that `Get-FileHash` matches on both hosts.
- **`$scope`** is generated at **T − 40 min** (about 14:20Z on 10-12) and its
  sha256 recorded:

  ```powershell
  New-Item -ItemType Directory -Force (Split-Path $scope) | Out-Null
  & $python -m weather.market.lfc_cli shadow-scope-union --date 2026-10-12 --out $scope
  ```

  Success: exit 0, printing `sha256` and `count`; record the sha256 line. It
  reads public Gamma only and **fails closed** (`shadow_scope_event_missing`,
  nothing written) until every registry event dated 10-11 to 10-14 (D−1 to
  D+2) is listed; rerun later if so. An existing `--out` is refused.
- `go <6 hex>` is typed by the owner at each `live` start; it is the first 6 hex
  of the selection digest that `live` prints. Check S0 rules 1-2 by eye on the
  printed `event_slug` and `condition` before typing.

## 3. Pre-flight (once, then the gate before each run)

### 3.0 Pinned worktree (created by the main session after review)

The main session creates the new locked, detached worktree once the Fable
delta-3 review over `468607b13..acd052a2d` passes. The old
`C:\wt\lfc-pinned-6c45aaa14` stays as it is.

```powershell
git -C C:\Users\Michael\Documents\github\weather fetch origin claude/lfc-pinned-ext-20261009
git -C C:\Users\Michael\Documents\github\weather worktree add --detach C:\wt\lfc-pinned-acd052a2d acd052a2d0c38e701e951f7e5efd53d0a7e11781
git -C C:\Users\Michael\Documents\github\weather worktree lock --reason "LFC session-0 pinned tip acd052a2d (owner-approved 2026-10-09; delta-3 reviewed)" C:\wt\lfc-pinned-acd052a2d
```

### 3.1 Pinned code and lock (window A)

```powershell
git -C C:\wt\lfc-pinned-acd052a2d rev-parse HEAD
git -C C:\wt\lfc-pinned-acd052a2d status --porcelain --untracked-files=normal
git -C C:\Users\Michael\Documents\github\weather worktree list --porcelain | Select-String -Context 0,4 'lfc-pinned-acd052a2d'
```

Success: HEAD `acd052a2d0c38e701e951f7e5efd53d0a7e11781`; status prints nothing (the code refuses on any
untracked or modified file); the worktree entry shows
`locked LFC session-0 pinned tip acd052a2d ...`. Anything else: **stop**.

### 3.2 Interpreter and imports

```powershell
& $python -c "import sys, weather, weather.paths, weather.market.lfc_cli as c; print(sys.version.split()[0]); print(weather.__file__); print(c.__file__); print(weather.paths.REPO_ROOT)"
& $python -c "import importlib.metadata as m; print(m.version('polymarket-client'))"
& $python -c "import sys, weather.market.lfc_cli, weather.market.re1_evidence, weather.market.re1_owner_checks, weather.market.re1_rehearsal, weather.market.re1_transport, weather.market.wallet_reader_client; print('econ_loaded=' + str('weather.market.exchange_economics' in sys.modules))"
```

Success, exactly:
- `3.11.9`;
- `C:\wt\lfc-pinned-acd052a2d\weather\__init__.py`;
- `C:\wt\lfc-pinned-acd052a2d\src\weather\market\lfc_cli.py`;
- `C:\wt\lfc-pinned-acd052a2d`;
- `0.6.0`;
- `econ_loaded=False` (P2 scan).

If any path points at `C:\Users\Michael\Documents\github\weather`, the
`PYTHONPATH` or working directory is wrong: **stop**. The venv's editable
install points at the main checkout; only the setup block above makes the
pinned code load.

### 3.3 Host assignment

```powershell
. .\scripts\ops\workload_admission.ps1
$a = Get-Content .\config\international_live_execution_host.json -Raw | ConvertFrom-Json
$h = Get-WeatherExecutionHostId; $p = Get-WeatherExecutionPrincipalId
"status=$($a.assignment_status) host_match=$($h -eq $a.active_portable_execution_host_id) principal_match=$($p -eq $a.active_portable_execution_principal_id) not_capture=$($h -ne $a.dedicated_capture_execution_host_id)"
```

Success: `status=ASSIGNED host_match=True principal_match=True not_capture=True`
(else `live` refuses `wrong_workstation_or_principal`).

### 3.4 Heavy-work mutex: freeze, then check before every run (settled)

Settled by master-agent and the owner 2026-10-09: freeze plus a check before
each run replaces "hold the mutex for the session".

`preflight` and `live` take the host mutex `Global\WeatherProjectHeavyWorkloadV1`
**themselves**, without waiting, and refuse `host_mutex_busy_or_abandoned` if it
is held or abandoned, or `host_workload_recovery_required` if the poison file
exists. **Do not hold the mutex from another window**: that makes every run
refuse. "Holding it for the session" means:

1. Tell the master and every workstation agent session: **no qtest, pytest,
   compileall, replay or training on this machine until session 0 is reported
   done.** Wait for any running job to finish.
2. Before every `preflight` and every `live`, in window B:

   ```powershell
   Test-HostFree
   ```

   Success: `holder=null` (or an empty holder), `poison=False`, `queued=0`,
   `MUTEX FREE` (or `MUTEX WAS ABANDONED (now cleared)` right after 0c).
3. `poison=True` with no holder is an interrupted heavy job. **Do not delete the
   file by hand**; recovery is owned by the
   [host load policy](../operations/HOST_LOAD_POLICY.md). Stop session 0 for the
   day if it cannot be recovered.

### 3.5 Machine

- Sleep off while attending (Settings > System > Power: screen and sleep
  "Never" on AC). Owner checks by eye.
- Notifications on for PowerShell/Windows toasts (Focus assist off). The toast
  is checked by hand at each run end (S0-8).

### 3.6 Wallet reader for the workstation — OWNER ONLY, after the owner's direct yes

**Design** (owner decision 2026-10-09 ~20:45): one reader instance, the
existing one on port 8765, accepts any PC on the LAN as a caller. The pinned
tip carries that code (`b818d187c`, cherry-picked as `388043de5`): `serve`
admits any RFC1918 or loopback IPv4 source, `--allow` is optional, and
`GET /open-orders?fresh=1` is the no-cache read the S0 §5 helper uses. There
is **no second instance**.

- The reader server runs on this workstation, with the L2 credentials and the
  reader token from the common checkout's `.env`. The capture host is also its
  client.
- The bind stays a literal RFC1918 address (never loopback), so the
  workstation's own client URL is `http://<workstation LAN IP>:8765`, never
  127.0.0.1.

No agent runs these steps, opens `.env`, or opens the client file. Owner rule,
verbatim: "we must NEVER upload credentials to github". The file is under the
gitignored `config/local/`.

1. Find the workstation LAN IPv4:

   ```powershell
   Get-NetIPAddress -AddressFamily IPv4 | Where-Object { $_.IPAddress -match '^(10\.|192\.168\.|172\.(1[6-9]|2\d|3[01])\.)' } | Select-Object IPAddress, InterfaceAlias
   ```

2. **Restart the reader on the any-LAN code** (elevated PowerShell at the main
   checkout; the owner picks the time, since it briefly interrupts the capture
   host's reads). Steps from the any-LAN handback and the
   [wallet reader](../operations/wallet-reader.md) "Restart serve after
   updating":
   1. Create a detached reader worktree at the reviewed commit that contains
      `b818d187c`: `origin/master` once the any-LAN branch is merged, else the
      pinned tip `acd052a2d0c38e701e951f7e5efd53d0a7e11781` after the delta-3 review:
      `git worktree add --detach ..\weather-wallet-reader-<sha8> <sha>`. Set
      `$wt` to it and `$sha` to the full SHA.
   2. `& "<old reader worktree>\scripts\ops\register_wallet_reader_logon_task.ps1" -Unregister`.
      This also stops the reader. Confirm
      `Get-NetTCPConnection -LocalPort 8765 -State Listen` is empty.
   3. `& "$wt\scripts\ops\register_wallet_reader_logon_task.ps1" -RepoRoot $wt -ExpectedCommit $sha -Bind <ws LAN IP> -SignatureType <2|3> -WhatIf`,
      then the same without `-WhatIf`. **No `-AllowIp`** (any-LAN).
   4. `Start-ScheduledTask -TaskName WeatherWalletReader`.
   5. Check `wallet_reader_client summary` from the capture host and from the
      workstation (step 4 below). Keep the existing firewall rule: the
      workstation's own calls are same-machine traffic, and the rule still
      blocks other remote PCs. Keep the old reader worktree and its
      `data\wallet_reader\` journal (account-read evidence).

3. Write the client config (window A). The token is the same reader token the
   capture host's client uses (`.env` field `POLYMM_READER_TOKEN`); the owner
   types it.

   ```powershell
   # OWNER ONLY. <ws ip> = the address from step 1. The token never appears in any shared output.
   New-Item -ItemType Directory -Force C:\wt\lfc-pinned-acd052a2d\config\local | Out-Null
   $tok = Read-Host 'reader token (64 hex)'
   [IO.File]::WriteAllText('C:\wt\lfc-pinned-acd052a2d\config\local\wallet_reader_client.json', (@{ url = 'http://<ws ip>:8765'; token = $tok } | ConvertTo-Json -Compress))
   Remove-Variable tok
   git -C C:\wt\lfc-pinned-acd052a2d check-ignore -v config/local/wallet_reader_client.json
   git -C C:\wt\lfc-pinned-acd052a2d status --porcelain --untracked-files=normal
   ```

   Success: `check-ignore` names `.gitignore` (`config/local/`); status still
   prints nothing (else `live` refuses on code identity).

4. **Reader up** — part of the T − 40 min pre-flight, and again before each
   run (owner-run only):

   ```powershell
   Get-NetTCPConnection -LocalPort 8765 -State Listen | Select-Object LocalAddress, LocalPort, OwningProcess
   $c = Get-Content C:\wt\lfc-pinned-acd052a2d\config\local\wallet_reader_client.json -Raw | ConvertFrom-Json
   Invoke-RestMethod -Uri ($c.url.TrimEnd('/') + '/health') -Headers @{ Authorization = 'Bearer ' + $c.token }; Remove-Variable c
   Get-OpenOrderCount
   ```

   Success: a listener on `<ws ip>:8765`; `/health` answers through the LFC
   client config (it proves the server responds, not venue access; the client
   module has no `health` command, hence the direct request); and
   `Get-OpenOrderCount` prints a number (expected `0`). `ERR http_403`,
   `ERR http_400` or `ERR refused` means the reader still runs the old
   one-IP code: do step 2 first.

**Limits of the reader:**
- One cap of 30 upstream attempts per 60 s for the whole server, **shared
  with the capture host's 5-minute journal reads**. Every `Get-OpenOrderCount`
  is a fresh read and counts. Keep LFC reads to the plan in this runbook; the
  time-to-zero loop makes at most 8.
- Cached routes (`summary`, `positions`, plain `open-orders`) keep the 30 s
  success cache (failures 10 s). The fresh read bypasses it and refreshes it.
- **Plain HTTP** carries the token and account data unencrypted on the LAN;
  that is the owner's accepted scope (wallet-reader doc).

### 3.7 Ledger (once, at the first step of T − 24 h)

```powershell
& $python -m weather.market.lfc_cli init-ledger
```

Success: `status: CREATED`, `ledger: <...>\.weather-lfc-20261009\ledger.jsonl`.
Confirm that path equals `$root`. Run it once only; the ledger spans the whole
campaign (L ≤ 100 pUSD, session 0 included).

## 4. Wallet snapshots and the no-trade window

Owner statement (relayed 2026-10-09 ~20:35), verbatim: "Just snapshot my wallet
before and after the run, you don't need to know any before or after. I will
not trade during that window."

| When | Command | Purpose |
| --- | --- | --- |
| T − 24 h (10-11, ~15:00Z) | `Save-OwnerSnapshot t24` then `& $python -m weather.market.lfc_cli baseline --label t24` | record only; session 0 does not use t24 |
| T − 40 min (10-12, ~14:20Z, before 0a) | `Save-OwnerSnapshot t40`, then `shadow-scope-union` (section 2) | owner-private before-snapshot; the `$scope` file and its sha256 |
| before **each** sub-run (≤ 90 min before its start) | `& $python -m weather.market.lfc_cli baseline --label t40` | ledger-bound baseline the start checks |
| after the last sub-run | `Save-OwnerSnapshot after-session0` | owner-private after-snapshot |
| after settlement of any session-0 lot | `Save-OwnerSnapshot after-settlement` | **only if a session-0 order filled**; if nothing filled, the end-of-session snapshot suffices (owner, 2026-10-09 evening; D9) |

- **No-trade window:** from the T − 24 h snapshot to the last snapshot, the
  owner places no manual order and cancels nothing, except the two 0b test
  orders this runbook asks for (section 6, 0b), and nothing at all during 0g.
- **Owner approvals, 2026-10-09 evening** (relayed by master-agent; draft D9):
  "I hold no positions, 10-12 confirmed"; no after-settlement snapshot if
  nothing filled; and the two 0b test orders (the foreign order on a market
  outside the session, per C6) may be placed inside the no-trade window as
  part of the test.
- S0-6 and L are judged **only** against our order IDs and the baselines.
  Nothing outside the window is reconciled, and the agents never need the
  owner's activity outside it.
- `baseline` success: `status: PASS`, `open_orders: 0`. It exits 1 with
  `FAIL_FOREIGN_OPEN_ORDERS` if any order is open; that snapshot is still
  recorded, and the next start refuses `baseline_foreign_open_orders` until a
  clean `baseline --label t40` is taken.
- A position change outside our tokens since the latest t40 makes `live`
  refuse `wallet_activity_outside_pilot`.
- Share only the printed SHA-256 lines of `Save-OwnerSnapshot`, never the
  files.

## 5. The per-run cycle

Every sub-run R uses this cycle unless section 6 says otherwise.

```powershell
# window B
Test-HostFree                                             # MUTEX FREE, before every preflight and live
Get-NetTCPConnection -LocalPort 8765 -State Listen        # reader up (section 3.6)
Get-OpenOrderCount                                        # fresh read; must print 0
# window A
& $python -m weather.market.lfc_cli baseline --label t40  # retaken before EVERY sub-run: PASS, open_orders 0
& $python -m weather.market.lfc_cli preflight @s0 --run R # replace R; a fresh PASS before every live
```

`preflight` success: it prints `open_sessions: []`, `unresolved_legs: []` and
`stop_reason: null`, then `PASS` steps, and its summary ends `status: PASS`.
The receipt is `$root\preflight-<UTC stamp>\preflight.json`.

```powershell
# window A, only after a PASS preflight
& $python -m weather.market.lfc_cli live @s0 --run R
```

- It prints the selection (condition, `event_slug`, quote, size, run,
  minutes, L figures, `available_collateral`) and `Type: go <6 hex>`.
- Check the event is one of your listed off-panel events, then type the phrase
  exactly. A wrong phrase refuses with nothing posted.
- The run then needs no input. It ends with an `LFC-RESULT ...` line and a
  toast.
- Outputs: `$root\session0\<R>\` for the first run of R, or
  `$root\session0\<R>-<session id>\` for a repeat: `attempt.json`,
  `selection.json`, `journal.jsonl`, `submit-N.intent.json`,
  `submit-N.ack.json` and `session_end.json`. Ledger rows go to
  `$root\ledger.jsonl`, `$root\l_ledger.json` and `$root\notifications.jsonl`.

After every run (window B, then A):

```powershell
Get-OpenOrderCount                                        # S0-1 (fresh read): must print 0
$dir = Get-ChildItem "$root\session0" -Directory | Sort-Object LastWriteTime | Select-Object -Last 1
Get-Content "$($dir.FullName)\session_end.json"            # reason, cleanup_ok, panic, L, open_orders, fills
Get-Content "$($dir.FullName)\journal.jsonl" | Select-String '"submit_request"' | ForEach-Object { ($_.Line | ConvertFrom-Json).request | Select-Object token_id, side, size, price, post_only, expiration }
& $python -m weather.market.lfc_cli verify
```

- S0-3: `reason` as in the table below, `cleanup_ok: true`, no `PANIC` line in
  window A.
- S0-7 (**manual**, settled 2026-10-09): the owner checks by eye that every
  `expiration` equals the session start + run duration + 60 s (one value per
  run). No code check exists.
- `verify`: `our_open_orders: []`, `foreign_open_orders: []`, no open
  session, `status: PASS`.

**Record for each run:** run, folder name, session id (`S0<run>-<UTC stamp>`),
the `LFC-RESULT` line, end reason, `cleanup_ok`, the helper count after the
run, whether the toast arrived, and any refusal code.

## 6. Run order and run specifics

The code does not enforce an order. Run **0a, 0b, 0c, 0d, 0e, (0f), 0g** —
0g last, because its failure halts the campaign for good.

| Run | Length | Accepted end reason | Pass needs |
| --- | --- | --- | --- |
| 0a | 20 min fixed | `fixed_end` | band posted (2 legs, 2 tokens, order IDs) |
| 0b | ≤ 10 min | `foreign_open_order` | band posted before the foreign order |
| 0c | ≤ 10 min | `reconciled_after_crash` (via `reconcile`) | band posted; S0-2 ≤ 20 s |
| 0d | ≤ 10 min | `heartbeat_stale` or `order_no_longer_resting` | band posted |
| 0e | < 2 min | `l_budget_refused` | no leg intent recorded, no submit |
| 0f | optional | — (not part of the pass gate) | — |
| 0g | ≤ 10 min | `venue_deadman_cancelled` | band posted; no cancel from us after the drop |

Every pass also needs `cleanup_ok: true` and an uncounted ledger session.

### 0a — fixed end

Standard cycle. Wait the full 20 min. Pass: `fixed_end`.

### 0b — foreign order (two parts)

The foreign order goes on a token **outside the session** (C6): any
International Polymarket market that is off every panel and not one of the
three listed candidate events. It is a small limit BUY at the market minimum
size, far below the mid so it cannot fill.

**Pre-part (S0-4):**
1. Window B: `Test-HostFree`, `Get-OpenOrderCount` → `0`.
2. Owner places the foreign order in the Polymarket UI. `Get-OpenOrderCount`
   → `1`.
3. Window A: `& $python -m weather.market.lfc_cli preflight @s0 --run 0b`.
   Success: it **fails** with `account_has_open_orders` and a non-zero exit;
   `status: FAIL`. Record the `preflight-<stamp>` folder. No submit exists
   (preflight never submits).
4. Owner cancels that order in the UI. `Get-OpenOrderCount` → `0`.

**Run part:**
5. `Test-HostFree`, `baseline --label t40` → PASS. Then a **fresh**
   `preflight @s0 --run 0b` → must be **PASS** (settled 2026-10-09). The failed
   receipt from step 3 is now the latest one, and `live` accepts only the
   latest receipt.
6. `live @s0 --run 0b`, type `go <6 hex>`.
7. Window B: repeat `Get-OpenOrderCount` until it prints `2` (both legs rest,
   N-1). Only then place the same foreign order again.
8. The script must end `foreign_open_order` within about 30 s. Its cleanup
   cancels account-wide, so it also cancels the owner's foreign order; that is
   expected.

Halt: a 0b that ends `foreign_open_order` before the helper read `2` does not
pass; repeat it. If the foreign order fills, stop: S0-6 fails and the next
start refuses `wallet_activity_outside_pilot`.

### 0c — crash (binding S0-2)

1. Standard cycle up to `live @s0 --run 0c` and `go <6 hex>`.
2. Window B: wait until `Get-OpenOrderCount` prints `2` (each call is a fresh
   read; a few seconds apart is enough). Then find the process:

   ```powershell
   $ps = @(Get-CimInstance Win32_Process -Filter "Name='python.exe'" | Where-Object { $_.CommandLine -match 'weather\.market\.lfc_cli\s+live' })
   $top = @($ps | Where-Object { $ps.ProcessId -notcontains $_.ParentProcessId })
   $ps | Format-Table ProcessId, ParentProcessId, ExecutablePath -AutoSize
   $top.Count   # must be 1 (the venv launcher; its child is the interpreter)
   ```

3. Kill and measure in **one** paste:

   ```powershell
   $t0 = (Get-Date).ToUniversalTime(); taskkill /F /T /PID $top[0].ProcessId; "kill_utc=$($t0.ToString("yyyy-MM-dd'T'HH:mm:ss.fff'Z'"))"; Measure-TimeToZero $t0
   ```

   `taskkill /F /T` (settled 2026-10-09) kills the launcher and its
   interpreter child. atexit does not run, and only the venue's dead-man can
   clear the orders. `Measure-TimeToZero` reads `GET /open-orders?fresh=1`
   at once and then every 3 s for up to 21 s; every read reaches the venue, so
   no wait before the kill is needed.
4. **Record:** `kill_utc`, the full `open=0 seconds=<s> ... helper_zero_utc=<T>`
   line. `helper_zero_utc` is the value for `--s0-2-helper-zero-utc` (N-10).
5. Window B: `Test-HostFree`. Expect `MUTEX WAS ABANDONED (now cleared)`
   (clearing the abandoned mutex is settled, 2026-10-09). Without this step the
   next `preflight` or `live` refuses once and writes a FAIL receipt.
6. Window A: `& $python -m weather.market.lfc_cli reconcile`. Success: exit 0,
   the 0c session id in `closed_sessions`, `our_open_orders: []`, no
   mismatches, no adoption refusals, no unacknowledged intents.
   `session_end.json` appears with `reconciled_after_crash`, and a toast
   (S0-8).
7. `verify` → PASS.

Halt and repeat: `open` is not `0` when the 21 s loop ends (or it prints
`ERR`), or `seconds` > 20, or the timestamp gap in section 8 exceeds 20 s. That is an S0-2 fail: run
`cancel-ours` (section 9) if any of our orders rest, then `reconcile`, and
repeat 0c. S0-2 measured on 0c is the gate for every unattended session.

### 0d — heartbeat drop

1. Standard cycle; `live @s0 --run 0d`.
2. Window B: read `Get-OpenOrderCount` → `2` once. Wait for the drop row
   (about 120 s after posting), then measure (fresh reads every 3 s):

   ```powershell
   $j = Join-Path (Get-ChildItem "$root\session0" -Directory | Sort-Object LastWriteTime | Select-Object -Last 1).FullName 'journal.jsonl'
   while (-not (Select-String -Path $j -SimpleMatch 'heartbeat_sends_stopped' -Quiet)) { Start-Sleep -Milliseconds 500 }
   Measure-TimeToZero (Get-Date).ToUniversalTime()
   ```

3. The script ends `heartbeat_stale` (its own 8 s stale cleanup) or
   `order_no_longer_resting` (the venue was first).
4. Evidence rows, in order:

   ```powershell
   Select-String -Path $j -Pattern 'heartbeat_sends_stopped|lfc_first_terminal_order_read|lfc_session0_safety_cancel|cleanup_cancel_response' | ForEach-Object Line
   ```

   `lfc_first_terminal_order_read` (taken before the cleanup cancel) tells a leg
   already terminal from one the script cancelled. `evidence_complete: false`
   on a REST-path end is expected (N-4).

S0-2 for 0d: `seconds` ≤ 20 from the drop. Fail: repeat 0d (blocks session 1).

### 0e — L refusal

Standard cycle; `live @s0 --run 0e`. The script sets the L budget just below
the quote's reserve and must refuse before any submit. Pass:
`l_budget_refused`, no `submit-*` file, no `submit_request` row, and no leg in
the ledger (S0-5). `Get-OpenOrderCount` stays `0` throughout.

### 0f — main-loop stall (optional)

Same as 0d, with `--run 0f`: the main loop stalls 25 s about 120 s after
posting, and the heartbeats must stop. It is not in the pass gate; skip it if
time is short.

### 0g — venue-only dead-man (last)

**MANUAL TRADING PAUSED.** From before `preflight @s0 --run 0g` until the 0g
result is read, the owner places no order and cancels nothing, in the UI or
anywhere else. An owner cancel would counterfeit the proof. Both
`preflight --run 0g` and the 0g `go` prompt print this rule.

1. Standard cycle with `--run 0g`.
2. Heartbeat sends stop 120 s after posting, and the script's own stale cleanup
   is off. Only the venue can cancel. The script reads our orders at the first
   control checkpoint ≥ 30 s after the drop.
3. Window B may run the 0d wait-and-measure block (reads only).
4. Evidence rows:

   ```powershell
   Select-String -Path $j -Pattern 'heartbeat_sends_stopped|lfc_venue_deadman_first_terminal|lfc_venue_deadman_not_observed|lfc_first_terminal_order_read|lfc_session0_safety_cancel' | ForEach-Object Line
   ```

   Pass: `lfc_venue_deadman_first_terminal` with `all_terminal: true` and
   `own_cancel_requests_since_drop: 0`; end reason `venue_deadman_cancelled`.

| 0g outcome | Meaning |
| --- | --- |
| `venue_deadman_cancelled` | pass |
| `order_no_longer_resting`, `fill`, `venue_deadman_requote_needed` | no pass; repeat 0g |
| `venue_deadman_not_observed` | **PERMANENT HALT** (Q-C2, signed): the ledger records a halt; every later start refuses. The cleanup's safety cancel still runs. Resuming needs a new ledger and a further clarification. |

## 7. After the runs

```powershell
& $python -m weather.market.lfc_cli verify
& $python -m weather.market.lfc_cli wallet-verify
Save-OwnerSnapshot after-session0
```

- `verify` success: `status: PASS`, `session0_passed: true`,
  `session0_runs_missing: []`. `session0_attestation` shows it is still
  missing until section 8.
- `wallet-verify` success: exit 0, S0-1 and S0-6 PASS,
  `positions_reader_status` `OBSERVED` (or `PARTIAL` meeting C7). The default
  `--since` is the ledger genesis, before any of our orders.
- The owner judges S0-1..S0-8 from the records before attesting.

## 8. Attestation

`session0-attest` writes `$root\session0\pass.json` once (schema
`lfc_session0_pass_v0.1`). Both flags are required at `acd052a2d` (draft D1):

```powershell
& $python -m weather.market.lfc_cli session0-attest --s0-2-seconds <S> --s0-2-helper-zero-utc <helper_zero_utc of the passing 0c>
```

1. Before typing the phrase, read the printed `s0_2_0c_last_journal_row_utc`
   and compute the gap:

   ```powershell
   $last = '<s0_2_0c_last_journal_row_utc as printed>'; $zero = '<helper_zero_utc>'
   [math]::Ceiling(([datetimeoffset]::Parse($zero) - [datetimeoffset]::Parse($last)).TotalSeconds)
   ```

2. `S` must be ≥ the gap and ≤ 20, and should be
   `ceil(max(0c loop seconds, gap))`. The last journal row is at or before the
   kill, so the gap is at least the true kill-to-zero time. If the gap is
   above `S`, press Ctrl+C and rerun with the larger `S`. If it is above 20,
   S0-2 fails: repeat 0c.
3. Type `attest session0 <first 6 hex of ledger.previous>` as printed.
   Success: `status: ATTESTED`, the file path and its `sha256`. Refusals write
   nothing: `session0_runs_missing_<runs>`, `session0_s0_2_above_20_seconds`,
   `session0_s0_2_below_timestamp_gap`, `session0_s0_2_timestamps_invalid`,
   `owner_confirmation_refused`.
4. `& $python -m weather.market.lfc_cli verify` → `session0_attestation` with
   no refusal.

**Send to master** (one message): per run the folder, session id, end reason,
`cleanup_ok` and the `LFC-RESULT` line; the 0b pre-part receipt folder; 0c
`kill_utc`, `helper_zero_utc`, loop seconds, gap and `S`; 0d loop seconds; the
0g evidence row values (`seconds_after_drop`, `own_cancel_requests_since_drop`,
`all_terminal`); the `verify` and `wallet-verify` status lines; the
`pass.json` sha256 and `ledger_previous_sha256`; the snapshot hash lines; toast
yes/no per run; any refusal code. **Never** raw positions, balances, addresses
or snapshot files: only rows for session 0's own order IDs, under the read
clearance.

## 9. Abort and emergency cancel — OWNER ONLY

Use when anything looks wrong while our orders may rest.

1. **Ctrl+C** in window A. The script's cleanup cancels each of our orders, then
   cancels account-wide, then reconciles. Wait for its end line.
2. If the process is gone or the cleanup printed `PANIC`:

   ```powershell
   & $python -m weather.market.lfc_cli cancel-ours
   ```

   It cancels only orders whose IDs are in the ledger and writes
   `$root\cancel-ours-<stamp>.json`. Success: `remaining_ours: []`.
3. Last resort, if an order of ours still rests or an unacknowledged intent may
   have posted: cancel it in the Polymarket UI. During 0g this voids the run
   (and an owner cancel can never count as the venue dead-man).
4. Then:

   ```powershell
   & $python -m weather.market.lfc_cli reconcile
   & $python -m weather.market.lfc_cli verify
   & $python -m weather.market.lfc_cli wallet-verify
   Get-OpenOrderCount
   ```

5. Backstop: every order is GTD at run end + 60 s.

Any refusal from the CLI ends with
`action: If orders may rest, run cancel-ours, then verify.` — do that.

**Rollback.** There is none for money: session 0 counts in L, repeats
included. The rollback is to stop: leave the pinned worktree as it is, take
`Save-OwnerSnapshot after-session0`, and report to master. Session 1 does not
start.

## 10. Halt table

| Condition | Effect |
| --- | --- |
| 0g `venue_deadman_not_observed` | permanent campaign halt (ledger halt) |
| `l_stop_at_cap` (L reaches 100 pUSD) | permanent halt (PR §6) |
| `l_reconciliation_mismatch` / any trade mismatch | permanent halt (PR §6) |
| `ledger_halted` at any start | the halt above is in force; stop |
| S0-1, S0-2 or S0-6 fail | blocks session 1; fix and repeat that run |
| `cleanup_ok: false` or `PANIC` | emergency path (section 9), then repeat |
| `ledger_unacknowledged_intent_needs_reconcile` or an open session | run `reconcile`; if it keeps refusing, stop for a written fix (C3) |
| `cancel_not_terminal` | leg stays in L; `reconcile`, then repeat |
| a wrong end reason for the run | no pass; repeat the run |
| `host_mutex_busy_or_abandoned`, `host_workload_recovery_required` | section 3.4 |
| `clean_final_tip_preflight_required` | rerun `preflight` to PASS (same UTC date, same commit) |
| `baseline_t40_age`, `baseline_foreign_open_orders` | take `baseline --label t40` again |
| `wallet_activity_outside_pilot` | stop; owner activity changed positions |
| `past_hard_stop_2350z` | too late in the UTC day; continue another day before 10-15 |
| `session0_deadline_passed` | 2026-10-15T00:00Z reached; session 0 cannot run any more (D10) |

## 11. Differences between the signed docs and the code at acd052a2d

Status as of 2026-10-09 evening. **Settled** = approved by master-agent and
the owner; **closed** = no longer a difference at `acd052a2d`, or carried in
draft D; **open** = still a runbook-only note.

1. **Mutex — settled.** The FIX1 deployment note says to hold the mutex for the
   session. The code takes it per run without waiting, so a pre-held mutex
   refuses every run. Section 3.4: a freeze and a check before each run.
2. **0c kill — settled.** S0 §4 says `taskkill /F /PID <script pid>`. The CLI
   prints no PID, and the venv `python.exe` is a launcher with an interpreter
   child. Section 6 finds the launcher and kills the tree with `/T`.
3. **0c leaves the mutex abandoned — settled.** The next `preflight`/`live`
   refuses once (and a failed preflight becomes the latest receipt) unless the
   probe clears it first (section 6, 0c step 5).
4. **0b pre-part — settled.** Its intended preflight failure becomes the latest
   receipt, so a fresh PASS preflight is needed before `live --run 0b`.
5. **0b foreign order location — closed.** S0 §4 says "on the session-0
   market"; C6 says a token outside the session. This runbook follows C6, and
   the owner approved the two 0b orders on that basis (D9).
6. **t40 age — settled.** The code needs a t40 baseline ≤ 90 min old at every
   start, so it is retaken before each sub-run.
7. **Baseline sources — open (note).** PR §5 baselines are
   `wallet_reader_client` reads; the code's `baseline` reads the venue and the
   public data-api. This runbook takes both.
8. **Attest flag — closed (D1).** The code also requires
   `--s0-2-helper-zero-utc` and refuses when `S` is below the
   last-journal-row-to-helper-zero gap.
9. **Session-0 deadline — closed (D10).** Enforced in code:
   `session0_deadline_passed` at or after 2026-10-15T00:00Z.
10. **Wording in C — closed (D2-D4).** The N-6 rule; "0d and 0g journal";
    "0e recorded no leg intent".
11. **Extra conditions and shadow scope — closed.** The 88a file is accepted as
    is, and `shadow-scope-union` generates the scope file (section 2).
12. **Run order — open (note).** Not enforced; this runbook puts 0g last.
13. **0d S0-2 — open (note).** Judged from the drop row and the loop; the
    script's own 8 s cleanup normally ends 0d before the venue does.
14. **0b owner orders in the no-trade window — closed (D9).** Owner-approved
    2026-10-09 evening.
15. **S0 §5 commands — open (note).** They use `.\venv\Scripts\python.exe`
    from the repository root; the pinned worktree has no venv, so this runbook
    uses the main venv's interpreter with the pinned `PYTHONPATH`.
16. **Reader topology — closed (D6.3).** The pinned tip carries the any-LAN
    reader; the 8765 reader is restarted on it (section 3.6).
17. **Reader cache vs S0-2 — closed (D6).** The helper uses the no-cache
    `GET /open-orders?fresh=1`, polled every 3 s (S0 §5 says 2 s; 3 s keeps
    the loop inside the shared cap and only lengthens the measured time).
18. **S0-7 — settled.** Checked by hand (section 5); no code check.
19. **C8 — closed (D7).** The maker-fee class rule replaces "fee rate 0";
    session 0 must be FEE_FREE.
20. **Neg-risk — open (known limit, D8).** The session-0 picks are plain
    binary markets, so session 0 does not exercise the neg-risk signing path;
    session 1 is the first neg-risk signing, under the existing hard limits.

## 12. Owner inputs still needed

Done: the event slugs (section 2), the `$extra` path, the session-0 date
(10-12, ~15:00Z), the after-settlement answer and the 0b approval (D9).

1. The Fable delta-3 review over `468607b13..acd052a2d`; then the main session
   creates and locks `C:\wt\lfc-pinned-acd052a2d` (section 3.0).
2. The restart of the 8765 reader on the any-LAN code at a time the owner
   picks; then the direct yes and the workstation LAN IP for the client config
   (section 3.6; written by the owner, never uploaded).
3. At T − 40 min on 10-12: `shadow-scope-union` PASS and its sha256 recorded.
4. Signature of draft clarification D (after the delta-3 review) before
   session 1.
