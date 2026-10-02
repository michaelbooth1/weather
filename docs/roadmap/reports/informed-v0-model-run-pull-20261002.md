# Informed-v0 model-run pull: frozen-policy check (owner item 5, 2026-10-02)

**Verdict: YES — the change alters frozen, pre-registered exam policy. NOT IMPLEMENTED. No code changed.**
The owner instruction for this case was "do not change it; report it". This report is the whole deliverable.

Owner decision 2026-10-02 (item 5): "informed_v0 pulls T+1/T+2 quotes around GFS/ECMWF availability times."

## What is frozen, and what binds it

1. **`informed_v0` is the scored candidate of the signed replay exam.**
   `docs/research/maker-replay-hurdles-preregistration-2026-09-27.md` ("Policies, fills and accounting"):
   the candidate is `informed_v0` (spelling `informed-v0`); the registered policy semantics are those of the
   harness basis, "a behavior change needs a prospective amendment, not silent use of a new branch tip"; and
   "changing a frozen policy or analysis choice requires a new registration".
   Raw-byte SHA-256 at the exam tree `6ac18be7e`:
   `0380212d8e82474281afbed1197161263f794570ec06cf51fec99a3c6c03a6bf` (= `protocol_sha256` in the
   DECISION_LOG `APPROVE_MAKER_REPLAY` rows of 2026-09-27 and in `SIGNED_BINDINGS` in
   `src/maker_core/replay/authorization.py`).
2. **The execution addendum fixes `policy = informed-v0`.**
   `docs/research/maker-replay-execution-addendum-2026-09-27.md`, SHA-256
   `074a0e56b87770eff9f574232819b5d95ecd7073e450f27adac7bf555a43410b` (`addendum_sha256`).
   `src/maker_core/replay/execution_manifest.py` `FROZEN_CONFIG = dict(policy="informed-v0", ...)`.
3. **The signed clarifications keep the same candidate.** Clarification 1
   `37d2fd8e34462a77d6209ee4018e3685bf91a81a93e2cb08df6986985811fa0e`, Clarification 2
   `1719fd1ea679cd14501d5b6ddd392fbb9e8d2b086cf6b5a3c0348961824e60f0` (signed 2026-10-01T15:23Z), Clarification 3
   `fcbcb7d0d2a38777814b6f9d5e8b96c879d069af873c0b32fb4b274506b03eaa` (signed 2026-10-01T17:44Z; its reporting
   rules are about informed-v0's quoted fraction and pull counts). Authorization `maker-replay-2026-10-15-v3`
   binds all five hashes (DECISION_LOG 2026-10-01 rows; `authorization.py` `SIGNED_BINDINGS`/`CLARIFIED_IDS`).
   All five hashes were recomputed from raw blobs at `6ac18be7e` for this report, and all match.
4. **Policy source bytes are hashed into the execution manifest.** `execution_manifest.source_hashes()`
   (exam tree) hashes every `src/maker_core/**/*.py`, every `src/weather/market/maker_plugin/**/*.py`,
   `pyproject.toml` and the four `maker_plugin_*`/`maker_replay_bundle.py` modules. The exam method row
   (DECISION_LOG 2026-10-02) says every bundle, the manifest and the look come from the pinned tree `6ac18be7e`
   plus only the reviewed `CLARIFICATION_3_SHA256` commit.
5. **The behavior the owner wants to change is the frozen behavior.** At `6ac18be7e`:
   - `src/weather/market/maker_plugin/clock.py` (SHA-256 `f91d87a1…57dd34`) emits `model_cycle` InfoEvents
     with `action_hint="widen"` at each model cycle and at cycle + 210 min (00/06/12/18Z), and at observed NBM
     fetch times. The design's "When to adjust" table says the same thing: "widen around model cycles".
   - `src/maker_core/quoting/policy.py` (SHA-256 `60171f9d…6062a8`) reads `widen`/`recentre` events as width
     inputs. Only `pull` events (scheduled prints, new highs) remove quotes.
   Pulling T+1/T+2 quotes around GFS/ECMWF availability would turn widen into pull in one or both of those
   hashed files. That changes informed-v0's decisions, its pulled-minute count, the exposure matching of the
   `clock_only` control, and the frozen pull-efficiency hurdle.
6. **The second candidate inherits it too.** `one-sided-edge-v0`
   (`docs/roadmap/workstation-handoff-2026-09-110w-one-sided-edge-profile.md`) falls back to the symmetric
   `informed-v0` decision and requires informed-v0 decisions to be byte-identical. The handoff also says
   "Do not touch ... the frozen `informed-v0` semantics."

## Why no separate variant was built either

The option of a new, default-off variant (for example `informed_v1`) was rejected for four reasons:

- Any new `.py` under `src/maker_core/` or `src/weather/market/maker_plugin/` joins the hashed source inventory
  of every manifest built from a tree that contains it.
- The exam tree's `decide()` accepts only `informed-v0` and `blind_re1` as profile names, and the replay CLI,
  engine and `authorization.POLICIES` list only the four registered policies. A new variant needs edits to
  hashed files there.
- `clock.py` and `engine.py` exist only on the exam branch, not on master. Master's `policy.py` (SHA-256
  `8c77d722…`) already differs from the exam copy. A master-side variant would therefore fork from the exam
  code and conflict when the exam branch lands.
