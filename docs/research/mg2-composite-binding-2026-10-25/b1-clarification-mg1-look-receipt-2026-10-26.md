# Rule B-1 clarification (DRAFT): the MG-1 look receipt, 2026-10-26

- **Status:** DRAFT for master's review. Not bound until the B-1 binding commit, and dated before D0.
- **Authority:** master's R3 ruling of 2026-10-26 on the B-1 binding review, relayed by the coordinator. Master
  accepted the receipt format proposed by lane L8 and ruled that a tool writes it.
- **History only:** no outcome, label, price or market row dated after 2026-09-29 was read to write this.
- **What changes:** what "MG-1's look receipt" means in B-1 §4, §8 (VOID 5) and §9 (step 1), plus the B-1
  FILL items that MG-2 Clarification C9 §7 adds. Nothing else in B-1 changes: the estimand, the keep/kill rule,
  the markets, the dates, the interval and the other VOID conditions.

## 1. Why

- **Before this:** B-1 §9 step 1 required that "MG-1's look receipt exists", and VOID 5 compared the transfer
  time with `looked_at_utc` inside it. No tool wrote that receipt. `weather.mg1_reserved_window` registered no
  MG-1 look entry point, so the receipt would have been made by hand.
- **The risk:** VOID 5 depended on a field that nothing defined and that anyone could type.
- **The fix:** one tool writes the receipt, and B accepts only what that tool wrote.

## 2. The receipt: `mg1_look_receipt/1`

The receipt is written once, by `weather.calibration.mg1_look` running as the registered MG-1 look (§3), at
`data/mg1_look/receipt-<mg1_rule_sha256>.json`. The schema is registered in
`weather.schema_families.mg1_look`.

| Field | Meaning |
| --- | --- |
| `schema` | `mg1_look_receipt/1` |
| `entry_point` | `{module, source_sha256}`: the look module and the sha256 of its source bytes |
| `mg1_rule_sha256` | the signed MG-1 pre-registration, `b044e0f196512379d2f74a22a2a97a10cf58fdbcf5a255c4eb6a470f7f6ba665` |
| `window` | `{d0, last}`, read from `weather.mg1_reserved_window.window()` |
| `dates_scored` | `{count, first, last}` of the dates the look scored |
| `looked_at_utc` | the instant the first outcome join began, stamped by the clock (§3). Never typed |
| `completed_at_utc` | the instant the receipt was written |
| `result` | `{path, sha256}` of the look's result file |
| `mg1_py_sha256` | sha256 of `src/weather/reporting/scorecards/free_source_candidates/mg1.py` |
| `repo_commit` | `git rev-parse HEAD` when the receipt was written |
| `host` | the host name |
| `body_sha256` | sha256 of the canonical JSON (sorted keys, no spaces) of every other field |

## 3. How it is written

- **Registered entry point:** `MG1_CONFIRMATION_ENTRY_POINTS` in `weather.mg1_reserved_window` maps
  `weather.calibration.mg1_look` to the sha256 of its source bytes.
  - Any edit of the module changes that sha, so it needs a reviewed edit of the registration.
  - Until that edit, the edited module is refused like any other caller.
- **The only way to an outcome:** the look reaches outcomes only through `Look.join_outcomes`. Its first
  call does four things, in order:
  1. it refuses unless the running `__main__` is the registered module at its registered sha;
  2. it stamps `looked_at_utc` from the clock;
  3. it writes `data/mg1_look/started-<mg1_rule_sha256>.json` (`mg1_look_started/1`, mode "x");
  4. only then does it run the loader.
- **One look:** a new look for the same rule is refused once the start marker exists, even if the first look
  crashed before writing its receipt.
- **The receipt:** `Look.finish` writes the receipt in mode "x" at the fixed path. It refuses if no outcome was
  joined.
- **The rule:** the look refuses unless the MG-1 rule file hashes to the signed `b044e0f1…`.

## 4. What B checks

- **Absent:** the B look refuses before reading anything (B-1 §9 step 1, `b_scorer.look_guard`).
- **VOID 5:** `b_scorer.receipt_time_problems` runs `mg1_look.receipt_problems` first. The look is VOID 5
  unless all of these hold:
  - the schema is `mg1_look_receipt/1` and every §2 field is present;
  - `body_sha256` matches the other fields;
  - `mg1_rule_sha256` is the signed MG-1 rule;
  - `entry_point` names the registered module at its registered sha;
  - the file's bytes equal those of the receipt at the fixed path for the signed rule;
  - the transfer manifest binds the receipt's sha256 (`mg1_look_receipt_sha256`);
  - `transferred_at_utc` is after `looked_at_utc`. A file time is never used.
- **So:** a hand-made receipt, or one edited by hand, is VOID 5. That holds even when the manifest binds the
  edited bytes.

