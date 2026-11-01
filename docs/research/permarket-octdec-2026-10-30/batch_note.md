# Oct-Dec LOYO batch note (X13, X18, X20, X36), lane L3, 2026-10-30

Batch relayed by the coordinator on 2026-10-30. This note records the kill check. It is history-only, reads no
dev-window data, and makes no edge claim.

| Item | Disposition | Citations |
| --- | --- | --- |
| X18 R-G (trajectory columns) | **ruled out by family, not run** | successor proposal `ef761fec0eec6716c0625a0ec8d0a59b7b917486c8eb6f0caa05d19a734ba458` §1 (EXCLUDED); register X66-X70 (trajectory/tracking killed 10-30); RATE-0712, ledger row 81; reopen only via the frozen RISE-T3R3 replication, ledger row 80; coordinator ruling 2026-10-30: no override |
| X20 R-J (trajectory columns) | **ruled out by family, not run** | same citations as X18 |
| X13 L9 ladder (overnight low, dewpoint) | **covered by family, not run** | R-ODC Oct-Dec 07-12, ledger rows 65, 69, 70; C1 on the SM-L6 incumbent, ledger row 85 (DROP); dewpoint already in L6 OWN; MET-DEWDEP killed against the market, ledger row 78 |
| X36 R-M (per-market centre shift) | **eligible: ledger row 92** | rule `rule_rm_octdec.md` in this directory |

Gates for the run (row 92):
- §10w: met by construction, as for row 85 (no forecast_history, open_meteo_archives or reanalysis reader).
- No rebuild: pinned existing inputs only; a399941e is not needed.
