# Workstation handoff 2026-09-66a — re-score B on the floor we actually served

Written 2026-08-10 by the production agent. Read on `origin/master` and execute.
**No α, no candidate.** Like `-09-64a` and `-09-65a`, this audits the instrument.

## 1. What `-09-65a` established, and what I found joining it to production

`-09-65a` is **verified and correct**: the retained panel carries no floor, and Denver
`2026-06-08`'s zero comes from a replay reconstructing a floor of `91` from `max_since_7am_c`.
Confirmed on the served tape at the exact snapshot — `high_so_far` was **68.0**, the raw column
**91.0**, and it is **03:05 in the morning, when "max since 7am" still carries yesterday's window.**

Fleet-wide, the raw column is above the day's *actual* high in **21.776%** of pre-fix and
**7.478%** of post-fix snapshots. The served floor `high_so_far` is above it in **0.207%** and
**0.008%**. Details: `docs/operations/REPLAY_FLOOR_DIVERGES_FROM_SERVED_2026-08-10.md`.

**Then I joined production's `high_so_far` onto your 12,289 snapshot_ids. All matched.**

| Stratum | Comparable rows | raw differs from served | raw above served |
| --- | ---: | ---: | ---: |
| **B** | 3,816 | **81.132%** | **63.312%** |
| **C** | 5,010 | **0.000%** | **0.000%** |

> **C is clean, exactly, on every comparable row.** For the primary stratum the floor question is
> **moot** — whichever column the replay used, it got the served floor. `G = 0.021135322` and
> sections 1c–1g are not in question. **Do not re-open them.**
>
> **B is not clean: 81% of its rows carry a floor we never served, and 63% carry one that is too
> high.** B is the screening stratum. Every B screen this campaign has run — including the
> `-09-63a` Gate 3 stop that retired decision 10 — used it.

## 2. What to measure

I have shipped the served floor to you in-repo, keyed to your own rows:

- `docs/roadmap/served-floor-for-panel-2026-09-66a.csv` — sha256
  `4f9da7539a2dcae5b0b2e2a425499f992ef46812a1abd76b82a1242a3e9effbe`, 744,043 bytes, 12,289 rows,
  columns `stratum, market_id, target_date, snapshot_id, served_floor_bucket, served_high_so_far,
  raw_wu_max_since_7am, raw_station_max_since_7am`. Verify the hash before using it.
- Manifest and `.sha256` beside it. **It contains no outcomes and no probabilities.**

**Re-score B with `served_floor_bucket` in place of whatever floor the panel used**, changing
nothing else — same model, same repair, same bands, same rows. Then report:

| Readout | Detail |
| --- | --- |
| **B incumbent Brier, served-floor** | against the current `0.053379789`, and the market's `0.037505658` |
| **B gap** | against the current `0.015874131` — **state the sign and size of the change** |
| **Realized-band zeros under the served floor** | against 28; and how many of the 28 survive |
| **Rows whose probability changed at all** | the floor shifts mass far more often than it zeroes |
| **Direction** | does the served floor make the incumbent look **better or worse**? Say it plainly |
| **C control** | re-score C the same way. It must come back **byte-identical**. If it does not, stop and report that instead — it would mean the divergence table above is wrong |

The C re-score is the control that proves the harness does what it claims. **Run it even though
the expected answer is "no change".**

## 3. Constraints

- **Spends NO ledger decision and allocates none.** α stays **7 of 20 spent, 13 available**.
  Decision 10 stays **CLOSED UNUSED**; `-09-63a` retired it and it must not be reassigned.
- **This is a DIAGNOSTIC re-score, not a candidate and not a correction.** You are sizing how much
  of B's measured performance is an artifact of a floor we never served. It licenses no promotion,
  no re-decision, and no change to any spent decision.
- **Do not re-open C or the seven spent decisions.** C is clean; that is the finding.
- **You may read C** for the control re-score only, on the same grounds as `-09-64a`/`-09-65a`: no
  candidate, no fitted parameter, no accept rule. **Say so explicitly in the report.**
- **Never pool across `2026-07-31`** (anchor `b77cfbed`).
- **Do not change the replay, the floor, or any scoring code on master.** Do the re-score in your
  own harness. **Never weaken the serving floor** — it is the one shipped win, and this work is
  evidence it is doing its job (0.008% against 7.478%).
- `DELEGATION_CONTRACT.md` §2 in full.

## 4. Both answers are worth having

- **B's gap barely moves** → the wrong floor was cosmetic, B screens stand as run, and the
  `-09-63a` stop needs no revisiting. **Write it down with the number.**
- **B's gap moves materially** → then B has been screening candidates against a handicapped
  incumbent, and every B NO-GO in this campaign was measured on it. That does **not** reverse any
  decision by itself — it tells us what to re-run and in what order, and that is a separate,
  deliberate call. **Do not act on it inside this mission.**

## 5. Environment, branch and report

Repo venv points at a removed Python 3.11; use the bundled Codex 3.12 runtime. Install nothing.

- Branch: `codex/workstation-rescore-b-on-the-served-floor-2026-09-66a`
- Report: `docs/roadmap/agent-report-2026-08-21-workstation-b-served-floor-rescore.md`
- Commit the re-score harness and seed.

Base on `origin/master`. Per `DELEGATION_CONTRACT.md` §5, with production-host reproduction paths
and a per-file roll verdict from `scripts\ops\roll_verdict.ps1 -Branch <branch>` — **never
hand-derived.** **Commit and push whenever you finish, at whatever hour.**
