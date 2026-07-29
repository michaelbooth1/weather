# Workstation handback — 2026-07-29: MM floor decomposed; warm-tier build started

## 2026-07-29d headline

**THE 66 GiB FLOOR IS NOT A CORPUS-COPY REQUIREMENT.** I merged
`origin/master` at `d2d7da082984aac5f24144dd8b0f3ae0fab77cce` and inspected
the frozen v7 analyzer before doing any more cleanup. It already streams one
primary event at a time from the existing read-only mirror binding. It does
not materialize a second corpus and it releases each event result after
writing compact per-event summaries, fills, coverage, and completion state.
The later reduction reads those compact results, not the raw corpus again.

The workload-only admission floor is **54.53 GiB** under the conservative
remaining-work stress case. The operational floor is still approximately
**63.41–68.53 GiB** because the MM workload and live capture share the same
volume and a rewards window needs another 11–14 GiB of capture headroom. The
existing 66 GiB gate is therefore a reasonable midpoint rather than an
80-GiB corpus-copy artifact. Free space was only 56.07 GiB at the Mission 1
decision, so the restructure could not clear the floor quickly and I switched
directly to the item-325 warm-tier build as instructed. No fetch, scoring,
amendment, or further disk cleanup ran.

## What the frozen analyzer reads and retains

The 419-event primary input binding totals 100,704,002,065 bytes
(93.788 GiB). Those bytes are read over time from the existing source and do
not become a new run-root allocation:

| Existing source artifact | Bound bytes | GiB | Mean working input |
| --- | ---: | ---: | ---: |
| `order_books.jsonl` | 73,740,519,894 | 68.676 | 167.839 MiB per primary event |
| price history | 13,707,708,282 | 12.766 | 65.038 MiB per 201 bound events |
| `order_books_summary.csv` | 12,513,716,674 | 11.654 | 28.482 MiB per primary event |
| long snapshots | 734,623,189 | 0.684 | 1.672 MiB per primary event |
| settlement | 7,434,026 | 0.007 | compact |
| **Total** | **100,704,002,065** | **93.788** | **one event at a time** |

The largest single primary-event input is Toronto 2026-06-22 at 871,990,665
bytes (831.595 MiB), almost entirely an already-present 830,084,768-byte
price-history binding. That event plus small accumulators is the peak pipeline
shape already implemented.

The current v7 run root occupies 5,065,384,050 bytes (4.717 GiB), principally
retained provider evidence rather than a corpus copy:

| Retained v7 output | Bytes |
| --- | ---: |
| raw provider API evidence | 2,670,511,420 |
| normalized raw trades | 2,367,090,980 |
| catalogs | 25,661,360 |
| program, receipts, and remaining compact state | 2,120,290 |

The accepted six-event analysis pilot wrote 967,063 bytes for 617 fills. A
straight 419-event projection is 67,533,233 bytes; the admission calculation
reserves 0.75 GiB for analysis even after an 8x JSON/horizon inflation.

## Revised admission calculation

| Reserve component | Normal | Stress |
| --- | ---: | ---: |
| remaining 147-event backfill | about 0.38 GiB | 2.780 GiB |
| analysis outputs | 0.75 GiB | 0.75 GiB |
| frozen rewards raw-page allowance | 0.576 GiB | 0.576 GiB |
| metadata, receipts, manifest variance, and calculation margin | included below | included below |
| **workload reserve** | **about 2.41 GiB** | **about 4.53 GiB** |
| invariant free-space floor | 50.00 GiB | 50.00 GiB |
| concurrent capture during rewards | 11.00 GiB | 14.00 GiB |
| **operational start floor** | **63.41 GiB** | **68.53 GiB** |

The combined rows deliberately retain the admission calculation's rounding
and output-variance margin rather than pretending the point estimates are an
exact allocation. The stress workload alone implies a 54.53 GiB floor. It was
below the 56.07 GiB decision-time reading, but starting there would violate the
50 GiB invariant while live capture continues through the frozen 5:14:45
minimum rewards cadence. The streaming finding therefore does not authorize
an MM resume.

## Volume layout and item-325 switch