- The exam-period merge policy (STATE_OF_PLAY) admits only disk-relief and exam-tooling merges during panel
  days 09-30..10-13.

## Facts for a future prospective registration (after the exam)

- The repo already has timing constants. `src/weather/market/info_event_calendar.py` has `nwp_release_cycles`
  (cycles 0/6/12/18 UTC, `release_delay_minutes: 210`, reason `INFO_EVENT_NWP_RELEASE`). The plugin clock uses
  +210 min. Nothing in the repo models ECMWF timing separately. ECMWF open data typically arrives about 6-8 h
  after cycle, so a single +210 min constant does not cover ECMWF. That timing would need measuring (no paid
  sources).
- Possible routes, all post-exam:
  (a) a new candidate policy name with its own pre-registration, panel and look, like `one-sided-edge-v0`;
  (b) a prospective amendment for a future informed-v0 exam.
  Neither may touch the 10-15 look.

## Per-file roll verdict

Only this report file changed (`docs/roadmap/reports/informed-v0-model-run-pull-20261002.md`): roll-free
(Markdown under `docs/`). No module imported by snapshot, CLOB, observation-trigger or CLOB-enrichment capture
loops changed. Production re-derives the verdict with `scripts\ops\roll_verdict.ps1 -Branch
codex/informed-v0-model-run-pull-20261002`.

## What was NOT done

No code change; no change to any frozen document, hash, manifest or authorization; no registration or
amendment; no production write, restart or merge; no venue call; nothing places, cancels or signs orders.

## Reproduction

```powershell
git fetch origin
git show 6ac18be7e:docs/research/maker-replay-hurdles-preregistration-2026-09-27.md   # lines 55-58, 136-142
git show 6ac18be7e:src/weather/market/maker_plugin/clock.py                           # model_cycle -> "widen"
git show 6ac18be7e:src/maker_core/replay/execution_manifest.py                        # source_hashes(), FROZEN_CONFIG
bash -c 'for f in maker-replay-hurdles-preregistration-2026-09-27 maker-replay-execution-addendum-2026-09-27 maker-replay-clarification-1-2026-09-27 maker-replay-clarification-2-2026-09-29 maker-replay-clarification-3-2026-10-01; do git cat-file blob 6ac18be7e:docs/research/$f.md | sha256sum; done'
```

Branch `codex/informed-v0-model-run-pull-20261002`, based on `origin/master` `fd274ac5`.
