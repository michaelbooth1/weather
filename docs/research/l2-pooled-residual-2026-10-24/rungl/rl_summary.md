# R-L result (lane L2), 2026-10-26: STOPPED at gate 1a (parity, training half), not a kill

**Rule:** `rule_rl.md` (sha `3ce9a6f2403c68b543c13be2ea36d4b92cd711b3e9e544a92e79744db53ca9b8`).

**What the stop means:**
- Gate 1 is inputs only. The rule says a gate 1 failure stops R-L **without a kill**.
- Nothing was fitted or scored: no LOYO and no dev step.
- No NBS value was joined to an outcome.

## What failed

| Check | Result |
| --- | --- |
| Coverage (`n_miss` = 0) on the 19,657 h07-12 training rows | **0.433** (8,517 covered); threshold 0.95: **FAIL** |
| Block sha256, header identity, parse, TXN range | 0 failures: pass |
| Column check: median \|`n_txn` − nbm_mean\| | 1.0 °F (≤ 3): pass |

**Every miss is `column_absent`:** 11,140 rows, and nothing else.

## Why (a data-format fact, read from inputs only)

**NBS drops a day's TXN maximum from cycles issued after that day's maximum period has begun.** In the delivered
blocks (CYYZ, 2023-08-15):
- **09Z cycle:** `TXN` is printed in the 00Z Aug 16 column (72). That is the Aug 15 maximum.
- **13Z and 15Z cycles:** that column is blank. The first `TXN` is the following minimum (62).
- **12Z cycle (2021-08-01):** still carries it.

**The consequence:**
- The rule takes the newest cycle available 10 min before h:00 and marks the row missing when its 00Z (d+1) column
  has no TXN.
- That cycle is 13Z or later for most of 07-12. For example, 10:00 EDT = 14Z.
- So those rows are missing by construction, not because of upstream gaps.

**The other gap is handled.** The 2022-09-04 09Z truncation (11 US blocks `station_absent`) took the next-older
eligible cycle, as the rule says. It is not part of the shortfall.

## What would be needed (not done; needs a ruling)

- **The fix:** a rule that selects the newest eligible cycle **that carries the target day's TXN** (in practice the
  newest ≤ 12Z cycle). This is a change of cycle rule.
  - Rule R-L forbids it ("No other … cycle rule").
  - R-L was not killed, so a new pre-registered rule (for example R-L2) is required.
- **Why that needs owner or master approval:**
  - The fix is chosen from the input format, not from any outcome.
  - But it changes what the feature measures. At late cutoffs it becomes an older (≤ 12Z) TXN.
  - R-H hypothesis 2 asks for a *fresher* centre, which this cannot deliver after about 12Z.

## Files and inputs

| Item | sha256 |
| --- | --- |
| NBS 2021-25 `SHA256SUMS` (pinned) | `2c5fc33a62a72b8d5b7aab7f44c4924571b96c9f4b15e1da5731a452c4867b86` |
| NBS 2021-25 `manifest.jsonl` | `f7aee19b8194f722ace64d51fa30eaf310e9a8a8be0fe308d5ba31d4c24e7e71` |
| NBS 2026 dev `SHA256SUMS` (pinned; not read, because the run stopped first) | `dd2b7ac4227ee3b9d3345f1e84b81e0f8fcbe4648688e54f0b09e92e6ade7887` |
| `C:\t\l2\rungl\loyo\rl_loyo_audit.json` | `adcc8b2ad73e3ce1c1b10fda5d3130efd644d00c877407bb12c1e48bd25d1c23` |

- **Code:** branch `claude/rung0712-20261025` @ `1dd4145a1` (the run). The dev emit and score added after it are at
  `ceae734d1` and are unused.
- **Run tree:** `C:\wt\l2run` @ `4809e7c3a` (local).
- **Wrapper:** `workstation_heavy.ps1 -Queue`, with PREGATE_HOLD absent.
