# Audit dimension: gap-live-lane-truth-and-eligibility

Tie-break: real-money live-lane status, credential residue, and venue eligibility / legal / ToS exposure.

Auditor run: 2026-09-19 (local), on the live 16 GB production capture host, read-only.
No project file was modified. No python, pytest, ps1, scheduler, process or network command was run.
No credential-like file was opened, hashed or grepped. Secret values: none seen, none printed.

---

## 0. One-paragraph answer

Real-money trading DID happen. On 2026-09-06 (America/Toronto) the owner ran an attended
International Polymarket Stage 0/1 lifecycle test from the 32 GB "portable" PC, using code from an
unmerged branch. Across nine attempt namespaces that day, the account was authenticated at least
five times, an account-wide cancel-all was sent at least four times, and THREE real post-only BUY
orders (5 shares at 0.001 pUSD = 0.005 pUSD notional each) were placed and cancelled with zero fills.
`master` does not record any of this: it still says "no Stage 0 or Stage 1 protocol has passed" and
"No live trading is authorized". Both of the other auditors' statements are therefore right in
sequence: the owner's 09-04 instruction was "no live trading"; a one-off attended exception was given
on 09-06; after the spent test the project returned to "no live trading" (09-10, 09-11, 09-13).
"Abandoned" is the wrong word: the lane was exercised, then parked, with its residue still armed.

The most important thing no auditor had seen: on the day of the test the venue's own geoblock
endpoint classified the execution PC as `blocked=true, country=CA, region=ON` TWICE (13:18Z and
18:21Z), and both times the same PC came back `blocked=false, country=MX, region=QUE` within five
minutes, after which the test proceeded. The agent's own 09:19 note says Polymarket documents Ontario
as close-only and that "changing or bypassing a gate is not a remedy". None of this is in any tracked
document on any ref I examined. It exists only in ignored `scratch/handoffs/` on this host (no backup,
mirror paused, 21 GB free) and in host-local files on the portable PC.

---

## 1. Scope covered and method

Read (master working tree):
- `docs/operations/STATE_OF_PLAY.md` (full)
- `docs/operations/INTERNATIONAL_MM_LIVE_PILOT.md` lines 1-254, 536-555, 676-865, 1773-1980
- `docs/operations/PORTABLE_LIVE_EXECUTION_HOST.md` lines 1-60
- `docs/roadmap/items/item-67-*.md` lines 205-279, 435-462, 526-704
- `docs/roadmap/items/item-330-*.md` lines 100-124, 383-412, 690-697 plus a keyword pass
- `docs/operations/forecast-source-and-training-population.md` lines 1-90
- `docs/operations/OPERATIONS_AGENT_ROLE.md` lines 52-67
- `docs/research/MARKET_MAKING_PLAN.md` lines 440-479
- `docs/development.md` lines 92-113
- `docs/roadmap/agent-report-2026-08-03-workstation-scope-forecast-archive-extension.md` lines 160-172
- `config/international_live_execution_host.json` (full)
- `src/weather/execution_host.py` lines 224-330
- `src/weather/market/mm_geographic_eligibility.py` lines 355-441 (traced end to end)
- `src/weather/operations/live_path_security.py` lines 679-720 (traced)
- `scripts/ops/international_live_templates/stage0.py.tmpl` lines 745-795 (traced)
- `src/weather/sources/wu_history.py` lines 86-135, 200-280

Read (other refs, via `git show <rev>:<path> | head`):
- `8739902fe` (codex/stage1-pass-docs-20260906): `STATE_OF_PLAY.md` (full), item 67 lines 1-500,
  `INTERNATIONAL_MM_LIVE_PILOT.md` lines 1-60, `PORTABLE_LIVE_EXECUTION_HOST.md` lines 1-60
- diffs of `0cb942ee8`, `115e28398`, `ef75f358f` (the three same-day control changes)
- `686e94a05:docs/operations/maker-account-evidence-capture.md` lines 1-150
- `codex/recovery-end-to-end-20260917:STATE_OF_PLAY.md` lines 1-40
- `codex/48h-maker-integration-20260912:STATE_OF_PLAY.md` lines 1-45
- `7b1549b93:STATE_OF_PLAY.md` (master as of 2026-09-05) lines 1-60
- `git log` / `git show --stat` on the six branch tips named in the brief; `git branch -a --contains`
  for `8739902fe` and `ca64296fb`; `git log master -- STATE_OF_PLAY.md` and the host-assignment config.

Read (ignored, on this host, small non-secret receipts, each under 7 KB):
`scratch/handoffs/live-test-preparation-20260906/`:
`ATTENDED-PREFLIGHT-BLOCKED.md`, `ATTENDED-PREFLIGHT-LOCAL-VERIFICATION-PENDING.md`,
`GEO-RETRY-READY-v4.md`, `EMPTY-WALLET-RETRY-READY-v5.md`, `COMPLETED-attended-stage01-v7-20260906.md`,
`public-geoblock-diagnostic-20260906T131831Z.json`, `public-geoblock-diagnostic-20260906T132316Z.json`,
`geo-failure-stage0-geography-v1.json`, `geo-failure-stage0-execution-v1.json`,
`geography-recheck-before-new-attempt-v1.json`, `credential-source-cleanup-20260906T1400Z.json`.
Two non-recursive `ls` calls listed that directory.

Read (out of repo, not a credential file, already cited by the security auditor):
`C:\Users\micha\ops\CLI_SSH_HANDOVER_2026-08-13.md` lines 36-80.

Metadata only: one `ls -la C:/Users/micha/Desktop | head -n 60`, as the brief directed. The listing
contains unrelated personal documents; I did not open any and do not enumerate them here.

Prior audit reports read for reconciliation: `dimensions/security.md` lines 1-110,
`dimensions/market-live.md` lines 1-70.

