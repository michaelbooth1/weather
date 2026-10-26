# NBS cycle-label check: is the dev 95% exact match labelling or a v5.0 product change? (inputs only)

Approved by the coordinator on 2026-10-26 as outcome-free. There is no rule and no verdict changes: the R-L2 kill and the
R-L3 drop stand.
- **What was read:** NBS station blocks and NBP PIT corpus rows only, dated no later than 2026-09-29. No label,
  outcome, price or market row was read.
- **Script:** a scratch script outside the repo, sha256 `44717a5151a3f4ffb67cfbc2260e716fed97d847a4d42738307d6122d2c56c60`. It
  parses blocks with `rl_parse_block`, and every block was sha-verified against the manifest.
- **Output:** `C:\t\l2\nbslabel\nbs_label_check.json`, sha256
  `6f19e12e525931a12fcd60a3a4fe525ff11195506b01ad7d45ac7bd89ddb947e`.

## Method

For every NBP row (dev: all 682; training: every second of 7,425), the TXN in the NBS column valid at
target+1 00Z was read from:
- every NBS cycle on the target date (training: cycles 04-12Z only);
- the evening cycles of the day before.

Each TXN is compared to the NBP 07Z mean, and to the same row's NBS 07Z TXN.

## Labels are correct

| Check | Dev (v5.0) | Training (v4.0-4.3) |
| --- | --- | --- |
| Block header issuance equals the file's cycle | 10,912 / 10,912 | 37,097 / 37,097 |
| Header station equals the manifest station | 10,912 / 10,912 | 37,097 / 37,097 |
| Object key (`/HH/`, `.tHHz`) equals the manifest cycle | 992 / 992 | 6,885 / 6,885 |
| Header version string | V5.0 only | V4.0, V4.1, V4.2, V4.3 |

The median `last_modified` lag after the nominal cycle is 40-100 minutes in both halves. The longest lags fall on the
major cycles: dev 07Z 77 min, 12Z 97 min, 19Z 77 min. No cycle is published before its nominal time.

## v5.0 product change: TXN is carried forward from 07Z

| NBS cycle (target date) | Dev v5.0: TXN equals own 07Z TXN | Training v4.x: TXN equals own 07Z TXN | Dev: exact match to NBP 07Z mean | Training: exact match to NBP 07Z mean |
| --- | --- | --- | --- | --- |
| 04-06Z | 0.575 | 0.744-0.840 | 0.575 | 0.341-0.351 |
| 07Z | 1.000 | 1.000 | 0.953 | 0.342 |
| 08Z | 1.000 | 0.856 | 0.953 | 0.346 |
| 09-12Z | 1.000 | 0.684-0.699 | 0.953 | 0.328-0.334 |

By version, the training exact match to the NBP mean at 07Z is:

| Version | Exact match |
| --- | --- |
| 4.0 | 0.230 |
| 4.1 | 0.445 |
| 4.2 | 0.377 |
| 4.3 | 0.428 |

No v4.x cycle exceeds 0.452. NBP means are integers in every version, so rounding does not explain the dev match.

## Reading

**What changed in v5.0.** The hourly NBS cycles 08-12Z repeat the 07Z TXN in every row, and the 07Z TXN equals the NBP
07Z mean in 95% of rows. In v4.x, the 08-12Z cycles revise TXN in 14-32% of rows, and TXN agrees with the NBP mean only
23-45% of the time at any cycle.

**Effect on R-L2.** At cutoff hours 07-12, R-L2's dev NBS input was therefore close to a copy of the NBP anchor.
- In training it was a partly independent signal.
- This is a train/serve distribution shift caused by the product. It is not a cycle-labelling error.

**What this means for the verdict.**
- No RETRACTED or ledger labelling note is needed.
- The R-L2 kill text stays as written. If the coordinator wants the mechanism recorded, a one-line addition would be:
  "dev gap≈0 is a v5.0 NBS product change (08-12Z TXN carried from 07Z, matching NBP 07Z mean); labels verified".
