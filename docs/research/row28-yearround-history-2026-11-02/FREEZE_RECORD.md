# Row 28 — freeze record

This record governs the Status line of `prereg_row28.md`. That line still reads "DRAFT, NOT
FROZEN"; it is superseded by this record, and the prereg itself is not edited after the freeze.

## Frozen artefact

- **Prereg:** `prereg_row28.md`, sha256
  `cb6d4e8da0ab5a144a185cf8dbaf777881402ea8a95db99f2a0e98f20a5e132b`.
- **Tip:** `2a0b3ffbac16a245123f288587e5d7857842e642` on
  `claude/row28-yearround-history-20261102`.
- **Frozen by master:** 2026-11-03 02:25:03 EST (master's host-logged Get-Date). Relayed to the WS
  (lane L59) at 2026-11-03T02:25:21.6934278-05:00 (WS Get-Date at receipt of the relay).

## Inputs bound by the freeze

| Input | Manifest | sha256 |
| --- | --- | --- |
| NBM NBP 07Z Dec–May + 01Z/00Z add-on | `manifest_nbp.json` | `2948b7180f54b0aa413360553d82851a3e3610cf1a3576104422d346259b6f5f` |
| R-P2 IEM extension, Dec 16 – Jun 1 windows | `manifest_iem.json` | `17aca6d162316aeb4b391cd145ca830578e8191e1a49a878bb6e93ed699ad61f` |
| NBM gap 07Z, Jun 1 – Jul 31 and Oct 1 – Dec 16 | `manifest_nbp_gap.json` | `02e5e8cbe67839ff3d8c68de4ea3633d28f97e9f24439078a6dd9010ba501c7b` |
| IEM gap, May 31 – Dec 17 windows | `manifest_iem_gap.json` | `bdf84209d1ef99c2cff74caf0b81201b63e873944fd2cb8607dc9277fa9fb402` |

All four manifests are held locally under `C:\t\L59\row28\fetch\` (ignored local data).

## Deciding dates

- `deciding_dates_r4.txt` with CRLF line ends (as first written and as produced by
  `scripts/row28_deciding_dates_r4.py`): sha256
  `6913484a6abb1c7f0f2083eef919699cb2f05670c52306b2ab96998e0d84bcfb`.
- The same file as committed in this folder, with LF line ends: sha256
  `a2f601baef06dc662bedb710f53392f29da826c0eaede83182311768b3105b29`.
- Master verified on the host: re-CRLF of the LF file gives `6913484a…`; 660 lines;
  2024-02-29 present; 2024-03-01 absent.

## B-guard

PASS. `Test-BBoundHead` against origin/master `b7071ccfe`: Refuse=False, 0 hits, 0 warns.
Master also verified that the diff since `ead57fe7c` touches only this folder.

## Ruling (1) — underpowered labelling (extends §8.4; governs)

Master's ruling on r4, given after the coordinator's 21:36 report of 2026-11-02, verbatim:

> "My rule: a non-passing result on an underpowered run is INCONCLUSIVE-UNDERPOWERED, not
> KILL. The lever stays open, with a reopen trigger (more seasons or a forward lane). [...] A
> true KILL needs either adequate power at the observed κ, or a point estimate that crosses
> the futility line, as the prereg defines it."

**Extension, 2026-11-03.** Master ACCEPTS "adequate power = P ≥ 0.80" (§8.4) as master's
ruling. So the 2.19–2.93×σ_eff band is also INCONCLUSIVE-UNDERPOWERED for a failure-to-show
condition. Reason: the row was designed at MDE80, and the crossing conditions still KILL a true
null at any power. At d = 0, P(point > −0.00285) ≈ 0.89–0.95 across the bands.

The "Master's rule" bullet in §8.4 is a paraphrase. Where they differ, the quote above
governs.

## Ruling (2) — erratum, no sha change

In §14, the r4 note's "and the 2024 leap day" means **2024-03-01**, the date that no centre
window reaches in a leap year. §1.1 and `deciding_dates_r4.txt` govern. **2024-02-29 is a
deciding date** under Rule L (§3.2).