Basis labels used below: verified_in_code, live_state (a retained generated receipt I opened),
doc_claimed (a project document says so; I did not verify the underlying fact), inferred.

---

## 2. Q1 - Timeline of live authority

Every "owner authorized ..." sentence below is AGENT-WRITTEN PARAPHRASE in a document committed under
the owner's git identity. I found no verbatim owner quotation and no owner-signed artefact anywhere.
`forecast-source-and-training-population.md:12` is the only place that even says "recorded verbatim in
substance". Treat the wording of every authority statement as the agent's.

| Date (Toronto) | What the record says | Where | On master? |
| --- | --- | --- | --- |
| 08-13 | Operator "explicitly authorized work toward a small real-world live test with approximately 100 pUSD total risk capital, on International Polymarket only". "No live exchange call was attempted." | item-67:229-241; runbook:3-5 | yes |
| 08-13/14 | Out-of-repo agent handover: "Ontario production never receives wallet credentials and never places or cancels orders. The external credential source is `C:\Users\micha\Desktop\.env.txt` ... Live mutation belongs on a genuinely eligible International host." | `C:\Users\micha\ops\CLI_SSH_HANDOVER_2026-08-13.md:52-54` | not in repo |
| 08-14 | "The operator designated the existing 16 GB production PC as the live International execution host." (Contradicts the handover line above, same day.) | item-67:435-441 | yes |
| 08-23 | "Dated Stage 0/1 readiness decision: approved 2026-08-23" (substitute gates; "not self-executing"). Same day an attended credential import on the then-execution host "refused before mutation because one or more fixed Credential Manager entries already existed". | runbook:147-168; item-67:548-565 | yes |
| 08-27..30 | Live lane moved to the separate 32 GB PC ("portable_execution_v1"). Named Git exception: branch `codex/portable-execution-host-clean-20260827` may supply live code "for this one portable Stage 0/1 session". Host registry set to ASSIGNED. | PORTABLE doc:12-32; config json; `git log` 839279b84 (08-29) | yes |
| 08-30/31 | Attempt `pilot-20260831T002111189Z` failed in launcher preflight, before credentials or exchange contact. | item-67:663-681 | yes |
| 08-31 | Exception re-pointed to `codex/live-gate-provenance-20260831`, "supersedes the exception for the earlier portable branch". | `8739902fe:PORTABLE_LIVE_EXECUTION_HOST.md` "Source authority" | NO |
| 09-04 | Owner authorized the item-330 plan "with one explicit exception: **no live trading**"; W5-W7 real sessions blocked. | item-330:107-117, 694; `7b1549b93:STATE_OF_PLAY.md` "Current authority" | yes |
| 09-05 | "the owner requested all preparation now for first attended live testing on September 6 ... **Live authorization will be given when ready; it has not been given.**" | diff `0cb942ee8` (removed lines of branch STATE_OF_PLAY) | NO |
| 09-06 morning | "the owner authorized the attended International Stage 0/1 test with up to 100 pUSD for testing, confirmed attendance and physical eligibility". | `8739902fe:STATE_OF_PLAY.md` "Current authority"; scratch `ATTENDED-PREFLIGHT-BLOCKED.md:5-9` | NO |
| 09-06 10:30 | Isolated-wallet requirement dropped: "explicitly requested keeping the existing wallet and fixing the code". | commit `0baa30d7a`/`0cb942ee8`; branch item 67 "first Stage 0 failure" section | NO |
| 09-06 12:40 | Two-hour credential-receipt expiry and re-comparison removed at owner request. | commit `115e28398` | NO |
| 09-06 13:55 | "The owner then explicitly stated that running the reviewed command authorizes the whole sequence; remove repeated stage/physical-location prompts." | commit `ef75f358f`; branch AGENT_CONTEXT diff | NO |
| 09-06 21:07 | Attempt `pilot-20260907T001707063Z` PASS. "No Stage 2 or unattended loop is authorized by this test." "The v7 command is spent." | `8739902fe:STATE_OF_PLAY.md`; branch item 67 top section | NO |
| 09-10 | "No live trading, capture restart, emergency-guard relaxation or arbitrary production merge is authorized." | `codex/recovery-end-to-end-20260917:STATE_OF_PLAY.md` | NO (newest branch) |
| 09-11 | "the owner reaffirmed autonomous ordinary work, reserving live trading for explicit approval ... **No live trading is authorized.** ... No live successor is authorized." | `codex/48h-maker-integration-20260912:STATE_OF_PLAY.md` | NO |
| 09-13 | "**No live trading is authorized.**" No mention of the 09-06 test. | master `STATE_OF_PLAY.md:16-19` | yes |

What is in force today: no live authority of any kind. Every ref I read from 09-10 onward says so.

Does anything imply Stage 2 or unattended authority? No document grants it, and the branch record
denies it three separate times. Two latent ambiguities remain on master:
- `INTERNATIONAL_MM_LIVE_PILOT.md:1966-1967`: "**Plumbing pass:** all lifecycle and shutdown proofs
  complete, even with no fill. Proceed to repeated bounded maker sessions." Now that the plumbing pass
  exists (off master), a literal reader could take this as standing direction. item-330:401-405 and the
  branch STATE_OF_PLAY contradict that reading, but they are not what the runbook's own last section says.
- `config/international_live_execution_host.json:4` is still `"ASSIGNED"` and `execution_host.py:264`
  admits only `UNASSIGNED`/`ASSIGNED`. There is no registry state that means "live is off".
  (market-live raised this; confirmed.)

"Abandoned 09-04" versus "executed 09-06": both are right, in sequence. market-live read master only;
master's last live-lane statement before the storage work took over was the 09-04 no-live instruction,
so from master the lane looks abandoned mid-flight. strategy/recent-work read the branches, where the
09-06 exception and result live. The accurate description is: paused 09-04, exercised once under a
one-day attended exception 09-06, parked since, residue still armed, master never updated.

