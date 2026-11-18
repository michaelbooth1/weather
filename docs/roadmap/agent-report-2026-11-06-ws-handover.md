# WS Claude handover, 2026-11-06

Written by the workstation (WS) Claude coordinator on the 32 GB non-capture PC
before it goes idle. Codex now owns WS implementation work. This note is a dated
snapshot; [the state of play](../operations/STATE_OF_PLAY.md) and the
[decision log](../operations/DECISION_LOG.md) stay the owners of current state
and decisions.

## Owner instruction recorded here

Owner, in the WS chat, 2026-11-06, verbatim: "Deploy the wallet, include it in
handover notes". The deploy is done and verified (below).

## In-flight items

| Item | State | Where | Exact refs |
| --- | --- | --- | --- |
| LFC F0 positions-v2 fix | FINAL; pregate PASS 15:44 ET; Codex T004 merges it with F2 | branch `claude/lfc-f0-positions-v2-20261106`, worktree `C:\wt\lfc-f0` | head `f531395522d0b0a37495185b2750164008fe586a`; receipt `C:\Users\Michael\Documents\github\weather\data\pregate\pg-f531395522d0-20261106T143255-53296\receipt.json`, sha256 `b363876e36960e5aec3b330cfd900cd309ad2171bed7c8f48f1d08b93cd6dc99` |
| Locked F0 execution worktree | created and `git worktree lock`ed; client config copied 16:54 ET (see below); G13 client check (b) PASS 16:55 ET | `C:\Users\Michael\Documents\github\weather-lfc-f0-f5313955` | detached at `f5313955`; non-zero token map 147 tokens, sha256 `9b0f7c6e2a167794e9789e3f86193acc2935b0ba8e7a3774258e4cba683cd58b`, equal to the host reader v2.1 read |
| Wallet reader v2.1 | DEPLOYED by the owner ~15:58 ET; host read PASS 15:59 | branch `claude/wallet-reader-v2-20261106` (`C:\wt\wallet-reader-v2`); live worktree `C:\Users\Michael\Documents\github\weather-wallet-reader-107cafaf` | `107cafaf9aa32f2130cb3beba12a7bee8a75eeba`; task `WeatherWalletReader` S4U, serve `--bind 192.168.1.106 --port 8765 --signature-type 2`; journal `<worktree>\data\wallet_reader\` |
| Reader rollback | kept, not running | `...\weather-wallet-reader-06bda67e` (v2, cursor bug), `...\weather-wallet-reader-a1014eda` (v1 Data API, now 410) | re-register from either worktree with the same elevated block |
| Probe evidence | read-only, done | `C:\t\pilot1109\f0\probe-20261106.json` | dust probe: `filter_amount=0` keeps the 0.1-share floor |
| F2 design | committed on this docs head | [maker-pilot-f2-design-2026-11-06.md](../research/maker-pilot-f2-design-2026-11-06.md) | `1a7edb0a5` |
| re1_payout_evidence port | handed to Codex T012 | `C:\t\codex\T012*` | off `f5313955` |
| WS-3 receive | Sat 11-07 AM after master's count, only if it fits by 12:00; otherwise Codex | master decides | none |

Low items, not for Monday (master's v2.1 review): surface
`zero_size_positions_dropped` in `payload["plan"]`; tidy the F5 code tag and the
doc line "one per further 500 rows".

## Owner approvals, 2026-11-06 (closed)

Master ruled ~16:5x ET that the two quotes below together are a valid session-1
money re-yes and a valid yes for the ruling-11(a) reward reads. Master adds the
decision-log row.

- **The WS ask, posted ~15:47 ET in the WS chat.** It gave the owner this wording
  to send, verbatim: "I approve the Monday 11-09 live MM session 1 on F0 head
  f531395522d0b0a37495185b2750164008fe586a (pregate PASS), on the 10-26 terms:
  20 shares per leg, one band, TOR+DEN; $100 L ledger, $25/day, stop at $50
  realised; GO 11:00 EST, latest go 12:50 EST. I accept the dust deviation:
  holdings under 0.1 share are invisible to /v2/positions, so the closing check
  cannot see them."
- **The follow-up ask, posted ~16:37 ET in the WS chat.** It asked for the
  ruling-11(a) reads on Tue 11-10 and Wed 11-11 ~12:00 ET, and the client config
  copy into the locked F0 worktree. It closed: "Still waiting on you as well: the
  money re-yes for Monday, in both chats."
- **Owner, WS chat, ~16:54 ET, verbatim:** "approval all, why can't you copy it
  yourself".
- **Owner, master chat, 16:52 ET, verbatim:** "confirmed".

**G13 copy.** The owner's second clause directed the WS Claude to make the copy.
At 16:54 ET it copied an existing local `wallet_reader_client.json` byte for byte
into `C:\Users\Michael\Documents\github\weather-lfc-f0-f5313955\config\local\`.
Three local copies had identical hashes. The contents were never read or printed,
and the copy was checked by hash only. The target is git-ignored, and the
worktree stays clean.

Master reads that clause as letting agents copy local credential-config files
the same way: by hash, unread, and never into a tracked path.

**Check (b), 16:55 ET, PASS:**
- `summary`, `positions` and `trades` (since now-24 h) each returned a well-formed
  object with no client error.
- `open-orders` returned an empty list.

Master: Monday's prerequisites are complete, apart from the owner's Sun 12:00
t24 step and the Mon 10:20 console.

## Owner decisions, master chat, 2026-11-06 ~18:53 ET

Owner, verbatim (relayed by master; master adds the DL rows and the SoP update):
"yes approved no manual trade approve 2 and 3".

1. **No manual trades.** On Mon 11-09 the account is exclusive to session 1, so
   every account fill, reward and rebate for UTC 2026-11-09 may be treated as the
   session's. Any non-F0 order that appears makes the affected quantities NOT
   QUALIFIED; nothing is allocated silently.
2. **Session 1 is simulator-calibration evidence.** Declared NOT QUALIFIED up
   front: the competing-maker reward census, native public execution IDs, and
   global fee/rebate denominators. Session 1 cannot qualify an edge on its own.
3. **MG-1 is amended before its look.** The primary mask becomes outcome-blind
   (B Clarification 8): admitted coverage, exactly one venue winner, and a frozen
   label key; WU/venue reconciliation is not a condition. The old mask stays only
   as a frozen sensitivity that decides nothing. Codex T020 drafts Clarification 4
   and the code (`codex/mg1-clarification-4-20261106`, due Sun 18:00, lands after
   Monday).

## Capture host address, 2026-11-06

The capture host's Wi-Fi dropped at 17:06 ET. The owner moved it to Ethernet, and
it is now `192.168.1.192`; `192.168.1.247` is gone.
- The owner stored the workstation SMB credential for the new address.
- Master repointed the WS `production-pc` SSH alias and the MG-2 pull task, which
  now passes `-ShareRoot "\\192.168.1.192\mg2-inputs"`.
- Host transfers use `\\192.168.1.192\xfer`.

## Open items

1. **Session-1 rewards reads on D+1 and D+2.** Approved (above). Originally the
   owner was to read them, or the WS with the read-only client on the owner's
   WS-chat yes (master ruling 9, DL 2026-11-06). Master ruling 11 (2026-11-06 ~16:4x;
   master adds the DL row) sets the path:
   - (a) **Primary record, must not slip:** on the owner's yes in the WS chat
     and a confirm in the master chat, the WS runs the deployed v2.1
     read-only client `rewards --date 2026-11-09` once on Tue 11-10 ~12:00 ET
     (D+1) and once on Wed 11-11 ~12:00 ET (D+2). Outputs go create-only to
     `C:\t\pilot1109\rewards\2026-11-09-d1.json` and `-d2.json`, each with a
     sha256 sidecar. No new pin, no Scheduler, no code. Whoever runs it (the
     WS Claude if its session is open, otherwise a Codex task from master)
     does exactly that and nothing else. How long the venue keeps per-date
     accruals is unknown, which is why these reads are the primary record.
     The client config is in place in the locked F0 worktree (the G13 copy);
     run the client from there.
   - (b) REWARD distributions and MAKER_REBATE for 11-09 are taken on or after
     11-11 from the F2 R3/R4 recording-only pin (D7), from the append-only
     `/v2/activity` history.
   - (c) Held as a fallback only: if (a) fails, master brings the cross-check
     use of the host journal's pilot-condition `/rewards` rows to the owner
     (DL 2026-11-05 row on the manual order journal is the owner's).

   On F0, no LFC module reads rewards or rebates (`lfc_cli.py:88-119` modes;
   `lfc_fees.py:181-199` records only the fee-schedule `rebateRate`), and the
   RE-1 payout verdict (`re1_payout_evidence.py`) is not on the LFC path.

## Owner's steps

- **Sunday 11-08, t24 (about 12:00 EST).** The session-0 runbook's T - 24 h
  step: `Save-OwnerSnapshot t24`, then `& $python -m weather.market.lfc_cli baseline --label t24`
  from the locked F0 worktree. It must fall 20-30 h before the go (latest about
  14:20 EST for an 11:00 Monday go, per master). No reader restart or WS reboot
  from Sun 11:45 (WS freeze, master ruling 10).
- **Monday 11-09, console 10:20-11:00 EST.** The T - 40 min step at 10:20:
  `Save-OwnerSnapshot t40`, `shadow-scope-union`, then `baseline --label t40`
  and the session-start baseline; first preflight and go at 11:00 EST. Dry run
  08:15-09:00; end by 17:00. WS freeze Mon 08:00-18:00.

The commands are in
[the session-0 runbook](../research/live-fill-calibration-session0-runbook-2026-10-09.md)
(T - 24 h and T - 40 min rows) as amended by Clarification E and the 10-28
errata; master owns the session-1 timetable.

## Where Codex works

Codex tasks T000-T012 and their briefs live in `C:\t\codex\` (standing brief
`C:\t\codex\COMMON.md`), on `codex/*` branches and `C:\wt\codex-*` worktrees.
`C:\t\codex\HOLD_HEAVY` was released after the F0 pregate (moved to
`C:\t\pending-owner-delete\`, not deleted).

## WS Claude going idle

The WS Claude closes its subagents and starts nothing new after this docs head.
It stays available as the owner's guide in the WS chat. Its private checkpoint
`C:\t\WS-CHECKPOINT.md` and running log
`C:\wt\workstation-chat\l-data\WORKSTATION_STATE.md` are aids, not project
truth.
