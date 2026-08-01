# Workstation handoff — 2026-08-01c: rehearse past preselection, synthetically

The consolidation is exactly what I asked for and I am merging it **first** tonight — 01:15, ahead of
both the monitor and frontier branches, because its base is exactly current master and it is on the
critical path. One roll-sensitive file (`schema_registry_recent_data.py`), zero textual conflicts, both
additive auto-merges reviewed and explained, `strict-parity` correctly retired as report-only, and
3,273 passed on the combined tree. The `snapshot_store.py` overlap I predicted was stale branch
ancestry rather than real work — good catch, and it is why the roll footprint is one file instead of
two.

## Your "first blocker" is the expected gate, and everything upstream of it passed

Read your own admission list against the streak tape:

| | 07-14 | 07-15 | 07-16 | 07-17 | 07-18 | 07-19 | 07-20 | 07-21…07-29 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| preselection | ✓ | ✓ | ✓ | **skip** | ✓ | **skip** | **skip** | ✓ |
| `streak.ps1` | — | — | complete | **partial** | complete | **partial** | **partial** | complete |

**Exact agreement.** Preselection excluded 07-17, 07-19 and 07-20 as `quality:partial`, which is
precisely what both clocks say. That is now a **third independent confirmation** that the operational
streak, the release-admissibility clock and production preselection all classify the same days the
same way — measured through three different code paths.

So `ContractViolation: production preselection requires a contiguous 14-day window` is not a defect. We
have 10 contiguous days (through 07-30 on this host; your ledger is a day behind at 07-29). The 14th
contiguous day is **2026-08-03**, and on that date preselection gets its window and passes.

What you actually proved is more useful than a blocker: source materialization passes, hash-binding
works, the manifest is valid at 26,884 band rows and 2,444 captured-input identities, all 13 labels
came from the ledger with no sidecar fallback, and **the contract fails safe** — no
`preselection_lock.json`, no candidate directory, no pointer.

## But the risk I sent you to retire is still fully in place

Nothing past preselection has ever run on real evidence. Your rehearsal stopped at the one gate that
cannot open until 08-03 — so that statement is exactly as true tonight as it was yesterday, and the
lock opens only a **7-day** window.

There is no way around it with real evidence: no contiguous 14-day complete window has ever existed in
this project's history. This run is the first. So waiting for 08-03 means the entire post-preselection
path executes for the first time *inside* the window it is supposed to be de-risking.

## Mission: rehearse downstream with a synthetic prelock

A rehearsal's job is to find **code** failures, not to produce valid evidence. So build a **synthetic
prelock** and drive the whole downstream path with it: candidate fit → locked replay → PIT
qualification → promotion qualification → immutable training-graph verification → research-only
all-shadow release.

Non-negotiable framing, because this is the dangerous part:

- it is **NOT EVIDENCE** and must be incapable of being mistaken for evidence — synthetic marker in
  the artifact, a run root that cannot be confused with a real prelock path, and no possibility of it
  satisfying a later real gate;
- do **not** relax, bypass or edit any production contract to make it pass. Construct the synthetic
  input outside the contract and feed it in;
- if a stage refuses synthetic input by design, that is a finding — report it and move to the next
  stage rather than defeating the check.

What I want back is the **list of everything that breaks**, in order, with the honest classification of
each: real code defect, missing prerequisite, or artifact of the input being synthetic. A rehearsal
that surfaces six real defects is worth vastly more to me than one that runs clean.

Every failure found before 08-03 is free. Every failure found after it is paid for out of the seven
days.

## Recorded from your report

- Merge one branch, not three. Done — armed first tonight.
- `strict-parity` retired as report-only. Agreed.
- The rehearsal source is preserved as **evidence of the first failure only**, never reusable as a
  prelock. Agreed, and noted that it did not reach candidate replay so it did not mix artifacts across
  the `2026-07-31` `rows[-1]` boundary.
- Your venv is broken (removed Python 3.11 base) and this host has long paths disabled — you worked
  around both without touching repository code, which is the right call. Flag it if it starts costing
  real time.

## Priority

This is the only mission. It is the last chance to de-risk the build before the window opens.

Still deferred: MM promotion-gate relaxation, C prelock/fit/replay, cold tier, pointer creation, warm
tier, hardening branch. Disk is parked by operator decision — do not raise reclaim options.

## Guardrails

Unchanged: `data/` read-only under the deny-write ACL, outputs under one declared run root outside the
mirror, topic branches only, no PR, no merge, no master push, no promotion, no pointer change, no
serving change, no scheduler/capture/mirror/ACL change, never read or expose the sync credential.
Start from `origin/master` after tonight's three merges land.

## Handback

`docs/roadmap/agent-report-<date>-workstation-synthetic-rehearsal.md`: the ordered list of failures
with each one classified real-defect / missing-prerequisite / synthetic-artifact, then how far down the
path you got, then anything the synthetic approach could not exercise. Push before you start and again
at handback.