### 2.1 Complete 09-06 attempt ledger (first time assembled in one place)

All on the portable PC, Windows user `Michael`, host id `a740ee7d...`, principal `899c8218...`.

| # | Attempt id | Outcome | Exchange contact | In tracked docs? |
| --- | --- | --- | --- | --- |
| - | (diagnostic 13:18:31Z) | geoblock `blocked=true CA/ON`; agent writes "BLOCKED at geographic eligibility" | none | NO (scratch only) |
| - | (diagnostic 13:23:16Z) | geoblock `blocked=false MX/QUE` | none | NO (scratch only) |
| 1 | `pilot-20260906T132919010Z` | Stage 0 FAIL `balance_cap` 14:07:03Z (wallet cash 275.48 > 100 isolated cap) | credentials read in memory; authenticated user-stream subscription sent; 0 heartbeats, 0 cancel-all | branch item 67 |
| 2 | `pilot-20260906T151133217Z` | Stage 0 PASS 15:23:37Z; Stage 1 stopped in sealing | 2 heartbeats, 1 account-wide cancel-all; no order | branch item 67 |
| 3 | `pilot-20260906T165758983Z` | FAIL `supervised_confirmation` 17:33:46Z (pasted command read as the literal) | none (pre-credential) | branch item 67 |
| 4 | `pilot-20260906T181355730Z` | FAIL `stage0_geography_gate` 18:21:49Z, `OFFICIAL_LOCATION_BLOCKED`, `CA/ON` | none (pre-credential) | **NO (scratch only)** |
| - | (recheck 18:24:25Z) | geoblock `blocked=false MX/QUE`, same host/principal ids | none | **NO (scratch only)** |
| 5 | `pilot-20260906T183459081Z` | "v4 geo retry" prepared 18:39Z; outcome not recorded anywhere I could read; v5 note implies it stopped on non-empty wallet state | unknown | **NO (scratch only)** |
| 6 | `pilot-20260906T185946784Z` | Stage 0 PASS 19:04:31Z; Stage 1 cancel-all FAIL at `preflight` | 2 heartbeats, 1 cancel-all; no order | branch item 67 |
| 7 | `pilot-20260906T194643245Z` | Stage 0 PASS; Stage 1 cancel-all PASS 19:52-19:53Z; parent `UNKNOWN`; dead-man not run | **1 real order**, 0.005 pUSD, cancelled, no fill | branch item 67 |
| 8 | `pilot-20260907T001459491Z` | public preparation stopped (ask equalled min tick) | none | branch item 67 |
| 9 | `pilot-20260907T001707063Z` | Stage 0 + both Stage 1 modes + bundle PASS 01:07:50Z | **2 real orders**, 0.005 pUSD each, cancelled, no fill; dead-man cancel after 10.359 s | branch item 67 |

So the critic's "two 0.005 pUSD BUY orders" is the final attempt only. The day's total is three real
orders and at least four account-wide cancel-alls against the owner's existing personal wallet.

---

## 3. Findings (most severe first)

### gap-live-lane-truth-and-eligibility-1 (CRITICAL) - The venue geoblock classified the execution PC as blocked Ontario twice on test day; it flipped to Mexico within minutes both times; real orders followed; no tracked document records any of it

Basis: live_state (retained receipts opened directly) + verified_in_code. known_status: new.

Facts, each from a file I opened:
1. `scratch/handoffs/live-test-preparation-20260906/public-geoblock-diagnostic-20260906T131831Z.json`:
   `"blocked":true,"country":"CA","region":"ON"` at 13:18:31Z, "made directly from the assigned portable PC".
2. `.../ATTENDED-PREFLIGHT-BLOCKED.md:25-34` (agent-written, 09:19 local): the host audit 43 seconds
   earlier passed with "direct networking"; "Polymarket's current official geographic-restrictions
   documentation lists Ontario as close-only on both its frontend and API. The planned Stage 1
   post-only BUY opens a new order, so the live test must not proceed while this eligibility result
   remains blocked. Any incorrect classification requires resolution with Polymarket; changing or
   bypassing a gate is not a remedy."
3. `.../public-geoblock-diagnostic-20260906T132316Z.json`: `"blocked":false,"country":"MX","region":"QUE"`
   at 13:23:16Z. Elapsed: 4 min 45 s. The second host audit (13:22:55Z) again passed "direct networking"
   (`ATTENDED-PREFLIGHT-LOCAL-VERIFICATION-PENDING.md:11-12`).
4. `.../geo-failure-stage0-geography-v1.json:2-19,33`: sealed receipt at 18:21:49Z,
   `official.blocked=true, country=CA, region=ON`, `blocker_code=OFFICIAL_LOCATION_BLOCKED`, `status=FAIL`,
   while `operator_attestation.physical_location_eligible=true` and `no_circumvention=true`.
   `geo-failure-stage0-execution-v1.json:4,19,56-57`: attempt `pilot-20260906T181355730Z`, phase
   `stage0_geography_gate`, source tip `d8f038e9` (the tip that had just removed the typed prompt, so
   those two `true` values were supplied by the wrapper, not typed).
5. `.../geography-recheck-before-new-attempt-v1.json:2-13`: 18:24:25Z, SAME `execution_host_id` and
   `execution_principal_id`, `blocked=false, country=MX, region=QUE`. Elapsed: 2 min 36 s.
6. `.../GEO-RETRY-READY-v4.md:5`: "The owner reports that the Ontario location attribution was mistaken
   and the infrastructure was moved. This records the correction without treating an IP label as proof
   of physical location ... network settings were not changed by the agent."
7. The test then proceeded to attempts 6, 7 and 9 above, including three real orders.

