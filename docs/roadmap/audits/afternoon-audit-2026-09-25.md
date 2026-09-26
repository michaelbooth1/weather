# Afternoon second-opinion audit — 2026-09-25

- **Owns:** the read-only audit of the work done on 2026-09-25 up to ~13:05 ET, its verified findings, dispositions and next moves.
- **Read when:** planning tonight's window, RE-1 sessions 12+, or the wallet reader's landing.
- **Do not use for:** current state ([STATE_OF_PLAY](../../operations/STATE_OF_PLAY.md)).

Auditor: Fable read-only subagent (two public GETs, no authenticated calls, no wallet-reader calls). The production agent
verified the HIGH findings before acting (**verified**).

## Verdict

Today's landings match master with receipts; the status cleanup, W32Time fix and wallet-reader security properties hold. The
unpriced risk was disk: 88a stops itself below 50 GiB and the volume was at 50.9 GiB and falling. Reward terms also changed
intraday (Chicago minimum 100 → 20).

## Findings and dispositions

| Sev | Area | Finding | Evidence | Disposition |
| --- | --- | --- | --- | --- |
| HIGH | Disk / 88a | 88a's own floor is 50 GiB (`critical` → stop; `red` < 60 disables the update-window stream); it stopped 11:16-11:21; 50.9 GiB at 12:50. | `maker_evidence_store.py:48-50`; `status.json` | **verified** (50.85 at 13:13). Reclaimed the six 09-03 `weather-ws96a…99c-publication-transfer` folders (bundles + bare repos; every ref verified on origin; `wt/` clean) → **57.69 GiB**; receipt `data\alerts\reclaim-publication-transfer-20260925.json`. Owner call pending: may 88a's floor sit below the suite floor? |
| HIGH | Tonight | Two bounded suites do not fit; one does at ≥ 52 GiB. | trail | Tonight: pause-flag tests + land, doc closeout, 95b only if ≥ 52 GiB. Wallet reader stays on its branch (served from the workstation; landing buys nothing this week and costs a fleet roll + suite). |
| MED | Rewards | Chicago `rewards_min_size` 100 at 15:01Z, **20** at ~17:05Z (gamma and CLOB agree); CLOB `/rewards/markets` is authoritative. A 75-share resting sell is now reward-eligible. | two public GETs | **verified** (reader showed 20). EF §10m updated; inventory rule 2 must read CLOB at decision time. |
| MED | Wallet reader | `unrealized_pnl_pusd` sums resolved dust (−9,703); `campaign_pnl_pusd` null until `--campaign-capital`. | `wallet_reader.py:56-64` | Split live vs resolved P&L (handoff 100e, workstation); owner supplies campaign capital (equity at the 09-22 campaign start). |
| MED | 95c pause flag | `a38bc86c0` is correct and sufficient (contract dot-sourced at run time; Stage B and the barrier resume carry the result/flag); hardcoding matches "explicit owner-paused". Missing: a consistency guard. | `daily_refresh.ps1:29-33,91`; `daily_refresh_settled_day.py:189-192,370-371` | Land tonight after its focused tests; add a `status.ps1` check that the token matches the paper-maker tasks' state (roll-free, later). |
| MED | RE-1 | `2b9a0ca9e` untested; `extra_conditions.json` absent. | `git show 2b9a0ca9e`; `Test-Path` | Sessions use `d90d0a6e6` unless RE-1 tests pass on the workstation first; write `extra_conditions.json` before each session. |
| LOW | Handbacks | 100c already built (`2b37cae88`, report `dfb84341b`). | branch log | **verified:** default A, panel B 09-25..10-08, `FROZEN_REF` = `0df126491`. |
| LOW | Canon | W32Time line, disk low, audit row stale. | STATE_OF_PLAY | Fixed in this commit. |
| LOW | Scheduler | Many spent one-shots still Ready (`*Reproof*0814`, `*TopicPush0822`, `WeatherArchiveS4U*Probe_20260910`, `WeatherInternationalCredentialImport0822`, `WeatherSnapshotErrorRecovery0818`, `WeatherQuietWindowMerge` 0x1 from 08-01). | `Get-ScheduledTask` | Batch-unregister with XML backups when convenient. |

Wallet reader security verified from code: credential loader never names the private key; one GET gate with exact host/path/query
sets refuses `/balance-allowance/update`, cancel, `/order`, heartbeat, `/auth/*`; no redirects or proxies; journal logs no
headers; server checks token (constant time), source IP and RFC1918 bind. No merge-tool path can commit
`config/local/wallet_reader_client.json` (the drift commit stages only the two fleet config files; `.git/info/exclude` covers it).

## Owner decisions raised

1. Chicago lot: hold, or rest a sell at the ask (now reward-eligible at minimum 20); cancel before any session.
2. RE-1 sessions 12-16 at 20 shares (eligible everywhere, ~73% less fill exposure) vs 75.
3. `--campaign-capital` value for the wallet reader; whether 88a's disk floor may drop below 50 GiB.

## Next 48 h (auditor's proposal)

Verify tonight's pause flag landed and `daily_learning.json` refreshes after 09:30; 100e P&L split; the multi-domain seed as a
pure order-set module (list of {market, side, size, price}, one reserve check, one cancel-all) with fixture tests on the
workstation, making two-band RE-2's first experiment rather than an RE-1 change.

## Unverified

Cause of the 11:20 transient; current campaign P&L (auditor estimate ≈ −16 marked); the minute Chicago's terms changed; whether
the merge tool's recovery proof includes the 88a worker; RE-1 journals.