## 5. Per-checkout paths

data_path is per-checkout, so the B look runs only from the production root, and the consumed marker is copied
into the repo record and committed the same day.

- **The MG-1 files too:** the MG-1 look's start marker and receipt live under the same per-checkout `data/`.
  So the MG-1 look also runs only from the production root, and both files are copied into the repo record and
  committed the same day.
- **The residual gap:** an edit made in place at the fixed path, with `body_sha256` recomputed, is not visible
  from the receipt alone. Two things catch it:
  - the transfer manifest binds the receipt's sha256 when the transfer is made;
  - the committed copy records the receipt's bytes on the day of the look.

## 6. B-1 FILL items (from MG-2 Clarification C9 §7)

| B-1 item | Value at binding | Where it is filled |
| --- | --- | --- |
| Season-matched L6 own-model state sha256 (C9 §3) | `800072c79af65394cc33134cbaae34af65c4428feb3934e35f8cd6cd153ee2db` | §1 table, and the `b_rule_v1` line `l6_state_sha256:` (a `b_scorer.BOUND_FIELDS` entry; it must equal the `l6_state_sha256` in MG-2's `release-binding.json`, written by `mg2_composite bind-release` from the sha that `load_l6_own_state` verified) |
| Season-matched captured dev nowcast sha256 (C9 §3) | `714fa14e04c416da922803514fea1de8fe64459a0ea543878ddddfd6bc34896a` | §1 table only |

- **The state sha:** the B-1 rule block as drafted has no `l6_state_sha256:` line. At binding it gains the
  line, because the scorer refuses a block without it.
- **The dev nowcast sha:** this is the reproduction pin of MG-2's section 7 `nowcast_replay` check
  (`mg2_composite check --nowcast-pin-sha256`). B reads it only through the control receipt's
  `mg2_section7_rehearsal`.
  - It is not a `b_rule_v1` key. `b_scorer.read_rule` refuses unknown keys.
  - **For master to decide:** if this sha must also be a `b_rule_v1` key, the scorer needs a new bound field
    before binding, and its sha256 changes.
- **Rehearsal evidence (09-28, L8, re-run at `0fa6e6921`):**
  - The nowcast replay at `800072c7…` reproduced `714fa14e…` exactly (27,868 rows, serve core `179fcbe4…`).
  - `C:\t\l8wire\rh0928b\mg2_checks.json`, sha256 `0e1b9847…`, records `nowcast_replay`, `p3d_n_replay` and
    `window_leakage` as true. It is byte-identical to the first run at `2415bc050`.
  - The B control receipt `C:\t\l8wire\bcontrol3\b_control.json`, sha256
    `c67ba81a1f59fb4127145da61361fc7d5ff3bde1e9966467fcf6ff2272e9ab12`, is PASS at b_scorer `c27e710d…`.
    It supersedes `bcontrol2` (`2ce8f4a7…`), which was made at the older scorer sha `091c27cc…`.

## 7. Scope limits stated

- **No MG-1 scoring yet:** the MG-1 scoring of pre-registration §4 is not built into the entry point.
  `python -m weather.calibration.mg1_look run` refuses. Adding the scoring is a reviewed edit that changes the
  module's sha and so its registration.
- **What the receipt proves:** it shows which registered code ran the look and when its first outcome join
  began. It does not show that the MG-1 result is correct. That stays with MG-1's own void conditions.
- **The capture host:** registering the look admits it, and only it, to the MG-1 reserved dates.
  `weather.mg1_reserved_window` is imported by the item-190 NBM scorer and by `mg2_composite`. Merging it on
  the production host follows `scripts\ops\roll_verdict.ps1`.

## 8. Code

- **Branch:** `claude/mg2-l6-wiring-20261026`.
- **Writer commit:** `a0ef736567f1a74dc642d9798922ac81053dce82`. The ratchet fixes that follow it
  (`0fa6e6921a24d038e7201d577938023f97fd7e93`) do not change `b_scorer.py` or `mg1_look.py`.
- **Files:**
  - writer: `src/weather/calibration/mg1_look.py`;
  - registration: `src/weather/mg1_reserved_window.py`;
  - VOID 5: `src/weather/calibration/b_scorer.py` (`receipt_time_problems`);
  - schemas: `src/weather/schema_families/mg1_look.py`;
  - tests: `tests/calibration/test_mg1_look.py`, `tests/calibration/test_b_scorer.py` and
    `tests/reporting/test_mg1_reserved_window.py`.
- **At that commit:** `b_scorer.py` sha256 is `c27e710d4dca9b82654135283344ab870e952d785035543dd808b22947308f78`
  and `mg1_look.py` sha256 is `1e691c58b68a203aebaed3f505295971f56821e92555e3bc12ef8a4db23ff305`.