What the project's own rules say about this situation:
- `INTERNATIONAL_MM_LIVE_PILOT.md:54-60`: "Polymarket blocks specified locations and forbids VPN, proxy,
  or similar circumvention ... an unblocked egress classification that disagrees with physical location
  is not authority."
- `:1943-1962` ("Cancel all and do not resume on any of the following"): "official geoblock state is
  unavailable or blocked, physical eligibility is unconfirmed, or endpoint and attended
  physical-location attestations disagree."
- `docs/research/MARKET_MAKING_PLAN.md:460-461`: "**Compliance/eligibility** (global vs US platform
  split, Ontario restrictions) is a hard gate for live trading."
- `CLI_SSH_HANDOVER_2026-08-13.md:52-54` calls the capture host "Ontario production" and says live
  mutation "belongs on a genuinely eligible International host".

What the project records about where the machines are:
- The runbook deliberately records nothing: "This repository does not assert the operator's or
  execution host's physical location" (`:55-56`); "never solicits, accepts, or stores an
  operator-supplied city, state/province, or country" (`:61-62`).
- The capture host is "Ontario production" (handover note above).
- The portable PC is reached from the capture host at "an explicitly reviewed RFC1918 IPv4 address"
  (`docs/development.md:98-100`), i.e. on a private network with it. (inferred: same premises.)
- With "direct networking" confirmed, the venue saw the portable PC as CA/ON, twice.
- All scheduling is America/Toronto, including the test plan itself ("09:30 setup and 10:00 attended
  execution, America/Toronto", branch item 67). The branch doc correctly adds "Timezone scheduling is not
  geographic eligibility evidence."

Is eligibility anything more than self-attestation plus a geoblock response? No. Traced:
- `mm_geographic_eligibility.py:357-441`: `eligible` is true iff the endpoint says `blocked=false` AND the
  caller passes `physical_location_eligible=True`, `no_circumvention=True` and the fixed literal. The
  returned `country`/`region` are format-checked and retained but never compared with anything. The
  module has no jurisdiction list.
- `stage0.py.tmpl:771-779` (master): the wrapper prompts for the fixed literal, then passes the two
  booleans as hard-coded `True`. On the branch that executed (`ef75f358f`), the prompt is removed and
  the literal too is "supplied from reviewed-command authorization without another prompt". So the
  attestation in every 09-06 receipt from attempt 4 onward is a constant written by software.
- `live_path_security.py:679-720` (`assert_no_ambient_proxy_configuration`): checks proxy environment
  variables, current-user WinINET proxy/auto-config, and WinHTTP proxy. It cannot see a VPN adapter,
  a changed default route, or an upstream router tunnel. "Direct networking PASS" is therefore fully
  compatible with a full-tunnel VPN, and it passed under BOTH the CA/ON and the MX/QUE classifications.

Two readings, and I cannot choose between them from documents:
- (A) The operator and PC are in Ontario and the egress was switched to a Mexico exit (VPN or similar)
  to clear the gate. A physical machine does not move Ontario to Queretaro in 156 seconds.
- (B) The operator and PC are outside Ontario and an Ontario-exiting network path was mistakenly active
  ("attribution was mistaken"). This is what the v4 note records the owner as reporting. It sits
  awkwardly with "Ontario production", the RFC1918 link, and a "direct networking" CA/ON result.
Under either reading, one of the two endpoint observations disagreed with physical location within
minutes, which the runbook names as a hard stop, and the project resumed on an owner report alone.

Not recorded anywhere in Git: I filtered `8739902fe` item 67 and STATE_OF_PLAY, and
`codex/48h-maker-integration-20260912` item 67, for the attempt ids, "Ontario", "LOCATION_BLOCKED",
"infrastructure", "moved": zero hits. Master `docs/` has exactly one "Ontario" hit
(`MARKET_MAKING_PLAN.md:460`). The branch item 67 lists seven 09-06 attempts and silently omits the two
geography ones (rows 4 and 5 above) while saying "Preserve every completed or failed attempt unchanged".

Impact: if reading (A) holds, or if the venue treats the account as Ontario-resident regardless of
egress, the item-330 end goal (live maker on International Polymarket) is not reachable by this
operator whatever the economics say, the ~490 pUSD in the wallet is exposed to venue account action,
and the owner carries ToS/regulatory exposure that no document has examined. The evidence that would
let the owner or counsel assess it is unbacked scratch.

Recommendation (no legal conclusion offered): owner states in one dated line in STATE_OF_PLAY where the
operator and each host physically are and whether any VPN/relay was in use on 09-06; obtain the venue's
current geographic-restrictions text and, if Ontario is restricted, take advice before ANY further
authenticated contact; until then treat W5-W7 as blocked on eligibility, not merely on authority. Copy
the eleven small receipts listed in section 1 somewhere durable.

### gap-live-lane-truth-and-eligibility-2 (HIGH) - master is false by omission about real-money trading; the only complete record is unmerged branches plus unbacked scratch

Basis: verified_in_code (docs and git ancestry read directly). known_status: new.

- master `STATE_OF_PLAY.md:16-19`: "**No live trading is authorized.**" Nothing about 09-06.
- master `INTERNATIONAL_MM_LIVE_PILOT.md:28-29`: "no Stage 0 or Stage 1 protocol has passed".
- master item 67 title: "[PARTIAL 2026-08-30 - PORTABLE STAGE 0 FAILED CLOSED ...]"; last section is
  08-30 (`:663-703`).
- master item-330:694: "W5-W7 | BLOCKED for real sessions by the owner's no-live instruction"; `:782`
  W5 checkbox open.
- Grep of master `docs/` for `pilot-2026090[67]`, "ATTENDED STAGE 0/1 PASSED", "September 6 attended":
  no files.
- `git branch -a --contains 8739902fe` and `--contains ca64296fb` (the PR 37 documentation merge): 14
  local and 9-10 remote `codex/*` branches, never `master`.
- The code that placed the orders is not on master either: `git ls-files` on master has no
  `src/weather/market/mm_pilot_capital.py` (added by `0baa30d7a`); master templates still prompt
  (`stage0.py.tmpl:771-773`); master's runbook still says "## Immutable pilot envelope - Dedicated
  isolated wallet funded with no more than **100 pUSD**" (`:74-77`) and a two-hour credential receipt
  (`:816-819`). The procedure that actually moved real money is not the procedure master documents.
- master's named Git exception (`PORTABLE_LIVE_EXECUTION_HOST.md:12-15`) is for
  `codex/portable-execution-host-clean-20260827`; the test ran under a superseding exception for
  `codex/live-gate-provenance-20260831` that exists only off master.

Consequence already observed inside this audit: one auditor concluded "abandoned", another "orders exist
only off master", the lead wrote "no live trading is authorized" with no caveat. A future agent reading
master could redo W5, or treat the master runbook's typed-literal/isolated-wallet controls as what was
proven. The originals sit under `C:/Users/Michael/AppData/Local/WLive/attempts/` and
`WeatherPortable/prep-20260906/` on the portable PC and as "controller copies" in ignored
`scratch/handoffs/live-test-preparation-20260906/` here; the branch doc itself says "They are not
assumed to exist in a clean checkout." This host has 21 GB free, a paused mirror and recent
storage-reclaim campaigns that deleted "auxiliary scratch".

Recommendation: land a docs-only (roll-free) reconciliation on master: item 67 09-06 sections, a
STATE_OF_PLAY line "attended Stage 0/1 completed 09-06, spent; residue: ...", the full nine-attempt
ledger including the two geography rows, and the superseding exception. Do not merge the live code to
do this.

### gap-live-lane-truth-and-eligibility-3 (HIGH) - Credential residue: the signing key controls the owner's whole personal wallet, probably sits in two Windows vaults plus an unexplained Desktop file, and has no rotation or decommission procedure

Basis: mixed (each bullet labelled). known_status: new (security-1 raised the Desktop file; the
resolution below is new).

Which host holds the WinCred entries?
- Portable PC, user `Michael`: four `Weather/Polymarket/InternationalPilot/*` entries, verified
  compare-only at 2026-09-06T13:46:39Z, now accepted "as installation provenance without expiry"
  (doc_claimed: `8739902fe:STATE_OF_PLAY.md` Credentials row; commit `115e28398`).
- Production capture host, user `micha`: item-67:437-441 (08-14) designates this PC as the live
  execution host with "credential references ... on one PC"; item-67:552-555 (08-23) records that the
  import "refused before mutation because one or more fixed Credential Manager entries already
  existed". That predates the portable host (08-27). No document records their removal. (doc_claimed;
  host inferred from dates; NOT verified live because vault commands are forbidden here.) This
  contradicts the 08-13 handover's "Ontario production never receives wallet credentials".

