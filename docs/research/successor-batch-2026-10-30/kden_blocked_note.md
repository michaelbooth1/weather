# KDEN retarget (lever map rank 7): BLOCKED, LOYO remainder considered, not run

Lane L8, 2026-10-30. A batch note for the coordinator's morning docs batch. It has no ledger row and no run.

- **Item:** lever map rank 7 / LEVER_INVENTORY row 4 tail. This is a Denver model retargeted to KDEN, the venue
  station for Denver events from 2026-10-23.
- **Stated reason:** written before any read, `C:\t\l8tor\kden\kden_reason.txt`, sha256
  `e7d9ce10b8f8191e3b0593545c422915c05d421fe69944e2af9c518f60868c54`.
- **S1 (presence only):** script `kden_s1.py`, sha256
  `c4df95301851d5128faada5abc1d890d3b71ccb07a3db4747e422b93adc5d8af`; output `kden_s1_out.json`, sha256
  `62895cd0ca991197841426db66f7279c80ea5a94c9fa826fa447c4ab4a550b86`. It read timestamps and metadata only, and
  dropped rows after 2026-09-29 local.

## Coverage

| Input | Present locally |
| --- | --- |
| KDEN routine and special METAR | 2021 through 2025 complete; 2026 through 09-29 (273 local dates) |
| KDEN PIT forecast corpora | 5 corpora (one per year, 2021-2025), all complete; 2026 excluded, so no 2026 rows |
| KDEN in NBP | not in the parser station list (v2 fails closed); only 178 unindexed bulletins from Jul-Aug 2026; MG-2 guidance tables carry Denver as KBKF |
| Market data on KDEN settlement | none in the dev window, because KDEN settlement starts with the 10-23 events |

## Kill check

The register (including `99be9e81`), RETRACTED and ledger rows 85-91 have no KDEN entry, so nothing has killed it.
The history family is already measured in NEW_CITY_MODEL_LANE: weather-only OLS+floor on corpus `d519ab1d`, fits
`92fdffe2` and `dd3f032d`. On the 2025 test, 07-12 Brier versus the baseline is -0.022 with a CI that excludes zero.

## Blocking routes

1. **2026 dev weather test.** It needs a 2026 KDEN PIT fetch (a download) or the held caches.
2. **KDEN NBP feature.** It needs a parser station-list change and the capture-host bulletins. Both are B-bound or
   off-limits.
3. **Market or forward-cluster test.** It needs post-10-23 data and a change to B's inputs. Denver is unscored and
   outside MG-2 and B (SoP; `GATE_EXCLUDED_MARKETS`).

## LOYO remainder: considered, not run, no edge power

The only eligible piece was a leave-one-year-out (2021-2025) run on `d519ab1d`. It would only re-check the
robustness of a weather-only result that is already measured. It carries no market or edge power, which the owner
directive of 10-23 requires, so it was not run. The coordinator accepted this on 2026-10-30.
