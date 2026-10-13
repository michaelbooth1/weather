# N10 landing night 2026-10-14 -> 2026-10-15 (workstation summary, DRAFT on a simulated base)

**Status: DRAFT_SIMULATED_BASE.** N9 had not landed when this plan was built. The base `7ec97bcce` (branch
`claude/t2-postn9-sim-20261013`) is origin/master `a99423120` + N9 rf-r2 `48becd401` (stacked on rs-r2 `dae4c96da`)
+ oc `051d8aa64`. After N9 lands (~04:00 10-14) the head is rebuilt on the real master as
`claude/integration-20261015-88a-rs-r2` (`l-data/t2heads/rebuild-r2.sh`), re-tested and re-pre-gated before the
10:00 10-14 heavy freeze, and this plan is regenerated with status `FINAL`. **Do not land the r1 head below.**

The machine-readable plan is `landing-night-plan-2026-10-15-n10.json`. Its `plan_sha256` is `1e0d69ad…c037b`.

Capacity: pyup section T holds the host lease 00:30-02:00, so one roll-sensitive head only. 10-16 and 10-17 are
no-merge nights.

| Order | Head | Sha | Class (static) | Members | Pre-gate (base 7ec97bcce) | Journal pinned touch |
| --- | --- | --- | --- | --- | --- | --- |
| 1 (only) | `claude/integration-20261015-88a-rs` | 403c2f108 | EXPECTED ROLL-SENSITIVE (execution-tape files in capture closures); 88a needs explicit re-adoption | #177 `codex/88a-trade-stream-coverage-20261003` 4518a49a1, which carries #173 96e226789 and #152 722b34b55 | PASS, 9816 passed / 62 skipped / 0 failed (22 chunks, 529 files) | none |

Targeted queue run on 403c2f108: 122 passed (a399ca487, before the Guards fix: 277 passed). `agent_docs_audit` rc 0.
`roll_verdict.ps1` on the workstation: UNDECIDABLE (no closure files); the host verdict binds.

Landing preflight (`--tests none`, bound to the plan, `preflight-n10-88a-rs.json`): routes ROLL_SENSITIVE. The only
FAIL is the correspondence-index check, which fails on master by design (closeout regenerates it).

Integration resolution:
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
  See open question D1.
- 88a rows written after the merge carry the reader's receipt stamp in `captured_at_utc` for stream, trade and
  lifecycle rows. Schema version and row shapes are unchanged.

## Open question
- D1: accept the 88a re-adoption gap inside UTC panel day 10-15 (recommended), or move #177 to 10-18.

## Not in this plan
- 10-18: #182 holding #172 (88a capture families), alone, with task registration of
  `WeatherMakerEvidenceLowestTemperature` as activation; regenerate `OPERATING_REFERENCE.md` and the index on the head.
- #118: owner hold (DL 2026-10-02 row 93), not before 10-30.