The v7 run root, canonical `data`, frozen MM worktree, cool-bias packet, and
this report worktree all resolve to the same NTFS volume:
`\\?\Volume{7fa9b4d0-06a2-48a0-8afa-c02c57cb3bf0}\` (serial
`AAD0-AB1D`, 999,126,200,320 bytes total). There is no second volume on which
a working corpus could be materialized or from which item 325 would provide
an indirect shortcut:

| Volume | Mission 1 free | Latest pre-handback free |
| --- | ---: | ---: |
| `C:` / volume serial `AAD0-AB1D` | 60,199,936,000 bytes (56.07 GiB) | 54,551,932,928 bytes (50.805 GiB) |

The latest reading, observed at `2026-07-29T15:55:17.7817814+00:00`, is
15.195 GiB below the 66 GiB admission floor. The decline occurred while the
build was running and no additional disk cleanup was attempted.

I therefore began `workstation-handoff-2026-07-29c-item-325-warm-tier.md`.
That work is build-only and uses synthetic fixtures. Production `data`, the
mirror, and every frozen MM packet remain unchanged. Its separate handback is
`agent-report-2026-07-29-workstation-item-325-warm-tier.md`.

The exact-empty `eventSlug: ""` amendment remains approved only in principle.
It was not landed because the required 1,619-result equivalence gate still
cannot run inside the operational floor.

## Earlier `-29b` stop

**EARLIER STATE / STOPPED AS DIRECTED.** I merged `origin/master` at
`7417f433fb57a37a9b5740be981ac52cb8fd8266` into the topic branch, kept the
accepted scaled-MM implementation frozen at
`c6319fa12788ab68fd83154205185ae3def695fc`, and executed the `-29b` cleanup
before any further MM work.

Free space was only 31.197 GiB immediately before cleanup. I removed
25.025 GiB of exact, authorized scratch state: rebuildable replay caches,
clean pushed/handed-back worktrees, pytest roots, duplicate dependency
environments, and superseded MM run roots. The drive finished at 56.285 GiB.
That is 9.715 GiB below the handoff's 66 GiB admission floor, so I stopped
again instead of deleting report-bound evidence, any `data/` path, or any
production-data junction.

The frozen v7 backfill therefore remains at 1,619 terminal completions,
17 explicit validation gaps, and 147 valid events left. Mission 2 analysis,
Mission 3 rewards, and cool-bias scoring remain `NOT_RUN`. Item 325 warm-tier
work (`-29c`) remains `NOT_STARTED`, because its handoff explicitly places it
after completed `-29b`.

## `-29b` storage reclaim

The action-bound free-space readings were:

| Reading | Bytes | GiB |
| --- | ---: | ---: |
| before the first unlink | 33,497,219,072 | 31.197 |
| after the authorized set | 60,435,828,736 | 56.285 |
| drive-observed increase | 26,938,609,664 | 25.088 |

The inventory sum is authoritative for what was removed; the small difference
from the drive-observed increase reflects concurrent host writes while the
cleanup ran.

| Authorized class | Files | Bytes | GiB |
| --- | ---: | ---: | ---: |
| three July 22 H1 replay-cache roots | 21 | 20,527,872,905 | 19.119 |
| 12 clean pushed/handed-back worktrees | 19,870 | 5,023,691,707 | 4.679 |
| 17 pytest/environment/superseded-run targets | 38,046 | 1,318,794,780 | 1.228 |
| **Total** | **57,937** | **26,870,359,392** | **25.025** |

The largest single contributor was
`weather-workstation-research-2026-07-22\scratch\workstation-research-output\workstream_a\h1\cache`:
9 files, 19,525,481,808 bytes (18.185 GiB). It was the explicit
`--cache-root` for a fully pushed July 22 report. Its compact reports, result
artifacts, frozen commands, and canonical rebuild inputs were left in place.
Two nested H1 replay caches added another 1,002,391,097 bytes, making
rebuildable replay caches the largest cleanup class at 19.119 GiB.

The 12 worktrees were clean and either exact at their pushed upstream or a
handed-back detached baseline. Their tracked states and branches remain in
Git/remotes; ignored worktree-local temp state is not recoverable from the
Recycle Bin. The pytest roots, environments, and replay caches are likewise
not in the Recycle Bin, but are rebuildable.

Hard exclusions remained untouched:

- the active v7 packet and its 5.065 GB of source evidence;
- the frozen cool-bias packet and every input it hash-binds;
- regime-split, clean-gap, sharpening, deficit, skill-gap, and profit-edge
  result artifacts that support pushed report numbers;
- the active MM code worktree, current report worktree, live-canary worktree,
  and unpushed model-learning worktree;
- remaining pushed evidence beneath the July 22 research worktree;
- every `data/` root, mirror path, and junction targeting production data.

No real-data file was applied, deleted, moved, rewritten, or compressed.

## Identity-amendment decision

**AUTHORIZED IN PRINCIPLE, NOT LANDED.** The narrowest uniform amendment is to
allow an exact-empty JSON string `eventSlug: ""` to use the already-bound
catalog event identity. The rule would apply to every event. Absent, null,
whitespace-only, and wrong nonempty slugs would still fail. All other exact
condition, token, local-day, transaction, side, economics, outcome, and
deduplication checks remain unchanged.

The four handoff checks currently stand as follows:

1. **Uniform rule:** designed; it is not conditioned on the 17 failures.
2. **Committed before scoring:** preserved. No analysis or held-out score has
   run, and no analysis artifact exists.
3. **Reproduce the existing 1,619:** not yet proven, so the amendment has not
   been accepted. The frozen baseline is 1,619 receipts (1,618 positive,
   1 empty), 2,946,985 canonical rows, zero duplicates, 362 local completions,
   and 268 primary completions.
4. **Coverage delta:** unchanged at this stop: 1,619 complete before and after,
   17 explicit gaps, and 147 valid nonterminal events.

V7's predeclaration forbids changing its frozen program in place. Once storage
reaches 66 GiB, the safe sequence is to finish the 147 under unchanged v7,
then build a separately predeclared v8 cache-only packet. Its independent gate
must dual-parse both the original 1,619 and every terminal v7 completion and
require identical rows, canonical IDs, CSV bytes, status, request tree, and
local/primary membership before the exact-empty amendment can recover any gap.
Network must be mechanically disabled for that replay.

Because analysis is still `NOT_RUN`, there is no defensible verdict-change
bound yet. The seven unresolved July 9 primary events could still change tier
selection, so decision authority remains null rather than being inferred from
the complete subset.

## Frozen v7 packet

The active evidence root is:

```text
C:\Users\Michael\Documents\github\weather\scratch\workstation-research-output\mm-scaled-20260728c-v7
```

V6 is preserved separately. It made 46 Gamma requests and exposed a legitimate
historical product-width change before any Data API trade request:

| Cohort | Valid event-days | Conditions per event |
| --- | ---: | ---: |
| 2026-02-03…02-13 | 77 | 7 |
| 2026-02-14…03-15 | 210 | 9 |
| 2026-03-16…07-25 | 1,496 | 11 |

All 516 local candidates remain exact 11-condition events. V7 therefore
freezes eleven as a **local estimand invariant**, not a product-lifetime
Gamma invariant. It admits only the exact date-width schema above; it does not
pad, truncate, impute, or remap historical events.

Key v7 bindings:

| Artifact | SHA-256 |
| --- | --- |
| `predeclaration.md` | `40df3361503d5be3fcbd6d1c6b9e7d09e8dba1022c95be6a525989885fad6472` |
| frozen fetcher | `a10144558d756e8c8cf43f07b6f7ed1d82e4cd12e932ca9bdc36e117b67b140f` |
| frozen analyzer | `05ddd08a67f188bee668372bc4a1bfea8941494403d31663c361d11961a2f9cf` |
| program-freeze receipt | `36c146541b9d58659368e0d26de78ed8d7cc8d2b72556c4599c22a0874c2c457` |
| settlement semantic gate | `80012e478e1b156fba29096c52b466d736aa7e88a694c5e0e6cb0dc144373441` |
| rewards forward design | `326413993d0f38213d548d3bb081bca738a8c37a5a423458eff73d10351560f6` |

Offline checks passed:

- fetcher: 15/15;
- analyzer: 30/30;
- independent verifier: 16/16;
- settlement JSON serialization: PASS;
- independent static/no-network audit: PASS.

## Input freeze

Prepare and quiet-window finalization both passed:

| Binding | Result |
| --- | --- |
| local candidates | 516 |
| primary local events | 419 |
| balanced primary dates | 31 |
| explicit price-history events | 264 |
| full books | 516 |
| full-book bytes | 87,520,295,742 |
| local-catalog SHA | `efc22e1b3f3b12ffe65974bec30f13f38014b7fef20a6b1451548e1688748daf` |
| terminal-binding SHA | `95b6d02e15901c0ce43eb00f558d86c3600b9ff42f8127f35575028f307d2302` |

The canonical `data\` ACL continued to deny Write/Delete to both Michael and
the Codex sandbox identity. No real-data file was created, modified, moved,
deleted, or compressed.

## Fresh Gamma result

The v7 catalog independently reproduced:

| Quantity | Count |
| --- | ---: |
| discovered event-days | 1,796 |
| valid closed event-days | 1,783 |
| invalid/not-closed event-days | 13 |
| valid conditions | 18,885 |
| local candidates | 516 × 11 |

Catalog SHA-256:
`2a0186da190128aadd9ba8ab13e8e3d8395b01859ec7eecbe4f76c9f1c8f52c6`.

The two previously observed Austin/Dallas 2026-07-09 Gamma omissions remained
strict local fallbacks. The 13 invalid events are nonlocal and remain explicit
unknowns.

## Resumable backfill state

At the safe stop:

| State | Count |
| --- | ---: |
| complete/empty terminal event-days | 1,619 |
| explicit validation failures | 17 |
| valid events still not terminal | 147 |
| interrupted event directories | 1 |
| temp/partial files | 0 |
| Gamma logical successes | 46 |
| Data API logical successes | 1,640 |

The single interrupted directory is
`highest-temperature-in-san-francisco-on-july-13-2026`. Cache publication is
atomic; resume revalidates all retained bodies and begins at that event.

There is no terminal backfill manifest yet.

## The 17 gaps

Every failure is the same frozen contract violation: at least one returned
execution has the exact JSON string `eventSlug: ""`. Across the 17 retained
HTTP-200 responses, 271 of 32,340 otherwise-valid rows have that exact-empty
value. None omit the key, use null or whitespace, supply a wrong nonempty slug,
or violate the remaining condition/token/time/economics checks. No row was
relabeled after inspection.

- Ten failures are vendor-only events on 2026-05-14 or 2026-05-21.
- Seven are local, primary, price-history events on 2026-07-09:
  Atlanta, Denver, Los Angeles, Miami, NYC, San Francisco, and Toronto.

Those seven primary gaps mean the current frozen packet cannot yield
decision-grade tier selection even after the remaining 147 events are
fetched. It can still run and disclose partial/descriptive estimates, but its
decision authority must remain null.

Recovering these events requires the separately frozen **pre-score** v8
identity amendment and equivalence gate described above. No policy or
canonical row changed in v7.

## Initial stop and current stop

The run began with 55.311 GiB free and stopped with 50.444 GiB free. Provider
evidence alone now occupies:

- Data API: 2,564,814,070 bytes;
- Gamma: 105,697,350 bytes.

Live capture continued growing the same disk. The remaining backfill projected
through the 50 GiB floor, and the subsequent rewards probe has a frozen
minimum cadence of 5:14:45 plus roughly 590 MiB for a one-page-per-variant
planning allowance. At the observed 50–65 GB/day live data growth, a complete
rewards window also needs roughly 11–14 GiB of capture headroom.

Before resuming, I recommend at least **66 GiB free, preferably 70 GiB**. That
keeps the 50 GiB floor through the remaining backfill, analysis outputs,
37,770 reward variants, and live capture.

The subsequent `-29b` cleanup recovered the full high-confidence authorized
set but ended at 56.285 GiB. The remaining approximately 9.715 GiB cannot be
obtained from the inventoried scope without touching active packets,
report-bound evidence, unpushed work, `data/`, or production-data junctions.
The handoff explicitly says to stop in that state, so no fetch or score was
started.

## MM resume order

Do not resume until a fresh quiet-window host admission proves at least
66 GiB free. Then:

```powershell
cd C:\Users\Michael\Documents\github\weather\scratch\workstation-research-output\mm-scaled-20260728c-v7
& 'C:\Users\Michael\Documents\github\weather\scratch\workstation-research-output\mm-scaled-20260728c\venv\Scripts\python.exe' `
  .\fetch_data_api_trades_scaled.py fetch `
  --min-request-interval-seconds 0.5