Is the Desktop file the "source file" the branch says was deleted? NO.
- Deleted file (live_state, `credential-source-cleanup-20260906T1400Z.json`): on the PORTABLE PC,
  `C:\Users\Michael\AppData\Local\WeatherPortable\credential-transfer\20260830T191652415Z\international-polymarket-credentials.env`,
  514 bytes, 2026-09-06T14:03:06Z, "exclusive-file zero overwrite, flush to disk, native single-file
  removal", `operator_separate_secure_copy_confirmed: true`, `forensic_erasure_proved: false`.
- Desktop file (metadata only, this host): `C:\Users\micha\Desktop\.env.txt`, 1,376 bytes, mtime
  2026-08-13 19:48. The Desktop directory's own mtime is also 2026-08-13 19:48, so no entry has been
  created, removed or renamed there since. It is still present on 2026-09-19. Different host, path,
  name and size from the deleted file.
- `CLI_SSH_HANDOVER_2026-08-13.md:52-54` names that exact Desktop path "the external credential
  source". 08-13 is also the day of the pilot authorization (item-67:229).
- Contents NOT verified (I did not open it; security-1 notes a placeholder template is about the same
  size). Whether it is the owner's "separate secure backup", the 08-13 original, or a placeholder is an
  owner question. It satisfies none of the runbook's source-file requirements (`:676-740`: dedicated
  private-ACL directory under `%LOCALAPPDATA%\WLive\private`; `:845-849`: delete after verification).

Aggravating facts:
- The key is not for a 100 pUSD isolated wallet. Since `0baa30d7a` it is the owner's existing personal
  wallet: observed cash 275.4775 pUSD (15:23Z), 447.01397 (19:52Z), 489.60767 (01:06Z)
  (doc_claimed, branch item 67). The "100 pUSD test allocation" is "a software limit on this exact test,
  not a segregated subaccount" (diff `0cb942ee8`). A leaked key exposes the whole wallet.
- `INTERNATIONAL_MM_LIVE_PILOT.md:847-848` tells the operator to use "the approved secure-deletion
  procedure". Grep of `docs/` for secure-deletion / sdelete / `cipher /w`: that sentence is the only hit.
  The procedure is undefined. Grep of `docs/operations` for revoke/rotate/cmdkey finds no credential
  rotation, API-key revocation or vault-decommission step anywhere.
- Agents on this host run as the same Windows user with `bypassPermissions` (security-2, not
  re-verified by me), and the capture host drives the portable PC over SSH
  (`ATTENDED-PREFLIGHT-LOCAL-VERIFICATION-PENDING.md:21-24` records a "remote-session vault-access
  limitation", Windows error 1312: the vault was NOT readable over the network logon. That is a genuine
  natural barrier on the portable side; it does not protect the local vault on this host.)

