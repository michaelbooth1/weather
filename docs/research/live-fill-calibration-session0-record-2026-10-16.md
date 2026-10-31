# Live Fill-Calibration Session-0 Record (2026-10-16): ATTESTED

Owns: the evidence record of LFC session 0, run by the owner on the workstation on 2026-10-16 (UTC) under the
[session-0 runbook](live-fill-calibration-session0-runbook-2026-10-09.md) and the
[session-0 spec](live-fill-calibration-session0-spec-2026-10-09.md). Read when: preparing session 1, or checking what
session 0 proved. Values were sent by master-agent, which guided the owner (runbook §8 "Send to master"). By rule this
record carries no addresses, balances, positions or snapshot contents; owner-private snapshot hashes stay owner-side.

## Outcome

- **Session 0 ATTESTED** about 16:35Z: `session0-attest` wrote `pass.json`, sha256
  `022980219e771a81afdada59b049f531922b72a698a06e2c31280a2f8114c8e9`; `ledger_previous_sha256`
  `3da98fc8fecdaefc174f7d353d71ef26fbf461cccfc5b5be2df2fe47745813d6`.
- Final `verify` (about 16:40Z, after the attestation): `status: PASS`, `session0_passed: true`,
  `session0_attestation` PASS, `counted_sessions: 0`, `session0_runs_missing: []`. `wallet-verify` PASS: S0-1 PASS, S0-6 PASS, venue L 0.00,
  positions `OBSERVED`.
- Final `Compare-T40ToStart` PASS (pilot tokens excluded 10, fills 0).
  - `t40_start`: `baseline-t40-20261016T144223872628Z.json`, sha256
    `6cf734cd97ab3bd567ab547bf9467660a258d67d361f0728e752fd15151c85aa` (T-40 at 14:42Z; baseline PASS, open orders 0).
  - Final t40: `baseline-t40-20261016T163113098143Z.json`, sha256
    `fb8a9d1a24d0c7570d2f4083802c1086dccfaeeecc03deff0ebaae0fc5aa4b68`.
- No fills in any run.

## Inputs

- **Code:** pin `C:\wt\lfc-pinned-e27909a76` at `e27909a764e96931c9ea38d6fba8202af8fc2b67`. The pin's git status stayed
  empty (the owner's client config sits in the gitignored `config\local\`).
- **Market:** event `netanyahu-out-before-2027`, condition `0xd1796c09…8c96`, quotes 0.34 / 0.55, size 5, `neg_risk`
  false on both tokens.
- **Extra conditions:** the 88a file `data\maker_evidence\extra_conditions.json` does not exist on the capture host,
  and 88a reads a missing file as `[]`. The owner approved an empty substitute at 09:16 EDT ("Yes I ok it"). The
  workstation recreated it byte for byte at 09:27 EDT on the owner's word: `extra_conditions-empty-20261016.json` = `[]`,
  2 bytes, sha256 `4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945`. A note,
  `extra_conditions-ABSENT-20261016.txt`, sits beside it.
- **Shadow scope:** `shadow-scope-union --date 2026-10-16` run on the workstation from the pin at 10:20 EDT, public Gamma
  only. It produced `shadow_scope_20261016.json`, sha256
  `0e2fc5206a102d09ef1203e797deb78d1a808e0501eef9a6997c34362af3bee8`, count 528, exit 0 on the first attempt.
- **Wallet reader:** the 8765 reader, pid 98080, running `a1014edab` (any-LAN code) since 10-13. The owner wrote the
  client config into the pin (runbook §3.6 step 3). Step 4 returned `/health` ok and an open-order count of 0.
- **Machine:** Windows Update paused until 2026-10-30, a heavy freeze from 10:00 EDT, and the home tunnel down for the
  session.

## Runs

| Run | Folder / session | End reason | Evidence |
| --- | --- | --- | --- |
| 0a | `S0a-20261016T145355Z` | `fixed_end` | expiry 1792163695 OK |
| 0b | pre-part `preflight-20261016T155010129460Z` (`account_has_open_orders`, S0-4); run `S0b-20261016T160251Z` | `foreign_open_order` | open-order helper read 1 then 2 before the foreign order, then 0; expiry 1792167231 |
| 0c | `S0c-20261016T160844Z` | `reconciled_after_crash`; toast delivered | `READER_QUIET` 16:09:21Z (phase 261, since 99999: helpers re-pasted). `kill_utc` 16:09:21.407Z. `helper_zero_utc` 16:09:34.171Z. Loop 13 s. Last journal row 16:09:20.747661Z. Gap 14 s. Attested S = 14 |
| 0d | `S0d-20261016T161512Z` | `heartbeat_stale` | `DROP_WINDOW` OK, drop 16:17:32Z; loop 10 s. The script cancelled both orders; the `first_terminal` read showed both still LIVE |
| 0e | `S0e-20261016T162158Z` | `l_budget_refused` | no submit |
| 0f | — | skipped (optional) | — |
| 0g | `S0g-20261016T162551Z` | `venue_deadman_cancelled` | `DROP_WINDOW` OK, drop 16:28:11Z. `seconds_after_drop` 12.375. `own_cancel_requests_since_drop` 0. `all_terminal` true. Loop 13 s |

## Finding: the reader cap under closely spaced reads

After 0g, the first `verify`/`baseline` raised `TimeoutError`, and `wallet-verify` returned venue L as `ERR`. Three
closely spaced reader reads overlapped the capture host's journal burst at :30. The reader is serial, with a rolling
cap of 30 attempts per 60 s (see [wallet reader](../operations/wallet-reader.md)). A retry after `Wait-ReaderQuiet`
was clean.

**Rule for later sessions:** run `Wait-ReaderQuiet` before each post-run read (`verify`, `wallet-verify`, `baseline`),
and treat one `timeout` or `refused` as a cue to wait and retry, not as a halt. Earlier that morning (09:27-09:28 EDT),
untokened probes also showed 4-15 s queueing while the reader served other callers.

## Next

Session 1: 10-18 or later, on its own pin `6bc6f2bec` (`claude/lfc-hardening-r2-20261014`), with a fresh preflight and
its t24 the day before (runbook §1). Its pin and date are DECISION_LOG rows.