```

Continue in this order:

1. validate the terminal v7 backfill independently;
2. freeze v8, prove exact equivalence for the original 1,619 and all terminal
   v7 completions, then replay cache-only with network disabled;
3. verify the coverage delta and run/verify scaled analysis, including the
   complete-subset verdict-change bound;
4. admit and run the 37,770-variant rewards probe;
5. score and verify the cool-bias packet, with held-out/no-op first;

Item-325 work is no longer behind this queue. The `-29d` handoff explicitly
moved its build ahead when the streaming check did not clear the operational
floor, so it began without running any MM fetch or score.

The cool-bias packet is already predeclared and self-tested, but unscored:

```text
C:\Users\Michael\Documents\github\weather\scratch\workstation-research-output\cool-bias-20260729a-32316de2
```

- predeclaration:
  `96be4e89e46d0295d6223789c6d543c0dbc3081f90d53eb1ca43180ca2442f34`;
- program:
  `6d42a5f8db54e575409a7e2d2db799f91ac906f4f4a5a7d9e83923ecd0b2df4d`;
- fit dates: July 2/3/4/5/7;
- held-out dates: July 8/9/10;
- headline remains held-out/no-op first.

Because the rewards cadence alone now exceeds the remaining 03:40–08:30
window, Mission 3 needs a fresh 01:00 start even if storage is freed
immediately.
