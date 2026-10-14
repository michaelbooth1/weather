# N10 landing night 2026-10-14 -> 2026-10-15 (workstation summary, FINAL)

**Status: FINAL.** Built on the real post-N9 master `378256d49` (N9 FINAL `260d498cd` plus docs-only landings). The
head is `claude/integration-20261015-88a-rs-r2`. Its delta over its base has the same patch-id as the r1 head
`403c2f108` built on the simulated base (`94d7ca2f…`), so the r1 review carries over. **The r1 head `403c2f108` is
superseded; do not land it.**

The machine-readable plan is `landing-night-plan-2026-10-15-n10.json`. Its `plan_sha256` is `93aef186…69cc1`; the
file sha256 is `557cd3ff…bce2e`.

Capacity: pyup §T holds the host lease 00:30-02:00 (host block `night-plans/2026-10-15/pyup-phase-t/PHASE-T.md` on
`claude/night-plans`), so one roll-sensitive head only. 10-16 and 10-17 are no-merge nights.

| Order | Head | Sha | Class (static) | Members | Pre-gate (base 378256d49) | Journal pinned touch |
| --- | --- | --- | --- | --- | --- | --- |
| 1 (only) | `claude/integration-20261015-88a-rs-r2` | d9a4e61f6 | EXPECTED ROLL-SENSITIVE (execution-tape files in capture closures); 88a needs explicit re-adoption | #177 `codex/88a-trade-stream-coverage-20261003` 4518a49a1, which carries #173 96e226789 and #152 722b34b55 | PASS, 9816 passed / 62 skipped / 0 failed (22 chunks, 529 files) | none |

Targeted queue run on d9a4e61f6: 332 passed, 51 subtests (16 files: execution tape, maker evidence, short basetemp,
quarantine, schema registry, storage classes, agent docs audit, hygiene ratchet). `agent_docs_audit` rc 0.
`roll_verdict.ps1` on the workstation: UNDECIDABLE (no closure files); the host verdict binds.

Landing preflight (`--tests none`, bound to the plan, `preflight-n10-88a-rs.json`, report sha256 `51cdac13…3da4`, file `8e453e5e…dfd13`): routes
ROLL_SENSITIVE. The only FAIL is the correspondence-index check, which fails on master by design (closeout
regenerates it).

Master drift: if origin/master moves past `378256d49` before the night, a difference limited to `docs/*.md` or
`night-plans/` keeps this pre-gate valid; anything else needs a rebuild (`l-data/t2heads/rebuild-r2.sh`).

Integration resolution (unchanged from r1):
- `tests/conftest.py` add/add: master's quarantine hooks stay the registered `pytest_configure` (the ratchet checks
  identity); #177's short-basetemp hook becomes `pytest_configure_short_basetemp` with
  `specname="pytest_configure"`, tryfirst.
- One fix commit adds a module-docstring `Guards:` line to the 6 new test modules (master's `guards_declaration`
  hygiene ratchet postdates #177).

## Landing constraints
- 88a freeze (DL 2026-10-03 row 102, 10-07 row 137) ends after 10-14: this is the first allowed night.
- Quiet window via `quiet_window_merge.ps1`. Bounded suite starts no later than **02:45**, merge starts no later than
  **03:40**. Missing either cutoff drops the head to 10-18; nothing else lands this night.
- **Activation (88a re-adoption).** 88a (`WeatherMakerEvidenceCapture`) is a direct task, not a supervisor. After the
  recovery proof, master-agent stops the running 88a process the documented way and lets the existing PT5M task
  start it on the new code, before 04:00. **Never run `register_maker_evidence_capture.ps1`** (it writes PT1M over
  the live PT5M; open owner question). Verify: `scripts\ops\status.ps1` shows 88a capturing with a fresh
  `status.json` whose `source_sha256` for `weather.market.maker_evidence_stream` matches the head.
- The re-adoption gap (~07:40-08:00Z) falls inside UTC 10-15, the first day of the desk-study panel (DL row 90).
- 88a rows written after the merge carry the reader's receipt stamp in `captured_at_utc` for stream, trade and
  lifecycle rows. Schema version and row shapes are unchanged.

## Answered
- D1: the owner accepts the capture restart ~03:40-04:00 EDT inside the UTC 10-15 panel day (STATE_OF_PLAY critical
  path item 4, "#177 (T2, owner yes)").

## Not in this plan
- 10-18: #182 holding #172 (88a capture families), alone, with task registration of
  `WeatherMakerEvidenceLowestTemperature` as activation; regenerate `OPERATING_REFERENCE.md` and the index on the head.
- #118: owner hold (DL 2026-10-02 row 93), not before 10-30.