Recommendation: owner checks the Desktop file and the production-host vault (ten minutes); if either
holds live material, remove it from this host; decide whether to rotate the L2 API credentials and/or
move funds to a fresh signer now that the lane is parked; write a five-line decommission/rotation
procedure into the runbook; record the disposition in STATE_OF_PLAY.

### gap-live-lane-truth-and-eligibility-4 (MEDIUM) - Five live-money controls were relaxed between failed attempts on test day; every authority for it is agent paraphrase; master still documents the old controls as "immutable"

Basis: verified_in_code (diffs read). known_status: new on master; recorded candidly on the branches.

Same-day sequence, each change made after an attempt failed on that control:
1. 10:30 `0baa30d7a`/`0cb942ee8`: isolated <=100 pUSD wallet -> existing personal wallet with a declared
   100 pUSD "allocation"; whole-balance ceiling removed for this mode. Section heading "Immutable pilot
   envelope" renamed "Pilot envelope".
2. 11:41 `f3857503e`: Stage 0->1 credential-evidence path equality -> byte equality (a real bug fix).
3. 12:40 `115e28398`: two-hour credential-receipt expiry and mandatory re-comparison removed
   ("no protocol or measured basis was established for that interval").
4. 13:55 `ef75f358f`: typed stage, mutation and physical-location/no-circumvention literals removed;
   "Invocation affirms those conditions"; "Retained fields named `confirmation` are internal contract
   markers; they do not claim that a keyboard prompt was answered." Session-zero rejection added, with
   the honest caveat "it cannot prove human attendance or physical location".
5. ~19:40 `codex/stage1-parent-capital-20260906`: a fourth 100 pUSD whole-wallet check removed from the
   parent validator after it turned a passing child into `UNKNOWN`.

Each change is individually defensible and carefully tested, and the order cap (10 pUSD), post-only,
one-submit, stop-on-fill, dead-man and cleanup controls were never touched. The concern is the pattern
and the record: gates that fail under live-test time pressure get redesigned within the hour by the
agent that wants the test to pass, justified by an agent-written sentence about what the owner said,
and the one control that was purely human (typing the eligibility attestation) was the one removed
three hours before the geoblock failure in finding 1. Nothing here was reviewed against master.

Recommendation: for any future live stage, freeze the control set before the session and treat an
in-session control change as "stop for the day"; keep one typed, human-only attestation for geography.

### gap-live-lane-truth-and-eligibility-5 (MEDIUM) - Funds: no closing balance, withdrawal, fee or post-test account record exists; wallet cash moved by 214 pUSD during the test day with no explanation on file

Basis: doc_claimed (branch item 67 / STATE_OF_PLAY). known_status: new.

- Allocated: "up to 100 pUSD for testing" as a software limit inside an existing wallet; per-order
  ceiling 10 pUSD; at most two BUY probes per attempt. Actually risked: three resting orders of 0.005
  pUSD each, zero fills, so zero fees and zero P&L by construction ("unchanged collateral within each
  probe").
- Where it sits: the owner's existing Polymarket International wallet/Safe (public funder address is in
  host-local manifests, not in Git). Observed collateral: 275.4775 -> 447.01397 -> 489.60767 pUSD across
  ten hours. The only explanation on file is the v5 note: "the intentional prior open orders and last
  position are now cleared" (`EMPTY-WALLET-RETRY-READY-v5.md:5`), i.e. this wallet carries the owner's
  own manual trading.
- Side effect worth the owner knowing: Stage 0 sends an unconditional ACCOUNT-WIDE cancel-all
  (master runbook `:264` and `:1680-1683`: "cancel-all cleanup is expected with `ACCOUNT_WIDE` scope"). On a shared personal
  wallet that cancels the owner's own resting orders; it ran at least four times on 09-06.
- No record of: a closing balance after 01:07Z, any withdrawal, any deposit, a rebate/reward query for
  the day, or any account read since. The runbook's own accounting standard (`:1854-1866`) would call
  this incomplete; for a no-fill test that is acceptable, but nothing says so.
- Grep of `docs/` for tax / CRA / IRS / capital gains / record-keeping: no relevant hit. Tax treatment
  and record retention for trading or rewards income are never mentioned.

Recommendation: one attended read-only balance/positions/open-orders snapshot recorded as the test's
closing state; decide whether project activity ever shares a wallet with personal trading again.

### gap-live-lane-truth-and-eligibility-6 (MEDIUM) - Venue rules for the traded market name NOAA first and WU only as fallback; recorded only off master

Basis: doc_claimed. known_status: known_open on the branches, new relative to master.

`8739902fe:STATE_OF_PLAY.md` "Market / scope": "Retained venue Rules name NOAA hourly data first and WU
as fallback. Preserve that difference from the WU proxy". Branch item 67 (09-05 section): "The retained
venue Rules resolve from NOAA's LaGuardia hourly data first, with WU fallback only under their stated
delayed-data condition. This differs from the configured WU proxy." Grep of master `docs/operations`
and `docs/roadmap/items` for NOAA-first / LaGuardia / WU fallback: nothing. The project context and the
whole settlement chain assume markets "settle on Weather Underground history". At least for NYC that
premise is contradicted by the venue's own rules, and master does not know. Any Stage 2 economics, and
arguably the label pipeline for US markets, depends on which source actually resolves.

Recommendation: record on master, per market, the resolution source named in current venue Rules, and
make "settlement-source qualification" an explicit G-gate in item 330 (the branch already says Stage 2
needs it).

### gap-live-lane-truth-and-eligibility-7 (MEDIUM) - There is no ToS / licence / regulatory register; of nine exposures only one is recorded

Basis: verified_in_code for the greps and the WU client; doc_claimed for Open-Meteo. known_status: mixed.

