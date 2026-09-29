# Agent report 2026-09-111f amendment 1 — share(t) from the RE-1 journals alone

Follows the [111f report](agent-report-2026-09-111f-reaction-diagnostic.md) after the production review:
- The RE-1 journals record our modelled share every minute, so share(t) does not need 88a overlap.
- The review asked for a `reaction --source re1-only` mode, run on this workstation's RE-1 journals.
- **Owner approval, 2026-09-29 (in chat):** read the journals on this workstation read-only, including the live
  campaign folder `%USERPROFILE%\.weather-re1m-20260921` (sessions 1-12). Do not copy or move them. Commit only the
  aggregate summary.

Branch `codex/reaction-diagnostic-20260930`. Evidence: `agent-report-2026-09-111f-reaction-diagnostic-amendment-1.json`
(sha256 `c33447f5a2ff49912759241b548fe7d16f0442b55db0891fbf9edbabfb66b1cb`). It holds aggregates only:
- no journal rows;
- no condition, token, order or wallet identifiers;
- bands relabelled `band-N`.

## Verdict

**ESTIMATED: competitors take about a third to a half of our modelled reward share within the quoting hour.**
- Against our share in the first minute after posting, pooled k over a 60-minute horizon is **0.67**:
  - 95% interval 0.28-0.80;
  - 9 episodes, 8 sessions, 7 bands;
  - 3 UTC dates × 4 markets.
- Against the selection-time share (the book before our quote), k is **0.54** (0.30-0.79, 8 opening episodes).
- The replay assumes k = 1. **The upper bound of both intervals is below 1.**

The 88a-overlap mode stays as built. Its expected NO_OVERLAP is now confirmed by folder timestamps alone: the last live
session folder (`session-12`) was last written 2026-09-25 02:23Z, before 88a began capturing at 06:34Z.

## Measured values

- **Source:** the per-minute `share_many` that the attended runner recorded in each live session.
  - This is 84b scoring of the public book, with our own size removed and a size-cutoff midpoint.
  - It is a modelled share, not a venue share. [EF §10m](../operations/ESTABLISHED_FINDINGS.md) found it right in
    scale against venue accrual.
- **Episodes:**
  - An episode starts at a posting that follows more than 60 s without one.
  - share at posting = the first minute sample within 120 s.
  - k = Σ(episode mean share over covered minutes) / Σ(baseline share).
- **Interval:** crossed date × market bootstrap, 2,000 reps, seed 20260930, 1,935 draws defined.
- **Sessions:** 12 found, all `mode: live`, none refused, none outside the allow-list (2026-09-22..26).
  - Four sessions had no minute sample: session-3 posted nothing; sessions 2, 7 and 11 ended within 20 s.

| Baseline | Episodes | k pooled | median episode k | 95% interval |
| --- | ---: | ---: | ---: | --- |
| share at posting, all postings | 9 | 0.667 | 0.488 | 0.283-0.797 |
| share at posting, opening postings only | 8 | 0.671 | 0.519 | 0.283-0.806 |
| selection-time share, opening postings | 8 | 0.538 | 0.409 | 0.296-0.788 |

share(t), mean `share_many` by whole minute since posting. The full 60-minute table is in the JSON.

| minute | 0 | 1 | 2 | 3 | 5 | 10 | 15 | 20 | 30 | 45 | 55 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| mean share | 0.518 | 0.489 | 0.337 | 0.355 | 0.262 | 0.266 | 0.127 | 0.162 | 0.143 | 0.167 | 0.090 |
| episodes | 9 | 9 | 7 | 6 | 7 | 7 | 6 | 5 | 5 | 3 | 3 |

| session | kind | band | market | date | samples | share at selection | at posting | mean | k |
| --- | --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: |
| session-1 | opening | band-1 | nyc | 2026-09-23 | 42 | 0.181 | 0.164 | 0.067 | 0.408 |
| session-4 | opening | band-4 | miami | 2026-09-24 | 2 | 1.000 | 0.306 | 0.447 | 1.460 |
| session-5 | opening | band-4 | miami | 2026-09-24 | 60 | 0.954 | 0.563 | 0.180 | 0.320 |
| session-5 | requote | band-4 | miami | 2026-09-24 | 17 | n/a | 0.102 | 0.050 | 0.488 |
| session-6 | opening | band-5 | atlanta | 2026-09-24 | 56 | 0.631 | 0.637 | 0.170 | 0.266 |
| session-8 | opening | band-6 | atlanta | 2026-09-24 | 2 | 0.880 | 0.880 | 0.871 | 0.990 |
| session-9 | opening | band-7 | chicago | 2026-09-24 | 13 | 0.939 | 0.975 | 0.878 | 0.900 |
| session-10 | opening | band-8 | miami | 2026-09-24 | 38 | 0.537 | 0.446 | 0.281 | 0.630 |
| session-12 | opening | band-10 | chicago | 2026-09-25 | 60 | 0.560 | 0.586 | 0.166 | 0.283 |

**Positive control:** session-5 (Miami) has a selection-time share of 0.954, which reproduces EF §10m's "95.4%".

## Caveats

- **The pooled k is weighted by baseline share.** The three sessions that ran close to an hour (5, 6, 12) each lost
  about 70% (k 0.27-0.32).
- **Short sessions (4, 8, 9) end within 13 minutes**, before most of the decay, and pull k up. Session-4's 1.46 rests
  on two samples.
- **Small support:** 3 dates, 4 markets, one campaign, all on a fixed ±1.5 c two-sided quote at 20-75 shares.
- **Some reaction may already be in the first sample.** Minute 0 is sampled within seconds of posting, so any reaction
  faster than that is already inside the posting baseline. The selection-time baseline brackets this.
- This is descriptive, not a hurdle input. It changes no estimator.

## Per-file roll verdict

The code changes stay in the new modules `reaction_diagnostic.py` and `reaction_diagnostic_io.py`, which enter no
closure. This amendment and its JSON are docs, also roll-free. The branch's roll sensitivity is unchanged: only the
additive `schema_registry_recent_data.py` row.

## What was NOT done

- The RE-1 journals were opened read-only and never copied or moved. The tool's output went first to a session
  scratch directory; only this aggregate summary is committed.
- No 88a, production or quote-panel data was read. Nothing was registered, merged or scheduled.

## Reproduction (workstation that holds the journals)

```powershell
.\venv\Scripts\python.exe -m weather.market.reaction_diagnostic reaction --source re1-only --read-live-campaign-root `
    --re1-root "$env:USERPROFILE\.weather-re1m-20260921" `
    --date 2026-09-22 --date 2026-09-23 --date 2026-09-24 --date 2026-09-25 --date 2026-09-26 `
    --out-dir <new empty directory outside the RE-1 root>
```
