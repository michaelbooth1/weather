# Workstation handoff — 2026-07-27h: storage pressure, build only

Your storage plan is accepted in substance. The operator has approved it with two changes to
how it runs. This supersedes the version written for the production host.

**You build. I deploy and run.** The data operations happen here because this host is the
`/MIR` source — I confirmed that: `$src = c:\Users\micha\Desktop\github\weather\data`,
destination `\\DESKTOP-RFCD2GH\weather-mirror\data`. Your side stays measurement and code.

**Do this LAST.** The operator confirmed the workstation is not critically full, and this host
has 174.6 GB free with a positive standing trend, so nothing here is time-pressured. Order:

1. `-27g` who-breaks-the-floor — the current profitability lead, and cheap.
2. Missions 3+ of `-28c` — the scaled-MM corpus, in the morning window. This is the actual
   profit question and it has been deferred repeatedly; it should not slip again.
3. This queue.

That ordering also dissolves the conflict described at the bottom: if the MM corpus work runs
before any compression exists, there is nothing for it to collide with, and it will have told
us empirically which tape representation that work needs.

## Why the original could not run as written

Four of the files it directs an agent to edit are inside the capture loops' loaded-module
closure:

| File | Mission | |
| :--- | :--- | :--- |
| `market/market_microstructure_capture.py` | 1 | **loop-loaded** |
| `operations/storage_classes.py` | 1, 2, 3 | **loop-loaded** |
| `operations/closed_market_day_archive.py` | 3 | **loop-loaded** |
| `operations/event_day_manifest.py` | 3 | **loop-loaded** |

Editing a loaded module rolls all three capture loops **the moment the file hits disk** — no
commit needed, because the supervisors fingerprint the working tree, not HEAD. The prompt's
isolation was a topic branch, which isolates history but not the filesystem. On this host that
would have rolled the fleet at 6/14 with the lock ~2026-08-03. On your host it is harmless,
which is exactly why the build belongs with you.

Verify roll-safety by parsing the three loop entrypoints (`collection/snapshot_tracker.py`,
`market/market_microstructure.py`, `operations/observation_trigger.py`) with `ast` and walking
`weather.*` imports transitively. Include a known-loaded control so an empty closure cannot
read as "safe."

## Correction to the evidence

"Repository search currently shows no live runtime consumer of `order_books_long.csv`" is not
accurate. `market/market_making_preflight.py` lists `order_books_long` and
`order_books_long_gzip` in `CLOB_RAW_BOOK_ARTIFACT_KEYS`. It is an any-of check that
`order_books_summary` also satisfies, so it plausibly survives removal — **prove that, do not
assume it.** Audit every consumer in that list of 11 files and state which are live-path,
which are archive/audit, and which are tests.

Confirmed from here: replay_cache is 309 directories, every one last written 2026-07-11 —
static for 16 days, as you said.

## The design flaw that must be fixed

The original says "do not activate the new capture behavior" while also changing
`market_microstructure_capture.py`. Those are contradictory. Once I merge that file, the loops
readopt it and the new behaviour **is** active — there is no separate deployment step to
withhold.

So Mission 1 must be built **behind a configuration flag whose default preserves today's
behaviour**, i.e. the long CSV keeps being written until the flag is turned on. Activation then
becomes a config change I can make after the lock, independently, and revert in one step if
capture misbehaves. Without that, Mission 1 cannot be merged before ~Aug 3 at all.

Same principle for anything in Missions 2 and 3 that alters what capture writes. Tooling that
only reads, compresses, or deletes closed-day artifacts does not need a flag.

## Scope

Build all three missions exactly as you specified them — dry-run defaults, reachability rather
than age or LRU, retain on ambiguity, exact manifests with path/bytes/SHA-256/identity/reason,
`cleanup_preflight`, re-verification immediately before each unlink, exact-file deletion only,
durable JSON and Markdown receipts, stop on first failure, and rebuild-one-and-prove-parity
before declaring the mechanism complete. Those are good and I am not changing them.

Additionally:

- **Do not run any apply, deletion, or compression against real data.** Dry-run against
  fixtures only. I run the production dry-run, review every selected class myself, and apply.
- Keep the replay-cache quota you proposed, and say what value you recommend and why.
- For Mission 3, the family registry must name each projection's canonical rebuild source and
  the accepted read representation, and every reader must have a `.csv.gz` fallback proven by
  test before that family is eligible.
- Leave historical long tables alone in Mission 1, as you had it.

## The conflict you need to resolve

Mission 3 compresses or removes `order_books_long.csv`. Your own scaled-MM queue reads roughly
85 GiB of **full-book tapes**, and those are the same files. If Mission 3 lands first, that read
breaks unless the reader fallback handles `.csv.gz` transparently.

State explicitly which representation the MM corpus work will consume, and make the fallback
cover it. If the honest answer is that MM needs the uncompressed form, then say so and we
sequence Mission 3 after the MM corpus work rather than discovering it mid-run.

Related: `order_books.jsonl` is canonical and holds the raw depth. If the MM work can read the
JSONL directly, the long CSV may be unnecessary for it — that would be worth knowing, because
it would make both problems easier.

## Guardrails

- `data/` read-only with proven deny-write ACL; single declared output root outside the mirror.
- No modelling, training, promotion, release, live trading, scheduler change, capture restart,
  PR, merge, or master push.
- Topic branch `codex/production-storage-pressure-2026-07-28` from freshly fetched
  `origin/master`; topic-branch push authorized.
- Never write to the mirror or `D:\weather-mirror`.
- NOT-DONE / NOT-REHEARSED first-class.

## Handback

`docs/roadmap/agent-report-<date>-workstation-storage-pressure-build.md`: the consumer audit
with live-path/archive/test classification, the roll-safety closure result for every file you
touched, the flag design and its default, the family registry with rebuild sources and reader
fallbacks, fixture dry-run receipts, the quota recommendation, and the MM-representation answer.
Push the topic branch.

I will merge in a quiet window, run the production dry-runs during the day, review the
manifests, and apply in the 01:00–04:00 window with disk measured before and after. Mission 1's
flag stays off until after the lock.

Context: master is `7068d50e`. Streak 6/14, lock ~2026-08-03. Disk here is 174.7 GB free of
930.6 GB; the standing trend was positive (~+1 GB/day reclaimed by existing tiering) until
today's chain run consumed ~15 GB. Real, worth fixing, not an emergency on this host.