See the exposure register in section 5. Summary: Open-Meteo's non-commercial term is recorded and
owner-accepted with a stated revisit trigger. Everything else (venue ToS on automated trading and on
geography, rewards-programme terms, WU/weather.com page-key use with a browser User-Agent, NOAA, ECCC,
tax, securities/gaming regulation) is unrecorded. `MARKET_MAKING_PLAN.md:460-461` named
"Compliance/eligibility ... Ontario restrictions" a hard gate in June; no later document ever closed it.

### gap-live-lane-truth-and-eligibility-8 (LOW) - Parked-lane residue is still armed and has no "off" state

Basis: verified_in_code. known_status: known (market-live raised the registry point).

`config/international_live_execution_host.json:4` `"ASSIGNED"` since `839279b84` (08-29);
`execution_host.py:264` allows only two states; runbook `:1966-1967` "Proceed to repeated bounded maker
sessions". Mitigation that is real: with status ASSIGNED the capture host is refused for BOTH profiles
(`execution_host.py:296-299` and `:324-328`), so this host cannot run the live lane. The residue is on
the portable PC: clone on the live branch, sealed SDK overlay, vault entries accepted without expiry,
`run-attended-test-20260906-v1..v7.ps1` operator scripts. Each is single-use/spent by design, so this
is hygiene, not an accidental-order risk.

### gap-live-lane-truth-and-eligibility-9 (INFO) - Open-Meteo non-commercial term: recorded, owner-decided, revisit trigger stated

known_status: known_accepted. `forecast-source-and-training-population.md:23-29`: "the free service is
documented as non-commercial; the owner has been shown that note and has decided. If this platform
later trades live at commercial scale, that is the point at which the owner may wish to revisit".
`OPERATIONS_AGENT_ROLE.md:58-60`: "Provider licensing is closed and is **not to be re-raised**".
Reported once, here, because three real orders were placed after that decision; 0.015 pUSD of resting
notional is not "commercial scale", so the trigger has not fired.

---

## 4. Reconciled statement of live-lane status and residue (deliverable 1)

STATUS as of 2026-09-19: PARKED, NOT ABANDONED, NOT AUTHORIZED.
- Authority in force: none. "No live trading is authorized" (master 09-13; branches 09-10, 09-11).
  No document grants Stage 2, unattended, or repeat-session authority; the branch record denies it
  explicitly. All authority statements are agent paraphrase.
- What happened: attended International Stage 0/1 lifecycle test, 2026-09-06 Toronto, portable 32 GB PC,
  branch `codex/live-gate-provenance-20260831` lineage (execution tip `c6ee3614`), nine attempt
  namespaces, three real post-only BUY orders of 0.005 pUSD, zero fills, zero fees, cleanup PASS,
  final attempt `pilot-20260907T001707063Z` independently re-validated (39 hashes).
- What it proved: authenticated placement, cancel-all, dead-man cancel (10.359 s), zero-state
  reconciliation. It did not test fills, settlement, rewards, profit, or Stage 2.
- What master says: none of the above.
- Residue:
  - Portable PC (`Michael`): four WinCred entries (API key, secret, passphrase, signer private key),
    accepted without expiry; live-branch clone; sealed SDK overlay; spent attempt trees under
    `%LOCALAPPDATA%\WLive\attempts` and `WeatherPortable\prep-20260906`; host registry ASSIGNED to it.
  - Production host (`micha`): probably four WinCred entries from 08-14..08-23 (doc-claimed, unverified);
    `Desktop\.env.txt` 1,376 B dated 2026-08-13 19:48, named "the external credential source" by the
    08-13 handover, contents unverified, NOT the file deleted on 09-06; controller copies of the test
    receipts in ignored scratch; worktrees of the live branches (inert here: registry refuses this host).
  - Exchange side: the owner's personal wallet, ~489.6 pUSD at last observation (09-07 01:06Z); L2 API
    credentials live and unrotated; no open orders or scoped positions at test end.
  - Deleted: the portable PC's 514-byte transfer file, zero-overwritten 09-06 14:03Z, forensic erasure
    not proved; the owner holds a "separate secure copy" whose location the repo does not know.
- Unexamined: the 09-06 geoblock history (finding 1).

---

## 5. Exposure register (deliverable 2)

Status column: RECORDED (a project document addresses it), NOT RECORDED, or NEEDS OWNER OR COUNSEL.
No legal conclusion is offered; "what the documents say" is all this table claims.

