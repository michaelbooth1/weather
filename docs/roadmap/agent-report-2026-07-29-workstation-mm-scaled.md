# Workstation handback — 2026-07-29: scaled MM queue stopped safely on storage

## Headline

**NOT DONE / RESUMABLE.** I pulled `origin/master` at
`32316de278614367219dd1958117c52f20f54e97`, kept the accepted scaled-MM
implementation frozen at
`c6319fa12788ab68fd83154205185ae3def695fc`, and started the commercially
important `-28c` queue first.

The fresh Gamma catalog is complete and reproduces the historical 7/9/11-band
regimes. The resumable Data API backfill reached 1,619 terminal completions
and 17 explicit validation gaps before I stopped it with 50.444 GiB free.
There are 147 valid events left. Continuing projected through the host's
50 GiB safety floor, so I did not manufacture space by deleting, compressing,
or rewriting evidence.

Mission 2 analysis, Mission 3 rewards, and the subsequently queued cool-bias
score are `NOT_RUN`. The frozen sequence forbids them before a terminal
backfill.

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
execution lacks `eventSlug`. No row was relabeled after inspection.

- Ten failures are vendor-only events on 2026-05-14 or 2026-05-21.
- Seven are local, primary, price-history events on 2026-07-09:
  Atlanta, Denver, Los Angeles, Miami, NYC, San Francisco, and Toronto.

Those seven primary gaps mean the current frozen packet cannot yield
decision-grade tier selection even after the remaining 147 events are
fetched. It can still run and disclose partial/descriptive estimates, but its
decision authority must remain null.

Recovering these events would require a new **pre-score** identity amendment,
for example admitting a missing `eventSlug` only when event-local condition,
token, side, economics, and exchange-time identity are otherwise exact and no
conflicting nonempty slug exists. I did not make that post-response policy
change.

## Why I stopped

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
37,770 reward variants, and live capture. No cleanup action is authorized by
this report.

## Resume and queue order

After a fresh quiet-window host admission:

```powershell
cd C:\Users\Michael\Documents\github\weather\scratch\workstation-research-output\mm-scaled-20260728c-v7
& 'C:\Users\Michael\Documents\github\weather\scratch\workstation-research-output\mm-scaled-20260728c\venv\Scripts\python.exe' `
  .\fetch_data_api_trades_scaled.py fetch `
  --min-request-interval-seconds 0.5
```

Then, in frozen order:

1. validate the terminal backfill independently;
2. run and verify scaled analysis;
3. admit and run the 37,770-variant rewards probe;
4. only then score the cool-bias packet.

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
