# Maker replay Clarification 4 option — scored-run memory (DRAFT)

**Status: prospective, UNSIGNED DRAFT option for owner review. Not signed, not approved, not bound by any
authorization.** It is an alternative or addition to the separate unsigned
Clarification 4 engine-events draft (`docs/research/maker-replay-clarification-4-draft.md` on
`codex/pull-cap-precheck-20261003`, PR #166); the owner chooses the number and the text. It would add to the frozen registration, the frozen execution
addendum and Clarifications 1, 2 and 3, all of which stay unchanged. This is not an execution approval, and this draft
changes no code.

No quote-panel, settlement, wallet, calibration or replay-result data was read to write this. Every number below is
from synthetic fixtures replayed by the exam tree at `37092926`, reported in
[the replay-memory report](../roadmap/agent-report-2026-10-03-replay-memory.md).

## Problem

Clarification 2 derives the scored-run memory ceiling as the largest calibration-date rehearsal peak above baseline
× 15, rounded up to a power of two. With the host limit (70% of 16 GiB) that allows at most ~546 MiB per date. The
#166 D = 12 full-day fixture (12 bands, one capture cycle a minute, 2,000 public-trade rows) measures:

| Measured on the exam tree | Value |
| --- | ---: |
| Rehearsal peak above baseline, one date | 2,514–2,616 MiB |
| Same pipeline, 3 full days in one run | 7,607 MiB (3.03 × one day) |
| 3-hour days: 1 / 3 / 15 days in one run | 362 / 1,068 / 5,280 MiB (15 days = 14.6 × one day) |
| Lowest byte-identical peak reached by prototypes, one date, without engine changes | 1,006 MiB |
| Same, with slotted engine records (changes the exporter closure) | 777 MiB |

**The × 15 rule is not pessimistic.** Scored-run memory grows linearly with the number of dates. The engine keeps
one span per active band per heap pop and one decision per tick. The report keeps one excluded interval per uncovered
span. All three grow with days × bands × capture clocks, and the scored run replays all 15 dates in one engine pass.
At this fixture density a 15-date scored run would need about 37 GiB; real 88a selects about 120 bands, not 12. No
change to the ceiling rule makes that run fit on the 16 GB host: a larger multiplier allowance would only move the
refusal from `derive_ceilings` to the scored run's own memory guard, or to the operating system.

Byte-identical memory reductions (dropping replay results once they are scored, one clock trial alive at a time,
compact report records, streamed rendering and hashing, slotted engine records) were prototyped and measured. They
leave the per-date peak at 777 MiB at best, 1.42 × the ~546 MiB budget (report §3). Getting under it needs a pipeline whose retained state does
not grow with spans and decisions: a streaming scorer, not a smaller one.

## Measured at ~120 bands (2026-10-03, before any streaming code)

The owner approved Option A on 2026-10-02. The streaming mission measured the 88a-sized universe first and stopped
([report](../roadmap/agent-report-2026-10-03-replay-streaming.md)). At ~120 simultaneously selected bands on the same
fixture density, one full date is a lower bound of 7.5 h runtime (budget ~546 s), ~31.5 GiB of report (budget
~546 MiB) and ~596 MiB of input (budget ~546 MiB). The current code would retain ~224 GiB of memory. A byte-identical
streaming pipeline changes only memory. **Option A therefore cannot make a ~120-band panel executable on this host**,
and this draft no longer proposes signing it for that universe. It remains the right memory fix only for a universe
small enough that runtime, report and input bytes fit, for example D ≈ 12. No panel data was read.

## Option A — operational: a streaming scored pipeline, then a fresh rehearsal

- **What changes (code, operational only).** The engine hands each span and decision to incremental consumers instead
  of retaining them: per-band-day score accumulators, the per-minute pull-opportunity counts, a running SHA-256 of the
  canonical decision list, and excluded intervals written straight to the report stream. The report is rendered to its
  file in canonical chunks. Every output byte (decisions digest, scores, intervals, pull counts, report JSON and
  Markdown) must equal the current code's on fixtures, proven by byte-identity tests that run both implementations.
- **Unchanged.** Every estimand, hurdle, policy, fill bound, bootstrap, report field and byte; the ceiling rule (largest
  date × 15, next power of two) and the host limits; look protection. The rehearsal still measures the scored
  pipeline end to end, so the rule still binds the real run.
- **Cost and risk.** It changes `src/maker_core/replay/engine.py` and the scoring modules, all inside
  `execution_manifest.source_hashes()`. `engine.py`, `bundle.py`, `ceilings.py`, `payloads.py` and
  `evidence/journal.py` are also inside the panel exporter's module closure, so the exporter's module hash changes too
  and the exporter must be re-pinned with the replay tree. The change lands, is re-pinned and is rehearsed before any
  manifest is built. If the fresh rehearsal still exceeds ~546 MiB per date, Clarification 2's verdict ("not executable
  on this host") stands.

## Option B — accept the Clarification 2 verdict

Sign nothing new. Run the production calibration rehearsal as planned. If it reproduces a per-date peak above
~546 MiB, `derive_ceilings` records "not executable on this host" and the exam line stops there without consuming
the look, exactly as Clarification 2 already prescribes.

## What this option does not do

- It does not raise the 70% host memory limit, change the × 15 multiplier, or sample, truncate or split the panel.
  Splitting the panel into independent per-date runs would change the estimand, because inventory is carried to
  settlement across dates. That is not operational, and this draft does not propose it.
- It does not change any report byte. A smaller report format, for example merged excluded intervals, would change
  bytes and is not proposed here.
- It does not decide merge timing. Both the replay tree and the exporter are re-pinned under the exam-period merge
  policy.

## Owner decision required

Sign Option A (authorizing the streaming re-implementation and a fresh rehearsal), choose Option B, or amend.
Either way, the production calibration rehearsal remains the measurement that decides executability; these fixture
numbers only predict it.