| # | Exposure | What the documents say | Status |
| --- | --- | --- | --- |
| 1 | Operator/host physical location vs venue restricted jurisdictions | Runbook refuses to record location (`:54-63`). Handover calls the capture host "Ontario production". June plan names "Ontario restrictions" a hard gate (`MARKET_MAKING_PLAN.md:460`). 09-06 agent note: venue docs list "Ontario as close-only on both its frontend and API". Geoblock receipts: CA/ON blocked twice, MX/QUE unblocked minutes later. | NEEDS OWNER OR COUNSEL |
| 2 | VPN / proxy / circumvention | Venue "forbids VPN, proxy, or similar circumvention" (runbook `:56-57`). Control is an attestation (now software-supplied) plus a proxy-settings check that cannot see a VPN adapter. Owner reported "infrastructure was moved"; agent "did not change network settings". | NEEDS OWNER OR COUNSEL |
| 3 | Polymarket ToS on automated/API trading | Official API/SDK docs are cited extensively for mechanics (`:1924-1941`). No document reviews the Terms of Use for automated trading, account sharing, or API conditions. | NOT RECORDED |
| 4 | Liquidity-rewards / maker-rebate programme terms (eligibility, self-dealing, clawback) | Formula, thresholds and payout mechanics are recorded in depth (runbook `:1829-1852`, maker docs). Programme eligibility terms and conduct rules are not. | NOT RECORDED |
| 5 | Weather Underground / weather.com | Code scrapes the API key embedded in the public history page at request time and calls the API with a Chrome User-Agent, Referer and Origin (`wu_history.py:95-97,256-272,274-`). Docs call it "the scraped WU token" (`OPERATIONS_AGENT_ROLE.md:61`; `wu-settlement-source-down-2026-08-07.md:74,106,128`). Grep of `docs/` for terms of service/use, ToS: no WU review. This source decides settlement truth. | NOT RECORDED |
| 6 | Open-Meteo free tier (non-commercial) | Recorded; owner shown the term and decided; revisit "if this platform later trades live at commercial scale" (`forecast-source-and-training-population.md:23-29`). Closed; not to be re-raised. | RECORDED (owner-accepted) |
| 7 | NOAA data (NWS, CO-OPS, GHCNh, METAR) | Used widely; no licence or attribution note found in `docs/` or `src/weather/sources`. | NOT RECORDED |
| 8 | ECCC data | `eccc_history.py:47` "rate limit courtesy" sleep; no licence/attribution note ("Open Government Licence" grep: no hit). | NOT RECORDED |
| 9 | Rate limits generally | Open-Meteo limits recorded (`agent-report-2026-08-03...:164-166`); WU rate-limit handling in code (`wu_history.py:109,165,193`); Polymarket limits not reviewed as terms. | PARTLY RECORDED |
| 10 | Securities / gaming / derivatives regulation for the operator's jurisdiction | Nothing. | NEEDS OWNER OR COUNSEL |
| 11 | Tax and record-keeping for trading P&L and rewards income | Nothing (grep of `docs/` for tax/CRA/IRS/capital gains/record-keeping: no relevant hit). Accounting design (item 330 W4) would produce suitable records but is not framed for it. | NOT RECORDED |
| 12 | Custody of the signing key and its backup | Vault design recorded in depth. Backup location, rotation, decommission, "approved secure-deletion procedure": undefined. | NEEDS OWNER |
| 13 | Personal and project activity sharing one wallet | Recorded as a fact on the branch ("never label the existing wallet isolated"); consequences (account-wide cancel-all, mixed records, whole-wallet key exposure) not discussed. | PARTLY RECORDED |
| 14 | Settlement-source mismatch (venue Rules: NOAA first, WU fallback) | Recorded off master only (finding 6). | RECORDED OFF MASTER |

---

## 6. Strengths (genuine)

1. The geography gate worked. At 18:21:49Z it saw `blocked=true` and failed closed before credentials,
   wrote an immutable receipt, and spent the attempt namespace (`mm_geographic_eligibility.py:401-435`;
   `geo-failure-stage0-execution-v1.json:56,62`). The failure in finding 1 is what happened around the
   gate, not the gate.
2. The agent's first reaction on 09-06 was exactly right and is preserved verbatim:
   `ATTENDED-PREFLIGHT-BLOCKED.md:30-34` ("changing or bypassing a gate is not a remedy").
3. Evidence discipline on the branches is exceptional: spent attempts are never rewritten, the parent
   `UNKNOWN` receipt was kept rather than fixed, a second independent validation re-derived the bundle
   and checked 39 hashes, and claims are tightly bounded ("This is a **no-fill** lifecycle proof; it
   does not test fills, establish profit, or authorize Stage 2").
4. Money at risk was engineered down to almost nothing: minimum size at the minimum tick (0.005 pUSD),
   post-only, one submit, stop on any fill, 10 pUSD hard clamp inside the adapter, dead-man proven.
5. Structural lock-out of the capture host is real code, not policy: `execution_host.py:296-299,324-328`.
   Credential-by-reference, create-only import, compare-only verification with no secret-derived output,
   and the honest `forensic_erasure_proved: false` in the cleanup receipt are all above hobby grade.
6. The Open-Meteo licensing question is a model of how to close an exposure: term noted, owner shown,
   decision dated, revisit trigger written down.
7. The runbook's privacy stance (never store the operator's location or IP) is principled; the cost is
   that it also leaves the project with no record with which to answer finding 1.

---

## 7. What I could not cover

- The portable PC's host-local originals (`WLive/attempts`, `WeatherPortable/prep-20260906`), including
  the geography receipts of the PASSING attempts. I do not know which country/region attempts 2, 6, 7
  and 9 recorded; by the pattern it was MX/QUE, but that is inferred.
- Whether the production host's Credential Manager still holds the four pilot entries (vault commands
  forbidden), and the contents of `Desktop\.env.txt` (credential-like; not opened).
- The outcome of attempt `pilot-20260906T183459081Z` (v4). I did not open the large qualification JSONs.
- The venue's current geographic-restrictions and Terms of Use text (no network). The statement that
  Ontario is "close-only" is the project agent's 09-06 reading, not mine.
- The remaining ~70 files in the handoff directory, `failed-stage0-20260906T140703Z/`, and
  `scratch/handoffs/venue-candidate-20260906/`.
- Branch item 67 beyond line 500 and the full branch runbook (2,000+ lines); I read heads and diffs.
- Live wallet state since 2026-09-07 01:07Z.

## 8. Open questions for the owner

1. Where, physically, were you and the portable PC on 2026-09-06, and what changed on the network at
   ~09:20 and ~14:22 local that moved the venue's classification from CA/ON to MX/QUE?
2. Does Polymarket treat your account as restricted irrespective of egress (KYC/residency), and have you
   read the current geographic-restrictions and Terms text yourself?
3. What is in `C:\Users\micha\Desktop\.env.txt`? Is it the "separate secure backup"?
4. Are the four pilot entries still in THIS host's Credential Manager?
5. Do you want the L2 API credentials rotated and/or funds moved to a fresh signer while the lane is parked?
6. Should project testing ever again share a wallet with your personal trading?
7. Do you want the 09-06 record (all nine attempts, including the two geography ones) on master?
